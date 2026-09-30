/**
 * PROGRESSION FUNNEL — 3 measures, current vs comparison period
 * ─────────────────────────────────────────────────────────────
 * Each measure is a funnel stage drawn as a horizontal bar:
 *   • solid magenta bar  = the primary period  (e.g. latest year)
 *   • lighter bar below  = the comparison period (e.g. prior year)
 *   • a % change arrow    = primary vs comparison for that stage
 *
 * Data model: 3 MEASURES + one period ATTRIBUTE that has ≥2 values.
 * (In your example: measures = Touched / Engaged / Met, period = Yearly Date.)
 *
 * Available Columns (standalone demo schema — replace with your query's columns):
 * "Yearly Date"            // ATTRIBUTE — the period (current vs comparison)
 * "Unique People Touched"  // MEASURE — stage 1 (top / widest)
 * "Unique People Engaged"  // MEASURE — stage 2
 * "Unique People Met"      // MEASURE — stage 3 (bottom / narrowest)
 * --- END ---
 */

// ── Customize ─────────────────────────────────────────────────────────────
// Funnel stages, top → bottom. Add / remove measures freely.
const MEASURES = ['Unique People Touched', 'Unique People Engaged', 'Unique People Met'];

// The attribute that splits current vs comparison (e.g. a date/year field).
// null → auto-detect the first non-measure column. Set to a name to force it.
const PERIOD_FIELD = null;

// Which period is the solid bar: 'latest' | 'earliest' | an explicit value (e.g. '2026').
const PRIMARY = 'latest';

// 'sum' | 'avg' | 'count' | 'min' | 'max'  — how repeated period rows combine.
const AGGREGATION = 'sum';

// ── Colours (match the screenshot's magenta profile) ──
const PRIMARY_COLOR = '#7A2D6B';   // solid current-period bar
const COMPARE_COLOR = '#D8D8E0';   // lighter comparison bar
const UP_COLOR      = '#2E8B57';   // "good" change
const DOWN_COLOR    = '#C0392B';   // "bad" change
const NEUTRAL_COLOR = '#8A8F9E';   // no change / not available

// For a funnel a decline is usually "bad" → shown red. Set false to invert.
const DOWN_IS_BAD = true;

// Longest bar reaches this % of the bar track; the rest leaves room for value labels.
const MAX_BAR_PCT = 76;

// Value number formatting (counts by default).
// type: 'number' {decimals} | 'currency' {currency,decimals} | 'percent' {decimals,fraction}
//       | 'compact' {decimals} | 'custom' {fn}
const VALUE_FORMAT = { type: 'number', decimals: 0 };

// Optional heading + legend above the funnel. TITLE = '' hides the heading.
const TITLE = 'Engagement funnel';
const SHOW_LEGEND = true;

// Optional tooltip text shown by the ⓘ next to each stage. Keyed by measure name.
const STAGE_INFO = {
  // 'Unique People Touched': 'Distinct people who received any outreach',
};
// ──────────────────────────────────────────────────────────────────────────

// Demo data — used when the `viz` object is unavailable (standalone preview).
const DEMO = {
  schema: [
    { name: 'Yearly Date',           type: 'ATTRIBUTE' },
    { name: 'Unique People Touched', type: 'MEASURE'   },
    { name: 'Unique People Engaged', type: 'MEASURE'   },
    { name: 'Unique People Met',     type: 'MEASURE'   },
  ],
  data: [
    ['2025', 317, 286, 101],
    ['2026', 159,  66,  36],
  ],
};

function getData() {
  try {
    const { schema, data } = viz.getDataFromSearchQuery().getData();
    return { schema, data };
  } catch {
    return DEMO;
  }
}

// ── Formatting ──────────────────────────────────────────────────────────────
function fmt(value) {
  if (value == null) return '—';
  const n = Number(value);
  if (isNaN(n)) return String(value);
  const f = VALUE_FORMAT;
  if (f.type === 'custom') return f.fn(n);
  const o = { minimumFractionDigits: f.decimals ?? 0, maximumFractionDigits: f.decimals ?? 2 };
  if (f.type === 'currency') return n.toLocaleString(undefined, { style: 'currency', currency: f.currency ?? 'USD', ...o });
  if (f.type === 'percent')  return (f.fraction ? n : n / 100).toLocaleString(undefined, { style: 'percent', ...o });
  if (f.type === 'compact')  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: f.decimals ?? 1 }).format(n);
  return n.toLocaleString(undefined, o);
}

// Period labels: ThoughtSpot dates often arrive as epoch millis → show the year.
function periodLabel(v) {
  const n = Number(v);
  if (!isNaN(n) && n > 1e10) return String(new Date(n).getUTCFullYear());
  return String(v);
}
function periodSortVal(v) {
  const n = Number(v);
  return isNaN(n) ? String(v) : n;
}

function agg(values) {
  if (!values.length) return null;
  switch (AGGREGATION) {
    case 'avg':   return values.reduce((a, b) => a + b, 0) / values.length;
    case 'count': return values.length;
    case 'min':   return Math.min(...values);
    case 'max':   return Math.max(...values);
    default:      return values.reduce((a, b) => a + b, 0); // sum
  }
}

