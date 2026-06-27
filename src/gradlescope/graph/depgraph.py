"""Inter-module dependency graph and affected-module computation.

The graph models project (module) dependencies only. Edge ``A -> B`` means
"module A depends on module B". "Affected" analysis answers: given a set of
changed files, which modules must be rebuilt/retested? That is the changed
modules plus everything that (transitively) depends on them.
"""
from __future__ import annotations

import os
from typing import Dict, List, Set, Tuple

from gradlescope.model import Repo

_GLOBAL_EXACT = {
    "settings.gradle",
    "settings.gradle.kts",
    "gradle.properties",
    "build.gradle",
    "build.gradle.kts",
}
_GLOBAL_PREFIXES = ("gradle/", "buildSrc/", "build-logic/")


class DependencyGraph:
    """A directed graph of module-to-module dependencies."""

    def __init__(self, nodes: Set[str], edges: Dict[str, Set[str]]):
        self.nodes: Set[str] = set(nodes)
        self._out: Dict[str, Set[str]] = {n: set(edges.get(n, set())) for n in self.nodes}
        self._in: Dict[str, Set[str]] = {n: set() for n in self.nodes}
        for src, targets in self._out.items():
            for tgt in targets:
                self._in[tgt].add(src)

    # -- construction ----------------------------------------------------- #
    @classmethod
    def from_repo(cls, repo: Repo) -> "DependencyGraph":
        nodes = {m.path for m in repo.modules}
        edges: Dict[str, Set[str]] = {}
        for module in repo.modules:
            targets = {
                dep.project_path
                for dep in module.project_dependencies
                if dep.project_path in nodes and dep.project_path != module.path
            }
            edges[module.path] = targets
        return cls(nodes, edges)

    # -- direct relationships --------------------------------------------- #
    def dependencies_of(self, path: str) -> Set[str]:
        return set(self._out.get(path, set()))

    def dependents_of(self, path: str) -> Set[str]:
        return set(self._in.get(path, set()))

    def fan_out(self, path: str) -> int:
        return len(self._out.get(path, set()))

    def fan_in(self, path: str) -> int:
        return len(self._in.get(path, set()))

    # -- transitive closures (iterative BFS) ------------------------------ #
    def _closure(self, start: str, adjacency: Dict[str, Set[str]]) -> Set[str]:
        seen: Set[str] = set()
        stack = list(adjacency.get(start, set()))
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(adjacency.get(node, set()) - seen)
        seen.discard(start)
        return seen

    def transitive_dependencies(self, path: str) -> Set[str]:
        return self._closure(path, self._out)

    def transitive_dependents(self, path: str) -> Set[str]:
        return self._closure(path, self._in)

    # -- cycles (iterative Tarjan SCC) ------------------------------------ #
    def find_cycles(self) -> List[List[str]]:
        index_counter = [0]
        index: Dict[str, int] = {}
        lowlink: Dict[str, int] = {}
        on_stack: Dict[str, bool] = {}
        stack: List[str] = []
        result: List[List[str]] = []

        for root in sorted(self.nodes):
            if root in index:
                continue
            work = [(root, iter(sorted(self._out.get(root, set()))))]
            index[root] = lowlink[root] = index_counter[0]
            index_counter[0] += 1
            stack.append(root)
            on_stack[root] = True
            while work:
                node, it = work[-1]
                descended = False
                for succ in it:
                    if succ not in index:
                        index[succ] = lowlink[succ] = index_counter[0]
                        index_counter[0] += 1
                        stack.append(succ)
                        on_stack[succ] = True
                        work.append((succ, iter(sorted(self._out.get(succ, set())))))
                        descended = True
                        break
                    if on_stack.get(succ):
                        lowlink[node] = min(lowlink[node], index[succ])
                if descended:
                    continue
                if lowlink[node] == index[node]:
                    component: List[str] = []
                    while True:
                        w = stack.pop()
                        on_stack[w] = False
                        component.append(w)
                        if w == node:
                            break
                    is_self_loop = node in self._out.get(node, set())
                    if len(component) > 1 or is_self_loop:
                        result.append(sorted(component))
                work.pop()
                if work:
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])
        return result

    @property
    def is_dag(self) -> bool:
        return not self.find_cycles()

    # -- longest dependency chain (handles cycles gracefully) ------------- #
    def longest_chain(self) -> int:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in self.nodes}
        depth: Dict[str, int] = {}
        for start in sorted(self.nodes):
            if color[start] != WHITE:
                continue
            stack = [(start, iter(sorted(self._out.get(start, set()))))]
            color[start] = GRAY
            while stack:
                node, it = stack[-1]
                advanced = False
                for nb in it:
                    if color[nb] == WHITE:
                        color[nb] = GRAY
                        stack.append((nb, iter(sorted(self._out.get(nb, set())))))
                        advanced = True
                        break
                if advanced:
                    continue
                best = 1
                for nb in self._out.get(node, set()):
                    if color[nb] == BLACK:
                        best = max(best, 1 + depth[nb])
                depth[node] = best
                color[node] = BLACK
                stack.pop()
        return max(depth.values()) if depth else 0

    # -- summary ---------------------------------------------------------- #
    def metrics(self) -> Dict[str, object]:
        cycles = self.find_cycles()
        edge_count = sum(len(v) for v in self._out.values())
        fan_in = {n: self.fan_in(n) for n in self.nodes}
        fan_out = {n: self.fan_out(n) for n in self.nodes}
        return {
            "module_count": len(self.nodes),
            "edge_count": edge_count,
            "max_depth": self.longest_chain(),
            "cycle_count": len(cycles),
            "is_dag": not cycles,
            "max_fan_in": max(fan_in.values()) if fan_in else 0,
            "max_fan_out": max(fan_out.values()) if fan_out else 0,
            "leaf_count": sum(1 for n in self.nodes if fan_out[n] == 0),
            "root_count": sum(1 for n in self.nodes if fan_in[n] == 0),
        }


# --------------------------------------------------------------------------- #
# Affected-module analysis
# --------------------------------------------------------------------------- #


def _is_within(child: str, parent: str) -> bool:
    try:
        rel = os.path.relpath(child, parent)
    except ValueError:  # pragma: no cover - different drives on Windows
        return False
    return rel == "." or not rel.startswith("..")


def map_files_to_modules(repo: Repo, files) -> Tuple[Set[str], bool]:
    """Map changed files to module paths.

    Returns ``(module_paths, is_global)``. When ``is_global`` is True a
    build-wide file changed and every module is considered affected.
    """
    modules: Set[str] = set()
    for raw in files:
        abs_path = raw if os.path.isabs(raw) else os.path.normpath(os.path.join(repo.root, raw))
        rel = os.path.relpath(abs_path, repo.root).replace(os.sep, "/")
        if rel in _GLOBAL_EXACT or rel.startswith(_GLOBAL_PREFIXES):
            return set(), True

        best_path = None
        best_len = -1
        for module in repo.modules:
            if _is_within(abs_path, module.directory) and len(module.directory) > best_len:
                best_path = module.path
                best_len = len(module.directory)
        if best_path is not None:
            modules.add(best_path)
    return modules, False


def affected_modules(repo: Repo, graph: DependencyGraph, files) -> List[str]:
    """Return the sorted list of modules affected by the given changed files."""
    changed, is_global = map_files_to_modules(repo, files)
    if is_global:
        return sorted(graph.nodes)
    result: Set[str] = set(changed)
    for path in changed:
        result |= graph.transitive_dependents(path)
    return sorted(result)
