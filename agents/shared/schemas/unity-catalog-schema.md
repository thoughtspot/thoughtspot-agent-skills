# Unity Catalog Metric View YAML Schema

Full schema reference for Databricks Unity Catalog Metric Views. Use during Step 11
(Validate) to verify the generated YAML is structurally correct before executing the
`CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML AS $$...$$` DDL.

---

## Complete Schema

```yaml
version: "1.1"                  # Required. Always "1.1".

comment: string                 # Optional. Human-facing description of the metric view.

source: catalog.schema.table    # Required. Fully-qualified fact/primary table name.
                                # Can also be an inline SELECT statement for complex sources.

filter: string                  # Optional. SQL boolean expression applied to ALL queries
                                # against this metric view (like a permanent WHERE clause).
                                # Example: "o_orderdate >= '2020-01-01'"

joins:                          # Optional. Star/snowflake schema join definitions.
  - name: string                # Required. Alias used to reference this table in expr fields.
                                # Must be unique within the metric view.
    source: catalog.schema.tbl  # Required. Fully-qualified table to join.
    on: string                  # Required. SQL join condition. See Join `on` Clause Syntax below.
    joins:                      # Optional. Nested joins (snowflake schema / multi-hop).
      - name: string
        source: catalog.schema.tbl
        on: string

dimensions:                     # Conditional. At least one of dimensions or measures required.
  - name: string                # Required. Identifier. Spaces allowed but require backtick-quoting
                                # in queries. Prefer snake_case names for clean SQL usage.
    expr: string                # Required. SQL expression. Source cols: bare name. Joined cols: join_alias.col.
    comment: string             # Optional. Human-facing description.
    display_name: string        # Optional. Override label shown in UIs and Genie.
    synonyms:                   # Optional. Alternate names for natural language queries.
      - string
    format:                     # Optional. Display formatting hint.
      type: string              # number | currency | percentage

measures:                       # Conditional. At least one of dimensions or measures required.
  - name: string                # Required. Identifier (same naming rules as dimensions).
    expr: string                # Required. Aggregate SQL expression. See Measure expr Patterns below.
    comment: string             # Optional.
    display_name: string        # Optional.
    synonyms:                   # Optional.
      - string
    format:                     # Optional.
      type: string              # number | currency | percentage
      currency_code: string     # e.g. USD — only for type: currency
      decimal_places:           # Optional.
        type: string            # exact | auto
        places: integer         # only for type: exact
      abbreviation: string      # compact — shorten large numbers (1M, 1B etc.)
    window:                     # Optional. For time-series and semi-additive measures.
      - order: string           # dimension name (must reference a dimension in this metric view)
        range: string           # trailing N unit | cumulative | current | leading N unit | all
                                # units: row | day | week | month | quarter | year
        semiadditive: string    # Optional. first | last  (how to aggregate across order dimension)

materialization:                # Optional. Query acceleration configuration.
  strategy: string              # refresh | auto
```

---

## Join `on` Clause Syntax

The `on:` field is a SQL boolean expression joining the parent context to the current join.

**Top-level join** — parent is the main `source` table, referenced by the literal keyword `source`:

```yaml
source: main.tpch.orders

joins:
  - name: customer
    source: main.tpch.customer
    on: source.o_custkey = customer.c_custkey
```

**Nested join** — parent is the enclosing join, referenced by that join's `name`:

```yaml
joins:
  - name: customer
    source: main.tpch.customer
    on: source.o_custkey = customer.c_custkey
    joins:
      - name: nation
        source: main.tpch.nation
        on: customer.c_nationkey = nation.n_nationkey
```

**Multi-column join** — use `AND`:

```yaml
on: source.dept_id = dept.dept_id AND source.region_id = dept.region_id
```

---

## `expr` Reference Syntax

In `dimensions` and `measures` `expr` fields:

| Column location | `expr` syntax | Example |
|---|---|---|
| Main `source` table | bare column name | `revenue` |
| Top-level join | `join_name.column` | `customer.c_name` |
| Nested join | `join_name.column` (flat namespace) | `nation.n_name` |
| Any level with reserved word | backtick-quote column only | `` `date` `` or `` customer.`name` `` |

