# Muze chart-building reference — recipes and patterns

> Adapted from an older Muze Studio chat pipeline. The recipes and API details below
> are still good; where anything here conflicts with SKILL.md or the references/ files
> (especially references/hard-rules.md), those win.

## Workflow, output format, and data

The workflow (iterate in the headed preview, screenshot, critique, fix) is defined in
SKILL.md; the output is always the three paste-ready files chart.html / chart.css /
chart.js, verified against references/emit-checklist.md. Sample data is written once to
`<RUNS>/<SLUG>/sample-data.json` and never regenerated mid-loop (SKILL.md step 3). The
simplify pass (drop config matching defaults, hoist non-default values into the
Customize block, remove debug code, drop layers with no visible effect) happens
unconditionally at emit — see emit-checklist section 5 and *Defaults First* below.
Static HTML belongs in chart.html and fixed styling in chart.css, not in JS. Data
modes (sample / live / fallback) are in references/byoc-data-modes.md.

## BYOC entry point

Every chart runs against the host-provided `viz` global — the skill's preview stubs
the same shape, so there is no porting step and no comment-toggling between
"standalone" and "ThoughtSpot" modes:

```javascript
const { muze, getDataFromSearchQuery } = viz;
const { DataModel } = muze;
```

`viz.muze` is **synchronous**: build the canvas with `canvas = muze.canvas();` — a
plain assignment to the module-scope `let canvas = null;` from the *Responsive Sizing*
pattern (a `const` here shadows the outer binding and blanks the chart on resize).
There is no `muze()` factory call, no `await muze()`, and no `DataModel.onReady()` in
BYOC.

Do not wrap chart.js in an async function — the host already executes it inside one.
Static HTML belongs in chart.html (never built via `innerHTML` / `createElement` in
JS) and fixed styling in chart.css; the only DOM construction that belongs in JS is
truly data-driven markup and `document.createElement('script')` for CDN loading.

Call `viz.events.emitRenderCompletedEvent()` **live — never commented out — on both
the success and `catch` paths**; Liveboard PDF export blocks until every tile reports
in. The render wrapper is in references/byoc-data-modes.md. This applies to Chart.js,
gridjs, and raw-SVG/HTML charts too, even though they don't touch `muze`.

## Hard Rules — Quick List

A scannable never-do list. Every entry below has detailed explanation and a working alternative in *Hard Rules — Detail* immediately after this section.

**API hallucination — these methods/options do not exist:**
- **NEVER** invent Muze methods. Only use what's documented in the API Reference at the bottom. When in doubt, use the simplest correct pattern.
- **NEVER** call `DataModel.onReady()` — use `DataModel.loadDataSync()`.
- **NEVER** call `canvas.scrollConfig()` — use `.config({ scrollBar: {...} })`.
- **NEVER** call `canvas.onready()` — use `.once("afterRendered", cb)`.
- **NEVER** call `canvas.tooltip()` — use `.config({ interaction: { tooltip: {...} } })`.
- **NEVER** invent helpers like `loadScriptOnce`, `loadScript`, `waitForLib` — use the documented `document.createElement('script')` + `await new Promise` shape.

**Silent failures — code looks correct but breaks at render or in ThoughtSpot:**
- **NEVER** pass `muze.Operators.html` to `.title()` / `.subtitle()` — renders verbatim. Plain strings only.
- **NEVER** use `point` `size` > `0.05` — area-based scale, fills the row.
- **NEVER** treat `tick` `size` like a point size — it's a band-fraction; use `0.02` for hairlines.
- **NEVER** set `p.update.x = <data value>` in `encodingTransform` — pixels, not data. Convert via `layer.measurement().width`.
- **NEVER** guard the position assignment with `if (p.update && p.update.x != null) { p.update.x = ... }` — when `p.update.x` is null (common for text-only KPI layers), the guard skips and the text renders at (0,0) or off-canvas. Assign unconditionally: `p.update.x = 10; p.update.y = 22;` (matches Recipe 16.39).
- **NEVER** use `p.text.*` in `encodingTransform` — undefined, crashes or silently no-ops.
- **NEVER** add text inside a bar/point layer's `encodingTransform` — bar layers don't render text. Inject labels via SVG in `afterRendered` (a separate top-level `mark: 'text'` layer breaks ThoughtSpot interaction propagation — see below).
- **NEVER** use `share()` with mismatched scales — pins everything near 0. Use the dual-axis tuple pattern.
- **NEVER** construct a new `DataModel` inside `source` — crashes with `e.getDomain is not a function`.
- **NEVER** reposition `mark: 'line'` via `encodingTransform` — ignored. Use `mark: 'point'` for vertical reference markers.
- **NEVER** add `mark: 'text'` as a top-level layer alongside point/bar — breaks ThoughtSpot interaction propagation. Inject SVG in `afterRendered`.
- **NEVER** set `tooltip.mode: 'consolidated'` — breaks ThoughtSpot interaction propagation. Configure only `formatter`.
- **NEVER** declare `Year` (or any temporal field) as `type: 'measure'` on a line chart — collapses the chart. Use `type: 'dimension'`.
- **NEVER** use root `axes.x.tickFormat` for temporal-named fields in ThoughtSpot — silently ignored. Use per-field path `axes.x.fields[FIELD].tickFormat` with `d.rawValue` as ms.
- **NEVER** rely on TS table-mode column format (currency, percent, etc.) propagating to the chart — it doesn't. Emit explicit `tickFormat`.
- **NEVER** use `domain: [...]` to control axis range — silently ignored.
- **NEVER** include `domain` in `.color({ field, range, domain })` — silently kills `range` too, reverting to Muze's default blue/orange palette. Provide only `range`, in alphabetical order of category values (see *Color `range` is alphabetically assigned*).
- **NEVER** use non-ASCII `·` `—` in `.title()` / `.subtitle()` — encoding bugs in TS render `Â·` etc.
- **NEVER** include literal `</script>` in code comments — breaks the HTML parser.
- **NEVER** redeclare `canvas` with `const` inside `renderChart` — shadows the outer `let canvas = null;` from the Responsive Sizing pattern. `applySize()` then reads `null` on the next `ResizeObserver` tick and bails, leaving the chart blank in TS. Use plain assignment: `canvas = muze.canvas();`.

## Hard Rules — Detail

### `muze.Operators.html` in `.title()` or `.subtitle()`
**NEVER** pass an `html` template literal to `.title()` or `.subtitle()`. It does not render HTML — Muze calls `.toString()` on the tagged template and the raw HTML string appears verbatim as the chart title (e.g., `<span style="font-weight:600">My Title</span>` shows up as literal text on screen).
Use plain strings only: `.title('My Title')`.
The `html` operator is restricted to KPI card text layers applied via `encodingTransform`, not to `.title()`.

### Point/diamond `size` values above 0.05 — fills entire row height
**NEVER** use `size: { value: () => 0.5 }`, `0.8`, `0.4`, `0.2`, or any value above `0.05` for small decorative point markers (diamonds on a bar chart, compa-ratio dots, etc.). Muze's size encoding is area-based — `0.5` renders a diamond that is taller than the bar row, creating massive orange shapes that obscure the entire chart. `0.05` is the hard maximum for a decorative marker. The ONLY exception is a bubble chart where the user explicitly requests large bubbles.

```javascript
// WRONG — creates shapes that fill the entire chart:
size: { value: () => 0.5 }   // still wrong
size: { value: () => 0.8 }   // very wrong
size: { value: () => 0.4 }   // still wrong

// CORRECT for decorative markers:
size: { value: () => 0.05 }
```

### `mark: 'tick'` size is a band-fraction, not a point size — keep it tiny for hairlines
For `mark: 'tick'` used as a thin vertical reference marker (e.g., a target line inside a horizontal bar), `size` controls the **fraction of the row band** the tick occupies along its non-positional axis. `size: 0.6` renders a tick that fills 60% of the row — visually a wide colored block, not a line. For a hairline reference marker:

```javascript
{ mark: 'tick',
  encoding: { x: TARGET_FIELD, color: { value: () => '#dc2626' } },
  size: { value: () => 0.02 },     // ← thin hairline, NOT 0.6
  calculateDomain: false, interactive: false }
```

This is distinct from `mark: 'point'` size (the 0.05 area-based rule above). Tick `size` is a fraction in `[0,1]`; point `size` is an area scalar that explodes past `0.05`.

### `p.update.x` in `encodingTransform` is PIXELS, not data values — CRITICAL
`p.update.x` is a **pixel offset relative to the plot area**, not a data value. Setting it to a large data value like `120000` will place the element 120,000 pixels off-screen.

**WRONG — places element ~120,000px off-screen:**
```javascript
encodingTransform: (points) => {
  points.forEach(p => {
    if (p.update && p.update.x != null) p.update.x = MARKET_NORM;  // MARKET_NORM=120000 = pixels!
  });
  return points;
}
```

**CORRECT — convert data value to pixels using `layer.measurement()`:**
```javascript
encodingTransform: (points, layer) => {
  const { width: plotWidth } = layer.measurement();
  // Convert data value to pixel: pixel = (dataValue / domainMax) * plotWidth
  const refPixel = (MARKET_NORM / AXIS_MAX) * plotWidth;
  points.forEach(p => {
    if (p.update && p.update.x != null) p.update.x = refPixel;
  });
  return points;
}
```

Small adjustments (like `p.update.x += 6` for a 6-pixel nudge) are fine — they ARE adding pixels. Only constant large data values are problematic.

`x: { value: () => MARKET_NORM }` has the same bug — Muze passes the return value as pixels, not a data value to map through the scale.

### Defensive guards on `p.update.x` skip the assignment — KPI cards render blank
For KPI/text layers, **always assign `p.update.x` and `p.update.y` unconditionally**. A guard like `if (p.update && p.update.x != null)` is *exactly* the wrong pattern: text layers without an `x`/`y` encoding have `p.update.x = null` at transform time, the `!= null` check fails, the assignment is skipped, and the text renders at (0,0) or off-canvas — silent failure with a blank chart.

