"""Interactive dependency-graph visualization.

The layered layout is computed server-side in Python (fast, deterministic,
unit-testable). The browser renders it on a Canvas — which scales to thousands
of nodes — with pan/zoom, hover, focus-on-module, pattern highlighting, an
abstraction-layers mode, and on-demand labels so text never overlaps.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Dict, Optional

from gradlescope.analysis.architecture import sdp_violations
from gradlescope.graph.depgraph import DependencyGraph


def _short(path: str) -> str:
    if path in ("", ":"):
        return ":"
    return path.rsplit(":", 1)[-1]


def _out_depth(graph: DependencyGraph) -> Dict[str, int]:
    """Longest dependency chain length starting at each node (cycle-safe)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph.nodes}
    depth: Dict[str, int] = {}
    for start in sorted(graph.nodes):
        if color[start] != WHITE:
            continue
        stack = [(start, iter(sorted(graph.dependencies_of(start))))]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nb in it:
                if color[nb] == WHITE:
                    color[nb] = GRAY
                    stack.append((nb, iter(sorted(graph.dependencies_of(nb)))))
                    advanced = True
                    break
            if advanced:
                continue
            d = 0
            for nb in graph.dependencies_of(node):
                if color[nb] == BLACK:
                    d = max(d, 1 + depth[nb])
            depth[node] = d
            color[node] = BLACK
            stack.pop()
    return depth


