"""Rule framework: context, base class, registry, and runner."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from gradlescope.graph.depgraph import DependencyGraph
from gradlescope.model import Finding, Repo, Severity

# Default thresholds and knobs. Every value is overridable via RuleContext.config
# so the same rule set can be tuned per organization without code changes.
DEFAULTS: Dict[str, Any] = {
    "max_graph_depth": 8,
    "max_fan_in": 20,
    "max_fan_out": 25,
    "min_gradle_major": 8,
    "cc_incompatible_plugins": [],  # heuristic, user-extensible denylist
}


@dataclass
class RuleContext:
    """Everything a rule needs to evaluate a repository."""

    repo: Repo
    graph: DependencyGraph
    config: Dict[str, Any] = field(default_factory=dict)

    def opt(self, key: str) -> Any:
        return self.config.get(key, DEFAULTS.get(key))


class Rule:
    """Base class for all rules.

    Subclasses set the class-level metadata and implement :meth:`evaluate`.
    """

    id: str = ""
    title: str = ""
    category: str = ""
    default_severity: Severity = Severity.MEDIUM
    weight: int = 5
    runbook: Optional[str] = None

    def evaluate(self, ctx: RuleContext) -> List[Finding]:  # pragma: no cover - abstract
        raise NotImplementedError

    def make_finding(
        self,
        message: str,
        recommendation: str = "",
        module_path: Optional[str] = None,
        severity: Optional[Severity] = None,
        evidence: Optional[str] = None,
    ) -> Finding:
        return Finding(
            rule_id=self.id,
            title=self.title,
            severity=severity or self.default_severity,
            category=self.category,
            message=message,
            recommendation=recommendation,
            module_path=module_path,
            weight=self.weight,
            runbook=self.runbook,
            evidence=evidence,
        )


_REGISTRY: List[Rule] = []


def register(rule_cls):
    """Class decorator that registers a single instance of the rule."""
    _REGISTRY.append(rule_cls())
    return rule_cls


def all_rules() -> List[Rule]:
    return list(_REGISTRY)


def run_rules(ctx: RuleContext, rules: Optional[List[Rule]] = None) -> List[Finding]:
    rules = rules if rules is not None else all_rules()
    findings: List[Finding] = []
    for rule in rules:
        findings.extend(rule.evaluate(ctx))
    findings.sort(key=lambda f: (-int(f.severity), f.category, f.rule_id, f.module_path or ""))
    return findings


# -- small shared helpers used by multiple rule modules --------------------- #


def prop_true(props: Dict[str, str], *keys: str) -> bool:
    for key in keys:
        if str(props.get(key, "")).strip().lower() == "true":
            return True
    return False


def prop_present(props: Dict[str, str], *keys: str) -> bool:
    return any(key in props for key in keys)


def module_build_text(repo: Repo) -> Dict[str, str]:
    """Map module path -> build-script text (empty string when absent)."""
    return {m.path: (m.build_file.text if m.build_file else "") for m in repo.modules}


JVM_PLUGIN_IDS = {
    "java",
    "java-library",
    "application",
    "groovy",
    "scala",
    "org.jetbrains.kotlin.jvm",
    "org.springframework.boot",
}
