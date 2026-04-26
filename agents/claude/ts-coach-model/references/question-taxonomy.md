# Question Taxonomy and Ranking — `ts-coach-model`

Deterministic patterns for generating and scoring candidate reference questions from a
ThoughtSpot Model. Used in [SKILL.md Step 4](../SKILL.md). The goal is to systematically
cover measure × dimension × time-grain × pattern combinations, then prune by signal so
the user reviews the top ~40 and selects ~15.

The "10–20 covering common questions" anchor and the "mix simple with complex" guidance
both come from
[Snowflake's Cortex Analyst best practices](https://www.snowflake.com/en/developers/guides/best-practices-semantic-views-cortex-analyst/).

---

## Notation

For a Model with measures `M = {M1, M2, ...}`, attribute dimensions `D = {D1, D2, ...}`,
date dimensions `T = {T1, T2, ...}`, and join paths `J = {J1, J2, ...}`:

- `M_top` — measures that already appear in any existing Liveboard tile or Answer
- `D_join` — dimensions that are join keys for ≥2 tables
- `T_default` — the highest-cardinality date dim, used when a tier needs only one `T`

---

## Tier 1 — Foundational (one entry per measure where possible)

| Pattern ID | Template | Example | Tokens (rough) | Needs formula? |
|---|---|---|---|---|
| `t1.total` | `What is total {M}?` | "What is total revenue?" | `[M]` | No |
| `t1.by_dim` | `{M} by {D}` | "Revenue by region" | `[D] [M]` | No |
| `t1.top_n` | `Top 10 {D} by {M}` | "Top 10 customers by revenue" | `[D] [M] top 10` | No |
| `t1.bottom_n` | `Bottom 10 {D} by {M}` | "Bottom 10 stores by revenue" | `[D] [M] bottom 10` | No |
| `t1.distinct_count` | `How many distinct {D}?` | "How many distinct customers?" | `unique count [D]` | No |

**Generation rule:** for each `M`, emit `t1.total`, `t1.by_dim` against the top-2 dimensions
ranked by `D_join` ∋ membership then alphabetical, and `t1.top_n` against the top-1 entity
dimension. For each entity dimension, emit `t1.distinct_count` once.

---

## Tier 2 — Time (require ≥1 date dim)

Skip this tier entirely if `T = ∅`.

| Pattern ID | Template | Example | Tokens (rough) | Needs formula? |
|---|---|---|---|---|
| `t2.by_time` | `{M} by {T grain}` | "Revenue by month" | `[T] [M] monthly` | No |
| `t2.this_vs_last` | `{M} this {grain} vs last {grain}` | "Revenue this quarter vs last quarter" | `[M] this quarter` plus paired `last quarter` | No |
| `t2.trend_by_dim` | `{M} trend by {D}` | "Revenue trend by product line" | `[T] [D] [M]` | No |
| `t2.recent_period` | `{M} in the last N {grain}` | "Revenue in the last 30 days" | `[M] last 30 days` | No |
| `t2.cumulative` | `Cumulative {M} by {grain}` | "Cumulative revenue by month" | `[T] [M_cumulative]` | Yes — `cumulative_sum([M], [T])` |

**Generation rule:** for each `M_top`, emit `t2.by_time` and `t2.recent_period` against
`T_default`, and `t2.this_vs_last` once at the quarter grain. Emit `t2.trend_by_dim` and
`t2.cumulative` for measures that already appear in a Liveboard.

**Grain choice:** infer the natural grain from the date dim's cardinality and the
underlying table's expected event frequency:

| Cardinality of distinct dates / row count | Default grain |
|---|---|
| < 100 distinct values | yearly |
| 100–1500 | monthly |
| 1500–50000 | weekly |
| > 50000 | daily |

When uncertain, default to `monthly`.

---

## Tier 3 — Filters and Ratios

| Pattern ID | Template | Example | Tokens (rough) | Needs formula? |
|---|---|---|---|---|
| `t3.dim_filter` | `{M} for {D} = {value}` | "Revenue for region = west" | `[D] = 'west' [M]` | No |
| `t3.avg_per` | `Average {M} per {D}` | "Average order value per customer" | `[D] [M_avg_per]` | Yes — `[M_total] / unique count [D]` |
| `t3.ratio` | `{M1} / {M2}` (e.g. margin %) | "Margin %" | `[Margin pct]` | Yes — `( [M1] - [M2] ) / [M1]` |
| `t3.share_of_total` | `{D} share of total {M}` | "Region share of total revenue" | `[D] [M_share]` | Yes — `[M] / group_aggregate(sum, [M], {})` |
| `t3.year_filter` | `{M} in {year}` | "Revenue in 2025" | `[T] = 2025 [M]` | No |

**Filter value selection.** For `t3.dim_filter` and `t3.year_filter`, pick a value that is
likely to be common (most-frequent value if usage data is available; otherwise the
alphabetically-first value, which the user will edit if it's wrong). Don't propose more
than one filter-value variant per dimension — that's a synonym proliferation pattern
Snowflake's guidance explicitly warns against.

**Ratio measure selection.** For `t3.ratio`, pair measures by name pattern matches
(`Revenue` ↔ `Cost`, `Sales` ↔ `Returns`, `Successful` ↔ `Total`) before falling back to
arbitrary pairs.

---

## Tier 4 — Complex (answer-level formula required)

| Pattern ID | Template | Example | Tokens (rough) | Formula |
|---|---|---|---|---|
| `t4.yoy_compare` | `{M} this year vs last year by {D}` | "Revenue this year vs last year by region" | `[D] [M] this year [M] last year` | None — uses search-bar `this year`/`last year` keywords |
| `t4.mom_compare` | `{M} this month vs last month` | "Revenue this month vs last month" | `[T] [M] this month [M] last month` | None — uses search-bar keywords |
| `t4.conditional_agg` | `{M} from {D = condition}` | "Revenue from new customers only" | `[M_new]` | `sum_if([M], [D_status]='new')` |
| `t4.window_rank` | `{D} rank by {M} within {D2}` | "Customer rank by revenue within region" | `[D] [D2] [M_rank]` | `rank([M], {[D2]})` |
| `t4.cross_join_metric` | `{M1} per {M2} (different fact tables)` | "Conversion rate (orders / sessions)" | `[M_conversion]` | `[M1] / [M2]` (relies on Model joins) |

**Generation rule:** emit `t4.yoy_compare` once for the top measure if `T` exists. Emit
`t4.conditional_agg` for any attribute that has a status-like name (`status`, `type`,
`flag`, `category` ≤ 5 distinct values) and the top measure. Emit `t4.cross_join_metric`
only if the Model has ≥2 fact tables joined; pair the two largest measures.

> **Note on YoY/MoM growth %.** An earlier version of this taxonomy emitted formula-bearing
> `t4.yoy` / `t4.mom` rows using `group_aggregate(sum, [M], { [T] - 1 })`. The `[T] - 1`
> operator on a date column inside a grouping argument is **not valid TS formula syntax** —
> `group_aggregate`'s third argument is a `query_filters()` expression, not a date offset.
> A verified period-over-period growth-% formula has not been documented in
> [thoughtspot-formula-patterns.md](~/.claude/shared/schemas/thoughtspot-formula-patterns.md);
> the keyword-based comparison above is the safe fallback (produces two side-by-side KPIs,
> one per period, with no formula required). Tracked in
> [open-items.md](open-items.md) until a verified pattern lands.

**Formula generation** — full expression building rules and a worked example for each
T4 pattern are in [token-mapping-rules.md](token-mapping-rules.md) (Section 4).

---

## Ranking Signals (additive)

Score each generated candidate, then keep the top 40.

| Signal | Score | How to detect |
|---|---|---|
| `mined_search_match` — pattern matches a real `search_query` from Step 3a | **+5** | Token-level overlap ≥ 70% with any mined search_query |
| `matches_existing_global_feedback` — `search_tokens` shape matches an existing `access: GLOBAL` Reference Question on the Model | **+4** | Token-level overlap ≥ 70% with `search_tokens` of any existing GLOBAL entry. The pattern matters; we generate adjacent (related-shape) candidates to fill gaps |
| `mined_sql_match` — pattern matches a top SQL pattern from Step 3b | **+3** | Same measure(s) and grouping dims as the SQL `GROUP BY` |
| `mined_prose_match` — pattern matches a question seed extracted from prose mining (Step 3c) | **+2** | Question seed (yoy / top_n / share / etc.) emitted from prose extraction matches this candidate's pattern |
| `measure_in_liveboard` | +2 | Measure name appears in any visualization on a Liveboard that depends on this Model |
| `dim_is_join_key` | +2 | Dimension is in `D_join` |
| `tier_t1_or_t2` | +1 | Pattern is in T1 or T2 (foundation coverage bonus) |
| `complex_formula_unique` | +1 | Pattern requires an answer-level formula not already in `model.formulas[]` |
| `duplicate_existing_global` — `feedback_phrase` already in an existing GLOBAL entry | **drop, mark existing as KEEP** | Exact `feedback_phrase` match (case-insensitive). Preserve the existing GLOBAL entry; don't generate a competing one |
| `duplicate_existing_user_in_scope` — `feedback_phrase` matches a USER entry AND user opted IN | **drop** | Same as above when USER entries are in scope |
| `duplicate_existing_user_out_of_scope` — `feedback_phrase` matches a USER entry AND user opted OUT | none — proceed | The USER entry is invisible to the skill; the new candidate is independent |

### Why GLOBAL feedback is +4, not +5

Existing `access: GLOBAL` feedback is the strongest possible signal of "this pattern
matters and the team agrees on the answer". But the entry is already there. The +4
score is for **adjacent** patterns (same measures and dims, different shape) — e.g.
existing GLOBAL entry says "Inventory Balance by month", we boost candidates like
"Inventory Balance trend by region" or "Cumulative Inventory Balance by month" because
the team has already validated that this measure × dim combination gets used.

For identical patterns the candidate is dropped (`duplicate_existing_global`) and the
existing entry is preserved as KEEP.

Mined `search_query` strings (`+5`) are scored slightly higher because they signal
patterns that **don't yet have coaching** — the highest-leverage candidates.

### USER access entries

By default the skill excludes `access: USER` entries from input signal — they're
private, unreviewed, and may be experimental. The user can opt them in via the Step 5
scope menu prompt. When opted in, treat them like GLOBAL for ranking purposes. When
opted out, they are invisible to ranking and the skill never silently overwrites or
promotes them.

**Tiebreaker:** for equal scores, prefer T1 > T2 > T3 > T4. For equal tier, prefer
candidates with mined-search backing over generated-only.

---

## Selection Defaults

After scoring and capping at 40, mark the top 15 as `selected_default: True` with these
constraints (relaxed in order if the model is sparse):

1. ≥ 3 entries from T1
2. ≥ 2 entries from T2 (only if `T ≠ ∅`)
3. ≥ 2 entries from T3
4. ≥ 1 entry from T4
5. Fill remaining slots by score

If the Model has < 5 measures or < 3 dimensions, lower the default target from 15 to 10.

---

## Why these tiers

The Snowflake Cortex Analyst optimization guidance explicitly says verified queries
should *"reflect something a user might ask"* and that "*Simple queries may not have as
much useful information*" — so we deliberately mix T1 (simple, foundational, broadest
coverage) with T4 (complex, formula-bearing, highest accuracy lift) rather than
overloading on either. The ThoughtSpot
[TML coaching documentation](https://docs.thoughtspot.com/cloud/26.4.0.cl/tml-coaching)
defines the two feedback types we produce: `REFERENCE_QUESTION` for full question
patterns (all four tiers) and `BUSINESS_TERM` for column/formula synonym phrases (handled
opt-in in SKILL.md Step 7, not generated by this taxonomy).

---

## Worked example

For a Model with measures `Revenue`, `Cost`; dimensions `Region`, `Customer`,
`Product Line`; and date dim `Order Date`:

```
T1 candidates:
  t1.total       Revenue          → "What is total revenue?"
  t1.total       Cost             → "What is total cost?"
  t1.by_dim      Revenue, Region  → "Revenue by region"
  t1.by_dim      Revenue, Product → "Revenue by product line"
  t1.top_n       Customer/Revenue → "Top 10 customers by revenue"
  t1.distinct    Customer         → "How many distinct customers?"

T2 candidates (Order Date, monthly default):
  t2.by_time     Revenue          → "Revenue by month"
  t2.recent      Revenue          → "Revenue in the last 30 days"
  t2.this_v_last Revenue, quarter → "Revenue this quarter vs last quarter"
  t2.trend       Revenue, Product → "Revenue trend by product line"

T3 candidates:
  t3.dim_filter  Revenue, Region  → "Revenue for region = west"   (value placeholder)
  t3.avg_per     Revenue, Customer→ "Average revenue per customer"
  t3.ratio       Revenue, Cost    → "Margin %"  (formula required)
  t3.share       Region, Revenue  → "Region share of total revenue"

T4 candidates:
  t4.yoy         Revenue, Region  → "Revenue YoY growth by region"
  t4.cond_agg    Revenue, Customer Status → "Revenue from new customers"
  t4.cross_join  (skipped — only one fact)
```

After scoring, the top 15 with at least 3 T1, 2 T2, 2 T3, 1 T4 are pre-marked KEEP.
