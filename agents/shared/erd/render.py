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
  <div class="ctl-group">
    <span class="group-label">Layout</span>
    <div class="seg" id="layout-seg">
      <button data-l="organic" class="on">Organic</button>
      <button data-l="star">Star</button>
      <button data-l="lr">Layered →</button>
      <button data-l="tb">Layered ↓</button>
    </div>
    <button class="minibtn reset-btn" id="reset-pos" title="Restore auto-layout for this view">⟲ Reset</button>
    <span class="saved-badge" id="saved-badge" title="Manual positions saved for this layout">saved</span>
    <label class="toggle" id="orth-wrap" title="Right-angle edge routing" style="opacity:.4"><input type="checkbox" id="orth-toggle" disabled> Orthogonal</label>
  </div>
  <div class="ctl-group">
    <span class="group-label">Display</span>
    <div class="seg" id="notation-seg">
      <button data-n="arrow" class="on" title="ThoughtSpot-style directional arrows">Arrow</button>
      <button data-n="crow" title="Crow's foot — shows cardinality">Crow's foot</button>
    </div>
    <select id="col-mode">
      <option value="collapsed">Collapsed</option>
      <option value="keys" selected>Join keys</option>
      <option value="flagged">Flagged only</option>
      <option value="all">All columns</option>
    </select>
    <label class="toggle"><input type="checkbox" id="findings-toggle" checked> Findings</label>
  </div>
  <div class="ctl-group">
    <span class="group-label">Search</span>
    <input id="finder" list="tablelist" placeholder="table name…" autocomplete="off">
    <datalist id="tablelist"></datalist>
  </div>
  <div class="ctl-group">
    <span class="group-label">Filter</span>
    <div class="filter-chips" id="filter-chips">
      <button class="fchip on" data-f="all">All</button>
      <button class="fchip" data-f="fact">Fact</button>
      <button class="fchip" data-f="dim">Dim</button>
      <button class="fchip" data-f="sql_view">SQL View</button>
      <button class="fchip" data-f="alias">Alias</button>
      <button class="fchip" data-f="rls">RLS</button>
      <button class="fchip" data-f="rls_subgraph">RLS subgraph</button>
    </div>
  </div>
  <div class="spacer"></div>
  <div class="ctl-group actions">
    <button class="minibtn" id="share-btn" title="Download self-contained HTML with positions and notes baked in">Share HTML</button>
    <button class="minibtn" id="clear-notes-btn" title="Remove all notes">Clear notes</button>
    <button class="minibtn" id="help-btn" title="Legend and keyboard shortcuts">? Help</button>
  </div>
</div>

<main>
  <div class="canvas-wrap">
    <svg id="svg" role="img" aria-label="Entity relationship diagram">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#9AA4B1"/></marker>
        <marker id="arrow-hot" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#C2382E"/></marker>
        <marker id="arrow-rls" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#C2382E"/></marker>
        <marker id="arrow-sel" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1E6FA8"/></marker>
      </defs>
      <g id="viewport"><g id="edges"></g><g id="nodes"></g></g>
    </svg>
    <div class="ctrls">
      <button id="zoom-in" title="Zoom in" aria-label="Zoom in">+</button>
      <button id="zoom-out" title="Zoom out" aria-label="Zoom out">−</button>
      <button id="zoom-fit" title="Fit to view" aria-label="Fit to view">⤢</button>
    </div>
    <div class="hint" id="hint">Click a table to focus \xb7 Shift-click to compare \xb7 Double-click for connected component \xb7 drag to pan \xb7 scroll to zoom</div>
  </div>
  <aside id="inspector"></aside>
