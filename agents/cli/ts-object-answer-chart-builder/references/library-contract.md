# Library chart contract

Every chart in `library/` meets this. Read it before writing one, and before copying one. `$S` is this
skill's folder, and `<RUNS>` the `runs-root:` the doctor (`helpers/env.mjs`) prints, `~/.cache/ts-charts/runs` by default. The shared core is `library/_shared/core.js` and `core.css` (theme, column lookup, tooltip,
bounded CDN loader, motion, crumbs, `AZ.boot`). Reference charts that meet the bar: `library/pulse-monthly-line`
(Muze), `library/pulse-kpi-sales` (inline SVG), `library/what-sunburst` (Plotly drill).

Charts that go on a Liveboard are then sent to the Liveboard and checked by the `ts-object-liveboard-chart-builder`
skill; nothing in this file needs the ThoughtSpot MCP except the real-data fixture.

## 1. Hard contract

1. Three files in `<RUNS>/<slug>/chart/`, plus `<RUNS>/<slug>/sample-data.json` (the **real** rows for the preview, see 5) and `<RUNS>/<slug>/intent.txt`. Create `<RUNS>/<slug>/chart/.uses-core` (empty file) so `sync-core` inserts the core block.
2. `chart.js` = shared core block + your body. Never edit between the `amuzing core` markers. `node $S/helpers/sync-core.mjs <RUNS>/<slug>/chart` inserts/refreshes it.
3. Body starts with `AZ.boot({ need: '<search in plain words>', render: async ({ el, rows, schema, w, h, redraw }) => { ... } })`.
   `boot` handles the empty state, error painting, ResizeObserver on `#chart`, and render-complete. `redraw()` re-runs render (use it for toggles). Keep UI state (selected mode) in module-scope `let`s so it survives a redraw. Return a cleanup function if you create canvases or listeners on `window`.
4. **Transport rules (the chart is shipped as `String.raw`)**: no backtick anywhere, no `${`, **ASCII only** (a literal non-ASCII character, even an arrow, corrupts the checksum in transit; write `String.fromCharCode(8595)` instead. A `\\u0001` escape in source is fine) (no emoji, no em-dash, no curly quotes, no U+00A0), no literal `</script`. Build strings with `+`. `library-emit.mjs` rejects non-ASCII and the Liveboard skill's `liveboard-pack.mjs` rejects all of them.
5. `chart.html` holds the Geist font link and `<div id="chart"></div>` (copy from a reference chart). A CDN library `<script src>` goes in `chart.html`; also load it with `AZ.loadScript([primaryUrl, fallbackUrl], () => !!window.Lib, 8000)` in `chart.js` (bounded, with a fallback host). Pin versions (d3@7, echarts@5, plotly.js-dist-min@2, topojson-client@3, us-atlas@3). Verified: `<script src>` from jsdelivr and unpkg loads inside a tile; `fetch()` does not, so inline any data file.
6. `chart.css` starts with the core css marker pair and only adds chart-specific rules. Use the `--az-*` variables.
7. Sizing: the tile is `#chart` with `height: 100%`. Lay out with flex/grid inside it; charts must fit and re-fit when the tile resizes (test 3 sizes, section 5).
8. Muze notes (only if you use Muze): mount into an element you measured; `axes.x.fields[Field].tickFormat` for temporal ticks (the `d` argument is `{rawValue, formattedValue}`); Muze ignores `.color({range})` on line marks and can leave stroke width 0, so set stroke/width yourself after `afterRendered` (poll until every path has a `d` attribute); hide its native tooltip/crosshair with CSS and draw your own from `path.getScreenCTM()` read live on each mouse move (the layer animates in). No `mark: 'text'` layers, no `tooltip.mode: 'consolidated'`, point `size` <= 0.05, `domain` config is ignored. See `references/system-prompt.md` and `references/hard-rules.md`.

## 2. Design rules (no AI slop)

