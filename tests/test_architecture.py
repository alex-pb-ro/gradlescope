"""Tests for Clean Architecture component metrics."""
from gradlescope.analysis.architecture import (
    architecture_summary,
    compute_module_metrics,
    scatter_points,
    sdp_violations,
)
from gradlescope.graph.depgraph import DependencyGraph
from gradlescope.model import Dependency, Module, Repo


def _mod(path, deps=(), types=0, abstract=0):
    return Module(
        path=path,
        directory=f"/r/{path.strip(':').replace(':', '/')}",
        dependencies=[Dependency("implementation", project_path=d) for d in deps],
        type_count=types,
        abstract_type_count=abstract,
    )


def _metrics(repo):
    return compute_module_metrics(repo, DependencyGraph.from_repo(repo))


class TestMetrics:
    def test_instability(self):
        # :app -> :core ; app: Ce=1 Ca=0 -> I=1 ; core: Ce=0 Ca=1 -> I=0
        repo = Repo(root="/r", modules=[_mod(":app", deps=[":core"]), _mod(":core")])
        m = _metrics(repo)
        assert m[":app"].ce == 1 and m[":app"].ca == 0
        assert m[":app"].instability == 1.0
        assert m[":core"].instability == 0.0

    def test_isolated_module_instability_zero(self):
        repo = Repo(root="/r", modules=[_mod(":solo")])
        m = _metrics(repo)
        assert m[":solo"].instability == 0.0
        assert m[":solo"].has_coupling is False

    def test_abstractness(self):
        repo = Repo(root="/r", modules=[_mod(":a", types=4, abstract=1)])
        assert _metrics(repo)[":a"].abstractness == 0.25

    def test_abstractness_zero_when_no_types(self):
        repo = Repo(root="/r", modules=[_mod(":a")])
        assert _metrics(repo)[":a"].abstractness == 0.0

    def test_distance_on_main_sequence(self):
        # A=0, I=1 -> D = |0 + 1 - 1| = 0  (perfect)
        repo = Repo(root="/r", modules=[_mod(":app", deps=[":core"]), _mod(":core")])
        assert _metrics(repo)[":app"].distance == 0.0

    def test_zone_of_pain(self):
        # stable (I=0) + concrete (A=0) -> zone of pain. :core depended on by :app.
        repo = Repo(root="/r", modules=[_mod(":app", deps=[":core"]), _mod(":core", types=10, abstract=0)])
        assert _metrics(repo)[":core"].zone == "zone-of-pain"


class TestSdp:
    def test_violation_detected(self):
        # :stable -> :unstable  where unstable is less stable -> violation
        repo = Repo(
            root="/r",
            modules=[
                _mod(":stable", deps=[":unstable"]),  # but we need stable to have low I...
                _mod(":unstable", deps=[":x"]),
                _mod(":x"),
            ],
        )
        graph = DependencyGraph.from_repo(repo)
        m = compute_module_metrics(repo, graph)
        # :stable: Ce=1,Ca=0 -> I=1 (very unstable actually). Construct a real violation instead:
        # Build: :a depends on :b and :c depend on :a (so :a has Ca=2, Ce=1 -> I=0.33),
        # :b has Ca=1, Ce=0 -> I=0. a->b is fine (b more stable). Make a->d where d is unstable.
        repo2 = Repo(
            root="/r",
            modules=[
                _mod(":a", deps=[":d"]),
                _mod(":c1", deps=[":a"]),
                _mod(":c2", deps=[":a"]),
                _mod(":d", deps=[":e"]),  # d: Ce=1, Ca=1 -> I=0.5
                _mod(":e"),
            ],
        )
        g2 = DependencyGraph.from_repo(repo2)
        m2 = compute_module_metrics(repo2, g2)
        # :a I = Ce1/(Ca2+Ce1)=0.333 ; :d I = 0.5 -> a depends on less-stable d -> violation
        viols = sdp_violations(g2, m2)
        assert any(a == ":a" and b == ":d" for a, b, _ in viols)

    def test_no_violation_when_depending_on_more_stable(self):
        repo = Repo(root="/r", modules=[_mod(":app", deps=[":core"]), _mod(":core")])
        g = DependencyGraph.from_repo(repo)
        assert sdp_violations(g, compute_module_metrics(repo, g)) == []


class TestSummaryAndScatter:
    def test_summary(self):
        repo = Repo(root="/r", modules=[_mod(":app", deps=[":core"]), _mod(":core", types=10, abstract=0)])
        s = architecture_summary(_metrics(repo))
        assert "avg_distance" in s and "zones" in s
        assert s["scored_modules"] == 2

    def test_scatter_points(self):
        repo = Repo(root="/r", modules=[_mod(":app", deps=[":core"]), _mod(":core")])
        pts = scatter_points(_metrics(repo))
        assert len(pts) == 2
        for label, x, y, color in pts:
            assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
            assert color.startswith("#")
