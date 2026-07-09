<!-- currency: databricks — 2026-07 (PR1 window deep-analysis 2026-07-09: MV→TS window translations live-verified against a Databricks fixture + ThoughtSpot number-match — trailing/leading anchor args corrected (C1/C3), leading/all/cumulative/semi-additive confirmed (C3/C4/C5/C7), period-filter offset corrected from wall-clock sum_if to row-relative moving_sum LAG idiom (C6/C6a); quarter/year offset grains Deferred (C8); see BL-032; PR1.5 semantic deep-dive 2026-07-09: LOD dimension × filter (A1) CONFIRMED filter-aware on TS under both filter kinds, cross-platform DIVERGENCE for a DBX consumer's ad hoc query-time WHERE (A2, DBX-internal asymmetry); cross-measure ratio × grain (B1) CONFIRMED ratio-of-sums cross-platform at every grain; global filter: × window ordering (C1) CONFIRMED filter-before-window cross-platform, frame semantics DIVERGENCE (date-interval vs row-positional); semi-additive × date-range filter (D1) CONFIRMED last/first-in-filtered-range cross-platform; trailing-window frame (E1) DIVERGENCE — DBX date-interval vs TS row-positional on gapped data, density caveat added; A3 follow-up (user-suggested) 2026-07-09: group_aggregate's `{}` filter argument CORRECTS the A1/A2 "no TS analogue" conclusion — `{}` is search-filter-blind but model-filter-aware, reproducing DBX's MV-filter-aware + query-WHERE-blind composite when paired with a mirrored model-level filters: block; subtraction form query_filters() - {col} import-accepted but does not exclude a derived-formula filter — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md; see BL-032) -->

# Reverse Mapping Rules Reference

Databricks Metric View → ThoughtSpot Model TML. Consult during Steps 5–9.

---

## Retrieving the Metric View Definition

### Step 1: Discover Metric Views

```sql
SELECT table_catalog, table_schema, table_name
FROM system.information_schema.tables
WHERE table_type = 'METRIC_VIEW'
  AND table_catalog = '{catalog}'
```

### Step 2: Fetch Definition

```sql
DESCRIBE TABLE EXTENDED {catalog}.{schema}.{view_name}
```

Parse the result set (columns: `col_name`, `data_type`, `comment`, `metadata`):
- Find row where `col_name = 'View Text'` — the `data_type` column contains the YAML
- Find row where `col_name = 'Type'` — confirm `data_type = 'METRIC_VIEW'`

### Step 3: Parse YAML

The `View Text` value is a YAML string. Parse it to extract:
- `version` — determines v0.1 (single-source) vs v1.1 (multi-source) path
- `source` — table FQN, SQL query (parenthesized or bare), or another metric view — see
  [Source Forms](../../schemas/databricks-metric-view.md#source-forms-verified-2026-07)
  and the detection rules below (do not assume `source` is always a table FQN)
- `entities` — list of source tables with aliases (v1.1)
- `fields` or `dimensions` — list of dimension definitions (`fields:` is the GA-canonical key; `dimensions:` is accepted for backward compat — check `fields` first)
- `measures` — list of measure definitions
- `filter` — optional global filter expression

---

## Single-Source Parsing (v0.1 or v1.1 with `source:`)

### Source Table

`source: catalog.schema.table_name` identifies the single source table — but `source:`
(and `joins[].source`) can take **four forms**; classify before assuming it is a plain
table FQN (see [Source Forms](../../schemas/databricks-metric-view.md) in the schema
reference):

**Detection order:**
1. Strip leading/trailing whitespace from the `source:` value.
2. **SQL query (parenthesized or bare):** does it start with `(SELECT`, `(WITH`,
   `SELECT `, or `WITH ` (case-insensitive)? → go to "`source:` as SELECT subquery" below.
   Do not require parentheses — the current YAML reference documents the bare form
   (`source: SELECT ... FROM ...`, no parens) as valid, and treating a bare SQL source
   as a table FQN silently produces a Table TML whose measure columns are unqueryable
   (`METRIC_VIEW_MISSING_MEASURE_FUNCTION`).
3. **Metric view (MV-on-MV):** otherwise, it looks like an FQN — but an FQN cannot be
   assumed to be a physical table. Query
   `system.information_schema.tables WHERE table_type = 'METRIC_VIEW' AND table_catalog = '{catalog}' AND table_schema = '{schema}' AND table_name = '{name}'`
   for the referenced FQN. If it matches → go to "`source:` as another Metric View
   (MV-on-MV)" below.
4. **Table FQN:** otherwise, proceed as a physical table:
   1. Extract `catalog`, `schema`, and `table_name` from the FQN
   2. Fetch the table's columns: `DESCRIBE TABLE {source}`
   3. Build a column map: `{column_name: data_type}` for reference during classification

**`source:` as SELECT subquery:** Some MVs use a SQL query as `source:` — either
parenthesized (`source: (SELECT ... FROM ...)`) or bare/unparenthesized
(`source: SELECT ... FROM ...`). Present the subquery to the user and offer:

```
The Metric View source is a SELECT subquery, not a table reference:
  {subquery}

How should this be handled?
  D — Create a Databricks VIEW from this SQL, then use it as the source table
  T — Create a ThoughtSpot SQL-Based View (sql_view TML) from this SQL
  M — Map to an existing Unity Catalog table or view (you provide the name)
  S — Skip — cannot convert this Metric View
```

- **D (Databricks VIEW):** Generate and execute `CREATE OR REPLACE VIEW {catalog}.{schema}.{view_name} AS {subquery}`, then use the new view FQN as the source table for the Table TML.
- **T (ThoughtSpot SQL View):** Create a `sql_view` TML with the subquery as `sql_query`, referencing the Databricks connection. The model then references this sql_view instead of a physical table.
- **M (Map to existing):** Ask for the fully-qualified Unity Catalog object name. Use as the source table.
- **S (Skip):** Cancel the conversion.

**`source:` as another Metric View (MV-on-MV):** If `source:` (or a `joins[].source`)
resolves to a Metric View rather than a physical table or SQL query, **fail loud** —
do not silently treat it as a table FQN. This repo has no verified pattern for
flattening a chained Metric View into a single ThoughtSpot Model (the upstream MV's
own dimensions/measures would need to be resolved and merged first, which is a
judgment call, not a mechanical transform). Stop and report:

```
The Metric View's source ('{fqn}') is itself a Metric View, not a physical table
or SQL query. Chained (MV-on-MV) sources are not yet supported by this skill —
converting '{fqn}' directly first, or flattening the source chain in Databricks,
are the two ways to proceed. Which would you like to do?
```

Do not proceed with a Table TML built directly against the upstream MV's name —
its measure columns require `MEASURE()`/`agg()` to query and are not plain columns.

### v1.1 Column Metadata → ThoughtSpot Properties

When the MV uses v1.1, map rich metadata:

| MV field | ThoughtSpot property |
|---|---|
| `display_name:` | Column `name` (display name) |
| `comment:` | Column `description` |
| `synonyms:` | `properties.synonyms[]` + `properties.synonym_type: USER_DEFINED` |
| Top-level `comment:` | Model `description` |
| `name:` (identifier) | Use as `column_id` basis if no `display_name` |

If the MV uses v0.1 (no `display_name`), use the `name:` field as both the display
name and identifier.

### Dimension → ThoughtSpot Column

Each dimension entry:
```yaml
- name: order_date
  expr: DM_ORDER_ORDER_DATE
  display_name: 'Order Date'
  comment: 'Date the order was placed.'
  synonyms: ['order placed', 'purchase date']
```

**Classification decision:**

```
Is expr a direct column reference (single identifier, no functions)?
  YES → ATTRIBUTE column
        name: use display_name (or name if no display_name)
        column_id: use the physical column name from expr
        description: use comment
        properties.synonyms: use synonyms list (with synonym_type: USER_DEFINED)
  NO  → Does expr contain AGG() OVER (PARTITION BY ...)?
          YES → LOD formula (see LOD section below)
          NO  → Formula ATTRIBUTE
                Create a formulas[] entry with translated expression
                Create a columns[] entry with formula_id reference
```

**Direct column reference examples:**
- `expr: product_category` → column reference to `product_category`
- `expr: region` → column reference to `region`

**Computed expression examples:**
- `expr: date_trunc('day', transaction_date)` → formula
- `expr: CASE WHEN tenure < 12 THEN '0-1 Year' ... END` → formula
- `expr: CONCAT(LAST_NAME, ', ', FIRST_NAME)` → formula

### LOD Dimension → ThoughtSpot Formula

Dimensions with window functions are LOD calculations:

```yaml
- name: category_quantity
  expr: SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)
```

Maps to a ThoughtSpot formula:
```
group_aggregate(sum(quantity), {product_category}, query_filters())
```

Parse the pattern: `AGG(col) OVER (PARTITION BY dim1, dim2)` →
`group_aggregate(agg(col), {dim1, dim2}, query_filters())`

The third argument `query_filters()` ensures the LOD respects user-applied filters.

**Live-verified 2026-07-09** (see `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`,
A1/A2) — this claim is **CONFIRMED on the ThoughtSpot side**: `query_filters()` makes
the LOD respect user-applied filters under both a query-level pin and a model-level
`filters:` block, with no filter-blind condition on TS. **Cross-platform asymmetry
(DBX-side):** the equivalence holds for a Databricks consumer whose filter is baked
into the MV's own global `filter:` block (that condition matches the TS behavior
above exactly) — it does **not** hold for a Databricks consumer applying an ad hoc
query-time `WHERE` on an MV with no global `filter:`, because that DBX condition is
filter-**blind** for a partition-window LOD dimension (it prunes output rows only,
never the window's computed value). No `query_filters()`-based ThoughtSpot formula
can reproduce that DBX filter-blind behavior — this is a documented DBX-side
asymmetry, not a fixable formula gap. The same caveat applies to `range: all` window
measures below, which use this identical LOD mechanism.

**A3 follow-up, live-verified 2026-07-09** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, A3) — the asymmetry above **is
reproducible** on the ThoughtSpot side after all. `group_aggregate`'s third argument
also accepts the documented empty-set literal `{}` (`thoughtspot-formula-patterns.md`
Filter argument table): `group_aggregate(sum(x), {dim}, {})`. Live-tested against the
identical fixture, `{}` is **blind to a search-level/query-time filter** (a query pin
does not change the LOD value — matches DBX's ad hoc query-time `WHERE`-blind
condition exactly) but **still respects a model-level `filters:` block** (the LOD value
narrows when the model itself carries a `filters:` block — matches DBX's own
MV-global-`filter:`-aware condition exactly). **Refined mapping:** default to
`query_filters()` for the common case (an MV's global `filter:`, simpler formula); use
`{}` **paired with a model-level `filters:` block that mirrors the MV's own `filter:`**
when the target needs to reproduce a DBX consumer's ad hoc query-time `WHERE`-blind LOD
specifically — this combination reproduces both halves of the DBX composite in one
ThoughtSpot construct. A candidate subtraction form, `query_filters() - { [TABLE::col] }`
(also documented in `thoughtspot-formula-patterns.md`), was import-accepted but did
**not** exclude a filter pinned on a *derived* boolean formula built from that column —
recorded as a live finding, not a working alternative to `{}` for this scenario.

### Measure → ThoughtSpot Column or Formula

Each measure entry:
```yaml
- name: amount
  expr: SUM(LINE_TOTAL)
  display_name: 'Amount'
  comment: 'Dollar value of an order-line item.'
  synonyms: ['revenue', 'sales']
```

**Classification decision:**

```
Strip SQL comments (-- and /* */) from expr before classifying.

Does the measure have a `window:` section?
  YES → Window measure — classify by window type FIRST (see Window Function
        Translation below). The expr and window are translated together into
        a single ThoughtSpot formula. Flag with ⚠ WINDOW in review checkpoint.
        
        range: trailing N day  → moving_sum / moving_average (default/exclusive:
                                   start=N, end=-1; inclusive: start=N-1, end=0 —
                                   see Rolling Window below; Live-verified 2026-07-09)
        range: leading N day   → moving_sum / moving_average (default/exclusive:
                                   start=-1, end=N; inclusive: start=0, end=N-1 —
                                   see Leading Window below; Live-verified 2026-07-09)
        range: cumulative      → cumulative_sum (Live-verified 2026-07-09)
        range: current + raw date order        → last_value/first_value (semi-additive;
                                                   Live-verified 2026-07-09)
        range: current + truncated period, no offset → plain sum(m) at the query grain
                                                   (Live-verified 2026-07-09 — see Period
                                                   Filter below; this is row-relative, NOT
                                                   a wall-clock filter)
        range: current + truncated period, offset: -N <unit> → moving_sum(m, N, -N, date)
                                                   (LAG idiom; Live-verified 2026-07-09 —
                                                   one-row-per-period caveat, see Period
                                                   Filter below)
        range: all              → group_aggregate(sum(m), {partition dims}, query_filters())
                                   (Live-verified 2026-07-09 — see All-Partition Window below)
        
        For moving_sum/moving_average: strip the outer AGG wrapper from expr
        and translate the inner expression only. SUM(a * b) + trailing 7 day
        (default/exclusive) → moving_sum ( [a] * [b] , 7 , -1 , [date] )
        
  NO  → Continue with expr-only classification below.

Is expr a simple aggregate? (single AGG function wrapping a column or simple expression)
  Pattern: AGG(column_name) or AGG(DISTINCT column_name)
  
  Is it COUNT(DISTINCT col)?
    YES → Formula MEASURE: unique count ( [TABLE::col] )
          Do NOT use aggregation: COUNT_DISTINCT on a column_id — ThoughtSpot
          silently overrides column_type to ATTRIBUTE on physical column refs.
          Always create a formulas[] entry instead.
    NO  → MEASURE column
          Extract the aggregate function → aggregation field
          Extract the inner column → column_id
          Map display_name → name, comment → description, synonyms → properties.synonyms
        
  NO  → Does expr contain AGG(...) FILTER (WHERE ...)?
          YES → Conditional aggregate → *_if formula (see below)
  NO  → Is expr COUNT(*)?
          YES → Formula MEASURE: count ( 1 )
  NO  → Does expr contain MEASURE() or ANY_VALUE()?
          YES → Cross-measure reference (see below)
  NO  → Does expr contain (SELECT ...)?
          YES → Subquery — untranslatable, log in Unmapped Report
  NO  → Formula MEASURE (ratios, nested aggregates, arithmetic)
          Create a formulas[] entry with translated expression
```

**Simple aggregate examples:**

| Measure `expr` | TS `aggregation` | TS column reference |
|---|---|---|
| `SUM(sales)` | `SUM` | `sales` |
| `AVG(tenure)` | `AVERAGE` | `tenure` |
| `MIN(price)` | `MIN` | `price` |
| `MAX(quantity)` | `MAX` | `quantity` |
| `COUNT(*)` | — | Formula: `count ( 1 )` |
| `COUNT(DISTINCT customer_id)` | — | Formula: `unique count ( [TABLE::customer_id] )` |

**Complex expression examples (→ formulas[]):**

| Measure `expr` | Reason |
|---|---|
| `SUM(a * b * (1 - c))` | Arithmetic inside aggregate |
| `SUM(x) / COUNT(DISTINCT y)` | Multiple aggregates / ratio |
| `COUNT(DISTINCT x) / (SELECT ...)` | Subquery |
| `COALESCE(SUM(a) / NULLIF(SUM(b), 0), 0)` | safe_divide pattern → `safe_divide(sum(a), sum(b))` |

### Cross-Measure References → ThoughtSpot Formula

Measures using `MEASURE()` and `ANY_VALUE()` are cross-measure references:

```yaml
- name: category_contribution_ratio
  expr: MEASURE(quantity) / ANY_VALUE(category_quantity)
```

Translation:
- `MEASURE(name)` → reference to the ThoughtSpot measure column `[name]`
- `ANY_VALUE(dim_name)` → reference to the LOD dimension `[dim_name]`
- Combined: `[quantity] / [category_quantity]`

**Live-verified 2026-07-09 across query grain** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, B1) — **CONFIRMED**: this
inlining computes true ratio-of-sums, cross-platform, at every grain tested
(fine/coarse/total). No sum-of-ratios or average-of-ratios divergence found at any
grain — the mapping's implicit any-grain assumption holds; no formula change or
grain caveat is needed.

### Conditional Aggregates — `FILTER (WHERE ...)` → ThoughtSpot Formula

Databricks SQL `FILTER (WHERE ...)` clauses on aggregates translate to ThoughtSpot's
native `*_if` conditional aggregate functions:

| Databricks MV `expr` | ThoughtSpot formula |
|---|---|
| `SUM(x) FILTER (WHERE cond)` | `sum_if ( cond , [x] )` |
| `COUNT(x) FILTER (WHERE cond)` | `count_if ( cond , [x] )` |
| `COUNT(DISTINCT x) FILTER (WHERE cond)` | `unique_count_if ( cond , [x] )` |
| `AVG(x) FILTER (WHERE cond)` | `average_if ( cond , [x] )` |
| `MIN(x) FILTER (WHERE cond)` | `min_if ( cond , [x] )` |
| `MAX(x) FILTER (WHERE cond)` | `max_if ( cond , [x] )` |
| `STDDEV(x) FILTER (WHERE cond)` | `stddev_if ( cond , [x] )` |
| `VARIANCE(x) FILTER (WHERE cond)` | `variance_if ( cond , [x] )` |

**`*_if` function signature:** `agg_if ( condition , measure_expression )`

**Fallback:** If no native `*_if` function exists for the aggregate type, use
`agg ( if ( cond , [x] , null ) )` (or `0` for SUM).

Translate the `cond` using standard SQL → TS rules from `ts-databricks-formula-translation.md`.

These are always **formula MEASURE** columns — create a `formulas[]` entry.

### `COUNT(*)` → ThoughtSpot

`COUNT(*)` has no direct ThoughtSpot equivalent. Default to a formula: `count ( 1 )`.

### Semi-Additive Measures → ThoughtSpot Formula

Measures with `window:` containing `semiadditive` fall into two categories depending
on whether the `order:` dimension is a raw date or a truncated period. See the
classification decision tree in the "Window with Range/Offset" section below.

**True semi-additive** (snapshot metric, `order:` is a raw date):

```yaml
- name: inventory_balance
  expr: SUM(FILLED_INVENTORY)
  comment: "Closing stock level — end-of-period balance."
  window:
    - order: balance_date
      semiadditive: last
      range: current
```

Maps to ThoughtSpot `last_value` formula:
```
last_value ( sum ( [FILLED_INVENTORY] ) , query_groups ( ) , { [balance_date] } )
```

**Period filter** (flow metric, `order:` is a truncated dimension):

```yaml
- name: monthly_revenue
  expr: SUM(LINE_TOTAL)
  window:
    - order: order_month
      semiadditive: last
      range: current
```

Maps to a plain `sum` at the query grain (**corrected 2026-07-09** — see the
Period Filter subsection of the "Window with Range/Offset" section below;
`range: current` with no `offset` is row-relative, not a wall-clock filter):
```
sum ( [LINE_TOTAL] )
```

With an offset (e.g. `offset: -1 month`), this becomes the row-relative
`moving_sum` `LAG` idiom instead — see the Period Filter subsection below for
the full mapping and its one-row-per-period caveat.

### Filter → Boolean Formula Column (always)

The `filter:` field is a global WHERE clause. ThoughtSpot models DO support
model-level filters via the `filters:` section in TML. **Always create a boolean
formula column AND apply it as a model-level filter.**

```
If the MV has a filter:
  1. Translate the SQL filter to a ThoughtSpot boolean formula
  2. Create a formula column:
       name: "MV Filter"
       id: "formula_MV Filter"
       expr: <translated boolean formula>
       column_type: ATTRIBUTE
  3. Add a columns[] entry with formula_id: "formula_MV Filter"
  4. Add a model-level filters: section:
       filters:
       - column:
         - MV Filter
         oper: in
         values:
         - 'true'
  5. Note in description: "MV Filter applied automatically via model filter."
```

The `filters:` section enforces the filter on ALL queries against the model.
Without it, the formula exists but is never applied unless users manually pin it.
Do NOT duplicate the filter in the model `description` — it's enforced, not advisory.

**Live-verified 2026-07-09** (see `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`,
C1) — **filter ordering is CONFIRMED cross-platform**: both a Databricks MV's global
`filter:` and a ThoughtSpot model-level `filters:` block filter rows *before* a
windowed measure (e.g. `moving_sum`) computes over them — the model-level `filters:`
pattern above correctly reproduces this ordering. **Frame semantics DIVERGE on
filtered/gapped data** (same root cause as E1 below): Databricks' `trailing N day`
spans a date *interval*, while ThoughtSpot's `moving_sum` counts surviving *rows* —
on data with gaps (including gaps created by this filter itself), the two platforms
can compute different numbers for a trailing/leading window even though both filter
before windowing. See the density caveat in the Rolling Window / Leading Window
subsections below.

**SQL → ThoughtSpot filter translation:**

| SQL pattern | ThoughtSpot formula |
|---|---|
| `col = 'val'` | `[TABLE::col] = 'val'` |
| `NOT col` (boolean) | `[TABLE::col] = false` |
| `col IN ('a', 'b')` | `[TABLE::col] = 'a' or [TABLE::col] = 'b'` |
| `col BETWEEN a AND b` | `[TABLE::col] >= a and [TABLE::col] <= b` |
| `col >= 'date'` | `[TABLE::col] >= to_date('date', 'yyyy/MM/dd')` |

**Examples from production MVs:**

Simple AND filter (still create formula):
```
filter: NOT is_return AND transaction_status = 'Completed'
→ Formula: [TABLE::is_return] = false and [TABLE::transaction_status] = 'Completed'
```

IN clause — requires OR expansion:
```
filter: NOT is_return AND transaction_status IN ('Completed', 'Shipped')
→ Formula: [TABLE::is_return] = false and ( [TABLE::transaction_status] = 'Completed' or [TABLE::transaction_status] = 'Shipped' )
```

Complex — BETWEEN (formula):
```
filter: churn_date BETWEEN '2024-05-01' AND '2025-04-30'
→ Formula: [TABLE::churn_date] >= '2024-05-01' and [TABLE::churn_date] <= '2025-04-30'
```

---

## v1.1 Multi-Source Parsing (Nested Joins)

### Join Structure → Table TMLs

v1.1 MVs with joins use a nested hierarchy. The `source:` is the fact table;
`joins:` contains dimension tables, which can themselves contain nested sub-joins:

```yaml
source: catalog.schema.fact_table
joins:
  - name: orders
    source: catalog.schema.dm_order
    "on": source.FK = orders.PK
    rely: { at_most_one_match: true }
    joins:
      - name: customers
        source: catalog.schema.dm_customer
        "on": orders.FK2 = customers.PK2
```

Maps to ThoughtSpot:
- One Table TML per unique `source:` value (fact + all dimension tables)
- The MV `source:` → primary fact table in `model_tables[0]`
- Each `joins[].source` → additional Table TML

### Joins → ThoughtSpot Model Joins

Walk the nested join hierarchy and flatten into ThoughtSpot `joins[]`:

```yaml
# MV nested join:
joins:
  - name: orders
    source: catalog.dm_order
    "on": source.ORDER_ID = orders.ORDER_ID
    joins:
      - name: customers
        source: catalog.dm_customer
        "on": orders.CUSTOMER_ID = customers.CUSTOMER_ID
```

Corresponding ThoughtSpot model joins:
```yaml
model_tables:
  - id: FACT_TABLE
    name: FACT_TABLE
    joins:
      - name: fact_to_orders
        with: DM_ORDER
        on: "[FACT_TABLE::ORDER_ID] = [DM_ORDER::ORDER_ID]"
        type: INNER
        cardinality: MANY_TO_ONE
  - id: DM_ORDER
    name: DM_ORDER
    joins:
      - name: orders_to_customers
        with: DM_CUSTOMER
        on: "[DM_ORDER::CUSTOMER_ID] = [DM_CUSTOMER::CUSTOMER_ID]"
        type: INNER
        cardinality: MANY_TO_ONE
  - id: DM_CUSTOMER
    name: DM_CUSTOMER
```

**Cardinality mapping** — two MV syntaxes, same ThoughtSpot output:

| MV syntax | ThoughtSpot join `cardinality:` |
|---|---|
| `rely: { at_most_one_match: true }` | `MANY_TO_ONE` |
| `cardinality: many_to_one` (Runtime 18.1+) | `MANY_TO_ONE` |
| `cardinality: one_to_many` (Runtime 18.1+) | `ONE_TO_MANY` |
| Neither `rely:` nor `cardinality:` present | `MANY_TO_ONE` (spec default) |

When both `rely:` and `cardinality:` are present, `cardinality:` takes precedence.

### `using:` Joins — Shared-Column Shorthand (verified 2026-07)

A join may specify `using: [COL1, COL2, ...]` instead of `"on":` — an array of
column names present under the **same name** in both the parent (`source` for
top-level joins, or the parent join's alias for nested joins) and the joined
table. A join has exactly one of `on:` or `using:` — check for `using:` first if
`"on":` is absent; do not assume every join has an `on:` clause.

```yaml
# MV using: join
joins:
  - name: orders
    source: catalog.dm_order
    using: [ORDER_ID]
```

Translate `using: [COL]` to the same ThoughtSpot join expression form as `on:`,
equating the column in both tables:

```yaml
model_tables:
  - id: FACT_TABLE
    name: FACT_TABLE
    joins:
      - name: fact_to_orders
        with: DM_ORDER
        on: "[FACT_TABLE::ORDER_ID] = [DM_ORDER::ORDER_ID]"
        type: INNER
        cardinality: MANY_TO_ONE
```

For multiple shared columns, AND-join each pair:

```yaml
# MV: using: [ORDER_ID, REGION_ID]
# → ThoughtSpot:
on: "[FACT_TABLE::ORDER_ID] = [DM_ORDER::ORDER_ID] AND [FACT_TABLE::REGION_ID] = [DM_ORDER::REGION_ID]"
```

Since the column name is identical on both sides of a `using:` join, skip the
dot-path parsing used for `"on":` expressions (see Column References below) —
the shared name IS both the parent-side and joined-side physical column name.
Cardinality (`rely:`/`cardinality:`/default) applies identically regardless of
whether the join used `on:` or `using:`.

### Column References in v1.1

Dimensions and measures use dot-path notation through the join hierarchy:

| MV expression | Physical table | Physical column |
|---|---|---|
| `source.COL` | fact table | COL |
| `orders.COL` | dm_order | COL |
| `orders.customers.COL` | dm_customer | COL (through orders→customers path) |
| `products.category.COL` | dm_category | COL (through products→category path) |

Parse the dot-path to determine which Table TML the column belongs to. The last
segment is the column name; preceding segments trace the join path.

### Format Field → ThoughtSpot Properties

| MV `format:` | ThoughtSpot property |
|---|---|
| `type: currency` + `currency_code: USD` | `properties.currency_type: { currency_code: USD }` |
| `type: percentage` | **Unmapped** — note in model description |
| `decimal_places` | **Unmapped** — ThoughtSpot handles formatting at display level |

### Window with Range/Offset → ThoughtSpot Formulas

Measures with `window:` map to different ThoughtSpot formulas depending on the
type of measure and the `order:` dimension. Use this classification:

```
Does the window have `range: current`?
  YES → Is `order:` a raw date dimension (not a truncated period)?
          YES → True semi-additive (snapshot metric)
                → last_value ( sum ( [m] ) , query_groups ( ) , { [date] } )   [semiadditive: last]
                → first_value ( sum ( [m] ) , query_groups ( ) , { [date] } )  [semiadditive: first]
          NO  → Period filter (flow/additive metric) — row-relative, not wall-clock
                → no offset: plain sum ( [m] ) at the query grain
                → offset: -N <unit>: moving_sum ( [m] , N , -N , [date] )   (LAG idiom;
                  caveat: exactly one row per period in the `order:` dimension)
  NO  → Is `range: trailing <N> <unit>`?
          YES → Rolling look-back window
                → default / exclusive: moving_sum ( [m] , N , -1 , [date] )
                → inclusive:           moving_sum ( [m] , N-1 , 0 , [date] )
  NO  → Is `range: cumulative`?
          YES → cumulative_sum ( [m] , [date] )
  NO  → Is `range: leading <N> <unit>`?
          YES → Rolling look-ahead window
                → default / exclusive: moving_sum ( [m] , -1 , N , [date] )
                → inclusive:           moving_sum ( [m] , 0 , N-1 , [date] )
  NO  → Is `range: all`?
          YES → Unbounded window across the entire partition, scoped per query
                partition → group_aggregate ( sum ( [m] ) , { partition dims } , query_filters ( ) )
```

**All formulas above are Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C1–C7). Full derivation and
day_index-level number matches are in the Rolling Window / Leading Window /
Period Filter / All-Partition subsections below.

**Anchor-row modifier (`inclusive` | `exclusive`) — Live-verified 2026-07-09 (matrix
C1/C2/C3):** `trailing`/`leading` ranges accept an optional `inclusive|exclusive`
modifier controlling whether the anchor (current) row is included in the window.
The modifier applies **only** to `trailing`/`leading` — `current`, `cumulative`, and
`all` do not accept it. **Default: `exclusive`**, confirmed live 2026-07-08
(`trailing N day` == `trailing N day exclusive` at all 24 fixture rows).

The `trailing N day` ↔ `moving_sum([m], N, 0, [date])` equivalence recorded in this
repo before 2026-07-09 is **wrong**: `moving_sum([m], N, 0, [date])` always includes
the anchor row (spans N+1 rows), so it reproduces `trailing (N+1) day inclusive`, not
`trailing N day` (default/exclusive). See the Rolling Window and Leading Window
subsections below for the corrected mappings.

**How to identify the `order:` dimension type:**
- Look up the dimension's `expr` in the MV YAML
- Raw date: `expr` is a direct column reference (`balance_date`) or `date_trunc('day', ...)`
- Truncated period: `expr` uses `date_trunc('month', ...)`, `date_trunc('quarter', ...)`,
  `date_trunc('year', ...)`, or similar period-truncation function

#### True Semi-Additive (`order:` is raw date)

Snapshot metrics (inventory balances, account balances) where summing across time
is not meaningful — you want the last observation in each period.

| MV window pattern | ThoughtSpot equivalent |
|---|---|
| `range: current`, `order: raw_date`, `semiadditive: last` | `last_value ( sum ( [m] ) , query_groups ( ) , { [date] } )` |
| `range: current`, `order: raw_date`, `semiadditive: first` | `first_value ( sum ( [m] ) , query_groups ( ) , { [date] } )` |

Example:
```yaml
# MV: inventory balance — end-of-period snapshot
- name: inventory_balance
  expr: SUM(FILLED_INVENTORY)
  window:
    - order: balance_date        # raw date dimension
      semiadditive: last
      range: current
```
→ `last_value ( sum ( [FILLED_INVENTORY] ) , query_groups ( ) , { [balance_date] } )`

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C7). `last` was reconfirmed and
`first` was exercised live for the first time in this repo; both matched DBX exactly
at category grain.

