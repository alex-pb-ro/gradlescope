"""Tests for the server-side graph layout."""
from gradlescope.dashboard.graphview import compute_layout, render_graph_section
from gradlescope.graph.depgraph import DependencyGraph
from gradlescope.model import Dependency, Module, Repo
from gradlescope.result import build_result


def _graph(edges, nodes):
    repo = Repo(
        root="/r",
        modules=[
            Module(
                path=n,
                directory=f"/r/{n.strip(':')}",
                dependencies=[Dependency("implementation", project_path=t) for (s, t) in edges if s == n],
            )
            for n in nodes
        ],
    )
    return DependencyGraph.from_repo(repo)


class TestLayout:
    def test_chain_layers(self):
        # :a -> :b -> :c : c is foundational (layer 0), a is deepest (layer 2)
        g = _graph([(":a", ":b"), (":b", ":c")], [":a", ":b", ":c"])
        layout = compute_layout(g)
        by_id = {n["id"]: n for n in layout["nodes"]}
        assert by_id[":c"]["layer"] == 0
        assert by_id[":a"]["layer"] == 2
        assert layout["layer_count"] == 3
        assert len(layout["edges"]) == 2

    def test_node_has_fanio(self):
        g = _graph([(":a", ":b")], [":a", ":b"])
        by_id = {n["id"]: n for n in compute_layout(g)["nodes"]}
        assert by_id[":b"]["fi"] == 1 and by_id[":a"]["fo"] == 1

    def test_handles_cycle_without_hanging(self):
        g = _graph([(":a", ":b"), (":b", ":a")], [":a", ":b"])
        layout = compute_layout(g)
        assert len(layout["nodes"]) == 2

    def test_empty(self):
        layout = compute_layout(DependencyGraph(set(), {}))
        assert layout["nodes"] == [] and layout["edges"] == []


def test_render_graph_section_embeds_canvas_and_data():
    repo = Repo(
        root="/r",
        modules=[
            Module(path=":a", directory="/r/a", dependencies=[Dependency("implementation", project_path=":b")]),
            Module(path=":b", directory="/r/b"),
        ],
    )
    result = build_result(repo, generated_at="t")
    html = render_graph_section(result)
    assert "gv-canvas" in html
    assert "<script>" in html
    assert '"nodes"' in html  # embedded layout JSON
    assert "gv-search" in html
    # embedded JSON escapes '<' so a value cannot break out of the <script> tag
    assert "\\u003c" in html or "<" not in html.split("var GD =")[1].split(";")[0]
    # hover dimming uses a precomputed neighbour set (not the old O(N*deg) scan)
    assert "isNeighbor(" not in html
