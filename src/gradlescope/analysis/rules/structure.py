"""Rules about build structure, the dependency graph, toolchains, portability."""
from __future__ import annotations

import re
from typing import List

from gradlescope.analysis.rule import JVM_PLUGIN_IDS, Rule, RuleContext, register
from gradlescope.model import Finding, Severity
from gradlescope.scan.parser import extract_blocks, strip_comments

_ALLPROJECTS_RE = re.compile(r"\b(allprojects|subprojects)\s*\{")
# Matches both Groovy `apply from: '...'` and Kotlin `apply(from = "...")`.
_APPLY_FROM_RE = re.compile(r"\bapply\s*\(?\s*from\b")
_TOOLCHAIN_MARKERS = ("toolchain", "jvmToolchain", "sourceCompatibility", "JavaLanguageVersion")


@register
class CrossProjectConfiguration(Rule):
    id = "cross-project-configuration"
    title = "Cross-project configuration (allprojects/subprojects)"
    category = "modularity"
    default_severity = Severity.HIGH
    weight = 9
    runbook = "convention-plugins"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        raw = ctx.repo.root_build_file.text if ctx.repo.root_build_file else ""
        text = strip_comments(raw)
        matches = sorted({m.group(1) for m in _ALLPROJECTS_RE.finditer(text)})
        if not matches:
            return []
        return [
            self.make_finding(
                message=f"Root build uses cross-project configuration: {', '.join(matches)}.",
                recommendation=(
                    "Replace allprojects/subprojects blocks with convention plugins "
                    "(buildSrc or build-logic). Cross-project configuration blocks "
                    "Isolated Projects and makes the graph hard to reason about."
                ),
                evidence=", ".join(matches),
            )
        ]


@register
class ApplyFromScriptPlugin(Rule):
    id = "apply-from-script-plugin"
    title = "Legacy script plugins via apply from"
    category = "portability"
    default_severity = Severity.LOW
    weight = 4
    runbook = "convention-plugins"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        findings: List[Finding] = []
        repo = ctx.repo
        if repo.root_build_file and _APPLY_FROM_RE.search(strip_comments(repo.root_build_file.text)):
            findings.append(
                self.make_finding(
                    message="Root build applies a script plugin via 'apply from'.",
                    recommendation="Convert script plugins to convention plugins for cacheability and portability.",
                )
            )
        for module in repo.modules:
            text = strip_comments(module.build_file.text) if module.build_file else ""
            if _APPLY_FROM_RE.search(text):
                findings.append(
                    self.make_finding(
                        module_path=module.path,
                        message="Module applies a script plugin via 'apply from'.",
                        recommendation="Convert to a convention plugin.",
                    )
                )
        return findings


@register
class DependencyCycles(Rule):
    id = "dependency-cycles"
    title = "Module dependency cycles"
    category = "dependency-graph"
    default_severity = Severity.HIGH
    weight = 10
    runbook = "untangle-dependency-graph"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        cycles = ctx.graph.find_cycles()
        if not cycles:
            return []
        sample = " -> ".join(cycles[0])
        return [
            self.make_finding(
                message=f"{len(cycles)} dependency cycle(s) between modules detected.",
                recommendation=(
                    "Break cycles by extracting shared code into a lower-level module "
                    "or inverting a dependency. Cycles prevent correct incremental and "
                    "affected-only builds and block a future Bazel migration."
                ),
                evidence=sample,
            )
        ]


@register
class ExcessiveGraphDepth(Rule):
    id = "excessive-graph-depth"
    title = "Dependency graph is very deep"
    category = "dependency-graph"
    default_severity = Severity.MEDIUM
    weight = 5
    runbook = "untangle-dependency-graph"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        depth = ctx.graph.longest_chain()
        limit = ctx.opt("max_graph_depth")
        if depth <= limit:
            return []
        return [
            self.make_finding(
                message=f"Longest dependency chain is {depth} modules (limit {limit}).",
                recommendation=(
                    "Flatten deep chains. Deep graphs serialize the build and reduce "
                    "the benefit of parallel and affected-only execution."
                ),
                evidence=f"depth={depth}",
            )
        ]