**Live-verified 2026-07-09 under a query-time date-range filter** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, D1) — **CONFIRMED
cross-platform**: `last_value`/`first_value` under a query-level date-range pin
collapse to the last/first observation *within the filtered range* on both
platforms, identical values at every row including the single-surviving-row edge
case. No formula change needed.

#### Period Filter (`order:` is truncated period dimension)

Flow/additive metrics (revenue, quantity) with `range: current` + a truncated
period `order:` dimension.

**Corrected 2026-07-09 — row-relative, not wall-clock (matrix C6/C6a).** The
mapping previously documented here (`sum_if(diff_months([date], today())=N, [m])`)
is **wrong**: live testing (`docs/audit/2026-07-08-dbx-window-claim-matrix.md`,
Query B1, 3-hypothesis discriminator) proved `range: current` + `offset` is
evaluated **relative to each output row's own period**, not anchored to wall-clock
`today()`. Querying `prior_month_revenue` across a multi-month trend returns a
`LAG`-style shift for every row, not a fixed-calendar-month filter — the old
mapping only coincidentally matched a single current-period snapshot query and
fails for any query spanning more than one period.

**Offset conversion (unchanged from before the correction):** divide the offset
value by the `order:` dimension's own period size to get a period count N — `-1
month` at month grain = 1. `-3 month` at quarter grain = 1 quarter. `-1 year` at
month grain = 12 months. That N then drives the row-relative `moving_sum` idiom
below (valid under the one-row-per-period caveat).

**Corrected mapping:**

| MV window pattern | ThoughtSpot equivalent |
|---|---|
| `range: current`, no `offset` (any grain: month/quarter/year) | `sum ( [m] )` at the query grain — plain aggregate, no filter needed |
| `range: current`, `order: month_dim`, `offset: -1 month` | `moving_sum ( [m] , 1 , -1 , [date] )` — **Live-verified 2026-07-09** |
| `range: current`, `order: month_dim`, `offset: -1 year` | `moving_sum ( [m] , 12 , -12 , [date] )` — Deferred (C8), same idiom extrapolated to N=12, not separately live-tested |
| `range: current`, `order: quarter_dim`, `offset: -3 month` | `moving_sum ( [m] , 1 , -1 , [date] )` — Deferred (C8), not separately live-tested at quarter grain |
| `range: current`, `order: quarter_dim`, `offset: -6 month` | `moving_sum ( [m] , 2 , -2 , [date] )` — Deferred (C8), not separately live-tested at quarter grain |
| `range: current`, `order: year_dim`, `offset: -1 year` | `moving_sum ( [m] , 1 , -1 , [date] )` — Deferred (C8), not separately live-tested at year grain |
| `range: current`, `order: year_dim`, `offset: -2 year` | `moving_sum ( [m] , 2 , -2 , [date] )` — Deferred (C8), not separately live-tested at year grain |
| `MEASURE(a) - MEASURE(b)` (period comparison, e.g. MoM/YoY growth %) | Inline both `moving_sum`/`sum` expressions — cross-formula refs not supported during TML import |

**`[date]` in the `moving_sum` formulas above** is the physical date column (e.g.,
`[dm_order::ORDER_DATE]`), not the truncated dimension formula — same rule as the
Rolling Window section below.

**Caveat (carries forward to C8's quarter/year-grain extrapolations below): this
mapping is only exact when the query returns exactly one row per period** in the
`order:` dimension — `moving_sum`'s row-based offset only equals a period-based
offset under that precondition. General use (a query with gaps or multiple rows
per period) needs a period-grain pre-aggregation first; flag for manual review if
the query grain can't guarantee one row per period.

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C6, C6a). Verified for N=1
(`moving_sum([m], 1, -1, [date])` matched DBX `prior_month_revenue` exactly,
including the out-of-range `NULL` at the earliest row); N=12 (`-1 year` at month
grain) is the documented extrapolation of the same verified idiom, not separately
live-tested (see C8 below).

**Growth % formulas** (MoM, QoQ, YoY) inline both period expressions and compute
the ratio directly — no cross-formula references needed:
```
( sum ( [m] )
- moving_sum ( [m] , 1 , -1 , [date] ) )
/ moving_sum ( [m] , 1 , -1 , [date] ) * 100
```

#### Rolling Window (`range: trailing N day`)

Date-based rolling windows. ThoughtSpot's `moving_sum` / `moving_average` operate
on row counts, so this assumes one row per day (daily grain).

**Corrected 2026-07-09 (matrix C1/C2).** `moving_sum([m], N, 0, [date])` always
includes the anchor row — it spans **N+1 rows** (N preceding + anchor) — so it
reproduces `trailing (N+1) day inclusive`, not `trailing N day` (default/exclusive).
The mapping below is the corrected form, verified against every row of a 24-row
fixture (2 categories × 12 days) including boundary partial-window/NULL rows — e.g.
at an interior row with 5 buffer days on both sides, `trailing3_default` (exclusive)
matched the hand-computed exclusive-window sum of the 3 preceding rows exactly,
not the inclusive-of-anchor sum.

| MV window pattern | ThoughtSpot equivalent |
|---|---|
| `range: trailing N day` (default) / `trailing N day exclusive`, `order: date_dim` | `moving_sum ( [m] , N , -1 , [TABLE::date_col] )` |
| `range: trailing N day inclusive`, `order: date_dim` | `moving_sum ( [m] , N-1 , 0 , [TABLE::date_col] )` |

**`[m]` is the inner expression only** — strip the outer aggregate wrapper from `expr`.
`SUM(a * b)` → `[TABLE::a] * [TABLE::b]`.

**`[TABLE::date_col]` must be the physical date column** (`[TABLE::transaction_date]`),
not the formula dimension name. ThoughtSpot's `moving_sum` sort argument requires a
`TABLE::column` reference — formula references fail with "Search did not find" errors.
Look up the `order:` dimension's `expr` to find the underlying physical column.

If the measure uses `AVG` instead of `SUM`, use `moving_average` instead of `moving_sum`.

**Boundary behavior (Live-verified 2026-07-09):** Databricks returns a partial sum
when 1..N-1 rows are available in the trailing direction, and `NULL` only when zero
rows are available — never an error, never a silent 0. ThoughtSpot's `moving_sum`
matches this exactly.

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C1, C2).

**Density caveat (E1, live-verified 2026-07-09 on gapped data — see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`).** The above mapping was
re-verified against a fixture with date gaps and found to **diverge from Databricks
on that data**: Databricks' `trailing N day` is a genuine date-interval window;
`moving_sum` counts rows. On dense daily data (no gaps) the two framings are
identical, which is why the C1/C2 verification above didn't surface this.

