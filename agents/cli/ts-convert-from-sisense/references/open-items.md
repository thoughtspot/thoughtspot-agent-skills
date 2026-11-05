# Open items — ts-convert-from-sisense

Unverified assumptions / follow-ups. Status vocabulary: `TO VERIFY | VERIFIED | KNOWN |
DEFERRED | WONT-FIX`. Each must reach VERIFIED (live or via MCP spec) or be explicitly
deferred before this ships live.

## #1 — Live end-to-end conversion on a real cluster — VERIFIED 2026-07-21

Ran the full chain (`parse` → `build-model` → `ts tml lint` → `ts tml import` → `build-liveboard`
→ import) on **ps-internal**, a test Org, against the live **"Sisense Migration - Databricks"**
connection (`workspace.sisense_demo`, the captured `sample_ecommerce` bundle):

- **Model TML validated + imported OK** against the real connection, binding to the live
  Databricks tables (Commerce/Category/Brand/Country); `ts tml lint` CLEAN.
- **Numbers reconcile (no fan-out):** total `SUM(Revenue) = 5315.0`; `Revenue` grouped by
  `Category` (Electronics 2190 + Home 910 + Apparel 835 + Sports 820 + Toys 560) = **5315.0** —
  the `Commerce → Category` MANY_TO_ONE join does not inflate the measure.
- **Liveboard path:** `build-liveboard` emitted 9 Answers (8 Migrated, 1 Approximated =
  bubble→scatter) + 1 tabbed Liveboard; all 10 objects imported OK (0 errors) against the model.

Test objects were deleted after verification (`metadata/delete` → 204); the pre-existing
warehouse tables were left untouched. Merge gate satisfied.

## #2 — Chart-type fidelity via the shared emitter — VERIFIED (design)

