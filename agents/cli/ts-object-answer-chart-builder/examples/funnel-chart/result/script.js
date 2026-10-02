/**
 * SECURITY TRIAGE FUNNEL — 3 measures
 *
 * Funnel chart built from 3 MEASURES (no stage attribute in the search):
 * each measure is one funnel stage. The measures are folded into
 * (Stage, Value) rows, rendered as horizontal bars centered with
 * encodingTransform, with trapezoid connectors + labels injected as SVG.
 *
 * Available Columns (ThoughtSpot search):
 * "Event Count"     // MEASURE — stage 1 (top of funnel)
 * "Alert Count"     // MEASURE — stage 2
 * "Incident Count"  // MEASURE — stage 3 (bottom of funnel)
 * --- END ---
 */

const { muze, getDataFromSearchQuery } = viz;
const { DataModel } = muze;

// ─── Customize: the 3 measures, in funnel order (widest → narrowest) ───
const MEASURES = ['Event Count', 'Alert Count', 'Incident Count'];
const STAGE_COLORS = ['#30389B', '#5B63D3', '#9297E8']; // per stage, same order
const FLIPPED = true; // true = upside down (narrowest stage on top, widening down)

const STAGE_FIELD = 'Stage';
const VALUE_FIELD = 'Value';
const BAR_FILL = 0.95; // scales Muze's default bar height (rest = connector gap)

// ── Sample data (used when no search data is available, e.g. local preview) ──
let measureTotals = { 'Event Count': 61573, 'Alert Count': 9718, 'Incident Count': 3095 };

// ── ThoughtSpot search data: used automatically when present ──
try {
  const tsRaw = getDataFromSearchQuery().getData();
  const idx = (name) => tsRaw.schema.findIndex((s) => s.name === name);
  if (tsRaw.data && tsRaw.data.length && MEASURES.every((m) => idx(m) >= 0)) {
    measureTotals = {};
    MEASURES.forEach((m) => {
      measureTotals[m] = tsRaw.data.reduce((acc, r) => acc + (Number(r[idx(m)]) || 0), 0);
    });
  }
} catch (e) {
  console.warn('Falling back to sample data:', e.message);
}

// Fold the 3 measures into (Stage, Value) rows — stages keep MEASURES order.
const rows = MEASURES.map((m) => ({
  [STAGE_FIELD]: m,
  [VALUE_FIELD]: measureTotals[m] || 0,
}));

const schema = [
  { name: STAGE_FIELD, type: 'dimension' },
  { name: VALUE_FIELD, type: 'measure', defAggFn: 'sum' },
];

const topValue = rows[0][VALUE_FIELD] || 1;
const fmtInt = (v) => Math.round(v).toLocaleString('en-US');
const fmtPct = (v) => {
  const p = (v * 100).toFixed(1);
  return (p.endsWith('.0') ? p.slice(0, -2) : p) + '%';
};

let canvas = null;
const el = document.getElementById('chart');
const NS = 'http://www.w3.org/2000/svg';

// ── SVG annotations: trapezoid connectors between bars + in-bar labels ──
const injectAnnotations = () => {
  // Muze renders axes and plot in separate SVGs — find the one holding the bars.
  const bars = Array.from(
    el.querySelectorAll('.funnel-bar-layer rect, g[class*="muze-layer-bar"] rect')
  )
    .filter((r) => !r.classList.contains('muze-tracker'))
    .filter((r) => r.getBoundingClientRect().width > 2 && r.getBoundingClientRect().height > 2)
    .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  if (bars.length !== rows.length) return;
  const svg = bars[0].closest('svg');
  if (!svg) return;
  el.querySelectorAll('.funnel-annot').forEach((n) => n.remove());

  // bars[] is sorted top→bottom; dispRows mirrors that visual order.
  const dispRows = FLIPPED ? rows.slice().reverse() : rows;
  const colorOf = (stage) => STAGE_COLORS[MEASURES.indexOf(stage)] || STAGE_COLORS[0];

  // Paint stage colors directly — Muze applies its palette via inline
  // style.fill, so style (not the fill attribute) is what must be set.
  bars.forEach((r, i) => { r.style.fill = colorOf(dispRows[i][STAGE_FIELD]); });

  const svgBox = svg.getBoundingClientRect();
  const geo = bars.map((r) => {
    const b = r.getBoundingClientRect();
    return {
      left: b.left - svgBox.left,
      right: b.right - svgBox.left,
      top: b.top - svgBox.top,
      bottom: b.bottom - svgBox.top,
      cx: b.left - svgBox.left + b.width / 2,
      cy: b.top - svgBox.top + b.height / 2,
      width: b.width,
    };
  });

  const g = document.createElementNS(NS, 'g');
  g.setAttribute('class', 'funnel-annot');
  g.setAttribute('pointer-events', 'none');

  geo.forEach((cur, i) => {
    // Trapezoid connector down to the next bar, tinted like the wider stage
    if (i < geo.length - 1) {
      const nxt = geo[i + 1];
      const a = dispRows[i][VALUE_FIELD], b = dispRows[i + 1][VALUE_FIELD];
      const wider = a >= b ? dispRows[i] : dispRows[i + 1];
      const poly = document.createElementNS(NS, 'polygon');
      poly.setAttribute('points', [
        `${cur.left},${cur.bottom}`, `${cur.right},${cur.bottom}`,
        `${nxt.right},${nxt.top}`, `${nxt.left},${nxt.top}`,
      ].join(' '));
      poly.setAttribute('fill', colorOf(wider[STAGE_FIELD]));
      poly.setAttribute('opacity', '0.28');
      g.appendChild(poly);

      // Stage-to-stage conversion (always narrower/wider), centered in the gap
      const conv = document.createElementNS(NS, 'text');
      conv.setAttribute('x', String((cur.cx + nxt.cx) / 2));
      conv.setAttribute('y', String((cur.bottom + nxt.top) / 2 + 3.5));
      conv.setAttribute('text-anchor', 'middle');
      conv.setAttribute('font-family', 'Inter, sans-serif');
      conv.setAttribute('font-size', '10.5');
      conv.setAttribute('font-weight', '600');
      conv.setAttribute('fill', '#5A5F73');
      conv.textContent = (FLIPPED ? '▲ ' : '▼ ') + fmtPct(Math.min(a, b) / (Math.max(a, b) || 1));
      g.appendChild(conv);
    }

    // Count label: inside the bar if wide enough, else beside it
    const inside = cur.width >= 76;
    const val = document.createElementNS(NS, 'text');
    val.setAttribute('x', String(inside ? cur.cx : cur.right + 10));
    val.setAttribute('y', String(cur.cy + 5));
    val.setAttribute('text-anchor', inside ? 'middle' : 'start');
    val.setAttribute('font-family', 'Inter, sans-serif');
    val.setAttribute('font-size', '15');
    val.setAttribute('font-weight', '700');
    val.setAttribute('fill', inside ? '#FFFFFF' : colorOf(dispRows[i][STAGE_FIELD]));
    val.textContent = fmtInt(dispRows[i][VALUE_FIELD]);
    g.appendChild(val);
  });

  svg.appendChild(g);
};

