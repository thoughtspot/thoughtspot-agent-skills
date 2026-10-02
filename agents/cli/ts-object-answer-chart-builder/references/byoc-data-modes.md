# ThoughtSpot BYOC — sample data vs. live data vs. both

A custom chart gets opened in three different places, and they do not all have data:

1. a **live tile** on a Liveboard, bound to a search that returns rows;
2. an **unbound tile** — the chart editor before a search is attached, or a chart
   someone was handed without the model;
3. a **plain browser**, with no `viz` global at all, for local preview.

The data mode decides which of the three the file survives. Pick one deliberately.

---

## Mode A — Sample only

Paste-and-run with **no data source attached**. The rows live in the file.

```js
const { muze } = viz;
const { DataModel } = muze;          // viz.muze is the SYNC DataModel in BYOC

const SAMPLE_SCHEMA = [
  { name: 'Type of Sale', type: 'dimension' },
  { name: 'Retail Sales', type: 'measure', defAggFn: 'sum' },
];

// Array of OBJECTS keyed by column name.
const SAMPLE_DATA = [
  { 'Type of Sale': 'Cash Sales',    'Retail Sales': 224000 },
  { 'Type of Sale': 'Finance Sales', 'Retail Sales': 643000 },
  { 'Type of Sale': 'Lease Sales',   'Retail Sales': 249000 },
];

const rows = SAMPLE_DATA;
const dm = new DataModel(DataModel.loadDataSync(SAMPLE_DATA, SAMPLE_SCHEMA));
```

Use it for: demos, design iteration, handing a chart to someone with no model,
checking layout and print behaviour before the search exists.

Cost: the chart never shows real numbers until someone edits the file.

---

## Mode B — Live only

The shape every production tile ends up in.

```js
const { muze, getDataFromSearchQuery } = viz;
const { DataModel } = muze;

const liveDM = getDataFromSearchQuery();
const raw = liveDM.getData();        // { schema: [{name, type}], data: [[…], …] }
```

`getData()` returns **array rows**, not objects. Normalise them immediately so the
rest of the file never has to care:

```js
const rows = raw.data.map(arr => {
  const o = {};
  raw.schema.forEach((c, i) => { o[c.name] = cellVal(arr[i]); });
  return o;
});
```

Requirements and gotchas:

- The search must select **every** column the chart names. A column the chart asks
  for and the search omits is simply absent — not an error, just missing.
- Two columns with the same display name collide in the DataModel; one silently
  overwrites the other. Fix the search, not the chart.
- `vs. Last Month` / `vs. Last Year` style columns arrive **empty** unless the search
  also selects the prior period.
- Date dimensions arrive as **epoch milliseconds**.
- Some clusters return cells as objects rather than primitives — always unwrap.

```js
// Cells sometimes arrive as { value, formatted, … }, and `.value` is occasionally a
// method rather than a property. Passing an unwrapped object cell into gridjs or a
// formatter crashes it with an opaque "Script error."
const cellVal = v => {
  if (v == null || typeof v !== 'object') return v;
  try {
    const raw = typeof v.value === 'function' ? v.value() : v.value;
    return raw ?? v._value ?? v.v ?? v.formatted ?? v.f ?? null;
  } catch {
    return v._value ?? null;
  }
};
```

---

## Mode C — Live, falling back to sample (the default)

One file that works in all three places. Live data when there is any; the baked-in
rows when there is not; a visible badge whenever it fell back, so nobody mistakes
sample numbers for real ones.

