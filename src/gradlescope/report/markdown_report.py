"""Human-readable Markdown report."""
from __future__ import annotations

from typing import List

from gradlescope.result import AnalysisResult

_SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


def to_markdown(result: AnalysisResult) -> str:
    s = result.scorecard
    summary = result.summary
    g = result.graph
    lines: List[str] = ["# gradlescope report"]
    if result.generated_at:
        lines.append(f"_Generated: {result.generated_at} · gradlescope {result.version}_")
    lines.append("")
    lines.append(
        f"**Overall score: {s.overall} ({s.grade})** — "
        f"{summary['module_count']} modules · Gradle {summary['gradle_version']}"
    )
    lines.append("")

    lines.append("## Severity summary")
    for sev in _SEVERITY_ORDER:
        lines.append(f"- {sev}: {s.severity_counts.get(sev, 0)}")
    lines.append("")

    lines.append("## Category scores")
    lines.append("| Category | Score | Grade | Findings |")
    lines.append("| --- | ---: | :---: | ---: |")
    for name, cat in sorted(result.scorecard.categories.items()):
        lines.append(f"| {name} | {cat.score} | {cat.grade} | {cat.finding_count} |")
    lines.append("")

    lines.append("## Dependency graph")
    lines.append(f"- Modules: {g['module_count']} · edges: {g['edge_count']}")
    lines.append(f"- Max depth: {g['max_depth']} · cycles: {g['cycle_count']} · DAG: {g['is_dag']}")
    lines.append(f"- Max fan-in: {g['max_fan_in']} · max fan-out: {g['max_fan_out']}")
    lines.append("")

    lines.append("## Findings")
    if not result.findings:
        lines.append("No issues found. 🎉")
    for sev in _SEVERITY_ORDER:
        bucket = [f for f in result.findings if f.severity.name == sev]
        if not bucket:
            continue
        lines.append(f"### {sev} ({len(bucket)})")
        for f in bucket:
            scope = f.module_path or "(repo-wide)"
            lines.append(f"- **{f.title}** `[{f.rule_id}]` — `{scope}` — {f.message}")
            if f.recommendation:
                lines.append(f"  - Fix: {f.recommendation}")
            if f.runbook:
                lines.append(f"  - Runbook: `{f.runbook}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
