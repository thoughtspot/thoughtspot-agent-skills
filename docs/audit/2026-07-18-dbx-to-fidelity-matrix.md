# ThoughtSpot → Databricks live numeric-fidelity gate — merge gate for `wip/to-databricks-mv-codify`

**Serves:** `references/open-items.md` #8 (Task 18 merge gate) in
`agents/cli/ts-convert-to-databricks-mv/`. Sibling artifact to the **reverse**-direction
matrices (`docs/audit/2026-07-08-dbx-window-claim-matrix.md`,
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`), which live-verified Databricks →
ThoughtSpot construct semantics. This matrix exercises the **forward** path — the
codified `ts databricks build-mv` emit path — end-to-end: a real ThoughtSpot Model, the
emitted DDL, a real Databricks Metric View, and a query battery comparing actual numbers
on both platforms. Same conventions as the 2026-07-09 matrix: env header, statement
ledger, teardown section.

## Environment

- Databricks: profile `ts-production` (oauth-m2m, host `dbc-3472b2da-8a4e.cloud.databricks.com`),
  catalog `agent_skills`, warehouse `c6ed539a60038b93`. All statements via
  `databricks api post /api/2.0/sql/statements --profile ts-production`.
- ThoughtSpot: profile `se-thoughtspot`. Connection `DBX_DAMIAN`
  (`b9e709c6-b951-4b50-a816-b450e6aee278`, type `RDBMS_DATABRICKS`,
  `authentication_type: OAUTH_WITH_SERVICE_PRINCIPAL`) — confirmed live via `ts tml
  export` of the connection object: `host: dbc-3472b2da-8a4e.cloud.databricks.com`,
  `http_path: /sql/1.0/warehouses/c6ed539a60038b93` — exact match to the `ts-production`
  Databricks profile above. **Note:** `ts connections list --profile se-thoughtspot` does
  **not** surface this connection (1755 Snowflake connections returned, zero Databricks) —
  a listing gap, not a missing connection; `ts connections get <guid>` and `ts tml export
  <guid>` both resolve it correctly. Reused, not recreated, per the brief.
- Schema: `agent_skills.ts_dbx_to_fidelity_20260718` — created this run, dropped at
  teardown (see below).
- Fixture: `sales_fixture` — 20 rows, single table, no joins (deliberately — this doubles
  as the live verification for open-items.md #6, the `source.`-prefix-on-a-no-join-MV
  question). Two categories (`Electronics`, `Furniture`), a status column
  (`completed`/`cancelled`) for the filtered-aggregate construct, and a **deliberate one-day
  gap** in Electronics' dates (`2026-06-28` is missing) to exercise the row-positional vs
  date-interval trailing-window divergence in this (TS→DBX) direction, mirroring the
  reverse-direction E1 finding.

  | category | txn_date | customer_id | amount | qty | status |
  |---|---|---|---|---|---|
  | Electronics | 2026-06-25 | C1 | 100 | 1 | completed |
  | Electronics | 2026-06-26 | C2 | 100 | 2 | completed |
  | Electronics | 2026-06-27 | C1 | 100 | 1 | completed |
  | Electronics | 2026-06-29 | C3 | 100 | 1 | **cancelled** |
  | Electronics | 2026-06-30 | C2 | 100 | 2 | completed |
  | Electronics | 2026-07-01 | C4 | 200 | 1 | completed |
  | Electronics | 2026-07-02 | C1 | 200 | 1 | completed |
  | Electronics | 2026-07-03 | C5 | 200 | 2 | completed |
  | Electronics | 2026-07-04 | C2 | 200 | 1 | **cancelled** |
  | Electronics | 2026-07-05 | C4 | 200 | 1 | completed |
  | Furniture | 2026-07-01 | C6 | 50 | 5 | completed |
  | Furniture | 2026-07-02 | C7 | 50 | 5 | completed |
  | Furniture | 2026-07-03 | C6 | 50 | 5 | completed |
  | Furniture | 2026-07-04 | C8 | 50 | 5 | **cancelled** |
  | Furniture | 2026-07-05 | C7 | 50 | 5 | completed |
  | Furniture | 2026-07-06 | C9 | 60 | 6 | completed |
  | Furniture | 2026-07-07 | C6 | 60 | 6 | completed |
  | Furniture | 2026-07-08 | C10 | 60 | 6 | completed |
  | Furniture | 2026-07-09 | C9 | 60 | 6 | **cancelled** |
  | Furniture | 2026-07-10 | C7 | 60 | 6 | completed |

  Note: Electronics' date range spans June (5 rows) and July (5 rows) so the
  period-offset construct (`sum_if(diff_months(...)=0/-1, ...)`) has two real periods to
  compare, satisfying open-items.md #3's "at least one multi-period query" requirement.
  Hand-computed sanity check (confirmed live, statement 3): Electronics
  amount/qty/distinct-customers/completed-amount = 1500/13/5/1200; Furniture =
  550/55/5/440.

- ThoughtSpot objects (created this run, deleted at teardown):
  - Table `TS_FIDELITY_SALES_FIXTURE` — `595c6126-dd75-4d29-ad27-23117c46b1d2`
  - Model `TS Fidelity Sales Model` — `bc9d37e5-b807-400b-a51f-e4f3afcc6d68`
- Emitted DDL: `ts_fidelity_sales_mv` (`agent_skills.ts_dbx_to_fidelity_20260718.ts_fidelity_sales_mv`),
  built via the worktree's `ts databricks build-mv` (isolated `PYTHONPATH` invocation
  per the brief) — 6 dimensions, 8 measures, 0 skipped, 0 warnings on the deploy build.

## Statement ledger (13 of the ≤18 budget)

All statements ran via `databricks api post /api/2.0/sql/statements --profile
ts-production`, warehouse `c6ed539a60038b93`, polled to a terminal state.

| # | Statement | Purpose | Result |
|---|---|---|---|
| 1 | `CREATE SCHEMA IF NOT EXISTS agent_skills.ts_dbx_to_fidelity_20260718` | Seed schema | SUCCEEDED |
| 2 | `CREATE OR REPLACE TABLE ... sales_fixture AS SELECT * FROM VALUES (...)` | Seed 20-row fixture | SUCCEEDED |
| 3 | `SELECT category, COUNT(*), SUM(amount), SUM(qty), COUNT(DISTINCT customer_id), SUM(CASE WHEN status='completed' ...)` | Sanity check vs. hand-calc | SUCCEEDED — exact match |
| 3b | `DESCRIBE TABLE ... sales_fixture` | Confirm physical (lowercase) column names before registering the ThoughtSpot table | SUCCEEDED |
| 4 | `CREATE OR REPLACE VIEW ... WITH METRICS ...` (9-measure build, **including** the `Avg Amount Per Unit` cross-measure ratio as first authored) | First attempt to create the emitted MV | **FAILED** — `[MISSING_AGGREGATION]` (see Finding 1 below) — a real, live-reproduced emitter bug, not a fixture/DDL-execution mistake |
| 5 | `CREATE OR REPLACE VIEW ... ts_fidelity_sales_mv WITH METRICS ...` (8-measure build, ratio column excluded from the `build-mv` input to unblock the rest of the battery) | Create the clean, deployable MV | SUCCEEDED — also the live confirmation of open-items.md #6 (single-source, no-`joins:` MV, `source.`-prefixed columns, parses and creates cleanly) |
| 6 | `SELECT category, MEASURE(amount), MEASURE(qty), MEASURE(distinct_customers), MEASURE(completed_amount) ... GROUP BY category` | Query battery: plain aggregate + COUNT DISTINCT + filtered/conditional aggregate | SUCCEEDED — exact match to TS and hand-calc |
| 7 | `SELECT category, txn_date, MEASURE(amount), ANY_VALUE(category_total_amount) ... GROUP BY category, txn_date` | Query battery: LOD partition, fine grain | SUCCEEDED — exact match |
| 8 | `SELECT category, MEASURE(amount), ANY_VALUE(category_total_amount) ... GROUP BY category` | Query battery: LOD partition, coarse grain | SUCCEEDED — exact match |
| 9 | `SELECT category, txn_date, MEASURE(amount), MEASURE(cumulative_amount), MEASURE(trailing3_amount) ... GROUP BY category, txn_date` | Query battery: window measures (cumulative + trailing 3-day) | SUCCEEDED — cumulative exact match; trailing3 DIVERGENCE on the gapped category (expected, documented) |
| 10 | `SELECT category, month_txn_date, MEASURE(monthly_amount), MEASURE(prior_month_amount) ... GROUP BY category, month_txn_date` | Query battery: period-offset (current/prior month) | SUCCEEDED — confirms the row-relative-vs-wall-clock divergence live (open-items.md #3) |
| 11 | `DROP SCHEMA IF EXISTS agent_skills.ts_dbx_to_fidelity_20260718 CASCADE` | Teardown | SUCCEEDED |
| 12 | `SHOW SCHEMAS IN agent_skills LIKE 'ts_dbx_to_fidelity_20260718'` | Verify teardown | SUCCEEDED — `total_row_count: 0` |

Statement 4's FAILURE is retained in the ledger deliberately — the brief's "if blocked"
clause covers exactly this case ("the DDL fails to create ... report the exact error, do
not hand-patch the .sql"). Rather than aborting the whole gate, the one problematic
formula was excluded from the **input** to `build-mv` (a fresh emit, not an edit of the
emitted `.sql`) so the remaining 8 measures / 6 dimensions could still be verified — see
Finding 1 for the full reproduction and why this is a real emitter gap, not a fixture
mistake.

A 13th statement (`SHOW SCHEMAS ... LIKE 'smoke_ts_to_databricks_mv_fixture'`, verifying
the new smoke test's own `--live` run tore itself down) ran afterward as part of
validating the smoke test deliverable, not part of this gate's own budget.

## Query battery

| Construct family | TS number (searchdata) | DBX number (MEASURE/ANY_VALUE on the MV) | Verdict |
|---|---|---|---|
| Plain aggregate (SUM) | Electronics 1500 / Furniture 550 | Electronics 1500.0 / Furniture 550.0 | **CONFIRMED** |
| Plain aggregate (COUNT DISTINCT) | Electronics 5 / Furniture 5 | Electronics 5 / Furniture 5 | **CONFIRMED** |
| Filtered/conditional aggregate (`sum_if(status='completed', amount)`) | Electronics 1200 / Furniture 440 | Electronics 1200.0 / Furniture 440.0 | **CONFIRMED** |
| LOD partition (`group_aggregate(sum(amount), {category}, query_filters())`), fine grain (category × date) | 1500 / 550 at every row | 1500.0 / 550.0 at every row | **CONFIRMED** |
| LOD partition, coarse grain (category only) | 1500 / 550 | 1500.0 / 550.0 | **CONFIRMED** |
| Window — cumulative (`cumulative_sum(amount, txn_date)`) | Electronics 100,200,300,400,500,700,900,1100,1300,1500; Furniture 50,100,150,200,250,310,370,430,490,550 | Identical, row for row, both categories | **CONFIRMED** — cumulative sums are gap-insensitive (unbounded-preceding), so row-positional and date-interval framings coincide here |
| Window — trailing 3-day (`moving_sum(amount, 3, -1, txn_date)`), **Furniture** (dense, no gaps) | NULL,50,100,150,150,150,160,170,180,180 | Identical | **CONFIRMED** (dense-data control — non-discriminating, as expected) |
| Window — trailing 3-day, **Electronics** (gapped at 06-28) | NULL,100,200,**300,300,300**,400,500,600,600 (row-positional) | NULL,100,200,**200,200,200**,400,500,600,600 (date-interval) | **DIVERGENCE (expected, documented caveat)** — rows 4–6 (06-29, 06-30, 07-01, the rows adjacent to the gap) diverge exactly as `ts-databricks-formula-translation.md`'s density caveat predicts: TS `moving_sum` is row-positional, Databricks `trailing N day` is a genuine date interval. This is the **same root cause as the reverse-direction E1 finding** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`), now confirmed in the TS→DBX direction — not a new bug, a cross-platform semantic gap that any consumer of a `moving_sum`-sourced trailing-window measure must expect on data with date gaps |
| Period-offset (`sum_if(diff_months(txn_date, today())=0/-1, amount)`), current month (query date 2026-07-18 → July) | Electronics 1000 / Furniture 550 | Electronics `month_txn_date=2026-07-01`: 1000.0; Furniture `month_txn_date=2026-07-01`: 550.0 | **CONFIRMED at the current-period row** — coincidence of shape, see caveat below |
| Period-offset, prior month (June) | Electronics 500 / Furniture **0** | Electronics `month_txn_date=2026-06-01`, `prior_month_amount`: **NULL**; Furniture: no June row exists at all, so `prior_month_amount` at the July row = **500** (Electronics June value, LAG-1) — Furniture's July row shows `prior_month_amount` = **NULL** (Furniture has no earlier month-bucket row to look back to) | **DIVERGENCE (documented, architectural — open-items.md #3 resolved)** — see Finding 2 |
| Cross-measure ref (`safe_divide(Amount, Qty)`, both plain physical SUM measures) | Electronics **1300** / Furniture **100** (confirmed via `ts spotql classify-columns`: this formula is `kind: raw_measure`, `wrapper: SUM` — i.e. ThoughtSpot itself computes `SUM(amount/qty)` per row, **sum-of-ratios**, not ratio-of-sums) | **DDL fails to create** — `[MISSING_AGGREGATION]` (statement 4) | **DIVERGENCE — live emitter bug, see Finding 1** |
| Single-source, no-`joins:` MV — `source.`-prefixed columns (open-items.md #6) | n/a | All 14 `source.`-prefixed dimension/measure expressions in the deployed MV parsed and returned correct values (statements 5–10) | **CONFIRMED — #6 flips to VERIFIED** |

All TS-side numbers were fetched via `POST /api/rest/2.0/searchdata`
(`{query_string, logical_table_identifier, record_size}`) — the same workaround the
2026-07-09 matrix used, since `ts spotql fetch-data`/`generate-sql` return `{"status":
"UNKNOWN", ...}` with no error detail against this build (the still-open BL-096 SpotQL
500). `ts spotql classify-columns --model <guid>` (which does not depend on the
data-fetch path) worked normally and was the key diagnostic for Finding 1.

## Finding 1 — Cross-measure ratio of two plain measures is emitted without its required aggregation wrapper (live emitter bug)

**Construct:** a MEASURE-type ThoughtSpot formula composed from a scalar function
(`safe_divide`) over two **plain physical** MEASURE columns (`Amount`, `Qty`, both
`aggregation: SUM`) — i.e. exactly the "ratio of two measures" shape the cross-measure-ref
construct family is meant to cover, just without an intervening formula column on either
side (contrast with `ts-to-databricks.md`'s worked `Category Contribution Ratio`, which
ratios a physical measure against an **LOD formula** column).

**What ThoughtSpot actually computes (live-confirmed):** `ts spotql classify-columns`
classifies `Avg Amount Per Unit` (`safe_divide([Amount],[Qty])`) as `"kind":
"raw_measure"`, `"aggregation": "SUM"`, `"wrapper": "SUM"` — meaning ThoughtSpot's own
query engine treats the formula as an **unaggregated per-row expression** and wraps it in
`SUM(...)` at query time. Confirmed via `searchdata`: Electronics = **1300**, Furniture =
**100** — exactly `Σ(amount_i / qty_i)` per row (sum-of-ratios), not `Σamount / Σqty`
(ratio-of-sums, which would be 115.38 / 10.0). Both are legitimate ThoughtSpot query
results, hand-verified against the fixture.

**What the emitter produces:** `mv_emit.emit_measure`'s formula-backed branch (no
`column_id`) calls `_formula_sql` → `emit_sql` directly and uses the resulting SQL string
as the measure's `expr`, **without ever consulting `col["properties"]["aggregation"]`**
the way the *physical*-column branch does (`_physical_measure_expr(dot_path,
props.get("aggregation"))`, a few lines above in the same function). The emitted DDL
(statement 4) contains:

