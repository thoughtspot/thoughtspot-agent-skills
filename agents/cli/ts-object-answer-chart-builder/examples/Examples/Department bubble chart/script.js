/**
 * Available Columns:
 * "Department"
 * "Average Avg Tenure Years"
 * "Average Engagement Score"
 * "Total Headcount"
 * "Measure names" // If 'measureValues' is enabled.
 * "Measure values" // If 'measureValues' is enabled.
 * --- END ---
 */

// ThoughtSpot: Uncomment the block below before pasting into ThoughtSpot

const { muze, getDataFromSearchQuery } = viz;


const { DataModel } = muze;

// Internal schema the chart draws from. TS display columns are mapped into
// these field names in buildRowsFromTS() so the chart code below never changes.
const schema = [
  { name: 'Department', type: 'dimension' },
  { name: 'AvgTenure',  type: 'measure', defAggFn: 'avg' },
  { name: 'Engagement', type: 'measure', defAggFn: 'avg' },
  { name: 'Headcount',  type: 'measure', defAggFn: 'sum' }
];

// ── Internal field names (used everywhere below) ──
const DEPARTMENT_FIELD = 'Department';
const AVG_TENURE_FIELD = 'AvgTenure';
const ENGAGEMENT_FIELD = 'Engagement';
const HEADCOUNT_FIELD  = 'Headcount';

// ── TS source column names (match the "Available Columns" header above) ──
const TS_DEPARTMENT_COL     = 'Department';
const TS_TENURE_COL         = 'Average Avg Tenure Years';
const TS_ENGAGEMENT_COL     = 'Average Engagement Score';
const TS_HEADCOUNT_COL      = 'Total Headcount';
const TS_MEASURE_NAMES_COL  = 'Measure names';
const TS_MEASURE_VALUES_COL = 'Measure values';

// ── Sample data — used only when no search data is available (local preview) ──
const SAMPLE_DATA = [
  { Department: 'Engineering', AvgTenure: 2.8, Engagement: 71.0, Headcount: 340 },
  { Department: 'Sales',       AvgTenure: 1.9, Engagement: 78.5, Headcount: 200 },
  { Department: 'Marketing',   AvgTenure: 2.5, Engagement: 80.2, Headcount: 120 },
  { Department: 'HR',          AvgTenure: 4.1, Engagement: 82.0, Headcount: 80  },
  { Department: 'Finance',     AvgTenure: 4.8, Engagement: 70.5, Headcount: 90  },
  { Department: 'Operations',  AvgTenure: 4.2, Engagement: 68.0, Headcount: 310 },
  { Department: 'Product',     AvgTenure: 3.6, Engagement: 79.5, Headcount: 145 },
  { Department: 'Support',     AvgTenure: 1.5, Engagement: 70.0, Headcount: 175 },
  { Department: 'Design',      AvgTenure: 2.2, Engagement: 76.5, Headcount: 65  },
  { Department: 'Legal',       AvgTenure: 5.2, Engagement: 73.5, Headcount: 40  }
];

