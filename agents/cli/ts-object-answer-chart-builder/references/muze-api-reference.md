# Muze v4.7.10 — Verified API Reference

> This reference was compiled by cross-referencing the actual muze.js v4.7.10 bundle
> (static analysis of 66,427 lines) with the official Muze Studio 26.2.0 documentation.
> Every method listed here has been verified to exist in the bundle.
>
> Adapted from an older Muze Studio chat pipeline. API details are still good; where
> anything here conflicts with SKILL.md or the references/ files (especially
> references/hard-rules.md), those win. In BYOC, `muze` comes from the host's `viz`
> global and is synchronous — `canvas = muze.canvas();`, no `muze()` factory call.
> Section 0 holds the working recipes; sections 1 to 21 are the API itself.

---

## 0. Recipes

Working patterns for a BYOC tile, kept from the older Muze Studio pipeline. Apply one when the
chart calls for it, not unconditionally. Every rule they lean on is in references/hard-rules.md.

### 0.1 Responsive sizing (Muze without the shared core)

Read the size from `#chart`, rebuild the canvas only when data changes, re-fit when size changes.
The retained-canvas re-mount (`canvas.width(w).height(h).mount(el)`) re-layouts in place with no
flicker and no entry animation re-run (verified on v4.7.10). Charts built on `AZ.boot` already get
this from the core.

```javascript
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

No `window.addEventListener('resize', ...)`: the observer on `#chart` covers it and fires for
tile resizes the window never sees. Hardcode pixel dimensions only when the user asks for them.

### 0.2 Reading row data inside `encodingTransform`

`p.data`, `p.row`, `p.datum` and `p.datum.dataObj` are all undefined inside `encodingTransform`
(they work in `encoding.color.value` and `encoding.size.value`, a different context). The only
reliable access is the layer's DataModel plus a schema index. `p?.datum?.dataObj?.[FIELD]` returns
undefined for every row with no error.

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

This fill override is also the escape hatch when the alphabetical `range` mapping (0.4) is fragile.

### 0.3 Helper layers, one-mark-per-row charts

- `interactive: false` and `calculateDomain: false` on every layer that is not a primary data mark
  (reference markers, annotation layers). They stop it eating hover events and expanding the axis.
- `autoGroupBy: { disabled: true }` for scatter, bubble and any chart that must draw one mark per
  row. Without it Muze groups by dimensions and collapses rows. Usually wrong for bar, line, area.

### 0.4 Colour

- Prefer the field name: `.color('Category')` or `encoding: { color: 'Category' }`, and let the
  default palette assign. Never list dimension values in `domainRangeMap` or `domain`: it breaks
  when the data changes, and `domain` inside `.color()` silently kills `range` too.
- Custom `range` only when the user asks, the chart semantically needs it (profit/loss), or the
  target plainly shows it. Then `.color({ field, range: [...] })` with **no `domain`**.
- `range` is assigned in **alphabetical, case-sensitive JS order** of the field's values; data
  order is irrelevant. `'Engagement' < 'eNPS'` because `'E' < 'e'`. Work it out with
  `[...new Set(data.map(d => d[FIELD]))].sort()`. When the order is fragile (renaming a category
  would shuffle colours), set `p.style.fill` per row via 0.2 instead.
- Conditional colour (positive green, negative red): a value function in the layer encoding, not a
  domain map.

### 0.5 Labels

- `axes.*.domain` is ignored, so headroom for bar-end labels cannot be bought from config. Use
  shorter formats (`$169K`, not `$169,000`), inside-bar labels (`'text-anchor': 'end'` and
  `p.update.x -= 4`), or post-render SVG labels (0.6).
- Stagger or omit labels that would overlap: compare neighbouring pixel positions against the
  label width (`deps.smartLabel.getOriSize(text)`) before drawing.
- `calculateDomain: false` on every text layer so label positions do not expand the axis.
- Relative nudges may keep a null guard, because skipping a cross-panel null point is fine; absolute
  positions are assigned unconditionally (hard rule). Muze text marks default to
  `text-anchor: middle`, so a bar-end label needs about +22px (half label width plus a gap), not +4:

```javascript
encodingTransform: (points) => {
  points.forEach(p => {
    if (p.update && p.update.x != null) {  // guard OK: relative nudge
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
```

### 0.6 Point and bubble labels without a text layer (TS-safe)

A top-level `mark: 'text'` layer beside bar or point marks throws
`this._onPropagationDone is not a function` in ThoughtSpot and breaks hover, even with
`interactive: false`. Capture pixel positions in the data layer's `encodingTransform`, then draw
SVG text in `afterRendered`. In a recipe that still shows a `mark: 'text'` layer (0.9, 0.10),
replace it with this at ship time; the offsets carry over.

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

### 0.7 Post-render SVG overlays (reference lines, trend lines, annotations)

**Timing.** `afterRendered` sometimes fires before the paths are in the DOM. Combine it with a
bounded poll:

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

**Pixel from data, two anchors.** Capture two known points' pixels in the data layer's
`encodingTransform`, derive a linear map, and position overlay elements in data space:

```javascript
const captured = {};
// inside encodingTransform of the point layer:
captured[city] = { px: p.update.x, py: p.update.y };
// after render, with two known cities A and B:
const m = (captured[B].px - captured[A].px) / (valB - valA);
const c = captured[A].px - m * valA;
const toPix = v => m * v + c;
```

**Drawing.** Always `createElementNS`; `createElement` makes nodes that never render.

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

**Muze's SVG structure, for horizontal bar charts.**

- Muze nests SVGs. `document.querySelector('#chart svg')` returns the y-axis SVG (about 100px
  wide), not the plot. Select the **widest** SVG.
- Horizontal bars are `<line>` elements whose `x2` stays at 0 (CSS transforms place them). Bar
  positions cannot be read from attributes or `getBoundingClientRect()`, during or after animation.
- The y-axis is a tall narrow `<path>` (height over 100px, width under 5px) and its bounding box is
  readable right after render. Plot width is about `svgWidth - plotLeft - 60` (right margin for
  bar-end labels and padding).

A continuous dashed vertical reference line, built on those facts:

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

### 0.8 Reference markers inside Muze

Three shapes, from cheapest to most faithful. `p.update.x` is **pixels**; convert a data value
through `layer.measurement().width` and the axis domain max. `x: { value: () => CONST }` is also
taken as pixels.

A hairline `tick` (its `size` is a fraction of the row band, so `0.02`, not `0.6`), with no
`source` property (a DataModel built inside `source` crashes with `e.getDomain is not a function`):

```javascript
{ mark: 'tick',
  encoding: { x: TARGET_FIELD, color: { value: () => '#dc2626' } },
  size: { value: () => 0.02 },     // thin hairline, NOT 0.6
  calculateDomain: false, interactive: false }
```

A `point` layer repositioned to the reference x. `mark: 'line'` ignores `p.update.x`, so this is
the mark to use; it draws one dot per row at the same x, a dotted vertical marker:

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

A continuous dashed line: post-render SVG, 0.7.

### 0.9 Dual-axis overlay: bar plus point with different scales

How Muze reads several measures in `.columns()` (same for `.rows()`, see section 14):

- `columns([share(A, B)])`: one shared axis and scale. Only for same-unit measures (min/max temp).
  With different units the small measure pins near zero.
- `columns([[A], [B]])`: **two x-axes in one panel**, overlaid. Each layer maps to its panel through
  its `encoding.x` field. This is the pattern for bars with a diamond on a second scale.
- `columns([A, B])`: separate stacked panels. Only for targets that really show two chart areas.

Normalise the second measure onto the first's scale so the marks spread across the width, and
reverse the normalisation in that axis's `tickFormat`.

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
    // and inject the labels via SVG in `afterRendered` instead (recipe 0.6).
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
  // Size via applySize() (recipe 0.1) — no fixed .width()/.height().
  // Budget ~70px per row + 200px overhead so both axes and the bar-end labels fit.
  .mount('#chart');
