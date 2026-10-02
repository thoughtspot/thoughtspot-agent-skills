/**
 * Custom flat table for ThoughtSpot BYOC, built on Grid.js.
 *
 * Table-mode counterpart to pivot-table.js. Everything tile-specific lives in the
 * CONFIG block below; nothing under it needs touching.
 */

// ── CONFIG ────────────────────────────────────────────────────────────────
const CONFIG = {
  // Columns in display order. Empty = the query's own order.
  columns: [
    'New / Used Flag',
    'New Retail',
    'vs. Last Year (NR)',
    'vs. Last Month (NR)',
    'New Non-Retail',
    'vs. Last Year (NNR)',
    'vs. Last Month (NNR)',
    'New Total',
    'vs. Last Year',
    'vs. Last Month',
  ],

  // Columns hidden entirely — anything the search selects but the tile must not show.
  hidden: ['__id__'],

  // { column: { type, decimals, fraction } }
  //   type: 'auto' | 'number' | 'percent' | 'thousands' | 'millions'
  //   'auto' abbreviates by magnitude the way TS does (1,120,000 → 1.12M, 254,000 → 254K),
  //   keeping `sig` significant digits (default 3).
  //   fraction: percent only — the value is already a rate (0.071 → 7.1%).
  formats: {
    'New Retail':          { type: 'auto', sig: 3 },
    'New Non-Retail':      { type: 'auto', sig: 3 },
    'New Total':           { type: 'auto', sig: 3 },
    'vs. Last Year (NR)':  { type: 'percent', decimals: 1, fraction: true },
    'vs. Last Month (NR)': { type: 'percent', decimals: 1, fraction: true },
    'vs. Last Year (NNR)': { type: 'percent', decimals: 1, fraction: true },
    'vs. Last Month (NNR)':{ type: 'percent', decimals: 1, fraction: true },
    'vs. Last Year':       { type: 'percent', decimals: 1, fraction: true },
    'vs. Last Month':      { type: 'percent', decimals: 1, fraction: true },
  },

  // { column: { neg, pos } } — text colour by sign, i.e. TS conditional formatting.
  signColors: {
    'vs. Last Year (NR)':  { neg: '#FF69B4', pos: '#31563A' },
    'vs. Last Month (NR)': { neg: '#FF69B4', pos: '#31563A' },
    'vs. Last Year (NNR)': { neg: '#FF69B4', pos: '#31563A' },
    'vs. Last Month (NNR)':{ neg: '#FF69B4', pos: '#31563A' },
    'vs. Last Year':       { neg: '#FF69B4', pos: '#31563A' },
    'vs. Last Month':      { neg: '#FF69B4', pos: '#31563A' },
  },

  // { nameUsedAbove: nameInTheQuery }. The keys above are display names, but the data
  // can arrive under the underlying column name instead (a "vs. Last Year" column
  // whose real name is "YoY"), so lookups fall back to these.
  aliases: {},

  // Sorting on the header. Off matches a native TS table tile in a PDF export.
  sort: true,
};
// Test harnesses replace the block above; production tiles never set this.
Object.assign(CONFIG, globalThis.__TABLE_TEST_CONFIG__ || {});
// ── END CONFIG ────────────────────────────────────────────────────────────

const isMeasure = c => c.type === 'MEASURE' || c.type === 'measure';

// Some clusters return cells as objects ({ value, formatted, ... }) instead of
// primitives, and `.value` is sometimes an accessor method rather than a property.
// Returning an object from a gridjs formatter also crashes its Preact renderer.
const cellVal = v => {
  if (v == null || typeof v !== 'object') return v;
  try {
    const raw = typeof v.value === 'function' ? v.value() : v.value;
    return raw ?? v._value ?? v.v ?? v.formatted ?? v.f ?? null;
  } catch {
    return v._value ?? null;
  }
};

// Date columns arrive as epoch millis.
const isEpochMs = v => Number.isFinite(Number(v)) && Number(v) > 1e11;
const fmtDim = v => isEpochMs(v)
  ? new Date(Number(v)).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
  : String(v);

// TS abbreviates by magnitude and keeps a fixed number of significant digits, so
// 1,120,000 reads 1.12M while 254,000 reads 254K — same column, different decimals.
function fmtAuto(n, sig = 3) {
  const a = Math.abs(n);
  const [div, suffix] = a >= 1e9 ? [1e9, 'B']
    : a >= 1e6 ? [1e6, 'M']
    : a >= 1e3 ? [1e3, 'K']
    : [1, ''];
  const scaled = a / div;
  const whole = Math.floor(scaled).toString().length;
  const d = Math.max(0, sig - whole);
  return (n < 0 ? '-' : '')
    + scaled.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })
    + suffix;
}

