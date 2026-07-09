# Databricks semantic deep-dive claim matrix — PR 1.5

**Serves:** BL-063 Phase 2 PR 1.5 (`docs/superpowers/specs/2026-07-08-dbx-conversion-substrate-design.md`,
"PR 1.5 — Dimension/metric semantic deep-dive"). Sibling artifact to PR 1's
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` — same conventions, separate claim-ID
namespace (A/B/C/D-prefixed, not C-prefixed) to avoid collision.

## Fixture (Task 2 fills in)

- Catalog: `agent_skills` (reused from PR 1 — confirmed Unity-Catalog-managed)
- Schema: `ts_dbx_substrate_pr15` — created 2026-07-09 (`CREATE SCHEMA IF NOT EXISTS`)
- Fixture tables: `window_fixture` (20 rows — cat X/Y dense 8-day 2026-06-01..08, cat Z gapped
  days 1/2/5/8), `ratio_fixture` (4 rows) — both created 2026-07-09 via `CREATE OR REPLACE
  TABLE ... AS SELECT * FROM VALUES ...`. Sanity check (`SELECT COUNT(*) ...` on both tables)
  returned `window_rows=20`, `ratio_rows=4` — matches expected, no diagnosis needed.
- Metric Views (Task 3, all created 2026-07-09, **all parsed on the first attempt** — the
  `filter:` + dimension-level `OVER (PARTITION BY ...)` combination in `window_filtered_mv`,
  flagged in the brief as never-before-exercised, parsed cleanly; no claim needed a PENDING
  parse-failure flag):
  - `window_filtered_mv` — global `filter: NOT excluded` baked in; covers A1's MV-filter
    condition and all of Battery C
  - `window_nofilter_mv` — no global filter; covers A1's no-filter/query-time conditions, A2,
    and Battery D
  - `ratio_mv` — covers Battery B
- ThoughtSpot connection: `DBX_DAMIAN` (`b9e709c6-b951-4b50-a816-b450e6aee278`) — reused, not
  recreated (Task 4's job to use it)
- ThoughtSpot objects (Task 4, created 2026-07-09 — all four are scratch; Task 7 cleans up):
  - Table `PR15_WINDOW_FIXTURE` — `2eea915d-5837-4ee9-b660-6c08fafe198b`
  - Table `PR15_RATIO_FIXTURE` — `72d0759c-9952-4948-97df-032aafb12abc`
  - Model `PR15_Window_Fixture` — `0fc5abc8-3205-40dd-b938-3215dc140aca`
  - Model `PR15_Ratio_Fixture` — `a7730c30-1d9e-4c93-a762-98743eb0554b`
- Statement ledger (11 of the ≤12 budget, all `SUCCEEDED`, none re-run): (1) `CREATE SCHEMA`,
  (2) `CREATE TABLE window_fixture`, (3) `CREATE TABLE ratio_fixture`, (4) sanity-check
  `SELECT COUNT(*)`, (5) `CREATE VIEW window_filtered_mv`, (6) `CREATE VIEW
  window_nofilter_mv`, (7) Query A/C (`window_filtered_mv`), (8) Query A/A2 (`window_nofilter_mv`
  baseline + query-time filter, UNION ALL), (9) Query D (`window_nofilter_mv` baseline +
  date-range filter, UNION ALL), (10) `CREATE VIEW ratio_mv`, (11) Query B (`ratio_mv`
  fine/coarse/total, UNION ALL).
- **Cleanup (Task 7, 2026-07-09) — confirmed complete:**
  - Databricks: `DROP SCHEMA IF EXISTS agent_skills.ts_dbx_substrate_pr15 CASCADE` executed via
    `databricks api post /api/2.0/sql/statements` (profile `ts-production`, warehouse
    `c6ed539a60038b93`) — `status.state: SUCCEEDED`. Confirmed via `SHOW SCHEMAS IN agent_skills
    LIKE 'ts_dbx_substrate_pr15'`: pre-drop returned 1 row (`ts_dbx_substrate_pr15`), post-drop
    returned `total_row_count: 0`.
  - ThoughtSpot: `ts metadata delete 0fc5abc8-3205-40dd-b938-3215dc140aca
    a7730c30-1d9e-4c93-a762-98743eb0554b 2eea915d-5837-4ee9-b660-6c08fafe198b
    72d0759c-9952-4948-97df-032aafb12abc --profile se-thoughtspot` (both models before both
    tables) — response `{"deleted": [...all 4 GUIDs...]}`. Confirmed via `ts metadata search
    --profile se-thoughtspot --name "PR15_%"` → `[]`.
  - `DBX_DAMIAN` connection (`b9e709c6-b951-4b50-a816-b450e6aee278`) confirmed still present
    (`ts connections get` returned connection metadata, not a 404) — **not** deleted, per the
    brief (shared scratch infrastructure for future PR-1-class work).

**A3 fixture (user-suggested follow-up, 2026-07-09) — recreated after the above cleanup, own
short-lived scratch:**
- Databricks: same `agent_skills.ts_dbx_substrate_pr15` schema + `window_fixture` table
  (identical 20-row CTAS, cat X/Y/Z), recreated via 2 statements (`CREATE SCHEMA IF NOT
  EXISTS`, `CREATE OR REPLACE TABLE ... window_fixture AS SELECT * FROM VALUES ...`) — both
  `SUCCEEDED`. No Metric Views needed — A3 is a TS-side-only probe; the DBX actuals it
  compares against (A1/A2's no-filter/MV-filter/query-time-WHERE readings) were already
  recorded above and were not re-run.
- ThoughtSpot connection: `DBX_DAMIAN` (reused, not recreated).
- ThoughtSpot objects (scratch, cleaned up after this probe — see Task 7-style cleanup note
  at the end of this file): Table `PR15A_WINDOW_FIXTURE` (`8e60c5c2-1622-4ff3-8f1f-58e22ae1bebd`),
  Model `PR15A_Window_Scoping` (`b4cc4f5e-b969-42d6-9bea-8c831934ede7`).

## A — LOD dimensions × filters

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| A1 | `SUM(x) OVER (PARTITION BY dim)` → `group_aggregate(sum(x), {dim}, query_filters())`; the third argument is claimed to make the LOD "respect user-applied filters" | `ts-from-databricks-rules.md:159-176` (esp. line 176), `ts-databricks-formula-translation.md:381-413` (esp. 409-411), `ts-to-databricks-rules.md:244-257`; worked example `ts-to-databricks.md` Formula 3 "Category Quantity" (line ~366) — **verified 2026-05-25 with NO filter ever applied to the query or the MV** | Live DBX (3-condition discriminator: no filter / MV global `filter:` / query-time `WHERE`) + TS number-match (query-level pin vs. model-level filter) | See `### A1 — live results` and `### A1 — TS-side` below — DBX condition-dependent: no-filter=360/8360 (X/Y; Z=160 in every condition), MV global `filter:`=160/4160 (matches a2), query-time `WHERE`=360/8360 (matches a1, i.e. unaffected). TS: baseline=360/8360; query-level pin=160/4160; model-level `filters:`=160/4160 — filter-aware under **both** TS filter kinds | **CONFIRMED (TS-side, live 2026-07-09) + DIVERGENCE caveat (cross-platform)** — the doc claim holds on TS: `query_filters()` makes the LOD respect user-applied filters, under both a query-level pin and a model-level `filters:` block (TS has no filter-blind condition). Cross-platform, that matches DBX's MV-global-`filter:` condition (160/4160) only; DBX's ad hoc query-time `WHERE` is filter-blind (360/8360) and **no `query_filters()`-based TS formula reproduces it** — Task 5 must caveat that the mapping's equivalence holds for the MV-`filter:` condition, not for consumers replicating a DBX query-time `WHERE` |
| A2 | (sub-probe of A1) Whether an MV's own global `filter:` and an ad hoc query-time `WHERE` on the same unfiltered MV produce the *same* LOD value | None — never asked in any existing doc; surfaced during this plan's research | Live DBX only (compare `window_filtered_mv` output to `window_nofilter_mv WHERE ...` output) | See `### A2 — live results` below — MV filter gives 160/4160, query-time WHERE on the same underlying rows gives 360/8360 | **DIVERGENCE (DBX-internal) (live DBX, 2026-07-09)** — an MV's baked-in global `filter:` is filter-aware for a partition-window LOD dimension; an ad hoc query-time `WHERE` on an MV with no global filter is filter-blind for that same dimension (it still removes rows from output, but does not change the window's computed value). **TS-side (live 2026-07-09): the same two-filter-kind probe on ThoughtSpot shows NO difference** — a query-level pin and a model-level `filters:` block both yield 160/4160 for the `query_filters()` LOD (see `### A1 — TS-side`); DBX's filter-kind sensitivity has no TS analogue *(superseded by A3, 2026-07-09 — the analogue exists via `{}`; see the A3 row below and `### A3 — live results`)* |

