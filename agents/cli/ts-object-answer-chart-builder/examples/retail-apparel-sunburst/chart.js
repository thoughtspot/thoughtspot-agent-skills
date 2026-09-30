/**
 * Retail Apparel - sales sunburst (region > state > item type)
 *
 * Available Columns this chart expects the search to select:
 *   "region"       // ATTRIBUTE
 *   "state"        // ATTRIBUTE
 *   "item type"    // ATTRIBUTE
 *   "Total sales"  // MEASURE
 * --- END ---
 */

// ============================ Customize ==================================

// Data mode:
//   'auto'   live data, sample rows when there is none  (default)
//   'live'   live only - explicit message when the query returns nothing
//   'sample' sample only - ignore any attached search
const DATA_MODE = 'auto';

// The three rings, inner to outer, then the measure they are sized by.
// These must match the column names your search selects. Whitespace and case
// are normalised before matching, and each falls back to a keyword search, so
// "Item Type" and "item type" both resolve.
const COL_L1    = 'region';
const COL_L2    = 'state';
const COL_L3    = 'item type';
const COL_VALUE = 'Total sales';

// Label on the centre disk, which also carries the grand total.
const ROOT_LABEL = 'All regions';

// One hue per top-level category; children inherit a lighter tint of the parent
// hue, so ring depth is legible without a legend. Categories not listed here
// cycle through PALETTE.
const REGION_COLORS = {
  'West':      '#4C6EF5',
  'East':      '#12B886',
  'Midwest':   '#F59F00',
  'Southwest': '#AE3EC9',
  'South':     '#FA5252',
};
const PALETTE = ['#4C6EF5', '#12B886', '#F59F00', '#AE3EC9', '#FA5252', '#15AABF', '#7950F2'];
const BG = '#FAFAFB';

// Tried in order until one defines window.Plotly. If your cluster allowlists a
// specific CDN - or none - put a self-hosted URL first.
const PLOTLY_SOURCES = [
  'https://cdn.plot.ly/plotly-2.35.2.min.js',
  'https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js',
];
const SCRIPT_TIMEOUT_MS = 12000;

// ========================== End customize ================================

// -- Sample rows (mode C fallback) ----------------------------------------
const SAMPLE_SCHEMA = [
  { name: COL_L1,    type: 'dimension' },
  { name: COL_L2,    type: 'dimension' },
  { name: COL_L3,    type: 'dimension' },
  { name: COL_VALUE, type: 'measure', defAggFn: 'sum' },
];

const SAMPLE_DATA = [
  { 'region': 'West',      'state': 'Montana',       'item type': 'Jackets', 'Total sales': 8420000 },
  { 'region': 'West',      'state': 'Montana',       'item type': 'Vests',   'Total sales': 3180000 },
  { 'region': 'West',      'state': 'Montana',       'item type': 'Bags',    'Total sales': 3940000 },
  { 'region': 'West',      'state': 'Nevada',        'item type': 'Jackets', 'Total sales': 7860000 },
  { 'region': 'West',      'state': 'Nevada',        'item type': 'Vests',   'Total sales': 2940000 },
  { 'region': 'West',      'state': 'Nevada',        'item type': 'Bags',    'Total sales': 4210000 },
  { 'region': 'West',      'state': 'California',    'item type': 'Jackets', 'Total sales': 3120000 },
  { 'region': 'West',      'state': 'California',    'item type': 'Vests',   'Total sales': 1870000 },
  { 'region': 'West',      'state': 'California',    'item type': 'Bags',    'Total sales': 1640000 },
  { 'region': 'East',      'state': 'New Jersey',    'item type': 'Jackets', 'Total sales': 4680000 },
  { 'region': 'East',      'state': 'New Jersey',    'item type': 'Vests',   'Total sales': 2510000 },
  { 'region': 'East',      'state': 'New Jersey',    'item type': 'Bags',    'Total sales': 2890000 },
  { 'region': 'East',      'state': 'Massachusetts', 'item type': 'Jackets', 'Total sales': 3340000 },
  { 'region': 'East',      'state': 'Massachusetts', 'item type': 'Vests',   'Total sales': 1720000 },
  { 'region': 'East',      'state': 'Massachusetts', 'item type': 'Bags',    'Total sales': 1980000 },
  { 'region': 'Midwest',   'state': 'Missouri',      'item type': 'Jackets', 'Total sales': 3010000 },
  { 'region': 'Midwest',   'state': 'Missouri',      'item type': 'Vests',   'Total sales': 1880000 },
  { 'region': 'Midwest',   'state': 'Missouri',      'item type': 'Bags',    'Total sales': 1910000 },
  { 'region': 'Midwest',   'state': 'Illinois',      'item type': 'Jackets', 'Total sales': 2740000 },
  { 'region': 'Midwest',   'state': 'Illinois',      'item type': 'Vests',   'Total sales': 1620000 },
  { 'region': 'Midwest',   'state': 'Illinois',      'item type': 'Bags',    'Total sales': 1780000 },
  { 'region': 'Southwest', 'state': 'Arizona',       'item type': 'Jackets', 'Total sales': 2360000 },
  { 'region': 'Southwest', 'state': 'Arizona',       'item type': 'Vests',   'Total sales': 1410000 },
  { 'region': 'Southwest', 'state': 'Arizona',       'item type': 'Bags',    'Total sales': 1520000 },
  { 'region': 'Southwest', 'state': 'Colorado',      'item type': 'Jackets', 'Total sales': 2210000 },
  { 'region': 'Southwest', 'state': 'Colorado',      'item type': 'Vests',   'Total sales': 1340000 },
  { 'region': 'Southwest', 'state': 'Colorado',      'item type': 'Bags',    'Total sales': 1290000 },
  { 'region': 'South',     'state': 'Georgia',       'item type': 'Jackets', 'Total sales': 1980000 },
  { 'region': 'South',     'state': 'Georgia',       'item type': 'Vests',   'Total sales': 1090000 },
  { 'region': 'South',     'state': 'Georgia',       'item type': 'Bags',    'Total sales': 1130000 },
];