```yaml
- name: avg_amount_per_unit
  expr: COALESCE(source.amount / NULLIF(source.qty, 0), 0)
  display_name: Avg Amount Per Unit
```

— no `SUM(...)`, no `window:` block, nothing that makes this an aggregate expression.

**Live consequence:** creating the MV with this measure included fails outright:

```
[MISSING_AGGREGATION] The non-aggregating expression
"__mv_src_v106_..._amount" is based on columns which are not participating in
the GROUP BY clause. Add the columns or the expression to the GROUP BY,
aggregate the expression, or use "any_value(...)" if you do not care which of
the values within a group is returned. SQLSTATE: 42803
```

This is not a corner case that merely produces a *wrong* number — it is a **hard DDL
failure** for the entire Metric View (all measures/dimensions in the same
`CREATE OR REPLACE VIEW`), meaning one mis-emitted "raw measure" ratio formula anywhere
in a model can block the whole MV from being created.

**Root cause, precisely scoped:** the gap is not specific to `safe_divide` — it is any
formula-backed MEASURE column whose top-level parsed AST is **not itself already an
aggregate call** (a `sum`/`count`/`group_aggregate`/window function, etc.) — i.e. exactly
what `ts spotql classify-columns` already calls `"raw_measure"` (`needs_agg`-style, though
its own flag name is `needs_agg: false` for the *SpotQL* AGG-wrapper case and instead
surfaces the fix via a separate `"wrapper": "SUM"` field — the point is the classifier
**already computes exactly the information `mv_emit.py` is missing**). Any MEASURE formula
built from arithmetic over two or more physical measures (`[Amount] - [Qty]`, `[Amount] *
1.1`, etc.) would hit the identical gap.