The shared emitter (`ts_cli.tableau.liveboard`) is on `main` (merged in #253). `build-liveboard`
emits Answer + tabbed-Liveboard TML directly via the emitter's `build_answer`, passing the
**Sisense-resolved `ts_chart`** (COLUMN/PIE/KPI/…) and status per widget (`answers.build_liveboard_result`).
It deliberately does NOT go through `build_from_spec`'s mark path: main's `build_from_spec`
`_resolve_ct` **re-infers** the chart from a mark and hardcodes `Migrated` (the `ts_chart`-aware
variant is only on the unmerged #255), which would silently mis-type KPIs/pies and hide the
review signal. Driving `build_answer` directly makes the chart mapping correct on today's `main`,
**independent of #255**. The Sisense dashboard filter bar is injected as `liveboard.filters`
chips after emission. Live-render fidelity of the emitted TML is covered by #1 / #5.

## #3 — Live Sisense REST fetch not built — DEFERRED

The converter consumes an **offline bundle JSON** (`{dashboard, widgets, datamodel}`) already on
disk; there is no command that pulls a dashboard, its widgets, and the datamodel directly from a
Sisense server's REST API. A user must assemble the bundle from a Sisense export first. A future
`ts sisense fetch` (following the `.claude/rules/ts-cli.md` "new command" flow: MCP-spec the
Sisense REST endpoints, verify live, then add the command) would close this. Deferred — the
offline path is the intended v1 surface.

## #4 — JAQL formula subset breadth — TO VERIFY on real dashboards

The deterministic `FUNCTION_MAP` / `AGG_MAP` in `ts_cli/sisense/functions.py` covers the common
subset observed in the sample bundles. Against a broader set of real customer dashboards, some
functions currently emitted as Migrated may still be rejected by the ThoughtSpot engine (e.g.
`median`, `stddev`/`variance` argument shapes), and some now marked NEEDS REVIEW may turn out to
have a safe deterministic port. Confirm against real JAQL on the first few live migrations; the
runtime prune step (Step 2) is the safety net until then.

## #5 — Numeric-range / date-bucket filter-chip fidelity — member/exclude VERIFIED 2026-10-27; ranges TO VERIFY live

The dashboard-filter → Liveboard-chip mapping (member→`IN`, exclude→`NOT_IN`, numeric range→
`GE`/`GT`/`LE`/`LT`/`BW_INC`/`BW`/`EQ`; date `level`→`HOURLY…YEARLY`) is derived from the
standalone converter and the worked examples, not yet round-tripped through a live Liveboard
import. Confirm the chip operators and bucket tokens render and filter correctly on a real
Liveboard. **Specifically verify the two-sided range boundary:** ThoughtSpot exposes `BW_INC`
(both-inclusive) and `BW` (both-exclusive); a **mixed** inclusive/exclusive Sisense range
(e.g. `from:10, toNotEqual:100`) keeps both bounds but is emitted as `BW_INC`, so the exact
open/closed boundary is approximate — confirm whether a mixed-bound operator exists on the
target build and tighten if so.

**Member / exclude chips — VERIFIED 2026-10-27.** The exported-Liveboard shape — top-level
`oper: in` / `oper: not in` with a top-level `values` list — filters every tile on import: a
`not in` chip excluding one test location moved every tile of a 19-tile board by the expected
amount (26.9 cluster). The `generic_filter {oper: IN|NOT_IN}` form previously emitted had never
been round-tripped, so both builders now emit the verified shape. **Range chips are still
emitted as `generic_filter` and remain TO VERIFY** — the dashboards used for this round carried
no numeric-range dashboard filter.

## #6 — Binding to an existing Model (`--target-model`) — VERIFIED 2026-10-27

Live end-to-end on a 26.9 cluster against a hand-designed production Model (128 table instances:
a hub dimension, 63 role-playing date copies, several role copies of one dimension). A 31-widget
dashboard (27 charts, 3 tab sets, 3 jump-to-dashboard pivots, 11 dashboard filters) was rebuilt
by `build-liveboard --target-model ... --drill ...` and compared with a hand-built rebuild of the
same dashboard, each tile's search run at the same moment:

- **19 of 19 tiles identical** (row count and total); 9 tab variants reported `Merged`; 0 NEEDS
  REVIEW after a 6-line `overrides.json` (three `filter_map` entries for filters on keys the
  Model hides, three `field_map` entries for a Sisense table the connection cannot see).
- `ts tml lint` clean; import OK; the board renders all 19 tiles (`liveboard/data`).

Facts established on the way, each now encoded:

| Behaviour | Where |
|---|---|
| ThoughtSpot search **ORs** repeated `[X] = v` and **ANDs** repeated `[X] != v`; `[X] in (...)` and `[X] not in (...)` are **silently ignored** (unfiltered result, no error) | `target_answers.filter_fragment` |
| `count [X]` → `Number of X`, `unique count` → `Unique Number of X`, `sum` → `Total X`, `average`/`min`/`max` → `Average`/`Minimum`/`Maximum X`; a formula measure keeps its name | `tableau/liveboard._output_name` |
| A measure filter on one fact with an attribute from another fact (both on a shared dimension) returns **0 or one all-NULL group, no error** | `render_check.suspect_tiles`, surfaced by `verify-render` |
| Server-generated obj_ids drop spaces, parentheses and commas; a Model may carry a custom obj_id no derivation reproduces | `tml_common.derive_viz_obj_id`; the target path uses the exported root `obj_id` |
| PyYAML reads an unquoted `on:` join key as boolean `True` | `target_model.TargetModel` |
| Sisense relation endpoints use the table **id** (sometimes opaque `tq_…`); JAQL dims use the table **name** | `parsing._parse_table` keeps `jaql_name` |
| A cascading dashboard filter group has no `jaql` of its own, only `levels[]` — read as one filter it was dropped silently (the same dashboard carried one: 11 chips became 14) | `parsing.parse_dashboard` |
| A measure NUMBER format (`unit: NONE`, `decimals: 2`, `removeTrailingZeroes: true`, thousands separators) on `answer_columns[].format` imports and exports unchanged (18 columns, one block) and renders a count as `22,652`: thousands separators, no `K`, no trailing `.00` | `target_answers.FULL_NUMBER_FORMAT` |

| A search literal containing `'` escaped as `\'` (`[X] = 'O\'Brien'`) matches: a member with an apostrophe returned the same count filtered as in the unfiltered list (2026-11-05, same build; the double-quoted form matches too) | `target_answers._literal` |

What the target path reports NEEDS REVIEW rather than emitting (unit-tested; the live board above
carries none of these, and its output is unchanged with every check below in place):

- a chip or widget filter whose condition it cannot carry: relative-date, unrecognised, or at a
  coarser date level than days (a `years` member is a period start, which a comparison on the date
  reads as one day); `all` is no condition and is carried as such. Range chips are emitted as a
  `generic_filter` and stay TO VERIFY under #5;
- a second aggregation or date level of one column in one widget;
- a chip bound to a different role-played copy than some tile's own Sisense path reaches;
- an instance the widget's facts cannot reach, or a name match the relation's join key disagrees with;
- a `field_map` / `filter_map` entry naming a column the Model lacks;
- a drill dashboard with no widget with fields, or more widgets than its details table carries.

A tab set whose hidden tabs plot different fields (not the same chart at another date level)
emits every tab as its own tile instead of reporting them `Merged`.

## #7 — obj_id derivation for other punctuation — KNOWN

Verified that the server drops spaces, parentheses and commas from a Model name when it generates
the obj_id. Other punctuation (`_`, `-`, `.`, `&`, `/`) is unverified, and two Models sampled
carried custom obj_ids. The `--target-model` path is unaffected (it uses the exported obj_id); the
derived path (`--model-fqn`, every converter) may still mis-bind a name with other punctuation.
Fix by sampling server-generated obj_ids for those characters.