```javascript
// WRONG — guard skips assignment when p.update.x is null, text never positions:
encodingTransform: (points) => {
  points.forEach(p => {
    if (p.update && p.update.x != null) {   // ← skips for text-only KPI layers
      p.update.x = 14;
      p.update.y = 22;
    }
  });
  return points;
}

// CORRECT — unconditional assignment, matches Recipe 16.39:
encodingTransform: (points, layer) => {
  points.forEach(p => {
    p.update.x = 14;
    p.update.y = 22;
    p.style = Object.assign(p.style || {}, { 'text-anchor': 'start', 'font-size': '11px' });
  });
  return points;
}
```

`p.update` itself is always defined for points that exist; it's `p.update.x` (the computed pixel) that may be null when there's no positional encoding. Just write to it.

### All text labels must be fully visible — no overlap, no clipping
When adding data labels (e.g., salary values at bar ends):

1. **You cannot reserve axis headroom via `domain`** — axis `domain` config is silently ignored (hard rule). If labels at bar ends risk clipping, use shorter formats, `text-anchor: 'end'` inside-bar labels, or post-render SVG labels instead.

2. **Avoid overlapping labels**: For dense data, use shorter formats (e.g., `$169K` not `$169,000`). Stagger or omit labels if they would overlap: check if points are closer than label width before rendering.

3. **Use `text-anchor: 'end'` for inside-bar labels**: If labels must appear inside bars (right-aligned at bar end), use `'text-anchor': 'end'` and `p.update.x -= 4` instead of `+= 4`.

4. **Use `calculateDomain: false`** on all text layers so label positions don't expand the axis range.

### `p.text.*` in `encodingTransform` — always crashes
There is NO `p.text` property on point objects. Every form of `p.text.*` crashes:
```javascript
// ALL of these crash — p.text is always undefined:
p.text.update.x += 4;         // TypeError: Cannot read properties of undefined
p.text.update.x = p.update.x; // same
if (p.text) { p.text.update.x... } // p.text is undefined, block never runs — labels silently never move
```

The **only** correct property path is `p.update.x`. Use this exact pattern and no other:
```javascript
encodingTransform: (points) => {
  points.forEach(p => {
    if (p.update && p.update.x != null) {  // guard OK — relative nudge; skipping cross-panel null points is fine
      p.update.x += 6;
    }
    p.style = Object.assign(p.style || {}, {
      'font-size': '11px',
      'font-weight': '600',
      'text-anchor': 'start'
    });
  });
  return points;
},
calculateDomain: false  // always add this on text layers
```

### Text labels in a bar/point layer's `encodingTransform` — labels never appear
Setting `p.text = {}` or `p.text.text = '...'` inside a bar layer's `encodingTransform` does nothing — bar layers do not render text. And a separate top-level `mark: 'text'` layer breaks ThoughtSpot interaction propagation (see *`mark: 'text'` as a separate layer* below), so in shipped BYOC charts inject labels via SVG in the `afterRendered` callback instead. The `encodingTransform` on a bar layer is only for repositioning the bar geometry (`p.update.*`) or adding CSS styles.

### `share()` when measures have different numeric scales — CRITICAL
`muze.Operators.share('FieldA', 'FieldB')` creates a **single shared axis scale** for both fields. CompaRatio values like 0.96 plotted on a salary axis of 0–180,000 appear at **x = 0.96** — essentially invisible at the far left. This cannot be fixed with `domain` config.

**Use `share()` only when both measures have the same units and scale** (e.g., min/max temperature, a range plot). For measures with different scales (salary + compa-ratio), use the tuple column pattern `[[SALARY], [COMPA_NORM]]` from the *Dual-Axis Overlay* section — this gives two OVERLAID panels with separate axis scales.

### `source` with a new DataModel — crashes with `e.getDomain is not a function`
**NEVER** construct a new DataModel inside a `source` function. This crashes Muze:

```javascript
// CRASH — do not do this:
{
  mark: 'tick',
  source: (dt) => new DataModel(DataModel.loadDataSync(refData, schema)),  // ← CRASH
  ...
}
// ALSO CRASH:
{
  mark: 'tick',
  source: () => dmRef,   // no-arg function returning a DataModel — CRASH
  ...
}
```

For a reference line at a fixed x position, use `x: { value: () => CONSTANT }` with `calculateDomain: false` and NO `source` property:

```javascript
// CORRECT — fixed x value, no source:
{
  mark: 'tick',
  encoding: {
    x: { value: () => MARKET_NORM },
    color: { value: () => '#888888' },
    size: { value: () => 0.002 }
  },
  calculateDomain: false,
  interactive: false
}
```

### `mark: 'line'` cannot be repositioned via `encodingTransform` — use `mark: 'point'` instead
The `line` mark's `encodingTransform` does not reliably reposition the line via `p.update.x`. Setting `p.update.x` on a `line` mark is ignored or has unpredictable behavior — the rendered line stays at the data-averaged position regardless of what you set.

**For a vertical reference marker**, use `mark: 'point'` with `encodingTransform` (which DOES support `p.update.x`). This places one dot per data row at the reference x position:
```javascript
{
  mark: 'point',
  encoding: { x: COMPA_NORM_FIELD, color: { value: () => '#C0622F' }, size: { value: () => 0.05 }, shape: { value: () => 'circle' } },
  encodingTransform: (points, layer) => {
    const refPixel = (MARKET_NORM / AXIS_MAX) * layer.measurement().width;
    points.forEach(p => { if (p.update && p.update.x != null) p.update.x = refPixel; });
    return points;
  },
  calculateDomain: false, interactive: false
}
```
This creates N dots (one per row) at the same x — visually a dotted vertical marker. For a **continuous dashed line** spanning the full chart height, use post-render SVG injection (see *Continuous Dashed Reference Line* below).

### Continuous Dashed Reference Line — post-render SVG injection
To render a true dashed vertical line (not just dots), inject an SVG `<line>` after Muze finishes rendering. The key insight: Muze renders the y-axis as a tall narrow `<path>` element — use its bounding box for `plotLeft` and y-extent, then derive `plotWidth` from the SVG width.

**Key facts about Muze's SVG structure:**
- Horizontal bars are rendered as SVG `<line>` elements whose `x2` attribute stays at 0 (CSS transforms make them visible). Do NOT try to read bar positions from DOM attributes or `getBoundingClientRect()` — they always return 0 during and after animation.
- The y-axis is a tall narrow `<path>` (height >100px, width <5px) that IS readable via `getBoundingClientRect()` immediately after render.
- The plot width can be estimated as: `svgBB.width − plotLeft − rightMargin`, where rightMargin ≈ 60px accounts for bar-end labels and Muze padding.

**CRITICAL: Muze uses nested SVG elements** — `document.querySelector('#chart svg')` returns the y-axis SVG (narrow, ~100px wide), not the plot area. Always select the **widest** SVG:

```javascript
// Fire after Muze animations (~1000ms). Retries until ready.
function injectDashedRefLine() {
  const allSvgs = Array.from(document.querySelectorAll('#chart svg'));
  if (!allSvgs.length) { setTimeout(injectDashedRefLine, 100); return; }

  // Pick the widest SVG — that's the plot area (not the y-axis sidebar)
  const rootSvg = allSvgs.reduce((w, s) =>
    s.getBoundingClientRect().width > w.getBoundingClientRect().width ? s : w, allSvgs[0]);
  const rootBB = rootSvg.getBoundingClientRect();
  if (rootBB.width < 200) { setTimeout(injectDashedRefLine, 100); return; }

  // Y-axis line: tall (>100px), narrow (<5px) — exists across ALL nested SVGs
  const yAxis = Array.from(document.querySelectorAll('#chart path')).find(el => {
    const bb = el.getBoundingClientRect();
    return bb.height > 100 && bb.width < 5;
  });
  if (!yAxis) { setTimeout(injectDashedRefLine, 100); return; }

  const yBB        = yAxis.getBoundingClientRect();
  const plotLeft   = (yBB.left + yBB.right) / 2 - rootBB.left; // may be negative (y-axis is left of plot SVG)
  const plotTop    = yBB.top    - rootBB.top;
  const plotBottom = yBB.bottom - rootBB.top;
  const plotWidth  = rootBB.width - plotLeft - 60;  // 60px right margin for bar-end labels

  // refX in plot-SVG coordinates
  const refX = plotLeft + (MARKET_NORM / AXIS_MAX) * plotWidth;

  const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  line.setAttribute('x1', refX);  line.setAttribute('x2', refX);
  line.setAttribute('y1', plotTop); line.setAttribute('y2', plotBottom);
  line.setAttribute('stroke', '#C0622F');
  line.setAttribute('stroke-dasharray', '6 4');
  line.setAttribute('stroke-width', '1.5');
  rootSvg.appendChild(line);  // append to the plot SVG, not querySelector result
}
setTimeout(injectDashedRefLine, 1100);
```

### `domain` axis config is silently ignored
`domain: [0.90, 1.06]` in axis config does nothing — Muze auto-fits from data extents and ignores the `domain` property. **Never use `domain` to try to control axis range.**

### Color `range` is alphabetically assigned — `domain` silently kills it
Two non-obvious facts about `.color({ field, range })`:

**1. Alphabetical assignment.** Muze sorts the categorical values of `field` alphabetically (case-sensitive, JS string compare) and assigns `range[0]` to the first sorted value, `range[1]` to the second, etc. The order in your `data` array is irrelevant. Example: cities `['Dallas', 'Austin', 'Boston']` sort as `Austin → Boston → Dallas`, so to make Dallas blue (`#2563EB`), put it at `range[2]`. To get the order, run `[...new Set(data.map(d => d[FIELD]))].sort()` in your head — uppercase comes before lowercase in JS (`'E' < 'e'`), so `'Engagement'` sorts BEFORE `'eNPS'`.

**2. `domain` poisons `range`.** Including `domain: [...]` alongside `range` causes Muze to ignore BOTH and fall back to its default palette (blue/orange/etc.). The `domain` property is unsupported in `.color()`, but its mere presence breaks the range mapping silently. The chart still renders; the colors are just wrong.