// -- Cell unwrapping -------------------------------------------------------
// Some clusters hand back { value, formatted } objects rather than primitives,
// and `.value` is occasionally a method. An unwrapped object reaching String()
// silently becomes "[object Object]" and every wedge collapses into one.
function cellVal(v) {
  if (v == null || typeof v !== 'object') return v;
  try {
    const raw = typeof v.value === 'function' ? v.value() : v.value;
    return raw ?? v._value ?? v.v ?? v.formatted ?? v.f ?? null;
  } catch (e) {
    return v._value ?? null;
  }
}

// -- Reaching the host ------------------------------------------------------
// `viz` is whatever the host puts in scope. Do NOT read it as `globalThis.viz`
// alone: ThoughtSpot's documented entry point is the bare identifier
// (`const { muze, getDataFromSearchQuery } = viz;`), and a host that hands the
// JS tab its `viz` as a function parameter rather than a global leaves
// `globalThis.viz` undefined. That failure is silent and doubly bad - the chart
// quietly falls back to sample rows AND emitRenderCompletedEvent() throws into
// an empty catch, so the tile never reports in and the host paints its own
// "Chart did not render".
//
// `typeof` on a `let`/`const` still in its temporal dead zone throws, which is
// why this is wrapped rather than just guarded.
function getViz() {
  try {
    if (typeof viz !== 'undefined' && viz) return viz;
  } catch (e) { /* TDZ or no such binding */ }
  try {
    if (globalThis.viz) return globalThis.viz;
  } catch (e) {}
  return null;
}

// -- Load rows (mode C) ----------------------------------------------------
function loadRows() {
  const viz_ = getViz() || {};
  if (DATA_MODE !== 'sample') {
    try {
      const dm = viz_.getDataFromSearchQuery && viz_.getDataFromSearchQuery();
      const raw = dm && dm.getData();
      if (raw && raw.data && raw.data.length) {
        return {
          source: 'live',
          schema: raw.schema,
          rows: raw.data.map(function (arr) {
            const o = {};
            raw.schema.forEach(function (c, i) { o[c.name] = cellVal(arr[i]); });
            return o;
          }),
        };
      }
    } catch (err) {
      console.warn('[sunburst] live data unavailable:', err);
    }
    if (DATA_MODE === 'live') return { source: 'empty', schema: [], rows: [] };
  }
  return { source: 'sample', schema: SAMPLE_SCHEMA, rows: SAMPLE_DATA };
}

