/**
 * Available Columns:
 * "Unit Type"                  // ATTRIBUTE
 * "Unit Name"                  // ATTRIBUTE
 * "Provider Specialty"         // ATTRIBUTE
 * "Unique Count Encounter Id"  // MEASURE
 * --- END ---
 */

// ── Column Name Constants ──
const COL_L1    = 'Unit Type';
const COL_L2    = 'Unit Name';
const COL_L3    = 'Provider Specialty';
const COL_VALUE = 'Unique Count Encounter Id';

// Named per-unit-type colors. Unknown units fall back to PALETTE (cycled).
const UNIT_COLORS = {
  'ED':                '#F9B3B9',
  'ICU':               '#F47E89',
  'L&D':               '#D1C0FB',
  'Med/Surg':          '#B094F8',
  'Ortho':             '#8C62F5',
  'Outpatient Clinic': '#6A4ABA',
  'Telemetry':         '#422E75',
};
const PALETTE = [
  '#F9B3B9', '#F47E89', '#D1C0FB', '#B094F8',
  '#8C62F5', '#6A4ABA', '#422E75',
];

// ── Sample dataset for standalone preview (uncomment to use) ──
// const SAMPLE = {
//   schema: [
//     { name: COL_L1, type: 'ATTRIBUTE' }, { name: COL_L2, type: 'ATTRIBUTE' },
//     { name: COL_L3, type: 'ATTRIBUTE' }, { name: COL_VALUE, type: 'MEASURE' },
//   ],
//   data: [
//     ['Ortho','Orthopedic Unit','General Surgery',94],
//     ['Outpatient Clinic','Surgical Services Clinic','Orthopedic Surgery',435],
//     ['ED','Emergency Department','Emergency Medicine',2950],
//     ['Outpatient Clinic','General Medicine Clinic','Gastroenterology',546],
//     ['Telemetry','Telemetry Unit','Cardiology',573],
//     ['ICU','Medical Intensive Care Unit','Critical Care',612],
//     ['Outpatient Clinic','Surgical Services Clinic','General Surgery',583],
//     ['Outpatient Clinic','Diagnostic & Imaging Center','Radiology',2580],
//     ['ICU','Medical Intensive Care Unit','Pulmonology',180],
//     ['L&D','Labor & Delivery','Obstetrics & Gynecology',398],
//     ['Outpatient Clinic','General Medicine Clinic','Internal Medicine',820],
//     ['Outpatient Clinic','General Medicine Clinic','Family Medicine',470],
//     ['ICU','Surgical Intensive Care Unit','Critical Care',310],
//     ['ED','Emergency Department','Pediatrics',260],
//     ['Telemetry','Telemetry Unit','Internal Medicine',210],
//     ['Outpatient Clinic','Diagnostic & Imaging Center','Cardiology',340],
//     ['Ortho','Orthopedic Unit','Orthopedic Surgery',160],
//     ['L&D','Labor & Delivery','Neonatology',120],
//     ['Med/Surg','Medical-Surgical Unit','Hospital Medicine',900],
//     ['Med/Surg','Medical-Surgical Unit','Internal Medicine',320],
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
  const i1 = resolveCol(schema, COL_L1,    'unit.*type', 'department.*type', 'category');
  const i2 = resolveCol(schema, COL_L2,    'unit.*name', 'department.*name', '^unit$', 'name');
  const i3 = resolveCol(schema, COL_L3,    'specialty', 'provider');
  const iV = resolveCol(schema, COL_VALUE, 'encounter', 'count', 'unique');

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
  const root = { name: 'All encounters', children: [], _index: new Map() };
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
    if (depth === 0)      color = '#F7F5FF';                       // root sits in center, matches page bg
    else if (depth === 1) color = baseColor;
    else                  color = lighten(baseColor, depth === 2 ? 0.22 : 0.42);
    colors.push(color);

    if (node.children) {
      // Track palette index separately so the fallback only advances for
      // unit types that aren't in UNIT_COLORS.
      let paletteIdx = 0;
      node.children.forEach(c => {
        let childBase;
        if (depth === 0) {
          childBase = UNIT_COLORS[c.name] || PALETTE[paletteIdx++ % PALETTE.length];
        } else {
          childBase = baseColor;
        }
        walk(c, id, depth + 1, childBase);
      });
    }
  }

  walk(rootNode, '', 0, '#7c3aed');
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
  // idPath: "All encounters|Outpatient Clinic|…"
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
      color:#9588b8;font-size:13px;letter-spacing:0.06em;text-transform:uppercase">
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
      line: { color: '#F7F5FF', width: 1.5 },
    },
    // Hover card
    hovertemplate:
      '<b>%{label}</b><br>' +
      'Encounters: %{value:,}<br>' +
      '%{percentParent:.1%} of parent · %{percentRoot:.1%} of total' +
      '<extra></extra>',
    // In-sector text. `radial` centers each label on its wedge's radial axis,
    // which keeps placement consistent (every label sits at the radial midline
    // of its wedge) — the "Outpatient Clinic floating near the inner edge"
    // problem `horizontal` has on very wide wedges.
    textinfo: 'label',
    insidetextorientation: 'radial',
    textfont: { family: 'Inter, system-ui, sans-serif', size: 12 },
    outsidetextfont: { family: 'Inter, system-ui, sans-serif', color: '#1e1b4b' },
    // Show 3 rings + the center disk (root)
    maxdepth: 4,
    rotation: 90,
    sort: false,
  };

  const layout = {
    // Bottom margin reserves room for the .ring-guide pill so it doesn't
    // overlap the outer ring's labels.
    margin: { l: 4, r: 4, t: 4, b: 36 },
    paper_bgcolor: '#F7F5FF',
    plot_bgcolor: '#F7F5FF',
    font: { family: 'Inter, system-ui, sans-serif', color: '#1e1b4b', size: 12 },
    showlegend: false,
    hoverlabel: {
      bgcolor: '#ffffff',
      bordercolor: 'rgba(124,58,237,0.25)',
      font: { family: 'Inter, system-ui, sans-serif', size: 12, color: '#1e1b4b' },
      align: 'left',
    },
    transition: { duration: 450, easing: 'cubic-in-out' },
  };

  const config = {
    responsive: true,
    displayModeBar: false,
  };

  Plotly.newPlot(chartEl, [trace], layout, config).then(gd => {
    // Sync breadcrumb whenever the user zooms in or out via the chart itself.
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
