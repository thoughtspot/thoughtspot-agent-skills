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
- Statement ledger (11 of the ≤12 budget, all `SUCCEEDED`, none re-run): (1) `CREATE SCHEMA`,
  (2) `CREATE TABLE window_fixture`, (3) `CREATE TABLE ratio_fixture`, (4) sanity-check
  `SELECT COUNT(*)`, (5) `CREATE VIEW window_filtered_mv`, (6) `CREATE VIEW
  window_nofilter_mv`, (7) Query A/C (`window_filtered_mv`), (8) Query A/A2 (`window_nofilter_mv`
  baseline + query-time filter, UNION ALL), (9) Query D (`window_nofilter_mv` baseline +
  date-range filter, UNION ALL), (10) `CREATE VIEW ratio_mv`, (11) Query B (`ratio_mv`
  fine/coarse/total, UNION ALL).

## A — LOD dimensions × filters

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| A1 | `SUM(x) OVER (PARTITION BY dim)` → `group_aggregate(sum(x), {dim}, query_filters())`; the third argument is claimed to make the LOD "respect user-applied filters" | `ts-from-databricks-rules.md:159-176` (esp. line 176), `ts-databricks-formula-translation.md:381-413` (esp. 409-411), `ts-to-databricks-rules.md:244-257`; worked example `ts-to-databricks.md` Formula 3 "Category Quantity" (line ~366) — **verified 2026-05-25 with NO filter ever applied to the query or the MV** | Live DBX (3-condition discriminator: no filter / MV global `filter:` / query-time `WHERE`) + TS number-match (query-level pin vs. model-level filter) | See `### A1 — live results` below — condition-dependent: no-filter=360/8360 (both cats), MV global `filter:`=160/4160 (matches a2), query-time `WHERE`=360/8360 (matches a1, i.e. unaffected) | — (needs Task 4) |
| A2 | (sub-probe of A1) Whether an MV's own global `filter:` and an ad hoc query-time `WHERE` on the same unfiltered MV produce the *same* LOD value | None — never asked in any existing doc; surfaced during this plan's research | Live DBX only (compare `window_filtered_mv` output to `window_nofilter_mv WHERE ...` output) | See `### A2 — live results` below — MV filter gives 160/4160, query-time WHERE on the same underlying rows gives 360/8360 | **DIFFERENT (live DBX-only, 2026-07-09)** — an MV's baked-in global `filter:` is filter-aware for a partition-window LOD dimension; an ad hoc query-time `WHERE` on an MV with no global filter is filter-blind for that same dimension (it still removes rows from output, but does not change the window's computed value) |

## B — Cross-measure ratio inlining × grain

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| B1 | `MEASURE(a) / MEASURE(b)` inlines to `[a] / [b]` and is claimed (implicitly, by having no grain caveat anywhere) to compute ratio-of-sums correctly at **any** query grain | `ts-from-databricks-rules.md:270-282`, `ts-databricks-formula-translation.md:415-434` (esp. 426, 434) and the quick-lookup row at line 649-651, `ts-to-databricks-rules.md:267-269,281`; worked examples `ts-from-databricks.md` (`avg_order_value`, `return_rate`) and `ts-to-databricks.md` (`category_contribution_ratio`, verification query at line ~1035-1042) — **every one of these was queried at exactly one grain, never compared across grains** | Live DBX (fine / coarse / total grain, one fixture designed so ratio-of-sums ≠ any naive alternative) + TS number-match (`safe_divide(sum(a), sum(b))`, which is definitionally grain-correct — TS side is the control, not the hypothesis under test) | See `### B1 — live results` below — fine/coarse/total all match ratio-of-sums exactly (fine: 10/1/100/10; coarse: 1.818.../18.18...; total: 10) | **CONFIRMED (live DBX-only, 2026-07-09)** — `MEASURE(a) / MEASURE(b)` computes true ratio-of-sums at every grain tested; no sum-of-ratios or average-of-ratios divergence found |

## C — Global `filter:` × window ordering

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| C1 | A Metric View's `filter:` is a "Global WHERE clause applied to all queries" (schema doc) and is independently claimed to combine safely with any measure, including windowed ones; the shipped worked example `ts-from-databricks.md` **already combines** `filter: status != 'cancelled'` (line 34) with a `revenue_7d_rolling` trailing-7-day window measure (lines 83-86) in the SAME MV, but the two were never queried together to see whether the filter removes rows before or after the window sums them | `databricks-metric-view.md` schema (`filter:` field description, lines 115/229/287, comparison table line 768), `ts-from-databricks-rules.md:358-385` ("Filter → Boolean Formula Column (always)"), `ts-to-databricks-rules.md:179-233`; worked example `ts-from-databricks.md` lines 34, 83-86, 316-319 | Live DBX (one MV, both a filter and a window, alternating included/excluded rows so trailing-3 sums diverge sharply between "filter-before-window" and "filter-after-window") + TS number-match (does a ThoughtSpot model-level `filters:` block filter before or after `moving_sum` computes?) | See `### C1 — live results` below — matches hypothesis (c1-dates) exactly at both cat X and Y, diverging sharply from (c1-rows) and (c2) | DBX hypothesis identity: **(c1-dates) — filter-before-window, DATE-INTERVAL frame** (live DBX-only, 2026-07-09); TS-side model-`filters:`-vs-`moving_sum`-ordering comparison — (needs Task 4) |

