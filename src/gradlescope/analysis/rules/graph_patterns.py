"""Rules detecting structural graph patterns and architecture smells."""
from __future__ import annotations

from typing import List

from gradlescope.analysis.architecture import sdp_violations
from gradlescope.analysis.rule import Rule, RuleContext, register
from gradlescope.model import Finding, Severity


def _examples(items, n=8):
    items = list(items)
    shown = ", ".join(items[:n])
    if len(items) > n:
        shown += f", … (+{len(items) - n} more)"
    return shown


@register
class StableDependenciesViolation(Rule):
    id = "sdp-violation"
    title = "Stable Dependencies Principle violation"
    category = "dependency-graph"
    default_severity = Severity.MEDIUM
    weight = 4
    runbook = "untangle-dependency-graph"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        if not ctx.metrics:
            return []
        violations = sdp_violations(ctx.graph, ctx.metrics)
        if not violations:
            return []
        by_src: dict = {}
        for src, tgt, delta in violations:
            by_src.setdefault(src, []).append((tgt, delta))
        findings: List[Finding] = []
        for src, targets in by_src.items():
            targets.sort(key=lambda t: -t[1])
            names = [t[0] for t in targets]
            findings.append(
                self.make_finding(
                    module_path=src,
                    message=f"Depends on {len(names)} less-stable module(s) (violates the Stable Dependencies Principle).",
                    recommendation=(
                        "Depend in the direction of stability: depend on modules that are "
                        "more stable (lower instability) than this one, or invert the "
                        "dependency via an abstraction this module owns."
                    ),
                    evidence=_examples(names),
                )
            )
        return findings


@register
class IsolatedModules(Rule):
    id = "isolated-module"
    title = "Isolated module (no dependencies in or out)"
    category = "modularity"
    default_severity = Severity.LOW
    weight = 2
    runbook = "untangle-dependency-graph"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        isolated = [
            n
            for n in ctx.graph.nodes
            if n != ":" and ctx.graph.fan_in(n) == 0 and ctx.graph.fan_out(n) == 0
        ]
        if not isolated:
            return []
        return [
            self.make_finding(
                message=f"{len(isolated)} module(s) have no module dependencies in or out.",
                recommendation=(
                    "Isolated modules are either unused, entry points (apps), or wired "
                    "only outside Gradle. Verify each is intentional; remove dead ones."
                ),
                evidence=_examples(sorted(isolated)),
            )
        ]


@register
class SingleConsumerModules(Rule):
    id = "single-consumer-module"
    title = "Module used by exactly one other module"
    category = "modularity"
    default_severity = Severity.INFO
    weight = 1
    runbook = "untangle-dependency-graph"

    def evaluate(self, ctx: RuleContext) -> List[Finding]:
        singles = sorted(n for n in ctx.graph.nodes if ctx.graph.fan_in(n) == 1)
        if not singles:
            return []
        return [
            self.make_finding(
                message=f"{len(singles)} module(s) are used by exactly one other module.",
                recommendation=(
                    "Single-consumer modules are candidates for inlining into their sole "
                    "consumer (fewer modules = faster configuration), unless the split "
                    "exists for build-avoidance or ownership reasons."
                ),
                evidence=_examples(singles),
            )
        ]
