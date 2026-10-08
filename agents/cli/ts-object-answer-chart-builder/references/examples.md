# Working examples shipped with this skill

Charts that already shipped or rendered correctly. Read one before writing a chart of
the same shape — a working file settles the API questions faster than reasoning from
the reference does, and these carry the workarounds for bugs you would otherwise
rediscover.

Paths are relative to the skill folder — `examples/` is a sibling of the `references/`
directory this file lives in, so they travel with the skill wherever it is installed.

Two rules for using them:

- **Copy the technique, not the file.** Every one of these was written against a
  specific search with specific column names. Lifting one wholesale and swapping the
  field constants is how you inherit a data mode and a set of formats nobody asked for.
- **They predate the preview loop.** None was iterated through `snap.mjs`, so treat
  them as correct-in-ThoughtSpot, not correct-in-preview. Still run the loop.

## Start here: the library

`library/` holds 58 charts built on real data. Each was iterated in the preview and is interactive; all but the four
marked *preview only* in `references/library.md` were also checked in a real cluster. They share one core (`library/_shared/core.js`: theme, column lookup, tooltip, CDN loader, motion,
crumbs, boot). **Look for your shape in this table first**, then in `references/library.md` (every chart by tab,
library and search). Use the `examples/` files further down only for shapes the library lacks, or for the
Muze workarounds they document.

| Pattern | Copy | Library | Why this one |
|---|---|---|---|
| Hierarchy with animated zoom | `library/what-sunburst` | Plotly | Native `sunburstclick` zoom, crumbs wired to `Plotly.restyle` |
| Hierarchy as rectangles, drill by click | `library/what-treemap-drill` | hand SVG | Three-level drill with crumbs and a way back |
| Flow between two or three dimensions | `library/what-money-sankey`, `library/what-chord` | ECharts / D3 | Click a node to isolate its flows; chord drills a family |
| Map, bubble per state, zoom to stores | `library/where-state-bubbles` | inline SVG map | Inline US paths (`_shared/us-states.js`), because `fetch()` is blocked in tiles |
| Hex cartogram | `library/where-hex-cartogram` | hand SVG | Supersedes `examples/State-hex-cartogram` |
| KPI tile | `library/kpi-ring`, `kpi-flip`, `kpi-odometer`, `kpi-bullet`, `kpi-sparkbars`, `kpi-dotstrip`, `kpi-quarter-pairs` | hand SVG | Seven readings of one number, with measure toggles and same-period YoY; supersede `examples/kpi-chart` |
| Line over time with a prior-year ghost | `library/pulse-monthly-line` | Muze | Muze line stroke fix and own crosshair |
| Calendar heatmap, click a year to drill | `library/when-calendar-heatmap` | hand SVG | Partial-period cells, measure toggle |
| Stream or stacked area with drill | `library/when-family-stream` | D3 | Stream / stacked / 100% toggle, family to item-type drill |
| Animated scatter over time | `library/when-bubble-motion` | hand SVG | Play and scrub control driving tweens |
| Pareto / concentration | `library/what-pareto` | hand SVG | The 80% line computed from live rows |
| What-if with sliders | `library/next-what-if` | hand SVG | Tweens from the last drawn state, `AZ.settle()` before measuring |
| Table with inline marks | `library/who-product-table` | hand HTML | Sort, share bars, sparklines; supersedes `examples/table-pivot/table-chart` for flat tables |
| Parallel coordinates | `library/who-store-parallel` | D3 | Brush an axis to filter lines |
| Beeswarm | `library/who-product-beeswarm` | D3 force | Collision layout that fits the tile |
| Pivot table with subtotals | `library/where-region-pivot` | hand HTML | Rows and columns expand both ways; ratio totals computed as sum over sum at every level, so they match ThoughtSpot. Supersedes `examples/table-pivot/pivot-table` |
| League table with movement and form | `library/who-store-league` | hand HTML | Rank change against the same window last year, a five-month form strip, partial-month detection. Supersedes `examples/League Table` and `examples/Scoreboard-chart` |
| Diverging bar, drill to members | `library/what-premium-diverging` | Muze | Muze bars coloured per point, own axis and labels; the workarounds for Muze's band-height floor and remount-on-update. Supersedes `examples/Examples/Example 2 diverging axis` |
| Growth split into volume and price | `library/pulse-family-growth` | hand HTML and SVG | Small-multiple cards with an exact units/price decomposition and like-for-like windows derived from the rows. Supersedes `examples/Examples/Example 4 growth comp` |

The narrative tiles (tab banners, About) are one template in the `ts-object-liveboard-chart-builder` skill (`narratives/`), driven by a config per tab.

## Older examples

These predate the preview loop and the shared core. Entries marked *superseded* have a better library chart above.

## Muze

| Path | What it is | Worth reading for |
|---|---|---|
| `examples/Examples/Example 1 bubble chart/` | Bubble chart, ~490 lines | `encodingTransform` plus an SVG overlay group. Muze's point-size range clamps around 50px, so the native marks are kept invisible and the bubbles are drawn into a cleared overlay — the only way to get large bubbles without leaking nodes across re-mounts |
| `examples/Examples/Department bubble chart/` | Same shape, smaller | The same overlay pattern with a `ResizeObserver`, and a shorter read |
| `examples/Examples/Example 2 diverging axis/` | Diverging bar, ~300 lines | *Superseded by `library/what-premium-diverging`.* Axis domain control and `encodingTransform` for a two-sided scale |
| `examples/funnel-chart/result/` | Funnel | Muze canvas underneath, polygons hand-drawn in SVG on top. Also the domain-mutation workaround: Muze reverses categorical domain arrays on re-mount, so pass `.slice()` and re-config every mount |