```

Rules the recipe depends on:

1. Column order: `[[COMPA_NORM_FIELD], [SALARY_FIELD]]`, first = top axis, second = bottom axis.
2. Tuple, not `share()`.
3. `axes.x.fields` per-field config, both fields; not the generic `axes.x`.
4. Normalisation `((ratio - RATIO_MIN) / (RATIO_MAX - RATIO_MIN)) * SALARY_MAX`, not `ratio * 100000`.
5. Reference marker: a `point` layer plus pixel conversion (0.8). Not `tick` (renders as bars
   here), and never `p.update.x = MARKET_NORM`.
6. Sort rows by the bar measure with `ordering` on the dimension field.
7. Both axes need room: about 70px per row plus 200px.

### 0.10 Diverging bars from a centred zero

Two metrics per category, one going left and one right: long-form data with one metric stored as
**negative values**, sub-rows so each category renders two bars, and `Math.abs` on both the axis
and the labels.

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
    // in the shipped chart inject these labels via SVG in `afterRendered` instead (recipe 0.6).
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

The `layer.axes().x.scale()(0)` trick (find the zero pixel, flip `text-anchor` per side) works
for any label that must sit on the outer side of a signed bar.

### 0.11 Temporal x-axis ticks in ThoughtSpot

ThoughtSpot types any dimension whose name contains `quarter`, `month`, `year`, `date`, `week` or
`day` (case-insensitive, for example `Quarter (Order Date)`) as `subtype: "temporal"` and feeds
Muze millisecond `rawValue`s. Muze then draws calendar-boundary ticks (`October`, `2024`, `April`)
instead of the `Q4 2023` the table shows. The preview cannot show this: there the field is a plain
string. Only `axes.x.fields[FIELD].tickFormat` is honoured for temporal axes; the root
`axes.x.tickFormat` is never called. `d` is `{ formattedValue, rawValue }`; derive the label from
`rawValue` with UTC getters so it does not shift with the viewer's timezone.

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

Pick the branch that matches the grain. Do not add it to non-temporal dimensions.

Keep `Year` (any temporal field) `type: 'dimension'`. Typed as a measure on a line chart Muze
treats x and y as a scatter relationship and aggregates: scatter points, an x-axis of `0-2200`,
a collapsed y-scale. For a smooth line across years, generate one row per year.

### 0.12 Measure formatting is the chart's job

Table-mode display formats never reach the chart: `Field.formattedData()` returns raw numbers
(a percent column returns `5.1865`, not `"518.65%"`), the schema carries only
`name/type/subtype/defAggFn`, `data.getFieldsConfig` does not exist, and `viz.formatters` exposes
`NumberFormatter`/`DateFormatter` classes with no "format like the table" helper. When the target
shows currency, percent or thousands, emit a `tickFormat` and promote the choice into the
Customize block. Skip it for plainly raw measures (counts, scores).

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

### 0.13 Tooltip formatter

Never set `tooltip.mode`; configure `formatter` only. `dataStore.getData()` is a direct call.

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

In a real tile the native tooltip totals series and the crosshair snaps off the pointer; the
library charts hide both and draw their own (references/hard-rules.md, "Verified in a real
cluster"). Use this formatter when the native tooltip is acceptable.

### 0.14 KPI card built from Muze text layers

The library's `kpi-*` charts are inline SVG and are the better starting point. When the card must
be Muze (data-bound through a DataModel), the shape is the one in section 8, "Full Example — KPI
Card", plus:

- One text layer per visual element (status badge, main value, change indicator, comparison),
  each positioned by `encodingTransform` with **absolute pixel values**, assigned unconditionally.
  `layer.measurement()` gives `{ width, height }` for centring.
- `rows` needs at least one measure and `columns` at least one dimension or Muze creates no
  plotting area; hide those axes, gridlines, borders and the legend in config.
- `autoGroupBy: { disabled: true }` so the rows are not aggregated.
- Pre-formatted display strings (`DisplayValue: '$124.29M'`) work well as dimension fields and
  avoid aggregation. Numeric measures work with a `formatter`; compose multi-field strings by
  reading the row in the formatter.
- `muze.Operators.html` only inside `encodingTransform`, never in `.title()` / `.subtitle()`.
- A sparkline is a line layer with hidden axes beneath the text layers.
- Design target about 250x200, sized by the responsive pattern, not hardcoded.

---

## 1. Initialization Pattern

```js
const { muze, getDataFromSearchQuery } = viz;   // BYOC: `muze` is the host's sync build
const { DataModel } = muze;

const data = [
  { Category: "A", Sales: 100 },
  { Category: "B", Sales: 200 }
];

const schema = [
  { name: "Category", type: "dimension" },
  { name: "Sales", type: "measure", defAggFn: "sum" }
];

const parsedData = DataModel.loadDataSync(data, schema);
const dm = new DataModel(parsedData);

let canvas = null;        // module scope — resize handling reads this
canvas = muze.canvas();   // plain assignment; `const canvas = ...` would shadow the outer `let`
canvas
  .data(dm)
  .rows(["Sales"])
  .columns(["Category"])
  .width(600)
  .height(400)
  .mount("#chart");
```

**IMPORTANT — APIs that DO NOT exist in v4.7.10:**

| Hallucinated API | Reality |
|-----------------|---------|
| `DataModel.onReady(cb)` | Does NOT exist. Use `DataModel.loadDataSync()` |
| `canvas.scrollConfig()` | Does NOT exist. Use `.config({ scrollBar: {...} })` |
| `canvas.onready(cb)` | Does NOT exist. Use `.once("afterRendered", cb)` |
| `canvas.tooltip()` | Does NOT exist. Use `.config({ interaction: { tooltip: {...} } })` |

---

## 2. Top-Level Exports

The bundle has a single default export — a factory function.

```js
import muze from './muze.js';
```

> **BYOC note:** `viz.muze` is already the env — call `muze.canvas()` directly. The
> `muze()` factory call documented below applies to the standalone bundle only.

| Property | Type | Description |
|----------|------|-------------|
| `muze()` | Function | Factory — returns env with `.canvas()` method |
| `muze.DataModel` | Class | Data modeling class |
| `muze.DataStore` | Class | Higher-level data wrapper |
| `muze.Operators` | Object | `html` (tagged template), `share` (shared axis) |
| `muze.version` | String | Library version |
| `muze.ActionModel` | Object | Cross-chart interaction registry |
| `muze.SideEffects` | Object | Side effect classes |
| `muze.Behaviours` | Object | Behavioural action classes |
| `muze.layerFactory` | Object | Layer registration factory |
| `muze.utils` | Object | ~160 utility functions/classes |
| `muze.Themes` | Object | `MuzeLight`, `ModeLight`, `DummyLight` |
| `muze.Components` | Object | Internal component constructors |
| `muze.registry` | Object | Global component registry |

### `muze()` Instance Methods

| Method | Description |
|--------|-------------|
| `.canvas(options?)` | Creates a new Canvas instance |
| `.settings()` | Returns serialized settings |
| `.registry(...components)` | Gets/sets component registry |
| `.cellRegistry(...cells)` | Gets/sets cell registry |
| `.layerRegistry(...layers)` | Gets/sets layer registry |
| `.globalDependencies()` | Returns `{ smartlabel, DataStore }` |

---

## 3. Schema Field Options

```js
const schema = [
  { name: "FieldName", type: "dimension", subtype: "temporal", format: "%Y-%m-%d" },
  { name: "Sales", type: "measure", defAggFn: "sum" }
];
```

| Property | Type | Values | Description |
|----------|------|--------|-------------|
| `name` | string | — | Field name, must match data keys |
| `type` | string | `"dimension"`, `"measure"` | Required field type |
| `subtype` | string | `"temporal"`, `"categorical"`, `"binned"`, `"continuous"` | Optional subtype |
| `format` | string or function | `"%Y"`, `"%Y-%m-%d"`, `(val) => formatted` | Date format (temporal) or formatting function |
| `defAggFn` | string | `"sum"`, `"avg"`, `"min"`, `"max"`, `"count"`, `"std"`, `"first"`, `"last"` | Default aggregation |
| `displayName` | string | — | Custom display label for axes/tooltips |
| `binSize` | number | — | Bin size (for `"binned"` subtype) |

**Dimension subtypes**: `"categorical"` (default), `"temporal"`, `"binned"`
**Measure subtype**: `"continuous"`

### 3.1 Date Format Tokens

| Token | Purpose | Output |
|-------|---------|--------|
| `%H` | 24-hour hour | 00–23 |
| `%I` | 12-hour hour | 01–12 |
| `%p` / `%P` | AM/PM | AM/am |
| `%M` | Minutes | 00–59 |
| `%S` | Seconds | 00–59 |
| `%a` / `%A` | Day name | Mon / Monday |
| `%e` / `%d` | Day of month | 1 / 01 |
| `%b` / `%B` | Month name | Jan / January |
| `%m` | Month number | 01–12 |
| `%y` / `%Y` | Year | 90 / 1990 |

Auto-recognized: milliseconds since epoch, JavaScript Date objects.

---

## 4. DataModel — Static Methods

| Method | Description |
|--------|-------------|
| `DataModel.loadDataSync(data, schema, options?)` | Synchronous data loading → returns `{ data, schema }` |
| `DataModel.loadData(data, schema, callback)` | Async data loading (uses web workers) |
| `DataModel.AggregationFunctions` | `SUM`, `AVG`, `MIN`, `MAX`, `COUNT`, `STD`, `FIRST`, `LAST` |
| `DataModel.ComparisonOperators` | `EQUAL`, `NOT_EQUAL`, `GREATER_THAN`, `LESS_THAN`, `GREATER_THAN_EQUAL`, `LESS_THAN_EQUAL`, `IN`, `NIN`, `EQUAL_TO`, `NOT_EQUAL_TO` |
| `DataModel.FilteringModes` | `NORMAL`, `INVERSE`, `ALL` |
| `DataModel.LogicalOperators` | `AND`, `OR` |
| `DataModel.FieldType` | `DIMENSION`, `MEASURE` |
| `DataModel.FieldSubtype` | `TEMPORAL`, `BINNED`, `CATEGORICAL`, `CONTINUOUS` |
| `DataModel.SortOrder` | `ASC`, `DESC`, `NO_ORDER` |
| `DataModel.DateTimeFormatter` | DateTime formatting utilities |
| `DataModel.Invalid` | Invalid value class |
| `DataModel.setInvalids(vals)` | Set invalid value definitions |
| `DataModel.unsetInvalids(vals)` | Remove invalid value definitions |
| `DataModel.defaultInvalidValue(val?)` | Get/set default invalid value |
| `DataModel.defaultAggregation(fn?)` | Get/set default aggregation |
| `DataModel.sanitizeStringVals(val)` | String value sanitizer |

### Data Input Formats

`loadDataSync` accepts three data formats:

```js
// JSON array of objects
const formattedData = DataModel.loadDataSync(jsonArray, schema);