```javascript
// WRONG — domain is ignored AND it kills range; you get the default palette:
.color({
  field: METRIC_FIELD,
  domain: ['Engagement', 'eNPS'],            // ← unsupported; remove
  range:  ['#1B3A2F', '#A89A5A'],
})

// CORRECT — sort range to match alphabetical order of values:
// 'Engagement' < 'eNPS' (uppercase E < lowercase e)
//   → range[0] for Engagement, range[1] for eNPS
.color({
  field: METRIC_FIELD,
  range: ['#1B3A2F', '#A89A5A'],
})
```

When the alphabetical order is non-obvious or fragile (renaming a category would silently shuffle colors), use the schema-indexed `encodingTransform` pattern (Production Pattern #1) to set `p.style.fill` per row from a value→color map. That bypasses the alphabetical mapping entirely.

### `mark: 'text'` as a separate layer — breaks ThoughtSpot interaction propagation
Adding a second layer with `mark: 'text'` for point/bubble labels (alongside the main `mark: 'point'` or `mark: 'bar'` layer) triggers `this._onPropagationDone is not a function` errors in ThoughtSpot, even when the text layer has `interactive: false`. The chart still renders, but the console floods with errors and hover behavior is broken.

**DO NOT** add a `mark: 'text'` layer for chart-point labels. Instead, inject labels via SVG in the `afterRendered` callback — this is what working ThoughtSpot charts do:

```javascript
// In the bubble/point layer, capture pixel coords during encodingTransform:
const pointPixels = {};
{
  mark: 'point',
  className: 'city-layer',  // give the layer a className to find it later
  encoding: { x: { field: X_FIELD }, y: { field: Y_FIELD }, /* ... */ },
  encodingTransform: (points, layer) => {
    const result = layer.data().getData();
    const cols = result.schema.map((s) => s.name);
    const labelIdx = cols.indexOf(LABEL_FIELD);
    points.forEach((p, i) => {
      const row = result.data[i];
      if (row && labelIdx >= 0) {
        pointPixels[row[labelIdx]] = { px: p.update.x, py: p.update.y };
      }
    });
    return points;
  },
}

// Then in afterRendered, draw labels as SVG text at the captured coords:
canvas.once('afterRendered', () => {
  const svg = document.querySelector('#chart svg');
  const NS = 'http://www.w3.org/2000/svg';
  Object.entries(pointPixels).forEach(([label, { px, py }]) => {
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', px + 14); t.setAttribute('y', py - 4);
    t.setAttribute('fill', '#333');
    t.setAttribute('font-size', '11');
    t.setAttribute('text-anchor', 'start');
    t.setAttribute('pointer-events', 'none');
    t.textContent = label;
    svg.appendChild(t);
  });
});
```

This is the only TS-safe way to label points/bubbles.

### `tooltip.mode: 'consolidated'` — breaks ThoughtSpot interaction propagation
Setting `interaction.tooltip.mode: 'consolidated'` triggers `_onPropagationDone is not a function` errors flooding the console (often hundreds of times) and breaks hover behavior in ThoughtSpot. The default tooltip mode works correctly in both standalone Muze and ThoughtSpot. **Never set `mode` on the tooltip config — only configure `formatter`.** Pattern:
```javascript
interaction: {
  tooltip: {
    // No `mode` property — leave it default
    formatter: (dataStore) => {
      const result = dataStore.getData();  // direct call, no defensive null-check
      const cols = result.schema.map((s) => s.name);
      const row  = result.data[0];
      if (!row) return [];
      // ... build tooltip rows
    }
  }
}
```

### Year-as-measure on a line chart breaks the chart entirely
Tempting fix: declare `Year` as `type: 'measure'` to get a continuous numeric x-axis with smooth interpolation. **Don't.** When both x and y are measures on a line layer, Muze treats the data as a scatter relationship and aggregates — the rendered chart shows scatter points, an x-axis labeled `0–2200` (or the row count), and the y-scale collapses to the wrong range.

`Year` must always be `type: 'dimension'`. To get a smooth-looking line across years, generate **dense yearly data** (one row per year, ~10–20 rows). The categorical x-axis renders cleanly when the values are sequential integer years.

```javascript
const schema = [
  { name: 'Year', type: 'dimension' },          // ← dimension, NOT measure
  { name: 'CO2',  type: 'measure', defAggFn: 'sum' },
];
const data = []; // 2010..2050 inclusive
for (let y = 2010; y <= 2050; y++) data.push({ Year: String(y), CO2: ... });
```

### Date-like dimensions render as month/year ticks in ThoughtSpot — use `axes.x.fields[FIELD].tickFormat`
When the chart's x-axis dimension name suggests a temporal field — case-insensitive match on `quarter`, `month`, `year`, `date`, `week`, or `day` (e.g. `Quarter (Order Date)`, `Order Month`, `Ship Date`) — TS will type that field as `subtype: "temporal"` and feed Muze millisecond-timestamp `rawValue`s. Muze then auto-generates calendar-boundary ticks (e.g. for quarterly data: `October`, `2024`, `April`, `July` …). The user expects to see what TS table mode shows (e.g. `Q4 2023`, `Q1 2024`).

In the skill's preview, the same field is a categorical string (`"Q3 2023"`), so the chart looks fine here. The bug only appears once the script is pasted into a real TS tile.

**CRITICAL: Muze ignores the root `axes.x.tickFormat` for temporal axes.** It only respects the per-field path `axes.x.fields[FIELD].tickFormat`. Putting the formatter at root level silently does nothing for temporal data — the chart still renders but the formatter is never called.

**The `d` parameter is an object** of shape `{ formattedValue: "October", rawValue: 1696136400000 }`. The `formattedValue` is Muze's auto-generated label (the wrong one); use `rawValue` (the millisecond timestamp) and derive the label yourself. **Use `getUTCMonth()` / `getUTCFullYear()`** so the label doesn't shift across viewer timezones.

```javascript
.config({
  axes: {
    x: {
      fields: {
        [QUARTER_FIELD]: {                              // <-- per-field, NOT root axes.x
          tickFormat: function (d) {
            var ms = d && typeof d === 'object' ? d.rawValue : d;
            var date = new Date(ms);
            if (isNaN(date.getTime())) return String(d); // preview (string fallthrough)
            var q = Math.floor(date.getUTCMonth() / 3) + 1;
            return 'Q' + q + ' ' + date.getUTCFullYear();
            // Month dimension:   date.toLocaleString('en', { month: 'short', timeZone: 'UTC' }) + ' ' + date.getUTCFullYear()
            // Year dimension:    String(date.getUTCFullYear())
            // Date dimension:    date.toISOString().slice(0, 10)
          }
        }
      }
    }
  }
})
```

Pick the derivation branch that matches the dimension's granularity (quarter / month / year / day). Do NOT add this `tickFormat` for non-temporal dimensions (Category, Region, Department, etc.) — it's noise there and violates the *Defaults First* rule.

### Measure axis formatting in ThoughtSpot is NOT inherited from the column's table-mode format
TS's table can render a measure as `$1.2M`, `518.65%`, `0.45`, etc. depending on the column's chosen display format. **None of that propagates into the data the custom chart receives.** The Field's `formattedData()` method returns raw numeric values (verified: a percent-formatted column returns `5.1865`, not `"518.65%"`); the schema carries only `name/type/subtype/defAggFn`; `data.getFieldsConfig` doesn't exist; `viz.formatters` exposes `NumberFormatter`/`DateFormatter` *classes* but no "format like the table would" runtime helper. Display formatting is, by design, the chart author's responsibility.

So when the target image clearly shows a measure rendered as percent / currency / thousands / etc., the chart needs an explicit `tickFormat`. Promote the format choice into the Customize block (see *Tweakable Constants Block*) so a non-technical user can switch it without touching axis code:

```javascript
const FORMAT = {
  yAxis: 'currency',  // 'currency' | 'percent' | 'thousands' | 'raw'
  decimals: 0
};

function formatMeasure(d) {
  const v = d && typeof d === 'object' ? d.rawValue : d;
  if (v == null || isNaN(v)) return '';
  switch (FORMAT.yAxis) {
    case 'percent':
      return (v * 100).toFixed(FORMAT.decimals) + '%';
    case 'currency':
      if (v >= 1e6) return '$' + (v / 1e6).toFixed(FORMAT.decimals) + 'M';
      if (v >= 1e3) return '$' + (v / 1e3).toFixed(FORMAT.decimals) + 'K';
      return '$' + v.toFixed(FORMAT.decimals);
    case 'thousands':
      if (v >= 1e6) return (v / 1e6).toFixed(FORMAT.decimals) + 'M';
      if (v >= 1e3) return (v / 1e3).toFixed(FORMAT.decimals) + 'K';
      return v.toFixed(FORMAT.decimals);
    default:
      return String(v);
  }
}

// Then in axes config:
.config({
  axes: {
    y: {
      tickFormat: formatMeasure
    }
  }
})
```

Pick the default `FORMAT.yAxis` value based on the target image. The user can flip it later by changing one line in the Customize block. Do NOT add this scaffolding for charts where the measure is plainly raw numeric (e.g. counts, scores) — *Defaults First* still applies.

### Special Unicode characters in `.title()` / `.subtitle()` — CRITICAL
The `·` character (U+00B7, middle dot) may render as `Â·` in some environments (particularly ThoughtSpot) due to encoding issues.
**Rule: use only ASCII characters in `.title()` and `.subtitle()` strings to be safe.**
- Middle dot `·` → use ` | ` (pipe with spaces)
- Em dash `—` → use ` - `
- Any accented or symbol character → replace with ASCII equivalent

## Defaults First

**Match complexity to what the target image actually demands.** Muze produces a complete, well-styled chart from just `rows`, `columns`, `data`, `title`, and `mount` — it auto-infers axis names from field names, shows horizontal gridlines, picks a default blue, hides the legend when there's no color/size encoding, and renders raw numeric ticks. Start from that minimal shape and add config **only** for things that visibly diverge from those defaults in the target image:

- Add `tickFormat` only if the target shows formatted ticks (e.g. `$11M` vs `11000000`).
- Add a `color.value` override only if the target color clearly differs from Muze's default blue.
- Add `axes.x/y.name` + `showAxisName` only when you need a label different from the field name.
- Add `gridLines`, `legend.show: false`, or `axes.*.show: false` only when those defaults are wrong for the target.
- **Do NOT call `.title()` or `.subtitle()` unless the target image visibly contains a chart title/subtitle inside the chart frame, or the user explicitly asks for one.** ThoughtSpot Liveboard tiles render their own title and subtitle around the chart — emitting a chart-internal title creates a duplicate header. When in doubt, omit.

For a basic chart matching Muze's default appearance, the minimal correct shape is:
```javascript
canvas.data(dm).rows([Y_FIELD]).columns([X_FIELD]).width(width).height(height).mount('#chart');
```
Config that produces the same output as omitting it is noise — drop it. Less code = easier for the user to read and adapt.

## Code Generation Rules

1. Always produce COMPLETE, self-contained JavaScript code.
2. Use Muze v4.7.10 (already loaded in the environment).
3. Generate realistic sample data that matches the chart being created.
4. Include the DataModel schema array, data array, and full canvas setup.
5. Follow this initialization pattern:
   - `const { DataModel } = muze;`
   - `const formattedData = DataModel.loadDataSync(data, schema);`
   - `const dm = new DataModel(formattedData);`
   - `canvas = muze.canvas();` — no `const`; assigns to the module-scope `let canvas = null;` from the Responsive Sizing pattern. **NEVER** write `const canvas = muze.canvas();` — it shadows the outer `let` and breaks `applySize()` after the first ResizeObserver tick (chart goes blank in TS).
   - `canvas.data(dm).rows([...]).columns([...]).layers([...]).mount('#chart');`
6. Limit sample data to a MAXIMUM of 30 rows. Even if the uploaded image shows months or years of data, generate only enough rows to demonstrate the chart as a working example. Quality of the chart pattern matters more than data volume.
7. NEVER change the data structure (add/remove/rename columns or change types) without explicitly asking the user first. If you believe a data structure change is needed, explain why and wait for confirmation before generating updated data.
8. Always mount to `'#chart'`.

### Schema and value notes
- The `stack100percent` transform is available in Muze v4.7.10. For 100% stacked charts, you can use the `stack100percent` transform or pre-compute percentages in the data.
- Value encodings must use functions: `{ value: () => 'red' }`, not `{ value: 'red' }`.
- For range charts where measures share the SAME numeric scale (e.g., min/max temp), use `muze.Operators.share('field1', 'field2')`. For measures with different scales (e.g., salary + compa-ratio), use the *Dual-Axis Overlay* pattern — `share()` on different-scale measures will place points near x=0.
- Dimensions go in schema as `{ name: 'X', type: 'dimension' }`.
- Measures go in schema as `{ name: 'Y', type: 'measure', defAggFn: 'sum' }`.
- **Point Size Defaults:** Muze's `size` encoding for point marks uses an area-based scale, so values map to much larger rendered dots than expected. Always use `0.05` as the default starting size for small decorative point markers on line charts (e.g., `size: { value: () => 0.05 }`). Never default to values like `50`, `10`, or even `1` — these will render as enormous dots. Only use larger values if the user explicitly requests bigger markers (e.g., a bubble chart or large scatter plot dots).

### Field-Name Constants

After the schema and sample data definitions, define all column names as UPPER_SNAKE_CASE constants. Use these constants everywhere in the Muze code instead of string literals — in `.rows()`, `.columns()`, `encoding`, `color`, `size`, `formatter`, `select()`, etc. The schema and data keep their natural readable names; the constants map those names to variables used in the rest of the code. This allows users to update column names in one place when adapting for their own data. Example:
```
const schema = [
  { name: 'Category', type: 'dimension' },
  { name: 'Revenue', type: 'measure', defAggFn: 'sum' },
];
const data = [
  { Category: 'Electronics', Revenue: 42000 }
];

// ── Column Names (update these to match your data) ──
const CATEGORY_FIELD = 'Category';
const REVENUE_FIELD = 'Revenue';

canvas
  .rows([REVENUE_FIELD])
  .columns([CATEGORY_FIELD])
  .layers([{ mark: 'bar', encoding: { y: REVENUE_FIELD } }])
```

### Tweakable Constants Block

**Only when the chart actually has tunable values.** Per *Defaults First*, a default-styled chart shouldn't need this block at all. When the chart **does** override defaults (custom colors, custom labels different from field names, custom precision, thresholds), group those overrides into a clearly-marked configuration block above `renderChart` so a non-technical user can adjust them without reading the rest of the file:

```
// ─── Customize ──────────────────────────────────────
const COLORS = {
  primary: '#1B3A2F',
  accent:  '#E8744F',
  neutral: '#666',
  // one entry per series / category referenced below
};
const LABELS = {
  xAxis: 'Category',
  yAxis: 'Revenue',
  // any rendered text users might want to change
};
const PRECISION = {
  axis:    0,   // decimals on axis ticks
  tooltip: 2,   // decimals in tooltip values
  kpi:     1,   // decimals on big-number tiles
};
const THRESHOLDS = { /* numeric cutoffs the chart depends on, e.g. target: 100 */ };
// ────────────────────────────────────────────────────
```

Rules:
- **Skip the block entirely if there's nothing to customize.** Don't emit `COLORS = {}`, `LABELS = { title: '...' }` with one entry, or `PRECISION = {}` just to satisfy a structural rule. An empty/near-empty block is noise.
- Every **non-default** color, label, axis title, precision value, threshold, or category-to-color mapping must reference these constants. **No inline magic strings or numbers** for non-default values further down in the file. (Default values aren't in the file at all — they live in Muze.)
- Group by purpose (`COLORS`, `LABELS`, `PRECISION`, `THRESHOLDS`); do not mix.
- A category-to-color mapping with 2+ entries always belongs in `COLORS` even if it's the only customization, since users frequently want to tweak palettes.
- Field-name constants (the `UPPER_SNAKE_CASE` ones tied to schema field names) stay separate — they map to data, not visuals, and aren't user-editable in the same way.
- Keep field-name constants near the schema; keep this Customize block above `renderChart`.

## Responsive Sizing & Dynamic Data

**REQUIRED, combined pattern**: Read dimensions directly from the `#chart` container, rebuild the canvas only when *data* changes, and re-fit cheaply when *size* changes. This pattern works natively in both the skill's preview and ThoughtSpot — no host-provided helper required.

```javascript
const SAMPLE_DATA = [/* baked-in rows — mirror <RUNS>/<SLUG>/sample-data.json */];
let currentData = SAMPLE_DATA;
let canvas = null;                    // module-scope; applySize() reads this. NEVER shadow with `const canvas` inside renderChart.
const el = document.getElementById('chart');

function renderChart(data) {
  if (data) currentData = data;
  const dm = new DataModel(DataModel.loadDataSync(currentData, schema));
  canvas = muze.canvas()
    .data(dm)
    .rows([Y_FIELD])
    .columns([X_FIELD])
    .layers([/* ... */]);
  applySize();
}

function applySize() {
  if (!canvas) return;
  const w = el.clientWidth, h = el.clientHeight;
  if (w <= 0 || h <= 0) return;        // tile not laid out yet
  canvas.width(w).height(h).mount(el);
}

renderChart();
window.updateChart = renderChart;       // host can call window.updateChart(newRows) later

let _rafId = null;
new ResizeObserver(() => {
  if (_rafId) cancelAnimationFrame(_rafId);
  _rafId = requestAnimationFrame(() => { applySize(); _rafId = null; });
}).observe(el);
```

Why this shape:
- **`#chart` is sized by the host** — the preview sets it via CSS, ThoughtSpot's tile sizes it. `clientWidth/clientHeight` always reflect the available area.
- **Retained-canvas re-mount** (`canvas.width(w).height(h).mount(el)`) re-layouts in place: no flicker, no entry-animation re-run on resize. Verified against Muze v4.7.10.
- **Rebuild only on data change** — `renderChart(data)` rebuilds DataModel + canvas; `applySize()` does not. Keeps update paths cheap.
- **`ResizeObserver` on `#chart`** — fires for both browser resize and tile-container resize (TS sidebars, layout changes).

**Do NOT** add `window.addEventListener('resize', ...)` — the `ResizeObserver` already covers it and observes the actual chart container.

For Chart.js: `responsive: true, maintainAspectRatio: false` plus a flex parent (`flex: 1 1 0; min-height: 0;`). Wrap the chart instance in `renderChart(data)` and call `chart?.destroy()` before re-creating on data change.

For raw SVG (KPI tiles): use a `viewBox` and the same `ResizeObserver` + `requestAnimationFrame` shape on `#chart`.

Only use hardcoded pixel dimensions if the user explicitly requests a specific size.

## Library Selection — Muze, Chart.js, or Raw SVG

Default to Muze, but pick the right tool for the chart type. All four options run inside the ThoughtSpot environment.

- **Muze** (default) — bar / column / line / area / scatter / bubble / box / waterfall / pie / heatmap / dual-axis / KPI tiles where the value is data-bound. Anywhere we want axes, legends, color encodings, tooltips, or interactivity tied to a `DataModel`. Also covers chart types reachable via the 7 native marks (bar, line, point, area, arc, text, tick).
- **Chart.js** — line charts that need smooth interpolation Muze doesn't natively express (e.g., damped Hermite between sparse anchor years); bar+line combo charts with conditional bar coloring (above/below plan); horizontal stacked-bar progress meters; line charts with colored background band zones; chart types Muze can't reach with native marks (radar, polar area, doughnut, sankey, treemap).
- **Raw SVG / Canvas (no chart lib)** — single-stat KPI tiles (mostly typography + small graphic); healthcare/metric tiles with fixed layout sections; semi-circle gauge charts; slope/bump charts (rank changes over time — use HTML5 Canvas with explicit arc drawing). Use `ResizeObserver` + `requestAnimationFrame` + `viewBox` for responsiveness.
- **Raw HTML/CSS** — quote/text annotation cards, intro/context slides, attribution blocks. No chart library or canvas needed — just HTML structure + CSS.

**Rule of thumb:** if the user's image is recognizably an axis chart with x/y scales, legend, and multiple series, use Muze. If it's a KPI tile that's mostly typography with a small graphic, use raw SVG. If it's a quote card, intro card, or text-only slide, use raw HTML/CSS. If it's a line chart with bespoke smoothing, conditional coloring, background bands, or one of the unreachable Muze types (sankey, gauge), use Chart.js or Canvas. The user can override at any time ("use Muze", "use Chart.js").

**When the chart type isn't documented in this prompt:** Don't silently improvise. If the image doesn't match a documented recipe (no specific guidance for this chart type, no close analogue you can adapt from the patterns above), say so before generating code. State briefly what you see, that you don't have a documented recipe for it, and offer 2–3 concrete paths — for example: "(a) compose it in Muze from native marks (`tick`, `bar`, `point`, etc.) — first pass, we iterate; (b) use Chart.js if there's a known plugin/pattern; (c) point me at a reference chart or docs link." Wait for the user's choice before generating any code blocks. This is strictly better than producing a confident-looking result that misses the target — a wrong-but-plausible chart is harder to recover from than an honest "I'm not sure, here are the options."

**CRITICAL rules when using Chart.js or raw SVG:**
- **MUST** produce all three files: chart.html, chart.css, chart.js
- **MUST** use the exact script-loading pattern below (`document.createElement` + `await new Promise`)
- **NEVER** invent helper functions like `loadScriptOnce`, `loadScript`, `waitForLib` — they do not exist
- **NEVER** include literal `</script>` in code comments — it breaks the HTML parser
- Still use schema + DataModel.loadDataSync for data loading (even when Chart.js or SVG does the rendering — keeps the data contract consistent)
- Still use UPPER_SNAKE_CASE field constants
- Mount all visuals into the `#chart` container
- Always call `viz.events.emitRenderCompletedEvent()` live, on both the success and `catch` paths

### Chart.js Pattern (complete example)

**chart.html:**
```
<div id="chart">
  <canvas id="myChart"></canvas>
</div>
```

**chart.css:**
```
#chart { width: 100%; height: calc(100vh - 32px); }
#myChart { width: 100%; height: 100%; }
```

**chart.js:**
```
const { DataModel } = muze;

const schema = [...];
const data = [...];

// ── Column Names (update these to match your data) ──
const CATEGORY_FIELD = 'Category';
const VALUE_FIELD = 'Value';

const formattedData = DataModel.loadDataSync(data, schema);
const dm = new DataModel(formattedData);

// ── Extract data for Chart.js ──
const result = dm.getData();
const columns = result.schema.map(s => s.name);
const chartData = result.data.map(row => {
  const obj = {};
  columns.forEach((col, i) => { obj[col] = row[i]; });
  return obj;
});

// ── Dynamically load Chart.js ──
// Dynamic loading is the shipping shape — chart.html must contain no <script> tags.
const cjsScript = document.createElement('script');
cjsScript.src = 'https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js';
await new Promise((resolve, reject) => {
  cjsScript.onload = resolve;
  cjsScript.onerror = reject;
  document.head.appendChild(cjsScript);
});

// ── Render with Chart.js ──
const ctx = document.getElementById('myChart').getContext('2d');

new Chart(ctx, {
  type: 'radar', // or 'polarArea', 'doughnut', 'bubble', 'sankey', etc.
  data: {
    labels: chartData.map(d => d[CATEGORY_FIELD]),
    datasets: [{
      label: VALUE_FIELD,
      data: chartData.map(d => d[VALUE_FIELD]),
    }]
  },
  options: { responsive: true, maintainAspectRatio: true }
});

viz.events.emitRenderCompletedEvent();   // live — and call it in your catch path too
```

For Chart.js plugins (e.g., sankey, treemap), load them the same way after loading Chart.js — they register on the global `Chart` object automatically.

## Patterns & Recipes

Reference material — apply when the chart calls for the technique, not unconditionally.

### encodingTransform — When and How to Use It
`encodingTransform` is a layer-level callback that lets you modify computed point positions, styles, and text **after** Muze calculates them but **before** rendering. It works on ANY layer type (bar, line, point, text, tick, area, arc) — not just KPI cards.

**Signature:** `encodingTransform: (points, layer, deps) => points`
- `points` — array of point objects with `update` (x, y, width, height), `style`, `text`, `rowId`, `data`
- `layer` — the layer instance. Call `layer.measurement()` to get `{ width, height }` of the plotting area for responsive positioning
- `deps` — `{ smartLabel }` for measuring text dimensions via `deps.smartLabel.getOriSize(text)`

**Use cases across chart types:**
- **Text layers**: Precise label positioning (KPI cards, annotations, custom data labels)
- **Bar/tick layers**: Nudge bars or ticks by an offset, add custom spacing
- **Point layers**: Jitter overlapping points in scatter plots, adjust bubble positions
- **Any layer**: Conditional styling based on data values, responsive positioning using `layer.measurement()`

**Always prefer `layer.measurement()`** for positioning over hardcoded pixel values — it adapts to different canvas sizes.

**Text label positioning** — the positioning mechanics below (`p.update.x`, never `p.text`) are the only correct shape. **ThoughtSpot note:** a top-level `mark: 'text'` layer alongside bar/point breaks TS interaction propagation (hard rule) — in shipped BYOC charts, apply the same offsets to SVG labels injected in `afterRendered` instead (see *`mark: 'text'` as a separate layer*):
```javascript
{
  mark: 'text',
  encoding: {
    x: MEASURE_FIELD,
    text: {
      field: MEASURE_FIELD,
      formatter: (d) => {
        const v = typeof d === 'object' ? d.rawValue : d;
        return '$' + Math.round(v / 1000) + 'K';
      }
    },
    color: { value: () => '#333333' }
  },
  encodingTransform: (points) => {
    points.forEach(p => {
      if (p.update && p.update.x != null) {
        p.update.x += 6;
      }
      p.style = Object.assign(p.style || {}, {
        'font-size': '11px',
        'font-weight': '600',
        'text-anchor': 'start'
      });
    });
    return points;
  },
  calculateDomain: false
}
```
The null guard `if (p.update && p.update.x != null)` is acceptable here **only** because this is a relative nudge (`+=`) — skipping a cross-panel null point is fine. For absolute positioning of text/KPI layers, assign unconditionally (see *Defensive guards on `p.update.x`*). There is **no** `p.text` property. Do not use `p.text.*` in any form.

### Dual-Axis Overlay — Bar + Point with Different Scales (REQUIRED PATTERN)

**CRITICAL — How Muze handles multiple measures in `.columns()`:**

- `columns([share(A, B)])` — ONE shared axis, one axis label. Both fields use the same numeric scale. Use only when A and B have the same units (e.g., min/max temp).
- `columns([[A], [B]])` — **DUAL x-axes in the SAME panel** (overlaid, NOT side-by-side). First field gets bottom axis, second field gets top axis. Each layer maps to its panel via its `encoding.x` field. **This is the correct pattern for bar + diamond overlay with different scales.**

#### When target shows bars AND diamonds in the same horizontal space with two axis scales (one top, one bottom):

Use the **tuple columns** approach with **data normalization**. The normalization ensures the diamonds are spread across the chart width, while the top axis's `tickFormat` reverse-normalizes to show the original ratio values.

**Full working recipe — copy and adapt field names:**
```javascript
// ── Normalization parameters — match to your data range ──
const RATIO_MIN  = 0.88;   // slightly below actual minimum compa-ratio
const RATIO_MAX  = 1.08;   // slightly above actual maximum compa-ratio
const SALARY_MAX = 180000; // approximately the max salary value in your dataset

// ── Data: add normalized column (maps ratio onto salary scale) ──
const rawRows = [
  { Department: 'Engineering', AvgBaseSalary: 169000, CompaRatio: 0.96 },
  { Department: 'Product',     AvgBaseSalary: 156000, CompaRatio: 1.01 },
  // ... more rows
];
const data = rawRows.map(row => ({
  ...row,
  CompaRatioNorm: ((row.CompaRatio - RATIO_MIN) / (RATIO_MAX - RATIO_MIN)) * SALARY_MAX
  // e.g. ratio 0.88 → 0, ratio 1.00 → 108000, ratio 1.08 → 180000
}));

const schema = [
  { name: 'Department',    type: 'dimension' },
  { name: 'AvgBaseSalary', type: 'measure', defAggFn: 'avg' },
  { name: 'CompaRatio',    type: 'measure', defAggFn: 'avg' },
  { name: 'CompaRatioNorm', type: 'measure', defAggFn: 'avg' },
];

const DEPT_FIELD       = 'Department';
const SALARY_FIELD     = 'AvgBaseSalary';
const COMPA_FIELD      = 'CompaRatio';
const COMPA_NORM_FIELD = 'CompaRatioNorm';

const dm = new DataModel(DataModel.loadDataSync(data, schema));

// Reference line: normalized x-position for compa-ratio = 1.0
const MARKET_NORM = ((1.0 - RATIO_MIN) / (RATIO_MAX - RATIO_MIN)) * SALARY_MAX;

canvas
  .data(dm)
  .rows([DEPT_FIELD])
  // CRITICAL ORDER: [[COMPA_NORM_FIELD], [SALARY_FIELD]] — first field = TOP axis, second = BOTTOM axis
  // In Muze horizontal bar chart, first column = top x-axis, second column = bottom x-axis
  .columns([[COMPA_NORM_FIELD], [SALARY_FIELD]])
  .layers([
    // Bar: salary (maps to SALARY_FIELD panel — bottom axis)
    {
      mark: 'bar',
      encoding: {
        x: SALARY_FIELD,
        color: { value: () => '#1B3A2F' }
      }
    },
    // Text: salary labels at bar ends (also maps to SALARY_FIELD panel)
    // ThoughtSpot note: a top-level text layer alongside bar/point breaks TS
    // interaction propagation (hard rule) — in the shipped chart, drop this layer
    // and inject the labels via SVG in `afterRendered` instead (see the pattern in
    // *`mark: 'text'` as a separate layer*). The offsets below still apply.
    // Muze text marks default to text-anchor:middle, so use +22px to center the label
    // just beyond the bar end (~18px half-width + 4px gap). Use calculateDomain:false
    // so label positions don't expand the axis domain.
    {
      mark: 'text',
      encoding: {
        x: SALARY_FIELD,
        text: {
          field: SALARY_FIELD,
          formatter: (d) => {
            const v = typeof d === 'object' ? d.rawValue : d;
            return '$' + Math.round(v / 1000) + 'K';
          }
        },
        color: { value: () => '#444444' }
      },
      encodingTransform: (points) => {
        points.forEach(p => {
          if (p.update && p.update.x != null) { p.update.x += 22; }  // guard OK — relative nudge (cross-panel points are null); +22 because text-anchor defaults to middle
        });
        return points;
      },
      calculateDomain: false
    },
    // Point: compa-ratio diamond (maps to COMPA_NORM_FIELD panel — top axis) — size MUST be 0.05
    {
      mark: 'point',
      encoding: {
        x: COMPA_NORM_FIELD,
        color: { value: () => '#E8744F' },
        shape: { value: () => 'diamond' },
        size: { value: () => 0.05 }   // NEVER exceed 0.05 — larger values fill the entire row
      }
    },
    // Reference line at compa-ratio = 1.0
    // CRITICAL: p.update.x is in PIXELS (not data values). Convert MARKET_NORM
    // to pixels using layer.measurement().width and the axis domain max (AXIS_MAX).
    // Never set p.update.x = MARKET_NORM directly — that places it 120,000px off-screen.
    {
      mark: 'point',
      encoding: {
        x: COMPA_NORM_FIELD,
        color: { value: () => '#C0622F' },
        shape: { value: () => 'circle' },
        size: { value: () => 0.05 },
        opacity: { value: () => 0.7 }
      },
      encodingTransform: (points, layer) => {
        // Use the axis domain max here. If you set domain: [0, SALARY_MAX], use SALARY_MAX.
        // If you added headroom (e.g., AXIS_MAX = SALARY_MAX * 1.08), use that instead.
        const refPixel = (MARKET_NORM / SALARY_MAX) * layer.measurement().width;
        points.forEach(p => {
          if (p.update && p.update.x != null) p.update.x = refPixel;
        });
        return points;
      },
      calculateDomain: false,
      interactive: false
    }
  ])
  .config({
    axes: {
      x: {
        fields: {
          [COMPA_NORM_FIELD]: {
            showAxisName: true,
            name: 'Compa-Ratio',
            tickFormat: (d) => {
              const v = typeof d === 'object' ? d.rawValue : d;
              // Reverse-normalize: convert from salary-scale back to compa-ratio
              const original = RATIO_MIN + (v / SALARY_MAX) * (RATIO_MAX - RATIO_MIN);
              return original.toFixed(2);
            }
          },
          [SALARY_FIELD]: {
            showAxisName: true,
            name: 'Avg Base Salary',
            tickFormat: (d) => {
              const v = typeof d === 'object' ? d.rawValue : d;
              return '$' + Math.round(v / 1000) + 'K';
            }
          }
        }
      },
      y: {
        showAxisName: false,
        fields: {
          [DEPT_FIELD]: {
            ordering: {
              type: 'field',
              direction: 'desc',
              field: { name: SALARY_FIELD, aggregation: 'avg' }
            }
          }
        }
      }
    },
    legend: { show: false }
  })
  // Title/subtitle only because the source image showed them — omit otherwise (Liveboard provides its own).
  .title('Salary and Compa-Ratio by Department')
  .subtitle('Bars = avg base salary | Diamonds = compa-ratio | 1.0 = on market')
  // Size via applySize() (Responsive Sizing pattern) — no fixed .width()/.height().
  // Budget ~70px per row + 200px overhead so both axes and the bar-end labels fit.
  .mount('#chart');
```

**KEY RULES for this pattern:**
1. Column order MATTERS: `[[COMPA_NORM_FIELD], [SALARY_FIELD]]` — first = TOP axis, second = BOTTOM axis
2. Use tuple NOT `share()` — tuple gives dual axes; share gives one shared axis
3. Use `axes.x.fields` per-field config (NOT generic `axes.x`), configuring both fields
4. Normalization formula: `((ratio - RATIO_MIN) / (RATIO_MAX - RATIO_MIN)) * SALARY_MAX` — NOT `ratio * 100000`
5. Reference marker at compa-ratio = 1.0: use `mark: 'point'` with `x: COMPA_NORM_FIELD` and an `encodingTransform` that converts `MARKET_NORM` from **data space to pixels** via `layer.measurement()`. Do NOT set `p.update.x = MARKET_NORM` directly (large data values = off-screen pixels). Do NOT use `mark: 'tick'` (renders as horizontal bars). Correct pattern:
   ```javascript
   { mark: 'point', encoding: { x: COMPA_NORM_FIELD, color: { value: () => '#C0622F' }, size: { value: () => 0.05 }, shape: { value: () => 'circle' } },
     encodingTransform: (points, layer) => {
       const refPixel = (MARKET_NORM / SALARY_MAX) * layer.measurement().width;  // use axis domain max
       points.forEach(p => { if (p.update && p.update.x != null) p.update.x = refPixel; });
       return points;
     }, calculateDomain: false, interactive: false }
6. Sort departments by salary descending: `y.fields[DEPT_FIELD].ordering = { type: 'field', direction: 'desc', field: { name: SALARY_FIELD, aggregation: 'avg' } }`
7. Canvas height must be at least 560px to show both top and bottom axes

#### When the target shows side-by-side panels (genuinely separate charts):
Only use this for targets that show completely separate chart areas with a shared Y axis. This is rare. Do NOT use for bar+diamond overlaid charts.

### Diverging Bar Chart — Symmetric Bars from Zero

When the target shows two metrics per category with bars going LEFT and RIGHT from a centered zero (e.g., Engagement going left, eNPS going right): use **long-form data with one metric stored as negative values**, plus sub-rows so each category renders as two stacked bars.

```javascript
const schema = [
  { name: 'Department', type: 'dimension' },
  { name: 'Metric',     type: 'dimension' },
  { name: 'Value',      type: 'measure', defAggFn: 'sum' },
];

// Engagement stored NEGATIVE → bar goes left of zero. eNPS positive → bar goes right.
const data = [
  { Department: 'Engineering', Metric: 'Engagement', Value: -82.1 },
  { Department: 'Engineering', Metric: 'eNPS',       Value:  38.4 },
  // ... one row per (department, metric)
];

const DEPT_FIELD   = 'Department';
const METRIC_FIELD = 'Metric';
const VALUE_FIELD  = 'Value';

// Range is alphabetically assigned by metric value.
// 'Engagement' < 'eNPS' (uppercase 'E' < lowercase 'e' in JS) → range[0] = Engagement.
const COLORS = {
  Engagement: '#1B3A2F',
  eNPS:       '#A89A5A',
};

canvas
  .data(dm)
  .rows([DEPT_FIELD, METRIC_FIELD])              // sub-rows → two bars per dept
  .columns([VALUE_FIELD])
  .color({
    field: METRIC_FIELD,
    range: [COLORS.Engagement, COLORS.eNPS],     // alphabetical; NO domain
  })
  .layers([
    { mark: 'bar', encoding: { x: VALUE_FIELD } },
    // TS note: top-level text layers break interaction propagation (hard rule) —
    // in the shipped chart inject these labels via SVG in `afterRendered` instead.
    {
      mark: 'text',
      encoding: {
        x: VALUE_FIELD,
        text: {
          field: VALUE_FIELD,
          formatter: (d) => {
            const v = typeof d === 'object' ? d.rawValue : d;
            return Math.abs(v).toFixed(1);       // hide the negative sign
          },
        },
        color: { value: () => '#333333' },
      },
      encodingTransform: (points, layer) => {
        // Use the axis scale to find the zero pixel, then flip text-anchor per side.
        const xScale = layer.axes()?.x?.scale?.();
        const zeroX  = xScale ? xScale(0) : null;
        points.forEach(p => {
          const isNeg = zeroX !== null && p.update.x < zeroX;
          if (isNeg) { p.update.x -= 4; p.style = Object.assign(p.style || {}, { 'text-anchor': 'end',   'font-size': '10px', 'font-weight': '600' }); }
          else       { p.update.x += 4; p.style = Object.assign(p.style || {}, { 'text-anchor': 'start', 'font-size': '10px', 'font-weight': '600' }); }
        });
        return points;
      },
      calculateDomain: false,
    },
  ])
  .config({
    axes: {
      x: {
        tickFormat: (d) => {
          const v = typeof d === 'object' ? d.rawValue : d;
          return String(Math.abs(Math.round(v)));   // axis labels show |value|
        },
      },
      y: {
        showAxisName: false,
        fields: { [METRIC_FIELD]: { show: false } }, // hide the inner sub-row label
      },
    },
    legend: { show: true, position: 'top' },
  });
```

**KEY RULES:**
1. Store one metric as negative values in the data — that's how the bar gets a left-going extent.
2. `.rows([DEPT_FIELD, METRIC_FIELD])` produces two stacked sub-rows per department; the second sub-row label is hidden via `axes.y.fields[METRIC_FIELD].show: false`.
3. Color via `.color({ field: METRIC_FIELD, range: [...] })` — **NO `domain`** — and put `range` in alphabetical order of metric names.
4. `tickFormat` on the x-axis must `Math.abs(...)` so the axis shows `100 ... 0 ... 100`, not `-100 ... 0 ... 100`.
5. Text label `formatter` must `Math.abs(v)` so the displayed numbers are positive.
6. Text label `encodingTransform` reads the axis scale to detect which side of zero each point lies on, then flips `text-anchor` and the pixel nudge.

### Color Encoding Rules

1. **Always prefer dynamic color assignment**: Use simple field-name strings for color encoding
   (e.g., `.color('Category')` or `encoding: { color: 'FieldName' }`). Let Muze's default
   palette handle color assignment automatically.

2. **Never hardcode dimension values in color configuration**: Do NOT use `domainRangeMap`,
   `domain`, or `range` arrays that list specific dimension values (e.g.,
   `domainRangeMap: { 'USA': '#ff0000', 'Japan': '#0000ff' }`). These break when the
   data changes and create maintenance burden.

3. **Only specify custom color ranges (without domain) when**:
   - The user explicitly requests specific colors or a specific color palette
   - The chart type semantically requires it (e.g., red/green for profit/loss,
     bullish/bearish in financial charts)
   - The uploaded image clearly shows a specific color scheme that must be matched

4. **When custom colors ARE needed**, prefer palette-level range arrays over value-level
   domain maps:
   - PREFERRED: `.color({ field: 'Category', range: ['#4A90D9', '#E8744F', '#6BC8A3'] })`
   - AVOID: `domainRangeMap: { 'Technology': '#4A90D9', 'Automotive': '#E8744F' }`
   - **CRITICAL**: `range` is assigned in **alphabetical order** of the field's category values. Sort your `range` array to match the alphabetical order of the categories you want to color, or use the `encodingTransform` fill-override pattern. See *Color `range` is alphabetically assigned*. Never include `domain` in the `.color()` call — it silently breaks `range`.

5. **For conditional coloring** (e.g., positive=green, negative=red), use value functions
   in the layer encoding rather than hardcoded domain maps.

### KPI Cards / Metric Tiles

When the uploaded image shows a KPI card, KPI chart, or metric tile, follow this pattern exactly.
See Recipe 16.39 in the Muze API Reference below for the complete working code example.

**Recognition cues:**
- A large, prominent number or metric value as the primary visual element
- Optional sparkline, variance indicator, or comparison to a target/benchmark
- Minimal or no axis labels, gridlines, or full chart infrastructure

**Canvas sizing:**
- Size via the responsive pattern; KPI cards read best around 250x200 — treat that as
  the design target, not a hardcoded `.width().height()`.
- Only hardcode dimensions if the user explicitly requests a specific size.

**Building with Muze — required pattern:**
1. Each visual element (status badge, main value, change indicator, peer comparison) is a **separate text layer**
2. Position each layer using `encodingTransform` with **absolute pixel values**. Use `layer.measurement()` to get `{ width, height }` if needed (e.g., to center: `width / 2`), but set fixed pixel positions — NOT percentages. This keeps the layout consistent regardless of display size: `p.update.x = 10; p.update.y = 60;`. **Assign unconditionally** — never wrap in `if (p.update && p.update.x != null) { ... }`. The guard skips when `p.update.x` is null (the default for text-only layers without x/y encoding), and the chart renders blank.
3. Style each layer using `p.style` with SVG attributes: `'font-size'`, `'font-weight'`, `'text-anchor'`
4. `rows` must have at least one measure and `columns` at least one dimension to create the plotting area — these axes are hidden via config, but Muze needs them internally
5. Set `autoGroupBy: { disabled: true }` to prevent aggregation
6. Hide all axes, gridlines, borders, and legend (see Recipe 16.39 config block)
7. For styled KPI text layers, use `muze.Operators.html` inside `encodingTransform` to set SVG text content — **NOT** in `.title()` or `.subtitle()`, which only accept plain strings
8. For sparklines, add a line layer with hidden axes beneath the text layers

**Data schema tips:**
- Pre-formatted display strings (e.g., `DisplayValue: '$124.29M'`) work well as dimension fields — they avoid aggregation issues
- Numeric measures also work — use a formatter: `{ field: 'Value', formatter: (val) => '$' + val.toFixed(2) + 'M' }`
- To compose multi-field strings, reference the data row directly in the formatter: `formatter: (val) => '+' + val + 'M (' + row.ChangePercent + '%)'`

### Production Patterns from Real ThoughtSpot Charts

Apply these patterns when the chart calls for the technique — don't apply them unconditionally.

#### Muze patterns

**1. Schema-indexed data access inside `encodingTransform`** — when you need other field values per point (e.g., to color a point by its category), you cannot read them off `p`. Walk the DataModel result instead:
```javascript
encodingTransform: (points, layer) => {
  const result = layer.data().getData();
  const cols = result.schema.map(s => s.name);
  const cityIdx = cols.indexOf(CITY_FIELD);
  points.forEach((p, i) => {
    const city = cityIdx >= 0 ? result.data[i][cityIdx] : null;
    p.style = Object.assign(p.style || {}, { fill: COLORS[city] });
  });
  return points;
}
```
Why: `p.data`, `p.row`, `p.datum`, and `p.datum.dataObj` are all **undefined** inside `encodingTransform` — even though `d.datum.dataObj` works fine inside `encoding.color.value` or `encoding.size.value` callbacks. These are different execution contexts. In `encodingTransform`, the ONLY reliable data access is `layer.data().getData()` + schema index. Never use `p?.datum?.dataObj?.[FIELD]` in `encodingTransform` — it will silently return `undefined` for every row, which is very hard to debug.

**2. `autoGroupBy: { disabled: true }` for scatter / bubble / one-mark-per-row charts.** Otherwise Muze auto-groups by dimensions and collapses rows you wanted to render individually. Required for bubble and scatter; usually wrong for bar / line / area.

**3. Smart label positioning via the axis scale function** — for diverging bar charts, read the axis scale to find the zero pixel, then flip `text-anchor`:
```javascript
encodingTransform: (points, layer) => {
  const xScale = layer.axes()?.x?.scale?.();
  const zeroX = xScale ? xScale(0) : null;
  points.forEach(p => {
    const isNegative = zeroX !== null ? p.update.x < zeroX : false;
    if (isNegative) { p.update.x -= 6; p.style['text-anchor'] = 'end'; }
    else            { p.update.x += 6; p.style['text-anchor'] = 'start'; }
  });
  return points;
}
```

**4. Pixel↔data scale conversion via two anchor points** — to draw a regression line or reference line that aligns with Muze's rendered axes, capture two known points' pixel positions during `encodingTransform`, then derive a linear map:
```javascript
const captured = {};
// inside encodingTransform of the point layer:
captured[city] = { px: p.update.x, py: p.update.y };
// after render, with two known cities A and B:
const m = (captured[B].px - captured[A].px) / (valB - valA);
const c = captured[A].px - m * valA;
const toPix = v => m * v + c;
```
Use the resulting `toPix(v)` to position SVG overlay elements in data space.

**5. Labels and bubble radii near the axis edge** — `axes.*.domain` is silently ignored (hard rule), so you cannot buy headroom via config. Use shorter label formats, flip `text-anchor` to keep labels inside the plot, or draw the labels as post-render SVG overlays instead.

**6. `interactive: false` and `calculateDomain: false` on helper layers.** Apply to text overlays, reference markers, annotation layers — anything that isn't a primary data mark. Prevents them from eating hover events or expanding the axis domain.

**7. SVG overlay injection on top of a rendered Muze chart** — for reference lines, annotations, or trend lines Muze can't natively express. Use the namespaced API and the post-render timing pattern from rule below:
```javascript
const NS = 'http://www.w3.org/2000/svg';
const rootSvg = document.querySelector('#chart svg');
const g = document.createElementNS(NS, 'g');
g.setAttribute('clip-path', 'url(#muze-ov-clip)');
g.setAttribute('pointer-events', 'none');
const ln = document.createElementNS(NS, 'line');
ln.setAttribute('x1', toPix(meanX)); ln.setAttribute('y1', plotTop);
ln.setAttribute('x2', toPix(meanX)); ln.setAttribute('y2', plotBottom);
ln.setAttribute('stroke', COLORS.neutral);
ln.setAttribute('stroke-dasharray', '5 5');
g.appendChild(ln);
rootSvg.appendChild(g);
```
**Always** use `createElementNS(NS, …)` for SVG elements — `createElement` produces non-rendering nodes.

**8. Post-render timing — `afterRendered` plus retry**. Muze's `afterRendered` event sometimes fires before SVG paths are in the DOM. Combine the event with a polling retry:
```javascript
canvas.once('afterRendered', () => {
  let attempts = 0;
  const tryRun = () => {
    if (document.querySelector('#chart svg path')) {
      injectOverlays();
    } else if (attempts++ < 40) {
      setTimeout(tryRun, 100);
    }
  };
  tryRun();
});
```

#### Chart.js patterns

**9. Damped Hermite interpolation for smooth curves between sparse anchors** — use when the user wants a smooth line through 2–3 anchor points (e.g., 2024 → 2035 → 2050) without overshoot. Inline ~15-line helper:
```javascript
function smoothInterp(y0, v0, y1, v1, y2, v2, yr) {
  if (yr <= y0) return v0;
  if (yr >= y2) return v2;
  // damped cubic Hermite — t in [0,1] across the segment
  const segStart = yr <= y1 ? y0 : y1;
  const segEnd   = yr <= y1 ? y1 : y2;
  const vStart   = yr <= y1 ? v0 : v1;
  const vEnd     = yr <= y1 ? v1 : v2;
  const t = (yr - segStart) / (segEnd - segStart);
  const damp = t * t * (3 - 2 * t);
  return vStart + (vEnd - vStart) * damp;
}
```

**10. Stacked horizontal progress bar** — for KPI progress meters: two stacked datasets (progress + remainder), `indexAxis: 'y'`, `borderRadius` per side, hidden axes, and an absolute-positioned `<div>` tick mark using `transform: translateX(-50%)` to mark the current position.

**11. Loading Chart.js**: use the dynamic-load pattern in the *Library Selection* section (`document.createElement('script')` + `await new Promise`) — chart.html must contain no `<script>` tags. Reference `window.Chart` after the load promise resolves.

#### Raw SVG patterns

**12. ResizeObserver + RAF + `viewBox` for responsive single-stat tiles** — the canonical recipe:
```javascript
const container = document.getElementById('chart');
let rafId = null;
function render(w) {
  if (w <= 0) return;                       // guard against zero-width init
  const svgH = 200;
  svg.setAttribute('viewBox', `0 0 ${w} ${svgH}`);
  // ...compute circle / line / text positions from `w` and constants...
}
const ro = new ResizeObserver(() => {
  if (rafId) cancelAnimationFrame(rafId);
  rafId = requestAnimationFrame(() => { render(container.offsetWidth); rafId = null; });
});
ro.observe(container);
render(container.offsetWidth);
```
RAF batching prevents render thrashing during continuous resize events. The `w > 0` guard avoids rendering at zero width during initialization.

**13. Big-number typography for KPI tiles** — 52px / weight 800 / letter-spacing -2px is the calibration that reads well at the typical TS tile size. Glow effect = outer transparent circle + inner solid circle.

#### Layout patterns (chart + KPI compositions)

**14. Flex layout with `min-height: 0`** — for layouts that combine a chart area with a KPI strip:
```css
#chart            { display: flex; flex-direction: column; height: 100%; }
.chart-wrap       { flex: 1 1 0; min-height: 0; position: relative; }
.metrics          { flex: 0 0 auto; }
```
The `min-height: 0` is the line that's easy to forget — without it, flex children won't shrink below their content size and the chart area won't resize correctly.

**Heights chain or collapse — every parent up to `<html>` needs explicit height.** A common Chart.js / SVG render bug: only header text appears, the chart area is blank. Cause: `#chart { height: 100% }` against a body without explicit height collapses to 0, so the canvas inside has nothing to fill. Two fixes:

```css
/* Option A — explicit chain */
html, body { height: 100%; margin: 0; }
#chart      { height: 100%; }

/* Option B — viewport unit (simpler, robust to body styling) */
#chart      { height: calc(100vh - 32px); }   /* or 100vh */
```

For **compact KPI cards** (gauges, healthcare cards, single-stat tiles): do the OPPOSITE — set `#chart { height: auto }` and give the card a fixed `max-width` and content-driven `min-height` so it doesn't stretch to fill the viewport. A KPI card sized to fill 100vh looks broken even when every internal style is correct.

**15. System fonts** — `font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;` is what TS dashboards use. Match it for visual consistency.

#### Chart.js extended patterns

**16. Bar + line combo with conditional bar coloring (above/below plan)** — use TWO separate bar datasets (one for "below plan" rows with green, one for "above plan" rows with red), plus a line dataset. Each bar dataset uses `null` for rows it doesn't own:
```javascript
datasets: [
  { type: 'bar', label: 'Below Plan', data: actuals.map((v,i) => v < plan[i] ? v : null), backgroundColor: '#16a34a' },
  { type: 'bar', label: 'Above Plan', data: actuals.map((v,i) => v >= plan[i] ? v : null), backgroundColor: '#dc2626' },
  { type: 'line', label: 'Plan', data: plan, borderDash: [6,4], borderColor: '#3b82f6', fill: false },
]
```
Load `chartjs-plugin-datalabels` for bar value labels at bar start/end.

**17. Line chart with background performance bands** — inject a custom plugin that draws filled `fillRect` bands in `beforeDraw`. Read pixel extents from `chart.chartArea` and `chart.scales.y.getPixelForValue(yValue)`:
```javascript
const bandPlugin = {
  id: 'bands',
  beforeDraw(chart) {
    const { ctx: c, chartArea: { top, bottom, left, right }, scales: { y } } = chart;
    [{ yMin: 80, yMax: 100, color: 'rgba(45,212,191,0.18)' },
     { yMin: 40, yMax: 80,  color: 'rgba(200,200,200,0.15)' },
     { yMin: 0,  yMax: 40,  color: 'rgba(252,165,165,0.22)' }].forEach(({ yMin, yMax, color }) => {
      const yT = y.getPixelForValue(yMax), yB = y.getPixelForValue(yMin);
      c.save(); c.fillStyle = color;
      c.fillRect(left, Math.max(yT, top), right - left, Math.min(yB, bottom) - Math.max(yT, top));
      c.restore();
    });
  },
};
new Chart(ctx, { type: 'line', plugins: [bandPlugin], ... });
```

**18. Horizontal stacked progress bar with annotation** — for KPI progress meters (actual vs forecast vs target):
```javascript
{ type: 'bar', indexAxis: 'y', data: { datasets: [
  { label: 'Actual', data: [ACTUAL], backgroundColor: '#1d4ed8' },
  { label: 'Gap',    data: [TARGET - ACTUAL], backgroundColor: 'rgba(252,165,165,0.5)' },
]}}
// annotation plugin draws dashed line at TARGET + label
```
Load both `chartjs-plugin-datalabels` (for "146,942" center label) and `chartjs-plugin-annotation` (for dashed target line).

**Chart.js plugin CDN URLs MUST include the explicit `/dist/plugin.min.js` path** — `https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2` (without the `/dist/...`) returns 404 on jsdelivr, leaving the plugin unregistered and the chart silently rendering without datalabels. Use the full path:

```javascript
'https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2/dist/chartjs-plugin-datalabels.min.js'
'https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3/dist/chartjs-plugin-annotation.min.js'
'https://cdn.jsdelivr.net/npm/chartjs-chart-sankey@0.12/dist/chartjs-chart-sankey.min.js'
```

Plugins auto-register on `window.Chart` once loaded; you don't need to call `Chart.register(...)` for the standard ones. After all plugin scripts have loaded (await each Promise), you can build the `Chart` instance.

**19. Sankey diagram** — use `chartjs-chart-sankey` plugin:
```javascript
const sankeyScript = document.createElement('script');
sankeyScript.src = 'https://cdn.jsdelivr.net/npm/chartjs-chart-sankey@0.12/dist/chartjs-chart-sankey.min.js';
await new Promise((resolve, reject) => { sankeyScript.onload = resolve; sankeyScript.onerror = reject; document.head.appendChild(sankeyScript); });
// data format: [{ from: 'Node A', to: 'Node B', flow: 59.1 }, ...]
// colorFrom/colorTo callbacks: (context) => colorMap[context.dataset.data[context.dataIndex].from]
new Chart(ctx, { type: 'sankey', data: { datasets: [{ label: 'Flow', data, colorFrom, colorTo, borderWidth: 0 }] } });
```
Node labels are single-line strings — newlines (`\n`) are not supported and will render as literal text.

#### Raw Canvas patterns

**20. Slope / bump chart** — for rank-over-time charts, use HTML5 Canvas directly. Key recipe:
- Container div with `flex: 1 1 0; min-height: 0;` so Canvas fills available height
- Set `canvas.width = wrap.offsetWidth * devicePixelRatio` and scale the ctx for HiDPI
- `xForYear(yr) = padL + ((yr - minYr) / (maxYr - minYr)) * chartW` — linear x
- `yForRank(r) = padT + ((r - 1) / (N - 1)) * chartH` — linear y (rank 1 = top)
- Draw lines via `ctx.beginPath(); moveTo(x0,y0); lineTo(x1,y1); ctx.stroke()`
- Left labels: `ctx.textAlign='right'`; right labels: `ctx.textAlign='left'`
- Dots at anchor years: `ctx.arc(x, y, 3, 0, Math.PI*2); ctx.fill()`
- Wrap in `ResizeObserver` + `requestAnimationFrame` for responsive resize

#### Raw SVG patterns

**21. Semi-circle gauge chart** — use SVG arc paths. The gauge is a half-circle from 180° to 360°. Formula:
```javascript
function arcPath(cx, cy, r, startAngle, endAngle) {
  const x1 = cx + r * Math.cos(startAngle), y1 = cy + r * Math.sin(startAngle);
  const x2 = cx + r * Math.cos(endAngle),   y2 = cy + r * Math.sin(endAngle);
  const large = (endAngle - startAngle) > Math.PI ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
}
// Track (full): arcPath(cx, cy, r, Math.PI, 2*Math.PI)
// Fill:         arcPath(cx, cy, r, Math.PI, Math.PI + (pct/100)*Math.PI)
```
Set `stroke-linecap="round"` on both paths. SVG height should be ~r + strokeWidth (just the top half), e.g. `viewBox="0 0 160 90"` for r=60, cx=80, cy=80.

**22. KPI stat tile (big number + comparison text)** — raw SVG with fixed y positions. Keep the SVG viewport height tight (200px for 3 lines):
```javascript
container.innerHTML = `<svg viewBox="0 0 ${w} 200" width="${w}" height="200">
  <text x="16" y="96" font-size="96" font-weight="800" fill="${COLOR}">${MAIN_VALUE}</text>
  <text x="16" y="138" font-size="20" font-weight="700" fill="${COLOR2}">${COMPARISON}</text>
  <text x="16" y="165" font-size="16" fill="${COLOR3}">${SUBTITLE}</text>
</svg>`;
```

**23. Healthcare / metric KPI card** — use HTML+CSS rather than SVG for structured cards with sections:
- Left sidebar (YTD rank block): fixed-width `<div>` with grey background, large number
- Right content area: rate label + trend arrow, big metric %, vs-target comparisons
- Cards have `border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.1);`
- Trend arrows: use `&#9650;` (▲) in green and `&#9660;` (▼) in grey/red

#### Raw HTML/CSS patterns

**24. Quote / annotation text card** — no chart library; chart.html + chart.css carry everything, chart.js only calls `viz.events.emitRenderCompletedEvent()`:
- Left border gradient: prefer a sibling `<div class="card-border"></div>` with `width: 6px; align-self: stretch; flex-shrink: 0; background: linear-gradient(to bottom, #dc2626, #f97316, #16a34a);` over the `border-image` approach. The sibling-div pattern has fewer interactions with parent layout (height resolution, flex shrink, slice value) — `border-image: linear-gradient(...) 1` on `border-left` can render as a single solid color when the card's height isn't fully resolved at paint time. Wrap the card content in a flex container so the gradient div sits next to the body:
  ```html
  <div class="quote-card">
    <div class="card-border"></div>
    <div class="card-body"> ... </div>
  </div>
  ```
  ```css
  .quote-card { display: flex; flex-direction: row; }
  .card-border { width: 6px; align-self: stretch; flex-shrink: 0;
                 background: linear-gradient(to bottom, #dc2626, #f97316, #16a34a); }
  .card-body { padding: 36px 44px; }
  ```
- Opening quote: `&ldquo;` rendered in a serif font at 56px
- Italic secondary text: `font-style: italic; color: #374151;`
- Attribution row: flex row with circular SVG icon + bold title + grey subtitle

**25. Intro / context slide** — gradient background card:
```css
.intro-card {
  background: linear-gradient(135deg, #dbeafe 0%, #ede9fe 60%, #c7d2fe 100%);
  padding: 28px 32px;
}
```
Use dark navy for headline (`#1e3a5f`, `font-weight: 700`) and medium grey for body text.

## Core Principle
Recreate what the target shows with the library the chart routes to (see *Library
Selection* above and the library table in SKILL.md) — raw HTML/CSS, gridjs, and
Chart.js are all legitimate outputs, not just Muze. If some element cannot be
reproduced, call it out in the run README rather than quietly approximating.

## Muze API Reference
