# Databricks semantic deep-dive claim matrix — PR 1.5

**Serves:** BL-063 Phase 2 PR 1.5 (`docs/superpowers/specs/2026-07-08-dbx-conversion-substrate-design.md`,
"PR 1.5 — Dimension/metric semantic deep-dive"). Sibling artifact to PR 1's
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` — same conventions, separate claim-ID
namespace (A/B/C/D-prefixed, not C-prefixed) to avoid collision.

## Fixture (Task 2 fills in)

- Catalog: `agent_skills` (reused from PR 1 — confirmed Unity-Catalog-managed)
- Schema: `ts_dbx_substrate_pr15`
- Fixture tables: `window_fixture` (20 rows), `ratio_fixture` (4 rows)
- ThoughtSpot connection: `DBX_DAMIAN` (`b9e709c6-b951-4b50-a816-b450e6aee278`) — reused, not
  recreated

## A — LOD dimensions × filters

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| A1 | `SUM(x) OVER (PARTITION BY dim)` → `group_aggregate(sum(x), {dim}, query_filters())`; the third argument is claimed to make the LOD "respect user-applied filters" | `ts-from-databricks-rules.md:159-176` (esp. line 176), `ts-databricks-formula-translation.md:381-413` (esp. 409-411), `ts-to-databricks-rules.md:244-257`; worked example `ts-to-databricks.md` Formula 3 "Category Quantity" (line ~366) — **verified 2026-05-25 with NO filter ever applied to the query or the MV** | Live DBX (3-condition discriminator: no filter / MV global `filter:` / query-time `WHERE`) + TS number-match (query-level pin vs. model-level filter) | — | — |
| A2 | (sub-probe of A1) Whether an MV's own global `filter:` and an ad hoc query-time `WHERE` on the same unfiltered MV produce the *same* LOD value | None — never asked in any existing doc; surfaced during this plan's research | Live DBX only (compare `window_filtered_mv` output to `window_nofilter_mv WHERE ...` output) | — | — |

## B — Cross-measure ratio inlining × grain

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| B1 | `MEASURE(a) / MEASURE(b)` inlines to `[a] / [b]` and is claimed (implicitly, by having no grain caveat anywhere) to compute ratio-of-sums correctly at **any** query grain | `ts-from-databricks-rules.md:270-282`, `ts-databricks-formula-translation.md:415-434` (esp. 426, 434) and the quick-lookup row at line 649-651, `ts-to-databricks-rules.md:267-269,281`; worked examples `ts-from-databricks.md` (`avg_order_value`, `return_rate`) and `ts-to-databricks.md` (`category_contribution_ratio`, verification query at line ~1035-1042) — **every one of these was queried at exactly one grain, never compared across grains** | Live DBX (fine / coarse / total grain, one fixture designed so ratio-of-sums ≠ any naive alternative) + TS number-match (`safe_divide(sum(a), sum(b))`, which is definitionally grain-correct — TS side is the control, not the hypothesis under test) | — | — |

## C — Global `filter:` × window ordering

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| C1 | A Metric View's `filter:` is a "Global WHERE clause applied to all queries" (schema doc) and is independently claimed to combine safely with any measure, including windowed ones; the shipped worked example `ts-from-databricks.md` **already combines** `filter: status != 'cancelled'` (line 34) with a `revenue_7d_rolling` trailing-7-day window measure (lines 83-86) in the SAME MV, but the two were never queried together to see whether the filter removes rows before or after the window sums them | `databricks-metric-view.md` schema (`filter:` field description, lines 115/229/287, comparison table line 768), `ts-from-databricks-rules.md:358-385` ("Filter → Boolean Formula Column (always)"), `ts-to-databricks-rules.md:179-233`; worked example `ts-from-databricks.md` lines 34, 83-86, 316-319 | Live DBX (one MV, both a filter and a window, alternating included/excluded rows so trailing-3 sums diverge sharply between "filter-before-window" and "filter-after-window") + TS number-match (does a ThoughtSpot model-level `filters:` block filter before or after `moving_sum` computes?) | — | — |

## D — Semi-additive × date-range filters

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| D1 | `last_value`/`first_value` (`range: current`, `semiadditive: last`/`first`, raw-date `order:`) collapse to "the last/first observation" per group — PR 1's C7 confirmed this **at the full, unfiltered date range only** (Query A2, `rolling_mv`, no `filter:` present at all); never tested with a query that narrows the date range before the collapse happens | `ts-from-databricks-rules.md:313-334` and `:561-641` (`#### True Semi-Additive`), `ts-databricks-formula-translation.md:438-478`, `ts-to-databricks-rules.md:291-361`; PR 1's C7 in `docs/audit/2026-07-08-dbx-window-claim-matrix.md` (CONFIRMED, but at full-range only); `thoughtspot-formula-patterns.md:408-432` (Semi-Additive Functions — platform-agnostic TS reference, same untested gap) | Live DBX (query-time date-range `WHERE` narrower than the full fixture range, both ends) + TS number-match (`last_value`/`first_value` under an equivalent query-level date-range filter) | — | — |

## E — Trailing-window frame semantics (rows vs. dates)

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| E1 | DBX `trailing N day` frame semantics: **row-positional vs. date-interval**. PR 1's C1 CONFIRMED verdict (`moving_sum([m], N, -1, [date])` ≡ `trailing N day` default/exclusive) was obtained on **dense daily data only** (one row per day, no gaps), where the two framings are indistinguishable — the CONFIRMED verdict is density-conditional, the same non-discriminating-verification failure mode this PR closes. TS `moving_sum` is documented **row-positional** (`ts-from-databricks-rules.md:702-713` — "based on row counts, so this assumes one row per day (daily grain)"); if DBX's frame is a date interval, every PR-1-corrected trailing/leading mapping silently breaks on sparse data. | PR 1 matrix C1 (`docs/audit/2026-07-08-dbx-window-claim-matrix.md`); `ts-from-databricks-rules.md:702-713` row-counts note | Live DBX (gapped cat `Z` rides Battery C's existing query — Z has no excluded rows, isolating rows-vs-dates from the filter question) + TS number-match (Z-probe on `PR15_Window_Fixture`, row-positional expectation) | — | — |

## Live results convention

Same as PR 1's matrix: Tasks 3-4 append full query + result-set detail under a
`### <ID> — live results` subsection per claim; the table's `Actual (live)` cell holds only a
short pointer/summary. Do not touch the `Claim`/`Source` columns once seeded.
