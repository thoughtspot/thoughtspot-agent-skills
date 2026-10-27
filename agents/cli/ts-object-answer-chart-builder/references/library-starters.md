# Starters and traps by library (learned building the Amuzing chart samples Liveboard)

Library and Liveboard charts start from the shared core (`library/_shared/core.js`): `AZ.boot`, `AZ.col`, `AZ.tip`,
`AZ.loadScript`, `AZ.liveData`, formatters, the family theme. A standalone MayaCharts tile needs none of it (see its
section: 3 lines through `maya.host.thoughtspot`). What follows is what each library needs in a real ThoughtSpot tile. All of it was verified in a cluster
screenshot unless marked otherwise.

## Any library

- Load a CDN library with `AZ.loadScript([primary, fallback], () => !!window.Lib, 8000)`. It injects at once
  when no matching `<script src>` is in the document and waits up to 3 s when one is. A plain
  `<script src>` in `chart.html` is allowed by `liveboard-pack`; an inline script body containing `</script` is not.
- `fetch()` is blocked inside a tile. Inline data and maps.
- No backtick, no `${`, ASCII only (a literal non-ASCII character such as an arrow corrupts the checksum in
  transit). Use `String.fromCharCode(8595)` for an arrow if you must; a `\\u0001` escape in source is fine.
- Test at 280px wide as well as the nominal size.

## MayaCharts (mayacharts, `maya.core.global.js` / `maya.global.js`)

Verified in the preview (headless Chromium, 0.18.1) on the starter below, `examples/maya-was-bars/` and the
MayaCharts library charts (48 of 58 as of 2026-10-14): render, every data mode, 130 to 1400 px tiles, hover, click, drill, sweep. Not yet
screenshotted on a cluster: say "verified in preview" until it has been.

- **Version: the latest release, pinned.** Take it from the doctor's `mayacharts:` line (it asks jsDelivr, then npm)
  and write it into the one `MAYA` URL constant. Never an unpinned URL: a saved tile would change under the user on
  the next release. Never a version from memory: the library ships often. If the line says `unknown`, ask.
- **Which file.** `maya.core.global.js` holds the element, the 12 core types (bar line area scatter heatmap
  waterfall kpi dumbbell ridgeline beeswarm parallel table) and `maya.host`. A module type (treemap, sunburst,
  marimekko, waffle, sankey, chord, radial, gauge, hexmap, boxplot, funnel, weave, units, orbit, constellation)
  needs `maya.global.js`, which has everything in one file; one script keeps the loader to one line.
