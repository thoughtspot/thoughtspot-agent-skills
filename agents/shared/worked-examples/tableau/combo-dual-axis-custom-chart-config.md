<!-- currency: tableau — 2026-07 (fresh-import behavior live-verified on ps-internal 2026-07-15; corrects the earlier display-name claim) -->
# Worked example — Tableau dual-axis combo (line + column) → ThoughtSpot

## Source (Tableau)

A Tableau worksheet with a **dual axis**: `SUM([Sales])` as **bars** on the primary axis and
`SUM([Profit Ratio])` (a %) as a **line** on the secondary axis, by `[Order Date]` (month).
In the TWB this is two `<pane>` marks with different mark classes (`Bar` + `Line`) and a
synchronized/secondary axis on the second measure.

## The rule that a live import taught us

`chart.custom_chart_config` **cannot be hand-authored with column display names.** Its
`axes[].column` / `axes[].columns` reference columns by **GUID** — the per-answer column ids
that ThoughtSpot assigns only *after* an answer exists. A fresh TML import with display names
there fails hard: `Invalid GUID string: <name>` (live-verified on ps-internal, 2026-07-15). A
`ts tml lint` will NOT catch this — only a real import (or `--policy VALIDATE_ONLY`) does.

So `custom_chart_config` is a **capture-and-replay** artifact, not a fresh-emit construct.
There are two correct paths:

### Fresh emit (deterministic, what `ts tableau build-liveboard` does)

Emit `ADVANCED_LINE_COLUMN` with both measures and `axis_configs` by display name.
ThoughtSpot **auto-resolves** which measure is the line vs the column. You lose fine control
over *which* measure is which, but it imports cleanly and renders as a combo:

```yaml
chart:
  type: ADVANCED_LINE_COLUMN
  chart_columns:
  - {column_id: "Order Date"}
  - {column_id: "Total Sales"}
  - {column_id: "Profit Ratio"}
  axis_configs:
  - {x: ["Order Date"], y: ["Total Sales", "Profit Ratio"]}
answer_columns:
- {name: "Profit Ratio", format: {category: PERCENTAGE, percentageFormatConfig: {decimals: 1.0}}}
```

The build-liveboard emitter **drops** any `custom_chart_config` whose columns are display
names (it would fail import) and keeps this auto-resolving form instead.

### Durable pin (capture-and-replay, for exact line/column + dual axis)

1. Import the auto-resolved combo (above).
2. In the ThoughtSpot UI, set the exact line-vs-column split and the secondary axis.
3. **Export** the answer/liveboard TML — the exported `custom_chart_config` now carries real
   column **GUIDs** (`y-axis-column` / `y-axis-line`, `type: MERGED`).
4. Replay that exported config on subsequent imports (pass it through the visual's `override`).
   `build_answer_explicit` replays a `custom_chart_config` **only when its columns are GUIDs**.

`client_state_v2` is not the durable home for the split (ThoughtSpot re-derives it on render);
the exported, GUID-based `custom_chart_config` is.

## Gotchas (live-verified)

- Per-column display format (e.g. the ratio as a percent) belongs on `answer_columns[].format`.
- A **bucketed date** column's output is renamed: `[Order Date].monthly` in `search_query`
  produces an output column **`Month(Order Date)`** — reference *that* resolved name in
  `chart_columns`/`axis_configs`/`table`, not the raw `Order Date` (the emitter handles this).
  A **bare** (unbucketed) date column is fine to reference by its raw name.
- Tab GUIDs regenerate on every TML import (tabs keyed by name) — don't rely on tab GUIDs.
