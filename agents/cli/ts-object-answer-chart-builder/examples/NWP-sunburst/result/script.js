/**
 * Available Columns:
 * "Policy Status"  // ATTRIBUTE (depth-1: colored per STATUS_COLORS)
 * "Policy Region"  // ATTRIBUTE (depth-2: lightened from parent's base)
 * "Product"        // ATTRIBUTE (depth-3: lightened further from parent's base)
 * "Policy Count"   // MEASURE
 * --- END ---
 */

// ── Column Name Constants ──
const COL_L1    = 'Policy Status';
const COL_L2    = 'Policy Region';
const COL_L3    = 'Product';
const COL_VALUE = 'Policy Count';

// Named per-status colors (depth-1 ring). Unknown statuses fall back to PALETTE.
const STATUS_COLORS = {
  'Active':      '#292763',  // dark navy
  'Cancelled':   '#D8294B',  // crimson
  'Expired':     '#7176E5',  // periwinkle
  'Non-Renewed': '#E5A422',  // amber
};
const PALETTE = [
  '#292763', '#D8294B', '#7176E5', '#E5A422',
];

// ── Sample dataset for standalone preview (uncomment to use) ──
// const SAMPLE = {
//   schema: [
//     { name: COL_L1, type: 'ATTRIBUTE' },
//     { name: COL_L2, type: 'ATTRIBUTE' },
//     { name: COL_L3, type: 'ATTRIBUTE' },
//     { name: COL_VALUE, type: 'MEASURE' },
//   ],
//   data: [
//     ['Active',     'Southeast',  'General Liability',      233],
//     ['Active',     'Southeast',  'Commercial Property',    180],
//     ['Active',     'Southeast',  'Workers Compensation',   220],
//     ['Active',     'Southeast',  'Commercial Auto',        140],
//     ['Active',     'Midwest',    'Commercial Property',    160],
//     ['Active',     'Midwest',    'Workers Compensation',   110],
//     ['Active',     'Midwest',    'Commercial Auto',         80],
//     ['Active',     'Southwest',  'Workers Compensation',    30],
//     ['Active',     'Southwest',  'Commercial Auto',         55],
//     ['Active',     'Mid-Atlantic','Workers Compensation',   16],
//     ['Active',     'Mid-Atlantic','Commercial Property',    40],
//     ['Active',     'West',       'Commercial Property',     70],
//     ['Active',     'West',       'Workers Compensation',    50],
//     ['Expired',    'Midwest',    'Inland Marine',           66],
//     ['Expired',    'Midwest',    'Commercial Property',    180],
//     ['Expired',    'Midwest',    'Commercial Auto',        120],
//     ['Expired',    'Midwest',    'General Liability',       95],
//     ['Expired',    'Southwest',  'Commercial Umbrella',     48],
//     ['Expired',    'Southwest',  'Commercial Property',    140],
//     ['Expired',    'Southwest',  'Workers Compensation',    90],
//     ['Expired',    'Southeast',  'Commercial Property',    260],
//     ['Expired',    'Southeast',  'Workers Compensation',   220],
//     ['Expired',    'Southeast',  'Commercial Auto',        180],
//     ['Expired',    'West',       'Commercial Auto',          8],
//     ['Expired',    'West',       'Business Owners Policy',   4],
//     ['Expired',    'West',       'Commercial Property',      9],
//     ['Expired',    'Mid-Atlantic','Commercial Property',     45],
//     ['Non-Renewed','Southeast',  'Workers Compensation',   101],
//     ['Non-Renewed','Southeast',  'Commercial Property',    140],
//     ['Non-Renewed','Mid-Atlantic','Workers Compensation',    8],
//     ['Non-Renewed','Midwest',    'Commercial Auto',         60],
//     ['Non-Renewed','Southwest',  'Commercial Property',     85],
//     ['Non-Renewed','West',       'Commercial Property',     40],
//     ['Cancelled',  'Southwest',  'Business Owners Policy',  17],
//     ['Cancelled',  'Southwest',  'Commercial Auto',         85],
//     ['Cancelled',  'Midwest',    'General Liability',       26],
//     ['Cancelled',  'Midwest',    'Commercial Property',    120],
//     ['Cancelled',  'Southeast',  'Commercial Property',    160],
//     ['Cancelled',  'Southeast',  'Workers Compensation',   110],
//     ['Cancelled',  'West',       'Workers Compensation',     5],
//     ['Cancelled',  'Mid-Atlantic','Commercial Property',     30],
//   ],
// };

