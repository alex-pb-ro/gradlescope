"""Rules about dependency hygiene and reproducibility."""
from __future__ import annotations

from typing import List

from gradlescope.analysis.rule import Rule, RuleContext, register
from gradlescope.model import Finding, Severity
from gradlescope.scan.parser import strip_comments


@register
class NoVersionCatalog(Rule):
    id = "no-version-catalog"
    title = "No version catalog is used"
    category = "dependency-hygiene"
    default_severity = Severity.MEDIUM
    weight = 6
    runbook = "version-catalog"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        if ctx.repo.version_catalogs:
            return []
        return [
            self.make_finding(
                message="No Gradle version catalog (gradle/libs.versions.toml) was found.",
                recommendation=(
                    "Adopt a version catalog to centralize dependency and plugin "
                    "versions. This removes version drift across hundreds of modules "
                    "and is a prerequisite for clean dependency management."
                ),
            )
        ]


@register
class DynamicVersions(Rule):
    id = "dynamic-versions"
    title = "Dynamic dependency versions"
    category = "dependency-hygiene"
    default_severity = Severity.HIGH
    weight = 8
    runbook = "reproducible-dependencies"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        findings: List[Finding] = []
        for module in ctx.repo.modules:
            dynamic = [d for d in module.dependencies if d.is_dynamic]
            if dynamic:
                sample = ", ".join(sorted({d.raw for d in dynamic})[:3])
                findings.append(
                    self.make_finding(
                        module_path=module.path,
                        message=f"{len(dynamic)} dynamic version(s) declared.",
                        recommendation=(
                            "Pin exact versions (ideally via a version catalog). "
                            "Dynamic versions break reproducibility and undermine "
                            "the configuration and build caches."
                        ),
                        evidence=sample,
                    )
                )
        return findings


@register
class SnapshotVersions(Rule):
    id = "snapshot-versions"
    title = "SNAPSHOT dependency versions"
    category = "dependency-hygiene"
    default_severity = Severity.MEDIUM
    weight = 5
    runbook = "reproducible-dependencies"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        findings: List[Finding] = []
        for module in ctx.repo.modules:
            snaps = [d for d in module.dependencies if d.is_snapshot]
            if snaps:
                sample = ", ".join(sorted({d.raw for d in snaps})[:3])
                findings.append(
                    self.make_finding(
                        module_path=module.path,
                        message=f"{len(snaps)} SNAPSHOT dependency version(s) declared.",
                        recommendation="Depend on released versions to keep builds reproducible.",
                        evidence=sample,
                    )
                )
        return findings


@register
class MavenLocalUsed(Rule):
    id = "maven-local-used"
    title = "mavenLocal() repository is used"
    category = "dependency-hygiene"
    default_severity = Severity.MEDIUM
    weight = 5
    runbook = "reproducible-dependencies"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        findings: List[Finding] = []
        repo = ctx.repo
        root_text = strip_comments(
            (repo.root_build_file.text if repo.root_build_file else "") + "\n" + (repo.settings_text or "")
        )
        if "mavenLocal()" in root_text:
            findings.append(
                self.make_finding(
                    message="mavenLocal() is used in the root build or settings.",
                    recommendation=(
                        "mavenLocal() makes builds depend on machine-local state and "
                        "is non-reproducible. Prefer a hosted repository (e.g. Artifactory)."
                    ),
                )
            )
        for module in repo.modules:
            text = strip_comments(module.build_file.text) if module.build_file else ""
            if "mavenLocal()" in text:
                findings.append(
                    self.make_finding(
                        module_path=module.path,
                        message="mavenLocal() is used in this module.",
                        recommendation="Remove mavenLocal(); rely on a hosted repository instead.",
                    )
                )
        return findings
