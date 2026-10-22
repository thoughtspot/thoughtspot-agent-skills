<!-- currency: thoughtspot — 2026-10 (new doc, SpotterViz-mandatory redesign) -->

# Building a Liveboard via SpotterViz

**SpotterViz** is ThoughtSpot's own MCP server for building Liveboards directly from
natural-language instructions, instead of hand-authoring Liveboard/Answer TML. It is the
required liveboard-building mechanism for `ts-convert-from-tableau` and
`ts-convert-from-looker` — those skills no longer generate liveboard TML by hand.

## Confirming connectivity

Before any liveboard work, confirm the SpotterViz MCP tools are available this session
(look for tool names under `mcp__claude_ai_ThoughtSpot_Spotter__*` — `check_connectivity`,
`create_dashboard`, `get_dashboard_status`, `modify_dashboard`, `list_orgs`, `switch_org`,
`search_objects`, plus analysis/model-session tools). If they are not loaded, walk the user
through setup — do not silently fall back to hand-authored TML (there is no fallback path
in these skills):

1. **Add the server to the MCP config** (project or user `mcp.json`, or the client's MCP
   settings UI):
   ```json
   {
     "mcpServers": {
       "ThoughtSpot": {
         "command": "npx",
         "args": ["mcp-remote", "https://vizagent.thoughtspot.app?api-version=latest"]
       }
     }
   }
   ```
2. **Restart the client.** Local/project MCP servers only take effect after a restart — a
   config edit mid-session does not make the tools appear.
3. **Complete the interactive OAuth login** that `mcp-remote` triggers on first connect.
   This cannot be completed in a non-interactive session — if the current session can't do
   it, tell the user to run the login interactively (a terminal session, or via the
   client's own connector-authorization flow) and come back once it's done.
4. **Re-check connectivity** (e.g. call `check_connectivity`) before proceeding.

**If the user wants to proceed without it:** say plainly that liveboard generation cannot
run this session, but Model/Table conversion work is unaffected and can continue normally.
Don't block the rest of the skill on this — only the liveboard step is gated.

## The `is_spotter_enabled` gate

**The target Model/Worksheet must have AI search ("Spotter") enabled**, or `create_dashboard`
returns `needs_input` saying it "cannot create Answer visualizations" against that source —
a gate separate from general query access (the model can still answer ordinary queries with
it disabled). Check before calling `create_dashboard`, not after hitting the blocker:

```bash
ts tml export {model_guid} --profile {profile_name} --parse
```

Read `model.properties.spotter_config.is_spotter_enabled`. If `false` or absent, tell the
user SpotterViz needs it and ask to enable it (even if they declined AI search earlier in
the conversion flow — SpotterViz specifically depends on it, independent of that earlier
choice); on yes, set it `true` and re-import in place (existing `guid`/`obj_id` at the
document root, `--no-create-new`). If they decline, liveboard generation cannot proceed for
that model — same messaging as a missing connection.

## Building the dashboard

`create_dashboard` takes a `title`, a free-text `instructions` string, and an optional
`data_source_id` (the target model's guid/obj_id). Compose `instructions` as a clear,
structured description — not a vague one-liner — covering, per tab/section:

- **What each tile should show**: the measure(s) and dimension(s), any filter, and the
  chart intent in plain words ("a bar chart of total revenue by region", "a KPI of order
  count with a monthly trend", "a map of event locations sized by count"). Draw the intent
  vocabulary from `thoughtspot-chart-types.md`'s "Analytical intent → chart type" mapping
  rather than inventing ad hoc phrasing — SpotterViz resolves chart type and shelf
  assignment itself from the instructions, so clear, consistent intent words matter more
  than literal shelf/encoding detail.
- **Grouping and tab structure**: which tiles belong together and under what tab/section
  name, mirroring the source dashboard's own structure. Once a tab has more than ~6-8
  tiles, ask for named sections by theme rather than a flat list — confirmed preference,
  apply upfront rather than waiting to be asked.
- **Per-record filters**: if the source dashboard's title/subtitle shows per-record
  identifying attributes (e.g. "Order ID: 10248 | Customer: Acme Corp"), ask for a liveboard
  filter on that basis even with no explicit source filter action — that pattern itself
  signals a per-record-scoped dashboard.
- **Chart-intent wording for specific shapes, confirmed over a generic description**: a
  per-entity dot/strip-style source visual (one measure + a categorical grouping + a
  size/color dimension, no aggregation) → ask for a bubble chart sized by the measure, not
  an aggregated bar; a geographic lat/long source visual → ask for a map, not a line of
  coordinates; a multi-measure trend/comparison → ask for a multi-series line once every
  needed measure exists, not a table placeholder.
- **A final summary tab**, if the skill's own migration-summary convention calls for one —
  ask for it explicitly in the same instructions (e.g. "add a final tab summarizing what was
  migrated, what was skipped, and why").

Call `create_dashboard` (new liveboard) or `modify_dashboard` (iterating on one already
built this session). It returns a `task_id`; poll `get_dashboard_status` until:
- `completed` — capture the returned Liveboard guid/URL.
- `needs_input` — relay the question to the user verbatim, get an answer, resubmit.
- `failed` — report the failure plainly; never treat it as success.

## Verifying the build

`completed` means SpotterViz finished building, not that every tile necessarily runs —
export the liveboard and run each tile's search/query (e.g. `ts agentql fetch-data`),
confirming it both succeeds and returns at least one row. A tile that errors or comes back
empty gets one retry (either the fetch itself, if transient, or a `modify_dashboard` call
asking SpotterViz to rebuild that specific tile). If it's still broken after the retry,
don't ship it unexplained — call `modify_dashboard` once more asking it to record that
tile's name and failure detail in the migration summary tab, and carry the same detail into
the skill's own migration report.

## Known gotchas

- **A generated filter literal's casing may not match the formula's actual output.** When
  a tile's filter is built from a plain-English label in the instructions (e.g. "filter to
  the North Region category"), SpotterViz may lowercase or otherwise reformat the
  literal it writes into the underlying Answer. If a filtered tile returns the same
  unfiltered value regardless of which filter is selected, check the filter literal's exact
  casing against the formula/column's actual output — don't assume the instructions' casing
  survived verbatim.
- **The result is still ordinary Liveboard TML underneath.** A dashboard built this way is
  subject to the same TML rules as a hand-authored one if anyone later exports and hand-edits
  it — `TABLE_MODE` not surviving a reimport, bare-name (not `[formula_...]`) references for
  answer-local formulas, the chart-block-completeness rule — see the rest of
  `thoughtspot-liveboard-tml.md` for those.
- **A tile that shows the same unfiltered value for every filter choice is not necessarily
  the casing bug above.** `=`/`!=`/`in` comparisons are case-insensitive in ThoughtSpot (see
  "String comparison is case-insensitive" in `thoughtspot-formula-patterns.md`), so treat
  casing as one hypothesis to verify, not the default explanation — check the filter is
  actually attached to the right column/tile first.
- **Styling/theme is SpotterViz's own default choice**, not currently requestable through
  `instructions` in a verified way — there is no equivalent of a hand-authored theme pass.
  Treat this as a known limitation, not something to work around with a hand-authored
  TML-styling pass (that would reintroduce the hand-authored path these skills no longer
  support).
