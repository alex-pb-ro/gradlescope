"""Small, dependency-free HTML building blocks and the page shell.

The whole dashboard is self-contained: CSS and JS are inlined so a generated
site works from ``file://`` with no network access. When served by the
gradlescope server, ``live=True`` injects a control bar that can trigger
re-scans and Gradle runs from the browser.
"""
from __future__ import annotations

from html import escape
from typing import Iterable, List, Sequence, Tuple

NAV: List[Tuple[str, str]] = [
    ("index.html", "Overview"),
    ("findings.html", "Findings"),
    ("modules.html", "Modules"),
    ("graph.html", "Graph"),
    ("architecture.html", "Architecture"),
    ("plugins.html", "Plugins"),
    ("processes.html", "Processes"),
    ("runbooks.html", "Runbooks"),
    ("ai.html", "AI"),
]

BASE_CSS = """
:root{
  --bg:#0f1420;--panel:#161d2e;--panel2:#1d2740;--text:#e6ebf5;--muted:#9aa6c0;
  --border:#283450;--accent:#4f7cff;--accent2:#7c9cff;
  --A:#16a34a;--B:#65a30d;--C:#d97706;--D:#ea580c;--F:#dc2626;
  --CRITICAL:#dc2626;--HIGH:#ea580c;--MEDIUM:#d97706;--LOW:#0ea5e9;--INFO:#64748b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent2);text-decoration:none}a:hover{text-decoration:underline}
header.top{display:flex;align-items:center;gap:20px;padding:14px 24px;background:var(--panel);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:10}
header.top .brand{font-weight:700;font-size:18px;letter-spacing:.3px}
header.top .brand span{color:var(--accent)}
nav.main{display:flex;gap:6px;flex-wrap:wrap}
nav.main a{padding:6px 12px;border-radius:8px;color:var(--muted)}
nav.main a.active{background:var(--panel2);color:var(--text)}
.toolbar{margin-left:auto;display:flex;gap:8px;align-items:center}
button.act{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:7px 14px;font-weight:600;cursor:pointer}
button.act.secondary{background:var(--panel2);color:var(--text);border:1px solid var(--border)}
button.act:hover{filter:brightness(1.08)}
main{padding:24px;max-width:1200px;margin:0 auto}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 12px}
.muted{color:var(--muted)}
.grid{display:grid;gap:16px}
.grid.cards{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:18px}
.card h3{margin:0 0 10px;font-size:13px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted)}
.stat{display:flex;flex-direction:column;gap:2px}
.stat .v{font-size:30px;font-weight:700}
.stat .s{color:var(--muted);font-size:13px}
.hero{display:grid;grid-template-columns:200px 1fr;gap:24px;align-items:center}
.gradebadge{font-size:13px;font-weight:700;padding:3px 10px;border-radius:999px;color:#fff;display:inline-block}
.grade-A{background:var(--A)}.grade-B{background:var(--B)}.grade-C{background:var(--C)}.grade-D{background:var(--D)}.grade-F{background:var(--F)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
tr:hover td{background:var(--panel2)}
.sev{font-weight:700;font-size:11px;padding:2px 8px;border-radius:6px;color:#fff;display:inline-block}
.sev-CRITICAL{background:var(--CRITICAL)}.sev-HIGH{background:var(--HIGH)}.sev-MEDIUM{background:var(--MEDIUM)}.sev-LOW{background:var(--LOW)}.sev-INFO{background:var(--INFO)}
.chart{max-width:100%;height:auto}
.chart .axis{stroke:var(--border)}
.chart .bar-label,.chart text{fill:var(--muted);font-size:11px}
.chart .hbar-label{fill:var(--text);font-size:12px}
.chart .hbar-value{fill:var(--muted);font-size:11px}
.chart .axis-label{fill:var(--muted);font-size:11px}
.gauge-value{fill:var(--text)!important;font-size:38px;font-weight:700}
.legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:8px;font-size:13px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{width:12px;height:12px;border-radius:3px;display:inline-block}
.controls{display:flex;gap:10px;margin:10px 0;flex-wrap:wrap}
input[type=search],select{background:var(--panel2);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:7px 10px}
pre{background:#0b1020;border:1px solid var(--border);border-radius:10px;padding:14px;overflow:auto;font-size:12.5px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.prompt{margin:14px 0}
.prompt .head{display:flex;justify-content:space-between;align-items:center;gap:10px}
.runbook{margin-bottom:30px}.runbook h2{border-bottom:1px solid var(--border);padding-bottom:6px}
footer{padding:24px;text-align:center;color:var(--muted);font-size:13px}
#toast{position:fixed;bottom:20px;right:20px;background:var(--panel2);border:1px solid var(--border);padding:12px 16px;border-radius:10px;opacity:0;transition:.3s;pointer-events:none}
#toast.show{opacity:1}
.gv-wrap{border:1px solid var(--border);border-radius:14px;background:var(--panel);overflow:hidden}
.gv-controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:12px;border-bottom:1px solid var(--border)}
.gv-controls label{font-size:13px;color:var(--muted);display:inline-flex;gap:6px;align-items:center}
#gv-canvas{display:block;width:100%;background:radial-gradient(circle at 30% 20%,#141b2c,#0d1320)}
.pluginpill{font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px;color:#fff;display:inline-block}
.zone-pill{font-size:11px;padding:2px 7px;border-radius:6px;display:inline-block;border:1px solid var(--border)}
.btn-mini{background:var(--panel2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:3px 9px;font-size:12px;cursor:pointer}
.btn-mini:hover{filter:brightness(1.15)}
.jobline{font-family:ui-monospace,Menlo,monospace;font-size:12px;white-space:pre-wrap}
.job{border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:12px;background:var(--panel)}
.job.running{border-left:3px solid var(--accent)}
.job.ok{border-left:3px solid var(--A)}
.job.failed{border-left:3px solid var(--F)}
.dot-status{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:6px}
"""

