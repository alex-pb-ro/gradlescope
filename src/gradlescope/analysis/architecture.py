"""Clean Architecture component metrics (Robert C. Martin).

For each module we compute the package/component metrics from *Clean
Architecture* / *Agile Software Development*:

- ``Ca`` afferent coupling  — modules that depend on this one (fan-in)
- ``Ce`` efferent coupling  — modules this one depends on (fan-out)
- ``I``  instability        — ``Ce / (Ca + Ce)``  (0 = stable, 1 = unstable)
- ``A``  abstractness       — ``abstract types / total types``
- ``D``  distance from the main sequence — ``|A + I - 1|``

The *Stable Dependencies Principle* (SDP) says a module should depend only on
modules at least as stable as itself; we flag edges that violate it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from gradlescope.graph.depgraph import DependencyGraph
from gradlescope.model import Repo


@dataclass
class ModuleMetrics:
    path: str
    ca: int
    ce: int
    instability: float
    abstractness: float
    distance: float
    type_count: int
    abstract_type_count: int
    has_coupling: bool

    def to_dict(self) -> Dict:
        return {
            "path": self.path,
            "ca": self.ca,
            "ce": self.ce,
            "instability": self.instability,
            "abstractness": self.abstractness,
            "distance": self.distance,
            "type_count": self.type_count,
            "abstract_type_count": self.abstract_type_count,
            "has_coupling": self.has_coupling,
            "zone": self.zone,
        }

    @property
    def zone(self) -> str:
        """Which problem zone the module sits in (or 'ok')."""
        if self.distance <= 0.3:
            return "main-sequence"
        if self.abstractness < 0.35 and self.instability < 0.35:
            return "zone-of-pain"  # stable + concrete: rigid, hard to change
        if self.abstractness > 0.65 and self.instability > 0.65:
            return "zone-of-uselessness"  # abstract + unstable: unused abstractions
        return "off-sequence"


def compute_module_metrics(repo: Repo, graph: DependencyGraph) -> Dict[str, ModuleMetrics]:
    metrics: Dict[str, ModuleMetrics] = {}
    for module in repo.modules:
        ca = graph.fan_in(module.path)
        ce = graph.fan_out(module.path)
        denom = ca + ce
        instability = (ce / denom) if denom else 0.0
        abstractness = (module.abstract_type_count / module.type_count) if module.type_count else 0.0
        distance = abs(abstractness + instability - 1.0)
        metrics[module.path] = ModuleMetrics(
            path=module.path,
            ca=ca,
            ce=ce,
            instability=round(instability, 3),
            abstractness=round(abstractness, 3),
            distance=round(distance, 3),
            type_count=module.type_count,
            abstract_type_count=module.abstract_type_count,
            has_coupling=denom > 0,
        )
    return metrics


def sdp_violations(
    graph: DependencyGraph,
    metrics: Dict[str, ModuleMetrics],
    margin: float = 0.1,
) -> List[Tuple[str, str, float]]:
    """Edges ``a -> b`` where b is significantly *less* stable than a
    (I(b) > I(a) + margin). Returns ``(a, b, delta)`` sorted worst-first."""
    violations: List[Tuple[str, str, float]] = []
    for src in graph.nodes:
        a = metrics.get(src)
        if a is None:
            continue
        for tgt in graph.dependencies_of(src):
            b = metrics.get(tgt)
            if b is None:
                continue
            delta = b.instability - a.instability
            if delta > margin:
                violations.append((src, tgt, round(delta, 3)))
    violations.sort(key=lambda v: -v[2])
    return violations


def architecture_summary(metrics: Dict[str, ModuleMetrics]) -> Dict:
    values = list(metrics.values())
    scored = [m for m in values if m.has_coupling]
    avg_distance = round(sum(m.distance for m in scored) / len(scored), 3) if scored else 0.0
    zones: Dict[str, int] = {}
    for m in values:
        zones[m.zone] = zones.get(m.zone, 0) + 1
    most_distant = sorted(values, key=lambda m: -m.distance)[:10]
    return {
        "avg_distance": avg_distance,
        "scored_modules": len(scored),
        "zones": zones,
        "most_distant": [m.path for m in most_distant if m.distance > 0],
    }


def _distance_color(distance: float) -> str:
    if distance <= 0.2:
        return "#16a34a"
    if distance <= 0.4:
        return "#d97706"
    return "#dc2626"


def scatter_points(metrics: Dict[str, ModuleMetrics]) -> List[Tuple[str, float, float, str]]:
    """Points for the A/I main-sequence scatter: (label, instability, abstractness, color)."""
    return [
        (m.path, m.instability, m.abstractness, _distance_color(m.distance))
        for m in metrics.values()
    ]
