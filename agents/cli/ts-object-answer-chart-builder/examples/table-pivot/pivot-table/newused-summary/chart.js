// ── CONFIG ────────────────────────────────────────────────────────────────
const CONFIG = {
  // Attributes down the left and across the top. Either may be empty.
  // No column dimension here: this tile is a flat table, so every measure is its own
  // column and the pivot degenerates to one row per New / Used Flag.
  rowDims: ['New / Used Flag'],
  colDims: [],

  // Measures, in display order.
  measures: [
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

  // 'columns' = measures across the top | 'rows' = measures down the left.
  placement: 'columns',

  // The native pivot's "Measures / Values" band above the header. Only meaningful when
  // there is a column dimension for it to group; off for a flat table.
  axisLabels: false,

  // 'none' | 'pctOfColumn' — re-express each cell as a share of its column, the way
  // TS's percentOfColumnTotal / percentOfColumnGrandTotal summary modes do.
  summaryMode: 'none',

  // { measure: { type, decimals, fraction } }
  //   type: 'auto' | 'number' | 'percent' | 'thousands' | 'millions'
  //   'auto' abbreviates by magnitude the way TS does (1,120,000 → 1.12M,
  //   254,000 → 254K), keeping `sig` significant digits (default 3).
  //   fraction: percent only — the value is already a rate (0.473 → 47.3%).
  formats: {
    'New Retail':           { type: 'auto', sig: 3 },
    'New Non-Retail':       { type: 'auto', sig: 3 },
    'New Total':            { type: 'auto', sig: 3 },
    'vs. Last Year (NR)':   { type: 'percent', decimals: 1, fraction: true },
    'vs. Last Month (NR)':  { type: 'percent', decimals: 1, fraction: true },
    'vs. Last Year (NNR)':  { type: 'percent', decimals: 1, fraction: true },
    'vs. Last Month (NNR)': { type: 'percent', decimals: 1, fraction: true },
    'vs. Last Year':        { type: 'percent', decimals: 1, fraction: true },
    'vs. Last Month':       { type: 'percent', decimals: 1, fraction: true },
  },

  // { measure: { neg, pos } } — text colour by sign, i.e. TS conditional formatting.
  signColors: {
    'vs. Last Year (NR)':   { neg: '#FF69B4', pos: '#31563A' },
    'vs. Last Month (NR)':  { neg: '#FF69B4', pos: '#31563A' },
    'vs. Last Year (NNR)':  { neg: '#FF69B4', pos: '#31563A' },
    'vs. Last Month (NNR)': { neg: '#FF69B4', pos: '#31563A' },
    'vs. Last Year':        { neg: '#FF69B4', pos: '#31563A' },
    'vs. Last Month':       { neg: '#FF69B4', pos: '#31563A' },
  },

  // Bold summary row across the bottom. Off, as asked: the growth columns are not
  // summable and no base column is selected to rebuild them from, so a total row here
  // would be six blanks beside three sums.
  grandTotal: false,

  // Bold Total column down the right, summing across the column dimension. Only
  // meaningful when there is a column dimension to total across.
  rowTotal: false,

  // { measure: baseColumn } for growth rates, i.e. (current − prior) / prior.
  // Those cannot be summed: TS recomputes the formula at the total grain, so 3.3% +
  // 10.5% + 2.2% is not 16.0% but 7.1%. The prior period is implied by the rate itself
  // (prior = base / (1 + rate)), so the true total is rebuilt as
  //   Σ base / Σ (base / (1 + rate)) − 1
  // which reproduces TS exactly. `baseColumn` is the amount the rate is measured on.
  ratioTotal: {},

  // { measure: 'mean' } — how several query rows collapse into one cell. Adding up is
  // right for an amount and wrong for a share: where the query carries an attribute the
  // tile never displays, a cell holds one share per hidden bucket (12 monthly shares
  // under a year), and its own share is their average, not their sum — which is where
  // a 1,200% total comes from. TS would weight that average by the underlying volume;
  // no weight column is in the query, so this is the plain mean, exact wherever a cell
  // is a single row and within a tenth of a point where it is not.
  aggregate: {},

  // { measure: weightColumn } — a weighted average, for a measure that is itself an
  // average. The buy-rate tiles are `sum(rate × weight) / sum(weight)` per cell, so a
  // total is Σ(cell × weight) / Σ weight and nothing else: the four bands sum to
  // 29.89% and average 7.47% where TS shows 5.48%. `weightColumn` is that denominator,
  // `Total Str Weight`, selected alongside. It is an ordinary additive measure sitting
  // in the same rows as the cells, so it carries their filters exactly — including the
  // rolling-period window, which a column grouped one level up silently loses.
  weightedTotal: {},

  // Measures left blank in the total row — for a rate whose base column is not in the
  // query, where nothing can be rebuilt and a sum would be a plausible wrong number.
  noTotal: [],

  // { measure: columnHoldingItsTotal } — for a measure whose total cannot be built out
  // of the cells at all. `Current Month` on the buy-rate tiles is
  // group_aggregate([Buy Rate/IRR (Average)], query_groups(), …): an average, so the
  // total is neither the sum (29.89%) nor the mean (7.47%) of the four bands but the
  // average over every loan, 5.48% — a number that is simply not a function of the
  // four rows the chart receives. So the query carries a second column computed one
  // grain up, `query_groups()` minus the row dimension, which holds that total on
  // every row; the total line reads it instead of aggregating. Computed measures pick
  // their components up the same way, so their totals follow.
  //
  // The extra column is grouped one level up from the rows, which is the column total.
  // A tile with a column dimension would need a further column for the grand total;
  // none of the tiles using this have one.
  totalFrom: {},

  // Measures the chart works out itself, from other columns in the same query:
  //   { op: 'diff',  a, b, scale }  → (a − b) × scale   e.g. a percentage-point delta
  //   { op: 'ratio', a, b }         → (a − b) / b       e.g. a growth rate
  // TS evaluates these formulas only at the grain it displays. The rows handed to a
  // custom chart are finer (one per month, say), and at that grain the formula is
  // null in every row — which is why such a column arrives empty. Its components do
  // arrive, so the value is rebuilt per cell after aggregating, exactly as TS does
  // it. Totals follow from the same formula applied to the totals of the components.
  computed: {},

  // { nameUsedAbove: nameInTheQuery }. Everything above is written in the display
  // names a reader recognises, but the data can arrive keyed by the underlying column
  // name instead (a "vs. Last Year" column whose real name is "YoY"). Lookups try the
  // display name first and fall back to these, so either naming resolves.
  aliases: {},

  // Row order: 'asc' | 'desc' | 'none' (keep the order rows arrive in).
  sortRows: 'asc',
};
// Test harnesses replace the block above; production tiles never set this.
Object.assign(CONFIG, globalThis.__PIVOT_TEST_CONFIG__ || {});
// ── END CONFIG ────────────────────────────────────────────────────────────

const isMeasure = c => c.type === 'MEASURE' || c.type === 'measure';

// Some clusters return cells as objects ({ value, formatted, ... }) instead of
// primitives, and `.value` is sometimes an accessor method rather than a property.
const cellVal = v => {
  if (v == null || typeof v !== 'object') return v;
  try {
    const raw = typeof v.value === 'function' ? v.value() : v.value;
    return raw ?? v._value ?? v.v ?? v.formatted ?? v.f ?? null;
  } catch {
    return v._value ?? null;
  }
};

// Date dimensions arrive as epoch millis.
const isEpochMs = v => Number.isFinite(Number(v)) && Number(v) > 1e11;
const fmtDim = v => isEpochMs(v)
  ? new Date(Number(v)).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
  : v;

// TS abbreviates by magnitude and keeps a fixed number of significant digits, so
// 1,120,000 reads 1.12M while 254,000 reads 254K — same column, different decimals.
function fmtAuto(n, sig = 3) {
  const a = Math.abs(n);
  const [div, suffix] = a >= 1e9 ? [1e9, 'B']
    : a >= 1e6 ? [1e6, 'M']
    : a >= 1e3 ? [1e3, 'K']
    : [1, ''];
  const scaled = a / div;
  const d = Math.max(0, sig - Math.floor(scaled).toString().length);
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
  let s;
  if (f.type === 'thousands')     s = sign + (a / 1e3).toLocaleString(undefined, o) + 'K';
  else if (f.type === 'millions') s = sign + (a / 1e6).toLocaleString(undefined, o) + 'M';
  else if (f.type === 'percent')  s = (f.fraction ? n : n / 100).toLocaleString(undefined, { style: 'percent', ...o });
  else                            s = n.toLocaleString(undefined, o);
  // A total row that cancels out lands just below zero and rounds to "-0.0"; the
  // native tile shows "0.0". Decided on the rendered digits, so it holds whatever the
  // scale and precision are.
  return /^-0[.,0]*[^\d]*$/.test(s) ? s.slice(1) : s;
}

function signColor(n, measure) {
  const c = CONFIG.signColors[measure];
  if (!c || !Number.isFinite(n) || n === 0) return null;
  return n < 0 ? c.neg : c.pos;
}

// Fill anything CONFIG left blank from the schema, so a tile still renders if its
// block was never pasted in.
// Column names are matched loosely on the second attempt. TS hands back names that
// differ from the tile's header by whitespace alone -- a non-breaking space, a double
// space, a trailing one -- and an exact-match lookup then silently misses, dropping the
// measure from the table. Normalising case and runs of any space makes the CONFIG names
// above tolerant of that. Exact match is still tried first, so nothing else shifts.
const norm = s => String(s).replace(/[\s ]+/g, ' ').trim().toLowerCase();

const NORM_INDEX = new WeakMap();
const normIndex = at => {
  let m = NORM_INDEX.get(at);
  if (!m) {
    m = Object.fromEntries(Object.entries(at).map(([k, v]) => [norm(k), v]));
    NORM_INDEX.set(at, m);
  }
  return m;
};

// A column's position, under whichever of its two names the data actually uses.
function indexOf(name, at) {
  const exact = at[name] ?? at[CONFIG.aliases[name]];
  if (exact !== undefined) return exact;   // 0 is a valid index, hence `??` not `||`
  const m = normIndex(at);
  return m[norm(name)] ?? m[norm(CONFIG.aliases[name] ?? '\0')];
}

// Why a configured column produced nothing: absent from the query, or present but
// empty. Silent em-dashes hide both, so this is surfaced above the table.
function diagnose(schema, data) {
  const at = Object.fromEntries(schema.map((c, i) => [c.name, i]));
  const notes = [];
  const check = (n, numeric) => {
    const i = indexOf(n, at);
    if (i === undefined) { notes.push(`${n}: no such column`); return; }
    // Dimensions carry labels, measures carry numbers — test each on its own terms.
    const filled = data.reduce((c, r) =>
      c + (numeric ? Number.isFinite(Number(r[i])) : r[i] != null && r[i] !== ''), 0);
    if (!filled) notes.push(`${n}: column found, all ${data.length} rows empty`);
  };
  [...CONFIG.rowDims, ...CONFIG.colDims].forEach(n => check(n, false));
  CONFIG.measures.filter(n => !CONFIG.computed[n]).forEach(n => check(n, true));
  return notes.length
    ? `${notes.join(' · ')} — columns in this query: ${schema.map(c => c.name).join(', ')}`
    : null;
}

function resolve(schema) {
  const at = Object.fromEntries(schema.map((c, i) => [c.name, i]));
  const names = { has: n => indexOf(n, at) !== undefined };
  const keep = list => list.filter(n => names.has(n));
  CONFIG.measures = CONFIG.measures.filter(n => CONFIG.computed[n] || names.has(n));
  CONFIG.rowDims  = keep(CONFIG.rowDims);
  CONFIG.colDims  = keep(CONFIG.colDims);
  if (!CONFIG.measures.length) CONFIG.measures = schema.filter(isMeasure).map(c => c.name);
  if (!CONFIG.rowDims.length && !CONFIG.colDims.length) {
    CONFIG.rowDims = schema.filter(c => !isMeasure(c)).map(c => c.name);
  }
}

// Evaluate a computed measure from its two aggregated components.
function derive(spec, a, b) {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  if (spec.op === 'ratio') return b ? (a - b) / b : null;
  return (a - b) * (spec.scale ?? 1);
}

// Numbers compare as numbers (epoch-ms dates, "12-48" before "49-63"), everything else
// naturally, so "2 - 91 to 100" lands after "1 - 0 to 90" rather than before "10".
function compareKeys(a, b) {
  const x = Number(a), y = Number(b);
  if (Number.isFinite(x) && Number.isFinite(y)) return x - y;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

// cell(rowKey, colKey, measure) → number | null, already summary-transformed.
function buildMatrix(schema, data) {
  const raw = Object.fromEntries(schema.map((c, i) => [c.name, i]));
  const at = name => indexOf(name, raw);
  const { rowDims, colDims, measures } = CONFIG;
  const rowKeys = [], colKeys = [], cells = {};

  // Columns that are not displayed are aggregated too when something derives from
  // them: the components of a computed measure, and the base of a ratio total.
  const computed = CONFIG.computed;
  const tracked = [...new Set([
    ...measures.filter(m => !computed[m]),
    ...Object.values(computed).flatMap(c => [c.a, c.b]),
    ...Object.values(CONFIG.ratioTotal),
    ...Object.values(CONFIG.weightedTotal),
  ])].filter(m => at(m) !== undefined);

  // A total column already holds its value on every row of the group, so it is kept as
  // it arrives rather than added up.
  const carried = [...new Set(Object.values(CONFIG.totalFrom))].filter(m => at(m) !== undefined);
  const held = {};

  // Rows behind each cell, for the measures that average rather than add.
  const averaged = CONFIG.aggregate || {};
  const counts = {};

  for (const row of data) {
    const rk = rowDims.map(d => String(row[at(d)] ?? '')).join('\0');
    const ck = colDims.map(d => String(row[at(d)] ?? '')).join('\0');
    if (!rowKeys.includes(rk)) rowKeys.push(rk);
    if (!colKeys.includes(ck)) colKeys.push(ck);
    cells[rk] ??= {};
    cells[rk][ck] ??= {};
    counts[rk] ??= {};
    counts[rk][ck] ??= {};
    for (const m of tracked) {
      const v = Number(row[at(m)]);
      if (!Number.isFinite(v)) continue;
      cells[rk][ck][m] = (cells[rk][ck][m] ?? 0) + v;
      counts[rk][ck][m] = (counts[rk][ck][m] ?? 0) + 1;
    }
    held[rk] ??= {};
    held[rk][ck] ??= {};
    for (const m of carried) {
      const v = Number(row[at(m)]);
      if (Number.isFinite(v) && held[rk][ck][m] === undefined) held[rk][ck][m] = v;
    }
  }

  // Shares divide back down before anything reads them, so computed measures and every
  // total downstream see the cell's own value rather than a hidden-grain sum.
  for (const rk of rowKeys) {
    for (const ck of colKeys) {
      const bag = cells[rk]?.[ck];
      if (!bag) continue;
      for (const m of tracked) {
        const n = counts[rk]?.[ck]?.[m];
        if (averaged[m] === 'mean' && n > 1) bag[m] /= n;
      }
    }
  }

  // Computed measures are evaluated per cell, once the components are aggregated.
  for (const rk of rowKeys) {
    for (const ck of colKeys) {
      const bag = cells[rk]?.[ck];
      if (!bag) continue;
      for (const [m, spec] of Object.entries(computed)) bag[m] = derive(spec, bag[spec.a], bag[spec.b]);
    }
  }

  // Both axes arrive in query order, which is not the order the native pivot shows —
  // months especially come back shuffled.
  if (CONFIG.sortRows !== 'none') {
    const dir = CONFIG.sortRows === 'desc' ? -1 : 1;
    rowKeys.sort((a, b) => dir * compareKeys(a, b));
  }
  colKeys.sort(compareKeys);

  // Kept pre-summary: totalling shares across columns would give 200% for two months,
  // where the native pivot shows the row's share of everything.
  const preSummary = {};
  for (const rk of rowKeys) {
    preSummary[rk] = {};
    for (const ck of colKeys) preSummary[rk][ck] = { ...(cells[rk]?.[ck] || {}) };
  }
  const summarized = CONFIG.summaryMode === 'pctOfColumn';

  if (CONFIG.summaryMode === 'pctOfColumn') {
    for (const ck of colKeys) {
      for (const m of measures) {
        const total = rowKeys.reduce((s, rk) => s + (cells[rk]?.[ck]?.[m] ?? 0), 0);
        for (const rk of rowKeys) {
          const v = cells[rk]?.[ck]?.[m];
          if (v != null) cells[rk][ck][m] = total ? v / total : null;
        }
      }
    }
  }

  const cell = (rk, ck, m) => cells[rk]?.[ck]?.[m] ?? null;

  // Totals of a computed measure come from re-applying its formula to the totals of
  // its components — never from adding up the derived values.
  // What a measure is worth over a set of cells. A measure whose total the query
  // carries reads it off; everything else adds up.
  // An average re-averages over the cells, weighted the way it was built. Every cell is
  // Σ(rate × weight) / Σ weight, so Σ(cell × weight) recovers the numerator and the
  // division happens once, at whatever grain the total covers.
  const weightedOf = (pairs, name) => {
    const w = CONFIG.weightedTotal[name];
    let num = 0, den = 0;
    for (const [rk, ck] of pairs) {
      const v = cells[rk]?.[ck]?.[name], q = cells[rk]?.[ck]?.[w];
      if (!Number.isFinite(v) || !Number.isFinite(q)) continue;
      num += v * q;
      den += q;
    }
    return den ? num / den : null;
  };

  const sumOf = (pairs, name) => {
    if (CONFIG.weightedTotal[name]) return weightedOf(pairs, name);
    const carry = CONFIG.totalFrom[name];
    if (carry) {
      const v = pairs.map(([rk, ck]) => held[rk]?.[ck]?.[carry]).find(Number.isFinite);
      return v === undefined ? null : v;
    }
    const vals = pairs.map(([rk, ck]) => cells[rk]?.[ck]?.[name]).filter(Number.isFinite);
    return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
  };
  const deriveOver = (pairs, m) =>
    derive(computed[m], sumOf(pairs, computed[m].a), sumOf(pairs, computed[m].b));

  const columnTotal = (ck, m) => {
    if (CONFIG.noTotal.includes(m)) return null;
    if (computed[m]) return deriveOver(rowKeys.map(rk => [rk, ck]), m);
    if (CONFIG.weightedTotal[m] || CONFIG.totalFrom[m]) return sumOf(rowKeys.map(rk => [rk, ck]), m);

    // A growth rate: rebuild both periods from the base column, then divide once.
    const base = CONFIG.ratioTotal[m];
    if (base) {
      let now = 0, prior = 0;
      for (const rk of rowKeys) {
        const b = cell(rk, ck, base), rate = cell(rk, ck, m);
        if (!Number.isFinite(b) || !Number.isFinite(rate) || rate === -1) return null;
        now += b;
        prior += b / (1 + rate);
      }
      return prior ? now / prior - 1 : null;
    }

    const vals = rowKeys.map(rk => cell(rk, ck, m)).filter(Number.isFinite);
    return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
  };

  const rawTotal = (pairs, m) => {
    const vals = pairs.map(([rk, ck]) => preSummary[rk]?.[ck]?.[m]).filter(Number.isFinite);
    return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
  };
  const everything = rowKeys.flatMap(rk => colKeys.map(ck => [rk, ck]));

  // Across a row: a share of everything when summarised, otherwise a plain sum.
  const rowTotal = (rk, m) => {
    if (computed[m]) return deriveOver(colKeys.map(ck => [rk, ck]), m);
    if (CONFIG.noTotal.includes(m) || CONFIG.ratioTotal[m]) return null;
    // Across a row the weights are per column, so the same one-division rule holds.
    if (CONFIG.weightedTotal[m]) return sumOf(colKeys.map(ck => [rk, ck]), m);
    // The carried column is grouped one level up from the rows, which makes it the
    // column total. Totalling one across a row would need its own column; blank beats
    // a plausible wrong number.
    if (CONFIG.totalFrom[m]) return null;
    const across = rawTotal(colKeys.map(ck => [rk, ck]), m);
    if (!summarized) return across;
    const grand = rawTotal(everything, m);
    return (Number.isFinite(across) && grand) ? across / grand : null;
  };
  const grandTotal = m => {
    if (computed[m]) return deriveOver(everything, m);
    if (CONFIG.noTotal.includes(m) || CONFIG.ratioTotal[m]) return null;
    if (CONFIG.weightedTotal[m] || CONFIG.totalFrom[m]) return sumOf(everything, m);
    return summarized ? 1 : rawTotal(everything, m);
  };

  return { rowKeys, colKeys, cell, columnTotal, rowTotal, grandTotal };
}

// ── DOM ─────────────────────────────────────────────────────────────────────
const th = (text, cls, span = {}) => {
  const n = document.createElement('th');
  n.textContent = text;
  if (cls) n.className = cls;
  if (span.colSpan > 1) n.colSpan = span.colSpan;
  if (span.rowSpan > 1) n.rowSpan = span.rowSpan;
  return n;
};

const td = (text, cls, color) => {
  const n = document.createElement('td');
  n.textContent = text;
  if (cls) n.className = cls;
  if (color) n.style.color = color;
  return n;
};

// Colour follows the rendered digits, not the raw sign: -0.006 displays as "0.0",
// which the native pivot leaves uncoloured.
const valueCell = (v, m, cls) => {
  if (v == null) return td('—', cls + ' empty');
  const text = fmtValue(v, CONFIG.formats[m]);
  return td(text, cls, /[1-9]/.test(text) ? signColor(v, m) : null);
};

// A label function for one axis. A date column whose values all land on 1 January is a
// year-grain column, so it reads "2023" rather than "Jan 2023".
function labeller(keys) {
  const parts = (keys[0] || '').split('\0').map((_, i) => keys.map(k => k.split('\0')[i]));
  const yearOnly = parts.map(vals => vals.length > 1 && vals.every(v => {
    if (!isEpochMs(v)) return false;
    const d = new Date(Number(v));
    return d.getUTCMonth() === 0 && d.getUTCDate() === 1;
  }));
  return k => k.split('\0')
    .map((v, i) => yearOnly[i] ? String(new Date(Number(v)).getUTCFullYear()) : fmtDim(v))
    .join(' / ');
}

// Corner labels above the measure-name column when measures sit on the rows.
const MEASURE_AXIS_LABEL = 'Measures';
const VALUE_AXIS_LABEL   = 'Values';

// Measures across the top, nested under each column-dim group when there is one.
function renderMeasuresOnColumns(matrix) {
  const { rowKeys, colKeys, cell, columnTotal, rowTotal, grandTotal } = matrix;
  const { rowDims, colDims, measures } = CONFIG;
  // Measure names only need their own header row when several sit under each group.
  const grouped = colDims.length > 0 && measures.length > 1;
  const showTotal = CONFIG.grandTotal && rowKeys.length > 1;
  const showRowTotal = CONFIG.rowTotal && colDims.length > 0 && colKeys.length > 1;
  const keyLabel = labeller(colKeys);
  const rowLabel = labeller(rowKeys);

  const table = document.createElement('table');
  table.className = 'pivot-table';
  const head = table.createTHead();

  if (grouped) {
    const r1 = head.insertRow(), r2 = head.insertRow();
    rowDims.forEach(d => r1.appendChild(th(d, 'dim-header', { rowSpan: 2 })));
    colKeys.forEach(ck => r1.appendChild(th(keyLabel(ck), 'col-group', { colSpan: measures.length })));
    if (showRowTotal) r1.appendChild(th('Total', 'col-group total-col', { colSpan: measures.length }));
    const groups = showRowTotal ? colKeys.length + 1 : colKeys.length;
    for (let g = 0; g < groups; g++) {
      measures.forEach((m, i) => r2.appendChild(th(m, 'measure-header'
        + (i === 0 ? ' group-start' : '') + (g === colKeys.length ? ' total-col' : ''))));
    }
  } else if (colDims.length) {
    // A single measure under a column dimension: name the dimension on top, its
    // values underneath.
    const r1 = head.insertRow(), r2 = head.insertRow();
    // The native pivot names the single measure in the corner above the row dim.
    if (rowDims.length) r1.appendChild(
      th(measures.length === 1 ? measures[0] : '', 'dim-header', { colSpan: rowDims.length }));
    r1.appendChild(th(colDims.join(' / '), 'col-group', { colSpan: colKeys.length }));
    if (showRowTotal) r1.appendChild(th('Total', 'col-group total-col', { rowSpan: 2 }));
    rowDims.forEach(d => r2.appendChild(th(d, 'dim-header')));
    colKeys.forEach(ck => r2.appendChild(th(keyLabel(ck), 'col-group')));
  } else {
    // Measures straight across the top. The corner names the two field areas the
    // way the native pivot does: Measures above the row dimension, Values above
    // the measure names. With no column dimension that band groups nothing and just
    // costs a row of tile height, so `axisLabels: false` drops it — see CONFIG.
    if (CONFIG.axisLabels !== false) {
      const r1 = head.insertRow();
      if (rowDims.length) r1.appendChild(th(MEASURE_AXIS_LABEL, 'dim-header', { colSpan: rowDims.length }));
      r1.appendChild(th(VALUE_AXIS_LABEL, 'col-group', { colSpan: measures.length }));
    }
    const r2 = head.insertRow();
    rowDims.forEach(d => r2.appendChild(th(d, 'dim-header')));
    measures.forEach(m => r2.appendChild(th(m, 'col-value-header')));
  }

  const body = table.createTBody();
  for (const rk of rowKeys) {
    const tr = body.insertRow();
    if (rowDims.length) rowLabel(rk).split(' / ').forEach(v => tr.appendChild(td(v, 'dim-cell')));
    for (const ck of colKeys) {
      measures.forEach((m, i) => tr.appendChild(
        valueCell(cell(rk, ck, m), m, 'value-cell' + (grouped && i === 0 ? ' group-start' : ''))));
    }
    if (showRowTotal) {
      measures.forEach((m, i) => tr.appendChild(valueCell(rowTotal(rk, m), m,
        'value-cell total-col' + (grouped && i === 0 ? ' group-start' : ''))));
    }
  }

  if (showTotal) {
    const tr = table.createTFoot().insertRow();
    const label = td('Grand total', 'dim-cell total-row-label');
    label.colSpan = Math.max(1, rowDims.length);
    tr.appendChild(label);
    for (const ck of colKeys) {
      measures.forEach((m, i) => tr.appendChild(
        valueCell(columnTotal(ck, m), m, 'value-cell total-row' + (grouped && i === 0 ? ' group-start' : ''))));
    }
    if (showRowTotal) {
      measures.forEach((m, i) => tr.appendChild(valueCell(grandTotal(m), m,
        'value-cell total-row total-col grand-total' + (grouped && i === 0 ? ' group-start' : ''))));
    }
  }

  return table;
}

// Measures down the left, column dims spread across the top.
function renderMeasuresOnRows(matrix) {
  const { rowKeys, colKeys, cell, columnTotal, rowTotal } = matrix;
  const { rowDims, colDims, measures } = CONFIG;
  const showRowTotal = CONFIG.rowTotal && colDims.length > 0 && colKeys.length > 1;
  const keyLabel = labeller(colKeys);
  const rowLabel = labeller(rowKeys);

  const table = document.createElement('table');
  table.className = 'pivot-table';

  // Two header rows, matching the native pivot: the column dimension's name spans all
  // of its values on top, the values themselves sit underneath, and the corner above
  // the measure-name column reads Measures / Values.
  const head = table.createTHead();
  const r1 = head.insertRow(), r2 = head.insertRow();
  rowDims.forEach(d => r1.appendChild(th(d, 'dim-header', { rowSpan: 2 })));
  r1.appendChild(th(MEASURE_AXIS_LABEL, 'dim-header'));
  r2.appendChild(th(VALUE_AXIS_LABEL, 'dim-header'));
  r1.appendChild(th(colDims.join(' / '), 'col-group', { colSpan: colKeys.length }));
  if (showRowTotal) r1.appendChild(th('Total', 'col-group total-col', { rowSpan: 2 }));
  colKeys.forEach(ck => r2.appendChild(th(keyLabel(ck), 'col-group')));

  const body = table.createTBody();
  for (const rk of rowKeys) {
    measures.forEach((m, i) => {
      const tr = body.insertRow();
      if (i === 0 && rowDims.length) {
        rowLabel(rk).split(' / ').forEach(v => {
          const c = td(v, 'dim-cell');
          c.rowSpan = measures.length;
          tr.appendChild(c);
        });
      }
      tr.appendChild(td(m, 'dim-cell measure-row'));
      colKeys.forEach(ck => tr.appendChild(valueCell(cell(rk, ck, m), m, 'value-cell')));
      if (showRowTotal) tr.appendChild(valueCell(rowTotal(rk, m), m, 'value-cell total-col'));
    });
  }

  // One total line per measure. With a single row key the totals would just repeat
  // the body, so they are skipped.
  if (CONFIG.grandTotal && rowKeys.length > 1) {
    const foot = table.createTFoot();
    measures.forEach((m, i) => {
      const tr = foot.insertRow();
      if (i === 0 && rowDims.length) {
        const c = td('Grand total', 'dim-cell total-row-label');
        c.rowSpan = measures.length;
        tr.appendChild(c);
      }
      tr.appendChild(td(m, 'dim-cell total-row-label'));
      colKeys.forEach(ck => tr.appendChild(valueCell(columnTotal(ck, m), m, 'value-cell total-row')));
      if (showRowTotal) tr.appendChild(valueCell(matrix.grandTotal(m), m,
        'value-cell total-row total-col grand-total'));
    });
  }

  return table;
}

// ── Debug: what precision does the chart actually receive? ──────────────────
// Off unless the liveboard URL carries `?pivotdebug=1`, so it can be turned on in
// production without a rewrite. Answers one question: are the values handed to the
// chart already rounded to the column's display format (5.63) or full precision
// (5.6312...)? If they arrive rounded, a weighted total rebuilt from them inherits
// that rounding and no change to the weight can fix it -- the total has to be read
// off the query (`totalFrom`) instead of recomputed.
function debugRawPrecision(schema, data) {
  // The chart runs in a sandboxed iframe, so `location` is the iframe's, not the
  // liveboard's -- and the liveboard is a hash route, where a query after the `#` is
  // not `location.search` at all. Put `?pivotdebug=1` BEFORE the hash and it lands in
  // the iframe's referrer (referrers carry the query, minus the fragment), which is
  // the only place the parent URL is legible from in here.
  if (!/pivotdebug/.test(location.search)
      && !/pivotdebug/.test(document.referrer)
      && !globalThis.__PIVOT_DEBUG__) return;
  const names = schema.map(c => c.name);
  const at = Object.fromEntries(schema.map((c, i) => [c.name, i]));
  const log = (...a) => console.log('[pivot-debug]', ...a);
  log('columns:', names);
  for (const [measure, weight] of Object.entries(CONFIG.weightedTotal)) {
    // Alias-aware: the config is written in display names, the data may be keyed by
    // the underlying column name.
    const mi = indexOf(measure, at), wi = indexOf(weight, at);
    if (mi === undefined) { log(measure, '-> NOT IN SCHEMA'); continue; }
    // 17 significant digits: the shortest round-trip form of a double. A value that
    // was rounded to 2dp upstream prints as 5.6299999999999999, not 5.6312481....
    const vals = data.map(r => r[mi]).filter(Number.isFinite);
    log(measure, 'raw values:', vals.map(v => v.toPrecision(17)));
    log(measure, 'rounded-to-2dp already?',
        vals.every(v => Math.abs(v * 100 - Math.round(v * 100)) < 1e-9));
    if (wi === undefined) { log('  weight', weight, '-> NOT IN SCHEMA'); continue; }
    let num = 0, den = 0;
    data.forEach(r => {
      const v = r[mi], q = r[wi];
      if (Number.isFinite(v) && Number.isFinite(q)) { num += v * q; den += q; }
    });
    log('  weighted total =', den ? (num / den).toPrecision(17) : null,
        '(num', num, '/ den', den, ')');
  }
}

// ── Render (the BYOC sandbox masks exceptions — surface the real one) ────────
const chart = document.getElementById('chart');
try {
  const raw = viz.getDataFromSearchQuery().getData();
  const data = raw.data.map(r => r.map(cellVal));
  debugRawPrecision(raw.schema, data);
  const problem = diagnose(raw.schema, data);
  resolve(raw.schema);

  const scroll = document.createElement('div');
  scroll.className = 'pivot-scroll';
  scroll.appendChild(CONFIG.placement === 'rows'
    ? renderMeasuresOnRows(buildMatrix(raw.schema, data))
    : renderMeasuresOnColumns(buildMatrix(raw.schema, data)));

  chart.innerHTML = '';
  if (problem) {
    const warn = document.createElement('div');
    warn.className = 'pivot-warn';
    warn.textContent = problem;
    chart.appendChild(warn);
  }
  chart.appendChild(scroll);
  viz.events.emitRenderCompletedEvent();
} catch (err) {
  console.error('[pivot] render failed:', err);
  chart.innerHTML = '<pre style="color:#d93025;white-space:pre-wrap;padding:12px;'
    + 'font:12px/1.5 monospace">' + (err?.stack || err?.message || String(err)) + '</pre>';
  // Still signal completion. Liveboard PDF export waits for every tile to report in,
  // so a tile that throws and stays silent hangs the whole export -- one broken tile
  // would mean no PDF at all. The events API has no error emitter to use instead.
  try { viz.events.emitRenderCompletedEvent(); } catch {}
}
