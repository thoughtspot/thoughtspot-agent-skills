# Audit Mode Report Format (Step A4)

The per-file, per-datasource, and combined report templates for **Step A4 — Migration
Coverage Report (Audit Mode)**. Source the numbers from `classification.json` (Step A3's
`ts tableau classify-formulas` output) — do not hand-tally tiers. See the Step A4 spine in
`SKILL.md` for how to source the numbers before rendering these templates.

## Tier reference (Step A3)

`ts tableau classify-formulas` tiers, mapped to the human-readable categories used in the
report — kept as reference/documentation, not as executed classification logic:

| Tier | Description | Examples |
|---|---|---|
| **Native / Set** | Direct ThoughtSpot mapping exists | IF/THEN, IFNULL, DATEDIFF, LEFT, ABS, ROUND, IIF; **bins** (`class='bin'`) → `floor([x]/size)*size` or BIN_BASED cohort; **manual groups** (`class='categorical-bin'`, incl. fields named "… clusters") → `GROUP_BASED` cohort; `Number of Records`/row counts → `count([column])` (**prompt** for the column; default the primary key); **static sets** (`<group>` with `union`/`member`) → `GROUP_BASED` column-set cohort — incl. ones anchored on a **formula column**, with a **`%null%`** member (via `EQ {Null}`), or an **`except` member-list** (via `NE`) (Phase 2a); **Top-N/Bottom-N sets** (`function='end'`) → query set (`cohort_type: ADVANCED`, `COLUMN_BASED`) via a rank formula + parameter-filter formula (Phase 2b); **condition-based sets** (`function='filter'`) → query set with aggregate condition formula (Phase 2c); **member-list intersect** → `GROUP_BASED` cohort of common members (Phase 2c); **all-except-Top-N** → query set with inverted rank filter (Phase 2c); **computed set operations** (intersect/except of mixed types) → multi-formula query set (Phase 2c) |
| **LOD** | LOD expression → `group_aggregate()` | `{FIXED dim : SUM(col)}`; **`TOTAL(SUM(x))`** / percent-of-total → `group_aggregate(..., {}, query_filters())` |
| **Cumulative** | Running calculation → `cumulative_*()` | RUNNING_SUM, RUNNING_AVG |
| **Pass-through** | Valid SQL but no native function → `sql_*_aggregate_op()` | Partitioned RANK, DENSE_RANK |
| **Partial / Unmapped (sets)** | Tableau set construct with no current ThoughtSpot equivalent — logged as deferred, never mis-translated | **set controls** (`level-members` only, no fixed members) → no set object, surface as a liveboard filter; **set actions** (`<action>`) → no equivalent |
| **Row-offset (pass-through)** | `SIZE()` only → answer-level `sql_int_aggregate_op("COUNT(*) OVER()")` | `SIZE()` — only row-offset that still requires SQL pass-through ⚑ flag PT1 |
| **Untranslatable (row-offset ambiguous)** | Row-offset table calcs with unrecoverable intent — omitted | `INDEX`/`LOOKUP`/`FIRST`/`LAST` unconditionally omitted and flagged as untranslatable — no deterministic ThoughtSpot equivalent across all addressing contexts |
| **Untranslatable (window ambiguous)** | Window table calcs — omitted | `WINDOW_SUM`, `WINDOW_AVG`, `WINDOW_MAX`, `WINDOW_MIN`, `WINDOW_COUNT`, `WINDOW_STDEV`, `WINDOW_VAR`, `WINDOW_MEDIAN`, `WINDOW_PERCENTILE` unconditionally omitted and flagged as untranslatable — require worksheet addressing context (sort/partition attributes) this pipeline does not resolve |
| **Untranslatable** | No ThoughtSpot equivalent — will be omitted | `PREVIOUS_VALUE` (true recursion — not the string-aggregation technique); true **k-means clustering** (the analytics-engine "Clusters" calc — **not** `categorical-bin`); **geospatial** — full 13-function set (`MAKEPOINT`, `MAKELINE`, `BUFFER`, `OUTLINE`, `DISTANCE`, `AREA`, `LENGTH`, `INTERSECTS`, `SHAPETYPE`, `DIFFERENCE`, `INTERSECTION`, `SYMDIFFERENCE`, `VALIDATE`) — decompose `MAKEPOINT` lat/lon args to individual attribute columns, omit the spatial formula (see `tableau-formula-translation.md` Geospatial Policy); **embedded-RLS user attributes** (`USERATTRIBUTE`, `USERATTRIBUTEINCLUDES`) — rejected at translate time, see BL-071 |
| **Parameter ref (auto)** | References a Tableau parameter with static list/range — parameter auto-created in model | `[Parameters].[Currency]` where Currency has `<member>` values |
| **Parameter ref (query)** | References a Tableau parameter with SQL-lookup list — queryable at migration time | SQL-populated parameter lists (needs connection) |

