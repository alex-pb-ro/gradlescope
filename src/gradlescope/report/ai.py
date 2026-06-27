"""AI/LLM-friendly artifacts: a condensed context pack and ready-to-send prompts.

The goal is that a user can paste these straight into an LLM or a coding agent
to get a concrete remediation plan or patch, without the model needing the raw
repository.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Dict, List

from gradlescope.model import Finding
from gradlescope.result import AnalysisResult

_SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}


def ai_context(result: AnalysisResult, top_n: int = 15) -> Dict:
    """A small, serializable snapshot suitable for an LLM context window."""
    s = result.scorecard
    ordered = sorted(
        result.findings,
        key=lambda f: (-_SEVERITY_RANK.get(f.severity.name, 0), -f.weight),
    )
    top = ordered[:top_n]
    return {
        "tool": "gradlescope",
        "overall_score": s.overall,
        "grade": s.grade,
        "module_count": result.summary["module_count"],
        "gradle_version": result.summary["gradle_version"],
        "has_version_catalog": result.summary["has_version_catalog"],
        "severity_counts": s.severity_counts,
        "category_scores": {k: v.score for k, v in s.categories.items()},
        "graph": result.graph,
        "top_findings": [
            {
                "rule_id": f.rule_id,
                "title": f.title,
                "severity": f.severity.name,
                "category": f.category,
                "module": f.module_path,
                "message": f.message,
            }
            for f in top
        ],
    }


def _modules_for(findings: List[Finding]) -> List[str]:
    return sorted({f.module_path for f in findings if f.module_path})


def _category_prompt(category: str, findings: List[Finding], module_count: int) -> Dict:
    runbook = next((f.runbook for f in findings if f.runbook), None)
    modules = _modules_for(findings)
    bullets = []
    for f in findings[:25]:
        scope = f.module_path or "repo-wide"
        line = f"- [{scope}] {f.title}: {f.message}"
        if f.recommendation:
            line += f" (suggested: {f.recommendation})"
        bullets.append(line)
    affected = (
        f" Affected modules ({len(modules)}): {', '.join(modules[:30])}." if modules else ""
    )
    prompt = (
        f"You are a senior Gradle build engineer. In a {module_count}-module monorepo, "
        f"resolve the '{category}' issues found by gradlescope.\n\n"
        f"Findings:\n" + "\n".join(bullets) + "\n" + affected + "\n\n"
        "Produce: (1) a concrete, ordered remediation plan; (2) example Gradle changes "
        "(prefer Kotlin DSL and convention plugins); (3) how to validate the change; "
        "(4) rollout risks and a safe sequencing across modules."
    )
    if runbook:
        prompt += f"\n\nReference the gradlescope runbook: '{runbook}'."
    return {
        "category": category,
        "title": f"Resolve {category} issues",
        "runbook": runbook,
        "modules": modules,
        "finding_count": len(findings),
        "prompt": prompt,
    }


def _roadmap_prompt(result: AnalysisResult) -> Dict:
    context = ai_context(result)
    prompt = (
        "Given this gradlescope build-health report:\n\n```json\n"
        + json.dumps(context, indent=2)
        + "\n```\n\n"
        "Produce a prioritized remediation roadmap to raise the overall score, grouped "
        "into Quick Wins (days), Structural Work (weeks), and Stretch Goals (quarter). "
        "Cover: enabling the configuration cache, enabling local + remote build cache "
        "WITHOUT Develocity (e.g. an HttpBuildCache backed by Artifactory/S3/GCS), "
        "untangling the dependency graph for affected-only builds, adopting Isolated "
        "Projects, and keeping the build portable enough for an optional future Bazel "
        "migration. For each item give expected impact, effort, and the owning role."
    )
    return {
        "category": "roadmap",
        "title": "Build-health remediation roadmap",
        "runbook": None,
        "modules": [],
        "finding_count": result.scorecard.total_findings,
        "prompt": prompt,
    }


def ai_prompts(result: AnalysisResult) -> List[Dict]:
    """One actionable prompt per category with findings, plus a roadmap prompt."""
    grouped: Dict[str, List[Finding]] = defaultdict(list)
    for f in result.findings:
        grouped[f.category].append(f)

    # Order categories by total penalty (most impactful first).
    def total_penalty(items: List[Finding]) -> int:
        return sum(f.weight * _SEVERITY_RANK.get(f.severity.name, 1) for f in items)

    prompts: List[Dict] = []
    for category in sorted(grouped, key=lambda c: -total_penalty(grouped[c])):
        prompts.append(_category_prompt(category, grouped[category], result.summary["module_count"]))
    prompts.append(_roadmap_prompt(result))
    return prompts


def ai_markdown(result: AnalysisResult) -> str:
    """A single Markdown document bundling context and all prompts."""
    lines: List[str] = ["# gradlescope — AI handoff"]
    if result.generated_at:
        lines.append(f"_Generated: {result.generated_at}_")
    lines.append("")
    lines.append("## Context")
    lines.append("```json")
    lines.append(json.dumps(ai_context(result), indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Prompts")
    for p in ai_prompts(result):
        lines.append(f"### Prompt: {p['title']} (`{p['category']}`)")
        lines.append("```text")
        lines.append(p["prompt"])
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