**Not a bug in the fixture or in this test's methodology** — reproduced twice
independently: (a) the live Databricks `[MISSING_AGGREGATION]` error at DDL-create time,
and (b) `ts spotql classify-columns`'s `"kind": "raw_measure"` / `"wrapper": "SUM"`
classification, which is the authoritative signal the emitter should have consulted and
did not.

**Recommended fix (not applied here — per the brief, this task reports, it does not
patch the emitter):** in `mv_emit.emit_measure`'s formula-backed branch, when the parsed
formula's outermost node is not itself an aggregate call, wrap the translated SQL in
`{aggregation}(...)` from `col["properties"]["aggregation"]` (defaulting to `SUM`, matching
the physical-column branch's own default) before assigning it to `expr`. `mv_emit_sql.py`'s
`AGG_MAP` already has everything needed to do this cheaply — the reusable classifier logic
in `ts_cli/spotql_ops.py` (`is_aggregate_expr`/`classify_expr`) may also be directly
reusable rather than re-deriving an equivalent check in the Databricks emitter.

## Finding 2 — Period-offset construct: live confirmation of the row-relative-vs-wall-clock divergence (open-items.md #3)

Resolves open-items.md #3's outstanding requirement for "at least one multi-period query"
against the `sum_if(diff_months(...)=N, [m])` → `window: [{range: current, offset: N
month}]` mapping.

- **ThoughtSpot** computes `Monthly Amount`/`Prior Month Amount` as **wall-clock-scoped
  scalars**: one number per grouping key (`Category`), always meaning "this calendar
  month" / "the calendar month before `today()`" (query date 2026-07-18 → current = July
  2026, prior = June 2026) — invariant of how many rows/periods actually exist in the
  data. Electronics: 1000 / 500. Furniture (no June rows at all): 550 / **0** (TS
  represents "no matching rows" as `0`, not `NULL`).