// -- Column resolution -----------------------------------------------------
// ThoughtSpot ships non-breaking spaces inside display names, so an === match
// against a name typed with a normal space misses without any error at all.
// Normalise whitespace first, then fall back to keyword matching. The nbsp is
// written as an escape, not a literal: this file gets pasted through a browser
// textarea, and a literal non-breaking space in source is exactly the character
// that gets silently normalised in transit - which would disable the guard it
// exists to provide.
function norm(s) {
  return String(s == null ? '' : s).replace(/\u00A0/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
}

function resolveCol(schema, exact) {
  const keywords = Array.prototype.slice.call(arguments, 2);
  const names = schema.map(function (c) { return norm(c.name); });
  let i = names.indexOf(norm(exact));
  if (i >= 0) return i;
  for (const kw of keywords) {
    const re = new RegExp(kw, 'i');
    i = names.findIndex(function (n) { return re.test(n); });
    if (i >= 0) return i;
  }
  return -1;
}

function toRows(payload) {
  const schema = payload.schema || [];
  const rows = payload.rows || [];
  if (!schema.length || !rows.length) return [];

  const k1 = schema[resolveCol(schema, COL_L1, '^region$', 'region')];
  const k2 = schema[resolveCol(schema, COL_L2, '^state$', 'state', 'province')];
  const k3 = schema[resolveCol(schema, COL_L3, 'item.*type', 'category', 'product.*type')];
  const kV = schema[resolveCol(schema, COL_VALUE, 'total.*sales', 'sales', 'revenue', 'amount')];

  // No value column means nothing can be sized - fall through to the empty state
  // rather than drawing a ring of zero-width wedges.
  if (!kV) return [];

  return rows.map(function (r) {
    return {
      l1: k1 ? String(cellVal(r[k1.name]) ?? 'Unknown') : 'Unknown',
      l2: k2 ? String(cellVal(r[k2.name]) ?? 'Unknown') : 'Unknown',
      l3: k3 ? String(cellVal(r[k3.name]) ?? 'Unknown') : 'Unknown',
      v: Number(cellVal(r[kV.name]) ?? 0),
    };
  }).filter(function (d) { return Number.isFinite(d.v) && d.v > 0; });
}

// -- Hierarchy -------------------------------------------------------------
function buildHierarchy(rows) {
  const root = { name: ROOT_LABEL, children: [], _index: new Map() };
  for (const r of rows) {
    let n1 = root._index.get(r.l1);
    if (!n1) {
      n1 = { name: r.l1, children: [], _index: new Map() };
      root.children.push(n1); root._index.set(r.l1, n1);
    }
    let n2 = n1._index.get(r.l2);
    if (!n2) {
      n2 = { name: r.l2, children: [], _index: new Map() };
      n1.children.push(n2); n1._index.set(r.l2, n2);
    }
    let n3 = n2._index.get(r.l3);
    if (!n3) {
      n3 = { name: r.l3, value: 0 };
      n2.children.push(n3); n2._index.set(r.l3, n3);
    }
    n3.value += r.v;
  }
  const strip = function (n) { delete n._index; (n.children || []).forEach(strip); };
  strip(root);
  return root;
}

// Roll leaf values up. Plotly's branchvalues:'total' requires parents to equal
// the sum of their children, or wedges silently overlap.
function aggregate(node) {
  if (!node.children || !node.children.length) return node.value || 0;
  node.value = node.children.reduce(function (s, c) { return s + aggregate(c); }, 0);
  return node.value;
}

function sortTree(node) {
  if (node.children) {
    node.children.sort(function (a, b) { return (b.value || 0) - (a.value || 0); });
    node.children.forEach(sortTree);
  }
}

// -- Color helpers ---------------------------------------------------------
function lighten(hex, t) {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!m) return hex;
  const r = parseInt(m[1], 16), g = parseInt(m[2], 16), b = parseInt(m[3], 16);
  return 'rgb(' + Math.round(r + (255 - r) * t) + ','
               + Math.round(g + (255 - g) * t) + ','
               + Math.round(b + (255 - b) * t) + ')';
}