Row-positional: matches Databricks' date-interval trailing/leading windows only when the order column is dense at the window's unit grain (one row per unit, no gaps) — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md (E1). Treat this mapping as an approximation requiring a density check on any source with possible gaps.

#### Cumulative

| MV window pattern | ThoughtSpot equivalent |
|---|---|
| `range: cumulative` | `cumulative_sum ( [m] , [date] )` |

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C5): matched DBX's running
total at every row of the fixture.

#### Leading Window (`range: leading N unit`)

`range: leading <N> <unit>` is the look-ahead counterpart to `trailing`.

**Corrected 2026-07-09 (matrix C3).** The mapping previously candidated here
(`moving_sum([m], 0, N, [date])`) is **wrong** — it always includes the anchor
row (spans N+1 rows: anchor + N following) and matches neither the `exclusive`
nor `inclusive` DBX form. The corrected mapping below is verified against every
row of the fixture, including boundary partial-window/NULL rows.

| MV window pattern | ThoughtSpot equivalent |
|---|---|
| `range: leading N day` (default) / `leading N day exclusive`, `order: date_dim` | `moving_sum ( [m] , -1 , N , [TABLE::date_col] )` |
| `range: leading N day inclusive`, `order: date_dim` | `moving_sum ( [m] , 0 , N-1 , [TABLE::date_col] )` |

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C3).

