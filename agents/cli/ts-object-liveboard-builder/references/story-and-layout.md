# Story and layout

A storytelling Liveboard is one argument split into tabs. A reader who only reads the tab names and the
banners should get the argument; the charts are the evidence.

## The arc

- **Numbered, plain tab names**: `01 About`, `02 Pulse`, `03 Where`, `04 What`, `05 When`, `06 Who`,
  `07 Next`. The numbers carry the order. No icons, no emojis.
- **Five to seven tabs**, three acts: set-up (About), diagnosis (how are we doing, then where, what, when,
  who), action (what to do next). Each tab answers **one question**, stated in its banner.
- **About** first: a hero with live stakes numbers and the central finding, and a guide to reading the
  Liveboard (which chart is which, what clicks do). About tiles ignore the filters.
- **Action** last: moves the numbers support, a what-if, what is at risk. Label every projection as one.
- Each banner ends by pointing to the next tab ("Then: 04 What").

## The banner (one per tab, 12 x 3, at y = 0)

Three columns: the question and a computed lead sentence; "What the numbers say", three figures with
short labels (each with a hover note on how it was computed); "Ask Spotter", three questions a reader
could type next. All copy is computed from the banner's search, so it follows the filters. Build them
from `narratives/render.js` with a config per tab.

## Grid and sizes

12 columns; a grid unit is about 65 px wide and 60 px tall. Rows of a tab fill 12 columns.

| Tile | Size (w x h) |
|---|---|
| Tab banner | 12 x 3 |
| About hero / guide | 12 x 6 / 12 x 4 |
| KPI | 3 x 4 (four to a row) |
| Hero chart of a tab | 12 x 7, or 8 x 6 beside a 4 x 6 |
| Pair of charts | 6 x 6 or 6 x 7 each |
| Wide time or table view | 12 x 6 or 12 x 7 |

Charts at most 8 units tall. Test each chart at its real pixel size and at 280 px wide.

## What goes on a tab

- A **hero** per tab: the chart that answers the tab's question best, placed first and largest.
- Every tile answers a **different** question; two tiles showing the same cut in different shapes is
  one tile too many, unless the tab is deliberately a gallery (as `02 Pulse` shows KPI styles).
- **KPI variety**: do not repeat one KPI design. The library has sparkline, ring, odometer, flip, bullet,
  sparkbars, quarter pairs and dot strip; pick by what the number needs (a target, a trend, a rank).
- **Drill-down where the data has a hierarchy** (family > item type > product, region > state > store,
  year > quarter > month), with crumbs and a visible way back. Not on flat data.
- **Motion that explains a change**: entrances, toggles that tween, zooms on drill. Nothing loops.
- Titles name what is shown ("Sales by state"); the insight goes in the chart's own header line,
  computed from the rows. The tile description says how to read and what a click does.

## Colour across the Liveboard

One meaning per hue, fixed for the whole Liveboard: pick one attribute to own the hues (the example uses
five product families), and show everything else in ink and a slate ramp. A second attribute (region)
never gets hues. Status colours (good, bad) only with a sign. See the chart skill's
`references/library-contract.md` section 2 and `references/taste-rules.md`.

## Filters

Add Liveboard filters on the attributes a reader will want to cut by (the example: date, region, item
type). Every chart must survive one value, a short date range, and a single month, and say so plainly
when there is too little to draw. Exclude About tiles from the filters (`filters: false` in the spec).
Prove it with `cluster-shot.mjs --filter "Region=West"`.
