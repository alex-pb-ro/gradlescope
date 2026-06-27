"""Multi-page static dashboard generator.

``build_pages`` is pure (returns ``{filename: html}``) so it is unit-testable
without touching disk; ``render_site`` writes those pages plus machine-readable
artifacts to an output directory.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from gradlescope.dashboard import charts
from gradlescope.dashboard.html import (
    card,
    esc,
    grade_badge,
    page,
    sev_badge,
    stat,
    table,
)
from gradlescope.dashboard.runbooks import load_runbooks
from gradlescope.report import ai, json_report, markdown_report
from gradlescope.result import AnalysisResult

_SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
_SEVERITY_COLORS = {
    "CRITICAL": "#dc2626",
    "HIGH": "#ea580c",
    "MEDIUM": "#d97706",
    "LOW": "#0ea5e9",
    "INFO": "#64748b",
}
_SEVERITY_RANK = {s: i for i, s in enumerate(reversed(_SEVERITY_ORDER))}


def _short_cat(name: str) -> str:
    return name.replace("configuration-", "config-").replace("dependency-", "dep-")


def _severity_donut(result: AnalysisResult) -> str:
    counts = result.scorecard.severity_counts
    data = [(s, counts.get(s, 0), _SEVERITY_COLORS[s]) for s in _SEVERITY_ORDER]
    legend = "".join(
        f'<span><i style="background:{_SEVERITY_COLORS[s]}"></i>{esc(s)} {counts.get(s,0)}</span>'
        for s in _SEVERITY_ORDER
    )
    return charts.donut_chart(data) + f'<div class="legend">{legend}</div>'


def _category_bars(result: AnalysisResult) -> str:
    cats = result.scorecard.categories
    data = [(_short_cat(name), cat.score) for name, cat in sorted(cats.items())]
    return charts.bar_chart(data, width=560, height=240, max_value=100)


def _languages_bars(result: AnalysisResult) -> str:
    langs = result.summary.get("languages", {})
    if not langs:
        return '<p class="muted">No source languages detected.</p>'
    data = [(k, v) for k, v in sorted(langs.items(), key=lambda kv: -kv[1])]
    return charts.bar_chart(data, width=480, height=200, color="#7c9cff")


def _trend(result: AnalysisResult, history: Optional[List[Dict]]) -> str:
    series = list(history or [])
    points = [(str(h.get("generated_at", ""))[:16], float(h.get("overall", 0))) for h in series]
    cur_label = str(result.generated_at or "now")[:16]
    points.append((cur_label, result.scorecard.overall))
    return charts.line_chart(points, width=560, height=200)


def _finding_runbook_link(runbook: Optional[str]) -> str:
    if not runbook:
        return ""
    return f'<a href="runbooks.html#{esc(runbook)}">{esc(runbook)}</a>'


def _findings_rows(findings, limit=None):
    rows = []
    items = findings[:limit] if limit else findings
    for f in items:
        scope = f.module_path or "(repo-wide)"
        rows.append(
            [
                sev_badge(f.severity.name),
                f"{esc(f.title)}<div class='muted'>{esc(f.message)}</div>",
                f"<code>{esc(f.rule_id)}</code>",
                f"<code>{esc(scope)}</code>",
                esc(f.category),
                _finding_runbook_link(f.runbook),
            ]
        )
    return rows


def _page_index(result: AnalysisResult, history, live) -> str:
    s = result.scorecard
    summary = result.summary
    g = result.graph
    hero = (
        '<div class="hero">'
        f"<div>{charts.gauge(s.overall)}<div style='text-align:center;margin-top:6px'>{grade_badge(s.grade)}</div></div>"
        "<div class='grid cards'>"
        + card("Modules", stat(summary["module_count"], "in build"))
        + card("Gradle", stat(summary["gradle_version"] or "unknown", "wrapper version"))
        + card("Findings", stat(s.total_findings, "total issues"))
        + card("Version catalog", stat("yes" if summary["has_version_catalog"] else "no", "centralized versions"))
        + "</div></div>"
    )
    charts_row = (
        '<div class="grid cards">'
        + card("Findings by severity", _severity_donut(result))
        + card("Category scores", _category_bars(result))
        + card("Languages (modules)", _languages_bars(result))
        + "</div>"
    )
    trend = card("Overall score trend", _trend(result, history))
    graph_card = card(
        "Dependency graph",
        "<div class='grid cards'>"
        + stat(g["module_count"], "modules")
        + stat(g["edge_count"], "edges")
        + stat(g["max_depth"], "max depth")
        + stat(g["cycle_count"], "cycles")
        + stat(g["max_fan_in"], "max fan-in")
        + "</div>",
    )
    top = card(
        "Top findings",
        table(["Sev", "Issue", "Rule", "Scope", "Category", "Runbook"], _findings_rows(result.findings, 8))
        + '<p style="margin-top:10px"><a href="findings.html">See all findings →</a></p>',
    )
    body = f"<h1>Build health overview</h1><p class='muted'>{esc(result.root)}</p>{hero}{charts_row}<div class='grid cards'>{trend}{graph_card}</div>{top}"
    return page("Overview", body, "index.html", live=live, generated_at=result.generated_at or "")


def _page_findings(result: AnalysisResult, live) -> str:
    options = "".join(f'<option value="{s}">{s}</option>' for s in _SEVERITY_ORDER)
    controls = (
        '<div class="controls">'
        '<input type="search" id="flt" placeholder="Filter findings…" oninput="gsFilter()"/>'
        f'<select id="sevf" onchange="gsFilter()"><option value="">All severities</option>{options}</select>'
        "</div>"
    )
    rows = []
    for f in result.findings:
        scope = f.module_path or "(repo-wide)"
        hay = " ".join([f.title, f.message, f.rule_id, scope, f.category]).lower()
        rows.append(
            f'<tr data-row data-sev="{esc(f.severity.name)}" data-hay="{esc(hay)}">'
            f"<td>{sev_badge(f.severity.name)}</td>"
            f"<td>{esc(f.title)}<div class='muted'>{esc(f.message)}</div>"
            + (f"<div class='muted'>Fix: {esc(f.recommendation)}</div>" if f.recommendation else "")
            + f"</td><td><code>{esc(f.rule_id)}</code></td>"
            f"<td><code>{esc(scope)}</code></td><td>{esc(f.category)}</td>"
            f"<td>{_finding_runbook_link(f.runbook)}</td></tr>"
        )
    table_html = (
        "<table><thead><tr><th>Sev</th><th>Issue</th><th>Rule</th><th>Scope</th><th>Category</th><th>Runbook</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    body = f"<h1>Findings ({result.scorecard.total_findings})</h1>{controls}{table_html}"
    return page("Findings", body, "findings.html", live=live, generated_at=result.generated_at or "")


def _page_modules(result: AnalysisResult, live) -> str:
    modules = sorted(result.scorecard.modules.values(), key=lambda m: (m.score, m.path))
    rows = [
        [f"<code>{esc(m.path)}</code>", esc(m.score), grade_badge(m.grade), esc(m.finding_count)]
        for m in modules
    ]
    dist = charts.bar_chart(
        [(m.path.rsplit(":", 1)[-1] or ":", m.score) for m in modules[:25]],
        width=720,
        height=240,
        max_value=100,
    )
    body = (
        f"<h1>Modules ({len(modules)})</h1>"
        + card("Lowest-scoring modules", dist)
        + "<h2>All modules (worst first)</h2>"
        + table(["Module", "Score", "Grade", "Findings"], rows)
    )
    return page("Modules", body, "modules.html", live=live, generated_at=result.generated_at or "")


def _page_graph(result: AnalysisResult, live) -> str:
    g = result.graph
    cards = "".join(
        card(k.replace("_", " ").title(), stat(v, ""))
        for k, v in g.items()
    )
    graph_findings = [f for f in result.findings if f.category in ("dependency-graph", "modularity")]
    body = (
        "<h1>Dependency graph</h1>"
        "<p class='muted'>Affected-only builds and a future Bazel migration both depend on a clean, acyclic graph.</p>"
        f"<div class='grid cards'>{cards}</div>"
        "<h2>Graph & modularity findings</h2>"
        + table(["Sev", "Issue", "Rule", "Scope", "Category", "Runbook"], _findings_rows(graph_findings))
    )
    return page("Graph", body, "graph.html", live=live, generated_at=result.generated_at or "")


def _page_runbooks(result: AnalysisResult, runbooks, live) -> str:
    if not runbooks:
        body = "<h1>Runbooks</h1><p class='muted'>No runbooks bundled.</p>"
        return page("Runbooks", body, "runbooks.html", live=live)
    toc = "".join(f'<li><a href="#{esc(rid)}">{esc(rb["title"])}</a></li>' for rid, rb in runbooks.items())
    sections = "".join(
        f'<section class="runbook" id="{esc(rid)}">{rb["html"]}</section>' for rid, rb in runbooks.items()
    )
    body = f"<h1>Runbooks</h1><ul>{toc}</ul>{sections}"
    return page("Runbooks", body, "runbooks.html", live=live, generated_at=result.generated_at or "")


def _page_ai(result: AnalysisResult, live) -> str:
    context_json = json.dumps(ai.ai_context(result), indent=2)
    blocks = [
        "<h1>AI handoff</h1>",
        "<p class='muted'>Copy the context or any prompt into an LLM or coding agent to get a remediation plan or patch.</p>",
        '<div class="prompt"><div class="head"><h2>Context pack</h2>'
        '<button class="act secondary" onclick="gsCopy(\'ctx\')">Copy</button></div>'
        f'<pre id="ctx">{esc(context_json)}</pre></div>',
    ]
    for i, p in enumerate(ai.ai_prompts(result)):
        pid = f"p{i}"
        blocks.append(
            '<div class="prompt"><div class="head">'
            f'<h2>{esc(p["title"])} <span class="muted">({esc(p["category"])})</span></h2>'
            f'<button class="act secondary" onclick="gsCopy(\'{pid}\')">Copy</button></div>'
            f'<pre id="{pid}">{esc(p["prompt"])}</pre></div>'
        )
    return page("AI", "".join(blocks), "ai.html", live=live, generated_at=result.generated_at or "")


def build_pages(
    result: AnalysisResult,
    history: Optional[List[Dict]] = None,
    runbooks: Optional[Dict] = None,
    live: bool = False,
) -> Dict[str, str]:
    if runbooks is None:
        runbooks = load_runbooks()
    return {
        "index.html": _page_index(result, history, live),
        "findings.html": _page_findings(result, live),
        "modules.html": _page_modules(result, live),
        "graph.html": _page_graph(result, live),
        "runbooks.html": _page_runbooks(result, runbooks, live),
        "ai.html": _page_ai(result, live),
    }


def render_site(
    result: AnalysisResult,
    output_dir: str,
    history: Optional[List[Dict]] = None,
    live: bool = False,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    pages = build_pages(result, history=history, live=live)
    for name, html in pages.items():
        with open(os.path.join(output_dir, name), "w", encoding="utf-8") as fh:
            fh.write(html)
    with open(os.path.join(output_dir, "data.json"), "w", encoding="utf-8") as fh:
        fh.write(json_report.to_json(result))
    with open(os.path.join(output_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown_report.to_markdown(result))
    with open(os.path.join(output_dir, "ai.md"), "w", encoding="utf-8") as fh:
        fh.write(ai.ai_markdown(result))
    return output_dir