**Density caveat (E1)** — same as the Rolling Window section above: row-positional:
matches Databricks' date-interval trailing/leading windows only when the order
column is dense at the window's unit grain (one row per unit, no gaps) — see
docs/audit/2026-07-09-dbx-semantic-claim-matrix.md (E1).

#### All-Partition Window (`range: all`)

`range: all` spans the entire partition, unbounded in both directions — not a
bounded rolling window. Confirmed **scoped per query partition** (e.g. per
category), not table-wide.

| MV window pattern | ThoughtSpot equivalent |
|---|---|
| `range: all`, partitioned by one or more dimensions | `group_aggregate ( sum ( [m] ) , { [partition_dim1], [partition_dim2], ... } , query_filters ( ) )` |

The partition set is the same LOD mechanism used for
`AGG() OVER (PARTITION BY ...)` dimensions — see
[ts-databricks-formula-translation.md](ts-databricks-formula-translation.md#level-of-detail-lod-functions-verified-2026-05-25).
Column type is **ATTRIBUTE**, per the standard LOD convention (`range: all` results
are query-independent, like other `group_aggregate` results). Deriving the exact
partition-dimension set from a specific MV's query grain is a per-MV judgment call,
not a fixed rule — inspect how the MV's `all_amount`-style measure is queried
(GROUP BY columns) to determine the intended partition.

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C4): matched DBX exactly at
both row grain and category grain.

