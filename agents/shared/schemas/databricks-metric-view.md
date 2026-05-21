# Databricks Metric View Schema

Reference for Databricks Unity Catalog Metric Views. Metric Views define reusable
semantic layers with dimensions, measures, and filters using YAML embedded in SQL DDL.

**Preview channel required:** Metric Views are a Preview feature. The SQL warehouse
must be on the Preview channel — Current channel warehouses return `PARSE_SYNTAX_ERROR`.

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

## Version 0.1 — Single Source

All production Metric Views observed to date use this format. Single source table,
flat list of dimensions and measures, optional global filter.

### Schema

```yaml
version: 0.1                        # Required. Currently always "0.1" for single-source.

source: catalog.schema.table_name   # Required. Fully qualified source table name.

filter: <sql_boolean_expression>    # Optional. Global WHERE clause applied to all queries.
                                    # Uses column names from the source table directly.

dimensions:                         # Optional (but a MV with no dimensions or measures is useless).
  - name: <display_name>            # Required. Human-readable name (can contain spaces).
    expr: <sql_expression>          # Required. SQL expression using source table columns.
                                    # Can be a direct column reference or a computed expression.

measures:                           # Optional.
  - name: <display_name>            # Required. Human-readable name.
    expr: <sql_aggregate_expression> # Required. Must include the aggregate function
                                    # (SUM, COUNT, AVG, etc.) — unlike Snowflake SVs where
                                    # aggregation is separate from the column reference.
```

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
- No `description`, `synonyms`, `primary_key`, or `foreign_key` fields
- Column names in `expr` reference the source table's columns directly (no table alias prefix)
- Subqueries are allowed in measure expressions (e.g., `COUNT(DISTINCT x) / (SELECT COUNT(DISTINCT x) FROM table)`)

---

## Version 1.1 — Multi-Source (from documentation)

Multi-source Metric Views support joins across tables. This format exists in
Databricks documentation but has not been observed in live production environments.

### Schema

```yaml
version: 1.1                        # Required. "1.1" for multi-source.

entities:                            # Required. List of source tables.
  - name: <alias>                    # Required. Alias used in expr references.
    db_connection: <catalog.schema.table>  # Required. Fully qualified table name.
    type: <primary|foreign>          # Optional. Relationship role.
    primary_key:                     # Optional. Primary key columns for join target.
      - <column_name>
    foreign_key:                     # Optional. References another entity's primary key.
      entity: <other_entity_name>
      column: <column_name>

filter: <sql_boolean_expression>    # Optional. Uses entity_alias.column syntax.

dimensions:
  - name: <display_name>
    expr: <entity_alias>.<column>   # References use entity alias prefix.
    description: <text>             # Optional (v1.1 adds description support).

measures:
  - name: <display_name>
    expr: <sql_aggregate_expression>
    description: <text>             # Optional.
```

### Differences from v0.1

| Aspect | v0.1 | v1.1 |
|---|---|---|
| Source | `source:` (single FQN) | `entities:` (list of tables with aliases) |
| Column references | Direct column name | `entity_alias.column` |
| Joins | Not supported | `primary_key` + `foreign_key` on entities |
| Per-field descriptions | Not supported | `description:` on dimensions/measures |
| Production usage | All 13 observed MVs | Not observed in live environments |

---

## Comparison with Snowflake Semantic Views

| Feature | Snowflake SV | Databricks MV |
|---|---|---|
| Format | SQL DDL (`CREATE SEMANTIC VIEW`) or YAML via `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` | `CREATE VIEW ... WITH METRICS LANGUAGE YAML AS $$ ... $$` |
| Retrieval | `GET_DDL('SEMANTIC_VIEW', ...)` | `DESCRIBE TABLE EXTENDED` → `View Text` row |
| Discovery | `SHOW SEMANTIC VIEWS IN SCHEMA` | `information_schema.tables WHERE table_type='METRIC_VIEW'` |
| Multi-table | `tables()` + `relationships()` | `entities` + `primary_key`/`foreign_key` (v1.1) |
| Dimensions | Nested under each table | Flat list (v0.1) or with entity alias prefix (v1.1) |
| Metrics/Measures | `metrics()` clause — aggregation in expression | `measures:` — aggregation embedded in `expr` |
| Time dimensions | Separate `time_dimensions` section | No distinction — dates are regular dimensions |
| Synonyms | `with synonyms=(...)` | Not supported |
| Per-column comments | `comment='...'` | Not in v0.1; `description:` in v1.1 |
| Global filter | Not a concept | `filter:` block |
| CA extension | `with extension (CA='...')` | Not applicable |
| Preview required | No | Yes — Preview channel on SQL warehouse |

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