- **The whole tile is 3 lines: the URL, the adapter call, the loader.** `maya.host.thoughtspot(viz, spec)` reads the
  search, unwraps object cells, matches fields written as a RegExp or a case-insensitive name against the columns
  ThoughtSpot returns, finds or creates `#chart`, renders, and calls `emitRenderCompletedEvent` once the chart has
  settled, errors included. Verified on live, absent, wrapped, empty and no-host data, an empty HTML tab, a CDN that
  fails, a column that is not there (MayaCharts paints the error, listing the columns it found) and 130 to 1400 px:
  ```js
  const MAYA = 'https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js';
  const SRI = 'sha384-KZQbG8OHSEU86UWT5Pp3LATC64UAhHxwg1UMKN/lZtsu02CeDifcSVWCewQO2h/6'; // the doctor prints it beside the version
  const go = () => maya.host.thoughtspot(viz, { type: 'bar', x: 'Item Type', y: 'Total Sales' });
  if (window.maya?.host) go(); else { const s = document.querySelector('script[src="' + MAYA + '"]') ?? document.head.appendChild(Object.assign(document.createElement('script'), { src: MAYA, integrity: SRI, crossOrigin: 'anonymous' })); s.addEventListener('load', go); s.addEventListener('error', () => { (document.getElementById('chart') ?? document.body).textContent = 'MayaCharts could not load from ' + MAYA; viz?.events?.emitRenderCompletedEvent?.(); }); }
  ```
  `chart.html` is `<maya-chart id="chart"></maya-chart>` (plus the Geist link); `chart.css` is
  `html, body { height: 100%; margin: 0; } #chart { display: block; height: 100%; --maya-font: Geist, system-ui, sans-serif; --maya-bg: transparent; --maya-tooltip-bg: light-dark(#fff, #2b2f36); --maya-accent: light-dark(#1E1E24, #E6EDF3); }`
  (the theme lives here, see Theme below). 0.18.1 signals render-complete on the first draw, so a cold load no
  longer shows "Something went wrong" on a tile.
  The adapter's spec takes every option except `data`. **Write fields as plain column names**: `x: 'Item Type',
  y: 'Total Sales'`. The adapter matches a name to the search's columns case-insensitively and exactly (not as a
  substring: `'sales'` does not find `Total Sales`), so take the real names from the search's columns (`searchdata`,
  Step 3 of SKILL.md). A name that matches nothing is an `unknown-field` error listing the columns the host sent.
  The fields are `x`, `y`, `series`, `path`, `size`, `name`, `frame`, `y2`, `was.by`, `tooltip.fields`. A RegExp
  (`y: /sales/i`) is the fallback for one tile that must work on clusters naming the column differently.
- **When the spec needs a field the search does not return** (a family derived from item type, a per-row price, a
  top-N roll-up), keep the tile lean: hand the adapter a wrapped `viz` that adds the column, and name that column in the
  spec. No core, no `AZ`. `library/what-money-sankey` is the reference (8 lines of JS, family level derived):
  ```js
  const withFamily = (d, i = d.schema.findIndex((c) => /item/i.test(c.name))) => ({ schema: [...d.schema, { name: 'Family' }], data: d.data.map((r) => [...r, FAM[r[i]?.value?.() ?? r[i]?.value ?? r[i]]]) });
  const go = () => maya.host.thoughtspot({ events: viz?.events, getDataFromSearchQuery: () => ({ getData: () => { const d = viz?.getDataFromSearchQuery?.()?.getData(); return d && withFamily(d); } }) }, { type: 'sankey', path: ['region', 'Family', 'item type'], y: 'Total sales', drill: true });
  ```
  The adapter leaves a name it cannot find among the columns as written, so `'Family'` in `path` resolves to the added
  column. Keep the `viz?.` chains: they keep the tile drawing with no search and no host. `viz.events` is the only other
  thing the adapter reads. Charts that still carry the shared core (`AZ.maya(spec)`) are legacy for MayaCharts; do not
  start a new one that way. The contract is `library-contract.md` section 1a.
- **Theme in `chart.css`, not in JS (0.18.0).** Every theme token is a custom property on the chart element: kebab
  case with a `--maya-` prefix (`fgMuted` is `--maya-fg-muted`, `series3` is `--maya-series-3`, `numeric: 'tabular'`
  is `--maya-numeric: tabular-nums`). A library chart's `core.css` sets the house style on `maya-chart#chart`
  (Geist, ink, 2px radius, 14px title); a tile adds only the tokens that differ, on the same selector in its own
  `chart.css`: `maya-chart#chart { --maya-accent: #6A7891; --maya-series-1: #6A7891; --maya-good: #1F7A4D; }`.
  **The selector must be `#chart` itself**: on `:root`, `html`, `body` or any ancestor the value is ignored, because
  the chart sets its own defaults on the element. `spec.theme` still works and beats the CSS. Keep these in
  `spec.theme`, since they also size the layout or make a ramp diverging: `axisSize`, `labelSize`, `heroSize`,
  `cellGap`, `rampMid`, `rampMidValue`; so does any value computed from the data (a `fontSize` that depends on the
  number of measures). **Works on both ThoughtSpot themes**: no white background (none on `html`, `body` or `--maya-bg`: set `--maya-bg: transparent`), no hard-coded `--maya-fg` / `--maya-fg-muted`, and the tooltip needs `--maya-tooltip-bg: light-dark(#fff, #2b2f36)` because a transparent chart has no backdrop to mix it from. Any ink-coloured token or `colors` entry is `light-dark(#1E1E24, #E6EDF3)` (a spec `colors` map accepts `light-dark()` too). **The scheme comes from the host's text colour, not the OS** (`prefers-color-scheme` only mirrors the OS and made pale text on a white tile): the first line of `chart.js` is `document.getElementById('chart')?.style.setProperty('color-scheme', (([r, g, b]) => r * .299 + g * .587 + b * .114 > 140)(getComputedStyle(document.body).color.match(/\d+/g)) ? 'dark' : 'light');` and the CSS has no `color-scheme`. A tile also has **no `title`** (the Liveboard tile shows one); a `subtitle` is fine. Verified in a browser with the OS and the host themes set independently; whether ThoughtSpot's own dark theme changes the frame's text colour is not verified on a cluster.
  A `colors` map key now beats the series tokens (0.17.0), so both can stay.