**Filter asymmetry caveat (A1/A2, live-verified 2026-07-09)** — because this
mapping uses the same LOD mechanism as the `AGG() OVER (PARTITION BY ...)` LOD
Dimension mapping above, it inherits the same DBX-side asymmetry: a Databricks
MV's own global `filter:` participates in the `range: all` window, but an ad hoc
query-time `WHERE` on an MV with no global `filter:` does not — see the LOD
Dimension section above for the full caveat, **including the A3 refinement**
(`{}` + a mirrored model-level `filters:` block reproduces the DBX composite).

### Merging Multiple MVs into a Single ThoughtSpot Model

When multiple MVs represent what was originally a single multi-table ThoughtSpot
model (split due to the multi-fact limitation):

1. Detect related MVs (naming convention, shared dimension tables)
2. Generate one Table TML per unique source table across all MVs
3. Generate joins between tables in the model TML
4. Deduplicate shared dimension columns (e.g., `product_name` appearing in both
   a sales MV and an inventory MV)

---

## Data Type Mapping

Map Databricks types from `DESCRIBE TABLE` output to ThoughtSpot types:

| Databricks type | ThoughtSpot `data_type` |
|---|---|
| `string`, `varchar`, `char` | `VARCHAR` |
| `bigint`, `int`, `smallint`, `tinyint` | `INT64` |
| `double`, `float`, `decimal` | `DOUBLE` |
| `boolean` | `BOOL` |
| `date` | `DATE` |
| `timestamp`, `timestamp_ntz` | `DATETIME` |
| `binary`, `array`, `map`, `struct` | **Omit** — not supported in TS |

