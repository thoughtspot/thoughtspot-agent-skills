<!-- currency: powerbi — 2026-07 (verified on ps-internal) -->
# Worked example — combo line + column dual axis

A Power BI `lineClusteredColumnComboChart` maps to ThoughtSpot `LINE_COLUMN` /
`ADVANCED_LINE_COLUMN`. It needs **two measures** (a column series + a line series); if only
one survives translation, `ts powerbi build-liveboard` flags it NEEDS REVIEW rather than
downgrading it (the source type is kept so the gap is visible).

## The durable split lives in `custom_chart_config` (not client_state)
The line-vs-column split and dual/merged-axis layout do **not** persist through
`chart.client_state_v2` — ThoughtSpot re-derives that on every render. The durable config is
`chart.custom_chart_config`:

```yaml
custom_chart_config:
- key: basic
  dimensions:
  - {key: x-axis,        axes: [{type: FLAT,   column: <date/attr>}]}
  - {key: y-axis-column, axes: [{type: MERGED, columns: [<clustered-column measures, e.g. current + prior>]}]}
  - {key: y-axis-line,   axes: [{type: MERGED, columns: [<the line measure>]}]}
  - {key: trellis-by}
  mode: AXIS_DRIVEN
```

## Critical: axes reference columns by GUID, not name (live-verified)
`custom_chart_config` axes reference columns by the **GUID** assigned when the answer is
created. A hand-authored, display-name config errors `Invalid GUID string` on a fresh import.
So:
- The shared emitter **drops** a display-name `custom_chart_config` and lets `ADVANCED_LINE_COLUMN`
  auto-resolve line-vs-column.
- To durably pin a specific split, **capture** it from an exported answer (real GUIDs) and
  replay it via an override (`overrides.visuals[].custom_chart_config`).

## Related gotcha
Tab GUIDs regenerate on every TML import (tabs keyed by name, no stable id), so a bookmarked
`.../tab/<guid>` URL breaks after each re-push. Don't rely on tab GUIDs across pushes.
