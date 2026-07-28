# Concept Mapping — Databricks Metric View YAML → ThoughtSpot Model

Reference detail for the SKILL.md **## Concept Mapping** section: the full
construct-by-construct mapping table (33 rows) consulted while parsing and
translating a Metric View (Steps 5, 6, 8, 9) — not read sequentially. The
**Key structural rules** list that follows this table in SKILL.md stays there;
it is procedural guidance, not reference data.

---

| Databricks Metric View YAML | ThoughtSpot Model |
|---|---|
| `source:` (table FQN, SQL query, or another metric view — 4 forms, see schema) | Table FQN → Single Table TML (`db_table`, `db`, `schema` decomposed from the FQN); SQL query → see `source:` as SELECT subquery row below; another metric view → **fail loud** (MV-on-MV chaining is not supported) |
| Top-level `comment:` (v1.1) | Model `description` |
| `dimensions[].expr` (direct column reference) | `columns[]` with `column_type: ATTRIBUTE` |
| `dimensions[].expr` (computed expression) | `formulas[]` entry with translated expression + `columns[]` with `formula_id` reference |
| `dimensions[].expr` (window function — LOD) | LOD `formulas[]` entry: `group_aggregate(agg([col]), {[dim]}, query_filters())` — 3 args required. **Live-verified 2026-07-09** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, A1/A2): this is filter-aware on TS under both filter kinds, and reproduces a Databricks MV's own global `filter:` — but NOT an ad hoc query-time `WHERE` on an MV with no global filter (DBX-side asymmetry, not fixable by formula), **unless** the emitted formula uses `{}` instead of `query_filters()` paired with a model-level `filters:` block mirroring the MV's `filter:` — that combination reproduces both DBX conditions (A3 follow-up, same matrix, live-verified 2026-07-09) |
| `dimensions[].display_name` (v1.1) | Column `name` (display name) |
| `dimensions[].comment` (v1.1) | Column `description` |
| `dimensions[].synonyms` (v1.1) | `properties.synonyms[]` + `properties.synonym_type: USER_DEFINED` |
| `measures[].expr` (simple `AGG(col)` — SUM, AVG, MIN, MAX, COUNT) | `columns[]` with `column_type: MEASURE` + extracted `aggregation` |
| `measures[].expr` (`COUNT(DISTINCT col)`) | `formulas[]` entry: `unique count ( [TABLE::col] )` — NOT `aggregation: COUNT_DISTINCT` on a `column_id` (TS silently overrides to ATTRIBUTE) |
| `measures[].expr` (complex — ratios, nested aggregates) | `formulas[]` entry with translated expression + `columns[]` with `formula_id` reference |
| `measures[].expr` with `MEASURE()`/`ANY_VALUE()` | Cross-measure formula — **inline** the referenced expressions (cross-refs fail during TML import). **Live-verified 2026-07-09 across query grain** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, B1) — CONFIRMED true ratio-of-sums, cross-platform, at every grain; no grain caveat needed |
| `measures[].window`, `order:` raw date (semi-additive) | `last_value ( sum ( [m] ) , query_groups ( ) , { [date] } )` / `first_value ( ... )` — snapshot metrics (inventory, balance). **Live-verified 2026-07-09**, `docs/audit/2026-07-08-dbx-window-claim-matrix.md` C7. **Also live-verified 2026-07-09 under a query-time date-range filter** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, D1) — CONFIRMED cross-platform, collapses to last/first-in-filtered-range on both platforms |
| `measures[].window`, `order:` truncated period (period filter), no `offset` | `sum ( [m] )` at the query grain — flow metrics (revenue, qty). **Live-verified 2026-07-09**, matrix C6 |
| `measures[].window`, `order:` truncated period, `offset: -N <unit>` | `moving_sum ( [m] , N , -N , [date] )` — row-relative `LAG(N)` idiom, **NOT** a wall-clock filter; valid only when the query returns exactly one row per period. **Live-verified 2026-07-09 at month grain, N=1** (matrix C6/C6a); quarter/year grains and N>1 are Deferred (C8) extrapolations of the same idiom. Corrects the pre-2026-07-09 `sum_if(diff_months/quarters/years([date], today())=N, [m])` mapping, which was WRONG for any multi-period query |
| `measures[].window` with `range: trailing N day` (default/exclusive) | `moving_sum([m], N, -1, [date])` — rolling look-back window, anchor excluded. **Live-verified 2026-07-09**, matrix C1/C2. **Density caveat (E1):** row-positional — matches only when the order column is dense at the window's unit grain (one row per unit, no gaps); see `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md` (E1) |
| `measures[].window` with `range: trailing N day inclusive` | `moving_sum([m], N-1, 0, [date])` — anchor included. **Live-verified 2026-07-09**, matrix C1. Same E1 density caveat as above |
| `measures[].window` with `range: leading N day` (default/exclusive) | `moving_sum([m], -1, N, [date])` — rolling look-ahead window, anchor excluded. **Live-verified 2026-07-09**, matrix C3. Same E1 density caveat as above |
| `measures[].window` with `range: leading N day inclusive` | `moving_sum([m], 0, N-1, [date])` — anchor included. **Live-verified 2026-07-09**, matrix C3. Same E1 density caveat as above |
| `measures[].window` with `range: cumulative` | `cumulative_sum([m], [date])`. **Live-verified 2026-07-09**, matrix C5 |
| `measures[].window` with `range: all` | `group_aggregate(sum([m]), {partition dims}, query_filters())`, `column_type: ATTRIBUTE` — unbounded partition window, scoped per query partition. **Live-verified 2026-07-09**, matrix C4. Inherits the same A1/A2 filter asymmetry as the LOD row above (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`), including its A3 `{}` + model-filter refinement |
| `measures[].window` with `inclusive`/`exclusive` anchor modifier | Default is `exclusive`, confirmed. Applies only to `trailing`/`leading`. **Live-verified 2026-07-09**, matrix C1/C2/C3 |
| `measures[].expr` with `FILTER (WHERE cond)` | `agg_if ( cond , [x] )` — native `*_if` conditional aggregate (e.g., `sum_if`, `unique_count_if`) |
| `COUNT(*)` | Formula: `count ( 1 )` |
| `fields[]` (GA alias for `dimensions[]`) | Same mapping as `dimensions[]` above — `fields:` is checked first, `dimensions:` is the fallback |
| Growth % (MoM, QoQ, YoY) | Inline `sum([m])` and `moving_sum([m], N, -N, [date])` expressions for both periods — cross-formula refs not supported during TML import |
| `joins:` (nested hierarchy) | One Table TML per source; model `joins[]` from parent→child hierarchy |
| `joins[]."on"` or `joins[].using` (exactly one present) | `on` → join expression as-is; `using: [COL, ...]` → `[A::COL] = [B::COL]` (AND-joined for multiple columns) |
| `filter:` (any) | Boolean formula column `[MV Filter]` — users apply `[MV Filter] = true`. Always create, never description-only. **Live-verified 2026-07-09** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, C1): filter ordering is CONFIRMED cross-platform — a model-level `filters:` block filters rows before a windowed measure computes, matching a Databricks MV's own global `filter:`. Frame semantics on windowed measures still DIVERGE on gapped data — see the density caveat on the trailing/leading rows above (E1) |
| Subquery in `expr` | **Untranslatable** — log in Unmapped Report |
| `source:` as SELECT subquery (parenthesized `(SELECT ...)` or bare `SELECT ...`/`WITH ...`) | Prompt user: (D) create Databricks VIEW, (T) create ThoughtSpot SQL View, (M) map to existing, (S) skip |
| `source:` as another metric view (MV-on-MV) | **Fail loud** — not supported; ask the user to convert the upstream MV first or flatten the chain in Databricks |
| `version:` | Drives parsing path (v0.1 vs v1.1) — not stored in ThoughtSpot |