// CSV string
const formattedData = DataModel.loadDataSync(csvString, schema);

// 2D array (first row = headers)
const formattedData = DataModel.loadDataSync(arrayData, schema);
```

**loadDataSync options (third parameter):**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `dataFormat` | string | `"auto"` | Data format hint |
| `firstRowHeader` | boolean | `true` | First row contains headers (CSV/DSV) |
| `fieldSeparator` | string | `","` | Delimiter for CSV/DSV |

### Invalid Value Handling

Default invalid values: `null`, `undefined`, `NaN`, `"null"`, `"undefined"`, `"NaN"`, `"nil"`, `"na"`, `""`

```js
DataModel.setInvalids(['N/A', 'missing']);    // Add to invalid list
DataModel.unsetInvalids(['na']);              // Remove from invalid list
DataModel.defaultInvalidValue('—');          // Display text for invalids
```

---

## 5. DataModel — Instance Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `new DataModel(parsedData)` | Constructor | Creates from `loadDataSync` result |
| `.id()` | `→ string` | Returns instance ID |
| `.getData(options?)` | `→ { data, schema }` | Returns data |
| `.getDataMeta()` | `→ { rowCount, columnCount }` | Returns metadata |
| `.getSchema()` | `→ array` | Returns schema array |
| `.getField(name)` | `→ Field` | Returns field by name |
| `.getParent()` | `→ DataModel` | Returns parent |
| `.getChildren()` | `→ array` | Returns children |
| `.clone(saveChild?)` | `→ DataModel` | Clones the DataModel |
| `.select(predicate, mode?)` | `→ DataModel` | Filters rows |
| `.project(fields, mode?)` | `→ DataModel` | Selects columns |
| `.groupBy(fields, reducers?, config?)` | `→ DataModel` | Groups data |
| `.sort(config)` | `→ DataModel` | Sorts data |
| `.splitByRow(fields)` | `→ DataModel[]` | Splits by unique row values |
| `.calculateVariable(schema, deps, fn)` | `→ DataModel` | Creates derived field |
| `.propagate(criteria, payload?, opts?)` | — | Propagates selection events |
| `.onPropagation(callback)` | — | Listens for propagation events |
| `.dispose(removeChildren?)` | — | Disposes the DataModel |

All operations are **immutable** — they return new DataModel instances.

### Field Instance Methods

Retrieved via `dm.getField('FieldName')`:

| Method | Returns | Description |
|--------|---------|-------------|
| `name()` | string | Field name |
| `type()` | string | `"measure"` or `"dimension"` |
| `subtype()` | string | Field subcategory |
| `schema()` | object | Complete field schema |
| `displayName()` | string | Display label |
| `domain()` | array | Value range (continuous/temporal) or unique values (categorical) |
| `data()` | array | Raw field values |
| `formattedData(format)` | array | Formatted field values |
| `getRowsCount()` | number | Number of records |

### `.select()` Examples

```js
// Simple equality
const filtered = dm.select({
  field: 'Origin',
  value: 'USA',
  operator: DataModel.ComparisonOperators.EQUAL
});

// Compound conditions (AND/OR)
const filtered = dm.select({
  operator: DataModel.LogicalOperators.AND,
  conditions: [
    { field: 'Origin', value: 'Japan', operator: DataModel.ComparisonOperators.EQUAL },
    { field: 'Horsepower', value: 100, operator: DataModel.ComparisonOperators.GREATER_THAN }
  ]
});
```

### `.project()` Examples

```js
// Include only these fields
const projected = dm.project(['Name', 'Origin', 'Horsepower']);

// Exclude specific fields (INVERSE mode)
const projected = dm.project(['Name'], { mode: DataModel.FilteringModes.INVERSE });
```

### `.groupBy()` Example

```js
const grouped = dm.groupBy(
  ['Category'],
  [{ aggn: DataModel.AggregationFunctions.AVG, field: 'Sales' }]
);
```

### `.sort()` Example

```js
const sorted = dm.sort([
  ['Origin', 'desc'],       // sort by Origin descending
  ['Acceleration']           // then by Acceleration ascending (default)
]);
```

### `.calculateVariable()` Example

```js
const derived = dm.calculateVariable(
  { name: 'BinRange', type: 'dimension' },
  ['Value'],
  (value) => {
    const bin = Math.floor(value / 10) * 10;
    return `${bin}-${bin + 10}`;
  }
);
```

### Method Chaining

```js
const result = dm
  .select({ field: 'Year', value: '1980', operator: DataModel.ComparisonOperators.EQUAL })
  .project(['Origin', 'Horsepower', 'Weight_in_lbs'])
  .sort([['Horsepower', 'desc']]);
```

---

## 6. Canvas — Encoding Methods

All encoding methods are chainable getter/setters: call with argument to set (returns `this`), call without to get current value.

### Data & Dimensions

| Method | Type | Description |
|--------|------|-------------|
| `.data(dm)` | DataModel | Sets the data source |
| `.width(px)` | Number | Canvas width in pixels |
| `.height(px)` | Number | Canvas height in pixels |
| `.minUnitWidth(px)` | Number (default: 50) | Min width per visual unit |
| `.minUnitHeight(px)` | Number (default: 60) | Min height per visual unit |

### Controlling Row Height in Faceted Charts

Muze has an internal default minimum row height of ~60px per facet row. Setting `.height()` alone to a small value does not shrink rows — Muze adds a scrollbar instead.

Compact rows require **both settings used together**:

```js
canvas
  .height(180)        // Total canvas height — creates pressure to shrink
  .minUnitHeight(10)  // Lowers the internal floor from 60px to 10px