- **Colours by meaning.** `colors` takes a map: by series value, by `path[0]` on treemap and sunburst, by node name on
  sankey and chord (links and inner levels inherit), by category on waffle. Slots are fixed from all rows, so hues
  hold through drill. Family hues: `colors: AZ.T.family`. Region is never a hue.
- **Spec is JSON only.** Number formats: `format: { 'Total Sales': { style: 'currency', currency: 'USD', notation:
  'compact', maximumFractionDigits: 1 } }`; Intl options must be keyed by field, and take `prefix` / `suffix`.
  Display names: `titles`. Epoch-ms dates work with `xType: 'time'`; a `[date].yearly` column formats with `'year'`.
- **Customisation that needs no code:**
  - `title` and `subtitle` with data tokens: `'{max.x} leads with {max.y}'` ({max.x} {max.y} {min.x} {min.y}
    {first.x} {first.y} {last.x} {last.y} {total} {mean}), formatted by `format`. With no rows the tokens are dropped
    (0.17.0) and the empty state shows alone.
  - `rules`: a value line (`100`, `'mean'`, `{ y, label }`), a category line (`{ x, label }`), a band
    (`{ band: [lo, hi] }`), and on scatter a diagonal (`{ slope: 'mean' }` is sum(y) / sum(x), through the origin).
  - `annotate: ['max', 'last', { x: 'CA', text: 'Largest store' }]` labels marks picked from the data.
  - `dash: ['2024']` draws that series dashed (line, area). `tooltip: { fields: [...] }` adds rows.
  - `yScale: 'log'` (line, scatter), `xScale: 'log'` (scatter). `legend: 'top' | 'bottom' | 'right'`.
  - `was: { by: /year/i }`: a ghost of the previous period straight from long rows (one per item and period).
  - `aggregate: { ratio: ['Total Sales', 'Total Quantity Purchased'] }` with `y: 'Price'` rolls a ratio up as sum over
    sum in every category, drill level, Other bucket and `'mean'` rule. Never `mean` of a ratio column.
- **Drill-down is built in.** `path: [outer, ..., inner]` replaces `x`, and `drill: true` turns a click or Enter into an
  animated zoom with a breadcrumb (Back > West > CA); Escape, Back or a click on empty space go up.
  - Types: treemap, sunburst, sankey, chord; bar, line, area, dumbbell, table and marimekko with `path`; heatmap with
    `path` on its rows. Sankey starts at the first column and continues one column at a time.
  - `depth: 2` on a treemap draws parents with their children inside; a click drills into the parent under the
    pointer. `minAngle` (sunburst) controls folding thin slices into a grey "Other (n)" (`0` folds nothing).
  - With `select` too, a click selects (cross-filter) and double-click, Shift+Enter or the pinned tooltip's
    "Drill into" drills. At the deepest level the drill gesture fires `maya-drill-leaf { path }`, for drill-through.
  - `el.view = { drill: ['West'] }` restores a level; `maya-view` reports every change. A data update keeps the
    level; a filter that removes the branch falls back to the root.
  - A date path (`path: ['year', 'month']` with ISO months) drills onto a real time axis. The drill only filters rows
    the tile has, so the search needs every level.