function renderChart() {
  const dm = new DataModel(DataModel.loadDataSync(rows, schema));

  // In ThoughtSpot, viz.muze is an initialized instance exposing .canvas()
  // directly (muze itself is NOT callable there). The local preview shim
  // grafts a matching .canvas() onto the raw factory, so this works in both.
  canvas = muze.canvas();

  canvas
    .data(dm)
    .rows([STAGE_FIELD])
    .columns([VALUE_FIELD])
    .color({ field: STAGE_FIELD, domain: MEASURES.slice(), range: STAGE_COLORS.slice() })
    .layers([
      {
        mark: 'bar',
        className: 'funnel-bar-layer',
        encoding: {
          x: { field: VALUE_FIELD },
          y: { field: STAGE_FIELD },
        },
        // Funnel shape: center each bar horizontally and slim it inside its
        // band so the trapezoid connectors have a gap to live in.
        // p.update.* are PIXELS relative to the plot area.
        encodingTransform: (points, layer) => {
          const { width: plotW } = layer.measurement();
          points.forEach((p) => {
            if (!p.update || p.update.width == null) return;
            p.update.x = (plotW - p.update.width) / 2;
            const h = p.update.height;
            p.update.y += (h - h * BAR_FILL) / 2;
            p.update.height = h * BAR_FILL;
          });
          return points;
        },
      },
    ])
    .config(buildConfig());

  canvas.on('afterRendered', scheduleInject);

  applySize();
}

// Built fresh for every mount: Muze mutates (re-sorts) the y-domain array it
// is handed, so a re-mount with a stale config flips the funnel upside down.
function buildConfig() {
  return {
    legend: { show: false },
    transition: { disabled: true },
    axes: {
      x: { show: false, domain: [0, topValue * 1.04] },
      y: {
        show: true,
        showAxisName: false,
        showAxisLine: false,
        // enforce funnel order (reversed when upside down), not alphabetical
        domain: FLIPPED ? MEASURES.slice().reverse() : MEASURES.slice(),
      },
    },
    gridLines: { x: { show: false }, y: { show: false } },
    border: {
      showRowBorders: { top: false, bottom: false, left: false, right: false },
      showColBorders: { top: false, bottom: false, left: false, right: false },
      showValueBorders: { top: false, bottom: false, left: false, right: false },
    },
    // No custom tooltip formatter: ThoughtSpot's Muze passes a dataStore
    // wrapper WITHOUT .getData(), so a formatter written against the local
    // build crashes there ("dataStore.getData is not a function"). The
    // default tooltip (Stage + Value) is TS-safe, and the % breakdowns are
    // already drawn on the chart itself.
  };
}

// Muze can re-layout after afterRendered (e.g. the retained-canvas re-mount on
// resize) without emitting the event again, so re-inject on a short schedule —
// each pass recomputes geometry from the live DOM and replaces the old group.
let _injectTimers = [];
function scheduleInject() {
  _injectTimers.forEach(clearTimeout);
  injectAnnotations();
  _injectTimers = [120, 400, 900].map((ms) => setTimeout(injectAnnotations, ms));
}

function applySize() {
  if (!canvas) return;
  const w = el.clientWidth, h = el.clientHeight;
  if (w <= 0 || h <= 0) return;
  canvas.config(buildConfig()).width(w).height(h).mount(el);
  scheduleInject();
}

renderChart();

let _rafId = null;
new ResizeObserver(() => {
  if (_rafId) cancelAnimationFrame(_rafId);
  _rafId = requestAnimationFrame(() => { applySize(); _rafId = null; });
}).observe(el);

// Signal render completion to ThoughtSpot (no-op in the local preview shim).
viz.events.emitRenderCompletedEvent();