```

| Setting | Used Alone | Effect |
|---|---|---|
| `.height(smallValue)` | only | Muze hits 60px floor, adds scrollbar |
| `.minUnitHeight(smallValue)` | only | No effect — rows stay natural size |
| Both together | works | Muze divides canvas height across rows AND is permitted to go below 60px |

**Mental model:** `height` = pressure to shrink (total space), `minUnitHeight` = permission to shrink (removes the floor). Both are needed.

**Tuning guide** (approximate row height = canvas height / number of facet rows):

| Goal | Example |
|---|---|
| Very compact (~30px rows, 5 facets) | `.height(180).minUnitHeight(10)` |
| Compact (~40px rows, 5 facets) | `.height(220).minUnitHeight(20)` |
| Medium (~60px rows, 5 facets) | `.height(300).minUnitHeight(30)` |

Hiding the x-axis (`axes: { x: { show: false } }`) also helps since axis tick labels reserve vertical space within each row panel.

### Encoding Channels

| Method | Signature | Description |
|--------|-----------|-------------|
| `.rows([fields])` | Array of strings or shared variables | Y-axis fields; multiple dimensions → row facets |
| `.columns([fields])` | Array of strings or shared variables | X-axis fields; multiple dimensions → column facets |
| `.color(field)` | String or `{ field, as?, range?, step?, stops?, invalidValueColor? }` | Color encoding |
| `.opacity(field)` | String or `{ value: number or function }` | Opacity encoding |
| `.backgroundColor(field)` | String or Object | Background color encoding (text/pivot cells) |
| `.shape(field)` | String or Object | Shape encoding (point marks) |
| `.size(field)` | String or `{ field, as?, range?, stops?, domain? }` | Size encoding |
| `.detail([fields])` | Array of strings | Detail fields (split without visual encoding) |

**Color config object properties:**

| Property | Type | Description |
|----------|------|-------------|
| `field` | string | Color field name |
| `as` | string | `"discrete"` or `"continuous"` — force scale type |
| `range` | string[] or string | Color array or d3 color scheme name |
| `step` | boolean | Step legend (default: false) |
| `stops` | number | Number of legend stops when `step: true` (default: 5) |
| `domain` | — | **Do not use.** Unsupported in `.color()` — its mere presence silently disables `range` too (see references/hard-rules.md) |
| `invalidValueColor` | string | Color for invalid values (default: `"#ccc"`) |

**Size config object properties:**

| Property | Type | Description |
|----------|------|-------------|
| `field` | string | Size field name |
| `as` | string | `"discrete"` or `"continuous"` |
| `range` | number[] | `[min, max]` size range |
| `stops` | number | Number of size intervals |
| `domain` | number[] | Override default size domain |

### Layers, Config, Transform

| Method | Signature | Description |
|--------|-----------|-------------|
| `.layers([...])` | Array of layer definition objects | Mark definitions (see Section 8) |
| `.config({...})` | Object | Configuration (see Section 9) |
| `.transform({...})` | Object of named functions | Named data transforms |

### Title & Subtitle

| Method | Signature | Description |
|--------|-----------|-------------|
| `.title(text, config?)` | See options below | Chart title |
| `.subtitle(text, config?)` | See options below | Chart subtitle |

**Title options:**

| Property | Default | Values |
|----------|---------|--------|
| `position` | `"top"` | `"top"`, `"bottom"` |
| `align` | `"left"` | `"left"`, `"right"`, `"center"` |
| `padding` | 4 (title) / 16 (subtitle) | number |
| `maxLines` | 2 (subtitle only) | number |
| `className` | `"muze-title-container"` / `"muze-subtitle-container"` | string |

**Do NOT pass `muze.Operators.html` to `.title()` / `.subtitle()`** — the markup
renders verbatim as literal text (see references/hard-rules.md). Plain strings only.

### Mounting & Lifecycle

| Method | Description |
|--------|-------------|
| `.mount(selector)` | Renders to DOM element or CSS selector string |
| `.dispose()` | Destroys the canvas and all components |
| `.alias(name?)` | Gets/sets canvas name (used for cross-interaction) |

### Axes & Legend Access

| Method | Description |
|--------|-------------|
| `.xAxes()` | Returns 2D array of X axis instances |
| `.yAxes()` | Returns 2D array of Y axis instances |
| `.getRetinalAxes()` | Returns color/shape/size axis instances |
| `.legend()` | Returns legend |
| `.getLegendState()` | Returns legend selection state |

### Composition & Internal

| Method | Description |
|--------|-------------|
| `.composition()` | Returns `{ layout, legend, visualGroup }` |
| `.layout()` | Returns GridLayout |
| `.store()` | Returns reactive state store |
| `.firebolt()` | Gets/sets the GroupFireBolt (interaction dispatcher) |
| `.registry(components?)` | Gets/sets component registry |
| `.dependencies(deps?)` | Gets/sets dependencies |

### Pagination

| Method | Description |
|--------|-------------|
| `.goToNextPage()` | Navigate to next page |
| `.goToPreviousPage()` | Navigate to previous page |
| `.goToPage(n)` | Navigate to page N |
| `.goToLastPage()` | Navigate to last page |
| `.getPaginationMetaInfo()` | Returns `{ pageCount, currentPage, ... }` |

### Hierarchy (Faceted Charts)

| Method | Description |
|--------|-------------|
| `.setRowCollapseState(state)` | Set row collapse state |
| `.setColumnsCollapseState(state)` | Set column collapse state |
| `.collapseRowLevel(n)` / `.expandRowLevel(n)` | Collapse/expand row level |
| `.collapseAllRows()` / `.expandAllRows()` | Collapse/expand all rows |
| `.collapseColumnLevel(n)` / `.expandColumnLevel(n)` | Collapse/expand column level |
| `.collapseAllColumns()` / `.expandAllColumns()` | Collapse/expand all columns |

---

## 7. Canvas — Events

### Methods (Inherited EventEmitter Mixin)

| Method | Description |
|--------|-------------|
| `.on(event, handler)` | Subscribe to event |
| `.once(event, handler)` | Subscribe once |
| `.off(event, handler)` | Unsubscribe |
| `.addListener(event, handler)` | Add listener |
| `.removeListener(event, handler)` | Remove listener |
| `.removeAllListeners(event?)` | Remove all listeners |

### Event Names (Lifecycle Order)

| Event | Description |
|-------|-------------|
| `"initialized"` | Component initialized |
| `"beforeLayout"` | Before layout calculation |
| `"afterLayout"` | After layout calculation |
| `"beforeRendered"` | Before render |
| `"afterRendered"` | After chart drawn (before animation) |
| `"animationEnd"` | After animation complete |
| `"beforeDisposed"` | Before dispose |
| `"afterDisposed"` | After dispose |
| `"error"` | Error occurred |

### Usage

```js
canvas.once("afterRendered", () => {
  console.log("Chart rendered!");
});
```

---

## 8. Layer Definitions

Layers are configured via `canvas.layers(layersArray)`. Each element is a layer definition object.

**Layer rendering order:** Layers render in **array order** — later layers appear on top of earlier ones.

### Common Layer Definition Properties

| Property | Type | Description |
|----------|------|-------------|
| `mark` | string | **Required.** Mark type: `"bar"`, `"line"`, `"point"`, `"area"`, `"arc"`, `"text"`, `"tick"` |
| `name` | string | Optional layer name identifier |
| `className` | string | Optional CSS class |
| `encoding` | object | Visual encoding mappings (see per-layer details below) |
| `source` | string or function | Named transform reference or inline filter: `(dt) => dt.select({...})` |
| `transform` | object | `{ type: "identity"\|"group"\|"stack"\|"stack100percent" }` |
| `encodingTransform` | function | Post-render position adjustment: `(points, layer, deps) => points` |
| `calculateDomain` | boolean | If `false`, excludes layer from axis domain calculation |
| `interactive` | boolean | If `false`, disables interaction on this layer |
| `transition` | object | Animation config (see Transition below) |
| `interpolate` | string | Line/area curve type: `"linear"`, `"catmullRom"`, `"step"` |
| `connectNullData` | boolean | Line/area only. Bridges gaps in null data (default: `false`) |
| `nullDataLineStyle` | object | CSS-like style for null data bridge lines (line layer only) |
| `outline` | boolean or object | Enable outlines on point marks: `true` or `{ enable, fill, strokeColor, width }` |

### encodingTransform — Callback Internals

`encodingTransform` is a post-render hook that lets you modify the computed positions, styles, and text of every data point before they are drawn. It is essential for KPI cards, custom label positioning, and any advanced layout.

**Full signature:**
```js
encodingTransform: (points, layerInstance, deps) => points
```

#### Parameter 1: `points` (Array)

An array of point objects. Each point represents one rendered data mark. Mutate the points in place and return the array.

**Point object structure:**
```js
{
  // ── Position (most commonly modified) ──
  update: {
    x: number,        // Scaled x position (px)
    y: number,        // Scaled y position (px)
    width: number,    // Width (bars, ranges)
    height: number    // Height (bars, ranges)
  },

  // ── Visual styling ──
  style: {
    // Any SVG/CSS property, e.g.:
    'font-size': '24px',
    'font-weight': 'bold',
    'text-anchor': 'start',   // 'start', 'middle', 'end'
    'opacity': 0.8
  },

  // ── Text label ──
  // NOTE: there is NO usable `p.text` inside encodingTransform — every form of
  // `p.text.*` is undefined and crashes or silently no-ops (see
  // references/hard-rules.md). Position text layers via `p.update.x/y` like any
  // other mark.

  // ── Data references ──
  rowId: number,              // Unique row identifier
  data: object,               // WARNING: undefined inside encodingTransform — use layer.data().getData() + schema index (recipe 0.2)
  source: any,                // Source information
  meta: object,               // Metadata (lastInteraction, etc.)

  // ── Flags ──
  className: string,          // CSS class name on the mark
  size: number,               // Size encoding value
  isLabelThinned: boolean,    // true if label was removed due to collision
  isTotalLabel: boolean       // true for stack sum/total labels
}
```

**Common modifications:**
```js
encodingTransform: (points) => {
  points.forEach(p => {
    // Reposition marks
    p.update.x = 10;
    p.update.y += 20;

    // (No p.text — text layers are positioned via p.update.x/y as well.)

    // Apply SVG styles
    p.style['font-size'] = '32px';
    p.style['font-weight'] = 'bold';
    p.style['text-anchor'] = 'start';
    p.style.opacity = '0.8';
  });
  return points;
}
```

#### Parameter 2: `layerInstance` (Layer Object)

The live layer instance. Useful for reading the layer's dimensions, axes, data, and configuration.

**Most useful methods inside encodingTransform:**

| Method | Returns | Purpose |
|--------|---------|---------|
| `measurement()` | `{ width, height }` | Layer plotting area dimensions in pixels. Use this for responsive positioning instead of hardcoding pixel values. |
| `axes()` | object | The layer's axis instances (`x`, `y`, `color`, `size`, `shape`). Each axis has `.scale()` for the D3 scale, `.domain()`, etc. |
| `data()` | DataModel | The layer's DataModel instance |
| `config()` | object | Layer configuration object |
| `metaInf()` | object | Meta information (facets, sourceType) |
| `transformType()` | string | Current transform: `"identity"`, `"group"`, `"stack"`, `"stack100percent"` |
| `id()` | string | Layer unique identifier |
| `alias()` | string | Layer alias name |

**`measurement()` example — responsive positioning:**
```js
encodingTransform: (points, layer) => {
  const { width, height } = layer.measurement();
  points.forEach(p => {
    p.update.x = width * 0.05;    // 5% from left edge
    p.update.y = height * 0.5;    // Vertically centered
  });
  return points;
}
```

**`axes()` example — reading scale info:**
```js
encodingTransform: (points, layer) => {
  const yAxis = layer.axes().y;
  // Access the underlying D3 scale if needed
  return points;
}
```

#### Parameter 3: `deps` (Dependencies Object)

```js
{
  smartLabel: SmartLabelInstance
}
```

**`smartLabel` methods:**

| Method | Returns | Purpose |
|--------|---------|---------|
| `setStyle(styleObj)` | void | Set font style before measuring. Pass an object like `{ 'font-size': '24px', 'font-weight': 'bold' }` |
| `getOriSize(text)` | `{ width, height }` | Measure the pixel dimensions of a text string using the current style |

**`smartLabel` example — measure text before positioning:**
```js
encodingTransform: (points, layer, deps) => {
  const { smartLabel } = deps;
  smartLabel.setStyle({ 'font-size': '32px', 'font-weight': 'bold' });

  points.forEach(p => {
    const textSize = smartLabel.getOriSize(p.text?.text || '');
    // Use textSize.width / textSize.height to avoid overlaps
    p.update.x = 10;
    p.update.y = 40;
  });
  return points;
}
```

#### Full Example — KPI Card with Responsive Positioning

```js
{
  mark: 'text',
  encoding: {
    text: { field: 'DisplayValue' },
    color: { value: () => '#1a1a1a' },
    size: { value: () => 200 }
  },
  encodingTransform: (points, layer, deps) => {
    const { width, height } = layer.measurement();
    const { smartLabel } = deps;

    smartLabel.setStyle({ 'font-size': '48px', 'font-weight': 'bold' });

    points.forEach(p => {
      const textDims = smartLabel.getOriSize(p.text?.text || '');
      p.update.x = (width - textDims.width) / 2;  // Center using measurement
      p.update.y = 65;                              // Absolute px — choose based on layout
      p.style['font-size'] = '48px';
      p.style['font-weight'] = 'bold';
      p.style['text-anchor'] = 'start';
    });
    return points;
  }
}
```

#### Multi-Zone Layouts

To create layouts where text layers appear organized into visual zones (e.g., left panel, right panel, center panel), use `layer.measurement()` to know the available space and position layers at fixed pixel offsets:

**Strategy:**
1. Use `layer.measurement()` to get `{ width, height }` — useful for centering or dividing into zones
2. Set absolute pixel positions for x and y — choose values based on the layout
3. Use `'text-anchor': 'middle'` for centered content within a zone, `'start'` for left-aligned

```js
// Example: two-zone layout
// Left zone — status badge
encodingTransform: (points, layer) => {
  const { width, height } = layer.measurement();
  points.forEach(p => {
    p.update.x = 25;       // Fixed left offset
    p.update.y = 70;       // Fixed vertical position
    p.style = Object.assign(p.style || {}, {
      'text-anchor': 'middle'
    });
  });
  return points;
}

