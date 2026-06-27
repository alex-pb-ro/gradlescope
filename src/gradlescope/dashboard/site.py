"""Multi-page static dashboard generator.

``build_pages`` is pure (returns ``{filename: content}``) so it is unit-testable
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
    "CRITICAL": "#dc2626", "HIGH": "#ea580c", "MEDIUM": "#d97706",
    "LOW": "#0ea5e9", "INFO": "#64748b",
}
_ZONE_COLORS = {
    "main-sequence": "#16a34a", "zone-of-pain": "#dc2626",
    "zone-of-uselessness": "#a855f7", "off-sequence": "#d97706", "": "#64748b",
}


def _status_bar(result: AnalysisResult) -> dict:
    s = result.scorecard
    return {
        "score": s.overall, "grade": s.grade,
        "modules": result.summary["module_count"], "findings": s.total_findings,
    }


def _short_cat(name: str) -> str:
    return name.replace("configuration-", "config-").replace("dependency-", "dep-")


def _runbook_link(runbook: Optional[str]) -> str:
    return f'<a href="runbooks.html#{esc(runbook)}">{esc(runbook)}</a>' if runbook else ""


def _zone_pill(zone: str) -> str:
    color = _ZONE_COLORS.get(zone, "#64748b")
    return f'<span class="zone-pill" style="border-color:{color};color:{color}">{esc(zone or "n/a")}</span>'


def _prompt_btn(key: str) -> str:
    return f"<button class='btn-mini' onclick=\"gsCopyPrompt('{esc(key)}')\">Prompt</button>"


_PROMPTS_TAG = '<script src="prompts.js"></script>'


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
    langs = result.summary.get("language_versions") or result.summary.get("languages", {})
    if not langs:
        return '<p class="muted">No source languages detected.</p>'
    data = sorted(langs.items(), key=lambda kv: -kv[1])
    chart = charts.hbar_chart(data, width=480, color="#7c9cff", value_suffix=" mod", label_width=150)
    compat = result.summary.get("compat_modules", 0)
    note = (
        f'<p class="muted" style="margin-top:6px">{compat} module(s) compile to an older Java '
        "version than their toolchain (compatibility mode).</p>"
        if compat
        else ""
    )
    return chart + note


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
                f"<code>{esc(scope)}</code>",
                _runbook_link(f.runbook),
                _prompt_btn(f.key),
            ]
        )
    return rows


_FINDING_HEADERS = ["Sev", "Issue", "Scope", "Runbook", "AI"]


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
        + card("Languages &amp; versions", _languages_bars(result))
        + "</div>"
    )
    info_row = (
        '<div class="grid cards">'
        + card("Overall score trend", _trend(result, history))
        + card(
            "Dependency graph",
            "<div class='grid cards'>"
            + stat(g["module_count"], "modules") + stat(g["edge_count"], "edges")
            + stat(g["max_depth"], "max depth") + stat(g["cycle_count"], "cycles")
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
        table(_FINDING_HEADERS, _findings_rows(result.findings, 8))
        + '<p style="margin-top:10px"><a href="findings.html">See all findings →</a></p>',
    )
    body = (
        f"<h1>Build health overview</h1><p class='muted'>{esc(result.root)}</p>"
        f"{hero}{charts_row}{info_row}{top}{_PROMPTS_TAG}"
    )
    return page("Overview", body, "index.html", live=live, generated_at=result.generated_at or "", status=_status_bar(result))


# --------------------------------------------------------------------------- #
# Findings
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
            f"<td>{_runbook_link(f.runbook)}</td><td>{_prompt_btn(f.key)}</td></tr>"
        )
    table_html = (
        "<table><thead><tr><th>Sev</th><th>Issue</th><th>Rule</th><th>Scope</th>"
        "<th>Category</th><th>Runbook</th><th>AI</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    body = (
        f"<h1>Findings ({result.scorecard.total_findings})</h1>"
        "<p class='muted'>Each <b>Prompt</b> button copies a ready-to-paste AI prompt "
        "(Goal, Context, Locations, references, stats).</p>"
        f"{controls}{table_html}{_PROMPTS_TAG}"
    )
    return page("Findings", body, "findings.html", live=live, generated_at=result.generated_at or "", status=_status_bar(result))


# --------------------------------------------------------------------------- #
# Modules
# --------------------------------------------------------------------------- #


def _page_modules(result: AnalysisResult, live) -> str:
    modules = sorted(result.scorecard.modules.values(), key=lambda m: (m.score, m.path))
    metrics = result.module_metrics
    info = result.modules_info
    dist = charts.hbar_chart(
        [(m.path, m.score) for m in modules[:25]], width=720, max_value=100, label_width=220,
    )
    rows = []
    for m in modules:
        mm = metrics.get(m.path)
        mi = info.get(m.path, {})
        langs = ", ".join(mi.get("languages", [])) or "—"
        jvm = mi.get("jvm") or "—"
        compat = (
            f"<span style='color:var(--HIGH)'>{esc(mi.get('compat'))} ⚠</span>"
            if mi.get("runs_compat")
            else "—"
        )
        rows.append(
            [
                f"<code>{esc(m.path)}</code>", esc(m.score), grade_badge(m.grade), esc(m.finding_count),
                esc(langs), esc(jvm), compat,
                esc(mm.ca if mm else "-"), esc(mm.ce if mm else "-"),
                esc(mm.instability if mm else "-"), esc(mm.abstractness if mm else "-"),
                esc(mm.distance if mm else "-"), _zone_pill(mm.zone if mm else ""),
            ]
        )
    body = (
        f"<h1>Modules ({len(modules)})</h1>"
        + card("Lowest-scoring modules", dist)
        + "<h2>All modules (worst first)</h2>"
        + "<p class='muted'>JVM = Java toolchain · Compat = compiles to an older Java than the toolchain · "
        "Ca/Ce = afferent/efferent coupling · I = instability · A = abstractness · D = distance.</p>"
        + table(
            ["Module", "Score", "Grade", "Findings", "Languages", "JVM", "Compat", "Ca", "Ce", "I", "A", "D", "Zone"],
            rows,
        )
    )
    return page("Modules", body, "modules.html", live=live, generated_at=result.generated_at or "", status=_status_bar(result))


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #


def _page_graph(result: AnalysisResult, live) -> str:
    graph_findings = [f for f in result.findings if f.category in ("dependency-graph", "modularity")]
    body = (
        "<h1>Dependency graph</h1>"
        "<p class='muted'>Use <b>Highlight</b> to surface painpoints (cycles, deep chains, hubs, "
        "isolated/single-consumer, SDP violations). Switch to <b>Abstraction layers</b> for a "
        "stacked, numbered-layer view.</p>"
        + render_graph_section(result)
        + "<h2>Graph &amp; modularity findings</h2>"
        + table(_FINDING_HEADERS, _findings_rows(graph_findings))
        + _PROMPTS_TAG
    )
    return page("Graph", body, "graph.html", live=live, generated_at=result.generated_at or "", status=_status_bar(result))


# --------------------------------------------------------------------------- #
# Architecture
# --------------------------------------------------------------------------- #

_GLOSSARY = [
    ("Ca", "Afferent coupling", "Number of modules that depend on this module (incoming). Higher = more responsibility / wider blast radius."),
    ("Ce", "Efferent coupling", "Number of modules this module depends on (outgoing)."),
    ("I", "Instability", "I = Ce / (Ca + Ce). 0 = maximally stable (only depended upon), 1 = maximally unstable (only depends on others)."),
    ("A", "Abstractness", "A = abstract types / total types. 0 = fully concrete, 1 = fully abstract."),
    ("D", "Distance from the main sequence", "D = |A + I − 1|. 0 means the module sits on the ideal line A + I = 1; larger D is worse."),
    ("SDP", "Stable Dependencies Principle", "Depend in the direction of stability: a module should only depend on modules at least as stable (lower I) as itself."),
    ("SAP", "Stable Abstractions Principle", "A stable module (low I) should be abstract (high A) so it can be extended without modification."),
]


def _page_architecture(result: AnalysisResult, live) -> str:
    from gradlescope.analysis.architecture import scatter_points

    metrics = result.module_metrics
    arch = result.architecture or {}
    vals = list(metrics.values())
    scatter = charts.scatter_chart(
        scatter_points(metrics), width=460, height=380, diagonal=True,
        x_label="Instability (I)", y_label="Abstractness (A)",
    )
    zones = arch.get("zones", {})
    zone_cards = "".join(
        card(z.replace("-", " ").title(), stat(zones.get(z, 0), "modules"))
        for z in ["main-sequence", "off-sequence", "zone-of-pain", "zone-of-uselessness"]
    )

    def top_by(attr, n=20):
        ranked = sorted(vals, key=lambda m: -getattr(m, attr))[:n]
        return charts.hbar_chart([(m.path, getattr(m, attr)) for m in ranked], width=520, label_width=200)

    metric_charts = (
        '<div class="grid cards">'
        + card("Furthest from main sequence (D)", top_by("distance"))
        + card("Most unstable (I)", top_by("instability"))
        + card("Most abstract (A)", top_by("abstractness"))
        + card("Highest fan-in (Ca)", top_by("ca"))
        + card("Highest fan-out (Ce)", top_by("ce"))
        + "</div>"
    )
    glossary = "<dl class='glossary'>" + "".join(
        f"<dt>{esc(abbr)} — {esc(name)}</dt><dd>{esc(desc)}</dd>" for abbr, name, desc in _GLOSSARY
    ) + "</dl>"
    sdp_rows = [
        [f"<code>{esc(a)}</code>", "→", f"<code>{esc(b)}</code>", esc(d)]
        for a, b, d in result.sdp_violations[:50]
    ]
    sdp_section = (
        "<h2>Stable Dependencies Principle violations</h2>"
        + (
            table(["From", "", "Depends on (less stable)", "ΔI"], sdp_rows)
            if sdp_rows
            else "<p class='muted'>None 🎉</p>"
        )
    )
    body = (
        "<h1>Clean Architecture metrics</h1>"
        "<p class='muted'>After Robert C. Martin. The ideal is the main sequence A + I = 1.</p>"
        + f'<div class="grid cards">{zone_cards}</div>'
        + card(
            f"Main sequence (avg distance D = {esc(arch.get('avg_distance', 'n/a'))})",
            scatter
            + '<div class="legend"><span><i style="background:#16a34a"></i>near</span>'
            '<span><i style="background:#d97706"></i>off</span>'
            '<span><i style="background:#dc2626"></i>far</span></div>',
        )
        + metric_charts
        + sdp_section
        + card("Metric glossary", glossary)
    )
    return page("Architecture", body, "architecture.html", live=live, generated_at=result.generated_at or "", status=_status_bar(result))


# --------------------------------------------------------------------------- #
# Plugins
# --------------------------------------------------------------------------- #


def _page_plugins(result: AnalysisResult, live) -> str:
    pov = result.plugins or {"plugins": [], "category_counts": {}, "distinct": 0, "version_conflicts": 0}
    cc = pov.get("category_counts", {})
    cards_html = (
        '<div class="grid cards">'
        + card("Distinct plugins", stat(pov.get("distinct", 0), "applied across modules"))
        + card("External", stat(cc.get("external", 0), "from public repos"))
        + card("Convention", stat(cc.get("convention", 0), "in-house (buildSrc/build-logic)"))
        + card("Internal", stat(cc.get("internal", 0), "other in-house"))
        + card("Core", stat(cc.get("core", 0), "Gradle built-in"))
        + card("Version conflicts", stat(pov.get("version_conflicts", 0), "applied with >1 version"))
        + "</div>"
    )
    controls = (
        '<div class="controls"><input type="search" id="flt" placeholder="Filter plugins…" oninput="gsFilter()"/></div>'
    )
    rows = []
    for i, p in enumerate(pov.get("plugins", [])):
        color = category_color(p["category"])
        pill = f'<span class="pluginpill" style="background:{color}">{esc(p["category"])}</span>'
        versions = ", ".join(p["versions"]) if p["versions"] else "—"
        versions = (
            f"<span style='color:var(--HIGH)'>{esc(versions)} ⚠</span>" if p.get("version_conflict") else esc(versions)
        )
        mods = p.get("modules", [])
        shown = mods[:800]
        more = f" <span class='muted'>+{len(mods)-len(shown)} more</span>" if len(mods) > len(shown) else ""
        modlist = (
            f"<div class='plugin-modules' id='pm{i}'><div class='modlist'>"
            + "".join(f"<code>{esc(m)}</code>" for m in shown)
            + f"</div>{more}</div>"
        )
        hay = (p["id"] + " " + p["category"]).lower()
        rows.append(
            f'<tr data-row data-hay="{esc(hay)}">'
            f"<td><code>{esc(p['id'])}</code></td><td>{pill}</td>"
            f"<td><span class='expander' onclick=\"document.getElementById('pm{i}').classList.toggle('show')\">"
            f"{esc(p['count'])} ▾</span>{modlist}</td>"
            f"<td>{versions}</td></tr>"
        )
    body = (
        "<h1>Plugins</h1>"
        "<p class='muted'>Classified as core / convention (this repo) / internal / external. "
        "Click a module count to list the modules using that plugin.</p>"
        + cards_html + controls
        + "<h2>All plugins (by usage)</h2>"
        + "<table><thead><tr><th>Plugin id</th><th>Type</th><th>Modules</th><th>Versions</th></tr></thead>"
        + f"<tbody>{''.join(rows)}</tbody></table>"
    )
    return page("Plugins", body, "plugins.html", live=live, generated_at=result.generated_at or "", status=_status_bar(result))


# --------------------------------------------------------------------------- #
# Processes
# --------------------------------------------------------------------------- #

_PROCESSES_JS = r"""
(function(){
  var offsets={}, lineStore={}, MAXDOM=4000;
  var conn=document.getElementById('pr-conn');
  function esc(t){var d=document.createElement('div');d.textContent=t==null?'':t;return d.innerHTML;}
  function pill(s){return '<span class="dot-status" style="background:'+({running:'#4f7cff',ok:'#16a34a',failed:'#dc2626',cancelled:'#d97706'}[s]||'#64748b')+'"></span>'+s;}

  function renderSystem(s){
    var el=document.getElementById('pr-sys'); if(!el)return;
    var load=s.load_avg?(' · load '+s.load_avg.join(' / ')):''; var lp=s.load_pct!=null?(' ('+s.load_pct+'% of '+s.cpu_count+' cores)'):'';
    var mem=s.mem_pct!=null?(' · mem '+s.mem_pct+'%'):'';
    el.textContent='CPU cores: '+(s.cpu_count||'?')+load+lp+mem;
  }
  // daemons: reconcile rows by pid to avoid layout jump
  function renderDaemons(procs){
    var tb=document.getElementById('pr-daemons-body'); if(!tb)return;
    var seen={}; procs=procs||[];
    procs.forEach(function(p){ seen[p.pid]=1; var id='dm-'+p.pid; var tr=document.getElementById(id);
      if(!tr){ tr=document.createElement('tr'); tr.id=id; tr.innerHTML='<td class="c-pid"></td><td class="c-kind"></td><td class="c-up"></td><td class="c-cpu"></td><td class="c-mem"></td><td class="c-cmd"></td>'; tb.appendChild(tr); }
      tr.querySelector('.c-pid').textContent=p.pid; tr.querySelector('.c-kind').textContent=p.kind;
      tr.querySelector('.c-up').textContent=p.etime; tr.querySelector('.c-cpu').textContent=p.cpu;
      tr.querySelector('.c-mem').textContent=p.mem; tr.querySelector('.c-cmd').innerHTML='<code>'+esc(p.command)+'</code>'; });
    Array.prototype.slice.call(tb.children).forEach(function(tr){ var pid=tr.id.slice(3); if(!seen[pid]) tb.removeChild(tr); });
    var none=document.getElementById('pr-daemons-none'); if(none) none.style.display=procs.length?'none':'block';
  }
  function atBottom(pre){ return pre.scrollHeight-pre.scrollTop-pre.clientHeight < 40; }
  function applyFilter(box, jid){
    var q=(box.querySelector('.jf').value||'').toLowerCase(); var pre=box.querySelector('pre');
    var lines=lineStore[jid]||[]; var view = q? lines.filter(function(l){return l.toLowerCase().indexOf(q)>=0;}) : lines;
    if(view.length>MAXDOM){ var hidden=view.length-MAXDOM; pre.textContent='… '+hidden+' earlier lines hidden (use search or Open log) …\n'+view.slice(-MAXDOM).join('\n'); }
    else pre.textContent=view.join('\n');
  }
  function ensureJob(j){
    var id='job-'+j.id, box=document.getElementById(id);
    if(!box){ box=document.createElement('div'); box.id=id; box.className='job '+j.status;
      box.innerHTML='<div class="head" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><b>Job '+j.id+'</b><code>gradle '+esc(j.task)+'</code><span class="jstat"></span>'+
        '<span style="margin-left:auto;display:flex;gap:6px"><input class="jf" placeholder="search log…" style="min-width:160px"/>'+
        '<button class="btn-mini jcancel">Stop</button><button class="btn-mini jopen">Open log</button></span></div>'+
        '<pre class="jobline" style="max-height:320px;overflow:auto;margin-top:8px"></pre>';
      document.getElementById('pr-jobs').prepend(box); offsets[j.id]=0; lineStore[j.id]=[];
      box.querySelector('.jf').addEventListener('input', function(){ applyFilter(box, j.id); });
      box.querySelector('.jcancel').addEventListener('click', function(){ fetch('/api/jobs/'+j.id+'/cancel',{method:'POST'}).then(function(){gsToast('Cancelling '+j.id);}); });
      box.querySelector('.jopen').addEventListener('click', function(){ fetch('/api/jobs/'+j.id+'/open',{method:'POST'}).then(function(r){return r.json();}).then(function(d){gsToast(d.path?('Revealed '+d.path):'No file');}); });
    }
    box.className='job '+j.status;
    box.querySelector('.jstat').innerHTML=pill(j.status)+(j.returncode!=null?(' (rc='+j.returncode+')'):'');
    var cancel=box.querySelector('.jcancel'); if(cancel) cancel.style.display=(j.status==='running')?'':'none';
    return box;
  }
  function poll(){
    fetch('/api/system').then(function(r){return r.json();}).then(renderSystem).catch(function(){});
    fetch('/api/processes').then(function(r){return r.json();}).then(function(d){ conn.textContent='connected'; renderDaemons(d.processes);
      (d.jobs||[]).forEach(function(j){ var box=ensureJob(j);
        fetch('/api/jobs/'+j.id+'?offset='+(offsets[j.id]||0)).then(function(r){return r.json();}).then(function(jd){
          if(jd&&jd.lines&&jd.lines.length){ lineStore[j.id]=(lineStore[j.id]||[]).concat(jd.lines); offsets[j.id]=jd.next_offset;
            var pre=box.querySelector('pre'); var stick=atBottom(pre); applyFilter(box,j.id); if(stick) pre.scrollTop=pre.scrollHeight; }
        });
      });
    }).catch(function(){ conn.textContent='not connected — start `gradlescope serve`'; });
  }
  var btn=document.getElementById('pr-run');
  if(btn){ btn.addEventListener('click',function(){ var t=document.getElementById('pr-task').value||'help';
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
        "<p class='muted'>Live only under <code>gradlescope serve</code>. Logs stream incrementally "
        "and persist across refreshes; use a job's search box or <b>Open log</b> for massive logs.</p>"
        + card("System performance", "<div id='pr-sys' class='muted'>…</div>")
        + controls
        + "<h2>Running Gradle daemons / processes</h2>"
        + "<table><thead><tr><th>PID</th><th>Kind</th><th>Uptime</th><th>CPU%</th><th>MEM%</th><th>Command</th></tr></thead>"
        + "<tbody id='pr-daemons-body'></tbody></table>"
        + "<p id='pr-daemons-none' class='muted'>No running Gradle daemons/processes detected.</p>"
        + "<h2>Jobs</h2><div id='pr-jobs'></div>"
        + f"<script>{_PROCESSES_JS}</script>"
    )
    return page("Processes", body, "processes.html", live=live, generated_at=result.generated_at or "", status=_status_bar(result))


# --------------------------------------------------------------------------- #
# Runbooks & AI
# --------------------------------------------------------------------------- #


def _page_runbooks(result: AnalysisResult, runbooks, live) -> str:
    if not runbooks:
        return page("Runbooks", "<h1>Runbooks</h1><p class='muted'>No runbooks bundled.</p>",
                    "runbooks.html", live=live, status=_status_bar(result))
    toc = "".join(f'<li><a href="#{esc(rid)}">{esc(rb["title"])}</a></li>' for rid, rb in runbooks.items())
    sections = "".join(
        f'<section class="runbook" id="{esc(rid)}">{rb["html"]}</section>' for rid, rb in runbooks.items()
    )
    body = f"<h1>Runbooks</h1><ul>{toc}</ul>{sections}"
    return page("Runbooks", body, "runbooks.html", live=live, generated_at=result.generated_at or "", status=_status_bar(result))


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
    return page("AI", "".join(blocks), "ai.html", live=live, generated_at=result.generated_at or "", status=_status_bar(result))


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def _prompts_js(result: AnalysisResult) -> str:
    payload = json.dumps(ai.prompts_by_key(result)).replace("<", "\\u003c")
    return "window.GS_PROMPTS = " + payload + ";"


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
        "prompts.js": _prompts_js(result),
    }


def render_site(
    result: AnalysisResult,
    output_dir: str,
    history: Optional[List[Dict]] = None,
    live: bool = False,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    pages = build_pages(result, history=history, live=live)
    for name, content in pages.items():
        with open(os.path.join(output_dir, name), "w", encoding="utf-8") as fh:
            fh.write(content)
    with open(os.path.join(output_dir, "data.json"), "w", encoding="utf-8") as fh:
        fh.write(json_report.to_json(result))
    with open(os.path.join(output_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown_report.to_markdown(result))
    with open(os.path.join(output_dir, "ai.md"), "w", encoding="utf-8") as fh:
        fh.write(ai.ai_markdown(result))
    return output_dir