// Compact currency for the center disk: 8420000 -> "$8.4M". d3's SI format uses
// "G" for billions, which reads wrong on a sales figure, so this is hand-rolled.
function fmtCompact(n) {
  const v = Number(n) || 0;
  const abs = Math.abs(v);
  if (abs >= 1e9) return '$' + (v / 1e9).toFixed(1) + 'B';
  if (abs >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M';
  if (abs >= 1e3) return '$' + (v / 1e3).toFixed(0) + 'K';
  return '$' + v.toFixed(0);
}

function flatten(rootNode) {
  const ids = [], labels = [], parents = [], values = [], colors = [];
  let paletteIdx = 0;

  function walk(node, parentId, depth, baseColor) {
    const id = parentId ? parentId + '|' + node.name : node.name;
    ids.push(id);
    labels.push(node.name);
    parents.push(parentId);
    values.push(node.value || 0);

    let color;
    if (depth === 0) color = BG;
    else if (depth === 1) color = baseColor;
    else color = lighten(baseColor, depth === 2 ? 0.30 : 0.55);
    colors.push(color);

    (node.children || []).forEach(function (c) {
      const childBase = depth === 0
        ? (REGION_COLORS[c.name] || PALETTE[paletteIdx++ % PALETTE.length])
        : baseColor;
      walk(c, id, depth + 1, childBase);
    });
  }

  walk(rootNode, '', 0, PALETTE[0]);
  return { ids: ids, labels: labels, parents: parents, values: values, colors: colors };
}

// -- CDN load --------------------------------------------------------------
// Bounded on purpose. A blocked CDN usually fires onerror, but a request that
// hangs fires neither event - and an unsettled promise here means the await
// below never returns, emitRenderCompletedEvent never fires, and the host shows
// its own "Chart did not render" with no way to tell why. Always reach a
// terminal state, then say which source failed and how.
function injectScript(src, timeoutMs) {
  return new Promise(function (resolve, reject) {
    const s = document.createElement('script');
    let settled = false;
    const finish = function (err) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (err) { try { s.remove(); } catch (e) {} return reject(err); }
      resolve();
    };
    const timer = setTimeout(function () {
      finish(new Error('timed out after ' + timeoutMs + 'ms: ' + src));
    }, timeoutMs);
    s.src = src;
    s.onload = function () { finish(null); };
    s.onerror = function () { finish(new Error('blocked or unreachable: ' + src)); };
    (document.head || document.documentElement).appendChild(s);
  });
}

// chart.html carries the primary <script src> - that is the shape ThoughtSpot
// documents for CDN libraries, and the one this chart's predecessor shipped with.
// It may still be in flight when the JS tab evaluates, so wait on a tag that is
// already in the DOM before injecting a second copy of the same library.
function waitForExistingTag(timeoutMs) {
  if (!document.querySelector('script[src*="plotly"], script[src*="plot.ly"]')) {
    return Promise.resolve(false);
  }
  return new Promise(function (resolve) {
    const step = 50;
    let waited = 0;
    const timer = setInterval(function () {
      waited += step;
      if (globalThis.Plotly) { clearInterval(timer); resolve(true); }
      else if (waited >= timeoutMs) { clearInterval(timer); resolve(false); }
    }, step);
  });
}

async function ensurePlotly() {
  if (globalThis.Plotly) return globalThis.Plotly;
  if (await waitForExistingTag(SCRIPT_TIMEOUT_MS)) return globalThis.Plotly;
  const failures = [];
  for (const src of PLOTLY_SOURCES) {
    try {
      await injectScript(src, SCRIPT_TIMEOUT_MS);
      if (globalThis.Plotly) return globalThis.Plotly;
      failures.push('loaded but window.Plotly missing: ' + src);
    } catch (err) {
      failures.push(String((err && err.message) || err));
    }
  }
  throw new Error(
    'Plotly could not be loaded from any source.\n' + failures.join('\n')
    + '\n\nIf this cluster blocks external CDNs, host plotly.min.js yourself and'
    + '\nput its URL first in PLOTLY_SOURCES at the top of this file.'
  );
}