## Per-file report

```
Audit: {workbook_name}
══════════════════════════════════════════════════════

  Datasources:          {N} total
    Live:               {N}
    Extract:            {N} (skipped in migration)
    Published (sqlproxy): {N}

  Physical tables:      {N}
  Custom SQL relations: {N} → will generate sql_view TMLs
  Joins:                {N}

  Calculated fields:    {N} total
  ┌──────────────────────────────────────────────────────┐
  │ Tier                    Count    %     Examples      │
  ├──────────────────────────────────────────────────────┤
  │ Native                  {N}     {%}   IF, DATEDIFF  │
  │ LOD → group_agg         {N}     {%}   {FIXED ...}   │
  │ Cumulative              {N}     {%}   RUNNING_SUM   │
  │ Moving                  {N}     {%}   WINDOW_SUM    │
  │ Pass-through            {N}     {%}   DENSE_RANK    │
  │ Row-offset (native)     {N}     {%}   LAG→moving_sum│
  │ Row-offset (pass-thru)  {N}     {%}   SIZE→COUNT(*) │
  │ Parameter ref (auto)    {N}     {%}   static list   │
  │ Parameter ref (query)   {N}     {%}   SQL lookup    │
  │ Geospatial (omit+log)   {N}     {%}   MAKEPOINT     │
  │ Untranslatable          {N}     {%}   INDEX(ambig)  │
  └──────────────────────────────────────────────────────┘

  Cross-reference depth (formula-to-formula dependencies):
  ┌──────────────────────────────────────────────────────┐
  │ Depth                   Count    %     Note          │
  ├──────────────────────────────────────────────────────┤
  │ Level 0 (self-contained) {N}    {%}   Translate directly │
  │ Level 1 (refs Level 0)   {N}    {%}   Inline from Level 0 │
  │ Level 2+ (deep chains)   {N}    {%}   Multi-level inlining │
  │ Circular dependencies    {N}    {%}   Cannot resolve │
  └──────────────────────────────────────────────────────┘

  Formula complexity (effort estimate):
  ┌──────────────────────────────────────────────────────┐
  │ Complexity              Count    %     Criteria      │
  ├──────────────────────────────────────────────────────┤
  │ Simple (1–2)            {N}     {%}   ≤1 function, no cross-refs, no nesting │
  │ Medium (3–5)            {N}     {%}   2–3 functions or 1 cross-ref or 1 nesting level │
  │ Complex (6+)            {N}     {%}   4+ functions, 2+ cross-refs, or deep nesting │
  └──────────────────────────────────────────────────────┘
  Score = nesting_depth + cross_ref_count + function_count (each function/operator = 1)

  Effective migration coverage:
    Syntax-level:            {N}/{total} ({%}%) — based on tier classification only
    After orphan exclusion:  {N}/{total} ({%}%) — minus {N} orphan inherited calcs
    After dep resolution:    {N}/{total} ({%}%) — minus {N} circular, {N} unresolvable cross-refs
    ──────────────────────
    Realistic estimate:      {N}/{total} ({%}%)

  ⚠ The tier classification reports SYNTAX-LEVEL translatability. The realistic
  estimate accounts for orphan calcs (Step 3g), circular dependencies, and
  unresolvable cross-references. A formula classified "Native" may still not
  migrate if it depends on an orphan or circular chain.

  Tableau Sets (top-level <group> elements — separate from calculated fields).
  Source: classification.json's per-datasource `sets_tier_counts`
  (`column_set`/`query_set`/`deferred` — BL-088; same `set_type` `build-model`'s
  own Phase-2a/2b/2c cohort emission uses, never hand-tallied):
  ┌──────────────────────────────────────────────────────┐
  │ Set tier                Count    Notes               │
  ├──────────────────────────────────────────────────────┤
  │ Native / column set     {N}      static + member-intersect → GROUP_BASED cohort (2a/2c) │
  │ Query set               {N}      Top-N, condition, all-except-Top-N, mixed ops → ADVANCED (2b/2c) │
  │ Partial / deferred      {N}      set controls + set actions (no equivalent)     │
  └──────────────────────────────────────────────────────┘

  Parameters:           {N} total ({N} static, {N} SQL-lookup — query at migration)
  Dashboards:           {N} (optional liveboard migration)

  ──────────────────────────────────────────────────
  Migration coverage:   {(all except untranslatable-ambiguous) / total}%
                         (all parameters auto-created — static or queried)
  Untranslatable:       {N} formula(s) — will be omitted
  Geospatial:           {N} formula(s) — spatial funcs omitted; lat/lon cols migrated as attributes
  Deferred sets:        {N} (set controls/actions — flagged for manual creation)
  SQL-lookup params:    {N} — need warehouse connection at migration time
  Pass-through formulas (DENSE_RANK, SIZE, etc.) require SQL Passthrough Functions enabled.
  Row-offset native formulas (LAG, LEAD, LOOKUP(agg,FIRST/LAST), INDEX) use native TS functions — no pass-through needed.
  Bare FIRST()/LAST() standalone → omitted (returns offset, not value — no TS equivalent).

  Migration effort estimate:
    Formula translation:  deterministic (CLI pipeline, no LLM calls)
    Phase 1 import:       ~1-2 minutes (tables + base model)
    Phase 2 import:       ~{N} retry cycles expected
      Simple formulas:    {N} — likely import on first try
      Medium formulas:    {N} — may need 1-2 retries
      Complex formulas:   {N} — expect structural fixes
    Estimated total:      {M}-{N} minutes (model only, excludes liveboard)

  Orphan inherited calcs:  {N} formula(s) referencing missing tables
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ These calcs were inherited from a parent/copied datasource and          │
  │ reference tables not present in this datasource. They are               │
  │ non-functional in Tableau and will be excluded from migration.          │
  │                                                                         │
  │ Missing tables: {table1}, {table2}, …                                   │
  │                                                                         │
  │  #   Formula Name              Missing Table Reference                  │
  │  1   {name}                    {TABLE_NAME}                             │
  │  …                                                                      │
  │                                                                         │
  │ (Includes {N} transitive orphans — depend on a direct orphan)           │
  └──────────────────────────────────────────────────────────────────────────┘

  ⚠ Formulas Needing Review:  {N} formula(s)
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  #   Formula Name              Category           What to Verify        │
  ├──────────────────────────────────────────────────────────────────────────┤
  │  1   {name}                    No-keyword LOD      Test with/without    │
  │                                                    search filters       │
  │  2   {name}                    Blend-context        Compare totals      │
  │  3   {name}                    Pass-through SQL     SQL Passthrough on? │
  │  4   {name}                    ifnull stripped      Verify null display │
  │  5   {name}                    sum_if rewrite       Verify aggregation  │
  │  …                                                                      │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ Categories:                                                             │
  │  No-keyword LOD   {AGG([col])} → group_aggregate — filter context may  │
  │                   differ (Tableau: after dim filters, before table-calc)│
  │  Blend-context    Secondary datasource ref — post-agg blend vs row join│
  │  Pass-through SQL sql_*_aggregate_op — requires cluster setting enabled│
  │  ifnull stripped  ifnull(measure,0) removed — TS handles NULLs natively│
  │  sum_if rewrite   sum(if…then…else 0) → sum_if() — semantically equiv │
  └──────────────────────────────────────────────────────────────────────────┘

  Data Blending — post-aggregation semantics:
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ ⚠ Tableau blends aggregate the secondary datasource independently     │
  │ before joining. ThoughtSpot model joins operate at row level.          │
  │ If both sides are fact tables at different grains, aggregation         │
  │ results may differ.                                                    │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ Primary DS          Secondary DS       Link Cols    Risk               │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ {ds_caption}        {ds_caption}       {col1, …}   {HIGH/MED/LOW}     │
  │ …                                                                      │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ Risk: HIGH = both sides have measures (fact×fact — aggregation may     │
  │              diverge)                                                   │
  │       MED  = secondary has measures but likely reference table         │
  │       LOW  = secondary is dimension-only                               │
  └──────────────────────────────────────────────────────────────────────────┘
  Blended datasources:  {N} of {total} — will merge into single model(s)
  Blend relationships:  {M} total
  Star topologies:      {S} (1 primary → 2+ secondaries)
  HIGH-risk blends:     {N} — verify aggregation results post-migration
  ──────────────────────────────────────────────────
```