> **Casing convention for Databricks connections.** Unity Catalog uses **lowercase**
> identifiers for catalog, schema, and table names (`agent_skills.dunder_mifflin.dm_inventory`)
> but column names preserve the original DDL casing (often **uppercase**: `FILLED_INVENTORY`).
> When creating Table TMLs via `ts tables create`, use lowercase for `db`, `schema`, and
> `db_table`, and match column casing from `DESCRIBE TABLE` output exactly. ThoughtSpot
> validates both against the connection's JDBC metadata — mismatched case causes
> "does not exist in connection" errors.

---

## Formula Translation

Translate Databricks SQL expressions in `expr` to ThoughtSpot formula syntax.
See [ts-databricks-formula-translation.md](ts-databricks-formula-translation.md)
for the full translation reference.

Common patterns:

| Databricks SQL | ThoughtSpot formula |
|---|---|
| `date_trunc('day', col)` | `date(col)` |
| `date_trunc('month', col)` | `start_of_month(col)` |
| `date_trunc('year', col)` | `start_of_year(col)` |
| `CASE WHEN x THEN y ELSE z END` | `if (x) then y else z` |
| `COALESCE(a, b)` | `if (a != null) then a else b` |
| `CONCAT(a, b)` | `concat(a, b)` |
| `EXTRACT(MONTH FROM d)` | `month_number(d)` |
| `EXTRACT(YEAR FROM d)` | `year(d)` |
| `DATEDIFF(MONTH, start, end)` | `diff_months(start, end)` — 3-arg form |
| `DATEDIFF(DAY, start, end)` | `diff_days(start, end)` — 3-arg form |
| `COUNT(DISTINCT col)` | `unique count ( [col] )` — space, not underscore |