// -- Mount -----------------------------------------------------------------
// The host assembles the three tabs itself and the order is not contractual.
// If chart.js evaluates before the HTML tab's markup is in the DOM - or if the
// HTML tab is empty because someone pasted only the JS - every getElementById
// returns null, Plotly throws on a null container, and the tile goes blank with
// no visible error. Build whatever is missing so the JS tab alone is enough.
function ensureMount() {
  let chart = document.getElementById('chart');
  if (!chart) {
    chart = document.createElement('div');
    chart.id = 'chart';
    (document.body || document.documentElement).appendChild(chart);
  }
  let wrapper = chart.querySelector('.wrapper');
  if (!wrapper) {
    wrapper = document.createElement('div');
    wrapper.className = 'wrapper';
    chart.appendChild(wrapper);
  }
  let crumb = document.getElementById('breadcrumb');
  if (!crumb) {
    crumb = document.createElement('div');
    crumb.id = 'breadcrumb';
    crumb.className = 'breadcrumb';
    wrapper.appendChild(crumb);
  }
  let svgWrap = chart.querySelector('.svg-wrap');
  if (!svgWrap) {
    svgWrap = document.createElement('div');
    svgWrap.className = 'svg-wrap';
    wrapper.appendChild(svgWrap);
  }
  let stage = document.getElementById('sunburst');
  if (!stage) {
    stage = document.createElement('div');
    stage.id = 'sunburst';
    svgWrap.appendChild(stage);
  }

  // A percentage height only resolves against a parent with a definite one, and
  // a ThoughtSpot tile's <body> has none. `#chart { height: 100% }` then computes
  // to zero, Plotly draws into a 0px box, and the tile is blank with nothing in
  // the console - the chart is "working", it just has no room. chart.css declares
  // the html/body chain; this measures the result in case the host wraps #chart
  // in something else, and falls back to the viewport (the tile's own iframe).
  if (chart.clientHeight < 40) {
    chart.style.height = '100vh';
    chart.style.minHeight = '260px';
  }

  return { chart: chart, stage: stage, wrap: svgWrap, crumb: crumb };
}

// -- Render-complete signal ------------------------------------------------
// Fires at most once, on every exit path, plus a watchdog. The Liveboard PDF
// export blocks until every tile reports in, so a tile that never signals costs
// the whole board its export.
let renderSignalled = false;
let watchdog = 0;
function signalRenderComplete() {
  if (renderSignalled) return;
  renderSignalled = true;
  if (watchdog) { clearTimeout(watchdog); watchdog = 0; }
  const v = getViz();
  try {
    v.events.emitRenderCompletedEvent();
  } catch (e) {
    // Never silent. A swallowed failure here is exactly how a tile hangs the
    // Liveboard PDF export with nothing in the console to explain it.
    console.warn('[sunburst] emitRenderCompletedEvent unavailable:', e);
  }
}

// -- Module state ----------------------------------------------------------
// Plain assignment into module-scope bindings from boot, never `const el = ...`
// inside a function - that shadowing is what makes a chart render once and then
// break on the next resize tick.
let chartEl = null;
let stageEl = null;
let wrapEl = null;
let crumbEl = null;
let currentLevelId = ROOT_LABEL;
let hier = null;
let resizeObs = null;

// Plotly's `responsive: true` only listens to window.resize. A Liveboard tile
// changes size without the window changing at all - drag-resize, layout edits,
// PDF export - and the SVG then keeps its old width and gets clipped by the
// tile. Watch the container itself. Plain assignment to the module-scope
// binding, never a local `const resizeObs` inside the function.
function observeResize() {
  // Watch the wrapper, not the element Plotly draws into - resizing the plot
  // changes the stage's own box, and observing that feeds the observer its own
  // output.
  const target = wrapEl || stageEl;
  if (resizeObs || !globalThis.ResizeObserver || !target) return;
  let pending = 0;
  resizeObs = new ResizeObserver(function () {
    if (pending) cancelAnimationFrame(pending);
    pending = requestAnimationFrame(function () {
      pending = 0;
      try { globalThis.Plotly.Plots.resize(stageEl); } catch (e) { /* pre-plot */ }
    });
  });
  resizeObs.observe(target);
}

// -- Renderers -------------------------------------------------------------
function renderBreadcrumb(idPath) {
  if (!crumbEl) return;
  const parts = String(idPath).split('|');
  crumbEl.innerHTML = '';
  parts.forEach(function (name, idx) {
    if (idx > 0) {
      const sep = document.createElement('span');
      sep.className = 'crumb-sep';
      sep.textContent = '>';
      crumbEl.appendChild(sep);
    }
    const c = document.createElement('span');
    const isTail = idx === parts.length - 1;
    const isRootAlone = parts.length === 1;
    c.className = 'crumb' + (idx === 0 ? ' root' : '') + (isTail && !isRootAlone ? ' tail' : '');
    c.textContent = name;
    c.title = name;
    if (!isTail) {
      const targetId = parts.slice(0, idx + 1).join('|');
      c.addEventListener('click', function () { zoomToId(targetId); });
    }
    crumbEl.appendChild(c);
  });
}