// Reshape ThoughtSpot search data into the internal { Department, AvgTenure,
// Engagement, Headcount } rows. Handles the wide shape (one row per department
// with the three named measures) and the folded shape (Measure names/values).
// Returns null when no usable search data is present so the caller can fall back.
function buildRowsFromTS() {
  const res = getDataFromSearchQuery().getData();
  const cols = (res.schema || []).map((s) => s.name);
  const rows = res.data || [];
  if (!rows.length) return null;

  const idx = (name) => cols.indexOf(name);
  const deptI = idx(TS_DEPARTMENT_COL);
  if (deptI < 0) return null;

  // Wide format: one search row per department with the named measure columns.
  const tenureI = idx(TS_TENURE_COL);
  const engI    = idx(TS_ENGAGEMENT_COL);
  const hcI     = idx(TS_HEADCOUNT_COL);
  if (tenureI >= 0 || engI >= 0 || hcI >= 0) {
    const out = rows
      .filter((r) => r[deptI] != null)
      .map((r) => ({
        [DEPARTMENT_FIELD]: String(r[deptI]),
        [AVG_TENURE_FIELD]: tenureI >= 0 ? Number(r[tenureI]) || 0 : 0,
        [ENGAGEMENT_FIELD]: engI    >= 0 ? Number(r[engI])    || 0 : 0,
        [HEADCOUNT_FIELD]:  hcI     >= 0 ? Number(r[hcI])     || 0 : 0
      }));
    return out.length ? out : null;
  }

  // Folded format: (Department, Measure names, Measure values) — measureValues on.
  const mnI = idx(TS_MEASURE_NAMES_COL);
  const mvI = idx(TS_MEASURE_VALUES_COL);
  if (mnI < 0 || mvI < 0) return null;
  const byDept = {};
  rows.forEach((r) => {
    if (r[deptI] == null) return;
    const key = String(r[deptI]);
    const rec = byDept[key] || (byDept[key] = {
      [DEPARTMENT_FIELD]: key,
      [AVG_TENURE_FIELD]: 0,
      [ENGAGEMENT_FIELD]: 0,
      [HEADCOUNT_FIELD]:  0
    });
    const val = Number(r[mvI]) || 0;
    if (r[mnI] === TS_TENURE_COL)          rec[AVG_TENURE_FIELD] = val;
    else if (r[mnI] === TS_ENGAGEMENT_COL) rec[ENGAGEMENT_FIELD] = val;
    else if (r[mnI] === TS_HEADCOUNT_COL)  rec[HEADCOUNT_FIELD]  = val;
  });
  const out = Object.values(byDept);
  return out.length ? out : null;
}

const BUBBLE_COLOR = '#3d8577';
const PLOT_BG      = '#F4ECD8'; // page background — used as a halo behind labels
const FALLBACK_R   = 6;

const mean = (vals) => vals.reduce((a, b) => a + b, 0) / vals.length;

// Axis domain hugs the data with a little padding on each side. Unlike a
// round-number "nice" domain, this keeps the bubbles spread across the whole
// plot instead of squashed into a thin band when the values sit in a narrow
// range (e.g. engagement clustered around 73–75).
const paddedDomain = (vals, padFrac) => {
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = (max - min) || Math.abs(max) || 1;
  const pad = span * padFrac;
  return [min - pad, max + pad];
};

const el = document.querySelector('#chart');
const NS = 'http://www.w3.org/2000/svg';

// ── Chart state — everything below is recomputed on each (re)render so the viz
// tracks whatever data ThoughtSpot currently returns (this is a dynamic tile). ──
let data, dm;
let X_MIN, X_MAX, Y_MIN, Y_MAX, TENURE_REF, ENGAGEMENT_REF, HC_MIN, HC_MAX;
const RADIUS_MAP = {};   // department → current bubble radius (px), refreshed per layout
const deptPixels = {};   // department → { px, py } bubble centre in root-SVG pixels

// Read live TS data (falling back to sample data) and recompute every
// data-derived value. Runs at the top of every render — so a changed search
// result reshapes the axes, means and bubble sizes without a page reload.
function prepareData() {
  data = SAMPLE_DATA;
  try {
    const tsRows = buildRowsFromTS();
    if (tsRows && tsRows.length) data = tsRows;
  } catch (e) {
    console.warn('Department bubble chart: falling back to sample data —', e.message);
  }

  const tenureVals     = data.map((d) => d[AVG_TENURE_FIELD]);
  const engagementVals = data.map((d) => d[ENGAGEMENT_FIELD]);
  const headcounts     = data.map((d) => d[HEADCOUNT_FIELD]);

  const xd = paddedDomain(tenureVals, 0.18);     X_MIN = xd[0]; X_MAX = xd[1];
  const yd = paddedDomain(engagementVals, 0.20); Y_MIN = yd[0]; Y_MAX = yd[1];
  TENURE_REF     = mean(tenureVals);     // vertical divider = avg tenure
  ENGAGEMENT_REF = mean(engagementVals); // horizontal divider = avg engagement
  HC_MIN = Math.min(...headcounts);
  HC_MAX = Math.max(...headcounts);

  // Clear stale bubble centres (department set may have changed).
  Object.keys(deptPixels).forEach((k) => delete deptPixels[k]);

  dm = new DataModel(DataModel.loadDataSync(data, schema));
}

