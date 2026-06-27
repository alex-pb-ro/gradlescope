"""Tests for the scoring engine."""
from gradlescope.analysis.scoring import (
    CATEGORY_WEIGHTS,
    grade_for,
    compute_scorecard,
)
from gradlescope.model import Finding, Module, Repo, Severity


def _finding(category, severity, weight, module_path=None, rule_id="r"):
    return Finding(
        rule_id=rule_id,
        title="t",
        severity=severity,
        category=category,
        message="m",
        weight=weight,
        module_path=module_path,
    )


class TestGrade:
    def test_grade_bands(self):
        assert grade_for(95) == "A"
        assert grade_for(85) == "B"
        assert grade_for(75) == "C"
        assert grade_for(65) == "D"
        assert grade_for(50) == "F"


class TestScorecard:
    def test_perfect_score_when_no_findings(self):
        card = compute_scorecard([], repo=Repo(root="/r"))
        assert card.overall == 100.0
        assert card.grade == "A"

    def test_penalty_reduces_category_score(self):
        findings = [_finding("build-cache", Severity.HIGH, 10)]
        card = compute_scorecard(findings)
        assert card.categories["build-cache"].score < 100
        # All canonical categories are represented even with zero findings.
        assert "configuration-cache" in card.categories
        assert card.categories["configuration-cache"].score == 100

    def test_score_never_negative(self):
        findings = [_finding("build-cache", Severity.CRITICAL, 100) for _ in range(10)]
        card = compute_scorecard(findings)
        assert card.categories["build-cache"].score == 0
        assert card.overall >= 0

    def test_severity_scales_penalty(self):
        low = compute_scorecard([_finding("toolchains", Severity.LOW, 10)])
        high = compute_scorecard([_finding("toolchains", Severity.HIGH, 10)])
        assert high.categories["toolchains"].score < low.categories["toolchains"].score

    def test_overall_is_weighted_average(self):
        # Tanking a single category should not drag overall to zero.
        findings = [_finding("toolchains", Severity.CRITICAL, 100) for _ in range(5)]
        card = compute_scorecard(findings)
        assert card.categories["toolchains"].score == 0
        assert card.overall > 50

    def test_overall_respects_category_weights(self):
        # configuration-cache (weight 3.0) tanked must hurt more than toolchains
        # (weight 1.0) tanked by the same amount — proving weighting is applied.
        heavy = compute_scorecard([_finding("configuration-cache", Severity.CRITICAL, 100) for _ in range(5)])
        light = compute_scorecard([_finding("toolchains", Severity.CRITICAL, 100) for _ in range(5)])
        assert heavy.categories["configuration-cache"].score == 0
        assert light.categories["toolchains"].score == 0
        assert heavy.overall < light.overall

    def test_module_scores(self):
        repo = Repo(root="/r", modules=[Module(path=":a", directory="/r/a"), Module(path=":b", directory="/r/b")])
        findings = [_finding("dependency-hygiene", Severity.HIGH, 20, module_path=":a")]
        card = compute_scorecard(findings, repo=repo)
        assert card.modules[":a"].score < 100
        assert card.modules[":b"].score == 100  # untouched module stays perfect

    def test_severity_counts(self):
        findings = [
            _finding("build-cache", Severity.HIGH, 5, rule_id="x"),
            _finding("build-cache", Severity.HIGH, 5, rule_id="y"),
            _finding("toolchains", Severity.LOW, 1, rule_id="z"),
        ]
        card = compute_scorecard(findings)
        assert card.severity_counts["HIGH"] == 2
        assert card.severity_counts["LOW"] == 1
        assert card.total_findings == 3

    def test_to_dict_roundtrip(self):
        card = compute_scorecard([_finding("build-cache", Severity.HIGH, 10)])
        d = card.to_dict()
        assert "overall" in d and "grade" in d
        assert "categories" in d and "build-cache" in d["categories"]
        assert set(CATEGORY_WEIGHTS).issubset(d["categories"].keys())