## D — Semi-additive × date-range filters

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| D1 | `last_value`/`first_value` (`range: current`, `semiadditive: last`/`first`, raw-date `order:`) collapse to "the last/first observation" per group — PR 1's C7 confirmed this **at the full, unfiltered date range only** (Query A2, `rolling_mv`, no `filter:` present at all); never tested with a query that narrows the date range before the collapse happens | `ts-from-databricks-rules.md:313-334` and `:561-641` (`#### True Semi-Additive`), `ts-databricks-formula-translation.md:438-478`, `ts-to-databricks-rules.md:291-361`; PR 1's C7 in `docs/audit/2026-07-08-dbx-window-claim-matrix.md` (CONFIRMED, but at full-range only); `thoughtspot-formula-patterns.md:408-432` (Semi-Additive Functions — platform-agnostic TS reference, same untested gap) | Live DBX (query-time date-range `WHERE` narrower than the full fixture range, both ends) + TS number-match (`last_value`/`first_value` under an equivalent query-level date-range filter) | See `### D1 — live results` below — matches hypothesis (d1) exactly at both cat X and Y | — (needs Task 4) |

## E — Trailing-window frame semantics (rows vs. dates)

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| E1 | DBX `trailing N day` frame semantics: **row-positional vs. date-interval**. PR 1's C1 CONFIRMED verdict (`moving_sum([m], N, -1, [date])` ≡ `trailing N day` default/exclusive) was obtained on **dense daily data only** (one row per day, no gaps), where the two framings are indistinguishable — the CONFIRMED verdict is density-conditional, the same non-discriminating-verification failure mode this PR closes. TS `moving_sum` is documented **row-positional** (`ts-from-databricks-rules.md:702-713` — "based on row counts, so this assumes one row per day (daily grain)"); if DBX's frame is a date interval, every PR-1-corrected trailing/leading mapping silently breaks on sparse data. | PR 1 matrix C1 (`docs/audit/2026-07-08-dbx-window-claim-matrix.md`); `ts-from-databricks-rules.md:702-713` row-counts note | Live DBX (gapped cat `Z` rides Battery C's existing query — Z has no excluded rows, isolating rows-vs-dates from the filter question) + TS number-match (Z-probe on `PR15_Window_Fixture`, row-positional expectation) | See `### E1 — live results` below — Z's gapped trailing-window matches the DATE-INTERVAL column exactly, diverging from ROW-positional at days 5/8 | DBX rows-vs-dates identity: **RESOLVED — DATE-INTERVAL** (live DBX-only, 2026-07-09) — confirms PR 1's C1/C3 CONFIRMED verdicts were density-conditional; density caveat needed in the mapping docs (Task 5). TS-side Z-probe comparison — (needs Task 4) |

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
from the output (12 of 20 rows in Query A/C; 6 of the theoretical rows in the filtered A/A2
scenario) but the `SUM(amount) OVER (PARTITION BY cat)` dimension itself was already computed
inside the view before that outer `WHERE` is applied. This is not one of the brief's two named
hypotheses cleanly — it is a *third pattern*: "which kind of filter" determines the answer, not
"is a filter active." TS-side number-match against the two ThoughtSpot candidate formulas
(query-level pinned filter vs. model-level `filters:` block) is Task 4's job — no Verdict is
recorded for A1 itself; A2 (below) is the sub-question this same evidence directly decides.

### A2 — live results

Directly derived from A1's two live conditions above, on the identical underlying
`window_fixture` rows: `window_filtered_mv`'s baked-in `filter: NOT excluded` produces
`category_total_amount` = 160 (X) / 4160 (Y); `window_nofilter_mv WHERE NOT excluded` (an ad
hoc query-time filter, no MV-level filter) produces 360 (X) / 8360 (Y) for the same dimension.

**Verdict: DIFFERENT (live DBX-only, 2026-07-09).** An MV's own global `filter:` and an ad hoc
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
(does ThoughtSpot's model-level `filters:` block interact with `moving_sum` the same way?) is
Task 4's job — the claim's overall Verdict stays pending that comparison.

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
same way?) is Task 4's job — no Verdict is recorded for D1 itself yet.

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
the claim's verification method) is Task 4's job — the claim's overall Verdict stays pending
that comparison, though the DBX-side ambiguity itself is now fully closed.