## A3 — group_aggregate filter-scoping shapes (user-suggested follow-up, 2026-07-09)

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| A3 | (follow-up of A1/A2, user-suggested) `group_aggregate`'s filter argument has documented shapes beyond `query_filters()` — `{}` ("no filters") and a subtraction form `query_filters() - { [TABLE::col] }` (`thoughtspot-formula-patterns.md:383-389`). Decisive question: does `{}` blind the LOD only to **search/query-time** filters, or also to a **model-level** `filters:` block? If `{}` is search-blind but model-aware, `group_aggregate(sum(x), {dim}, {})` + a model-level `filters:` block reproduces DBX's composite (MV-`filter:`-aware + query-`WHERE`-blind) exactly — upgrading A1/A2's "no TS analogue" caveat | `thoughtspot-formula-patterns.md:383-389` (Filter argument table — documents `query_filters()`, `{}`, and subtraction shapes, but not their live search-vs-model-filter scoping); A1/A2 above (the composite this follow-up resolves) | Live TS-only, 3-condition discriminator on a fresh scratch model (`PR15A_Window_Scoping`) over the same `window_fixture` data: (i) no filter, (ii) search-level pin only, (iii) model-level `filters:` block only, each queried against `query_filters()` [control], `{}` [decisive], and the subtraction candidate | See `### A3 — live results` below — `{}` unchanged at 360/8360/160 under (i) and (ii) (blind to the search pin), but narrows to 160/4160/160 under (iii) (aware of the model filter) — identical readings to `query_filters()` under (i) and (iii), diverging only at (ii) | **CONFIRMED — DBX composite REPRODUCIBLE (live TS-only, 2026-07-09).** `group_aggregate(sum(x), {dim}, {})` is filter-blind to search-level/query-time filters but filter-aware of a model-level `filters:` block — exactly DBX's MV-`filter:`-aware + query-time-`WHERE`-blind composite. This **corrects** A1/A2's "no TS analogue" conclusion: the analogue exists, using `{}` instead of `query_filters()`, paired with a model-level filter mirroring the MV's `filter:`. Subtraction candidate `query_filters() - { [TABLE::col] }` (targeting the physical column underlying a derived boolean filter formula) was import-accepted but did **not** exclude the tested filter — see live results for the exact mechanism |

## B — Cross-measure ratio inlining × grain

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| B1 | `MEASURE(a) / MEASURE(b)` inlines to `[a] / [b]` and is claimed (implicitly, by having no grain caveat anywhere) to compute ratio-of-sums correctly at **any** query grain | `ts-from-databricks-rules.md:270-282`, `ts-databricks-formula-translation.md:415-434` (esp. 426, 434) and the quick-lookup row at line 649-651, `ts-to-databricks-rules.md:267-269,281`; worked examples `ts-from-databricks.md` (`avg_order_value`, `return_rate`) and `ts-to-databricks.md` (`category_contribution_ratio`, verification query at line ~1035-1042) — **every one of these was queried at exactly one grain, never compared across grains** | Live DBX (fine / coarse / total grain, one fixture designed so ratio-of-sums ≠ any naive alternative) + TS number-match (`safe_divide(sum(a), sum(b))`, which is definitionally grain-correct — TS side is the control, not the hypothesis under test) | See `### B1 — live results` and `### B1 — TS-side` below — DBX fine/coarse/total all match ratio-of-sums exactly (fine: 10/1/100/10; coarse: 1.818.../18.18...; total: 10); TS `safe_divide(sum(rev), sum(qty))` returns the identical values at all three grains | **CONFIRMED (cross-platform, live 2026-07-09)** — DBX `MEASURE(a) / MEASURE(b)` and TS `safe_divide(sum(a), sum(b))` both compute true ratio-of-sums at every grain tested (fine/coarse/total), with identical values; no sum-of-ratios or average-of-ratios divergence found on either platform |

