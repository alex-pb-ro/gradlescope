"""Scoring engine: turn findings into category, module, and overall scores.

Model: every category starts at 100 and loses ``weight * severity_factor`` per
finding. The overall score is the category-weighted average, so a single weak
area cannot zero out an otherwise healthy build (and vice versa). Best
practices score well precisely because they produce no findings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from gradlescope.model import Finding, Repo, Severity

# Relative importance of each category in the overall score.
CATEGORY_WEIGHTS: Dict[str, float] = {
    "configuration-cache": 3.0,
    "build-cache": 3.0,
    "dependency-graph": 3.0,
    "dependency-hygiene": 2.0,
    "parallelism": 2.0,
    "modularity": 2.0,
    "toolchains": 1.0,
    "portability": 1.0,
    "maintainability": 1.0,
}

SEVERITY_FACTOR: Dict[Severity, float] = {
    Severity.INFO: 0.2,
    Severity.LOW: 0.5,
    Severity.MEDIUM: 1.0,
    Severity.HIGH: 1.5,
    Severity.CRITICAL: 2.5,
}

_GRADE_BANDS = [(90, "A"), (80, "B"), (70, "C"), (60, "D")]


def grade_for(score: float) -> str:
    for threshold, letter in _GRADE_BANDS:
        if score >= threshold:
            return letter
    return "F"


def penalty_for(finding: Finding) -> float:
    return finding.weight * SEVERITY_FACTOR.get(finding.severity, 1.0)


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


@dataclass
class CategoryScore:
    name: str
    score: float
    grade: str
    finding_count: int
    penalty: float

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "score": self.score,
            "grade": self.grade,
            "finding_count": self.finding_count,
            "penalty": round(self.penalty, 1),
        }


@dataclass
class ModuleScore:
    path: str
    score: float
    grade: str
    finding_count: int

    def to_dict(self) -> Dict:
        return {"path": self.path, "score": self.score, "grade": self.grade, "finding_count": self.finding_count}


@dataclass
class Scorecard:
    overall: float
    grade: str
    categories: Dict[str, CategoryScore]
    modules: Dict[str, ModuleScore] = field(default_factory=dict)
    severity_counts: Dict[str, int] = field(default_factory=dict)
    total_findings: int = 0

    def to_dict(self) -> Dict:
        return {
            "overall": self.overall,
            "grade": self.grade,
            "total_findings": self.total_findings,
            "severity_counts": self.severity_counts,
            "categories": {k: v.to_dict() for k, v in self.categories.items()},
            "modules": {k: v.to_dict() for k, v in self.modules.items()},
        }


def compute_scorecard(
    findings: Iterable[Finding],
    repo: Optional[Repo] = None,
    config: Optional[Dict] = None,
) -> Scorecard:
    findings = list(findings)

    # -- categories ------------------------------------------------------- #
    category_names = set(CATEGORY_WEIGHTS)
    category_names.update(f.category for f in findings)

    penalties: Dict[str, float] = {name: 0.0 for name in category_names}
    counts: Dict[str, int] = {name: 0 for name in category_names}
    for f in findings:
        penalties[f.category] += penalty_for(f)
        counts[f.category] += 1

    categories: Dict[str, CategoryScore] = {}
    for name in sorted(category_names):
        score = _clamp_score(100.0 - penalties[name])
        categories[name] = CategoryScore(
            name=name,
            score=score,
            grade=grade_for(score),
            finding_count=counts[name],
            penalty=penalties[name],
        )

    # -- overall (category-weighted average) ------------------------------ #
    weighted_sum = 0.0
    weight_total = 0.0
    for name, cat in categories.items():
        weight = CATEGORY_WEIGHTS.get(name, 1.0)
        weighted_sum += cat.score * weight
        weight_total += weight
    overall = _clamp_score(weighted_sum / weight_total) if weight_total else 100.0

    # -- per-module ------------------------------------------------------- #
    modules: Dict[str, ModuleScore] = {}
    if repo is not None:
        module_penalty: Dict[str, float] = {m.path: 0.0 for m in repo.modules}
        module_count: Dict[str, int] = {m.path: 0 for m in repo.modules}
        for f in findings:
            if f.module_path in module_penalty:
                module_penalty[f.module_path] += penalty_for(f)
                module_count[f.module_path] += 1
        for path in sorted(module_penalty):
            mscore = _clamp_score(100.0 - module_penalty[path])
            modules[path] = ModuleScore(
                path=path,
                score=mscore,
                grade=grade_for(mscore),
                finding_count=module_count[path],
            )

    # -- severity tally --------------------------------------------------- #
    severity_counts = {s.name: 0 for s in Severity}
    for f in findings:
        severity_counts[f.severity.name] += 1

    return Scorecard(
        overall=overall,
        grade=grade_for(overall),
        categories=categories,
        modules=modules,
        severity_counts=severity_counts,
        total_findings=len(findings),
    )