function zoomToId(id) {
  currentLevelId = id;
  globalThis.Plotly.restyle(stageEl, { level: [id] });
  renderBreadcrumb(id);
}

async function renderChart(flat) {
  const Plotly = await ensurePlotly();

  // Per-point template array: the root disk carries the grand total, every other
  // wedge shows just its label. Plotly accepts texttemplate as an array indexed
  // the same way as ids/labels/values.
  const texttemplate = flat.parents.map(function (parent, i) {
    return parent === ''
      ? '%{label}<br><b>' + fmtCompact(flat.values[i]) + '</b>'
      : '%{label}';
  });

  const trace = {
    type: 'sunburst',
    ids: flat.ids,
    labels: flat.labels,
    parents: flat.parents,
    values: flat.values,
    branchvalues: 'total',
    marker: { colors: flat.colors, line: { color: BG, width: 1.5 } },
    hovertemplate:
      '<b>%{label}</b><br>'
      + 'Total sales: $%{value:.3s}<br>'
      + '%{percentParent:.1%} of parent, %{percentRoot:.1%} of total'
      + '<extra></extra>',
    texttemplate: texttemplate,
    insidetextorientation: 'radial',
    textfont: { family: 'Inter, system-ui, sans-serif', size: 11 },
    outsidetextfont: { family: 'Inter, system-ui, sans-serif', color: '#1B1B2F' },
    maxdepth: 4,
    rotation: 90,
    sort: false,
  };

  const layout = {
    margin: { l: 4, r: 4, t: 4, b: 34 },
    paper_bgcolor: BG,
    plot_bgcolor: BG,
    font: { family: 'Inter, system-ui, sans-serif', color: '#1B1B2F', size: 12 },
    showlegend: false,
    hoverlabel: {
      bgcolor: '#ffffff',
      bordercolor: 'rgba(76,110,245,0.28)',
      font: { family: 'Inter, system-ui, sans-serif', size: 12, color: '#1B1B2F' },
      align: 'left',
    },
    transition: { duration: 420, easing: 'cubic-in-out' },
  };

  const gd = await Plotly.newPlot(stageEl, [trace], layout, {
    responsive: true,
    displayModeBar: false,
  });

  observeResize();

  gd.on('plotly_sunburstclick', function (e) {
    const pt = e && e.points && e.points[0];
    if (!pt) return;
    if (pt.id === currentLevelId && pt.parent !== undefined) {
      currentLevelId = pt.parent || ROOT_LABEL;
    } else {
      currentLevelId = pt.id;
    }
    renderBreadcrumb(currentLevelId);
  });
}

// -- Boot ------------------------------------------------------------------
// Watchdog first: whatever happens below, the host hears back.
watchdog = setTimeout(signalRenderComplete, SCRIPT_TIMEOUT_MS * 2 + 4000);

try {
  const mount = ensureMount();
  chartEl = mount.chart;
  stageEl = mount.stage;
  wrapEl = mount.wrap;
  crumbEl = mount.crumb;

  const payload = loadRows();
  if (payload.source === 'sample') chartEl.classList.add('is-sample');

  const rows = toRows(payload);

  if (!rows.length) {
    stageEl.innerHTML = '<div class="chart-empty">No rows returned by the search</div>';
    renderBreadcrumb(ROOT_LABEL);
  } else {
    hier = buildHierarchy(rows);
    aggregate(hier);
    sortTree(hier);
    renderBreadcrumb(ROOT_LABEL);
    await renderChart(flatten(hier));
  }
} catch (err) {
  console.error('[sunburst] render failed:', err);
  // Paint the real error into the tile. The BYOC sandbox otherwise replaces it
  // with a generic "Chart did not render", which says nothing actionable.
  // Fall back through stage -> #chart -> body so this cannot itself throw on a
  // null container, which is how the original failure stayed invisible.
  const host = stageEl || chartEl || document.getElementById('chart') || document.body;
  if (host) {
    host.textContent = '';
    const pre = document.createElement('pre');
    pre.className = 'chart-error';
    pre.textContent = (err && err.stack) || String(err);
    host.appendChild(pre);
  }
}

signalRenderComplete();
