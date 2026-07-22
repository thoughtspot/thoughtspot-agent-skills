# Migration Report Format (Step 12)

The required `MIGRATION_REPORT.md` structure for **Step 12 — Migration Report**. Every
migration produces this report — write it to `/tmp/ts_tableau_mig/output/MIGRATION_REPORT.md`
and display it inline. Build hyperlinks from `{base_url}` (Step 1) and the GUID returned at
import: Model/table → `{base_url}/#/data/tables/{guid}`; Liveboard →
`{base_url}/#/pinboard/{guid}`; Answer (standalone) → `{base_url}/#/saved-answer/{guid}`.

## Report structure

```markdown
# Tableau → ThoughtSpot Migration Report
_Generated {date} · ThoughtSpot: {base_url} · Connection: {connection_name}_

## Overview

| # | Source workbook (.twb) | Outcome | Model | Liveboard |
|---|---|---|---|---|
| 1 | Amazon Sales.twb | ✅ Model + Liveboard | [Amazon Sales]({link}) | [Amazon Dashboard]({link}) |
| 2 | arms_viz.twb | ◑ Model only (no dashboards) | [arms]({link}) | — |
| 3 | legacy.twb | ⊘ No action | — | — |

Outcome legend: **✅ Model + Liveboard** · **◑ Model only** · **⊘ No action** (why).

---

## {workbook_name}

**Source:** `{twb path}` · **Outcome:** {outcome} · **Connection:** {connection_name}

**Objects created**
| Type | Name | Link |
|---|---|---|
| Table | {name} | [{guid8}]({link}) |
| Model | {name} | [{guid8}]({link}) |
| Liveboard | {name} | [{guid8}]({link}) |

**What was done** — datasources, tables/SQL views, joins, model, Spotter, # tiles, theme.

**Decisions made** — the non-obvious calls (blend → one SQL view, bins = formula vs cohort,
dynamic vs anchored YoY, orphan worksheets added/left off, separate vs tabbed liveboards…).

**Formula mapping** — every calculated field, with status:
| Tableau field | Tableau expression | ThoughtSpot expression | Status |
|---|---|---|---|
| Total sales | `SUM([Sales])` | `sum([ORDERS::SALES])` | ✅ Migrated (model) |
| Cumulative sales | `RUNNING_SUM(SUM([Monthly sales]))` | `cumulative_sum([Sales])` | ✅ Migrated (answer-level) |
| Sales growth rate | `(SUM(curr)-SUM(prev))/SUM(prev)` | `([formula_Current…]-…)/…` | ◑ Partial — N/A on this data (dynamic, data ends 2024) |
| Relative difference | `LOOKUP([Total sales],-1)…` | `growth of [Total sales] by [Order Date]` | ◑ Partial — realized as a growth viz, not a column |
| Profit forecast | `MODEL_QUANTILE(…)` | — | ⊘ Not migrated — no ThoughtSpot equivalent (placeholder tile built) |

Status values: **✅ Migrated** (model or answer-level — say which), **◑ Partial** (built but
with a caveat — approximation, N/A on current data, placeholder), **⏸ Parked** (import
attempted, failed, deferred — show error and potential fix), **⊘ Not migrated** (omitted
before import; give the reason). Every calculated field from Step 3 must appear in exactly
one row.

**Sets** — every Tableau set, how it was handled, and what to verify (per the MANDATORY set-review
rule). Set conversions are semantic reinterpretations — list each so the user can confirm intent:
| Tableau set | Kind | ThoughtSpot result | Review |
|---|---|---|---|
| State Set | static | column set (GROUP_BASED, 3 members) | verify membership |
| Category Set | `except` | column set via `NE` (except Furniture; nulls excluded) | verify exclusion |
| Year Set | static, calc-anchored | column set on formula column `Order Year` | verify calc + values |
| 01. Month Set | set control | filter on `Order Month`; IF-[Set] calcs collapsed to measure+filter | confirm filter ≈ control |
| State_TopN | Top-N | ✓ query set (rank desc by SUM, N=topN param) | verify ranking + N |
| State_BottomN | Bottom-N | ✓ query set (rank asc by SUM, N=topN param) | verify ranking + N |

**⏸ Parked formulas** — formulas that `build-model` attempted to import but failed after
retry cycles. Only present when `{parked_formulas}` is non-empty. Include the attempted
expression and error so the user (or Step 12.5) can diagnose:

| # | Name | Attempted Expression | Error | Original Tableau | Potential Fix |
|---|------|---------------------|-------|------------------|--------------|
| 1 | {name} | `{expr}` | {error} | `{original_tableau}` | {LLM assessment of what might fix it} |

If the Complete-mode fix cycle was run, note which formulas were fixed (moved to ✅) and
which exhausted their 3 attempts. Include the last error for exhausted formulas.

**Excluded formulas** — every ⊘ row from the formula mapping table, grouped by root cause.
Include the root cause summary first, then per-formula detail under each heading:

Root cause summary:
| Root Cause | Count | Potential Resolution |
|---|---|---|
| Orphan inherited calc | {N} | Non-functional — references tables not in this datasource (copied from parent). Add missing tables or leave excluded |
| Missing table in model | {N} | Add source table(s) to the connection and model, then create the formula |
| Untranslatable function | {N} | No ThoughtSpot equivalent — consider a SQL view or Snowflake UDF |
| Circular dependency | {N} | Break the cycle by inlining one formula into the other |
| Complex date arithmetic | {N} | Rewrite with ThoughtSpot date functions or pre-compute in warehouse |
| Geospatial function | {N} | Spatial functions not supported — lat/lon columns migrated as attributes |

### {Root cause category} ({N} formulas)
| # | Formula Name | Tableau Expression | Potential Resolution |
|---|---|---|---|
| 1 | {name} | `{expr}` | {specific to this formula — what the user can do} |

Omit root cause categories with zero formulas. Ground each root cause and potential
resolution in [`coverage-matrix.md`](coverage-matrix.md) — it is
the canonical mapped/unmapped construct reference.

**⚠ Formulas needing review** — formulas that WERE migrated (✅ in the mapping table) but
require user verification. The ThoughtSpot behaviour may differ from Tableau in specific
conditions. List every flagged formula with a specific verification question:

| # | Formula Name | Review Category | What to Verify |
|---|---|---|---|
| 1 | {name} | No-keyword LOD | Test with/without search filters — does the value change as expected? |
| 2 | {name} | Blend-context | Row-level join may produce different aggregation — compare totals |
| 3 | {name} | Pass-through SQL | Confirm SQL Passthrough Functions is enabled on the cluster |
| 4 | {name} | `ifnull` stripped | NULL handling deferred to ThoughtSpot — verify nulls display correctly |
| 5 | {name} | `sum_if` rewrite | Simplified from `if/then/else` — verify aggregation matches |

Review category reference:
| Category | When flagged | What to verify |
|---|---|---|
| No-keyword LOD | `{AGG([col])}` → `group_aggregate(..., {}, query_filters())` | Tableau computes after dimension filters, before table-calc filters — no exact TS match. Test with/without search filters. If the formula should be an absolute total, change `query_filters()` to `{}`. |
| Blend-context | Formula references columns from a blended secondary datasource | Row-level join may aggregate differently than Tableau's post-agg blend — compare totals |
| Pass-through SQL | `sql_*_aggregate_op` or `sql_*_op` functions | Requires SQL Passthrough Functions enabled; verify SQL dialect matches your warehouse |
| `ifnull` stripped | `ifnull(measure, 0)` wrapper removed (default) | NULL handling deferred to ThoughtSpot query engine — verify nulls display correctly in charts/tables |
| `sum_if` rewrite | `sum(if(cond) then expr else 0)` → `sum_if(cond, expr)` (default) | Semantically equivalent but verify aggregation matches original |

Omit categories with zero formulas. The `ifnull` stripped and `sum_if` rewrite counts come
from the `translate_formulas` stats (`ifnull_stripped`, `agg_if_conversions`).
```