## C — Global `filter:` × window ordering

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| C1 | A Metric View's `filter:` is a "Global WHERE clause applied to all queries" (schema doc) and is independently claimed to combine safely with any measure, including windowed ones; the shipped worked example `ts-from-databricks.md` **already combines** `filter: status != 'cancelled'` (line 34) with a `revenue_7d_rolling` trailing-7-day window measure (lines 83-86) in the SAME MV, but the two were never queried together to see whether the filter removes rows before or after the window sums them | `databricks-metric-view.md` schema (`filter:` field description, lines 115/229/287, comparison table line 768), `ts-from-databricks-rules.md:358-385` ("Filter → Boolean Formula Column (always)"), `ts-to-databricks-rules.md:179-233`; worked example `ts-from-databricks.md` lines 34, 83-86, 316-319 | Live DBX (one MV, both a filter and a window, alternating included/excluded rows so trailing-3 sums diverge sharply between "filter-before-window" and "filter-after-window") + TS number-match (does a ThoughtSpot model-level `filters:` block filter before or after `moving_sum` computes?) | See `### C1 — live results` and `### C1 — TS-side` below — DBX matches hypothesis (c1-dates) exactly at both cat X and Y, diverging sharply from (c1-rows) and (c2); TS under an equivalent model-level `filters:` block matches **(c1-rows)** exactly (X: NULL/10/40/90; Y: NULL/1010/2040/3090) | DBX hypothesis identity: **(c1-dates) — filter-before-window, DATE-INTERVAL frame** (live DBX, 2026-07-09); TS identity (live 2026-07-09): **(c1-rows) — filter-before-window, ROW-positional frame**. Split verdict: filter ordering **CONFIRMED (cross-platform)** — both platforms filter before the window computes (a TS model-level `filters:` block behaves like DBX's MV global `filter:` in ordering terms); frame semantics **DIVERGENCE (documented caveat)** — TS `moving_sum` counts surviving *rows*, DBX `trailing N day` spans a *date interval*, so the two platforms produce different numbers on filtered (gapped-survivor) data. Same root cause as E1 — a platform divergence to caveat in Task 5, not a formula bug |

## D — Semi-additive × date-range filters

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| D1 | `last_value`/`first_value` (`range: current`, `semiadditive: last`/`first`, raw-date `order:`) collapse to "the last/first observation" per group — PR 1's C7 confirmed this **at the full, unfiltered date range only** (Query A2, `rolling_mv`, no `filter:` present at all); never tested with a query that narrows the date range before the collapse happens | `ts-from-databricks-rules.md:313-334` and `:561-641` (`#### True Semi-Additive`), `ts-databricks-formula-translation.md:438-478`, `ts-to-databricks-rules.md:291-361`; PR 1's C7 in `docs/audit/2026-07-08-dbx-window-claim-matrix.md` (CONFIRMED, but at full-range only); `thoughtspot-formula-patterns.md:408-432` (Semi-Additive Functions — platform-agnostic TS reference, same untested gap) | Live DBX (query-time date-range `WHERE` narrower than the full fixture range, both ends) + TS number-match (`last_value`/`first_value` under an equivalent query-level date-range filter) | See `### D1 — live results` and `### D1 — TS-side` below — DBX matches hypothesis (d1) exactly at both cat X and Y; TS under an equivalent query-level date-range pin returns the identical values (X 6/3, Y 106/103, Z 5/5) | DBX hypothesis identity: **(d1) — last/first-in-filtered-range** (live DBX, 2026-07-09); TS identity (live 2026-07-09): **(d1)** as well. **CONFIRMED (cross-platform)** — `last_value`/`first_value` under a query-level date-range pin collapses to the last/first observation *within the filtered range* on both platforms, identical values at X/Y and at the single-surviving-row Z edge case |

