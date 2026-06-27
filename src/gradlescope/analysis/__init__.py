"""Analysis: rule framework plus the built-in rule set.

Importing this package registers all built-in rules.
"""
from typing import Dict, List, Optional

from gradlescope.analysis import rules as _rules  # noqa: F401  (registers rules)
from gradlescope.analysis.rule import (  # noqa: F401
    DEFAULTS,
    Rule,
    RuleContext,
    all_rules,
    run_rules,
)
from gradlescope.graph.depgraph import DependencyGraph
from gradlescope.model import Finding, Repo


def analyze(repo: Repo, config: Optional[Dict] = None) -> List[Finding]:
    """Scan-to-findings convenience: build the graph and run every rule."""
    graph = DependencyGraph.from_repo(repo)
    ctx = RuleContext(repo=repo, graph=graph, config=config or {})
    return run_rules(ctx)
