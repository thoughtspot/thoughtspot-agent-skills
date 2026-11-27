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

The deterministic `FUNCTION_MAP` in `ts_cli/sisense/functions.py` covers the common
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
by `build-liveboard --target-model ... --drill ...`:

- `ts tml lint` clean; import OK; the board renders all 19 tiles (`liveboard/data`); 9 tab
  variants reported `Merged`.
- Each tile's search matched a hand-built rebuild of the same dashboard (row count and total).
  That rebuild made the same binding choices, so this checks the emitter, **not** parity with
  Sisense: what VERIFIED covers here is that the target path builds, imports and renders.

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

| A date value has no verified search form: `[D] = '2026-02-01'` and `'2026-02-01T00:00:00'` are rejected ("Date value token doesn't have a valid date filter"), bare `2026-02-01` / `02/01/2026` are invalid tokens, and `'02/01/2026'` parses but matched nothing for a day with 8,662 rows (same build) | `target_filters.date_problem` |
| `top N` and `bottom N` rank by the answer's single measure: each returned exactly the N largest / smallest values of the unfiltered list (same build) | `target_filters.top_n` |
| `top N` ranks the FILTERED rows wherever it sits in the query: `... top 2 [Region] = 'West'` and `... [Region] = 'West' top 2` return the same two rows, the top two of the filtered list (26.11, 2026-11-17) | `target_answers._answer_for` puts the ranking last anyway |
| Search `=` and `!=` on text ignore case (`[Status] = 'ACTIVE'` matches `Active`), and `[X] != 'v'` KEEPS rows where X is NULL (on a column holding NULLs, `!= 'v'` returned every row but the `v` rows, NULLs included) (26.11, 2026-11-17) | `target_settings.value_matching_row`, and the join-type check counts an exclude as showing unmatched rows |
| On a boolean formula column (`if ( ... ) then true else false`), `[X] = true` returned exactly the true group and `= false` / `!= true` exactly the false group (the groups summed to the total); `= 'true'` behaves like `= true` (26.11, 2026-11-17) | `target_filters.value_problem`, `target_answers._term_problem` (booleans only on a boolean column) |
| A Sisense relation with no join type is an INNER join (Sisense documentation, Linux edition, "Creating and Removing a Relationship Between Tables"); every relation in the data model above has `type: null` | `target_settings.join_type_problem` (see #8) |
| Sisense "Highlight" mode (`dashboardFiltersMode: select`) highlights members of a column the widget plots instead of filtering, and acts as a normal filter on a column it does not plot; a widget filter takes priority over a dashboard filter on the same dimension; a switched-off filter performs no filtering (Sisense documentation, Linux edition) | `target_chips` |

**The rule is an allowlist, at every level on both sides.** On the Sisense side `allowlist.py`
lists every dashboard, widget, `options`, `style`, `metadata`, panel, data-model table and
relation key the converter reads or treats as presentation (built from the keys 21 real
dashboards carry), the parser lists every JAQL, panel-item and filter key it does not read, and
contradictory filter keys are refused. On the Model side `target_settings.py` reads the Model's
filters, `join_progressive`, join types, column properties and Tables' warehouse tables. A new
setting on either side is flagged, never ignored. What is flagged NEEDS REVIEW,
on the chip and on every tile it affects, is enumerated in the coverage matrix ("Binding to an
existing Model"). Rebuilt with every check in place, the live board above reports these NEEDS
REVIEW rows, each a real risk or an unverified step: tiles whose tables reach the filtered
facility through two copies Sisense relates (which one Sisense filters by cannot be decided), and
the hidden grains merged into them; weekly buckets (that cluster starts weeks on Monday, as the
Sisense widgets do, so they are accepted there); a calculated column bound to its Model formula by
name only (confirmed with one `field_map` line); two count tiles whose dimension both the
enrollment fact and the Model-added union view reach (ThoughtSpot's choice of fact, not Sisense's);
a tile on a Sisense loop (enrollment, case and facility relate to each other); a filter override
that reads a view built to stand in for a Sisense table; quarterly grains (that cluster uses
calendar quarters, as Sisense does, so they are accepted there); and the drill's details table, whose facility
columns were bound through the enrollment copy while Sisense joins that widget's facility through
the case, and whose patient table Sisense reaches on a column the Model does not join. The earlier
tile-for-tile comparison above was between two rebuilds sharing those bindings, not against Sisense.

Still unit-tested only: range chips (#5, flagged until verified), and a search value containing
a backslash (flagged, since only `'` quoting is verified).

## #8 — Sisense value matching and join type, against a live Sisense query — TO VERIFY

ThoughtSpot's side is live-verified (#6: search ignores case and keeps NULL rows under `!=`). Two
Sisense behaviours the target path relies on are read from documentation, not observed:

- **Join type.** A relation with no type is an INNER join (Sisense docs). Community threads
  disagree on older builds, so this should be confirmed on the customer's own Sisense: count a
  fact's rows grouped by a dimension that has an unmatched key, in a widget, and compare with
  the fact's total. Until then a Model join that is not INNER on a tile's path is NEEDS REVIEW.
- **Member and exclude matching.** Whether Sisense compares text members case-sensitively, and
  whether an exclude keeps NULL rows. Until verified, one board-level row names every tile and
  chip that compares text values. Chips (`in` / `not in`) are not verified on ThoughtSpot either.

Close each by running the same query on both sides for a column with mixed case and NULLs.

## #7 — obj_id derivation for other punctuation — KNOWN

Verified that the server drops spaces, parentheses and commas from a Model name when it generates
the obj_id. Other punctuation (`_`, `-`, `.`, `&`, `/`) is unverified, and two Models sampled
carried custom obj_ids. The `--target-model` path is unaffected (it uses the exported obj_id); the
derived path (`--model-fqn`, every converter) may still mis-bind a name with other punctuation.
Fix by sampling server-generated obj_ids for those characters.

## #9 — Widget measures, measured values, widget filters, ignore, pivots — VERIFIED 2026-11-26

`build-liveboard` now emits widget measures as Answer formulas, measured values as
`group_aggregate` over a conditional aggregate, widget `metadata.ignore` as `group_aggregate`
filter sets, tile filters shadowed by a Liveboard filter as measure conditions, KPI tiles with
a y axis, and flattened pivots as `TABLE_MODE` grids. Verified on **ps-internal** (a test Org)
over a single-table Databricks dataset shaped like a recruiting pipeline (synthetic rows):
the model and a 14-tile Liveboard generated from a real-shaped bundle (with three synthetic
widgets added for `ignore.ids`, `ignore.all` and a Columns-panel pivot) imported with no
error, and every tile returned data. Numbers reconciled with direct SQL on the same table:

- distinct jobs 120, published 83, unpublished 37; distinct applications 2,500; positions
  755, unpublished positions 246; pivot cells (18, 20) and (25, 14) for two companies;
- under a Liveboard runtime filter on the status column: the `ignore.ids` tile and the
  `ignore.all` tile stay 2,500, the measured value "Unpublished Jobs" stays 37, and a tile
  whose own filter is `Status = Published` reads 0 (the Sisense intersection) rather than the
  37 a search filter would give;
- under a runtime filter on the company column: the `ignore.ids` tile narrows to 376 (= SQL)
  while the `ignore.all` tile stays 2,500.

Found during verification: a `GRID_TABLE` emitted in `CHART_MODE` imports cleanly but its
Liveboard tile returns "No data source found for the query"; the same Answer in `TABLE_MODE`
renders. The Sisense path now sets `TABLE_MODE`. The shared emitter
(`ts_cli/tableau/liveboard.build_answer`) still emits `CHART_MODE` for every chart type, so
the other converters' grids are exposed to the same failure (follow-up, not changed here).

Test objects were deleted after verification.

## #10 — UNION of timestamps in a hand-written SQL view — KNOWN (Snowflake)

When a Sisense cube is rebuilt as a ThoughtSpot SQL view (a custom table, or several Sisense
tables unioned into one event table), Snowflake refuses a `UNION` whose branches mix
`TIMESTAMP_NTZ` with `TIMESTAMP_TZ`/`TIMESTAMP_LTZ` columns; casting every timestamp branch to
`::TIMESTAMP_NTZ` fixed it on a production Snowflake migration (2026-11-26). Not reproduced on
ps-internal (no active Snowflake connection there). Databricks does not fail: a `UNION ALL` of
`TIMESTAMP` and `TIMESTAMP_NTZ` returns `TIMESTAMP` (probed 2026-11-26), but the values are
then read in the session time zone, so cast there too when the sources disagree.