// Right zone — main value, left-aligned
encodingTransform: (points, layer) => {
  const { width, height } = layer.measurement();
  points.forEach(p => {
    p.update.x = 60;       // Fixed offset into right zone
    p.update.y = 70;       // Same vertical line as left zone
    p.style = Object.assign(p.style || {}, {
      'text-anchor': 'start'
    });
  });
  return points;
}
```

Each zone can have multiple layers stacked vertically (labels, values, indicators) by varying the y-proportion while keeping the same x-proportion.

### Transition Config (All Layers)

```js
{
  effect: "cubic",    // "linear", "cubic", "bounce", "elastic"
  duration: 1000,     // milliseconds
  disabled: false     // true to disable animation
}
```

### Transform Types

| Type | Description |
|------|-------------|
| `"identity"` | No transform (default) |
| `"group"` | Grouped side by side |
| `"stack"` | Stacked |
| `"stack100percent"` | 100% stacked |

Can also be placed inside `config` on the layer: `config: { transform: { type: 'stack' } }`

---

### 8.1 BarLayer (`mark: "bar"`)

**Config:**
- `innerPadding` (number, default: 0.1) — padding between grouped bars

**Encoding:**

| Channel | Type | Description |
|---------|------|-------------|
| `x` | string or `{ field, value? }` | X-coordinate field |
| `y` | string or `{ field, value? }` | Y-coordinate field |
| `x0` | string or `{ field, value? }` | Range start (horizontal). Width = x - x0 |
| `y0` | string or `{ field, value? }` | Range start (vertical). Height = y - y0 |
| `color` | `{ field?, value? }` | Color encoding |
| `size` | `{ field?, value? }` | Size encoding |
| `opacity` | `{ value: number or function }` | Opacity encoding |
| `text` | TextEncoding | Text label config |
| `detail` | `string[]` | Detail fields |

---

### 8.2 PointLayer (`mark: "point"`)

**Encoding:**

| Channel | Type | Description |
|---------|------|-------------|
| `x` | string or `{ field, value? }` | X-coordinate field |
| `y` | string or `{ field, value? }` | Y-coordinate field |
| `color` | `{ field?, value? }` | Color encoding |
| `size` | `{ field?, value? }` | Size encoding |
| `shape` | `{ field?, value? }` | Shape encoding |
| `opacity` | `{ value: number or function }` | Opacity encoding |
| `text` | TextEncoding | Text label config |
| `detail` | `string[]` | Detail fields |

**Point size reference** — Muze uses an area-based scale, so size values produce much larger dots than expected:

| Point size value | Rendered appearance |
|---|---|
| `0.05` | Small subtle marker on a line |
| `0.5` | Medium dot |
| `5` | Large dot |
| `50` | Enormous / fills the chart |

Default to `size: { value: () => 0.05 }` for decorative point markers. Only use larger values for bubble charts or when the user requests it.

---

### 8.3 LineLayer (`mark: "line"`)

**Config:**
- `connectNullData` (boolean, default: `false`) — bridges gaps in null data
- `nullDataLineStyle` (object, default: `{}`) — CSS-like styles for null bridges
- `interpolate` (string, default: `"linear"`) — `"linear"`, `"catmullRom"`, `"step"`

**Encoding:**

| Channel | Type | Description |
|---------|------|-------------|
| `x` | string or `{ field, value? }` | X-coordinate field |
| `y` | string or `{ field, value? }` | Y-coordinate field |
| `color` | `{ field?, value? }` | Color encoding |
| `size` | `{ field?, value? }` | Size (stroke width) encoding |
| `opacity` | `{ value: number or function }` | Opacity encoding |
| `text` | TextEncoding | Text label config |
| `detail` | `string[]` | Detail fields |

---

### 8.4 AreaLayer (`mark: "area"`)

**Config:**
- `connectNullData` (boolean, default: `false`)
- `interpolate` (string, default: `"linear"`) — `"linear"`, `"catmullRom"`, `"step"`

**Encoding:**

| Channel | Type | Description |
|---------|------|-------------|
| `x` | string or `{ field, value? }` | X-coordinate field |
| `y` | string or `{ field, value? }` | Y-coordinate field (top) |
| `y0` | string or `{ field, value? }` | Range start (bottom) for range areas |
| `color` | `{ field?, value? }` | Color encoding |
| `size` | `{ field?, value? }` | Size encoding |
| `opacity` | `{ value: number or function }` | Opacity encoding |
| `text` | TextEncoding | Text label config |
| `detail` | `string[]` | Detail fields |

---

### 8.5 TextLayer (`mark: "text"`)

**Encoding:**

| Channel | Type | Description |
|---------|------|-------------|
| `x` | string or `{ field, value? }` | X-coordinate field |
| `y` | string or `{ field, value? }` | Y-coordinate field |
| `color` | `{ field?, value? }` | Text color encoding |
| `text` | TextEncoding | **Key channel.** Text content and formatting |
| `backgroundColor` | `{ field?, value? }` | Background color for text cells (pivot tables) |
| `detail` | `string[]` | Detail fields |

**Note:** When only discrete fields (dimensions) are in rows and columns and canvas contains only a text layer, Muze renders a **pivot table** automatically.

---

### 8.6 TickLayer (`mark: "tick"`)

**Encoding:**

| Channel | Type | Description |
|---------|------|-------------|
| `x` | string or `{ field, value? }` | X-coordinate field |
| `y` | string or `{ field, value? }` | Y-coordinate field |
| `x0` | string or `{ field, value? }` | If present, draws a **horizontal** tick from x0 to x |
| `y0` | string or `{ field, value? }` | If present, draws a **vertical** tick from y0 to y |
| `color` | `{ field?, value? }` | Color encoding |
| `size` | `{ value? }` | Tick thickness |
| `opacity` | `{ value: number or function }` | Opacity encoding |

Use ticks for reference lines, box plot whiskers, and range endpoints.

---

### 8.7 ArcLayer (`mark: "arc"`)

**Encoding:**

| Channel | Type | Description |
|---------|------|-------------|
| `x` | string or `{ field }` | Derives center X position |
| `y` | string or `{ field }` | Derives center Y position |
| `angle` | `{ field?, value? }` | Angle in radians. Field data calculates per-arc angles. Default value: 360 |
| `radius` | `{ field?, value?, range? }` | Radius in pixels. `range` is a function: `(defaultRange) => [inner, outer]` |
| `radius0` | `{ value: function }` | Inner radius for donut/polar: `{ value: () => 10 }` |
| `color` | `{ field?, value? }` | Slice color |
| `text` | TextEncoding | Text label config |
| `detail` | `string[]` | Detail fields |

**Donut chart**: Use `radius.range` function to create the inner hole:
```js
radius: {
  range: function(defaultRange) {
    return [defaultRange[0] + 100, defaultRange[1]];  // inner hole = +100px
  }
}
```

---

### TextEncoding (Shared Across All Layers)

The `text` encoding channel is available on all layer types:

```js
{
  text: {
    field: "Sales",
    formatter: (d) => `$${d.rawValue.toLocaleString()}`,
    labelPlacement: {
      anchor: ["outside-top", "center"]  // ordered fallback positions
    }
  }
}
```

| Property | Type | Description |
|----------|------|-------------|
| `field` | string | Field name for text content |
| `formatter` | function | `(d) => string` — receives `{ rawValue, formattedValue }` |
| `labelPlacement` | object | Label positioning config |
| `labelPlacement.anchor` | string[] | Ordered list of positions to try |

**Supported anchor positions:**
`"outside-top"`, `"outside-right"`, `"outside-bottom"`, `"outside-left"`,
`"inside-top"`, `"inside-right"`, `"inside-bottom"`, `"inside-left"`, `"center"`

---

### EncodingValue Function

When an encoding channel uses `value`, it receives a function with this signature:

```js
value: (d, i, dataArr, layerInst) => result
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `d` | DataObject | Data object for the plot element |
| `i` | number | Index of the plot element |
| `dataArr` | array | Array of all data objects |
| `layerInst` | BaseLayer | Layer instance |