// Bubble radius scales with headcount on a sqrt scale (so AREA reads as
// headcount) and with the plot's size (so bubbles look proportional in a small
// tile or full-screen). We draw the circles ourselves because Muze's point
// `size` range is clamped, which would let the largest bubble swallow its
// neighbours. Refreshed each layout pass with the current plot dimension.
function refreshRadii(basePx) {
  const maxR = Math.max(16, Math.min(70, basePx * 0.06));
  const minR = Math.max(5,  Math.min(18, basePx * 0.016));
  data.forEach((d) => {
    const t = HC_MAX === HC_MIN ? 1 : (d[HEADCOUNT_FIELD] - HC_MIN) / (HC_MAX - HC_MIN);
    RADIUS_MAP[d[DEPARTMENT_FIELD]] = minR + (maxR - minR) * Math.sqrt(t);
  });
}

// `canvas` is declared once at module scope and reassigned on (re)render — never
// shadowed with a local `const`, or applySize() would resize a stale canvas.
let canvas;

function renderChart() {
  prepareData();
  canvas = muze.canvas();
  // ── Muze Experience standalone (default): comment the line above, uncomment: ──
  //canvas = muze().canvas();

  canvas
    .data(dm)
    .rows([ENGAGEMENT_FIELD])
    .columns([AVG_TENURE_FIELD])
    .detail([DEPARTMENT_FIELD])
    .layers([
      {
        mark: 'point',
        className: 'dept-bubble-layer',
        encoding: {
          // The native marks are kept invisible: they exist only to lay out one
          // point per department and hand us its pixel centre. We draw the real
          // bubbles ourselves in the overlay (see drawBubbles) — mutating Muze's
          // own marks leaks orphaned nodes across the resize re-mounts.
          color:   { value: () => BUBBLE_COLOR },
          opacity: { value: () => 0 },
          size:    { value: () => 0.3 }
        },
        encodingTransform: (points) => {
          points.forEach((p) => {
            const dept = p.data && p.data[DEPARTMENT_FIELD];
            if (dept != null) deptPixels[dept] = { px: p.update.x, py: p.update.y };
          });
          return points;
        }
      }
    ])
    .config({
      autoGroupBy: { disabled: true },
      axes: {
        x: {
          name: 'Avg Tenure (Years)',
          showAxisName: true,
          showAxisLine: false,
          domain: [X_MIN, X_MAX],
          numberOfTicks: 6
        },
        y: {
          name: 'Engagement Score (%)',
          showAxisName: true,
          showAxisLine: false,
          domain: [Y_MIN, Y_MAX],
          numberOfTicks: 6
        }
      },
      gridLines: { x: { show: true }, y: { show: true }, color: '#e4dcc6' },
      legend: { show: false }
    });

  applySize();

  canvas.once('afterRendered', () => schedulePostRender(40));
}

// Wait for Muze to lay out the (invisible) marks, then draw the overlay.
function schedulePostRender(maxAttempts) {
  let attempts = 0;
  const tryRun = () => {
    if (document.querySelector('#chart .dept-bubble-layer path') && Object.keys(deptPixels).length >= 1) {
      setTimeout(injectOverlays, 120);
    } else if (attempts++ < maxAttempts) {
      setTimeout(tryRun, 100);
    }
  };
  tryRun();
}