```js
// ── Data mode ───────────────────────────────────────────────────────────────
// 'auto'   live data, sample data when there is none  (default)
// 'live'   live only — render an explicit message if the query returns nothing
// 'sample' sample only — ignore any attached search
const DATA_MODE = 'auto';

// Reach the host through the BARE identifier, not `globalThis.viz`. A host that
// scopes `viz` to the wrapper it runs the JS tab in leaves the global undefined,
// and the chart then silently shows sample rows AND never fires
// emitRenderCompletedEvent — the tile hangs on "Chart did not render". `typeof`
// throws on a binding still in its temporal dead zone, hence the try.
function getViz() {
  try { if (typeof viz !== 'undefined' && viz) return viz; } catch (e) {}
  try { if (globalThis.viz) return globalThis.viz; } catch (e) {}
  return null;
}

const viz_ = getViz() || {};
const muze = viz_.muze;                 // undefined in a plain browser — see below
const DataModel = muze && muze.DataModel;

const SAMPLE_SCHEMA = [ /* … */ ];
const SAMPLE_DATA   = [ /* … */ ];

// Both branches produce the same thing: `rows`, an array of objects keyed by
// column name, and `schema`. Nothing downstream branches on the mode.
function loadRows() {
  if (DATA_MODE !== 'sample') {
    try {
      const dm = viz_.getDataFromSearchQuery && viz_.getDataFromSearchQuery();
      const raw = dm && dm.getData();
      if (raw && raw.data && raw.data.length) {
        return {
          source: 'live',
          schema: raw.schema,
          rows: raw.data.map(arr => {
            const o = {};
            raw.schema.forEach((c, i) => { o[c.name] = cellVal(arr[i]); });
            return o;
          }),
        };
      }
    } catch (err) {
      // No search attached, no `viz`, or the query failed. Fall through.
      console.warn('[chart] live data unavailable:', err);
    }
    if (DATA_MODE === 'live') return { source: 'empty', schema: [], rows: [] };
  }
  return { source: 'sample', schema: SAMPLE_SCHEMA, rows: SAMPLE_DATA };
}

const { source, schema, rows } = loadRows();

// Only Muze charts need the DataModel. A gridjs / HTML-table / raw-SVG chart works
// off `rows` alone, which is what lets it render in a plain browser with no `viz`.
const dm = DataModel && new DataModel(DataModel.loadDataSync(rows, schema));
```

Then say so on screen. Silent fallback is the failure mode worth avoiding — a tile
showing plausible sample numbers reads exactly like a tile showing real ones:

```js
const el = document.getElementById('chart');
if (source === 'sample') el.classList.add('is-sample');
if (source === 'empty')  el.innerHTML = '<div class="chart-empty">No rows returned by the search.</div>';
```

```css
.is-sample::before {
  content: 'sample data';
  position: absolute; top: 6px; right: 8px;
  font: 10px/1 Inter, system-ui, sans-serif; letter-spacing: .04em;
  text-transform: uppercase; color: #8a6d3b;
  background: #fdf3d8; border-radius: 3px; padding: 3px 6px;
}
#chart { position: relative; }
```

---

## Render, whichever mode

The sandbox masks exceptions behind a generic "Something went wrong", and the
Liveboard PDF export waits for every tile to report in — a tile that throws and stays
silent hangs the export for the whole board. So: surface the real error, and emit
completion on **both** paths.

```js
function signalRenderComplete() {
  try {
    getViz().events.emitRenderCompletedEvent();
  } catch (err) {
    // Never `catch {}` here. A swallowed failure is exactly how a tile hangs the
    // PDF export with nothing anywhere to explain it.
    console.warn('[chart] emitRenderCompletedEvent unavailable:', err);
  }
}

try {
  render(rows, schema);
} catch (err) {
  console.error('[chart] render failed:', err);
  el.innerHTML = '<pre style="color:#d93025;white-space:pre-wrap;padding:12px;'
    + 'font:12px/1.5 monospace">' + (err?.stack || String(err)) + '</pre>';
}
signalRenderComplete();
```

## Sizing, whichever mode

Worth stating here because it is the other way a chart that ran cleanly shows up as
an empty tile. `#chart` is a child of a `<body>` with **no explicit height**, so a
percentage height collapses to the content height and the chart stage inside it is
0px. `chart.css` has to complete the chain itself:

```css
html, body { height: 100%; margin: 0; }   /* load-bearing, not boilerplate */
#chart     { height: 100%; }
```

Full detail, and how the snap diagnostic detects it, in `hard-rules.md`.

---

## Previewing locally, with no `viz` at all

Mode C already handles a missing `viz` for non-Muze charts (HTML tables, gridjs, raw
SVG) — open the HTML file and it renders the sample rows.

A Muze chart still needs `viz.muze`, so a local preview harness stubs it. Keep the
stub in the preview HTML, never in the shipped JS:

```html
<div id="chart"></div>
<script>
  globalThis.viz = {
    muze: /* Muze from a CDN or a local build */,
    getDataFromSearchQuery: () => ({
      getData: () => ({ schema: [ /* … */ ], data: [ /* array rows */ ] }),
    }),
    events: { emitRenderCompletedEvent() {} },
  };
</script>
<script type="module" src="chart.js"></script>
```

Drop `getDataFromSearchQuery` from the stub to exercise the sample-data fallback.

---

## Which to pick

| Situation | Mode |
|---|---|
| Building against a real search, chart is going straight onto a live tile | B |
| Demo, mockup, print/layout work, or sharing with someone who has no model | A |
| Anything else, and every chart you want to be reusable | **C** |

Mode C costs about twenty lines over mode B and removes the whole class of "it works
on my tile" problems. Make it the default and let the user narrow it.
