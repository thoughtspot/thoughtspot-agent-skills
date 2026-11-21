<!-- currency: thoughtspot — 2026-10 (new doc, SpotterViz-mandatory redesign) -->

# Building a Liveboard via SpotterViz

**SpotterViz** is ThoughtSpot's own MCP server for building Liveboards directly from
natural-language instructions, instead of hand-authoring Liveboard/Answer TML. It is the
required liveboard-building mechanism for `ts-convert-from-tableau` and
`ts-convert-from-looker` — those skills no longer generate liveboard TML by hand.

**Prerequisites — check these up front, not just connectivity.** `check_connectivity`
only confirms the MCP token and instance URL are valid; it does not check any of the
following, so a user missing one passes connectivity and fails partway through a
migration instead:
- ThoughtSpot cluster version 10.11.0.cl+ (26.2.0.cl+ for Spotter 3).
- Data-download and content-creation privileges on the target instance.
- Node.js 22+ (for `mcp-remote`, the Claude Code transport; not needed by Cortex Code
  CLI's native `cortex mcp add`).

## Confirming connectivity

Before any liveboard work, confirm the SpotterViz MCP tools are available this session —
look for a ThoughtSpot/Spotter MCP server exposing `check_connectivity`, `create_dashboard`,
`get_dashboard_status`, `modify_dashboard`, `list_orgs`, `switch_org`, `search_objects`, plus
analysis/model-session tools. **The exact tool-name prefix is runtime-specific, not a fixed
string**: via a claude.ai connector these surface as `mcp__claude_ai_ThoughtSpot_Spotter__*`;
added as a local/project MCP server (either runtime) the prefix is
`mcp__<server-name-you-chose>__*` instead. A skill checking for connectivity must look for
the capability (that set of tool names, under whatever prefix the running client/registration
method produced), never hardcode one prefix as the only valid form. SpotterViz is not
registered by default in either runtime — it has to be added (see step 1 below) before its
tools appear under any prefix; if no matching tool set is found after setup, that's a setup
problem, not a platform limit, and the walkthrough below applies the same way in Claude Code
or Cortex Code CLI. Once a matching tool set is found, confirm it's actually live by calling
`check_connectivity` rather than trusting its mere presence in the tool list. If no match is
found (or `check_connectivity` fails), walk the user through setup — do not silently fall
back to hand-authored TML (there is no fallback path in these skills):

1. **Add the server to the MCP config** (project or user `mcp.json`, or the client's MCP
   settings UI):
   ```json
   {
     "mcpServers": {
       "ThoughtSpot": {
         "command": "npx",
         "args": ["mcp-remote@0.16.0", "https://agent.thoughtspot.app/mcp?api-version=2026-10-14"]
       }
     }
   }
   ```
   `mcp-remote` is pinned to an exact version rather than left bare — a bare `npx mcp-remote`
   resolves to whatever is newest at invocation time, which is not reproducible across setups
   or over time; bump the pin deliberately (check `npm view mcp-remote versions`) rather than
   floating it. `api-version` is pinned to a dated value (`2026-10-14`, per the
   [public MCP docs](https://developers.thoughtspot.com/docs/connect-mcp-server-to-clients)'
   own example) rather than left as `latest` — `latest` is not reproducible across setups
   either, and the server's own source marks that date's release as a placeholder until a
   real release is scheduled, so an unpinned connection can silently gain or lose tools on a
   later run with no config change on this side. If a connection surfaces an unexpectedly
   small tool set (missing `check_connectivity`/`create_dashboard`), that's a sign the pinned
   date no longer matches the server's current tool surface — bump the date deliberately
   (re-check the public docs page) rather than reverting to `latest` — see BL-531.
   **Cortex Code CLI** — Snowflake's own agentic coding CLI, a client running this skill,
   unrelated to which warehouse the target ThoughtSpot connection actually queries — adds
   the same server via `cortex mcp add thoughtspot
   "https://agent.thoughtspot.app/mcp?api-version=2026-10-14"` (an OAuth HTTP server, per
   Snowflake's own `cortex mcp add` docs) rather than editing `mcp.json` directly; its tools
   then surface under `mcp__thoughtspot__*` (or whatever name was given to `cortex mcp add`),
   not the Claude.ai-connector-specific `mcp__claude_ai_ThoughtSpot_Spotter__*` prefix — this is why
   the connectivity check above looks for the tool-name *capability* under any prefix, never
   a hardcoded one.
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

**Live-verified 2026-10-15.** **The target Model/Worksheet must have AI search ("Spotter") enabled**, or `create_dashboard`
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
`data_source_id` — a GUID (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`), **not** the model's
`obj_id`. The tool's own description says to omit it "in most cases" and let the designer
auto-select — that default is for open-ended chat use; in a migration, the target model is
already known and confirmed, so always pass the model's GUID explicitly rather than relying
on auto-selection, which can pick the wrong Model when more than one shares a name (e.g. a
re-run leaves two Models called "Superstore"). `create_dashboard`'s first reply is always a
plan (`needs_input`) naming the data source it chose — before confirming that plan (calling
`create_dashboard` again with the same `task_id`), check the named data source against the
GUID you passed; if it doesn't match, do not confirm the plan — surface this to the user
rather than letting every tile silently bind to the wrong Model.

**Parameters.** A Tableau/Looker parameter that a migrated formula *consumes as a value*
(not just a filter) is worth asking for as an adjustable control: name it in the
instructions (e.g. "add an adjustable parameter for {Parameter Name} that the {tile} uses").
A filter-type parameter (used only to drive a row filter) should be described as a liveboard
filter instead, the same as any other per-record/per-category filter — not as a parameter
control. A display-toggle/sheet-swapping parameter (picks which sheet/metric to show, not a
value inside a formula) has no SpotterViz/ThoughtSpot equivalent — don't ask for a control
that doesn't correspond to any real tile behavior; record it as a known gap in the summary
tab and the skill's own migration report instead, the same as any other unmigrated-shape
item (a funnel placeholder, an omitted map, a split dual-axis chart, etc.) — SpotterViz
replaces hand-authored TML for most shapes, but it doesn't eliminate every gap a source
dashboard can have, and "the build completed" must never be read as "nothing to report."

Compose `instructions` as a clear, structured description — not a vague one-liner —
covering, per tab/section:

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

Call `create_dashboard` with `data_source_id` set to the model's GUID (new liveboard) or
`modify_dashboard` (iterating on one already built this session). It returns a `task_id`;
poll `get_dashboard_status` until:
- `completed` — capture the returned Liveboard guid/URL.
- `needs_input` — check the plan's named data source against the GUID you passed (see
  above) before relaying anything else; if it matches, relay the rest of the question to
  the user verbatim, get an answer, resubmit with the same `task_id`.
- `failed` — report the failure plainly; never treat it as success.

## Verifying the build

`completed` means SpotterViz finished building, not that every tile necessarily renders.
Run:
```bash
ts tml verify-render {liveboard_guid} --profile {profile_name}
```
Exit 0 means the board returns data and every chart tile has an axis encoding — nothing
further to do. **Do not treat an empty result as a failure on its own** — `verify-render`
only flags a genuine query-time error (`failing_tiles`) or a chart tile with no axis
encoding at all (`blank_chart_tiles`, draws visibly blank even though the query succeeds);
a tile that legitimately has zero matching rows (e.g. "orders returned this week" when
there are none) renders fine and is not one of these. Exit 1 means at least one of:
- `failing_tiles` — an actual query-time error. Retry once via `modify_dashboard`, asking
  SpotterViz to rebuild that specific tile — the failure is most often a dropped filter or
  a field that didn't survive model-build, so check that before assuming it's transient.
- `blank_chart_tiles` — a chart tile with no axis encoding. This is a chart-configuration
  gap, not a data gap — ask `modify_dashboard` to fix the chart type/encoding for that
  tile, not to "rebuild" it as if the data were wrong.

If either list is still non-empty after the retry, don't ship it unexplained — call
`modify_dashboard` once more asking it to record that tile's name and failure detail in the
migration summary tab, and carry the same detail into the skill's own migration report.

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
  it — bare-name (not `[formula_...]`) references for answer-local formulas, the
  chart-block-completeness rule (`thoughtspot-liveboard-tml.md`), and `TABLE_MODE` not
  surviving a reimport for a tile that was originally a grouping chart type
  (`thoughtspot-chart-types.md`, merged via #662).
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