- **No emojis anywhere.** No em-dashes. No sparkle glyphs. No stock phrasing ("Unlock", "Dive into", "Seamless", "at a glance").
- **Palette variables**: `--az-slate-0` to `--az-slate-7` and `--az-ink`, `--az-ink2`, `--az-muted`, `--az-grid`, `--az-good`, `--az-bad` are defined by the core css. `AZ.pts(x)` formats a signed gap in percentage points.
- **Colour has one meaning.** Hues are reserved for the five product **families** (`AZ.T.family`, via `AZ.familyColor(itemType)`): Outerwear `#D1543A`, Tops and dresses `#2A6FD0`, Bottoms `#0F9D8A`, Swim and basics `#D99A00`, Accessories `#C2477A`. **Region is never a hue**: show region by position/label, or with the slate ramp `AZ.T.slate`. Non-family series use ink `#1E1E24` and slate greys. Up/down text may use `AZ.T.good` / `AZ.T.bad` with an explicit `+` / `-` sign. One accent rule, locked for the whole Liveboard. Never introduce a new hue.
- Family grouping is editorial (not a model column); say so in the README if a chart uses it.
- **One radius scale**: 6px for controls and tooltips. Cards are not needed inside a tile (the tile is the card).
- **Type**: Geist (already loaded), tabular numerals, a small fixed scale (11 / 12 / 13 / 14 / 40 hero). No mixed families.
- **Copy is specific and data-derived.** A headline sentence cites a live number or asks a real question, e.g. "Jackets carry 18% of sales from 6% of units". Compute it from the rows. Titles name what is shown; the insight goes in the chart header line, not in a slogan. Re-read every visible string before you finish: grammatical, plain, not cute.
- No fake precision: figures come from rows and are formatted with `AZ.money/int/pct`. A projection must be labelled as a projection.
- Empty and tiny-data states are designed, not blank.

## 3. Interactivity (required on every chart)

Every chart must respond to the pointer. Minimum: a hover tooltip built with `AZ.tip(...)` + `AZ.row(...)` (crosshair/dot or mark highlight to show what is under the pointer). Add at least one more that fits the shape: click a mark or legend item to isolate/dim others, a metric or period toggle, a sort toggle, a scrub or play control, brush. Hit targets bigger than the mark. Keyboard focus styles on any button. Dim (opacity .25) rather than remove when isolating. Verify with the probe (below); a chart where nothing changes on hover is not done. In dense grids (waffle squares, heat cells) hit-test by position, not by element, so the gaps between marks still register. Test at **280px wide** as well as the nominal size: Liveboard tiles are often narrower than 65px per grid unit. Keep your own `#chart` flex or padding rules off the empty-state path (`.az-empty` centres itself).

## 4. Procedure per chart

1. **Real-data fixture.** Run the tile's exact search with MCP `execute-thoughtspot-code` (`ts.post('/api/rest/2.0/searchdata', { logical_table_identifier: '<model guid>', query_string: '<search>', record_size: <n> })`, read `body.contents[0].column_names` / `data_rows`). Have the sandbox return the fixture as a JSON string and write it with Python into `<RUNS>/<slug>/sample-data.json` as `{ "schema": [{name, type: "dimension"|"measure", defAggFn?}], "rows": [{colName: value}] }`. Write `defAggFn` in lower case (`"sum"`): `"SUM"` crashes the preview's Muze DataModel with "RuntimeError: unreachable". Dates: multiply seconds by 1000. Use the **column names the search returns**. Keep searches aggregated so the fixture stays under ~1,000 rows (top-N products, quarter grain, etc.); if the tile needs a bigger search, cap it in the search and say so.
2. Write the three files (create empty `chart.js` and `chart.css` plus `.uses-core` first, or let `sync-core` create them). `node $S/helpers/sync-core.mjs <RUNS>/<slug>/chart`.
3. Loop (up to 8 attempts): `node $S/helpers/snap.mjs <slug> NN --tile WxH` then **Read the PNG** and fix the top defect. Pixel size of a tile: width = grid_w x ~65 px, height = grid_h x ~60 px (a 6x6 tile is about 390x360; 12x7 is about 780x420; 3x4 is about 200x240, use 300x260 as the KPI preview).
4. Interaction check: `node $S/helpers/probe.mjs <slug> --tile WxH --sweep` (must report >= 3 of 5 points changed the DOM), and `--hover fx,fy --out NN` then Read `attempts/NN.hover.png` to read the tooltip. For clicks use `--click fx,fy` or `--click-sel "css"` (also `--hover-sel`); `--eval-first "js"` sets state (a slider, an accordion) before the screenshot. `--eval "js"` inspects the DOM after the interaction.
5. Edge checks (use `bash -c` for loops: zsh does not split an unquoted `$args`; `snap.mjs` also accepts `--data=absent` and `--tile=620x400`): `--data absent`, `--data wrapped`, `--data empty`, `--tile 620x400`, `--tile 1400x500`, `--tile 400x300`. The empty state must name the search. (`--data noviz` warns about render-complete by design in mode B.)
6. Filter-resilience check: temporarily edit a copy of the fixture to one region / one item type / 3 months and confirm the chart still draws or shows a clean message.
7. Publish: `node $S/helpers/library-emit.mjs <slug> --title ... --tab <Tab> --tile WxH --lib "..." --search "..." --question "..." --interactions "..." --notes "..." --png attempts/<final>.png`. It refuses non-ASCII or drifted core.
8. To put it on a Liveboard, hand over to the `ts-object-liveboard-chart-builder` skill.