// ── Shape the search data into funnel stages ──────────────────────────────────
function buildStages({ schema, data }) {
  const idx = name => schema.findIndex(s => s.name === name);

  const missing = MEASURES.filter(m => idx(m) < 0);
  if (missing.length) {
    throw new Error(
      `Funnel config references unknown measures: ${missing.join(', ')}\n` +
      `Available: ${schema.map(s => s.name).join(', ')}`
    );
  }

  const periodField = PERIOD_FIELD || (schema.find(s => !MEASURES.includes(s.name)) || {}).name;
  const pIdx = periodField ? idx(periodField) : -1;

  // period value → measure → raw number[]
  const buckets = {};
  const order = [];
  const add = (p, row) => {
    if (!(p in buckets)) { buckets[p] = {}; order.push(p); MEASURES.forEach(m => (buckets[p][m] = [])); }
    MEASURES.forEach(m => { const v = Number(row[idx(m)]); if (!isNaN(v)) buckets[p][m].push(v); });
  };

  if (pIdx >= 0) data.forEach(row => add(String(row[pIdx]), row));
  else           data.forEach(row => add('__all__', row));

  // Pick primary + comparison periods.
  const sorted = order.slice().sort((a, b) => (periodSortVal(a) > periodSortVal(b) ? 1 : periodSortVal(a) < periodSortVal(b) ? -1 : 0));
  let primaryP = null, compareP = null;
  if (sorted.length >= 2) {
    if (PRIMARY === 'earliest')      { primaryP = sorted[0];               compareP = sorted[1]; }
    else if (PRIMARY === 'latest')   { primaryP = sorted[sorted.length - 1]; compareP = sorted[sorted.length - 2]; }
    else if (sorted.includes(PRIMARY)) { primaryP = PRIMARY; compareP = sorted.filter(p => p !== PRIMARY).pop(); }
    else                             { primaryP = sorted[sorted.length - 1]; compareP = sorted[sorted.length - 2]; }
  } else {
    primaryP = sorted[0];
  }

  const val = (p, m) => (p != null ? agg(buckets[p][m]) : null);
  const stages = MEASURES.map(m => ({
    name: m,
    primary: val(primaryP, m),
    compare: val(compareP, m),
  }));

  return {
    stages,
    hasCompare: compareP != null,
    primaryLabel: primaryP === '__all__' ? '' : periodLabel(primaryP),
    compareLabel: compareP != null ? periodLabel(compareP) : '',
  };
}

// ── DOM helpers ──────────────────────────────────────────────────────────────
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function changeInfo(primary, compare) {
  if (compare == null || compare === 0 || primary == null) return { text: '—', color: NEUTRAL_COLOR };
  const pct = ((primary - compare) / compare) * 100;
  const rounded = Math.round(Math.abs(pct));
  if (rounded === 0) return { text: '0%', color: NEUTRAL_COLOR };
  const down = pct < 0;
  const isGood = down ? !DOWN_IS_BAD : DOWN_IS_BAD;
  return { text: (down ? '↓ ' : '↑ ') + rounded + '%', color: isGood ? UP_COLOR : DOWN_COLOR };
}

function render(model) {
  const container = document.getElementById('chart');
  container.innerHTML = '';

  const { stages, hasCompare, primaryLabel, compareLabel } = model;
  const values = stages.flatMap(s => [s.primary, s.compare].filter(v => v != null));
  const globalMax = Math.max(...values, 1);
  const barPct = v => (v == null ? 0 : (v / globalMax) * MAX_BAR_PCT);

  // Header (title + legend)
  if (TITLE || (SHOW_LEGEND && hasCompare)) {
    const head = el('div', 'pf-header');
    if (TITLE) head.appendChild(el('div', 'pf-title', TITLE));
    if (SHOW_LEGEND && hasCompare) {
      const legend = el('div', 'pf-legend');
      const item = (color, label) => {
        const i = el('span', 'pf-legend-item');
        const sw = el('span', 'pf-swatch'); sw.style.background = color;
        i.appendChild(sw); i.appendChild(document.createTextNode(label));
        return i;
      };
      legend.appendChild(item(PRIMARY_COLOR, primaryLabel || 'Current'));
      legend.appendChild(item(COMPARE_COLOR, compareLabel || 'Comparison'));
      head.appendChild(legend);
    }
    container.appendChild(head);
  }

  const list = el('div', 'pf-stages');

  for (const s of stages) {
    const row = el('div', 'pf-stage');

    // Label + info
    const label = el('div', 'pf-label');
    label.appendChild(el('span', 'pf-name', s.name));
    if (STAGE_INFO[s.name]) {
      const info = el('span', 'pf-info', 'i');
      info.title = STAGE_INFO[s.name];
      label.appendChild(info);
    }
    row.appendChild(label);

    // Change indicator
    const ch = changeInfo(s.primary, s.compare);
    const change = el('div', 'pf-change', ch.text);
    change.style.color = ch.color;
    row.appendChild(change);

    // Bars
    const bars = el('div', 'pf-bars');

    const primaryRow = el('div', 'pf-bar-row');
    const pBar = el('div', 'pf-bar pf-primary');
    pBar.style.width = barPct(s.primary) + '%';
    pBar.style.background = PRIMARY_COLOR;
    primaryRow.appendChild(pBar);
    primaryRow.appendChild(el('div', 'pf-val pf-val-primary', fmt(s.primary)));
    bars.appendChild(primaryRow);

    if (hasCompare) {
      const compareRow = el('div', 'pf-bar-row');
      const cBar = el('div', 'pf-bar pf-compare');
      cBar.style.width = barPct(s.compare) + '%';
      cBar.style.background = COMPARE_COLOR;
      compareRow.appendChild(cBar);
      compareRow.appendChild(el('div', 'pf-val pf-val-compare', fmt(s.compare)));
      bars.appendChild(compareRow);
    }

    row.appendChild(bars);
    list.appendChild(row);
  }

  container.appendChild(list);
}

// ── Boot ──────────────────────────────────────────────────────────────────────
try {
  render(buildStages(getData()));
} catch (e) {
  document.getElementById('chart').innerHTML =
    `<pre style="color:red;padding:16px;white-space:pre-wrap">${e.message}</pre>`;
}

try { viz.events.emitRenderCompletedEvent(); } catch {}
