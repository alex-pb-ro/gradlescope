"""The central analysis pipeline and its serializable result.

``build_result`` runs the whole pipeline (graph + rules + scoring) over a
scanned :class:`Repo` and returns an :class:`AnalysisResult` that every
consumer (JSON/Markdown/AI reports, dashboard, server) reads from.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from gradlescope import __version__
from gradlescope.analysis.rule import RuleContext, run_rules
from gradlescope.analysis.scoring import Scorecard, compute_scorecard
from gradlescope.graph.depgraph import DependencyGraph
from gradlescope.model import Finding, Repo


@dataclass
class AnalysisResult:
    root: str
    summary: Dict
    graph: Dict
    scorecard: Scorecard
    findings: List[Finding]
    generated_at: Optional[str] = None
    version: str = __version__
    config: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "tool": "gradlescope",
            "version": self.version,
            "generated_at": self.generated_at,
            "root": self.root,
            "summary": self.summary,
            "graph": self.graph,
            "score": self.scorecard.to_dict(),
            "findings": [f.to_dict() for f in self.findings],
        }


def _summarize(repo: Repo) -> Dict:
    language_counts: Counter = Counter()
    plugin_counts: Counter = Counter()
    for module in repo.modules:
        for lang in module.languages:
            language_counts[lang] += 1
        for plugin in module.plugins:
            plugin_counts[plugin.id] += 1
    return {
        "module_count": repo.module_count,
        "gradle_version": repo.gradle_version,
        "has_version_catalog": bool(repo.version_catalogs),
        "languages": dict(sorted(language_counts.items())),
        "plugin_usage": dict(plugin_counts.most_common()),
    }


def build_result(
    repo: Repo,
    config: Optional[Dict] = None,
    generated_at: Optional[str] = None,
    version: str = __version__,
) -> AnalysisResult:
    config = config or {}
    graph = DependencyGraph.from_repo(repo)
    ctx = RuleContext(repo=repo, graph=graph, config=config)
    findings: List[Finding] = run_rules(ctx)
    scorecard = compute_scorecard(findings, repo=repo, config=config)
    return AnalysisResult(
        root=repo.root,
        summary=_summarize(repo),
        graph=graph.metrics(),
        scorecard=scorecard,
        findings=findings,
        generated_at=generated_at,
        version=version,
        config=config,
    )