Every Muze example here is a `viz.muze` chart, not a Muze Studio script — the canvas is
built and mounted inside the BYOC file.

## Chart.js (CDN)

| Path | What it is | Worth reading for |
|---|---|---|
| `examples/model-connections-bump/result/` | Bump chart, ~420 lines | The CDN load done right: `createElement('script')` + `await new Promise`, jsdelivr pinned to `chart.js@4` |
| `examples/Examples/Example 3 linechart with kpi/` | Line + KPI header | Chart.js beside hand-built DOM in one tile |
| `examples/Examples/Example 5 KPI/` | KPI tile, ~130 lines | The smallest complete example in the repo. Good first read |

## Plotly (CDN)

Sunburst, treemap and icicle. Plotly is the only library here with a real
`type: 'sunburst'` — hierarchy, `branchvalues: 'total'`, click-to-zoom and
`plotly_sunburstclick` all come for free.

| Path | What it is | Worth reading for |
|---|---|---|
| `examples/retail-apparel-sunburst/` | Sunburst, ~470 lines | *Superseded by `library/what-sunburst`.* Still the fullest write-up of the four sunburst defects below. Hierarchy build, `flatten()` into Plotly's parallel `ids/labels/parents/values` arrays, breadcrumb wired to `plotly_sunburstclick`, plus the four fixes below |
| `examples/Sunburst-chart/result/` and `examples/NWP-sunburst/result/` | Sunburst, ~330 lines each | The same hierarchy technique, older. Carry the defects below — read them for shape, not for correctness |

These two were filed under Chart.js until this commit and are **not** Chart.js. If
a library table sent you to Chart.js for a sunburst, it was wrong; use Plotly.

Four defects in `examples/Sunburst-chart/result/` that a copier inherits silently,
all fixed in `examples/retail-apparel-sunburst/`:

- `index.html` is a standalone page (`<!DOCTYPE html><html><head>`), which is a
  hard-rule violation in the BYOC HTML tab. The CDN load belongs in the JS.
- `String(r[i1])` with no cell unwrapping — an object-wrapped cell becomes
  `[object Object]` and every wedge collapses into one. Run `--data wrapped`.
- `emitRenderCompletedEvent()` only on the success path, with no `try/catch`
  painting `err.stack`.
- Unbounded CDN injection and no `ResizeObserver`. Both produce a tile that fails
  in ThoughtSpot while looking perfect in preview — see `hard-rules.md`.

## Hand-built HTML / DOM

| Path | What it is | Worth reading for |
|---|---|---|
| `examples/table-pivot/pivot-table/newused-summary/` | Pivot table, ~720 lines | *Superseded by `library/where-region-pivot`* for a region by family pivot; still the fullest `CONFIG` reference. The most worked-over file here. A `CONFIG` block at the top is the whole interface; below it are the aggregation rules that make totals match TS — `weightedTotal`, `totalFrom`, `ratioTotal`, `computed` — plus `cellVal` for object-wrapped cells and loose column-name matching for non-breaking spaces. Read it before any pivot or crosstab |
| `examples/table-pivot/table-chart/newused-summary/` | Flat table, ~210 lines | *Superseded by `library/who-product-table`.* The same CONFIG idea without the pivot machinery |
| `examples/waffle_chart/result/` | Waffle grid, ~230 lines | Cards built with `createElement`, no library |
| `examples/progression-funnel/progression-funnel.js` | Funnel, ~280 lines | Pure DOM funnel; `_progression_funnel_demo.html` beside it is a standalone preview |
| `examples/Examples/Example 4 growth comp/` | Growth comparison | *Superseded by `library/pulse-family-growth`.* DOM plus `ResizeObserver`, no charting library at all |

## Raw SVG

| Path | What it is | Worth reading for |
|---|---|---|
| `examples/State-hex-cartogram/result/` | US hex cartogram, ~370 lines | *Superseded by `library/where-hex-cartogram`.* `createElementNS` throughout, a fixed layout table keyed by state, and a `ResizeObserver` redraw |
| `examples/kpi-chart/result/` | KPI tile, ~150 lines | *Superseded by the `library/kpi-*` charts.* Small, typography-led, resize-aware. Has a `README.md` |

## Self-contained HTML (everything in the HTML tab)

*Both superseded by `library/who-store-league`* for a standings table; read these only for the single-file shape.

`examples/League Table/` puts all markup, CSS and script in `.html`, leaving the `.js`
and `.css` tabs empty. Interactive: dropdowns and filter chips driving a re-render.

`examples/Scoreboard-chart/result/` is the same chart split back into three files —
read `script.js` for the live-data branch guarded with `typeof viz !== 'undefined'`,
which is how these run both in a plain browser and on a tile. (The single-file version
carried 9 MB of inlined match data and is not in this repo.)

This shape is legitimate for text-heavy or print-oriented tiles, but prefer the normal
three-file split unless there is a reason — the preview loop and the emit checklist
both assume it.

## Screenshots

`examples/Examples/*/result.png`, `examples/Scoreboard-chart/result/result.png` and
`examples/model-connections-bump/result/rendered.png` show what those files actually
render. Read one with vision when matching a target image to a technique.