If any formulas are classified as Row-offset, list them:

```
  Row-offset formulas (translated via decision tree):
    - {formula_name}: {tier} — {tableau_expr} → {ts_expr or "omit (ambiguous)"}
    - ...
```

**Excluded formulas** — every formula that will NOT be migrated, grouped by root cause:

```
  Excluded Formulas: {N} total
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ Root Cause               Count  Potential Resolution                    │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ Untranslatable function  {N}    No TS equivalent — SQL view or UDF      │
  │ Missing table in model   {N}    Add source tables, then create formula │
  │ Circular dependency      {N}    Break cycle by inlining one formula     │
  │ Complex date arithmetic  {N}    Rewrite with TS date funcs or warehouse │
  │ Geospatial function      {N}    Spatial not supported — lat/lon as attr │
  └──────────────────────────────────────────────────────────────────────────┘

  Per-formula detail:
    {Root cause category} ({N}):
    - {formula_name}: {tableau_expr} — {what the user can do}
    - ...
```

If any SQL-lookup parameters exist, note them:

```
  SQL-lookup parameters ({count} — populated from warehouse at migration time):
    - {param_name}: query/column reference from TWB
    - ...
  Values are a point-in-time snapshot. Consider /ts-recipe-parameter-sync for
  ongoing refresh.
```