## 5. Motion, drill-down and variety

These rules sit on top of everything above.

**Motion (smooth, not busy).**
- The core already fades every chart in and cross-fades on `redraw()`. Add motion inside your chart where it explains a change: bars growing, a line drawing on, a wedge or panel zooming, a number counting up (`AZ.countUp`), a value tweening between two states (`AZ.tween`, `AZ.EASE`, `AZ.lerp`).
- 200 to 550 ms, one easing family (`AZ.EASE.out` for entrances, `AZ.EASE.inOut` for moves). Nothing loops. Nothing moves that the viewer did not cause, except a single entrance.
- `AZ.reduced()` is true for prefers-reduced-motion: the helpers already jump to the end state; if you animate by hand, check it.
- Animate transform and opacity or SVG attributes; cancel every `tween` and `requestAnimationFrame` in your cleanup. A toggle should tween from the old state to the new one, not blank and redraw.
- Screenshots are taken about 700 ms after render-complete: either finish your entrance within that time or make the final frame the default state (the preview must show a finished chart).

**Drill-down (only where the data has a real hierarchy).**
- Hierarchies: family > item type > product; region > state > store; year > quarter > month; entity > its detail (store > its quarters, product > its item type peers).
- Use `AZ.crumbs(names)` + `AZ.wireCrumbs(root, onJump)` for the path (last crumb is the current level), a Back affordance, and keep the drill path in a module-scope variable so it survives `redraw()`. Re-resolve it against the current rows on every render: a filter may have removed the node, then fall back to the nearest valid level.
- Transition between levels visibly (zoom, expand, morph), 350 to 550 ms. Enter or Space drills a focused mark; Escape goes up.
- A drill only uses data the tile's search already returns, or a search you name in your report. Never fetch.

**Variety.** Each new chart must add a visual grammar the Liveboard does not have yet. Do not rebuild an existing chart with a new colour. Colour rules are unchanged: hues only for families; slate and ink for everything else; no emojis; specific, computed copy.

**Traps.**
- Create `AZ.tip(...)` **after** you set `el.innerHTML`; a tip created earlier is wiped with the rest of the markup and every later `tip.show` silently does nothing.
- The core's entrance fade uses an animation fill, so it excludes `.az-tip`. If you add your own hover-only elements directly under `#chart` (opacity driven by hover), give them a wrapper or the class `az-tip`, or the fill will pin them visible.
- `probe.mjs --sweep` counts DOM changes. A tile with one hover target and identical tooltip text everywhere reads as barely interactive; give it position-dependent feedback (highlight the part under the pointer).
- Use `AZ.animator()` for anything a user can trigger twice quickly (toggles, sliders, drills): it cancels the previous tween.