- **0.16.0 traps that 0.17.0 fixed** (every issue we filed, BbekShr/mayacharts#76 and #78 to #93, is closed): a
  series token beat a `colors` map, `was` ghosts were clipped and missing from the tooltip, labels kept dark ink on
  dark fills, `text.noData` did not wrap, raw tokens printed with no rows, tokens were not filled on scatter,
  `annotate: []` and `colorBy: null` threw, a slope rule showed no value, a sankey lost its colours after a drill, and
  `aggregate: { ratio }` could not go with a `y` array. The library charts still carry some 0.16.0 workarounds
  (derived fields, pivots, hand-built legends); each is worth retiring when the chart is next touched, using the new
  options: `facet`, `params`, `frameControl`, `list`, table `page` / `filter` / `expand`, `toggle`, named themes. The
  workarounds that remain true: `{total}` sums every series while `{max.y}` and `{last.y}` take one unless you add a
  series selector (`{max.y:2025}`, 0.17.0); in a tile under ~200 x 130 a title plus subtitle crowd the plot.
- **Small tiles.** The chart fills its container's height and draws a compact frame under about 160 px; dense bars
  roll into Other on their own; no `min-height` or `limit` arithmetic is needed.
- **Shadow DOM**: the marks live in the element's open shadow root (`data-maya="mark"`, `data-x`). `probe.mjs` and
  `snap.mjs`'s `svg-fit` look inside it, and so do `--click-sel` / `--hover-sel`; your own `--eval` / `--after`
  expressions reach in themselves (`document.getElementById('chart').shadowRoot`, `.maya-crumbs` for the breadcrumb).
- Too many marks: bars roll up into "Other" past 10,000 marks and say so; waterfall, dumbbell and the module charts
  throw `too-many-marks`. Keep searches aggregated, or set `limit`. Hierarchy and flow types reject `y <= 0`.
- Errors carry a code and a link (`https://bbekshr.github.io/mayacharts/errors.html#<code>`): read that page before
  guessing. The ceilings MayaCharts keeps on purpose are in its NON-FEATURES.md.

## ECharts (echarts@5.6.0)

Pinned build: `{ src: 'https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js', integrity: 'sha384-pPi0zxBAoDu6+JXW/C68UZLvBUUtU+7zonhif43rqj7pxsGyqyqzcian2Rj37Rss' }`.

- Render with `renderer: 'svg'`, set `animation: false`, and pass an explicit `width` and `height`
  (`echarts.init(el, null, { renderer: 'svg', width: w, height: h })`). Without them the first paint can be a
  fraction of the container, and a screenshot taken after render-complete catches a half-drawn chart.
- Fill any header text **before** you measure the plot area, then call `chart.resize({ width, height })`.
- zrender pointer events do not fire on empty areas. Attach native listeners to the container, and convert
  with `chart.convertFromPixel({ xAxisIndex: 0 }, px)` using a scalar.
- Sankey and sunburst labels collide first: drop or shorten the small ones and say so in the sub line.

## D3 (d3@7.9.0)

Pinned build: `{ src: 'https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js', integrity: 'sha384-CjloA8y00+1SDAUkjs099PVfnY2KmDC2BZnws9kh8D/lX1s46w6EPhpXdqMfjK6i' }`.

- Use it for scales, layouts (`d3.stack`, `d3.area`) and transitions; write the DOM yourself where a
  library would fight the shared tooltip.
- Geography: do not fetch topology. `library/_shared/us-states.js` holds all 51 states as pre-projected
  Albers paths (viewBox 0 0 975 610) with centroids. Paste the const into the chart body and draw plain SVG.

## Chart.js (chart.js@4.6.1)

Loaded from a CDN, so it cannot be previewed where the doctor reports `cdn: blocked`; verify it on a tile. Load `{ src: 'https://cdn.jsdelivr.net/npm/chart.js@4.6.1/dist/chart.umd.min.js', integrity: 'sha384-Emf5ZVIUiarAdhkgtqK+5/Z5qIvM6QoVrS+qAVtfyZVuD5lIHrac0me485+Antp0' }`
through `AZ.loadScript` (bounded, with a fallback host); reference `window.Chart` after it resolves. Plugins load
the same way afterwards and register on `window.Chart` by themselves.

- `responsive: true, maintainAspectRatio: false` inside a flex parent (`flex: 1 1 0; min-height: 0`). That option
  listens to `window.resize` only, so the core's `ResizeObserver` on `#chart` is still what re-fits a tile. Keep
  the instance in a module-scope variable and `chart?.destroy()` before re-creating on a redraw.
- **Plugin CDN URLs need the explicit `/dist/<file>.min.js` path.** `.../chartjs-plugin-datalabels@2` alone
  returns 404 on jsdelivr, the plugin never registers, and the chart silently renders without labels:
  `https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js`
  (`sha384-y49Zu59jZHJL/PLKgZPv3k2WI9c0Yp3pWB76V8OBVCb0QBKS8l4Ff3YslzHVX76Y`),
  `https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0/dist/chartjs-plugin-annotation.min.js`
  (`sha384-3N9GHhCtN3CQef6tNfqgZlv7sQLYIkcChN+uaTZ7xVdzKYp/SjBNPxa92+hM7EAY`),
  `https://cdn.jsdelivr.net/npm/chartjs-chart-sankey@0.12.1/dist/chartjs-chart-sankey.min.js`
  (`sha384-R5LF8opcxOg7Ibk9Tcz2v5qJ/2FKaqqJfvGRDQtj5e7gQ4AzhwYCB61EOu/N6qoh`).
- Bar plus line with bars coloured above or below plan: two bar datasets, each `null` where the other owns the
  row, plus the plan line. `chartjs-plugin-datalabels` for the bar values.

```javascript
datasets: [
  { type: 'bar', label: 'Below Plan', data: actuals.map((v,i) => v < plan[i] ? v : null), backgroundColor: '#16a34a' },
  { type: 'bar', label: 'Above Plan', data: actuals.map((v,i) => v >= plan[i] ? v : null), backgroundColor: '#dc2626' },
  { type: 'line', label: 'Plan', data: plan, borderDash: [6,4], borderColor: '#3b82f6', fill: false },
]
```

- Background performance bands on a line chart: a plugin that fills rects in `beforeDraw`, reading pixel extents
  from `chart.chartArea` and `chart.scales.y.getPixelForValue(v)`.

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

- Horizontal progress meter (actual vs target): `type: 'bar', indexAxis: 'y'`, two stacked datasets (actual and
  the gap to target), `borderRadius` per side, hidden axes; `chartjs-plugin-datalabels` for the centre value and
  `chartjs-plugin-annotation` for a dashed target line, or an absolutely positioned `<div>` with
  `transform: translateX(-50%)` as the tick.
- Sankey (`chartjs-chart-sankey`): `type: 'sankey'`, data as `[{ from, to, flow }]`, `colorFrom` / `colorTo`
  callbacks of `(context) => colorMap[context.dataset.data[context.dataIndex].from]`. Node labels are
  single-line; `\n` renders literally. The library's sankey is on ECharts.
- Smooth line through 2 or 3 sparse anchors (2024, 2035, 2050) without overshoot: damped cubic Hermite,
  inlined.

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

## Hand SVG and HTML (most tiles)

- Hit-test by position, not by element, in dense grids (waffle squares, heat cells), so the gaps register.
- One `AZ.tip`, one focus style, one radius (6px). Toggles are real `<button type="button">` elements and
  call `redraw()`; keep their state in module-scope variables so it survives a redraw and a resize.
- Part periods: a first or last quarter or year whose total is far below its neighbours is partial. Detect it
  from the rows and label it.
- Size an inline SVG with a `viewBox` computed from the measured width (`0 0 w h`), guarded by `w > 0`, so it
  re-fits on every `redraw`. The core's observer and `requestAnimationFrame` batching already stop thrash.
- Semi-circle gauge: two arc paths, a track from 180 to 360 degrees and a fill to `180 + pct * 180`, both with
  `stroke-linecap="round"`; the SVG only needs the top half (`viewBox="0 0 160 90"` for r=60, cx=80, cy=80).

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

  (The snippet above uses a template literal for readability; a shipped chart builds the string with `+`.)
- Slope or bump chart (rank over time) on an HTML5 canvas: container `flex: 1 1 0; min-height: 0`;
  `canvas.width = wrap.offsetWidth * devicePixelRatio` and scale the context for HiDPI;
  `xForYear(yr) = padL + ((yr - minYr) / (maxYr - minYr)) * chartW`;
  `yForRank(r) = padT + ((r - 1) / (N - 1)) * chartH` (rank 1 at the top); lines with
  `beginPath / moveTo / lineTo / stroke`; left labels `textAlign = 'right'`, right labels `'left'`; dots at
  anchor years with `arc(x, y, 3, 0, Math.PI * 2)`.
- A gradient edge on a text card: prefer a sibling `<div>` (`width: 6px; align-self: stretch; flex-shrink: 0`)
  in a flex row over `border-image` on `border-left`, which paints as one solid colour when the card's height is
  not resolved at paint time. Use it only where the taste rules allow a gradient at all.
- A text-only tile (quote, attribution, intro) is chart.html plus chart.css; chart.js only boots and signals
  render-complete.

## Tooling notes (macOS)

- `sed -i` needs a backup suffix (`sed -i.bak`), `grep -P` is absent, and `timeout` does not exist.
- zsh does not word-split an unquoted `$args`; use `bash -c` in loops, or the `--data=absent` /
  `--tile=620x400` forms.
- `snap.mjs` takes about 10 s. An all-slug edge-check loop exceeds a 120 s tool call: run it in the background.

## Motion and drill-down

- Motion helpers live in the core: `AZ.tween(ms, step, done, ease)`, `AZ.animator()` (cancels its previous run, so
  rapid toggles never fight), `AZ.countUp`, `AZ.lerp`, `AZ.reduced()` (skip motion when true), `AZ.settle()`.
- Keep the last drawn state in a module-scope variable and tween from it, so a slider or toggle glides instead of
  jumping (`library/next-what-if`).
- Hand-built drill-down (only where MayaCharts cannot drill): keep the current level in a module-scope `let`, draw `AZ.crumbs(...)` and wire them with
  `AZ.wireCrumbs`, read the new level back after a redraw. Click the centre or a crumb to go up. Every drill needs
  a visible way back and a hint that says what a click does.
- Order inside `render`: build the header text, `await AZ.settle()`, measure, draw, then run the entrance.
- When a view draws two levels (a treemap showing item types inside families), the pointer is almost always
  over the inner level. Resolve a click to the child of the current focus that contains it, so a click
  anywhere inside a rectangle goes down exactly one level. Handling only the exact node clicked made the
  treemap look dead after the first drill: its visible rectangles were leaves (`library/what-treemap-drill`,
  `stepOf`). Test a drill by clicking the centre of the largest rectangle at every level, not a header strip.
- Never raise the hovered SVG element to the top (`parent.appendChild(el)`) to show an outline when marks nest:
  a hovered parent then covers its own children and stays on top after the mouse leaves, so the chart
  looks merged and clicks land on the wrong level. Draw the outline as a separate `pointer-events: none`
  rect kept last in the SVG (`library/what-treemap-drill`, `hl`). Test hover by moving over every parent,
  then check `document.elementFromPoint` inside it still returns a child.
- Never ignore clicks while an animation runs (`if (!animating) drill()`). Browsers pause animation frames in
  hidden or off-screen tile frames, so the animation may never end and the chart never takes a click. Record
  the end state first, let a click jump the animation to it, and finish it on a timer (`ms + 400`) as a
  fallback (`library/what-treemap-drill`, `transition`).
- Where a library drills natively, use it: MayaCharts `drill: true` on a `path` (see its section), Plotly
  `sunburstclick` for an icicle. Do not rebuild the chart per click, and do not hand-roll a drill MayaCharts has.
- KPI variants worth copying: `kpi-ring`, `kpi-bullet`, `kpi-odometer`, `kpi-sparkbars`, `kpi-quarter-pairs`,
  `kpi-flip`, `kpi-dotstrip`. Same data, different reading; offer more than one per Liveboard.
