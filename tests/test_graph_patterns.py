"""Tests for graph-pattern rules."""
from gradlescope.analysis.architecture import compute_module_metrics
from gradlescope.analysis.rule import RuleContext
from gradlescope.analysis.rules import graph_patterns
from gradlescope.graph.depgraph import DependencyGraph
from gradlescope.model import Dependency, Module, Repo


def _mod(path, deps=(), types=0, abstract=0):
    return Module(
        path=path,
        directory=f"/r/{path.strip(':')}",
        dependencies=[Dependency("implementation", project_path=d) for d in deps],
        type_count=types,
        abstract_type_count=abstract,
    )


def _ctx(repo):
    g = DependencyGraph.from_repo(repo)
    return RuleContext(repo=repo, graph=g, metrics=compute_module_metrics(repo, g))


def test_isolated_module_flagged():
    repo = Repo(root="/r", modules=[_mod(":solo"), _mod(":a", deps=[":b"]), _mod(":b")])
    findings = graph_patterns.IsolatedModules().evaluate(_ctx(repo))
    assert findings and ":solo" in findings[0].evidence
    assert ":a" not in findings[0].evidence


def test_single_consumer_flagged():
    # :b used only by :a -> single consumer
    repo = Repo(root="/r", modules=[_mod(":a", deps=[":b"]), _mod(":b")])
    findings = graph_patterns.SingleConsumerModules().evaluate(_ctx(repo))
    assert findings and ":b" in findings[0].evidence


def test_no_single_consumer_when_shared():
    repo = Repo(
        root="/r",
        modules=[_mod(":a", deps=[":b"]), _mod(":c", deps=[":b"]), _mod(":b")],
    )
    # :b has fan_in 2 -> not single consumer; :a and :c have fan_in 0
    findings = graph_patterns.SingleConsumerModules().evaluate(_ctx(repo))
    assert findings == []


def test_sdp_violation_flagged():
    repo = Repo(
        root="/r",
        modules=[
            _mod(":a", deps=[":d"]),
            _mod(":c1", deps=[":a"]),
            _mod(":c2", deps=[":a"]),
            _mod(":d", deps=[":e"]),
            _mod(":e"),
        ],
    )
    findings = graph_patterns.StableDependenciesViolation().evaluate(_ctx(repo))
    assert any(f.module_path == ":a" and ":d" in (f.evidence or "") for f in findings)


def test_sdp_no_metrics_returns_empty():
    repo = Repo(root="/r", modules=[_mod(":a", deps=[":b"]), _mod(":b")])
    ctx = RuleContext(repo=repo, graph=DependencyGraph.from_repo(repo), metrics={})
    assert graph_patterns.StableDependenciesViolation().evaluate(ctx) == []