**Implementation notes:**
- **Date literals:** A bare `'2024-05-01'` is parsed as subtraction. Wrap in `to_date('2024-05-01', 'yyyy-MM-dd')` — hyphens are fine inside `to_date()`, no reformatting needed.
- **Operator ordering:** When tokenising operators, match `<=` and `>=` before `<` and `>`.
- **`moving_sum` / `moving_average`:** These aggregate internally — do NOT wrap `sum()` inside.
  Strip the outer aggregate: `moving_sum([col], N, -1, [date])`.

---

## ThoughtSpot TML Templates

### Table TML (for the source table)

```yaml
guid:
table:
  name: "{source_table_name}"
  db: "{catalog}"
  schema: "{schema}"
  db_table: "{table_name}"
  connection:
    name: "{databricks_connection_name}"
  columns:
  - name: "{column_name}"
    db_column_name: "{physical_column_name}"
    data_type: "{TS_DATA_TYPE}"
    column_type: "{ATTRIBUTE|MEASURE}"
```

### Model TML

```yaml
guid:
model:
  name: "{metric_view_display_name}"
  description: "{MV description or filter info}"
  tables:
  - name: "{table_tml_name}"
  model_tables:
  - name: "{table_tml_name}"
    columns:
    - name: "{dimension_or_measure_name}"
      column_id: "{table_name}::{physical_column_name}"
      properties:
        column_type: "{ATTRIBUTE|MEASURE}"
        aggregation: "{SUM|COUNT|...}"   # measures only
    formulas:
    - name: "{computed_column_name}"
      expr: "{translated_formula}"
      id: "{formula_id}"
```

See [../../schemas/thoughtspot-table-tml.md](../../schemas/thoughtspot-table-tml.md)
and [../../schemas/thoughtspot-model-tml.md](../../schemas/thoughtspot-model-tml.md)
for complete TML field references.