## E — Trailing-window frame semantics (rows vs. dates)

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| E1 | DBX `trailing N day` frame semantics: **row-positional vs. date-interval**. PR 1's C1 CONFIRMED verdict (`moving_sum([m], N, -1, [date])` ≡ `trailing N day` default/exclusive) was obtained on **dense daily data only** (one row per day, no gaps), where the two framings are indistinguishable — the CONFIRMED verdict is density-conditional, the same non-discriminating-verification failure mode this PR closes. TS `moving_sum` is documented **row-positional** (`ts-from-databricks-rules.md:702-713` — "based on row counts, so this assumes one row per day (daily grain)"); if DBX's frame is a date interval, every PR-1-corrected trailing/leading mapping silently breaks on sparse data. | PR 1 matrix C1 (`docs/audit/2026-07-08-dbx-window-claim-matrix.md`); `ts-from-databricks-rules.md:702-713` row-counts note | Live DBX (gapped cat `Z` rides Battery C's existing query — Z has no excluded rows, isolating rows-vs-dates from the filter question) + TS number-match (Z-probe on `PR15_Window_Fixture`, row-positional expectation) | See `### E1 — live results` and `### E1 — TS-side` below — DBX: Z's gapped trailing-window matches the DATE-INTERVAL column exactly (NULL/10/20/50), diverging from ROW-positional at days 5/8; TS Z-probe: matches the ROW-positional column exactly (NULL/10/30/80), diverging from DBX at the same two days | DBX rows-vs-dates identity: **RESOLVED — DATE-INTERVAL** (live DBX, 2026-07-09); TS Z-probe (live 2026-07-09): `moving_sum` is **ROW-positional**, exactly as documented. **DIVERGENCE (cross-platform, documented caveat)** — on gapped data DBX `trailing N day` (date-interval) and TS `moving_sum(m, N, -1, d)` (row-positional) produce different numbers (Z days 5/8: DBX 20/50 vs TS 30/80); PR 1's C1/C3 CONFIRMED verdicts were density-conditional. Density caveat required in the mapping docs (Task 5) — a potential translation-fidelity blocker on sparse data (Task 5/6 to decide phrasing/mitigation) |

## Live results convention

Same as PR 1's matrix: Tasks 3-4 append full query + result-set detail under a
`### <ID> — live results` subsection per claim; the table's `Actual (live)` cell holds only a
short pointer/summary. Do not touch the `Claim`/`Source` columns once seeded.

---

## Live results (Task 3)

All 11 statements below ran live against `agent_skills.ts_dbx_substrate_pr15` on 2026-07-09.
All three Metric Views (`window_filtered_mv`, `window_nofilter_mv`, `ratio_mv`) parsed and
created successfully on the first attempt — the `filter:` + dimension-level
`OVER (PARTITION BY ...)` combination in `window_filtered_mv`, flagged in the brief as
never-before-exercised, parsed cleanly. No claim needed a PENDING parse-failure flag.

### A1 — live results

**Query A/C** (`window_filtered_mv` — MV global `filter: NOT excluded` baked in):
```sql
SELECT cat, txn_date,
  ANY_VALUE(category_total_amount) AS category_total_amount,
  MEASURE(daily_amount)    AS daily_amount,
  MEASURE(trailing3_amount) AS trailing3_amount
FROM agent_skills.ts_dbx_substrate_pr15.window_filtered_mv
GROUP BY cat, txn_date
ORDER BY cat, txn_date
```

Full 12-row result (surviving odd days 1/3/5/7 for X/Y, all 4 Z rows — none dropped since Z has
no `excluded = true` rows; this result also feeds C1 and E1 below — not repeated per claim):

| cat | txn_date | category_total_amount | daily_amount | trailing3_amount |
|---|---|---|---|---|
| X | 2026-06-01 | 160.0 | 10.0 | NULL |
| X | 2026-06-03 | 160.0 | 30.0 | 10.0 |
| X | 2026-06-05 | 160.0 | 50.0 | 30.0 |
| X | 2026-06-07 | 160.0 | 70.0 | 50.0 |
| Y | 2026-06-01 | 4160.0 | 1010.0 | NULL |
| Y | 2026-06-03 | 4160.0 | 1030.0 | 1010.0 |
| Y | 2026-06-05 | 4160.0 | 1050.0 | 1030.0 |
| Y | 2026-06-07 | 4160.0 | 1070.0 | 1050.0 |
| Z | 2026-06-01 | 160.0 | 10.0 | NULL |
| Z | 2026-06-02 | 160.0 | 20.0 | 10.0 |
| Z | 2026-06-05 | 160.0 | 50.0 | 20.0 |
| Z | 2026-06-08 | 160.0 | 80.0 | 50.0 |

**Query A/A2** (`window_nofilter_mv` — no global filter; baseline + query-time filter, UNION ALL):
```sql
SELECT 'baseline' AS scenario, cat,
  ANY_VALUE(category_total_amount) AS category_total_amount
FROM agent_skills.ts_dbx_substrate_pr15.window_nofilter_mv
GROUP BY cat
UNION ALL
SELECT 'query_time_filter' AS scenario, cat,
  ANY_VALUE(category_total_amount) AS category_total_amount
FROM agent_skills.ts_dbx_substrate_pr15.window_nofilter_mv
WHERE NOT excluded
GROUP BY cat
ORDER BY scenario, cat
```

| scenario | cat | category_total_amount |
|---|---|---|
| baseline | X | 360.0 |
| baseline | Y | 8360.0 |
| baseline | Z | 160.0 |
| query_time_filter | X | 360.0 |
| query_time_filter | Y | 8360.0 |
| query_time_filter | Z | 160.0 |

**A1 finding.** Three live conditions, compared against the Battery A hand-computed table:

| Condition | Actual (X / Y) | Matches |
|---|---|---|
| No filter at all (baseline) | 360 / 8360 | Both hypotheses agree by construction |
| MV global `filter: NOT excluded` (Query A/C) | 160 / 4160 | **(a2) filter-aware** |
| Query-time `WHERE NOT excluded` on `window_nofilter_mv` (Query A/A2) | 360 / 8360 | **(a1) filter-blind** (identical to baseline) |

Cat Z reads 160 in every condition (Query A/C, both A/A2 scenarios) — confirming the brief's
prediction that Z is a no-op for Battery A (its rows are never `excluded`).

**Result: A1 has no single hypothesis winner.** The behavior is *condition-dependent*: an MV's
baked-in global `filter:` participates in whatever the window/LOD dimension computes over
(filter-aware, hypothesis a2), while an ad hoc query-time `WHERE` clause applied on top of an
MV with no global filter does **not** change the window's own value — it still removes rows
from the output (in both filtered scenarios only 12 of the 20 underlying rows survive — X/Y's
4 odd days each plus Z's 4 rows — grouped to 3 output rows per scenario in these cat-grain
queries) but the `SUM(amount) OVER (PARTITION BY cat)` dimension itself was already computed
inside the view before that outer `WHERE` is applied. This is not one of the brief's two named
hypotheses cleanly — it is a *third pattern*: "which kind of filter" determines the answer, not
"is a filter active." TS-side number-match against the two ThoughtSpot candidate formulas
(query-level pinned filter vs. model-level `filters:` block) was Task 4's job — **that ran on
2026-07-09; see `### A1 — TS-side` below** — and the A1 Verdict is now recorded; A2 (below) is
the sub-question this same evidence directly decides.

### A2 — live results

Directly derived from A1's two live conditions above, on the identical underlying
`window_fixture` rows: `window_filtered_mv`'s baked-in `filter: NOT excluded` produces
`category_total_amount` = 160 (X) / 4160 (Y); `window_nofilter_mv WHERE NOT excluded` (an ad
hoc query-time filter, no MV-level filter) produces 360 (X) / 8360 (Y) for the same dimension.

**Verdict: DIVERGENCE (DBX-internal) (live DBX-only, 2026-07-09).** An MV's own global `filter:` and an ad hoc
query-time `WHERE` on an unfiltered MV do NOT produce the same value for a partition-window LOD
dimension — the MV-level filter is baked into whatever the `OVER (PARTITION BY ...)` expression
sees, while the query-time `WHERE` is applied outside/after that computation and only prunes
output rows.

### B1 — live results

**Query B** (`ratio_mv`, fine/coarse/total grain, UNION ALL):
```sql
SELECT 'fine' AS grain, cat, CAST(txn_date AS STRING) AS grain_key,
  MEASURE(revenue) AS revenue, MEASURE(qty) AS qty, MEASURE(rev_qty_ratio) AS ratio
FROM agent_skills.ts_dbx_substrate_pr15.ratio_mv
GROUP BY cat, txn_date
UNION ALL
SELECT 'coarse' AS grain, cat, CAST(NULL AS STRING) AS grain_key,
  MEASURE(revenue) AS revenue, MEASURE(qty) AS qty, MEASURE(rev_qty_ratio) AS ratio
FROM agent_skills.ts_dbx_substrate_pr15.ratio_mv
GROUP BY cat
UNION ALL
SELECT 'total' AS grain, CAST(NULL AS STRING) AS cat, CAST(NULL AS STRING) AS grain_key,
  MEASURE(revenue) AS revenue, MEASURE(qty) AS qty, MEASURE(rev_qty_ratio) AS ratio
FROM agent_skills.ts_dbx_substrate_pr15.ratio_mv
ORDER BY grain, cat
```

| grain | cat | grain_key | revenue | qty | ratio |
|---|---|---|---|---|---|
| coarse | X | NULL | 20.0 | 11.0 | 1.818181818181818 |
| coarse | Y | NULL | 200.0 | 11.0 | 18.181818181818182 |
| fine | X | 2026-06-01 | 10.0 | 1.0 | 10.000000000000000 |
| fine | X | 2026-06-02 | 10.0 | 10.0 | 1.000000000000000 |
| fine | Y | 2026-06-01 | 100.0 | 1.0 | 100.000000000000000 |
| fine | Y | 2026-06-02 | 100.0 | 10.0 | 10.000000000000000 |
| total | NULL | NULL | 220.0 | 22.0 | 10.000000000000000 |

Compared against the hand-computed ratio-of-sums table: fine grain {10, 1, 100, 10}, coarse
grain {1.818..., 18.18...}, total {10} — **exact match at every grain, no rounding needed.**
None of the sum-of-ratios (X-coarse=11, total=121) or average-of-ratios (X-coarse=5.5,
total=30.25) alternatives the brief flagged as live possibilities appear anywhere in the actual
output.

**Verdict: CONFIRMED (live DBX-only, 2026-07-09).** `MEASURE(revenue) / MEASURE(qty)` computes
true ratio-of-sums at every grain tested (fine/coarse/total) — the mapping's implicit any-grain
assumption holds; no grain-pinning divergence found.

### C1 — live results

Same Query A/C result set as A1 above (`window_filtered_mv`). Isolating `trailing3_amount` for
the 4 surviving odd days of cat X and Y against the three Battery C hypotheses:

| cat | day (surviving) | ACTUAL | (c1-rows) | (c1-dates) | (c2) |
|---|---|---|---|---|---|
| X | 1 | NULL | NULL | NULL | NULL |
| X | 3 | 10 | 10 | 10 | 30 |
| X | 5 | 30 | 40 | 30 | 90 |
| X | 7 | 50 | 90 | 50 | 150 |
| Y | 1 | NULL | NULL | NULL | NULL |
| Y | 3 | 1010 | 1010 | 1010 | 2030 |
| Y | 5 | 1030 | 2040 | 1030 | 3090 |
| Y | 7 | 1050 | 3090 | 1050 | 3150 |

Actual matches the **(c1-dates)** column exactly at every row for both categories, diverging
sharply from (c1-rows) at days 5/7 (30/50 vs. 40/90 for X) and from (c2) everywhere a window is
non-null (30/50 vs. 90/150 for X).

**DBX hypothesis identity: (c1-dates) — filter-before-window, DATE-INTERVAL frame (live
DBX-only, 2026-07-09).** The filter removes even-day rows before the window computes, and the
`trailing 3 day` window's range is a genuine date-interval `[anchor−3, anchor−1]` intersected
with survivors — not a row-positional "3 preceding survivor rows" count. TS-side comparison
(does ThoughtSpot's model-level `filters:` block interact with `moving_sum` the same way?) ran
on 2026-07-09 — see `### C1 — TS-side` below; the C1 Verdict is now recorded (split:
filter-ordering CONFIRMED, frame DIVERGENCE).

### D1 — live results

**Query D** (`window_nofilter_mv`, semi-additive baseline + date-range filter, UNION ALL):
```sql
SELECT 'baseline' AS scenario, cat,
  MEASURE(balance_last)  AS balance_last,
  MEASURE(balance_first) AS balance_first
FROM agent_skills.ts_dbx_substrate_pr15.window_nofilter_mv
GROUP BY cat
UNION ALL
SELECT 'date_range_filtered' AS scenario, cat,
  MEASURE(balance_last)  AS balance_last,
  MEASURE(balance_first) AS balance_first
FROM agent_skills.ts_dbx_substrate_pr15.window_nofilter_mv
WHERE txn_date BETWEEN DATE'2026-06-03' AND DATE'2026-06-06'
GROUP BY cat
ORDER BY scenario, cat
```

| scenario | cat | balance_last | balance_first |
|---|---|---|---|
| baseline | X | 8.0 | 1.0 |
| baseline | Y | 108.0 | 101.0 |
| baseline | Z | 8.0 | 1.0 |
| date_range_filtered | X | 6.0 | 3.0 |
| date_range_filtered | Y | 106.0 | 103.0 |
| date_range_filtered | Z | 5.0 | 5.0 |

Compared against the hand-computed table:

| Scenario | (d1) in-filtered-range | (d2) in-full-data | ACTUAL |
|---|---|---|---|
| balance_last, X | 6 | 8 | **6** |
| balance_first, X | 3 | 1 | **3** |
| balance_last, Y | 106 | 108 | **106** |
| balance_first, Y | 103 | 101 | **103** |

Baseline (no filter): X = 8/1, Y = 108/101 — matches both hypotheses (non-discriminating,
recorded for completeness). Cat Z rides the same query at no extra cost: baseline = 8/1 (day
8's balance=8, day 1's balance=1); date-range-filtered (06-03..06-06) = 5/5 — only Z's day-5 row
(06-05) falls inside the filtered range, so last=first=5 by construction (a single surviving
row), consistent with but not independently discriminating for either hypothesis.

**DBX result: matches hypothesis (d1) — last/first-in-filtered-range — exactly, at both cat X
and Y.** The semi-additive `last`/`first` collapse operates on the rows that survive the
query-time date-range filter, not on the full unfiltered dataset. TS-side comparison (does
ThoughtSpot's `last_value`/`first_value` under an equivalent query-level date filter behave the
same way?) ran on 2026-07-09 — see `### D1 — TS-side` below; the D1 Verdict is now recorded
(CONFIRMED cross-platform).

### E1 — live results

Same Query A/C result set as A1/C1 above (`window_filtered_mv`) — cat Z's 4 rows (all
`excluded = false`, none dropped by the filter, isolating the frame question from the filter
question):

| Z day_index / date | ACTUAL | ROW-positional | DATE-interval |
|---|---|---|---|
| 1 / 06-01 | NULL | NULL | NULL |
| 2 / 06-02 | 10 | 10 | 10 |
| 5 / 06-05 | 20 | 30 | 20 |
| 8 / 06-08 | 50 | 80 | 50 |

Actual matches the **DATE-interval** column exactly at every row, diverging sharply from
ROW-positional at days 5 and 8 (20 vs. 30; 50 vs. 80).

**DBX rows-vs-dates identity: RESOLVED — DATE-INTERVAL (live DBX-only, 2026-07-09).**
Databricks' `trailing N day` frame is a genuine date-interval window, not a row-count window —
on gapped data the two framings diverge and DBX takes the date-interval reading. This confirms
the concern the claim raised: PR 1's C1 CONFIRMED verdict (`moving_sum([m], N, -1, [date]) ≡
trailing N day` default/exclusive) was obtained on dense, gapless daily data where
row-positional and date-interval framings are indistinguishable — that verdict needs a density
caveat in the mapping docs (every trailing/leading mapping built on `moving_sum`, which is
documented row-positional, silently diverges from DBX's actual date-interval semantics whenever
the underlying data has date gaps). TS-side comparison (Z-probe against a ThoughtSpot Model, per
the claim's verification method) ran on 2026-07-09 — see `### E1 — TS-side` below; the E1
Verdict is now recorded (DIVERGENCE cross-platform: TS row-positional vs. DBX date-interval).

---

## TS-side number-match results (Task 4, live 2026-07-09)

All queries below ran live on 2026-07-09 against `se-thoughtspot`, connection `DBX_DAMIAN`,
models `PR15_Window_Fixture` (`0fc5abc8-3205-40dd-b938-3215dc140aca`) and
`PR15_Ratio_Fixture` (`a7730c30-1d9e-4c93-a762-98743eb0554b`), over the same
`agent_skills.ts_dbx_substrate_pr15.*` fixture tables Task 3 used. Tables were registered via
`ts tables create` (GUIDs in the Fixture section above); `ts tml export` confirmed
`db_column_name` matches the physical name on every column of both tables.

**Execution path (same as PR 1's Task 5):** the SpotQL data endpoints still 500 on this build
(BL-096), so data was fetched via `POST /api/rest/2.0/searchdata` through the scratchpad
script reusing `ts_cli.client.ThoughtSpotClient` for auth. `ts spotql classify-columns
--model` ran first and classified as expected (base columns plain; the five formulas:
`LOD Category Total` and `Excluded Filter` ATTRIBUTE, the three window/semi-additive formulas
`aggregate_measure`). All imports used `< /dev/null` (BL-097). Date-range pin token syntax
that worked first try: `[Txn Date] >= '06/03/2026' [Txn Date] <= '06/06/2026'` (MM/DD/YYYY,
two chained comparison tokens — no `between` keyword needed). Boolean pin token:
`[Excluded Filter] = 'true'`.

**Import iterations:** zero content failures. Window model: 1 first-try create + 2 planned
in-place updates (Step 4 add `filters:` block, Step 6 revert it — both `guid:` at document
root, both first-try OK). Ratio model: first-try create. The step order followed the brief:
baseline + query-pin + Z-probe ran BEFORE the model filter existed; Battery D ran after the
filter was reverted (the D baseline reading X=8 — an even, `excluded=true` day — independently
confirms the revert took effect).

### A1 — TS-side

Model formula under test: `group_aggregate ( sum ( [amount] ) , { [cat] } , query_filters ( ) )`
(ATTRIBUTE), with `Excluded Filter` = `[excluded] = false` (ATTRIBUTE formula).

| Condition | Search tokens | Actual (X / Y / Z) | Matches DBX condition |
|---|---|---|---|
| Baseline (no filter anywhere) | `[Cat] [LOD Category Total]` | 360 / 8360 / 160 | = DBX no-filter (360/8360/160) |
| Query-level pin | `[Cat] [LOD Category Total] [Excluded Filter] = 'true'` | 160 / 4160 / 160 | = DBX MV global `filter:` (160/4160); ≠ DBX query-time `WHERE` (360/8360) |
| Model-level `filters:` block (Step 4 in-place update) | `[Cat] [LOD Category Total]` | 160 / 4160 / 160 | = DBX MV global `filter:` (160/4160) |

**TS finding.** `query_filters()` is filter-AWARE under **both** ThoughtSpot filter kinds — a
query-level pin and a model-level `filters:` block produce the identical 160/4160 reading. The
doc claim ("respects user-applied filters") is CONFIRMED on the TS side. Cross-platform, TS
matches DBX's MV-global-`filter:` condition only: DBX's ad hoc query-time `WHERE` is
filter-blind (360/8360), and ThoughtSpot exhibits no filter-blind condition for a
`query_filters()` LOD — DBX's third-pattern ("which kind of filter" matters) has **no TS
analogue** *(superseded by A3, 2026-07-09: the analogue exists via the `{}` filter argument —
see `### A3 — live results`; this sentence is scoped to the `query_filters()` form only)*
(that is A2's TS-side answer). Task 5 must caveat the A1 mapping accordingly: the
equivalence DBX MV `filter:` ↔ TS filter holds; a DBX consumer's query-time `WHERE` semantics
cannot be reproduced by the `query_filters()` form.

### B1 — TS-side

Model formula: `safe_divide ( sum ( [rev] ) , sum ( [qty] ) )` on `PR15_Ratio_Fixture`.

| Grain | Search tokens | Actual |
|---|---|---|
| Fine | `[Cat] [Txn Date].'daily' [Rev] [Qty] [Rev Qty Ratio]` | X 06-01: 10, X 06-02: 1, Y 06-01: 100, Y 06-02: 10 |
| Coarse | `[Cat] [Rev] [Qty] [Rev Qty Ratio]` | X: 1.818181818181818, Y: 18.181818181818183 |
| Total | `[Rev] [Qty] [Rev Qty Ratio]` | 10 |

Identical to the DBX actuals at every grain (fine {10, 1, 100, 10}; coarse {1.818...,
18.18...}; total {10}) — exact ratio-of-sums on both platforms. **B1 Verdict: CONFIRMED
(cross-platform).** The control behaved as expected; Task 5 needs no grain caveat for this
mapping.

### C1 — TS-side

With the Step 4 model-level `filters:` block active (`Excluded Filter in ('true')`), search
`[Cat] [Txn Date].'daily' [Amount] [Trailing3 Amount]` returned exactly the 12 surviving rows
(X/Y odd days + all 4 Z rows), mirroring DBX's filtered-MV output rows. `Trailing3 Amount` =
`moving_sum ( [amount] , 3 , -1 , [txn_date] )` per surviving day, against the hypotheses:

| cat | day (surviving) | TS ACTUAL | (c1-rows) | (c1-dates) = DBX actual | (c2) |
|---|---|---|---|---|---|
| X | 1 | NULL | NULL | NULL | NULL |
| X | 3 | 10 | 10 | 10 | 30 |
| X | 5 | 40 | 40 | 30 | 90 |
| X | 7 | 90 | 90 | 50 | 150 |
| Y | 1 | NULL | NULL | NULL | NULL |
| Y | 3 | 1010 | 1010 | 1010 | 2030 |
| Y | 5 | 2040 | 2040 | 1030 | 3090 |
| Y | 7 | 3090 | 3090 | 1050 | 3150 |

(Z rode along unchanged: NULL/10/30/80 — same as the Step 3a Z-probe, as expected since no Z
row is excluded.)

**TS identity: (c1-rows) — filter-before-window, ROW-positional frame** — exactly the
row-positional prediction, matched at every row. Filter ordering agrees with DBX (both
filter-before-window: the model filter removes even days before `moving_sum` sees them); frame
semantics diverge (TS sums the 3 preceding *surviving rows*, DBX intersects a 3-*day* interval
with survivors). **C1 Verdict: split — filter-ordering CONFIRMED (cross-platform), frame
DIVERGENCE (documented caveat, same root cause as E1).** This is a platform divergence on
filtered/gapped data to record honestly — not a formula bug to fix by trial.

### D1 — TS-side

Model filter reverted first (Step 6 in-place re-import without `filters:`). Formulas:
`last_value ( sum ( [balance] ) , query_groups ( ) , { [txn_date] } )` and the `first_value`
twin.

| Condition | Search tokens | Actual (Balance Last / Balance First) |
|---|---|---|
| Baseline (full range) | `[Cat] [Balance Last] [Balance First]` | X 8/1, Y 108/101, Z 8/1 |
| Date-range pin 06-03..06-06 | `[Cat] [Balance Last] [Balance First] [Txn Date] >= '06/03/2026' [Txn Date] <= '06/06/2026'` | X 6/3, Y 106/103, Z 5/5 |

Identical to DBX in both conditions, including the Z single-surviving-row edge case (5/5).
**D1 Verdict: CONFIRMED (cross-platform) — identity (d1), last/first-in-filtered-range** on
both platforms: the semi-additive collapse operates on the rows that survive the date-range
filter, matching DBX's Query D exactly.

### E1 — TS-side (Z-probe)

Run in the no-model-filter phase (Step 3a, before the Step 4 filter existed). Search:
`[Cat] [Txn Date].'daily' [Amount] [Trailing3 Amount] [Cat] = 'Z'` — 4 rows:

| Z day_index / date | TS ACTUAL | ROW-positional | DATE-interval = DBX actual |
|---|---|---|---|
| 1 / 06-01 | NULL | NULL | NULL |
| 2 / 06-02 | 10 | 10 | 10 |
| 5 / 06-05 | 30 | 30 | 20 |
| 8 / 06-08 | 80 | 80 | 50 |

TS matches the ROW-positional column exactly — `moving_sum` behaves as documented
(`ts-from-databricks-rules.md:702-713`), diverging from DBX's date-interval reading at both
gapped days (30 vs 20; 80 vs 50). **E1 Verdict: DIVERGENCE (cross-platform, documented
caveat)** — on gapped data, DBX `trailing N day` and TS `moving_sum(m, N, -1, d)` produce
different numbers; PR 1's C1/C3 equivalences are density-conditional (dense daily data only).
Task 5 must add the density caveat to the mapping docs; this is a potential
translation-fidelity blocker on sparse data for Tasks 5/6 to phrase (e.g. densification or a
"verify data density" pre-check), not a formula bug fixable by a different `moving_sum` shape.

---

## A3 — live results (user-suggested follow-up, 2026-07-09)

Ran entirely against a fresh scratch model, `PR15A_Window_Scoping`
(`b4cc4f5e-b969-42d6-9bea-8c831934ede7`), over `PR15A_WINDOW_FIXTURE`
(`8e60c5c2-1622-4ff3-8f1f-58e22ae1bebd`) — the identical `window_fixture` rows A1/A2/E1 used,
re-registered under a distinct table name to avoid colliding with the (already cleaned up)
Task 4 objects. `ts spotql classify-columns --model` confirmed all four candidate columns
classify as plain ATTRIBUTE (no `AGG()` wrapping needed in search tokens). Formulas under
test, all `column_type: ATTRIBUTE`:

- `LOD QF` = `group_aggregate ( sum ( [amount] ) , { [cat] } , query_filters ( ) )` — control,
  identical construct to A1.
- `LOD Blind` = `group_aggregate ( sum ( [amount] ) , { [cat] } , {} )` — the decisive
  candidate. **Import-accepted on the first attempt** — no error, contrary to the possibility
  that `{}` (documented "untranslatable" cross-platform in `thoughtspot-formula-patterns.md:387`)
  might also be TS-import-rejected; "untranslatable" there refers only to the Snowflake SV
  mapping, not TS's own parser.
- `Excluded Filter` = `[excluded] = false` — same boolean pin/model-filter target as A1.
- `LOD Subtract` = `group_aggregate ( sum ( [amount] ) , { [cat] } , query_filters ( ) - {
  [excluded] } )` — subtraction candidate per `thoughtspot-formula-patterns.md:389`'s
  documented `query_filters() - { [TABLE::col] }` shape, targeting the raw `excluded` column
  (the physical column the `Excluded Filter` boolean formula wraps). **Also
  import-accepted on the first attempt**, in the same `ALL_OR_NONE` batch as the other three
  formulas.

**Query grid** (`searchdata`, BL-096 workaround, same scratch script pattern as Task 4):

| Condition | Search tokens | LOD QF (X/Y/Z) | LOD Blind (X/Y/Z) | LOD Subtract (X/Y/Z) |
|---|---|---|---|---|
| (i) No filter anywhere | `[Cat] [LOD QF] [LOD Blind] [LOD Subtract]` | 360/8360/160 | 360/8360/160 | 360/8360/160 |
| (ii) Search-level pin only | `[Cat] [LOD QF] [LOD Blind] [LOD Subtract] [Excluded Filter] = 'true'` | 160/4160/160 | **360/8360/160** | 160/4160/160 |
| (iii) Model-level `filters:` block only (no pin; TML updated in-place, `guid` at doc root) | `[Cat] [LOD QF] [LOD Blind] [LOD Subtract]` | 160/4160/160 | **160/4160/160** | 160/4160/160 |

(i) is non-discriminating by construction (no filter anywhere — all three read the full
unfiltered total; Z=160 throughout since no Z row is ever excluded, same no-op role it played
in A1/A2/E1). (ii) and (iii) are the decisive rows:

- **(ii) search-level pin:** `LOD Blind` stayed at 360/8360 — **unchanged from baseline** —
  while `LOD QF` and `LOD Subtract` both dropped to 160/4160. `{}` is **blind to a
  search-level/query-time filter**, exactly like DBX's ad hoc query-time `WHERE` on an MV with
  no global filter (A1/A2's `a1` reading, 360/8360).
- **(iii) model-level filter:** `LOD Blind` dropped to 160/4160 — **identical to `LOD QF`
  under the same condition**. `{}` is **aware of a model-level `filters:` block**, exactly
  like DBX's own MV-baked-in global `filter:` (A1/A2's `a2` reading, 160/4160).

**A3 finding.** `{}` is not simply "ignore every filter" — it specifically excludes ad hoc
**query-level** filters (the ones `query_filters()` would otherwise pass through) while still
sitting downstream of whatever a **model-level** `filters:` block has already restricted the
underlying data to. This is architecturally consistent with how ThoughtSpot resolves the two
filter kinds: a model-level `filters:` block is baked into the model's own query plan (analogous
to a Databricks MV's global `filter:`, which is baked into the view), while a search-level pin
is a query-time filter (analogous to a Databricks ad hoc query-time `WHERE`) that only
`query_filters()` — not `{}` — pulls into the LOD's own aggregation.

**Subtraction candidate finding.** `query_filters() - { [PR15A_WINDOW_FIXTURE::excluded] }`
was import-accepted (documented syntax, per `thoughtspot-formula-patterns.md:389`) but produced
**no observable exclusion effect** in this test — under condition (ii) it read identically to
plain `query_filters()` (160/4160), not to `{}` (360/8360). The pin/model filter in this fixture
is applied to `Excluded Filter`, a *derived* boolean formula (`[excluded] = false`), not to the
raw `excluded` column directly — ThoughtSpot's query-filter provenance tracks the column the
filter predicate was actually applied to (the formula), not that formula's underlying physical
dependency, so subtracting the raw column does not remove the filter. Recorded as a live
finding about the subtraction form's exact semantics, not a usable alternative to `{}` for this
kind of derived-filter scenario.

**A3 Verdict: CONFIRMED — DBX composite REPRODUCIBLE (live TS-only, 2026-07-09).**
`group_aggregate(sum(x), {dim}, {})`, paired with a model-level `filters:` block mirroring the
Databricks MV's own `filter:`, reproduces **both halves** of DBX's composite behavior recorded
in A1/A2 — MV-`filter:`-aware AND query-time-`WHERE`-blind — in a single ThoughtSpot construct.
This **corrects** A1/A2's "DBX's filter-kind sensitivity has no TS analogue" conclusion: the
analogue exists, it just requires `{}` instead of `query_filters()`, deliberately paired with a
model-level filter equivalent to the MV's `filter:`. `query_filters()` remains the right default
mapping for the common case (an MV's global `filter:`, with a simpler formula and no
requirement to also emit a matching model-level `filters:` block) — `{}` is the refinement for
a consumer specifically needing to reproduce a DBX ad hoc query-time `WHERE`'s filter-blind LOD
behavior. See Task 5-equivalent doc updates in `ts-from-databricks-rules.md`,
`ts-to-databricks-rules.md`, `ts-databricks-formula-translation.md`,
`ts-databricks-properties.md`, `databricks-metric-view.md`, `thoughtspot-formula-patterns.md`,
both `ts-convert-*-databricks-mv/SKILL.md`, and `ts-to-databricks.md` (Formula 3).

**A3 cleanup (2026-07-09) — confirmed complete, second cleanup pass distinct from the Task 7
pass recorded in the Fixture section above:**
- Databricks: `DROP SCHEMA IF EXISTS agent_skills.ts_dbx_substrate_pr15 CASCADE` re-run
  (profile `ts-production`, warehouse `c6ed539a60038b93`) — `status.state: SUCCEEDED`. Confirmed
  via `SHOW SCHEMAS IN agent_skills LIKE 'ts_dbx_substrate_pr15'` → `total_row_count: 0`.
- ThoughtSpot: `ts metadata delete b4cc4f5e-b969-42d6-9bea-8c831934ede7
  8e60c5c2-1622-4ff3-8f1f-58e22ae1bebd --profile se-thoughtspot` (model before table) —
  confirmed via `ts metadata search --profile se-thoughtspot --name "PR15A_%"` → `[]`.
  `DBX_DAMIAN` connection left untouched (shared scratch infrastructure).