**DataObject Properties:**

| Property | Type | Present In |
|----------|------|------------|
| `x` | number | All layers |
| `y` | number | All layers |
| `width` | number | Bar only |
| `height` | number | Bar only |
| `angle` | number | Arc, tick, text |
| `color` | string | All layers |
| `shape` | string | Point only |
| `size` | number | Point only |

**Example — Conditional color:**

```js
layers: [{
  mark: "bar",
  encoding: {
    color: {
      value: (d) => d.y > 100 ? "green" : "red"
    }
  }
}]
```

**Example — Shift text position:**

```js
encoding: {
  x: {
    value: (d, i, dataArr, layerInst) => d.x + 10
  }
}
```

---

### InteractionConfig (Per-Layer)

Layers support per-layer interaction configuration for `highlight`, `select`, and `brush` behaviors:

```js
{
  mark: "bar",
  interaction: {
    highlight: {
      sideEffects: {
        "plot-highlighter": {
          enabled: true,
          rules: [{
            target: "exitSet",       // "entrySet" or "exitSet"
            style: {
              fill: "#cccccc",
              opacity: 0.3,
              stroke: "#000",
              "stroke-width": "1px",
              strokePosition: "inside"  // "inside", "center", "outside" (bar/point only)
            }
          }]
        }
      }
    }
  }
}
```

---

## 9. Canvas Config Schema

Full configuration via `canvas.config({...})`:

```js
{
  // Auto grouping
  autoGroupBy: { disabled: false },  // true to prevent auto-aggregation

  // Pagination
  pagination: {
    enabled: true,
    pageSize: 100,
    pageNumber: 1,
    unionAxisDomainPerPage: false
  },

  // Scrollbar
  scrollBar: {
    thickness: 10,        // pixels
    speed: 2,
    buttons: { show: true },
    vertical: {
      align: "right",     // "left" or "right"
      initialScrollPercent: 0
    },
    horizontal: {
      align: "bottom",    // "top" or "bottom"
      initialScrollPercent: 0
    }
  },

  // Legend
  legend: {
    show: true,
    position: "right",    // "top", "bottom", "left", "right"
    includeTotalDomain: true,
    preserveAxisDomainOnLegendToggle: false,
    color: {
      show: true,
      title: { text: "Legend Title" },
      border: 2,
      borderColor: "rgba(0,0,0,0)",
      padding: 2,
      item: {
        text: {
          orientation: "right",           // position of text relative to marker
          formatter: (value, index, dm, context) => value
        }
      },
      marker: {
        text: {
          formatter: (value, domain, dm) => value  // gradient legend markers
        }
      },
      fields: {
        "FieldName": {
          title: "Custom Title",
          position: "right",             // "top", "right", "bottom", "left"
          show: true,
          repeatRange: false,
          text: {
            formatter: (value, domain, dm) => value
          },
          ordering: {
            type: "alphabetical",        // "natural", "alphabetical", "field", "custom"
            direction: "asc",            // "asc", "desc"
            field: { name: "Revenue", aggregation: "sum" },
            custom: ["A", "B", "C"]
          },
          domainRangeMap: {
            "USA": "#ff0000",
            "Japan": "#0000ff"
          },
          range: ["#color1", "#color2", "#color3"]
        }
      }
    },
    shape: { /* same structure as color */ },
    size: { show: true },
    backgroundColor: {
      fields: {
        "FieldName": {
          splitBy: {
            field: "SplitField",
            values: {
              "Value1": { range: ["#light", "#dark"] },
              "Value2": { range: ["#light2", "#dark2"] }
            }
          }
        }
      }
    }
  },

  // Axes
  axes: {
    sharedAxisSeparator: ",",
    x: {
      show: true,
      name: "Custom Axis Label",
      showAxisName: true,
      showAxisLine: true,
      axisNamePadding: 7,               // padding between axis name and ticks
      showInnerTicks: true,             // show/hide tick marks
      compact: false,                   // compact axis labels
      tickFormat: (value, index, allTicks) => `$${value}`,
      numberOfTicks: 5,                 // hint, not exact
      interpolator: "linear",           // "linear", "log", "pow"
      padding: 0.2,                     // 0-1, categorical spacing
      nice: true,                       // optimize domain boundaries
      domain: [0, 100],                 // NOTE: silently ignored — do not rely on axis domain (see references/hard-rules.md)
      alignZero: true,                  // align zero line on dual-axis
      enableDirectSort: true,
      ordering: {                       // sort axis values
        type: "custom",                 // "natural", "alphabetical", "field", "custom"
        values: ["A", "B", "C"],        // for custom type
        direction: "asc",               // "asc" or "desc"
        field: { name: "Sales", aggregation: "sum" }  // for field type
      },
      tickInterval: {                   // time interval hints
        step: "Year",                   // field name
        multiplier: 10
      },
      bins: {                           // histogram bin display
        display: "startValue",
        position: "start"
      },
      labels: {
        rotation: 0                     // -180 to 180 degrees
      },
      fields: {                         // per-field overrides (same options as root)
        "FieldName": { showAxisName: false, ordering: { type: "custom", values: [...] } }
      }
    },
    y: {
      // Same options as x
    }
  },

  // Grid
  gridLines: {
    show: true,                          // show/hide all gridlines
    x: { show: false },                  // vertical gridlines (default: false)
    y: { show: true },                   // horizontal gridlines (default: true)
    color: "#efefef",
    showZeroLine: false,
    zeroLineColor: "#b6b6b6"
  },
  gridBands: {
    x: { show: false, color: ["#fff", "#f9f9f9"] },
    y: { show: false, color: ["#fff", "#fbfbfb"] }
  },

  // Border
  border: {
    style: "solid",                      // "solid", "dashed", "none"
    color: "#d6d6d6",
    width: 2,
    collapse: true,
    spacing: 0,
    showRowBorders: { top: true, bottom: true, left: true, right: true },
    showColBorders: { top: true, bottom: true, left: true, right: true },
    showValueBorders: { top: true, bottom: true, left: true, right: true }
  },

  // Headers & Facets
  showHeaders: false,
  rows: {
    totalMaxWidthRatio: 0.5,
    minWidth: 25,
    facets: {
      show: true,
      format: null,
      formatter: (dataInfo) => dataInfo.rawValue,
      className: "",
      labels: { align: "center" },       // "left", "right", "center"
      fields: {
        "FieldName": {
          show: true,
          labels: { align: "left" },
          className: "custom-facet",
          format: () => {},
          ordering: {
            type: "field",               // "natural", "alphabetical", "field", "custom", "nested"
            direction: "desc",
            field: { name: "Revenue", aggregation: "sum" },
            values: ["A", "B", "C"]      // for custom type
          }
        }
      },
      interaction: {
        collapse: { enabled: false, collapseAll: false, state: [] }
      }
    },
    headers: {
      show: null,
      position: "top",                   // "top" or "bottom"
      enableDirectSort: true,
      fields: { "FieldName": { show: false } }
    },
    totals: {
      subTotals: { enabled: false, text: "All" },
      grandTotals: { enabled: false, position: "end", text: "Grand Total" },
      data: { dataModel: null, totalString: "Total" },
      aggregations: {}
    }
  },
  columns: {
    // Same structure as rows, plus:
    headers: {
      show: true,
      position: "top",
      align: "center",                   // "left", "right", "center"
      padding: 4,
      maxLines: 1,
      separator: "/",
      formatter: (fields) => fields.join(' / '),
      fields: { "FieldName": { align: "right" } }
    },
    totals: {
      subTotals: { enabled: false, text: "All" },
      grandTotals: { enabled: false, position: "top", text: "Grand Total" }
    }
  },

  // Sort
  sort: {
    autoSort: { disabled: false }
  },

  // Interaction
  interaction: {
    tooltip: {
      // Do NOT set `mode` — 'consolidated' breaks ThoughtSpot interaction
      // propagation (see references/hard-rules.md); leave the default.
      fields: ["Field1", "Field2"],      // fields shown in tooltip
      formatter: (dataStore, config, context) => {
        // dataStore: wrapper over DataModel
        // config: { separator, classPrefix, margin }
        // context: { axes, detailFields, retinalFields }
        // Return array of row objects or HTML string via html operator
        return [{
          className: `${config.classPrefix}-tooltip-row`,
          data: [{ value: "Key", style: { "font-weight": "bold" } }, "Value"]
        }];
      },
      fieldFormatters: {
        "FieldName": (value) => formattedValue
      },
      includeDataFromAllLayers: false,
      freezeOnTooltipHover: false
    },
    highlight: { propagateDm: false, applyOnVisibleUnits: true },
    select: { propagateDm: true },
    brush: { propagateDm: true },
    contextMenu: { enabled: false },
    hyperlink: { clickModifier: "metaKey" }
  },

  // Virtual Scrolling
  virtualScrolling: { disabled: false },

  // Misc
  classPrefix: "muze",
  useExternalCSS: false,
  useUTC: false,
  minWidth: 100,
  minHeight: 100,
  uniformAxisDomains: false              // true for same domain across facets
}
```

---

## 10. Canvas-Level Transforms

Named data sources that layers reference via `source`:

```js
canvas.transform({
  averageLine: (dt) => dt.groupBy(
    [],
    [{ aggn: DataModel.AggregationFunctions.AVG, field: "Sales" }]
  ),
  lastPoint: (dt) => dt.select({
    field: "Date",
    value: maxDate,
    operator: DataModel.ComparisonOperators.EQUAL
  })
});

// Reference in layers:
canvas.layers([
  { mark: "bar" },
  { mark: "tick", source: "averageLine", calculateDomain: false, interactive: false },
  { mark: "point", source: "lastPoint" }
]);
```

The transform function receives a **DataStore** (wrapper over DataModel) and must return a DataStore.

Layers can also use inline source functions:

```js
{ mark: "point", source: (dt) => dt.select({ field: "Type", value: "Special", operator: DataModel.ComparisonOperators.EQUAL }) }
```

---

## 11. Operators

### `muze.Operators.html`

Tagged template for HTML strings. **Never pass it to `.title()` / `.subtitle()`** —
the markup renders verbatim there (see references/hard-rules.md). Its only safe use is
setting SVG text content in KPI text layers via `encodingTransform`.

### `muze.Operators.share`

Creates a shared axis variable from multiple measure fields:

```js
const { share } = muze.Operators;
const sharedField = share("MinTemp", "MaxTemp", "AvgTemp");

canvas
  .rows([sharedField])
  .columns(["Date"])
  .layers([
    { mark: "tick", encoding: { y: "MaxTemp", y0: "MinTemp" } },
    { mark: "line", encoding: { y: "AvgTemp" } }
  ]);
```

Use for: range plots, box plots, waterfall charts, any chart needing multiple measures on one axis.

---

## 12. layerFactory — Composite Layers

Register custom composite marks from atomic layers:

```js
const layerFactory = muze.layerFactory;

layerFactory.composeLayers('tickPoint', [
  {
    name: "errorTick",
    mark: "tick",
    encoding: {
      y0: "tickPoint.encoding.lowerLimit",  // reference parent encoding
      y: "tickPoint.encoding.upperLimit",
      x: "tickPoint.encoding.x",
      color: { value: () => '#4c8579' }
    },
    transform: { type: "identity" }
  },
  {
    name: "errorPoint",
    mark: "point",
    encoding: {
      y: "tickPoint.encoding.center",
      x: "tickPoint.encoding.x",
      color: { value: () => 'red' }
    },
    transform: { type: "identity" }
  }
]);

// Usage:
canvas.layers([{
  mark: "tickPoint",
  encoding: {
    x: "Category",
    lowerLimit: "Low",
    upperLimit: "High",
    center: "Median"
  }
}]);
```

Encoding references use dot notation: `"compositeName.encoding.fieldAlias"`

### `composeLayers(name, definition)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | string | Name for the composite mark type |
| `definition` | array | Array of sub-layer definitions |

Returns: `layerFactory` (for chaining)

---

## 13. ActionModel — Cross-Chart Interaction

```js
// Basic cross-interactivity (tooltips + highlighting)
muze.ActionModel.for(canvas1, canvas2).enableCrossInteractivity();

// With explicit filtering config
muze.ActionModel.for(barChart, pieChart).enableCrossInteractivity({
  [barChart.alias()]: {
    select: {
      target: {
        [pieChart.alias()]: {
          filter: {
            sideEffects: ["filter"]
          }
        }
      }
    }
  }
});
```

### ActionModel Methods

```js
const ActionModel = muze.ActionModel;

ActionModel
  .for(canvas)
  .registerSideEffects(customSideEffect)
  .registerBehaviouralActions(customBehaviour)
  .registerPhysicalBehaviouralMap({
    click: ['select'],
    hover: ['highlight']
  });
```

### Key Classes

| Class | Description |
|-------|-------------|
| `GenericBehaviour` | Abstract base class for behaviors |
| `VolatileBehaviour` | Non-persistent behaviors (e.g., highlight) |
| `PersistentBehaviour` | Persistent behaviors (e.g., select) |
| `GenericSideEffect` | Base class for side effects |
| `SpawnableSideEffect` | Adds new chart elements/layers |
| `SurrogateSideEffect` | Modifies existing element styles |

### Custom Side Effect Implementation

```js
// Static - must implement
static formalName() { return 'my-effect'; }
static target() { return 'visual-unit'; }  // 'visual-unit' | 'visual-group' | 'all'

// Instance - implement the effect
apply(entryExitSet, payload, options) { /* ... */ }
```