BASE_JS = """
function gsToast(msg){var t=document.getElementById('toast');if(!t)return;t.textContent=msg;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2600);}
function gsFilter(){var q=(document.getElementById('flt')||{}).value||'';var sev=(document.getElementById('sevf')||{}).value||'';q=q.toLowerCase();
  document.querySelectorAll('tr[data-row]').forEach(function(r){var hay=r.getAttribute('data-hay')||'';var s=r.getAttribute('data-sev')||'';
    var ok=(!q||hay.indexOf(q)>=0)&&(!sev||s===sev);r.style.display=ok?'':'none';});}
function gsCopy(id){var el=document.getElementById(id);if(!el)return;navigator.clipboard.writeText(el.innerText).then(function(){gsToast('Copied to clipboard');});}
window.GS_PROMPTS = window.GS_PROMPTS || {};
function gsCopyText(t){navigator.clipboard.writeText(t).then(function(){gsToast('Copied to clipboard');});}
function gsCopyPrompt(k){var t=(window.GS_PROMPTS||{})[k]; if(t){gsCopyText(t);} else {gsToast('No prompt available');}}
"""

LIVE_JS = """
function gsPost(path){gsToast('Running '+path+' ...');fetch(path,{method:'POST'}).then(function(r){return r.json();})
  .then(function(d){gsToast(d.message||'Done. Reloading...');setTimeout(function(){location.reload();},900);})
  .catch(function(e){gsToast('Error: '+e);});}
function gsRescan(){gsPost('/api/rescan');}
function gsRun(){var t=document.getElementById('gradletask');var task=t?t.value:'build';gsToast('Triggering gradle '+task);
  fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task:task})})
  .then(function(r){return r.json();}).then(function(d){gsToast(d.message||'Started');})
  .catch(function(e){gsToast('Error: '+e);});}
"""


def esc(value) -> str:
    return escape(str(value))


def grade_badge(grade: str) -> str:
    return f'<span class="gradebadge grade-{esc(grade)}">{esc(grade)}</span>'


def sev_badge(severity: str) -> str:
    return f'<span class="sev sev-{esc(severity)}">{esc(severity)}</span>'


def stat(value, label: str, sub: str = "") -> str:
    sub_html = f'<div class="s">{esc(sub)}</div>' if sub else ""
    return f'<div class="stat"><div class="v">{esc(value)}</div><div class="s">{esc(label)}</div>{sub_html}</div>'


def card(title: str, body: str, extra_class: str = "") -> str:
    head = f"<h3>{esc(title)}</h3>" if title else ""
    return f'<div class="card {extra_class}">{head}{body}</div>'


def table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{c}</td>" for c in row)  # cells are pre-rendered HTML
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _toolbar(live: bool) -> str:
    if not live:
        return ""
    return (
        '<div class="toolbar">'
        '<select id="gradletask" title="Gradle task">'
        '<option value="help">help</option>'
        '<option value="build">build</option>'
        '<option value="assemble">assemble</option>'
        '<option value="--dry-run build">build --dry-run</option>'
        "</select>"
        '<button class="act secondary" onclick="gsRun()">Run Gradle</button>'
        '<button class="act" onclick="gsRescan()">Re-scan</button>'
        "</div>"
    )


def page(title: str, body: str, active: str, live: bool = False, generated_at: str = "") -> str:
    nav = "".join(
        f'<a href="{href}" class="{"active" if href == active else ""}">{esc(label)}</a>'
        for href, label in NAV
    )
    scripts = BASE_JS + (LIVE_JS if live else "")
    gen = f'<span class="muted">· {esc(generated_at)}</span>' if generated_at else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='14' fill='%234f7cff'/%3E%3C/svg%3E"/>
<title>{esc(title)} · gradlescope</title>
<style>{BASE_CSS}</style></head>
<body>
<header class="top">
  <div class="brand">gradle<span>scope</span></div>
  <nav class="main">{nav}</nav>
  {_toolbar(live)}
</header>
<main>{body}</main>
<footer>Generated by gradlescope {gen} · build-tool-agnostic Gradle health</footer>
<div id="toast"></div>
<script>{scripts}</script>
</body></html>
"""
