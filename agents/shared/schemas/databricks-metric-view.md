<!-- currency: databricks — 2026-06 (verified against GA Metric Views docs) -->

# Databricks Metric View Schema

Reference for Databricks Unity Catalog Metric Views. Metric Views define reusable
semantic layers with dimensions, measures, and filters using YAML embedded in SQL DDL.

**Generally available (verified 2026-06-17).** Unity Catalog Business Semantics (which
includes Metric Views) went **GA on 2026-04-02**. The earlier "Preview channel required"
instruction is **obsolete** — do **not** flip warehouses to the Preview channel. Current
requirement: a SQL warehouse running **Databricks Runtime 17.3 or above** plus `CAN USE`
permission. (A `PARSE_SYNTAX_ERROR` on a GA-era runtime is no longer attributable to the
warehouse channel.) Sources: Databricks "Redefining the Semantics Data Layer" (2026-04) and
the [create/edit](https://docs.databricks.com/aws/en/business-semantics/metric-views/create-edit)
+ [YAML reference](https://docs.databricks.com/aws/en/business-semantics/metric-views/yaml-reference) docs.

---

## DDL Syntax

### Create

```sql
CREATE OR REPLACE VIEW {catalog}.{schema}.{view_name}
WITH METRICS LANGUAGE YAML AS $$
version: 0.1
source: {catalog}.{schema}.{table_name}
...
$$
```

**Not** `CREATE METRIC VIEW` — that syntax does not exist.

### Describe (retrieve definition)

```sql
DESCRIBE TABLE EXTENDED {catalog}.{schema}.{view_name}
```

The YAML definition is in the `View Text` row of the output. Parse the result set,
find the row where `col_name = 'View Text'`, and extract the `data_type` column value.

Additional metadata rows: `Type` = `METRIC_VIEW`, `Language` = `YAML`,
`Table Properties` contains `metric_view.raw_yml` with the raw YAML.

### Discover (list Metric Views)

```sql
SELECT table_catalog, table_schema, table_name
FROM system.information_schema.tables
WHERE table_type = 'METRIC_VIEW'
  AND table_catalog = '{catalog}'
```

There is no `SHOW METRIC VIEWS` command.

### Drop

```sql
DROP VIEW {catalog}.{schema}.{view_name}
```

---

## Version 0.1 — Single Source (legacy)

> **Legacy spec version (note added 2026-06-17).** The current GA YAML reference documents
> **version 1.1** only, and the `version` field **defaults to 1.1**; v0.1 is no longer
> surfaced in the product docs. Treat this section as "may be encountered on older Metric
> Views" — the from-databricks parser must still read it, but **emit v1.1 for all
> conversions**. Newer GA constructs (top-level `materialization:`, `fields:` as an alias
> for `dimensions:`) are tracked in **BL-032**.

Single source table, flat list of dimensions and measures, optional global filter.
Column metadata is limited to `name`, `expr`, and `window` — no `display_name`,
`comment`, or `synonyms`. Use v1.1 for rich column metadata even on single-source MVs.

### Schema

```yaml
version: 0.1                        # Required. "0.1" for single-source.

source: catalog.schema.table_name   # Required. Fully qualified source table name.

filter: <sql_boolean_expression>    # Optional. Global WHERE clause applied to all queries.
                                    # Uses column names from the source table directly.

dimensions:                         # Optional (but a MV with no dimensions or measures is useless).
  - name: <identifier>              # Required. Only 3 fields allowed: name, expr, window.
    expr: <sql_expression>          # Required. SQL expression using source table columns.

measures:                           # Optional.
  - name: <identifier>              # Required. Only 3 fields allowed: name, expr, window.
    expr: <sql_aggregate_expression> # Required. Must include the aggregate function
                                    # (SUM, COUNT, AVG, etc.).
    window:                         # Optional. Semi-additive window (see Window section).
      - order: <dimension_name>
        range: current
        semiadditive: last           # REQUIRED when window is present.
```

**v0.1 Column limitations (verified 2026-05-25):**
- Only 3 properties per column: `name`, `expr`, `window`
- Adding `display_name`, `comment`, or `synonyms` fails with `Unrecognized field`
- **Recommendation:** Use v1.1 even for single-source MVs to get rich metadata

### Verified Example

From `demo_qsr.prayansh.ecommerce_transactions_basic_sales_metrics_view` on TS_WS
workspace (retrieved 2026-05-21):

```yaml
version: 0.1

source: demo_qsr.prayansh.ecommerce_transactions
filter: NOT is_return AND transaction_status = 'Completed'

dimensions:
  - name: Transaction Date
    expr: date_trunc('day', transaction_date)

  - name: Product Category
    expr: product_category

  - name: Region
    expr: region

  - name: Customer Segment
    expr: customer_segment

measures:
  - name: Total Sales
    expr: SUM(product_price * quantity * (1 - discount_percent))

  - name: Total Transactions
    expr: COUNT(DISTINCT transaction_id)

  - name: Average Order Value
    expr: SUM(product_price * quantity * (1 - discount_percent)) / COUNT(DISTINCT transaction_id)

  - name: Total Discount Amount
    expr: SUM(product_price * quantity * discount_percent)

  - name: Unique Customers
    expr: COUNT(DISTINCT customer_id)
```

### DESCRIBE TABLE EXTENDED Output Format

The output is a result set with columns `[col_name, data_type, comment, metadata]`:

| col_name | data_type | Notes |
|---|---|---|
| `Transaction Date` | `timestamp` | Dimension columns |
| `Product Category` | `string` | |
| `Total Sales` | `double measure` | Measure columns have ` measure` suffix on data_type |
| `Total Transactions` | `bigint measure` | |
| *(empty row)* | | Separator |
| `# Detailed Table Information` | | Section header |
| `Type` | `METRIC_VIEW` | Confirms this is a Metric View |
| `View Text` | *YAML string* | **The full YAML definition** |
| `Language` | `YAML` | |
| `Table Properties` | *key=value pairs* | Contains `metric_view.raw_yml`, `metric_view.from.name`, etc. |

### Key observations from v0.1

- `expr` in measures always includes the aggregate function (e.g., `SUM(col)`)
- `expr` in dimensions can be computed (e.g., `date_trunc('day', col)`, `CASE WHEN...`)
- `filter` applies globally — there is no per-dimension/measure filter
- **Only 3 fields per column:** `name`, `expr`, `window` — any other field is rejected
- No `display_name`, `comment`, `synonyms`, `description`, `primary_key`, or `foreign_key` fields
- Column names in `expr` reference the source table's columns directly (no table alias prefix)
- Subqueries are allowed in measure expressions (e.g., `COUNT(DISTINCT x) / (SELECT COUNT(DISTINCT x) FROM table)`)

---

## Version 1.1 — Rich Metadata (verified 2026-05-25)

v1.1 adds rich column metadata (`display_name`, `comment`, `synonyms`) and
multi-source join support. **Use v1.1 even for single-source MVs** — it supports
`source:` (single FQN) just like v0.1, but with full column metadata.

### Schema — Single Source (v1.1)

```yaml
version: 1.1                        # Required. "1.1" for rich metadata.
comment: >-                         # Optional. View-level description.
  Human-readable description of the Metric View.

source: catalog.schema.table_name   # Single-source mode — same as v0.1.

filter: <sql_boolean_expression>    # Optional. Global WHERE clause.

dimensions:
  - name: <identifier>              # Required. Machine-readable identifier.
    expr: <sql_expression>          # Required. SQL expression or column reference.
    display_name: '<label>'         # Optional. Human-readable label.
    comment: '<description>'        # Optional. Column-level description.
    synonyms: ['alias1', 'alias2'] # Optional. Alternative search terms.

measures:
  - name: <identifier>
    expr: <sql_aggregate_expression> # Required. Aggregate function embedded.
    display_name: '<label>'
    comment: '<description>'
    synonyms: ['alias1', 'alias2']
    window:                          # Optional. Semi-additive window.
      - order: <dimension_name>
        range: current
        semiadditive: last           # REQUIRED when window is present.
```

### Schema — Multi-Source with Joins (v1.1)

v1.1 supports star-schema joins via a `joins:` field on the `source`. Joins can be
**nested** to express multi-hop relationships (e.g., fact → order → customer).

```yaml
version: 1.1
comment: >-
  Multi-source Metric View description.

source: catalog.schema.fact_table   # Required. The primary fact table.

joins:                              # Optional. Dimension table joins.
  - name: <alias>                   # Required. Alias used in expr references.
    source: <catalog.schema.dim>    # Required. Fully qualified dimension table.
    "on": source.<fk> = <alias>.<pk>  # Required. Join condition.
    rely:                           # Optional. Cardinality hint for query optimizer.
      at_most_one_match: true       # Declares many-to-one relationship.
    joins:                          # Optional. NESTED sub-joins under this join.
      - name: <sub_alias>
        source: <catalog.schema.sub_dim>
        "on": <alias>.<fk> = <sub_alias>.<pk>
        rely:
          at_most_one_match: true

filter: <sql_boolean_expression>    # Optional. Uses alias.column or source.column syntax.

dimensions:
  - name: <identifier>
    expr: <alias>.<column>          # References use join alias prefix (dot-path for nested).
    display_name: '<label>'
    comment: '<description>'
    synonyms: ['alias1', 'alias2']

measures:
  - name: <identifier>
    expr: <sql_aggregate_expression>
    display_name: '<label>'
    comment: '<description>'
    synonyms: ['alias1', 'alias2']
    format:                         # Optional. Display formatting.
      type: <currency|percentage>
      currency_code: <ISO_code>     # For currency type.
      decimal_places:
        type: exact
        places: <int>
    window:
      - order: <dimension_name>
        range: <current|cumulative>
        semiadditive: <last|first>  # REQUIRED when window is present.
        offset: <-N period>         # Optional. Period offset for comparisons (e.g., "-1 month").
```

### Join Structure (verified 2026-05-26)

Joins use **nested hierarchy**, not sibling-level references. Each join's `on` clause
references its **parent** (either `source` for top-level joins, or the parent join's
alias for nested joins):

```yaml
joins:
  - name: orders                                # top-level: references source
    source: catalog.schema.dm_order
    "on": source.ORDER_ID = orders.ORDER_ID
    joins:
      - name: customers                         # nested: references parent (orders)
        source: catalog.schema.dm_customer
        "on": orders.CUSTOMER_ID = customers.CUSTOMER_ID
      - name: employees                         # nested: references parent (orders)
        source: catalog.schema.dm_employee
        "on": orders.EMPLOYEE_ID = employees.EMPLOYEE_ID
  - name: products                              # top-level: references source
    source: catalog.schema.dm_product
    "on": source.PRODUCT_ID = products.PRODUCT_ID
    joins:
      - name: category                          # nested: references parent (products)
        source: catalog.schema.dm_category
        "on": products.CATEGORY_ID = category.CATEGORY_ID
```

**Column references use dot-path through the join hierarchy:**
- `source.COL` — fact table column
- `orders.COL` — first-level join column
- `orders.customers.COL` — nested join column (through orders)
- `products.category.COL` — nested join column (through products)

**`rely: { at_most_one_match: true }`** declares a many-to-one cardinality hint,
telling the optimizer each fact row matches at most one dimension row.

**Sibling-level references do NOT work.** A join's `on` clause cannot reference
another join at the same level — only `source` or the parent join alias. Nesting
is the mechanism for multi-hop relationships.

### Format Field (verified 2026-05-26)

Measures support a `format:` field for display formatting:

```yaml
measures:
  - name: revenue
    expr: SUM(LINE_TOTAL)
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
  - name: growth_pct
    expr: ...
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 1
```

| Format type | Fields | Notes |
|---|---|---|
| `currency` | `currency_code`, `decimal_places` | ISO 4217 code (USD, EUR, etc.) |
| `percentage` | `decimal_places` | Value is multiplied by 100 for display |

### Window with Offset — Period-over-Period (verified 2026-05-26)

The `window:` field supports an `offset` property for period comparisons:

```yaml
measures:
  - name: monthly_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_month
        semiadditive: last
        range: current
  - name: prior_month_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_month
        semiadditive: last
        range: current
        offset: -1 month           # one period back
  - name: prior_year_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_month
        semiadditive: last
        range: current
        offset: -1 year            # same month, prior year
  - name: cumulative_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_date
        semiadditive: last
        range: cumulative           # running total
```

| `range` value | Meaning |
|---|---|
| `current` | Current period only |
| `cumulative` | Running total from start to current period |

`offset` uses `<-N period>` syntax where period is `month`, `year`, `day`, etc.
Cross-measure references can then compute growth rates:

```yaml
  - name: mom_growth_pct
    expr: (MEASURE(monthly_revenue) - MEASURE(prior_month_revenue)) / MEASURE(prior_month_revenue) * 100
```

### LOD Patterns (verified 2026-05-25)

Level of Detail calculations use **dimension window functions**, not measure
`AGGREGATE OVER` (which causes `PARSE_SYNTAX_ERROR`).

```yaml
# LOD as a DIMENSION with window function
dimensions:
  - name: category_quantity
    expr: SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)
    display_name: 'Category Quantity'
    comment: 'Total units sold at the category grain, independent of query GROUP BY.'

# Cross-measure ratio referencing the LOD dimension
measures:
  - name: quantity
    expr: SUM(QUANTITY)
  - name: category_contribution_ratio
    expr: MEASURE(quantity) / ANY_VALUE(category_quantity)
    comment: 'Product share of category total units.'
```

**Rules:**
- LOD calculations → `dimensions[]` with `AGG() OVER (PARTITION BY ...)` in `expr`
- Cross-measure references → `MEASURE(measure_name)` in measure `expr`
- Referencing a dimension from a measure → `ANY_VALUE(dimension_name)`
- `AGGREGATE OVER` in YAML `expr` is NOT supported (causes `PARSE_SYNTAX_ERROR`)

### Semi-Additive Measures (verified 2026-05-25)

The `window` field on a measure requires `semiadditive` as a property. Using
`window` without `semiadditive` fails with `Missing required creator property 'semiadditive'`.

```yaml
measures:
  - name: inventory_balance
    expr: SUM(FILLED_INVENTORY)
    display_name: 'Inventory Balance'
    comment: 'Semi-additive snapshot measure.'
    window:
      - order: balance_date       # dimension to order by
        range: current            # current row only
        semiadditive: last        # REQUIRED — take last value
```

Valid `semiadditive` values: `last`, `first`.

### Querying Metric Views

Measures must be wrapped in the `MEASURE()` function when querying:

```sql
SELECT product_name, MEASURE(quantity), MEASURE(amount)
FROM agent_skills.dunder_mifflin.dunder_mifflin_sales_mv
GROUP BY product_name
```

Without `MEASURE()`, the query fails with `METRIC_VIEW_MISSING_MEASURE_FUNCTION`.

### Differences from v0.1

| Aspect | v0.1 | v1.1 |
|---|---|---|
| Source | `source:` only | `source:` (fact table) + optional `joins:` (dimension tables) |
| Column fields | `name`, `expr`, `window` only | + `display_name`, `comment`, `synonyms`, `format:` |
| View-level comment | Not supported | `comment:` at top level |
| Column references | Direct column name | Direct (single-source) or `alias.column` dot-path (multi-source) |
| Joins | Not supported | Nested `joins:` with `rely: { at_most_one_match: true }` — star schema support |
| LOD | Not available | Dimension window functions: `AGG() OVER (PARTITION BY ...)` |
| Cross-measure refs | Not available | `MEASURE(name)` in measure `expr` |
| Semi-additive | `window` with `semiadditive` | Same — `semiadditive` required in both versions |

### Verified v1.1 Example — Dunder Mifflin Sales MV (joined star schema)

From `agent_skills.dunder_mifflin.dunder_mifflin_sales_mv` (verified 2026-05-26).
Demonstrates nested joins, dot-path column refs, LOD, cross-measure, format, and
window with offset:

```yaml
version: 1.1
source: agent_skills.dunder_mifflin.dm_order_detail

joins:
  - name: orders
    source: agent_skills.dunder_mifflin.dm_order
    "on": source.DM_ORDER_DETAIL_ORDER_ID = orders.ORDER_ID
    joins:
      - name: customers
        source: agent_skills.dunder_mifflin.dm_customer
        "on": orders.DM_ORDER_CUSTOMER_ID = customers.CUSTOMER_ID
        rely: { at_most_one_match: true }
      - name: employees
        source: agent_skills.dunder_mifflin.dm_employee
        "on": orders.DM_ORDER_EMPLOYEE_ID = employees.EMPLOYEE_ID
        rely: { at_most_one_match: true }
      - name: dates
        source: agent_skills.dunder_mifflin.dm_date_dim
        "on": orders.DM_ORDER_ORDER_DATE = dates.DATE_VALUE
        rely: { at_most_one_match: true }
    rely: { at_most_one_match: true }
  - name: products
    source: agent_skills.dunder_mifflin.dm_product
    "on": source.DM_ORDER_DETAIL_PRODUCT_ID = products.PRODUCT_ID
    joins:
      - name: category
        source: agent_skills.dunder_mifflin.dm_category
        "on": products.DM_PRODUCT_CATEGORY_ID = category.CATEGORY_ID
        rely: { at_most_one_match: true }
    rely: { at_most_one_match: true }

comment: >-
  Dunder Mifflin Sales metrics built on normalized star schema — revenue,
  quantity, pricing, and period-over-period analysis.

dimensions:
  - name: order_date
    expr: orders.DM_ORDER_ORDER_DATE
    display_name: Order Date
    comment: Date the order was placed.
    synonyms: ['order placed', 'purchase date']
  - name: product_category
    expr: products.category.CATEGORY_NAME       # dot-path through nested join
    display_name: Product Category
    synonyms: ['category', 'product line']
  - name: customer_name
    expr: orders.customers.COMPANY_NAME         # dot-path through nested join
    display_name: Customer Name
    synonyms: ['customer', 'client', 'buyer']
  - name: employee_name
    expr: "CONCAT(orders.employees.LAST_NAME, ', ', orders.employees.FIRST_NAME)"
    display_name: Employee
    synonyms: ['sales rep', 'rep', 'salesperson']
  - name: category_total_revenue
    expr: SUM(source.LINE_TOTAL) OVER (PARTITION BY products.category.CATEGORY_NAME)
    display_name: Category Total Revenue
    comment: "Fixed LOD: total revenue at category grain."

measures:
  - name: revenue
    expr: SUM(source.LINE_TOTAL)
    display_name: Revenue
    format: { type: currency, currency_code: USD, decimal_places: { type: exact, places: 2 } }
    synonyms: ['sales', 'total sales', 'amount']
  - name: order_count
    expr: COUNT(DISTINCT orders.ORDER_ID)
    display_name: Order Count
    synonyms: ['number of orders']
  - name: category_contribution_pct
    expr: MEASURE(revenue) / ANY_VALUE(category_total_revenue) * 100
    display_name: Category Contribution %
    format: { type: percentage, decimal_places: { type: exact, places: 1 } }
  - name: monthly_revenue
    expr: SUM(source.LINE_TOTAL)
    window: [{ order: order_month, semiadditive: last, range: current }]
  - name: prior_month_revenue
    expr: SUM(source.LINE_TOTAL)
    window: [{ order: order_month, semiadditive: last, range: current, offset: -1 month }]
  - name: mom_growth_pct
    expr: (MEASURE(monthly_revenue) - MEASURE(prior_month_revenue)) / MEASURE(prior_month_revenue) * 100
    display_name: MoM Growth %
    format: { type: percentage, decimal_places: { type: exact, places: 1 } }
```

### Verified v1.1 Example — Dunder Mifflin Inventory MV

From `agent_skills.dunder_mifflin.dunder_mifflin_inventory_mv` (created 2026-05-25):

```yaml
version: 1.1
comment: >-
  Dunder Mifflin Inventory analysis — semi-additive stock levels.
source: agent_skills.dunder_mifflin.dm_inventory_flat

dimensions:
  - name: balance_date
    expr: DM_INVENTORY_BALANCE_DATE
    display_name: 'Balance Date'
    comment: 'Date the inventory balance was snapshotted.'

  - name: product_name
    expr: PRODUCT_NAME
    display_name: 'Product Name'
    synonyms: ['product', 'item']

measures:
  - name: inventory_balance
    expr: SUM(FILLED_INVENTORY)
    display_name: 'Inventory Balance'
    comment: 'Semi-additive snapshot measure.'
    synonyms: ['stock', 'stock on hand', 'current inventory']
    window:
      - order: balance_date
        range: current
        semiadditive: last
```

---

## Comparison with Snowflake Semantic Views

| Feature | Snowflake SV | Databricks MV |
|---|---|---|
| Format | SQL DDL (`CREATE SEMANTIC VIEW`) or YAML via `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` | `CREATE VIEW ... WITH METRICS LANGUAGE YAML AS $$ ... $$` |
| Retrieval | `GET_DDL('SEMANTIC_VIEW', ...)` | `DESCRIBE TABLE EXTENDED` → `View Text` row |
| Discovery | `SHOW SEMANTIC VIEWS IN SCHEMA` | `information_schema.tables WHERE table_type='METRIC_VIEW'` |
| Multi-table | `tables()` + `relationships()` | `joins:` with nested hierarchy (v1.1) — star schema via nested sub-joins |
| Dimensions | Nested under each table | Flat list — direct column or `AGG() OVER (PARTITION BY)` for LOD |
| Metrics/Measures | `metrics()` clause — aggregation in expression | `measures:` — aggregation embedded in `expr`; `MEASURE()` for cross-refs |
| Time dimensions | Separate `time_dimensions` section | No distinction — dates are regular dimensions |
| Synonyms | `with synonyms=(...)` | v1.1: `synonyms:` list; v0.1: not supported |
| Per-column comments | `comment='...'` | v1.1: `comment:` and `display_name:`; v0.1: not supported |
| LOD | Via SQL expressions | Dimension window functions: `SUM(x) OVER (PARTITION BY dim)` |
| Semi-additive | `last_value()` in SQL | `window: [{order: dim, range: current, semiadditive: last}]` |
| Cross-measure refs | Via SQL expressions | `MEASURE(measure_name)` + `ANY_VALUE(dim_name)` |
| Global filter | Not a concept | `filter:` block |
| CA extension | `with extension (CA='...')` | Not applicable |
| Preview required | No | No — GA since 2026-04-02 |

---

## SQL Execution via Databricks CLI

All SQL operations use the Statement Execution API via the Databricks CLI:

```bash
databricks api post /api/2.0/sql/statements \
  --profile {dbx_profile} \
  --json '{
    "warehouse_id": "{warehouse_id}",
    "statement": "{sql_statement}",
    "wait_timeout": "50s"
  }'
```

The `warehouse_id` is extracted from the profile's `sql_warehouse_http_path`:
```
/sql/1.0/warehouses/c6ed539a60038b93  →  c6ed539a60038b93
```

Response format:
```json
{
  "status": {"state": "SUCCEEDED"},
  "manifest": {"schema": {"columns": [...]}},
  "result": {"data_array": [[...], ...]}
}
```

For `PENDING` state, poll the statement ID:
```bash
databricks api get /api/2.0/sql/statements/{statement_id} --profile {dbx_profile}
```