// ── Data read / shaping ──
function readData() {
  try {
    if (typeof viz !== 'undefined' && viz?.getDataFromSearchQuery) {
      const dm = viz.getDataFromSearchQuery();
      const { schema, data } = dm.getData();
      return { schema, data };
    }
  } catch (e) {
    console.warn('[sunburst] viz read failed:', e);
  }
  // Standalone-preview fallback (used when not running inside ThoughtSpot).
  if (typeof SAMPLE !== 'undefined') return SAMPLE;
  return { schema: [], data: [] };
}

function resolveCol(schema, exact, ...fuzzyKeywords) {
  let i = schema.findIndex(c => c.name === exact);
  if (i >= 0) return i;
  const low = exact.toLowerCase();
  i = schema.findIndex(c => c.name.toLowerCase() === low);
  if (i >= 0) return i;
  for (const kw of fuzzyKeywords) {
    const re = new RegExp(kw, 'i');
    i = schema.findIndex(c => re.test(c.name));
    if (i >= 0) return i;
  }
  return -1;
}

function toRows({ schema, data }) {
  const i1 = resolveCol(schema, COL_L1,    'policy.*status', 'status');
  const i2 = resolveCol(schema, COL_L2,    'policy.*region', 'region', 'territory', 'area');
  const i3 = resolveCol(schema, COL_L3,    'product', 'line.*business', 'coverage');
  const iV = resolveCol(schema, COL_VALUE, 'policy.*count', 'count.*polic', '^count$', 'policies');

  console.log('[sunburst] schema columns:', schema.map(c => c.name));
  console.log('[sunburst] resolved indexes:', { i1, i2, i3, iV });

  return data.map(r => ({
    l1: i1 >= 0 ? String(r[i1] ?? '∅') : '∅',
    l2: i2 >= 0 ? String(r[i2] ?? '∅') : '∅',
    l3: i3 >= 0 ? String(r[i3] ?? '∅') : '∅',
    v:  iV >= 0 ? Number(r[iV] ?? 0) : 0,
  })).filter(d => Number.isFinite(d.v) && d.v > 0);
}

// ── Build hierarchical tree ──
function buildHierarchy(rows) {
  const root = { name: 'All policies', children: [], _index: new Map() };
  for (const r of rows) {
    let n1 = root._index.get(r.l1);
    if (!n1) { n1 = { name: r.l1, children: [], _index: new Map() }; root.children.push(n1); root._index.set(r.l1, n1); }
    let n2 = n1._index.get(r.l2);
    if (!n2) { n2 = { name: r.l2, children: [], _index: new Map() }; n1.children.push(n2); n1._index.set(r.l2, n2); }
    let n3 = n2._index.get(r.l3);
    if (!n3) { n3 = { name: r.l3, value: 0 }; n2.children.push(n3); n2._index.set(r.l3, n3); }
    n3.value += r.v;
  }
  const strip = n => { delete n._index; (n.children || []).forEach(strip); };
  strip(root);
  return root;
}

// Roll leaf values up to parents — Plotly's branchvalues:'total' requires this.
function aggregate(node) {
  if (!node.children || node.children.length === 0) return node.value || 0;
  node.value = node.children.reduce((sum, c) => sum + aggregate(c), 0);
  return node.value;
}

function sortTree(node) {
  if (node.children) {
    node.children.sort((a, b) => (b.value || 0) - (a.value || 0));
    node.children.forEach(sortTree);
  }
}

// ── Color helpers ──
function lighten(hex, t) {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!m) return hex;
  const r = parseInt(m[1], 16);
  const g = parseInt(m[2], 16);
  const b = parseInt(m[3], 16);
  return `rgb(${Math.round(r + (255 - r) * t)},${Math.round(g + (255 - g) * t)},${Math.round(b + (255 - b) * t)})`;
}

// ── Flatten tree into Plotly's parallel arrays ──
function flatten(rootNode) {
  const ids = [], labels = [], parents = [], values = [], colors = [];

  function walk(node, parentId, depth, baseColor) {
    const id = parentId ? `${parentId}|${node.name}` : node.name;
    ids.push(id);
    labels.push(node.name);
    parents.push(parentId);
    values.push(node.value || 0);

    let color;
    if (depth === 0)      color = '#FFFFFF';                       // root sits in center, matches page bg
    else if (depth === 1) color = baseColor;
    else                  color = lighten(baseColor, depth === 2 ? 0.22 : 0.42);
    colors.push(color);

    if (node.children) {
      // Track palette index separately so the fallback only advances for
      // statuses that aren't in STATUS_COLORS.
      let paletteIdx = 0;
      node.children.forEach(c => {
        let childBase;
        if (depth === 0) {
          childBase = STATUS_COLORS[c.name] || PALETTE[paletteIdx++ % PALETTE.length];
        } else {
          childBase = baseColor;
        }
        walk(c, id, depth + 1, childBase);
      });
    }
  }

  walk(rootNode, '', 0, '#292763');
  return { ids, labels, parents, values, colors };
}