**Key rule:** Join `name` values form a **flat namespace** for `expr` references — use
`nation.n_name` directly, not `customer.nation.n_name`, even when `nation` is nested
inside `customer` in the `joins:` hierarchy.

---

## Measure `expr` Patterns

**Simple aggregate:**
```yaml
expr: SUM(revenue)
expr: COUNT(*)
expr: COUNT(DISTINCT customer_id)
expr: AVG(order_value)
```

**Filtered aggregate** — `FILTER (WHERE ...)` applies a conditional to only this measure:
```yaml
expr: SUM(revenue) FILTER (WHERE order_status = 'complete')
expr: COUNT(*) FILTER (WHERE channel = 'online')
```

**Composed measure** — `MEASURE()` references another named measure in the same view:
```yaml
expr: MEASURE(total_revenue) / NULLIF(MEASURE(order_count), 0)
expr: try_divide(MEASURE(total_revenue), MEASURE(order_count))
```
`MEASURE()` arguments must reference measure `name` values defined in the same metric view.

**Window / semi-additive measure** — time-series or snapshot semantics via `window:` config:
```yaml
measures:
  - name: cumulative_revenue
    expr: SUM(revenue)
    window:
      - order: order_month     # a dimension name in this view
        range: cumulative

  - name: balance_end_of_month
    expr: SUM(balance_amount)
    window:
      - order: snapshot_month  # the time dimension driving the snapshot
        range: current
        semiadditive: last     # take the last value when aggregating across time
```

---

## Identifier Quoting in Databricks SQL

Databricks uses **backticks** for quoted identifiers, not double quotes.

| Situation | Example |
|---|---|
| Reserved word column name in `expr` | `` `date` ``, `` `order` ``, `` `name` `` |
| Column name with spaces | `` `order date` `` |
| Catalog/schema/table in DDL | `` `catalog`.`schema`.`view_name` `` |
| Normal identifier (no reserved word, no spaces) | `revenue`, `customer_id` — no quoting needed |

Common Databricks SQL reserved words that appear frequently as column names:
`date`, `time`, `order`, `group`, `schema`, `table`, `value`, `name`, `type`,
`key`, `id`, `from`, `to`, `end`, `start`

In YAML `expr` values, use backtick quoting inline:
```yaml
expr: "`date`"               # source table reserved word column
expr: "customer.`name`"      # joined table reserved word column
```

---

## Validation Checklist

Run all checks before executing the CREATE VIEW DDL:

| Rule | Check |
|---|---|
| `version: "1.1"` present | Top-level key exists with value `"1.1"` |
| `source:` present and fully-qualified | `catalog.schema.table` format |
| At least one of `dimensions` or `measures` | Both cannot be absent |
| Unique field names | No two `name` values in `dimensions` + `measures` are identical |
| Valid identifiers | `name` values should not be empty strings |
| Join names unique | No two entries in `joins:` at any level share a `name` |
| Join `on` references valid names | Top-level `on:` uses `source`; nested `on:` uses parent join's `name` |
| Joined table column refs | `expr` uses `join_name.col` for joined tables; `name` matches a `joins:` entry |
| `MEASURE()` references valid | All measure names inside `MEASURE()` are defined in this metric view |
| `window.order` references valid | Value is the `name` of a dimension defined in this metric view |
| Reserved words backtick-quoted in expr | Column names that are SQL reserved words wrapped in backticks |
| No unsupported fields | UC Metric Views do not support: `tables[]`, `relationships[]`, `time_dimensions[]`, `primary_key` |
| No `null` or placeholder exprs | Every `expr` must be valid SQL; no TODO comments |

---

## Example Structure