@register
class HighFanInHub(Rule):
    id = "high-fan-in-hub"
    title = "Hub module with very high fan-in"
    category = "dependency-graph"
    default_severity = Severity.MEDIUM
    weight = 5
    runbook = "untangle-dependency-graph"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        findings: List[Finding] = []
        limit = ctx.opt("max_fan_in")
        for path in ctx.graph.nodes:
            fan_in = ctx.graph.fan_in(path)
            if fan_in > limit:
                findings.append(
                    self.make_finding(
                        module_path=path,
                        message=f"{fan_in} modules depend on this one (limit {limit}).",
                        recommendation=(
                            "Hub modules force wide rebuilds: any change here marks a "
                            "huge fraction of the repo as affected. Split it into "
                            "narrower API modules consumers can depend on selectively."
                        ),
                        evidence=f"fan_in={fan_in}",
                    )
                )
        return findings


@register
class HighFanOut(Rule):
    id = "high-fan-out"
    title = "Module with very high fan-out"
    category = "modularity"
    default_severity = Severity.LOW
    weight = 3
    runbook = "untangle-dependency-graph"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        findings: List[Finding] = []
        limit = ctx.opt("max_fan_out")
        for path in ctx.graph.nodes:
            fan_out = ctx.graph.fan_out(path)
            if fan_out > limit:
                findings.append(
                    self.make_finding(
                        module_path=path,
                        message=f"This module depends on {fan_out} modules (limit {limit}).",
                        recommendation="High fan-out suggests low cohesion; consider splitting responsibilities.",
                        evidence=f"fan_out={fan_out}",
                    )
                )
        return findings


@register
class OutdatedGradle(Rule):
    id = "outdated-gradle"
    title = "Gradle version is outdated or unknown"
    category = "maintainability"
    default_severity = Severity.MEDIUM
    weight = 5
    runbook = "configuration-cache"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        version = ctx.repo.gradle_version
        min_major = ctx.opt("min_gradle_major")
        if version is None:
            return [
                self.make_finding(
                    severity=Severity.LOW,
                    message="Gradle wrapper version could not be determined.",
                    recommendation="Commit a Gradle wrapper and keep it current.",
                )
            ]
        try:
            major = int(version.split(".")[0])
        except ValueError:  # pragma: no cover - defensive
            return []
        if major >= min_major:
            return []
        return [
            self.make_finding(
                message=f"Gradle {version} is older than {min_major}.x.",
                recommendation=(
                    "Upgrade Gradle. Recent versions are required for a stable "
                    "configuration cache and Isolated Projects."
                ),
                evidence=version,
            )
        ]


@register
class MissingJavaToolchain(Rule):
    id = "missing-java-toolchain"
    title = "JVM module without a Java toolchain"
    category = "toolchains"
    default_severity = Severity.MEDIUM
    weight = 5
    runbook = "java-toolchains"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        repo = ctx.repo
        root_text = repo.root_build_file.text if repo.root_build_file else ""
        # Treat as covered only if a toolchain marker appears *inside* an
        # allprojects/subprojects block (so it actually applies to subprojects).
        cross_blocks = extract_blocks(root_text, "allprojects") + extract_blocks(root_text, "subprojects")
        global_toolchain = any(
            any(marker in block for marker in _TOOLCHAIN_MARKERS) for block in cross_blocks
        )
        if global_toolchain:
            return []

        findings: List[Finding] = []
        for module in repo.modules:
            plugin_ids = {p.id for p in module.plugins}
            if not (plugin_ids & JVM_PLUGIN_IDS):
                continue
            text = strip_comments(module.build_file.text) if module.build_file else ""
            if any(marker in text for marker in _TOOLCHAIN_MARKERS):
                continue
            findings.append(
                self.make_finding(
                    module_path=module.path,
                    message="JVM module does not declare a Java toolchain.",
                    recommendation=(
                        "Declare a Java toolchain (java { toolchain { languageVersion "
                        "= JavaLanguageVersion.of(N) } }). Toolchains let modules pin "
                        "different Java versions reproducibly and independently of the "
                        "machine JDK."
                    ),
                )
            )
        return findings