If any formulas are classified as Pass-through, list them with the generated expression:

```
  Pass-through formulas (require SQL Passthrough Functions enabled):
    - {formula_name}: sql_{type}_aggregate_op("...", ...)
    - ...
```

## Per-datasource breakdown

When a workbook has multiple datasources, report coverage **per datasource**, not just
workbook-wide. Different datasources within the same workbook can have very different
effective migration rates (e.g. a full datasource at 73% vs a copied subset at 54%). A
combined number hides this.

```
  Per-datasource coverage:
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ Datasource              Tables  Calcs  Orphans  Realistic Coverage     │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ {ds_name_1}             {N}     {N}    {N}      {N}/{N} ({%}%)         │
  │ {ds_name_2} (copy)      {N}     {N}    {N}      {N}/{N} ({%}%)         │
  └──────────────────────────────────────────────────────────────────────────┘
```

## Combined summary (multiple files)

```
Audit Summary: {N} workbook(s)
══════════════════════════════════════════════════════

  Workbook                          Tables  Calcs  Orphans  Coverage
  ─────────────────────────────────────────────────────────────────────
  {workbook_1}                      {N}     {N}    {N}      {%}%
  {workbook_2}                      {N}     {N}    {N}      {%}%
  ...
  ─────────────────────────────────────────────────────────────────────
  Total                             {N}     {N}    {N}      {%}%

  Coverage = realistic estimate (after orphan + circular + cross-ref exclusion)
```
