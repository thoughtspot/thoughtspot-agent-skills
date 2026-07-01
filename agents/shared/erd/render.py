"""Render an assembled ERD bundle into a single self-contained HTML file."""
import json
import os

_HERE = os.path.dirname(__file__)


def _asset(name):
    with open(os.path.join(_HERE, name), "r", encoding="utf-8") as fh:
        return fh.read()


_BODY = """<header>
  <div class="brand">
    <span class="eyebrow">ThoughtSpot Model \xb7 ERD</span>
    <h1></h1>
  </div>
  <div class="stats">
    <div class="stat"><b id="s-tables">0</b><span>Tables</span></div>
    <div class="stat"><b id="s-joins">0</b><span>Joins</span></div>
    <div class="stat crit"><b id="s-crit">0</b><span>Critical</span></div>
    <div class="stat warn"><b id="s-warn">0</b><span>Warnings</span></div>
    <div class="stat rls"><b id="s-rls">0</b><span>RLS rules</span></div>
  </div>
</header>

<div class="controls">
  <div class="ctl"><label>Layout</label>
    <div class="seg" id="layout-seg">
      <button data-l="organic" class="on">Organic</button>
      <button data-l="star">Star</button>
      <button data-l="lr">Layered →</button>
      <button data-l="tb">Layered ↓</button>
    </div>
  </div>
  <label class="toggle" id="orth-wrap" title="Right-angle edge routing" style="opacity:.4"><input type="checkbox" id="orth-toggle" disabled> Orthogonal</label>
  <span class="saved-badge" id="saved-badge" title="Manual positions saved for this layout">saved</span>
  <button class="minibtn" id="reset-pos" title="Restore auto-layout for this view">⟲ Reset positions</button>
  <div class="ctl"><label>Notation</label>
    <div class="seg" id="notation-seg">
      <button data-n="arrow" class="on" title="ThoughtSpot-style directional arrows">Arrow</button>
      <button data-n="crow" title="Crow's foot — shows cardinality">Crow's foot</button>
    </div>
  </div>
  <div class="ctl"><label>Columns</label>
    <select id="col-mode">
      <option value="collapsed">Collapsed</option>
      <option value="keys">Join keys</option>
      <option value="flagged">Flagged only</option>
      <option value="all" selected>All columns</option>
    </select>
  </div>
  <div class="ctl finder"><label for="finder">Find</label>
    <input id="finder" list="tablelist" placeholder="table name…" autocomplete="off">
    <datalist id="tablelist"></datalist>
  </div>
  <div class="spacer"></div>
  <label class="toggle"><input type="checkbox" id="findings-toggle" checked> Findings</label>
  <label class="toggle rls"><input type="checkbox" id="rls-toggle"> RLS</label>
  <label class="toggle rls"><input type="checkbox" id="rlsonly-toggle"> Secured subgraph</label>
</div>

<main>
  <div class="canvas-wrap">
    <svg id="svg" role="img" aria-label="Entity relationship diagram">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#9AA4B1"/></marker>
        <marker id="arrow-hot" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#C2382E"/></marker>
        <marker id="arrow-rls" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#6B4FB8"/></marker>
        <marker id="arrow-sel" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1E6FA8"/></marker>
      </defs>
      <g id="viewport"><g id="edges"></g><g id="nodes"></g></g>
    </svg>
    <div class="ctrls">
      <button id="zoom-in" title="Zoom in" aria-label="Zoom in">+</button>
      <button id="zoom-out" title="Zoom out" aria-label="Zoom out">−</button>
      <button id="zoom-fit" title="Fit to view" aria-label="Fit to view">⤢</button>
    </div>
    <div class="hint" id="hint">Click a table to focus \xb7 Shift-click to compare \xb7 drag to pan \xb7 scroll to zoom</div>
  </div>
  <aside id="inspector"></aside>
</main>"""


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style></head>
<body>{body}
<script>window.__ERD_DATA__ = {data};</script>
<script>{js}</script>
</body></html>"""


def render_html(bundle, *, title="Model ERD"):
    css = _asset("renderer.css")
    js = _asset("renderer.js")
    data = json.dumps(bundle, ensure_ascii=False)
    return _TEMPLATE.format(title=title, css=css, js=js, body=_BODY, data=data)


def write_html(bundle, out_path, *, title="Model ERD"):
    html = render_html(bundle, title=title)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path