def compute_layout(
    graph: DependencyGraph,
    metrics: Optional[Dict] = None,
    x_gap: int = 260,
    y_gap: int = 40,
    band_gap: int = 90,
    hub_threshold: int = 8,
    deep_threshold: int = 4,
) -> Dict:
    """Compute node positions for two layouts plus per-node pattern tags.

    - flow layout (``x``/``y``): foundational modules left, consumers right
    - layered layout (``lx``/``ly``): numbered abstraction layers, high layers
      on top (forced onto their level), concrete leaves at the bottom
    """
    depth = _out_depth(graph)
    max_layer = max(depth.values()) if depth else 0
    layers: Dict[int, list] = defaultdict(list)
    for n in sorted(graph.nodes):
        layers[depth[n]].append(n)

    flow_pos: Dict[str, tuple] = {}
    layered_pos: Dict[str, tuple] = {}
    for layer, members in layers.items():
        offset = (len(members) - 1) / 2.0
        for i, n in enumerate(members):
            flow_pos[n] = (layer * x_gap, (i - offset) * y_gap)
            # higher layer -> higher on screen (smaller y)
            layered_pos[n] = ((i - offset) * (x_gap // 2), (max_layer - layer) * band_gap)

    # cycle membership
    in_cycle = set()
    for comp in graph.find_cycles():
        in_cycle.update(comp)

    # SDP source modules (depend on a less stable module)
    sdp_sources = set()
    if metrics:
        for a, _b, _d in sdp_violations(graph, metrics):
            sdp_sources.add(a)

    idx: Dict[str, int] = {}
    nodes = []
    for n in sorted(graph.nodes):
        idx[n] = len(nodes)
        fx, fy = flow_pos[n]
        lx, ly = layered_pos[n]
        mm = metrics.get(n) if metrics else None
        fi, fo = graph.fan_in(n), graph.fan_out(n)
        tags = []
        if n in in_cycle:
            tags.append("cycle")
        if fi >= hub_threshold:
            tags.append("hub")
        if fi == 0 and fo == 0:
            tags.append("isolated")
        if fi == 1:
            tags.append("single")
        if depth[n] >= deep_threshold:
            tags.append("deep")
        if n in sdp_sources:
            tags.append("sdp")
        if mm and mm.zone == "zone-of-pain":
            tags.append("pain")
        nodes.append(
            {
                "id": n, "label": _short(n), "full": n,
                "x": round(fx, 1), "y": round(fy, 1),
                "lx": round(lx, 1), "ly": round(ly, 1),
                "layer": depth[n], "fi": fi, "fo": fo,
                "zone": (mm.zone if mm else ""),
                "inst": (mm.instability if mm else None),
                "abs": (mm.abstractness if mm else None),
                "t": tags,
            }
        )
    edges = []
    for n in graph.nodes:
        for t in graph.dependencies_of(n):
            edges.append([idx[n], idx[t]])
    return {"nodes": nodes, "edges": edges, "layer_count": max_layer + 1 if depth else 0}


_GRAPH_JS = r"""
(function(){
  var GD = __DATA__;
  var nodes = GD.nodes, edges = GD.edges, N = nodes.length;
  var outAdj=[], inAdj=[];
  for(var i=0;i<N;i++){ outAdj.push([]); inAdj.push([]); }
  for(var e=0;e<edges.length;e++){ outAdj[edges[e][0]].push(edges[e][1]); inAdj[edges[e][1]].push(edges[e][0]); }

  var cv=document.getElementById('gv-canvas'), ctx=cv.getContext('2d'), wrap=document.getElementById('gv-wrap');
  var statsEl=document.getElementById('gv-stats');
  var colorBy=document.getElementById('gv-colorby'), depthSel=document.getElementById('gv-depth');
  var search=document.getElementById('gv-search'), modeSel=document.getElementById('gv-mode'), hi_sel=document.getElementById('gv-highlight');
  var view={scale:1,ox:0,oy:0}, visible=null, focusIdx=-1, hoverIdx=-1, mode='flow';

  function zoneColor(z){ return ({'main-sequence':'#16a34a','zone-of-pain':'#dc2626','zone-of-uselessness':'#a855f7','off-sequence':'#d97706'})[z]||'#64748b'; }
  function instColor(v){ if(v==null)return '#64748b'; var r=Math.round(80+175*v),b=Math.round(255-175*v); return 'rgb('+r+',90,'+b+')'; }
  function faninColor(fi){ var t=Math.min(1,fi/20); return 'rgb('+Math.round(80+175*t)+',120,255)'; }
  function nodeColor(n){ var m=colorBy.value; if(m==='zone')return zoneColor(n.zone); if(m==='inst')return instColor(n.inst); return faninColor(n.fi); }
  function nodeRadius(n){ return 3+Math.min(9,Math.sqrt(n.fi)*1.6); }
  function nx(n){ return mode==='layers'? n.lx : n.x; }
  function ny(n){ return mode==='layers'? n.ly : n.y; }
  function wx(n){ return nx(n)*view.scale+view.ox; }
  function wy(n){ return ny(n)*view.scale+view.oy; }
  function hiTag(){ return hi_sel.value; }
  function tagged(n){ var t=hiTag(); return t==='' || (n.t && n.t.indexOf(t)>=0); }

  function resize(){ var dpr=window.devicePixelRatio||1, w=wrap.clientWidth, h=Math.max(520,window.innerHeight-300);
    cv.width=w*dpr; cv.height=h*dpr; cv.style.width=w+'px'; cv.style.height=h+'px'; ctx.setTransform(dpr,0,0,dpr,0,0); draw(); }
  function visIndices(){ if(visible)return Array.from(visible); var a=[]; for(var i=0;i<N;i++)a.push(i); return a; }
  function fit(){ var idxs=visIndices(); if(!idxs.length)return;
    var mnx=1e9,mny=1e9,mxx=-1e9,mxy=-1e9;
    for(var k=0;k<idxs.length;k++){ var n=nodes[idxs[k]]; var X=nx(n),Y=ny(n); if(X<mnx)mnx=X; if(Y<mny)mny=Y; if(X>mxx)mxx=X; if(Y>mxy)mxy=Y; }
    var w=cv.clientWidth,h=cv.clientHeight,pad=70,gw=Math.max(1,mxx-mnx),gh=Math.max(1,mxy-mny);
    view.scale=Math.min((w-pad)/gw,(h-pad)/gh,2.5); if(!isFinite(view.scale)||view.scale<=0)view.scale=1;
    view.ox=w/2-((mnx+mxx)/2)*view.scale; view.oy=h/2-((mny+mxy)/2)*view.scale; draw(); }
  function zoomBy(f){ var w=cv.clientWidth/2,h=cv.clientHeight/2; view.ox=w-(w-view.ox)*f; view.oy=h-(h-view.oy)*f; view.scale*=f; draw(); }

  function draw(){
    var w=cv.clientWidth,h=cv.clientHeight; ctx.clearRect(0,0,w,h);
    var visSet=visible; function vis(i){ return !visSet||visSet.has(i); }
    var ht=hiTag();
    // layer band guides (layers mode)
    if(mode==='layers'){ ctx.fillStyle='rgba(154,166,192,0.5)'; ctx.font='11px sans-serif';
      var seen={}; var idl=visIndices();
      for(var b=0;b<idl.length;b++){ var nb=nodes[idl[b]]; if(seen[nb.layer])continue; seen[nb.layer]=1;
        var yy=ny(nb)*view.scale+view.oy; ctx.strokeStyle='rgba(40,52,80,0.6)'; ctx.beginPath(); ctx.moveTo(0,yy); ctx.lineTo(w,yy); ctx.stroke();
        ctx.fillText('L'+nb.layer, 6, yy-3); } }
    // edges
    ctx.lineWidth=1; ctx.strokeStyle='rgba(150,160,190,0.16)'; ctx.beginPath();
    for(var e=0;e<edges.length;e++){ var a=edges[e][0],bb=edges[e][1]; if(!vis(a)||!vis(bb))continue;
      ctx.moveTo(wx(nodes[a]),wy(nodes[a])); ctx.lineTo(wx(nodes[bb]),wy(nodes[bb])); }
    ctx.stroke();
    var hl=hoverIdx>=0?hoverIdx:focusIdx;
    if(hl>=0){ ctx.lineWidth=1.6; ctx.strokeStyle='rgba(124,156,255,0.9)'; ctx.beginPath();
      for(var o=0;o<outAdj[hl].length;o++){ var t=outAdj[hl][o]; if(!vis(t))continue; ctx.moveTo(wx(nodes[hl]),wy(nodes[hl])); ctx.lineTo(wx(nodes[t]),wy(nodes[t])); }
      for(var p=0;p<inAdj[hl].length;p++){ var s=inAdj[hl][p]; if(!vis(s))continue; ctx.moveTo(wx(nodes[s]),wy(nodes[s])); ctx.lineTo(wx(nodes[hl]),wy(nodes[hl])); }
      ctx.stroke(); }
    var neigh=null; if(hl>=0){ neigh=new Set(); for(var oo=0;oo<outAdj[hl].length;oo++)neigh.add(outAdj[hl][oo]); for(var ii=0;ii<inAdj[hl].length;ii++)neigh.add(inAdj[hl][ii]); }
    var idxs=visIndices();
    for(var k=0;k<idxs.length;k++){ var i=idxs[k],n=nodes[i]; var on=tagged(n);
      ctx.beginPath(); ctx.arc(wx(n),wy(n),nodeRadius(n)*(on&&ht?1.4:1),0,6.2832);
      ctx.fillStyle = (ht&&on)?'#f59e0b':nodeColor(n);
      ctx.globalAlpha = (ht&&!on)?0.12 : ((neigh&&i!==hl&&!neigh.has(i))?0.35:1); ctx.fill(); ctx.globalAlpha=1; }
    // labels on demand
    var lab={}; if(idxs.length<=60||view.scale>1.1){ for(var k2=0;k2<idxs.length;k2++)lab[idxs[k2]]=1; }
    if(hl>=0){ lab[hl]=1; for(var o2=0;o2<outAdj[hl].length;o2++)lab[outAdj[hl][o2]]=1; for(var p2=0;p2<inAdj[hl].length;p2++)lab[inAdj[hl][p2]]=1; }
    ctx.fillStyle='#e6ebf5'; ctx.font='11px -apple-system,Segoe UI,Roboto,sans-serif';
    for(var key in lab){ var i3=+key; if(!vis(i3))continue; var n3=nodes[i3]; ctx.fillText(n3.label, wx(n3)+nodeRadius(n3)+3, wy(n3)+3); }
  }
  function nearest(mx,my){ var best=-1,bd=1e9,idxs=visIndices();
    for(var k=0;k<idxs.length;k++){ var i=idxs[k],dx=wx(nodes[i])-mx,dy=wy(nodes[i])-my,d=dx*dx+dy*dy; if(d<bd){bd=d;best=i;} } return bd<=225?best:-1; }
  function neighborhood(start,depth){ var set=new Set([start]),fr=[start];
    for(var d=0;d<depth;d++){ var nf=[]; for(var f=0;f<fr.length;f++){ var u=fr[f];
      outAdj[u].forEach(function(v){ if(!set.has(v)){set.add(v);nf.push(v);} }); inAdj[u].forEach(function(v){ if(!set.has(v)){set.add(v);nf.push(v);} }); } fr=nf; } return set; }
  function focus(i){ focusIdx=i; visible=neighborhood(i,+depthSel.value); stats(); fit(); }
  function reset(){ focusIdx=-1; visible=null; stats(); fit(); }
  function stats(){ var c=visible?visible.size:N; statsEl.textContent=c+' / '+N+' modules · '+edges.length+' edges'+(focusIdx>=0?(' · focus: '+nodes[focusIdx].full):''); }

  var dragging=false,lastX=0,lastY=0,moved=false;
  cv.addEventListener('mousedown',function(ev){ dragging=true;moved=false;lastX=ev.offsetX;lastY=ev.offsetY; });
  window.addEventListener('mouseup',function(){ dragging=false; });
  cv.addEventListener('mousemove',function(ev){ if(dragging){ view.ox+=ev.offsetX-lastX; view.oy+=ev.offsetY-lastY; lastX=ev.offsetX; lastY=ev.offsetY; moved=true; draw(); return; }
    var hh=nearest(ev.offsetX,ev.offsetY); if(hh!==hoverIdx){ hoverIdx=hh; cv.style.cursor=hh>=0?'pointer':'default'; cv.title=hh>=0?nodes[hh].full:''; draw(); } });
  cv.addEventListener('click',function(ev){ if(moved)return; var hh=nearest(ev.offsetX,ev.offsetY); if(hh>=0)focus(hh); });
  // zoom only with Ctrl/Cmd held, so the page scrolls normally otherwise
  cv.addEventListener('wheel',function(ev){ if(!(ev.ctrlKey||ev.metaKey))return; ev.preventDefault();
    var f=ev.deltaY<0?1.12:0.89, mx=ev.offsetX, my=ev.offsetY; view.ox=mx-(mx-view.ox)*f; view.oy=my-(my-view.oy)*f; view.scale*=f; draw(); },{passive:false});

  document.getElementById('gv-zin').addEventListener('click',function(){ zoomBy(1.2); });
  document.getElementById('gv-zout').addEventListener('click',function(){ zoomBy(0.83); });
  document.getElementById('gv-fit').addEventListener('click',fit);
  document.getElementById('gv-reset').addEventListener('click',reset);
  colorBy.addEventListener('change',draw); hi_sel.addEventListener('change',draw);
  modeSel.addEventListener('change',function(){ mode=modeSel.value; fit(); });
  depthSel.addEventListener('change',function(){ if(focusIdx>=0)focus(focusIdx); });
  search.addEventListener('change',function(){ var v=search.value.trim(); for(var i=0;i<N;i++){ if(nodes[i].full===v||nodes[i].label===v){ focus(i); return; } } });
  window.addEventListener('resize',resize);
  stats(); resize(); fit();
})();
"""


def render_graph_section(result) -> str:
    """Return the HTML body for the interactive graph (controls + canvas + script)."""
    layout = compute_layout(result.graph_obj, metrics=result.module_metrics)
    data_json = json.dumps(layout, separators=(",", ":")).replace("<", "\\u003c")
    options = "".join(
        f'<option value="{_escape(n["full"])}">' for n in sorted(layout["nodes"], key=lambda x: x["full"])
    )
    controls = (
        '<div class="gv-controls">'
        f'<input list="gv-nodes" id="gv-search" placeholder="Focus a module…"/>'
        f'<datalist id="gv-nodes">{options}</datalist>'
        '<label>Mode <select id="gv-mode"><option value="flow">Flow (L→R)</option>'
        '<option value="layers">Abstraction layers</option></select></label>'
        '<label>Highlight <select id="gv-highlight">'
        '<option value="">none</option><option value="cycle">cycles</option>'
        '<option value="deep">deep chains</option><option value="hub">hubs (high fan-in)</option>'
        '<option value="isolated">isolated</option><option value="single">single-consumer</option>'
        '<option value="sdp">SDP violations</option><option value="pain">zone of pain</option></select></label>'
        '<label>Depth <select id="gv-depth"><option>1</option><option selected>2</option>'
        '<option>3</option><option>4</option></select></label>'
        '<label>Color <select id="gv-colorby">'
        '<option value="fanin">fan-in</option><option value="zone">arch zone</option>'
        '<option value="inst">instability</option></select></label>'
        '<span id="gv-stats" class="muted"></span>'
        "</div>"
    )
    overlay = (
        '<div class="gv-overlay">'
        '<button class="btn-mini" id="gv-zin" title="Zoom in">+</button>'
        '<button class="btn-mini" id="gv-zout" title="Zoom out">−</button>'
        '<button class="btn-mini" id="gv-fit" title="Fit to view">Fit</button>'
        '<button class="btn-mini" id="gv-reset" title="Reset to whole graph">Reset</button>'
        "</div>"
    )
    hint = '<div class="gv-hint muted">Ctrl/⌘ + scroll to zoom · drag to pan · click a node to focus</div>'
    script = _GRAPH_JS.replace("__DATA__", data_json)
    return (
        f'<div id="gv-wrap" class="gv-wrap">{controls}'
        f'<div class="gv-canvas-wrap">{overlay}<canvas id="gv-canvas"></canvas></div>{hint}</div>'
        f"<script>{script}</script>"
    )


def _escape(s: str) -> str:
    from html import escape

    return escape(str(s), quote=True)
