<!-- currency: databricks — 2026-07 (external sweep: widened source-form detection — bare SQL + MV-on-MV fail-loud, using: join translation, leading/all window ranges flagged pending verification; see BL-032) -->

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
        
        range: trailing N day  → moving_sum / moving_average
        range: cumulative      → cumulative_sum
        range: current + raw date order   → last_value (semi-additive)
        range: current + truncated period → sum_if (period filter)
        range: leading N day   → PENDING LIVE VERIFICATION (see BL-032) — do not
                                   guess; flag for manual review
        range: all              → PENDING LIVE VERIFICATION (see BL-032) — do not
                                   guess; flag for manual review
        
        For moving_sum/moving_average: strip the outer AGG wrapper from expr
        and translate the inner expression only. SUM(a * b) + trailing 7 day
        → moving_sum ( [a] * [b] , 7 , 0 , [date] )
        
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

Maps to ThoughtSpot `sum_if` formula:
```
sum_if ( diff_months ( [ORDER_DATE] , today ( ) ) = 0 , [LINE_TOTAL] )
```

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
                → last_value ( sum ( [m] ) , query_groups ( ) , { [date] } )
          NO  → Period filter (flow/additive metric)
                → sum_if ( diff_months/quarters/years ( [date] , today ( ) ) = N , [m] )
  NO  → Is `range: trailing <N> <unit>`?
          YES → Rolling look-back window
                → moving_sum ( [m] , N , 0 , [date] )
  NO  → Is `range: cumulative`?
          YES → cumulative_sum ( [m] , [date] )
  NO  → Is `range: leading <N> <unit>`? (RECOGNISED, translation PENDING LIVE
        VERIFICATION — see BL-032)
          YES → Rolling look-ahead window. Candidate: `moving_sum ( [m] , 0 , N , [date] )`
                (look_ahead=N, window_size=0) — do NOT ship this without a live
                round-trip. Flag for manual review / log in Unmapped Report.
  NO  → Is `range: all`? (RECOGNISED, translation PENDING LIVE VERIFICATION —
        see BL-032)
          YES → Unbounded window across the entire partition. No verified
                ThoughtSpot equivalent — a partition-wide `group_aggregate(...)`
                (LOD-style) is the leading candidate but is untested against
                this construct. Flag for manual review / log in Unmapped Report.