### Drawing Context

```js
const ctx = sideEffect.drawingContext();
// ctx.svgContainer, ctx.width, ctx.height, ctx.sideEffectGroup
```

### Firebolt (Interaction Dispatcher)

```js
const firebolt = canvas.firebolt();

// Dispatch a brush selection
firebolt.dispatchBehaviour('brush', {
  criteria: { range: { Sales: [100, 500] } }
});

// Dispatch a click selection
firebolt.dispatchBehaviour('select', {
  criteria: { dimensions: { Category: ['Electronics'] } },
  sideEffects: ['tooltip']
});
```

**Built-in Behavior Types:**

| Behavior | Type | Description |
|----------|------|-------------|
| `"highlight"` | Volatile | Non-persistent, on hover |
| `"select"` | Persistent | Click to select, maintains state |
| `"brush"` | Persistent | Range/lasso selection |

---

## 14. Faceted Charts

Multiple dimensions in `.rows()` or `.columns()` create faceted small multiples:

```js
canvas
  .rows(["Category", "Sales"])    // Category = row facet, Sales = y-axis
  .columns(["Region", "Segment"]) // Region + Segment = column facets
```

### Rows/Columns Array Patterns — Stacked Panels vs Dual Axis vs Shared Axis

**Pattern 1 — Stacked Panels (flat array, separate measures):**
Each measure gets its own independent panel with its own y-axis and scale. Each layer maps to its panel via `encoding.y`. Layers whose `y` field doesn't match a panel are simply not drawn there.

```js
canvas
  .rows(['MeasureA', 'MeasureB'])
  .columns(['Dimension'])
  .layers([
    { mark: 'bar', encoding: { y: 'MeasureA' } },
    { mark: 'line', encoding: { y: 'MeasureB' } }
  ])
// Result: Two vertically stacked panels — bar in top, line in bottom
```

**Pattern 2 — Dual Y-Axis (nested arrays / tuple):**
Each measure wrapped in its own inner array creates left and right y-axes sharing a single panel. Both layers are overlaid in the same panel.

```js
canvas
  .rows([['MeasureA'], ['MeasureB']])
  .columns(['Dimension'])
  .layers([
    { mark: 'bar', encoding: { y: 'MeasureA' } },
    { mark: 'line', encoding: { y: 'MeasureB' } }
  ])
// Result: One panel, bar uses left y-axis, line uses right y-axis
```

**Pattern 3 — Shared Axis (`muze.Operators.share`):**
Multiple measures plotted on the same axis with a unified scale. Used for range marks (y + y0), box plots, candlesticks.

```js
canvas
  .rows([share('MeasureA', 'MeasureB')])
  .columns(['Dimension'])
  .layers([
    { mark: 'tick', encoding: { y: 'MeasureA', y0: 'MeasureB' } }
  ])
// Result: One panel, single y-axis with scale spanning both measures
```

### Axis Positioning

```js
// Y-axis on right side:
canvas.rows([[], ["Sales"]])

// Y-axis on left side (default):
canvas.rows([["Sales"], []])
```

### Field-as Syntax

Treat a dimension field as continuous (or vice versa):

```js
canvas.columns([{ field: "weight_bin", as: "continuous" }])
canvas.rows([{ field: "Year", as: "discrete" }])
```

---

## 15. Formatters

```js
const { NumberFormatter, DateFormatter, SplitByFormatter } = viz.formatters;   // BYOC: exposed on the viz global
```

### NumberFormatter

```js
const fmt = new NumberFormatter('currency', {
  currency: 'USD',
  decimalDigits: 0
});
fmt.format(1234.5);  // "$1,235"
```

Styles: `"currency"`, `"decimal"`, `"percent"`

### DateFormatter

```js
const fmt = new DateFormatter({ format: 'MMM dd, yyyy' });
```

### SplitByFormatter

Applies different formatters based on a split-by field:

```js
const fmt = new SplitByFormatter({
  splitByField: 'Category',
  values: {
    'Revenue': new NumberFormatter('currency', { currency: 'USD' }),
    'Discount': new NumberFormatter('percent', { decimalDigits: 1 })
  }
});
```

---

## 16. Global Options

> **Muze Studio only** — `setGlobalOptions` is not available in BYOC; do not use it
> in chart.js.

```js
setGlobalOptions({
  autoEmitRenderCompletedEvent: true,   // auto-emit render complete event
  autoResizeCanvas: true,               // auto-resize to container
  autoHandledXLSXDownload: true,        // handle XLSX download
  useRAF: false,                        // use requestAnimationFrame
  displayAs: {
    invalidValue: '{Null}',             // display text for invalid values
    columns: { 'Field': 'Display Name' }
  }
});
```

---

## 17. CSS Classes for Styling

| Element | Class | Common CSS Properties |
|---------|-------|----------------------|
| Title | `.muze-title-cell` | `color`, `font-weight`, `font-family` |
| Subtitle | `.muze-subtitle-cell` | `color`, `font-weight`, `font-family` |
| Axis labels | `.muze-ticks` | `fill`, `font-family` |
| Axis name | `.muze-axis-name` | `fill`, `font-family` |
| Tick lines | `.muze-tick-lines` | `stroke` |
| Tooltip box | `.muze-tooltip-box` | `background`, `color`, `padding` |
| Tooltip value | `.muze-tooltip-value` | `color` |
| Tooltip key | `.muze-tooltip-key` | `color` |
| Tooltip selected row | `.muze-tooltip-selected-row` | `background` |
| Legend title | `.muze-legend-title-text` | `color` |
| Chart container | `.muze-group-container` | `background-color` |
| Bar elements | `.muze-layer-bar` | `fill`, `stroke` |
| Line elements | `.muze-layer-line` | `stroke`, `stroke-width` |
| Point elements | `.muze-layer-point` | `fill`, `stroke` |
| Area elements | `.muze-layer-area` | `fill`, `opacity` |
| Tick elements | `.muze-layer-tick` | `stroke` |
| Text elements | `.muze-layer-text` | `fill`, `font-size` |
| Arc elements | `.muze-layer-arc` | `fill`, `stroke` |

---

## 18. Events API

In BYOC these live on the `viz` global. Call `viz.events.emitRenderCompletedEvent()`
**live on both the success and `catch` paths** (see references/hard-rules.md).

```js
// Emit render completed event
viz.events.emitRenderCompletedEvent();

// Handle XLSX download
viz.events.handleXLSXDownloadEvent((payload) => {
  console.log('Download requested:', payload.answerTitle);
  return { isDownloadHandled: true };
});
```

---

## 19. Utility Functions

```js
// Check if a value is invalid in Muze
isMuzeInvalidValue(value);  // returns boolean

// Create a new invalid value
newMuzeInvalidValue(value);
```

---

## 20. Automatic Chart Type Selection

Muze automatically selects chart types based on field types:

| rows (y) | columns (x) | color | Result |
|----------|-------------|-------|--------|
| measure | dimension (categorical) | — | Vertical bars |
| measure | dimension (categorical) | measure (continuous) | Colored bars (gradient) |
| measure | dimension (categorical) | dimension | Stacked bars |
| dimension | measure | — | Horizontal bars |
| measure | dimension (temporal) | — | Line chart |
| measure | dimension (temporal) | dimension | Multi-line chart |
| measure | measure | — | Scatter plot |
| dimension | dimension | — | Heatmap |

Use `.layers([{ mark: "..." }])` to override automatic selection.

Use `.transform({ type: "group" })` within a layer to get grouped (side-by-side) instead of stacked.

---

## 21. Enums Reference

| Enum | Access | Values |
|------|--------|--------|
| FilteringModes | `DataModel.FilteringMode` | `NORMAL`, `INVERSE`, `ALL` |
| AggregationFunctions | `DataModel.AggregationFunctions` | `SUM`, `AVG`, `MAX`, `MIN`, `COUNT`, `STD`, `FIRST`, `LAST` |
| ComparisonOperators | `DataModel.ComparisonOperators` | `EQUAL`, `NOT_EQUAL`, `GREATER_THAN`, `LESS_THAN`, `GREATER_THAN_EQUAL`, `LESS_THAN_EQUAL`, `IN`, `NIN` |
| LogicalOperators | `DataModel.LogicalOperators` | `AND`, `OR` |
| FieldType | `DataModel.FieldType` | `DIMENSION`, `MEASURE` |
| FieldSubtype | `DataModel.FieldSubType` | `CATEGORICAL`, `CONTINUOUS`, `TEMPORAL` |
| SortOrder | `DataModel.SortOrder` | `ASC`, `DESC`, `NO_ORDER` |
