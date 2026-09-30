# Starters and traps by library (learned building the Amuzing chart samples Liveboard)

Every chart starts from the shared core (`library/_shared/core.js`): `AZ.boot`, `AZ.col`, `AZ.tip`,
`AZ.loadScript`, formatters, the family theme. What follows is what each library needs on top of it in a
real ThoughtSpot tile. All of it was verified in a cluster screenshot unless marked otherwise.

## Any library

- Load a CDN library with `AZ.loadScript([primary, fallback], () => !!window.Lib, 8000)`. It injects at once
  when no matching `<script src>` is in the document and waits up to 3 s when one is. A plain
  `<script src>` in `chart.html` is allowed by `liveboard-pack`; an inline script body containing `</script` is not.
- `fetch()` is blocked inside a tile. Inline data and maps.
- No backtick, no `${`, ASCII only (a literal non-ASCII character such as an arrow corrupts the checksum in
  transit). Use `String.fromCharCode(8595)` for an arrow if you must; a `\\u0001` escape in source is fine.
- Test at 280px wide as well as the nominal size.

## ECharts (echarts@5)

- Render with `renderer: 'svg'`, set `animation: false`, and pass an explicit `width` and `height`
  (`echarts.init(el, null, { renderer: 'svg', width: w, height: h })`). Without them the first paint can be a
  fraction of the container, and a screenshot taken after render-complete catches a half-drawn chart.
- Fill any header text **before** you measure the plot area, then call `chart.resize({ width, height })`.
- zrender pointer events do not fire on empty areas. Attach native listeners to the container, and convert
  with `chart.convertFromPixel({ xAxisIndex: 0 }, px)` using a scalar.
- Sankey and sunburst labels collide first: drop or shorten the small ones and say so in the sub line.

## D3 (d3@7)

- Use it for scales, layouts (`d3.stack`, `d3.area`) and transitions; write the DOM yourself where a
  library would fight the shared tooltip.
- Geography: do not fetch topology. `library/_shared/us-states.js` holds all 51 states as pre-projected
  Albers paths (viewBox 0 0 975 610) with centroids. Paste the const into the chart body and draw plain SVG.

## Muze

See `references/system-prompt.md` and the "Verified in a real cluster" table in `references/hard-rules.md`.
Short version: set stroke colour and width yourself on line marks, hide the native tooltip, crosshair and the
`muze-columnHeader` cells, draw your own hover from `path.getScreenCTM()` read on every move.

## Hand SVG and HTML (most tiles)

- Hit-test by position, not by element, in dense grids (waffle squares, heat cells), so the gaps register.
- One `AZ.tip`, one focus style, one radius (6px). Toggles are real `<button type="button">` elements and
  call `redraw()`; keep their state in module-scope variables so it survives a redraw and a resize.
- Part periods: a first or last quarter or year whose total is far below its neighbours is partial. Detect it
  from the rows and label it.

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
- Drill-down: keep the current level in a module-scope `let`, draw `AZ.crumbs(...)` and wire them with
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
- Where a library drills natively, use it (Plotly `sunburstclick`, `Plotly.restyle` for crumb jumps); do not
  rebuild the chart per click.
- KPI variants worth copying: `kpi-ring`, `kpi-bullet`, `kpi-odometer`, `kpi-sparkbars`, `kpi-quarter-pairs`,
  `kpi-flip`, `kpi-dotstrip`. Same data, different reading; offer more than one per Liveboard.
