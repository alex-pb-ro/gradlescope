"""Multi-page static dashboard generator.

``build_pages`` is pure (returns ``{filename: html}``) so it is unit-testable
without touching disk; ``render_site`` writes those pages plus machine-readable
artifacts to an output directory.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from gradlescope.analysis.plugins import category_color
from gradlescope.dashboard import charts
from gradlescope.dashboard.graphview import render_graph_section
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
_ZONE_COLORS = {
    "main-sequence": "#16a34a",
    "zone-of-pain": "#dc2626",
    "zone-of-uselessness": "#a855f7",
    "off-sequence": "#d97706",
    "": "#64748b",
}


def _short_cat(name: str) -> str:
    return name.replace("configuration-", "config-").replace("dependency-", "dep-")


def _runbook_link(runbook: Optional[str]) -> str:
    return f'<a href="runbooks.html#{esc(runbook)}">{esc(runbook)}</a>' if runbook else ""


def _zone_pill(zone: str) -> str:
    color = _ZONE_COLORS.get(zone, "#64748b")
    label = zone or "n/a"
    return f'<span class="zone-pill" style="border-color:{color};color:{color}">{esc(label)}</span>'


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #


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
    return charts.hbar_chart(data, width=560, max_value=100, label_width=150)


def _languages_bars(result: AnalysisResult) -> str:
    langs = result.summary.get("languages", {})
    if not langs:
        return '<p class="muted">No source languages detected.</p>'
    data = [(k, v) for k, v in sorted(langs.items(), key=lambda kv: -kv[1])]
    return charts.hbar_chart(data, width=480, color="#7c9cff", value_suffix=" mod", label_width=120)


def _trend(result: AnalysisResult, history: Optional[List[Dict]]) -> str:
    series = list(history or [])
    points = [(str(h.get("generated_at", ""))[:16], float(h.get("overall", 0))) for h in series]
    points.append((str(result.generated_at or "now")[:16], result.scorecard.overall))
    return charts.line_chart(points, width=560, height=200)


def _findings_rows(findings, limit=None):
    rows = []
    for f in (findings[:limit] if limit else findings):
        scope = f.module_path or "(repo-wide)"
        rows.append(
            [
                sev_badge(f.severity.name),
                f"{esc(f.title)}<div class='muted'>{esc(f.message)}</div>",
                f"<code>{esc(f.rule_id)}</code>",
                f"<code>{esc(scope)}</code>",
                esc(f.category),
                _runbook_link(f.runbook),
            ]
        )
    return rows


def _page_index(result: AnalysisResult, history, live) -> str:
    s = result.scorecard
    summary = result.summary
    g = result.graph
    plugins = result.plugins or {}
    arch = result.architecture or {}
    hero = (
        '<div class="hero">'
        f"<div>{charts.gauge(s.overall)}<div style='text-align:center;margin-top:6px'>{grade_badge(s.grade)}</div></div>"
        "<div class='grid cards'>"
        + card("Modules", stat(summary["module_count"], "in build"))
        + card("Gradle", stat(summary["gradle_version"] or "unknown", "wrapper version"))
        + card("Findings", stat(s.total_findings, "total issues"))
        + card("Plugins", stat(plugins.get("distinct", 0), "distinct applied"))
        + "</div></div>"
    )
    charts_row = (
        '<div class="grid cards">'
        + card("Findings by severity", _severity_donut(result))
        + card("Category scores", _category_bars(result))
        + card("Languages (modules)", _languages_bars(result))
        + "</div>"
    )
    info_row = (
        '<div class="grid cards">'
        + card("Overall score trend", _trend(result, history))
        + card(
            "Dependency graph",
            "<div class='grid cards'>"
            + stat(g["module_count"], "modules")
            + stat(g["edge_count"], "edges")
            + stat(g["max_depth"], "max depth")
            + stat(g["cycle_count"], "cycles")
            + "</div><p style='margin-top:8px'><a href='graph.html'>Open graph →</a></p>",
        )
        + card(
            "Architecture",
            "<div class='grid cards'>"
            + stat(arch.get("avg_distance", "n/a"), "avg distance D")
            + stat(arch.get("zones", {}).get("zone-of-pain", 0), "in zone of pain")
            + "</div><p style='margin-top:8px'><a href='architecture.html'>Clean Architecture →</a></p>",
        )
        + "</div>"
    )
    top = card(
        "Top findings",
        table(["Sev", "Issue", "Rule", "Scope", "Category", "Runbook"], _findings_rows(result.findings, 8))
        + '<p style="margin-top:10px"><a href="findings.html">See all findings →</a></p>',
    )
    body = f"<h1>Build health overview</h1><p class='muted'>{esc(result.root)}</p>{hero}{charts_row}{info_row}{top}"
    return page("Overview", body, "index.html", live=live, generated_at=result.generated_at or "")


# --------------------------------------------------------------------------- #
# Findings (with per-finding prompt buttons)
# --------------------------------------------------------------------------- #


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
            f"<td>{_runbook_link(f.runbook)}</td>"
            f"<td><button class='btn-mini' onclick=\"gsCopyPrompt('{esc(f.key)}')\">Prompt</button></td></tr>"
        )
    table_html = (
        "<table><thead><tr><th>Sev</th><th>Issue</th><th>Rule</th><th>Scope</th>"
        "<th>Category</th><th>Runbook</th><th>AI</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    # Escape "<" so a finding message containing "</script>" cannot break out.
    prompts = json.dumps(ai.prompts_by_key(result)).replace("<", "\\u003c")
    body = (
        f"<h1>Findings ({result.scorecard.total_findings})</h1>"
        "<p class='muted'>Each finding's <b>Prompt</b> button copies a ready-to-paste AI prompt "
        "(Goal, Context, Locations, references, stats).</p>"
        f"{controls}{table_html}"
        f"<script>window.GS_PROMPTS = {prompts};</script>"
    )
    return page("Findings", body, "findings.html", live=live, generated_at=result.generated_at or "")


# --------------------------------------------------------------------------- #
# Modules (with Clean Architecture metrics)
# --------------------------------------------------------------------------- #


def _page_modules(result: AnalysisResult, live) -> str:
    modules = sorted(result.scorecard.modules.values(), key=lambda m: (m.score, m.path))
    metrics = result.module_metrics
    dist = charts.hbar_chart(
        [(m.path, m.score) for m in modules[:25]],
        width=720,
        max_value=100,
        label_width=220,
    )
    rows = []
    for m in modules:
        mm = metrics.get(m.path)
        rows.append(
            [
                f"<code>{esc(m.path)}</code>",
                esc(m.score),
                grade_badge(m.grade),
                esc(m.finding_count),
                esc(mm.ca if mm else "-"),
                esc(mm.ce if mm else "-"),
                esc(mm.instability if mm else "-"),
                esc(mm.abstractness if mm else "-"),
                esc(mm.distance if mm else "-"),
                _zone_pill(mm.zone if mm else ""),
            ]
        )
    body = (
        f"<h1>Modules ({len(modules)})</h1>"
        + card("Lowest-scoring modules", dist)
        + "<h2>All modules (worst first)</h2>"
        + "<p class='muted'>Ca/Ce = afferent/efferent coupling · I = instability · A = abstractness · D = distance from main sequence.</p>"
        + table(
            ["Module", "Score", "Grade", "Findings", "Ca", "Ce", "I", "A", "D", "Zone"],
            rows,
        )
    )
    return page("Modules", body, "modules.html", live=live, generated_at=result.generated_at or "")


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #


def _page_graph(result: AnalysisResult, live) -> str:
    graph_findings = [f for f in result.findings if f.category in ("dependency-graph", "modularity")]
    body = (
        "<h1>Dependency graph</h1>"
        "<p class='muted'>Click a node to focus on its upstream/downstream neighbourhood. "
        "Scroll to zoom, drag to pan, hover for labels. Foundational modules sit on the left.</p>"
        + render_graph_section(result)
        + "<h2>Graph &amp; modularity findings</h2>"
        + table(["Sev", "Issue", "Rule", "Scope", "Category", "Runbook"], _findings_rows(graph_findings))
    )
    return page("Graph", body, "graph.html", live=live, generated_at=result.generated_at or "")


# --------------------------------------------------------------------------- #
# Architecture (Clean Architecture main sequence)
# --------------------------------------------------------------------------- #


def _page_architecture(result: AnalysisResult, live) -> str:
    from gradlescope.analysis.architecture import scatter_points

    metrics = result.module_metrics
    arch = result.architecture or {}
    scatter = charts.scatter_chart(
        scatter_points(metrics),
        width=460,
        height=380,
        diagonal=True,
        x_label="Instability (I)",
        y_label="Abstractness (A)",
    )
    zones = arch.get("zones", {})
    zone_cards = "".join(
        card(z.replace("-", " ").title(), stat(zones.get(z, 0), "modules"))
        for z in ["main-sequence", "off-sequence", "zone-of-pain", "zone-of-uselessness"]
    )
    sdp_rows = [
        [f"<code>{esc(a)}</code>", "→", f"<code>{esc(b)}</code>", esc(d)]
        for a, b, d in result.sdp_violations[:50]
    ]
    sdp_section = (
        "<h2>Stable Dependencies Principle violations</h2>"
        "<p class='muted'>Edges where a module depends on a <i>less stable</i> module (higher instability).</p>"
        + (
            table(["From", "", "Depends on (less stable)", "ΔI"], sdp_rows)
            if sdp_rows
            else "<p class='muted'>None 🎉</p>"
        )
    )
    most_distant = arch.get("most_distant", [])
    distant = (
        "<h2>Furthest from the main sequence</h2>"
        + (
            "<p>" + ", ".join(f"<code>{esc(m)}</code>" for m in most_distant[:20]) + "</p>"
            if most_distant
            else "<p class='muted'>All modules are close to the main sequence.</p>"
        )
    )
    body = (
        "<h1>Clean Architecture metrics</h1>"
        "<p class='muted'>After Robert C. Martin: the ideal is the <b>main sequence</b> "
        "(A + I = 1). Distance D measures how far each module strays.</p>"
        + f'<div class="grid cards">{zone_cards}</div>'
        + card(
            f"Main sequence (avg distance D = {esc(arch.get('avg_distance', 'n/a'))})",
            scatter
            + '<div class="legend">'
            '<span><i style="background:#16a34a"></i>near</span>'
            '<span><i style="background:#d97706"></i>off</span>'
            '<span><i style="background:#dc2626"></i>far</span></div>',
        )
        + sdp_section
        + distant
    )
    return page("Architecture", body, "architecture.html", live=live, generated_at=result.generated_at or "")


# --------------------------------------------------------------------------- #
# Plugins
# --------------------------------------------------------------------------- #


def _page_plugins(result: AnalysisResult, live) -> str:
    pov = result.plugins or {"plugins": [], "category_counts": {}, "distinct": 0, "version_conflicts": 0}
    cc = pov.get("category_counts", {})
    cards = (
        '<div class="grid cards">'
        + card("Distinct plugins", stat(pov.get("distinct", 0), "applied across modules"))
        + card("External", stat(cc.get("external", 0), "from public repos"))
        + card("Convention", stat(cc.get("convention", 0), "in-house (buildSrc/build-logic)"))
        + card("Internal", stat(cc.get("internal", 0), "other in-house"))
        + card("Core", stat(cc.get("core", 0), "Gradle built-in"))
        + card("Version conflicts", stat(pov.get("version_conflicts", 0), "applied with >1 version"))
        + "</div>"
    )
    rows = []
    for p in pov.get("plugins", []):
        color = category_color(p["category"])
        pill = f'<span class="pluginpill" style="background:{color}">{esc(p["category"])}</span>'
        versions = ", ".join(p["versions"]) if p["versions"] else "—"
        if p.get("version_conflict"):
            versions = f"<span style='color:var(--HIGH)'>{esc(versions)} ⚠</span>"
        else:
            versions = esc(versions)
        rows.append([f"<code>{esc(p['id'])}</code>", pill, esc(p["count"]), versions])
    body = (
        "<h1>Plugins</h1>"
        "<p class='muted'>Plugins classified as core (Gradle), convention (this repo's "
        "buildSrc/build-logic), internal (other in-house), or external (public repositories).</p>"
        + cards
        + "<h2>All plugins (by usage)</h2>"
        + table(["Plugin id", "Type", "Modules", "Versions"], rows)
    )
    return page("Plugins", body, "plugins.html", live=live, generated_at=result.generated_at or "")


# --------------------------------------------------------------------------- #
# Processes (live jobs + gradle daemons)
# --------------------------------------------------------------------------- #

_PROCESSES_JS = r"""
(function(){
  var offsets = {};
  var statusEl = document.getElementById('pr-conn');
  function pill(s){ return '<span class="dot-status" style="background:'+({running:'#4f7cff',ok:'#16a34a',failed:'#dc2626'}[s]||'#64748b')+'"></span>'+s; }
  function esc(t){ var d=document.createElement('div'); d.textContent=t==null?'':t; return d.innerHTML; }
  function renderDaemons(procs){
    var el=document.getElementById('pr-daemons');
    if(!procs || !procs.length){ el.innerHTML='<p class="muted">No running Gradle daemons/processes detected.</p>'; return; }
    var h='<table><thead><tr><th>PID</th><th>Kind</th><th>Uptime</th><th>CPU%</th><th>MEM%</th><th>Command</th></tr></thead><tbody>';
    procs.forEach(function(p){ h+='<tr><td>'+p.pid+'</td><td>'+esc(p.kind)+'</td><td>'+esc(p.etime)+'</td><td>'+esc(p.cpu)+'</td><td>'+esc(p.mem)+'</td><td><code>'+esc(p.command)+'</code></td></tr>'; });
    el.innerHTML=h+'</tbody></table>';
  }
  function ensureJob(j){
    var id='job-'+j.id; var box=document.getElementById(id);
    if(!box){ box=document.createElement('div'); box.id=id; box.className='job '+j.status;
      box.innerHTML='<div class="head"><b>Job '+j.id+'</b> · <code>gradle '+esc(j.task)+'</code> <span class="jstat"></span></div><pre class="jobline" style="max-height:300px;overflow:auto"></pre>';
      document.getElementById('pr-jobs').prepend(box); offsets[j.id]=0; }
    box.className='job '+j.status;
    box.querySelector('.jstat').innerHTML=pill(j.status)+(j.returncode!=null?(' (rc='+j.returncode+')'):'');
    return box;
  }
  function poll(){
    fetch('/api/processes').then(function(r){return r.json();}).then(function(d){
      statusEl.textContent='connected'; renderDaemons(d.processes);
      (d.jobs||[]).forEach(function(j){ var box=ensureJob(j);
        fetch('/api/jobs/'+j.id+'?offset='+(offsets[j.id]||0)).then(function(r){return r.json();}).then(function(jd){
          if(jd && jd.lines && jd.lines.length){ var pre=box.querySelector('pre'); pre.textContent+=jd.lines.join('\n')+'\n'; pre.scrollTop=pre.scrollHeight; offsets[j.id]=jd.next_offset; }
          box.className='job '+jd.status; box.querySelector('.jstat').innerHTML=pill(jd.status)+(jd.returncode!=null?(' (rc='+jd.returncode+')'):'');
        });
      });
    }).catch(function(){ statusEl.textContent='not connected — start `gradlescope serve` to use live controls'; });
  }
  var btn=document.getElementById('pr-run');
  if(btn){ btn.addEventListener('click', function(){ var t=document.getElementById('pr-task').value||'help';
    fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task:t})})
      .then(function(r){return r.json();}).then(function(d){ gsToast(d.message||'started'); poll(); }); }); }
  poll(); setInterval(poll, 2500);
})();
"""


def _page_processes(result: AnalysisResult, live) -> str:
    controls = (
        '<div class="controls">'
        '<input type="text" id="pr-task" value="build" style="min-width:240px"/>'
        '<button class="act" id="pr-run">Run Gradle</button>'
        '<span id="pr-conn" class="muted">connecting…</span>'
        "</div>"
    )
    body = (
        "<h1>Processes &amp; jobs</h1>"
        "<p class='muted'>Launched Gradle runs stream here and persist across refreshes. "
        "This page is live only under <code>gradlescope serve</code>.</p>"
        + controls
        + "<h2>Running Gradle daemons / processes</h2><div id='pr-daemons'></div>"
        + "<h2>Jobs</h2><div id='pr-jobs'></div>"
        + f"<script>{_PROCESSES_JS}</script>"
    )
    return page("Processes", body, "processes.html", live=live, generated_at=result.generated_at or "")


# --------------------------------------------------------------------------- #
# Runbooks & AI (unchanged)
# --------------------------------------------------------------------------- #


def _page_runbooks(result: AnalysisResult, runbooks, live) -> str:
    if not runbooks:
        return page("Runbooks", "<h1>Runbooks</h1><p class='muted'>No runbooks bundled.</p>", "runbooks.html", live=live)
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
        "<p class='muted'>Copy the context or any prompt into an LLM or coding agent. "
        "(Per-finding prompts are on the Findings page.)</p>",
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


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


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
        "architecture.html": _page_architecture(result, live),
        "plugins.html": _page_plugins(result, live),
        "processes.html": _page_processes(result, live),
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
