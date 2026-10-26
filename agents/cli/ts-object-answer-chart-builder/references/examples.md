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
library and search). Use the `examples/` files further down only for shapes the library lacks.

| Pattern | Copy | Library | Why this one |
|---|---|---|---|
| Any standard business shape (bar, line, KPI, waterfall, treemap ...) | `examples/maya-was-bars` | MayaCharts | 6 lines of JS plus the theme in `chart.css`, no shared core: one `maya.host.thoughtspot` call whose spec draws bars with a ghost of last year straight from long rows (`was: { by }`) and a data-token headline. The starter for a standalone MayaCharts tile (preview-verified, not yet on a cluster) |
| Hierarchy with animated zoom | `library/what-sunburst` | MayaCharts | `type: 'sunburst'` with `drill: true`: rings, centre total, shares, animated zoom and crumbs from one spec; family hues from `colors: AZ.T.family`, thin wedges folded by `minAngle` (preview only) |
| Hierarchy as rectangles, drill by click | `library/what-treemap-drill` | MayaCharts | `type: 'treemap'` with `drill: true` and `depth: 2`: families with their item types inside, drill with crumbs and a way back (preview only) |
| Flow between two or three dimensions | `library/what-money-sankey`, `library/what-chord` | MayaCharts / D3 | Sankey: `type: 'sankey'`, click a region, then a family, to drill into its flows (preview only). Chord (D3) drills a family, which MayaCharts' chord cannot yet |
| Map, bubble per state, zoom to stores | `library/where-state-bubbles` | inline SVG map | Inline US paths (`_shared/us-states.js`), because `fetch()` is blocked in tiles |
| Hex cartogram | `library/where-hex-cartogram` | hand SVG | Supersedes `examples/State-hex-cartogram` |
| KPI tile | `library/kpi-ring`, `kpi-flip`, `kpi-odometer`, `kpi-bullet`, `kpi-sparkbars`, `kpi-dotstrip`, `kpi-quarter-pairs` | hand SVG | Seven readings of one number, with measure toggles and same-period YoY |
| Line over time with a prior-year ghost | `library/pulse-monthly-line` | MayaCharts | Lean MayaCharts line: the spec carries the series, tooltip and resize (preview only) |
| Calendar heatmap, click a year to drill | `library/when-calendar-heatmap` | hand SVG | Partial-period cells, measure toggle |
| Stream or stacked area with drill | `library/when-family-stream` | D3 | Stream / stacked / 100% toggle, family to item-type drill |
| Animated scatter over time | `library/when-bubble-motion` | hand SVG | Play and scrub control driving tweens |
| Pareto / concentration | `library/what-pareto` | hand SVG | The 80% line computed from live rows |
| What-if with sliders | `library/next-what-if` | hand SVG | Tweens from the last drawn state, `AZ.settle()` before measuring |
| Table with inline marks | `library/who-product-table` | hand HTML | Sort, share bars, sparklines |
| Parallel coordinates | `library/who-store-parallel` | D3 | Brush an axis to filter lines |
| Beeswarm | `library/who-product-beeswarm` | D3 force | Collision layout that fits the tile |
| Pivot table with subtotals | `library/where-region-pivot` | hand HTML | Rows and columns expand both ways; ratio totals computed as sum over sum at every level, so they match ThoughtSpot. Read it before any pivot or crosstab |
| League table with movement and form | `library/who-store-league` | hand HTML | Rank change against the same window last year, a five-month form strip, partial-month detection. Supersedes `examples/League Table` and `examples/Scoreboard-chart` |
| Diverging bar, drill to members | `library/what-premium-diverging` | MayaCharts | Lean MayaCharts diverging bar with sign colouring and drill (preview only) |
| Growth split into volume and price | `library/pulse-family-growth` | hand HTML and SVG | Small-multiple cards with an exact units/price decomposition and like-for-like windows derived from the rows |

The narrative tiles (tab banners, About) are one template in the `ts-object-liveboard-chart-builder` skill (`narratives/`), driven by a config per tab.

## Older examples

These predate the preview loop and the shared core. Entries marked *superseded* have a better library chart above.

## Chart.js (CDN)

No Chart.js chart ships, here or in `library/`; MayaCharts covers its usual shapes (radial, gauge, doughnut-like
waffle). If you need it, load it the way `AZ.loadScript` does: a `<script src>` plus a bounded promise, jsdelivr
pinned to an exact `chart.js` version with its integrity, and read the Chart.js section of `references/library-starters.md`.

## Plotly (CDN)

A sunburst or treemap with a zoom drill is MayaCharts now: `{ type: 'sunburst', path: [...], y, drill: true }` gives the
rings, centre total, shares in the tooltip and an animated zoom with a breadcrumb in one spec (`library/what-sunburst`).
The Plotly examples below are kept for icicles and as the record of the hand-built technique.

| Path | What it is | Worth reading for |
|---|---|---|
| `examples/retail-apparel-sunburst/` | Sunburst, ~470 lines | *Superseded by `library/what-sunburst` (MayaCharts, a few lines).* Still the fullest write-up of the four sunburst defects below. Hierarchy build, `flatten()` into Plotly's parallel `ids/labels/parents/values` arrays, breadcrumb wired to `plotly_sunburstclick`, plus the four fixes below |

This one is Plotly, not Chart.js. For a new sunburst use MayaCharts.

## Raw SVG

| Path | What it is | Worth reading for |
|---|---|---|
| `examples/State-hex-cartogram/result/` | US hex cartogram, ~370 lines | *Superseded by `library/where-hex-cartogram`.* `createElementNS` throughout, a fixed layout table keyed by state, and a `ResizeObserver` redraw |

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

`examples/Scoreboard-chart/result/result.png` and `examples/maya-was-bars/preview.png` show what those files
actually render. Read one with vision when matching a target image to a technique.