// TS renders negatives with a leading dash and always separates thousands.
function fmtValue(n, f) {
  if (!f) return n.toLocaleString();
  if (f.type === 'auto') return fmtAuto(n, f.sig);
  const d = f.decimals ?? 1;
  const o = { minimumFractionDigits: d, maximumFractionDigits: d };
  const sign = n < 0 ? '-' : '';
  const a = Math.abs(n);
  if (f.type === 'thousands') return sign + (a / 1e3).toLocaleString(undefined, o) + 'K';
  if (f.type === 'millions')  return sign + (a / 1e6).toLocaleString(undefined, o) + 'M';
  if (f.type === 'percent')   return (f.fraction ? n : n / 100).toLocaleString(undefined, { style: 'percent', ...o });
  return n.toLocaleString(undefined, o);
}

// Column names are matched loosely. TS hands back names that differ from the tile's
// header by whitespace alone -- a non-breaking space, a double space, a trailing one --
// and an exact-match lookup then silently misses: the column keeps its query position
// at the far right and renders unformatted (0.147 where 14.7% belongs). Normalising
// case and runs of any space makes the CONFIG keys above tolerant of that.
const norm = s => String(s).replace(/[\s ]+/g, ' ').trim().toLowerCase();
const byNorm = obj => Object.fromEntries(Object.entries(obj).map(([k, v]) => [norm(k), v]));

const FORMATS = byNorm(CONFIG.formats);
const SIGN_COLORS = byNorm(CONFIG.signColors);
const HIDDEN = CONFIG.hidden.map(norm);

// The name CONFIG uses for a column the data delivered under its underlying name.
const CONFIG_NAME = Object.fromEntries(
  Object.entries(CONFIG.aliases).map(([shown, actual]) => [norm(actual), shown]));
const configName = name => CONFIG_NAME[norm(name)] || name;

// True when a schema column is the one CONFIG calls `wanted`, directly or by alias.
const matches = (schemaName, wanted) =>
  norm(schemaName) === norm(wanted)
  || (CONFIG.aliases[wanted] && norm(schemaName) === norm(CONFIG.aliases[wanted]));

function signColor(n, name) {
  const c = SIGN_COLORS[norm(configName(name))];
  if (!c || !Number.isFinite(n) || n === 0) return null;
  return n < 0 ? c.neg : c.pos;
}

// ── Render (the BYOC sandbox masks exceptions — surface the real one) ────────
const chart = document.getElementById('chart');
try {
  await new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/gridjs/dist/gridjs.umd.js';
    s.crossOrigin = 'anonymous';   // surface real errors instead of "Script error."
    s.onload = res;
    s.onerror = () => rej(new Error('Failed to load Grid.js from the CDN — blocked by the sandbox CSP?'));
    document.head.appendChild(s);
  });

  const raw = viz.getDataFromSearchQuery().getData();

  // Drop hidden columns, then apply the configured order; anything CONFIG does not
  // name keeps its query position at the end.
  const visible = raw.schema.map((c, i) => i).filter(i => !HIDDEN.includes(norm(raw.schema[i].name)));
  const ordered = [
    ...CONFIG.columns.flatMap(n => visible.filter(i => matches(raw.schema[i].name, n))),
    ...visible,
  ].filter((v, i, a) => a.indexOf(v) === i);

  // A column CONFIG names but the query did not return, or returned under a name the
  // loose match still missed. Silent in the tile, so say it in the console.
  const missing = CONFIG.columns.filter(n => !raw.schema.some(c => matches(c.name, n)));
  if (missing.length) console.warn('[table-chart] not in the query:', missing,
    '— the query returned:', raw.schema.map(c => c.name));

  const columns = ordered.map(i => {
    const c = raw.schema[i];
    return {
      name: configName(c.name),
      id: String(i),   // stable id even when two columns share a name
      // Colour the <td> by sign via inline style — no HTML injection, so it works
      // regardless of the gridjs/Preact version the host page provides.
      attributes: cell => {
        if (cell == null) return {};   // header cell
        const color = signColor(Number(cell), c.name);
        return color ? { style: `color: ${color}` } : {};
      },
      formatter: cell => {
        if (cell == null || cell === '') return '';
        const n = Number(cell);
        if (!isMeasure(c) || isNaN(n)) return fmtDim(cell);
        return fmtValue(n, FORMATS[norm(configName(c.name))]);
      },
    };
  });

  // Data stays raw so `sort:true` sorts on the underlying numbers, not the strings.
  const data = raw.data.map(r => ordered.map(i => cellVal(r[i])));

  chart.innerHTML = '';
  new gridjs.Grid({ columns, data, sort: CONFIG.sort !== false }).render(chart);
  viz.events.emitRenderCompletedEvent();
} catch (err) {
  console.error('[table-chart] render failed:', err);
  chart.innerHTML = '<pre style="color:#d93025;white-space:pre-wrap;padding:12px;'
    + 'font:12px/1.5 monospace">' + (err?.stack || err?.message || String(err)) + '</pre>';
  // Still signal completion -- see the same guard in pivot-table.js: a silent tile
  // hangs the liveboard PDF export.
  try { viz.events.emitRenderCompletedEvent(); } catch {}
}
