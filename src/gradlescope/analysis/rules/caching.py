"""Rules about Gradle caching, parallelism, and configuration/isolated state."""
from __future__ import annotations

from typing import List

from gradlescope.analysis.rule import Rule, RuleContext, prop_true, register
from gradlescope.model import Finding, Severity


@register
class ConfigurationCacheDisabled(Rule):
    id = "config-cache-disabled"
    title = "Configuration cache is not enabled"
    category = "configuration-cache"
    default_severity = Severity.HIGH
    weight = 10
    runbook = "configuration-cache"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        props = ctx.repo.gradle_properties
        if prop_true(props, "org.gradle.configuration-cache", "org.gradle.unsafe.configuration-cache"):
            return []
        return [
            self.make_finding(
                message="The configuration cache is not enabled in gradle.properties.",
                recommendation=(
                    "Once the build is compatible, set "
                    "org.gradle.configuration-cache=true to skip the configuration "
                    "phase on subsequent builds."
                ),
            )
        ]


@register
class BuildCacheDisabled(Rule):
    id = "build-cache-disabled"
    title = "Build cache is not enabled"
    category = "build-cache"
    default_severity = Severity.HIGH
    weight = 10
    runbook = "build-cache"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        if prop_true(ctx.repo.gradle_properties, "org.gradle.caching"):
            return []
        return [
            self.make_finding(
                message="The build cache is not enabled in gradle.properties.",
                recommendation="Set org.gradle.caching=true to reuse task outputs locally.",
            )
        ]


@register
class ParallelExecutionDisabled(Rule):
    id = "parallel-disabled"
    title = "Parallel execution is not enabled"
    category = "parallelism"
    default_severity = Severity.MEDIUM
    weight = 6
    runbook = "parallel-execution"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        if prop_true(ctx.repo.gradle_properties, "org.gradle.parallel"):
            return []
        return [
            self.make_finding(
                message="Parallel project execution is not enabled.",
                recommendation=(
                    "Set org.gradle.parallel=true so independent modules build "
                    "concurrently — especially valuable in a large monorepo."
                ),
            )
        ]


@register
class IsolatedProjectsNotEnabled(Rule):
    id = "isolated-projects-disabled"
    title = "Isolated Projects is not enabled"
    category = "configuration-cache"
    default_severity = Severity.LOW
    weight = 4
    runbook = "isolated-projects"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        if prop_true(
            ctx.repo.gradle_properties,
            "org.gradle.unsafe.isolated-projects",
            "org.gradle.isolated-projects",
        ):
            return []
        return [
            self.make_finding(
                message="Isolated Projects is not enabled.",
                recommendation=(
                    "Isolated Projects extends the configuration cache by isolating "
                    "each project's model, unlocking parallel configuration. Adopt it "
                    "after removing cross-project configuration (allprojects/subprojects)."
                ),
            )
        ]


@register
class ConfigCacheIncompatiblePlugin(Rule):
    id = "config-cache-incompatible-plugin"
    title = "Configuration-cache-incompatible plugin"
    category = "configuration-cache"
    default_severity = Severity.HIGH
    weight = 8
    runbook = "configuration-cache"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        # User-extensible denylist (defaults to empty so we never ship guesses).
        denylist = set(ctx.opt("cc_incompatible_plugins") or [])
        if not denylist:
            return []
        findings: List[Finding] = []
        for module in ctx.repo.modules:
            bad = sorted({p.id for p in module.plugins if p.id in denylist})
            if bad:
                findings.append(
                    self.make_finding(
                        module_path=module.path,
                        message=f"Uses plugin(s) flagged as configuration-cache incompatible: {', '.join(bad)}.",
                        recommendation=(
                            "Upgrade to a configuration-cache-compatible version of the "
                            "plugin, or replace/isolate it. Configure the denylist via "
                            "the 'cc_incompatible_plugins' option."
                        ),
                        evidence=", ".join(bad),
                    )
                )
        return findings


@register
class RemoteBuildCacheMissing(Rule):
    id = "remote-build-cache-missing"
    title = "No remote build cache is configured"
    category = "build-cache"
    default_severity = Severity.MEDIUM
    weight = 6
    runbook = "remote-build-cache"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        settings = ctx.repo.settings_text or ""
        has_remote = "HttpBuildCache" in settings or "remote(" in settings
        if has_remote:
            return []
        return [
            self.make_finding(
                message="No remote build cache backend is configured in settings.",
                recommendation=(
                    "You do not need Develocity for a remote cache. Configure an "
                    "HttpBuildCache pointing at Artifactory (generic repo), an S3/GCS "
                    "gateway, or the open-source gradle-remote-cache-node so CI and "
                    "developers share task outputs."
                ),
            )
        ]