// Fill the #chart container, re-laying-out cleanly on resize (same canvas, no
// rebuild — re-mounting the same canvas re-flows without flicker).
function applySize() {
  if (!canvas || !el) return;
  const w = el.clientWidth, h = el.clientHeight;
  if (w <= 0 || h <= 0) return;
  canvas.width(w).height(h).mount(el);
}

// Draw the mean-cross reference lines, quadrant captions and department labels.
// Everything is derived from the freshly measured bubble geometry so it stays
// aligned across resizes and whatever data ThoughtSpot returns.
function injectOverlays() {
  const layer = document.querySelector('#chart .dept-bubble-layer');
  if (!layer) return;
  const svg = layer.closest('svg');
  if (!svg) return;
  const svgBB = svg.getBoundingClientRect();
  if (svgBB.width < 200) return;

  // Clear any overlay from a previous render/resize pass.
  svg.querySelectorAll('.muze-ov').forEach((n) => n.remove());

  // Type + bubble radii scale gently with the plot so it reads well small or
  // full-screen.
  const base    = Math.min(svgBB.width, svgBB.height);
  const labelFS = Math.max(11, Math.min(16, base * 0.026));
  const capFS   = Math.max(10, Math.min(14, base * 0.023));
  const capLH   = capFS + 2;
  refreshRadii(base);

  const radiusOf = (dept) => RADIUS_MAP[dept] || FALLBACK_R;

  // Build a linear data→pixel map from the two most-separated bubbles on each
  // axis (exact, version-independent — no guessing plot margins).
  const depts = Object.keys(deptPixels);
  if (depts.length < 2) return;
  const byTenure = [...data].sort((a, b) => a[AVG_TENURE_FIELD] - b[AVG_TENURE_FIELD]);
  const byEng    = [...data].sort((a, b) => a[ENGAGEMENT_FIELD] - b[ENGAGEMENT_FIELD]);
  const xA = byTenure[0], xB = byTenure[byTenure.length - 1];
  const yA = byEng[0],    yB = byEng[byEng.length - 1];
  const pA = deptPixels[xA[DEPARTMENT_FIELD]], pB = deptPixels[xB[DEPARTMENT_FIELD]];
  const qA = deptPixels[yA[DEPARTMENT_FIELD]], qB = deptPixels[yB[DEPARTMENT_FIELD]];
  if (!pA || !pB || !qA || !qB) return;

  const dxData = (xB[AVG_TENURE_FIELD] - xA[AVG_TENURE_FIELD]) || 1;
  const dyData = (yB[ENGAGEMENT_FIELD] - yA[ENGAGEMENT_FIELD]) || 1;
  const mX = (pB.px - pA.px) / dxData;
  const cX = pA.px - mX * xA[AVG_TENURE_FIELD];
  const mY = (qB.py - qA.py) / dyData;
  const cY = qA.py - mY * yA[ENGAGEMENT_FIELD];
  const toPixX = (v) => mX * v + cX;
  const toPixY = (v) => mY * v + cY;

  // Plot rectangle = domain edges mapped to pixels.
  const left   = toPixX(X_MIN);
  const right  = toPixX(X_MAX);
  const top    = toPixY(Y_MAX);
  const bottom = toPixY(Y_MIN);
  const xRef   = toPixX(TENURE_REF);
  const yRef   = toPixY(ENGAGEMENT_REF);

  const g = document.createElementNS(NS, 'g');
  g.setAttribute('class', 'muze-ov');
  g.setAttribute('pointer-events', 'none');

  const line = (x1, y1, x2, y2) => {
    const l = document.createElementNS(NS, 'line');
    l.setAttribute('x1', x1); l.setAttribute('y1', y1);
    l.setAttribute('x2', x2); l.setAttribute('y2', y2);
    l.setAttribute('stroke', '#9a9482');
    l.setAttribute('stroke-width', '1.25');
    l.setAttribute('stroke-dasharray', '6 4');
    g.appendChild(l);
  };
  line(xRef, top, xRef, bottom);   // vertical: avg tenure
  line(left, yRef, right, yRef);   // horizontal: avg engagement

  // ── Quadrant captions, tucked into each corner of the plot ──
  const cap = (lines, x, firstY, anchor) => {
    lines.forEach((txt, i) => {
      const t = document.createElementNS(NS, 'text');
      t.setAttribute('x', x);
      t.setAttribute('y', firstY + i * capLH);
      t.setAttribute('text-anchor', anchor);
      t.setAttribute('font-size', capFS);
      t.setAttribute('font-style', 'italic');
      t.setAttribute('fill', '#b3a48f');
      t.textContent = txt;
      g.appendChild(t);
    });
  };
  const cp = 8;
  cap(['High Engagement,', 'Low Tenure'],  left + cp,  top + capLH,          'start');
  cap(['High Engagement,', 'High Tenure'], right - cp, top + capLH,          'end');
  cap(['Low Engagement,',  'Low Tenure'],  left + cp,  bottom - capLH - 4,   'start');
  cap(['Low Engagement,',  'High Tenure'], right - cp, bottom - capLH - 4,   'end');

  // ── Bubbles — drawn here (not by mutating Muze's marks) so a resize re-mount
  // never leaves orphaned circles behind. Largest first, so small bubbles that
  // overlap a big one stay hittable/visible on top. ──
  [...data]
    .sort((a, b) => b[HEADCOUNT_FIELD] - a[HEADCOUNT_FIELD])
    .forEach((d) => {
      const c = deptPixels[d[DEPARTMENT_FIELD]];
      if (!c) return;
      const circle = document.createElementNS(NS, 'circle');
      circle.setAttribute('cx', c.px);
      circle.setAttribute('cy', c.py);
      circle.setAttribute('r', radiusOf(d[DEPARTMENT_FIELD]));
      circle.setAttribute('fill', BUBBLE_COLOR);
      circle.setAttribute('fill-opacity', '0.82');
      g.appendChild(circle);
    });

  // ── Department labels beside each bubble ──
  // Place to the right of the bubble; flip to the left when that would run past
  // the plot's right edge so nothing clips or spills outside the axes.
  data.forEach((d) => {
    const dept = d[DEPARTMENT_FIELD];
    const c = deptPixels[dept];
    if (!c) return;
    const r = radiusOf(dept);
    const gap = 6;
    const estW = dept.length * labelFS * 0.58 + gap;
    const flip = c.px + r + gap + estW > right - 4;

    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', flip ? c.px - r - gap : c.px + r + gap);
    t.setAttribute('y', c.py + labelFS * 0.34);
    t.setAttribute('text-anchor', flip ? 'end' : 'start');
    t.setAttribute('font-size', labelFS);
    t.setAttribute('font-weight', '600');
    t.setAttribute('fill', '#2b2b2b');
    // Halo in the page colour keeps labels readable where they pass near a bubble.
    t.setAttribute('stroke', PLOT_BG);
    t.setAttribute('stroke-width', '3');
    t.setAttribute('paint-order', 'stroke');
    t.textContent = dept;
    g.appendChild(t);
  });

  svg.appendChild(g);
}

renderChart();
window.updateChart = renderChart;

let _rafId = null;
new ResizeObserver(() => {
  if (_rafId) cancelAnimationFrame(_rafId);
  _rafId = requestAnimationFrame(() => {
    _rafId = null;
    applySize();
    // Re-mounting re-lays-out the marks; re-draw the overlay (bubbles, lines,
    // labels) against the new geometry once the fresh marks have settled.
    schedulePostRender(20);
  });
}).observe(el);

// Signal render completion to ThoughtSpot (no-op in the local preview shim).
if (viz.events && viz.events.emitRenderCompletedEvent) {
  viz.events.emitRenderCompletedEvent();
}
