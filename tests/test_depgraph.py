"""Tests for the dependency graph and affected-module analysis."""
import os

from gradlescope.graph import depgraph
from gradlescope.graph.depgraph import DependencyGraph
from gradlescope.model import Dependency, Module, Repo


def _mod(path, directory, deps=()):
    return Module(
        path=path,
        directory=directory,
        dependencies=[Dependency(configuration="implementation", project_path=d) for d in deps],
    )


def _chain_repo():
    # :a -> :b -> :c  (a depends on b depends on c)
    return Repo(
        root="/r",
        modules=[
            _mod(":a", "/r/a", deps=[":b"]),
            _mod(":b", "/r/b", deps=[":c"]),
            _mod(":c", "/r/c"),
        ],
    )


class TestGraphBasics:
    def test_nodes_and_edges(self):
        g = DependencyGraph.from_repo(_chain_repo())
        assert g.nodes == {":a", ":b", ":c"}
        assert g.dependencies_of(":a") == {":b"}
        assert g.dependents_of(":c") == {":b"}

    def test_fan_in_out(self):
        g = DependencyGraph.from_repo(_chain_repo())
        assert g.fan_out(":a") == 1
        assert g.fan_in(":c") == 1
        assert g.fan_in(":a") == 0

    def test_transitive_dependencies(self):
        g = DependencyGraph.from_repo(_chain_repo())
        assert g.transitive_dependencies(":a") == {":b", ":c"}

    def test_transitive_dependents(self):
        g = DependencyGraph.from_repo(_chain_repo())
        assert g.transitive_dependents(":c") == {":a", ":b"}

    def test_ignores_edges_to_unknown_modules(self):
        repo = Repo(root="/r", modules=[_mod(":a", "/r/a", deps=[":missing"])])
        g = DependencyGraph.from_repo(repo)
        assert g.dependencies_of(":a") == set()


class TestCyclesAndDepth:
    def test_is_dag_true(self):
        g = DependencyGraph.from_repo(_chain_repo())
        assert g.is_dag is True
        assert g.find_cycles() == []

    def test_cycle_detected(self):
        repo = Repo(
            root="/r",
            modules=[
                _mod(":a", "/r/a", deps=[":b"]),
                _mod(":b", "/r/b", deps=[":a"]),
            ],
        )
        g = DependencyGraph.from_repo(repo)
        assert g.is_dag is False
        cycles = g.find_cycles()
        assert len(cycles) == 1
        assert set(cycles[0]) == {":a", ":b"}

    def test_longest_chain_depth(self):
        g = DependencyGraph.from_repo(_chain_repo())
        assert g.longest_chain() == 3

    def test_longest_chain_with_cycle_terminates(self):
        repo = Repo(
            root="/r",
            modules=[
                _mod(":a", "/r/a", deps=[":b"]),
                _mod(":b", "/r/b", deps=[":a"]),
            ],
        )
        g = DependencyGraph.from_repo(repo)
        assert g.longest_chain() >= 1  # must terminate, not loop forever

    def test_empty_graph(self):
        g = DependencyGraph.from_repo(Repo(root="/r", modules=[]))
        assert g.longest_chain() == 0
        assert g.is_dag is True

    def test_metrics(self):
        g = DependencyGraph.from_repo(_chain_repo())
        m = g.metrics()
        assert m["module_count"] == 3
        assert m["edge_count"] == 2
        assert m["max_depth"] == 3
        assert m["cycle_count"] == 0
        assert m["is_dag"] is True


class TestAffected:
    def test_map_file_to_deepest_module(self):
        repo = Repo(
            root="/r",
            modules=[_mod(":core", "/r/core"), _mod(":core:utils", "/r/core/utils")],
        )
        mods, is_global = depgraph.map_files_to_modules(
            repo, ["core/utils/src/main/java/A.java"]
        )
        assert mods == {":core:utils"}
        assert is_global is False

    def test_global_file_marks_all(self):
        repo = _chain_repo()
        mods, is_global = depgraph.map_files_to_modules(repo, ["settings.gradle"])
        assert is_global is True

    def test_buildsrc_is_global(self):
        repo = _chain_repo()
        _, is_global = depgraph.map_files_to_modules(repo, ["buildSrc/src/main/kotlin/X.kt"])
        assert is_global is True

    def test_affected_includes_dependents(self):
        repo = _chain_repo()
        g = DependencyGraph.from_repo(repo)
        affected = depgraph.affected_modules(repo, g, ["c/src/main/java/C.java"])
        assert set(affected) == {":a", ":b", ":c"}

    def test_affected_leaf_change_is_local(self):
        repo = _chain_repo()
        g = DependencyGraph.from_repo(repo)
        affected = depgraph.affected_modules(repo, g, ["a/src/main/java/A.java"])
        assert set(affected) == {":a"}

    def test_affected_global_change_is_everything(self):
        repo = _chain_repo()
        g = DependencyGraph.from_repo(repo)
        affected = depgraph.affected_modules(repo, g, ["gradle.properties"])
        assert set(affected) == {":a", ":b", ":c"}

    def test_unmapped_file_affects_nothing(self):
        repo = _chain_repo()
        g = DependencyGraph.from_repo(repo)
        affected = depgraph.affected_modules(repo, g, ["docs/README.md"])
        assert set(affected) == set()