- **Databricks** computes the *same-named* measures as **row-relative, per-period-bucket**
  values: querying `GROUP BY category, month_txn_date` returns **one row per
  (category, month) combination that exists**, and `prior_month_amount` at each row is a
  `LAG(1)` over that category's own ordered month sequence — not "June 2026" as a fixed
  target. Electronics' July row shows `prior_month_amount = 500` (which *happens* to equal
  TS's wall-clock June reading, because Electronics has exactly one earlier period and it
  is June); Electronics' June row itself shows `prior_month_amount = NULL` (no period
  before June exists in this fixture). Furniture's single (July) row shows
  `prior_month_amount = NULL` (Furniture has no earlier bucket at all) — where TS reports
  `0` for the equivalent "no prior data" case.
- **Verdict:** the coincidental numeric match at the current-period row is exactly that —
  a coincidence of this fixture having only two adjacent periods. The **shape** already
  diverges (DBX returns a full per-month trend table; TS returns one wall-clock snapshot
  per category) and the **edge-case representation** diverges even in this simple fixture
  (`NULL` vs `0` for "no such period"). This is architectural, not a bug: the mapping's own
  documented caveat (`ts-databricks-formula-translation.md` "Corrected 2026-07-09 —
  approximation caveat") is confirmed live and should be treated as understood/accepted,
  per the brief — not a translation-fidelity blocker, but a caveat every consumer of a
  period-offset-derived MV measure must know before building a multi-period trend view on
  top of it.

## Teardown — confirmed complete

- Databricks: `DROP SCHEMA IF EXISTS agent_skills.ts_dbx_to_fidelity_20260718 CASCADE`
  (statement 11) — `SUCCEEDED`. Verified via `SHOW SCHEMAS IN agent_skills LIKE
  'ts_dbx_to_fidelity_20260718'` (statement 12) — `total_row_count: 0`.
- ThoughtSpot: `ts metadata delete bc9d37e5-b807-400b-a51f-e4f3afcc6d68
  595c6126-dd75-4d29-ad27-23117c46b1d2 --profile se-thoughtspot` (model before table) —
  `{"deleted": ["bc9d37e5-...", "595c6126-..."]}`. Verified via `ts metadata search
  --profile se-thoughtspot --name "%fidelity%"` → `[]` and `--name "%TS_FIDELITY%"` → `[]`.
- `DBX_DAMIAN` connection (`b9e709c6-b951-4b50-a816-b450e6aee278`) left untouched — shared
  scratch infrastructure, per the brief and prior precedent (2026-07-09 matrix).
- The new smoke test's own `--live` run creates and tears down an **independent** scratch
  schema (`smoke_ts_to_databricks_mv_fixture`); its cleanup was separately verified
  (`SHOW SCHEMAS ... LIKE 'smoke_ts_to_databricks_mv_fixture'` → `total_row_count: 0`) and
  does not share state with this gate's schema.

## Summary

7 of 8 tested construct families CONFIRMED (plain SUM, COUNT DISTINCT, filtered/conditional
aggregate, LOD partition at two grains, cumulative window, dense-data trailing window,
single-source no-join MV). 2 expected/documented DIVERGENCEs (gapped trailing-window
row-positional-vs-date-interval; period-offset row-relative-vs-wall-clock) matching prior
reverse-direction findings. 1 live, reproducible **emitter bug** found and reported (cross-
measure ratio of two plain measures emitted without its required aggregation wrapper,
causing a hard `[MISSING_AGGREGATION]` DDL failure on Databricks) — not hand-patched, per
the brief; see Finding 1 for the exact reproduction and recommended fix location.