// ── Formatters ──
const fmtInt = n => Number(n).toLocaleString();

// ── State ──
const raw = readData();
const ROWS = toRows(raw);
const hier = buildHierarchy(ROWS);
aggregate(hier);
sortTree(hier);
const flat = flatten(hier);
const TOTAL = hier.value || 0;

const chartEl    = document.getElementById('sunburst');
const breadcrumb = document.getElementById('breadcrumb');

let currentLevelId = hier.name; // tracks the Plotly trace's `level`

// ── Renderers ──
function renderBreadcrumb(idPath) {
  // Always rendered (even at root) so the container height is stable across
  // zooms — otherwise Plotly's chart overflows the bottom on the first click.
  const parts = idPath.split('|');
  breadcrumb.innerHTML = '';
  parts.forEach((name, idx) => {
    if (idx > 0) {
      const sep = document.createElement('span');
      sep.className = 'crumb-sep';
      sep.textContent = '›';
      breadcrumb.appendChild(sep);
    }
    const c = document.createElement('span');
    const isTail = idx === parts.length - 1;
    const isRootAlone = parts.length === 1;
    c.className = 'crumb' + (idx === 0 ? ' root' : '') + (isTail && !isRootAlone ? ' tail' : '');
    c.textContent = name;
    c.title = name;
    if (!isTail) {
      const targetId = parts.slice(0, idx + 1).join('|');
      c.addEventListener('click', () => zoomToId(targetId));
    }
    breadcrumb.appendChild(c);
  });
}

function renderEmpty() {
  chartEl.innerHTML = `<div style="
      width:100%;height:100%;display:flex;align-items:center;justify-content:center;
      color:#9ca3af;font-size:13px;letter-spacing:0.06em;text-transform:uppercase">
      No data to display
    </div>`;
}

// ── Chart ──
function renderChart() {
  const trace = {
    type: 'sunburst',
    ids: flat.ids,
    labels: flat.labels,
    parents: flat.parents,
    values: flat.values,
    branchvalues: 'total',
    marker: {
      colors: flat.colors,
      line: { color: '#FFFFFF', width: 1.5 },
    },
    // Hover card
    hovertemplate:
      '<b>%{label}</b><br>' +
      'Policies: %{value:,}<br>' +
      '%{percentParent:.1%} of parent · %{percentRoot:.1%} of total' +
      '<extra></extra>',
    // `radial` keeps every label sitting on its wedge's radial midline so
    // placement is consistent across wide and narrow wedges.
    textinfo: 'label',
    insidetextorientation: 'radial',
    textfont: { family: 'Inter, system-ui, sans-serif', size: 12 },
    outsidetextfont: { family: 'Inter, system-ui, sans-serif', color: '#1f2937' },
    // Show only 2 rings (Status + Region) at the root view; Products appear
    // when the user clicks into a region. Avoids the outer-ring label crush.
    // Plotly counts the root as a level — maxdepth: 3 = root + Status + Region.
    maxdepth: 3,
    rotation: 90,
    sort: false,
  };

  const layout = {
    // Bottom margin reserves room for the .ring-guide pill so it doesn't
    // overlap the outer ring's labels.
    margin: { l: 4, r: 4, t: 4, b: 36 },
    paper_bgcolor: '#FFFFFF',
    plot_bgcolor: '#FFFFFF',
    font: { family: 'Inter, system-ui, sans-serif', color: '#1f2937', size: 12 },
    showlegend: false,
    hoverlabel: {
      bgcolor: '#ffffff',
      bordercolor: 'rgba(41,39,99,0.25)',
      font: { family: 'Inter, system-ui, sans-serif', size: 12, color: '#1f2937' },
      align: 'left',
    },
    transition: { duration: 450, easing: 'cubic-in-out' },
  };

  const config = {
    responsive: true,
    displayModeBar: false,
  };

  Plotly.newPlot(chartEl, [trace], layout, config).then(gd => {
    gd.on('plotly_sunburstclick', e => {
      const pt = e?.points?.[0];
      if (!pt) return;
      if (pt.id === currentLevelId && pt.parent !== undefined) {
        currentLevelId = pt.parent || hier.name;
      } else {
        currentLevelId = pt.id;
      }
      renderBreadcrumb(currentLevelId);
    });
  });
}

function zoomToId(id) {
  currentLevelId = id;
  Plotly.restyle(chartEl, { level: [id] });
  renderBreadcrumb(id);
}

// ── Boot ──
if (!ROWS.length || !TOTAL) {
  renderEmpty();
} else {
  renderBreadcrumb(hier.name);
  renderChart();
}

// ── Signal TS render-complete (no-op when not in TS) ──
try { viz.events.emitRenderCompletedEvent(); } catch {}