```yaml
version: "1.1"
comment: "Order analytics with customer and nation dimensions"

source: main.tpch.orders

joins:
  - name: customer
    source: main.tpch.customer
    on: source.o_custkey = customer.c_custkey
    joins:
      - name: nation
        source: main.tpch.nation
        on: customer.c_nationkey = nation.n_nationkey

dimensions:
  - name: order_month
    expr: DATE_TRUNC('MONTH', o_orderdate)
    display_name: "Month of Order"
    synonyms:
      - order_date
      - month
  - name: order_status
    expr: o_orderstatus
    display_name: "Order Status"
  - name: customer_name
    expr: customer.c_name
    display_name: "Customer"
  - name: nation_name
    expr: nation.n_name
    display_name: "Country"

measures:
  - name: order_count
    expr: COUNT(*)
    display_name: "# Orders"
    format:
      type: number
      decimal_places:
        type: exact
        places: 0
  - name: total_revenue
    expr: SUM(o_totalprice)
    display_name: "Revenue"
    format:
      type: currency
      currency_code: USD
  - name: avg_order_value
    expr: try_divide(MEASURE(total_revenue), MEASURE(order_count))
    display_name: "Average Order Value"
    format:
      type: currency
      currency_code: USD
  - name: open_order_revenue
    expr: SUM(o_totalprice) FILTER (WHERE o_orderstatus = 'O')
    display_name: "Revenue — Open Orders"
  - name: cumulative_revenue
    expr: SUM(o_totalprice)
    display_name: "Cumulative Revenue"
    window:
      - order: order_month
        range: cumulative
```

---

## Execution DDL

```sql
-- Create the metric view
CREATE OR REPLACE VIEW `{catalog}`.`{schema}`.`{view_name}`
WITH METRICS
LANGUAGE YAML
AS $$
{full yaml content here}
$$;
```

**Notes:**
- Backtick-quote catalog, schema, and view name if they contain reserved words or spaces
- `WITH METRICS LANGUAGE YAML` is the required DDL clause
- The `$$` dollar-quoting allows YAML to contain backticks and single quotes safely
- No dry-run mode exists — errors are returned as DDL exceptions at CREATE time
- To drop and recreate: `DROP VIEW IF EXISTS \`{catalog}\`.\`{schema}\`.\`{view_name}\`;`

**Verify the view was created:**
```sql
-- Check the view exists and see its definition
SHOW CREATE TABLE `{catalog}`.`{schema}`.`{view_name}`;

-- Or describe it
DESCRIBE EXTENDED `{catalog}`.`{schema}`.`{view_name}`;

-- Spot-check: query a measure
SELECT MEASURE(`{first_measure_name}`)
FROM `{catalog}`.`{schema}`.`{view_name}`;
```

**Query syntax for metric views:**
```sql
SELECT
  dimension1,
  dimension2,
  MEASURE(measure_name_1),
  MEASURE(measure_name_2)
FROM `{catalog}`.`{schema}`.`{view_name}`
GROUP BY dimension1, dimension2;
-- Note: Cannot SELECT * — must list specific dimensions and wrap measures in MEASURE()
```

---

## What is NOT supported

| Snowflake concept | UC Metric View equivalent | Notes |
|---|---|---|
| `tables[]` array | n/a — use `source:` + `joins:` | UC is not table-scoped |
| `time_dimensions[]` | `dimensions[]` | Date columns are plain dimensions in UC |
| `relationships[]` | Inline `joins:` array | Joins defined in YAML, not separately |
| `primary_key:` | n/a | UC resolves joins from `on:` clause |
| `metrics` keyword | `measures` keyword | **Important: UC uses `measures`, not `metrics`** |
| `default_aggregation` | n/a — embed in `expr` | Aggregation is always explicit in expr |
| `data_type` on measures | n/a — inferred from SQL | UC infers types; do not include data_type on measures |

---

## Known Unity Catalog Metric View Limitations

### No dry-run validation

Unlike `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`, UC has no validate-only mode.
The CREATE VIEW DDL either succeeds or returns a DDL error. Always run the
Step 11 validation checklist before executing to catch structural errors early.

### Genie / AI/BI Dashboard integration

Metric views created via DDL are immediately available as data sources for Genie spaces
and AI/BI Dashboards. `display_name`, `synonyms`, and `comment` values are consumed
by Genie for natural language understanding. Keep these values informative and specific.

### Multi-fact / many-to-many patterns

UC Metric Views are designed for star and snowflake schemas. Many-to-many relationships
(bridge/junction tables) are not directly supported. If the ThoughtSpot model contains
bridge tables, document them in the Unmapped Report and advise the user to either
create a pre-aggregated view or restructure the model for UC.

### `SELECT *` not supported

Queries against metric views must explicitly list dimensions and wrap measures in
`MEASURE()`. `SELECT *` raises an error.

### Window measure ordering

The `window.order` field must reference a `name` in the same metric view's `dimensions`
array. If no date dimension is present, window measures cannot be defined.