```

**Anchor-row modifier (`inclusive` | `exclusive`) — PENDING RE-VERIFICATION:**
`trailing`/`leading` ranges accept an optional `inclusive|exclusive` modifier
controlling whether the anchor (current) row is included in the window. The
documented default is `exclusive`. The `trailing N day` ↔
`moving_sum([m], N, 0, [date])` equivalence in this table was recorded before this
default was confirmed and needs re-verification against a live instance — see
BL-032. If an MV explicitly sets `inclusive`, do not assume the mapping above is
exact until reverified.

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

#### Period Filter (`order:` is truncated period dimension)

Flow/additive metrics (revenue, quantity) where `range: current` means "filter to the
current period" and `offset` shifts the period anchor.

**Offset conversion:** divide the offset value by the period size to get the period
count. `-1 month` at month grain = -1. `-3 month` at quarter grain = -1 quarter.
`-1 year` at month grain = -12 months.

| MV window pattern | ThoughtSpot equivalent |
|---|---|
| `range: current`, `order: month_dim` | `sum_if ( diff_months ( [date] , today ( ) ) = 0 , [m] )` |
| `range: current`, `order: month_dim`, `offset: -1 month` | `sum_if ( diff_months ( [date] , today ( ) ) = -1 , [m] )` |
| `range: current`, `order: month_dim`, `offset: -1 year` | `sum_if ( diff_months ( [date] , today ( ) ) = -12 , [m] )` |
| `range: current`, `order: quarter_dim` | `sum_if ( diff_quarters ( [date] , today ( ) ) = 0 , [m] )` |
| `range: current`, `order: quarter_dim`, `offset: -3 month` | `sum_if ( diff_quarters ( [date] , today ( ) ) = -1 , [m] )` |
| `range: current`, `order: quarter_dim`, `offset: -6 month` | `sum_if ( diff_quarters ( [date] , today ( ) ) = -2 , [m] )` |
| `range: current`, `order: year_dim` | `sum_if ( diff_years ( [date] , today ( ) ) = 0 , [m] )` |
| `range: current`, `order: year_dim`, `offset: -1 year` | `sum_if ( diff_years ( [date] , today ( ) ) = -1 , [m] )` |
| `range: current`, `order: year_dim`, `offset: -2 year` | `sum_if ( diff_years ( [date] , today ( ) ) = -2 , [m] )` |
| `MEASURE(a) - MEASURE(b)` (period comparison) | Inline `sum_if` expressions — cross-formula refs not supported during TML import |

**`[date]` in the `sum_if` formulas above** is the physical date column (e.g.,
`[dm_order::ORDER_DATE]`), not the truncated dimension formula. `diff_months` /
`diff_quarters` / `diff_years` handle the grain internally.

**Growth % formulas** (MoM, QoQ, YoY) inline the `sum_if` expressions for both
periods and compute the ratio directly — no cross-formula references needed:
```
( sum_if ( diff_months ( [date] , today ( ) ) = 0 , [m] )
- sum_if ( diff_months ( [date] , today ( ) ) = -1 , [m] ) )
/ sum_if ( diff_months ( [date] , today ( ) ) = -1 , [m] ) * 100
```

#### Rolling Window (`range: trailing N day`)

Date-based rolling windows. ThoughtSpot's `moving_sum` / `moving_average` operate
on row counts, so this assumes one row per day (daily grain).

| MV window pattern | ThoughtSpot equivalent |
|---|---|
| `range: trailing 7 day`, `order: date_dim` | `moving_sum ( [m] , 7 , 0 , [TABLE::date_col] )` |
| `range: trailing 30 day`, `order: date_dim` | `moving_sum ( [m] , 30 , 0 , [TABLE::date_col] )` |
| `range: trailing N day`, `order: date_dim` | `moving_sum ( [m] , N , 0 , [TABLE::date_col] )` |

**`[m]` is the inner expression only** — strip the outer aggregate wrapper from `expr`.
`SUM(a * b)` → `[TABLE::a] * [TABLE::b]`.

**`[TABLE::date_col]` must be the physical date column** (`[TABLE::transaction_date]`),
not the formula dimension name. ThoughtSpot's `moving_sum` sort argument requires a
`TABLE::column` reference — formula references fail with "Search did not find" errors.
Look up the `order:` dimension's `expr` to find the underlying physical column.

If the measure uses `AVG` instead of `SUM`, use `moving_average` instead of `moving_sum`.

#### Cumulative

| MV window pattern | ThoughtSpot equivalent |
|---|---|
| `range: cumulative` | `cumulative_sum ( [m] , [date] )` |

#### Leading Window (`range: leading N unit`) — PENDING LIVE VERIFICATION

`range: leading <N> <unit>` is the look-ahead counterpart to `trailing` (both
documented in the current YAML reference). No live round-trip has verified the
ThoughtSpot equivalent. Do not ship a translation without one — log these
measures in the Unmapped Report and flag for manual review.

| MV window pattern | Candidate ThoughtSpot formula | Status |
|---|---|---|
| `range: leading 7 day`, `order: date_dim` | `moving_sum ( [m] , 0 , 7 , [TABLE::date_col] )` (look_ahead=7, window_size=0) | PENDING — see BL-032 |

#### All-Partition Window (`range: all`) — PENDING LIVE VERIFICATION

`range: all` spans the entire partition, unbounded in both directions — not a
bounded rolling window. No verified ThoughtSpot equivalent exists yet;
partition-wide `group_aggregate(...)` (the same LOD mechanism used for
`AGG() OVER (PARTITION BY ...)` dimensions — see
[ts-databricks-formula-translation.md](ts-databricks-formula-translation.md#level-of-detail-lod-functions-verified-2026-05-25))
is the leading candidate but is untested against this specific construct. Log
in the Unmapped Report until verified — see BL-032.

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
  Strip the outer aggregate: `moving_sum([col], N, 0, [date])`.

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