</main>
<div class="help-drawer" id="help-drawer">
  <button class="close" id="help-close" aria-label="Close help">\xd7</button>
  <h2>ERD Help</h2>
  <div class="section-label">Legend</div>
  <div class="help-legend">
    <div class="swatch" style="background:var(--accent-soft);border-color:var(--accent)"></div><span><b>Fact table</b> — has measures or outgoing joins</span>
    <div class="swatch" style="background:var(--dim-fill);border-color:var(--dim-stroke)"></div><span><b>Dimension</b> — joined to by facts</span>
    <div class="swatch" style="background:#FBE9E7;border-color:#C2382E"></div><span><b>RLS secured</b> — has row-level security rules</span>
    <div class="swatch" style="background:#FEF3C7;border-color:#D97706"></div><span><b>In RLS path</b> — referenced in another table’s RLS expression</span>
    <div class="swatch" style="background:#F0FDFA;border-color:#0D9488"></div><span><b>SQL View</b> — backed by a SQL query, not a physical table</span>
    <div class="swatch" style="background:#F5F3FF;border-color:#7C3AED"></div><span><b>Alias</b> — a second reference to the same physical table</span>
  </div>
  <div class="section-label">Join lines</div>
  <div class="help-legend">
    <div style="width:30px;height:0;border-top:2px solid #9AA4B1"></div><span><b>Normal</b> — standard join (solid grey)</span>
    <div style="width:30px;height:0;border-top:2px dashed #9AA4B1"></div><span><b>Flagged</b> — fan-out: same dimension joined by 2+ facts (dashed grey)</span>
    <div style="width:30px;height:0;border-top:2px dashed #C2382E"></div><span><b>RLS edge</b> — target table has row-level security (dashed red)</span>
    <div style="width:30px;height:0;border-top:3px solid #1E6FA8"></div><span><b>Selected / path</b> — active selection or traced join path (solid blue)</span>
    <div style="width:30px;height:0;border-top:2px solid #D97706"></div><span><b>Annotated</b> — join has a user note attached (solid amber)</span>
  </div>
  <div class="section-label">Edge badges</div>
  <div class="help-legend">
    <div style="background:var(--accent);color:#fff;width:20px;height:16px;border-radius:3px;display:grid;place-items:center;font-size:9px;font-weight:700">M</div><span><b>Model-local</b> — join defined in this model only</span>
    <div style="background:var(--dim-fill);color:var(--muted);width:20px;height:16px;border-radius:3px;display:grid;place-items:center;font-size:9px;font-weight:700">T</div><span><b>Table-level</b> — reusable join from table TML</span>
  </div>
  <div class="section-label">Interactions</div>
  <div class="help-shortcut"><kbd>Click</kbd> table — focus on table and its neighbours</div>
  <div class="help-shortcut"><kbd>Shift+Click</kbd> table — compare multiple tables, trace join path</div>
  <div class="help-shortcut"><kbd>Double-click</kbd> table — show full connected component</div>
  <div class="help-shortcut"><kbd>Click</kbd> edge — inspect join definition</div>
  <div class="help-shortcut"><kbd>Click</kbd> empty space — return to model overview</div>
  <div class="help-shortcut"><kbd>Drag</kbd> table — reposition (auto-saved)</div>
  <div class="help-shortcut"><kbd>Scroll</kbd> — zoom in/out</div>
  <div class="help-shortcut"><kbd>/</kbd> — focus search box</div>
  <div class="help-shortcut"><kbd>?</kbd> — toggle this help panel</div>
  <div class="help-shortcut"><kbd>Esc</kbd> — close this panel</div>
  <div class="section-label">Reading the joins</div>
  <p class="sub">Each join carries a midpoint badge: <b style="background:#1E6FA8;color:#fff;border-radius:3px;padding:1px 5px;font-family:var(--mono)">M</b> = model-local (defined in this model only), <b style="background:#EDEFF2;color:#6B7480;border-radius:3px;padding:1px 5px;font-family:var(--mono)">T</b> = table-level (reusable, can ripple to other models). Switch <b>Notation</b> to <b>Crow's foot</b> to read cardinality instead of TS-style arrows. Click any join for its type, cardinality and definition.</p>
  <div class="section-label">Notes</div>
  <p class="sub">Add notes to any table or join via the side panel. Notes persist in your browser and travel with <b>Share HTML</b> exports.</p>
  <div class="section-label">Share HTML</div>
  <p class="sub">Downloads a self-contained HTML file with your current layout positions and notes baked in. The recipient sees your view on first load.</p>
</div>"""


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style></head>
<body>{body}
<script id="erd-data">window.__ERD_DATA__ = {data};</script>
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
