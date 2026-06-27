"""Interactive dependency-graph visualization.

The layered layout is computed server-side in Python (fast, deterministic,
unit-testable). The browser renders it on a Canvas — which scales to thousands
of nodes — with pan/zoom, hover, focus-on-module (upstream/downstream), and
on-demand labels so text never overlaps.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Dict, Optional

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
) -> Dict:
    """Layered left→right layout: foundational modules (no deps) on the left,
    consumers on the right. Returns nodes (with x/y) and edges (index pairs)."""
    depth = _out_depth(graph)
    layers: Dict[int, list] = defaultdict(list)
    for n in sorted(graph.nodes):
        layers[depth[n]].append(n)

    positions: Dict[str, tuple] = {}
    for layer, members in layers.items():
        offset = (len(members) - 1) / 2.0
        for i, n in enumerate(members):
            positions[n] = (layer * x_gap, (i - offset) * y_gap)

    idx: Dict[str, int] = {}
    nodes = []
    for n in sorted(graph.nodes):
        idx[n] = len(nodes)
        x, y = positions[n]
        mm = metrics.get(n) if metrics else None
        nodes.append(
            {
                "id": n,
                "label": _short(n),
                "full": n,
                "x": round(x, 1),
                "y": round(y, 1),
                "fi": graph.fan_in(n),
                "fo": graph.fan_out(n),
                "layer": depth[n],
                "zone": (mm.zone if mm else ""),
                "inst": (mm.instability if mm else None),
            }
        )
    edges = []
    for n in graph.nodes:
        for t in graph.dependencies_of(n):
            edges.append([idx[n], idx[t]])
    return {"nodes": nodes, "edges": edges, "layer_count": (max(layers) + 1 if layers else 0)}


_GRAPH_JS = r"""
(function(){
  var GD = __DATA__;
  var nodes = GD.nodes, edges = GD.edges;
  var N = nodes.length;
  // adjacency (indices)
  var outAdj = [], inAdj = [];
  for (var i=0;i<N;i++){ outAdj.push([]); inAdj.push([]); }
  for (var e=0;e<edges.length;e++){ outAdj[edges[e][0]].push(edges[e][1]); inAdj[edges[e][1]].push(edges[e][0]); }

  var cv = document.getElementById('gv-canvas');
  var ctx = cv.getContext('2d');
  var wrap = document.getElementById('gv-wrap');
  var statsEl = document.getElementById('gv-stats');
  var colorBy = document.getElementById('gv-colorby');
  var depthSel = document.getElementById('gv-depth');
  var search = document.getElementById('gv-search');

  var view = {scale:1, ox:0, oy:0};
  var visible = null;     // Set of visible indices (null = all)
  var focusIdx = -1;
  var hoverIdx = -1;

  function zoneColor(z){ return ({'main-sequence':'#16a34a','zone-of-pain':'#dc2626','zone-of-uselessness':'#a855f7','off-sequence':'#d97706'})[z] || '#64748b'; }
  function instColor(v){ if(v==null) return '#64748b'; var r=Math.round(80+175*v), b=Math.round(255-175*v); return 'rgb('+r+',90,'+b+')'; }
  function faninColor(fi){ var t=Math.min(1, fi/20); var r=Math.round(80+175*t); return 'rgb('+r+',120,255)'; }
  function nodeColor(n){ var m=colorBy.value; if(m==='zone') return zoneColor(n.zone); if(m==='inst') return instColor(n.inst); return faninColor(n.fi); }
  function nodeRadius(n){ return 3 + Math.min(9, Math.sqrt(n.fi)*1.6); }

  function resize(){
    var dpr = window.devicePixelRatio||1;
    var w = wrap.clientWidth, h = Math.max(480, window.innerHeight-260);
    cv.width = w*dpr; cv.height = h*dpr; cv.style.width=w+'px'; cv.style.height=h+'px';
    ctx.setTransform(dpr,0,0,dpr,0,0);
    draw();
  }

  function visIndices(){ if(visible) return visible; var a=[]; for(var i=0;i<N;i++) a.push(i); return a; }

  function fit(){
    var idxs = visIndices();
    if(!idxs.length) return;
    var minX=1e9,minY=1e9,maxX=-1e9,maxY=-1e9;
    for(var k=0;k<idxs.length;k++){ var n=nodes[idxs[k]]; if(n.x<minX)minX=n.x; if(n.y<minY)minY=n.y; if(n.x>maxX)maxX=n.x; if(n.y>maxY)maxY=n.y; }
    var w=cv.clientWidth, h=cv.clientHeight, pad=60;
    var gw=Math.max(1,maxX-minX), gh=Math.max(1,maxY-minY);
    view.scale = Math.min((w-pad)/gw, (h-pad)/gh, 2.5); if(!isFinite(view.scale)||view.scale<=0) view.scale=1;
    view.ox = w/2 - ((minX+maxX)/2)*view.scale;
    view.oy = h/2 - ((minY+maxY)/2)*view.scale;
    draw();
  }

  function wx(n){ return n.x*view.scale + view.ox; }
  function wy(n){ return n.y*view.scale + view.oy; }

  function draw(){
    var w=cv.clientWidth, h=cv.clientHeight;
    ctx.clearRect(0,0,w,h);
    var visSet = visible ? visible : null;
    function vis(i){ return !visSet || visSet.has(i); }
    // edges
    ctx.lineWidth = 1; ctx.strokeStyle='rgba(150,160,190,0.18)';
    ctx.beginPath();
    for(var e=0;e<edges.length;e++){ var a=edges[e][0],b=edges[e][1]; if(!vis(a)||!vis(b)) continue;
      ctx.moveTo(wx(nodes[a]),wy(nodes[a])); ctx.lineTo(wx(nodes[b]),wy(nodes[b])); }
    ctx.stroke();
    // highlight edges of hovered/focus node
    var hi = hoverIdx>=0?hoverIdx:focusIdx;
    if(hi>=0){ ctx.lineWidth=1.6; ctx.strokeStyle='rgba(124,156,255,0.9)'; ctx.beginPath();
      for(var o=0;o<outAdj[hi].length;o++){ var t=outAdj[hi][o]; if(!vis(t))continue; ctx.moveTo(wx(nodes[hi]),wy(nodes[hi])); ctx.lineTo(wx(nodes[t]),wy(nodes[t])); }
      for(var p=0;p<inAdj[hi].length;p++){ var s=inAdj[hi][p]; if(!vis(s))continue; ctx.moveTo(wx(nodes[s]),wy(nodes[s])); ctx.lineTo(wx(nodes[hi]),wy(nodes[hi])); }
      ctx.stroke(); }
    // nodes — precompute the hovered node's neighbour set once (O(N+deg), not O(N*deg))
    var neigh = null;
    if(hi>=0){ neigh=new Set(); for(var oo=0;oo<outAdj[hi].length;oo++) neigh.add(outAdj[hi][oo]); for(var ii=0;ii<inAdj[hi].length;ii++) neigh.add(inAdj[hi][ii]); }
    var idxs = visIndices();
    for(var k=0;k<idxs.length;k++){ var i=idxs[k]; var n=nodes[i];
      ctx.beginPath(); ctx.arc(wx(n),wy(n),nodeRadius(n),0,6.2832);
      ctx.fillStyle = nodeColor(n); ctx.globalAlpha = (neigh && i!==hi && !neigh.has(i))?0.35:1; ctx.fill(); ctx.globalAlpha=1;
    }
    // labels: only when few visible, when zoomed in, plus hovered neighborhood
    var labelSet = {};
    if(idxs.length <= 60 || view.scale > 1.1){ for(var k2=0;k2<idxs.length;k2++) labelSet[idxs[k2]]=1; }
    if(hi>=0){ labelSet[hi]=1; for(var o2=0;o2<outAdj[hi].length;o2++) labelSet[outAdj[hi][o2]]=1; for(var p2=0;p2<inAdj[hi].length;p2++) labelSet[inAdj[hi][p2]]=1; }
    ctx.fillStyle='#e6ebf5'; ctx.font='11px -apple-system,Segoe UI,Roboto,sans-serif';
    for(var key in labelSet){ var i3=+key; if(!vis(i3))continue; var n3=nodes[i3]; ctx.fillText(n3.label, wx(n3)+nodeRadius(n3)+3, wy(n3)+3); }
  }

  function nearest(mx,my){
    var best=-1, bd=1e9; var idxs=visIndices();
    for(var k=0;k<idxs.length;k++){ var i=idxs[k]; var dx=wx(nodes[i])-mx, dy=wy(nodes[i])-my; var d=dx*dx+dy*dy; if(d<bd){bd=d;best=i;} }
    return bd<=225? best : -1;  // within 15px
  }

  function neighborhood(start, depth){
    var set=new Set([start]); var frontier=[start];
    for(var d=0; d<depth; d++){ var nf=[];
      for(var f=0;f<frontier.length;f++){ var u=frontier[f];
        outAdj[u].forEach(function(v){ if(!set.has(v)){set.add(v); nf.push(v);} });
        inAdj[u].forEach(function(v){ if(!set.has(v)){set.add(v); nf.push(v);} }); }
      frontier=nf; }
    return set;
  }

  function focus(i){ focusIdx=i; visible = neighborhood(i, +depthSel.value); updateStats(); fit(); }
  function reset(){ focusIdx=-1; visible=null; updateStats(); fit(); }
  function updateStats(){ var c = visible?visible.size:N; statsEl.textContent = c+' / '+N+' modules · '+edges.length+' edges'+(focusIdx>=0?(' · focus: '+nodes[focusIdx].full):''); }

  // interactions
  var dragging=false, lastX=0, lastY=0, moved=false;
  cv.addEventListener('mousedown', function(ev){ dragging=true; moved=false; lastX=ev.offsetX; lastY=ev.offsetY; });
  window.addEventListener('mouseup', function(){ dragging=false; });
  cv.addEventListener('mousemove', function(ev){
    if(dragging){ view.ox+=ev.offsetX-lastX; view.oy+=ev.offsetY-lastY; lastX=ev.offsetX; lastY=ev.offsetY; moved=true; draw(); return; }
    var h=nearest(ev.offsetX,ev.offsetY); if(h!==hoverIdx){ hoverIdx=h; cv.style.cursor=h>=0?'pointer':'default'; cv.title=h>=0?nodes[h].full:''; draw(); }
  });
  cv.addEventListener('click', function(ev){ if(moved) return; var h=nearest(ev.offsetX,ev.offsetY); if(h>=0) focus(h); });
  cv.addEventListener('wheel', function(ev){ ev.preventDefault(); var f=ev.deltaY<0?1.12:0.89; var mx=ev.offsetX,my=ev.offsetY;
    view.ox = mx - (mx-view.ox)*f; view.oy = my - (my-view.oy)*f; view.scale*=f; draw(); }, {passive:false});

  document.getElementById('gv-reset').addEventListener('click', reset);
  document.getElementById('gv-fit').addEventListener('click', fit);
  colorBy.addEventListener('change', draw);
  depthSel.addEventListener('change', function(){ if(focusIdx>=0) focus(focusIdx); });
  search.addEventListener('change', function(){ var v=search.value.trim(); for(var i=0;i<N;i++){ if(nodes[i].full===v || nodes[i].label===v){ focus(i); return; } } });

  window.addEventListener('resize', resize);
  updateStats(); resize(); fit();
})();
"""


def render_graph_section(result) -> str:
    """Return the HTML body for the interactive graph (controls + canvas + script)."""
    layout = compute_layout(result.graph_obj, metrics=result.module_metrics)
    # Escape "<" so a value containing "</script>" cannot break out of the tag.
    data_json = json.dumps(layout, separators=(",", ":")).replace("<", "\\u003c")
    options = "".join(
        f'<option value="{_escape(n["full"])}">' for n in sorted(layout["nodes"], key=lambda x: x["full"])
    )
    controls = (
        '<div class="gv-controls">'
        f'<input list="gv-nodes" id="gv-search" placeholder="Focus a module…"/>'
        f'<datalist id="gv-nodes">{options}</datalist>'
        '<label>Depth <select id="gv-depth"><option>1</option><option selected>2</option>'
        '<option>3</option><option>4</option></select></label>'
        '<label>Color <select id="gv-colorby">'
        '<option value="fanin">fan-in</option>'
        '<option value="zone">arch zone</option>'
        '<option value="inst">instability</option></select></label>'
        '<button class="act secondary" id="gv-fit">Fit</button>'
        '<button class="act" id="gv-reset">Whole graph</button>'
        '<span id="gv-stats" class="muted"></span>'
        "</div>"
    )
    script = _GRAPH_JS.replace("__DATA__", data_json)
    return (
        f'<div id="gv-wrap" class="gv-wrap">{controls}'
        f'<canvas id="gv-canvas"></canvas></div>'
        f"<script>{script}</script>"
    )


def _escape(s: str) -> str:
    from html import escape

    return escape(str(s), quote=True)
