/**
 * Custom flat table for ThoughtSpot BYOC, built on Grid.js.
 *
 * The table-mode counterpart to pivot-table.js: one CONFIG block per chart,
 * derived from the tile's liveboard TML. Paste your tile's block below and
 * nothing else here needs touching.
 */

// ── CONFIG ────────────────────────────────────────────────────────────────
const CONFIG = {
  // Columns in display order. Empty = the query's own order.
  columns: [],

  // Columns hidden entirely.
  hidden: ['__id__'],

  // { column: { type, decimals, fraction } }
  //   type: 'number' | 'percent' | 'thousands' | 'millions'
  //   fraction: percent only — the value is already a rate (0.473 → 47.3%).
  formats: {},

  // { column: { neg, pos } } — text colour by sign, i.e. TS conditional formatting.
  signColors: {},

  // { nameUsedAbove: nameInTheQuery }. The keys above are display names, but the data
  // can arrive under the underlying column name instead (a "vs. Last Year" column
  // whose real name is "YoY"), so lookups fall back to these.
  aliases: {},
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

// TS renders negatives with a leading dash and always separates thousands.
function fmtValue(n, f) {
  if (!f) return n.toLocaleString();
  const d = f.decimals ?? 1;
  const o = { minimumFractionDigits: d, maximumFractionDigits: d };
  const sign = n < 0 ? '-' : '';
  const a = Math.abs(n);
  if (f.type === 'thousands') return sign + (a / 1e3).toLocaleString(undefined, o) + 'K';
  if (f.type === 'millions')  return sign + (a / 1e6).toLocaleString(undefined, o) + 'M';
  if (f.type === 'percent')   return (f.fraction ? n : n / 100).toLocaleString(undefined, { style: 'percent', ...o });
  return n.toLocaleString(undefined, o);
}

// The name CONFIG uses for a column the data delivered under its underlying name.
const CONFIG_NAME = Object.fromEntries(
  Object.entries(CONFIG.aliases).map(([shown, actual]) => [actual, shown]));
const configName = name => CONFIG_NAME[name] || name;

function signColor(n, name) {
  const c = CONFIG.signColors[configName(name)];
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
  const visible = raw.schema.map((c, i) => i).filter(i => !CONFIG.hidden.includes(raw.schema[i].name));
  const ordered = [
    ...CONFIG.columns.flatMap(n => visible.filter(
      i => raw.schema[i].name === n || raw.schema[i].name === CONFIG.aliases[n])),
    ...visible,
  ].filter((v, i, a) => a.indexOf(v) === i);

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
        return fmtValue(n, CONFIG.formats[configName(c.name)]);
      },
    };
  });

  // Data stays raw so `sort:true` sorts on the underlying numbers, not the strings.
  const data = raw.data.map(r => ordered.map(i => cellVal(r[i])));

  chart.innerHTML = '';
  new gridjs.Grid({ columns, data, sort: true }).render(chart);
  viz.events.emitRenderCompletedEvent();
} catch (err) {
  console.error('[table-chart] render failed:', err);
  chart.innerHTML = '<pre style="color:#d93025;white-space:pre-wrap;padding:12px;'
    + 'font:12px/1.5 monospace">' + (err?.stack || err?.message || String(err)) + '</pre>';
  // Still signal completion -- see the same guard in pivot-table.js: a silent tile
  // hangs the liveboard PDF export.
  try { viz.events.emitRenderCompletedEvent(); } catch {}
}
