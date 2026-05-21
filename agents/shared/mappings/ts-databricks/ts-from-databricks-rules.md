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
- `source` — fully qualified source table name (v0.1)
- `entities` — list of source tables with aliases (v1.1)
- `dimensions` — list of dimension definitions
- `measures` — list of measure definitions
- `filter` — optional global filter expression

---

## v0.1 Parsing (Single Source)

### Source Table

`source: catalog.schema.table_name` identifies the single source table.

1. Extract `catalog`, `schema`, and `table_name` from the FQN
2. Fetch the table's columns: `DESCRIBE TABLE {source}`
3. Build a column map: `{column_name: data_type}` for reference during classification

### Dimension → ThoughtSpot Column

Each dimension entry:
```yaml
- name: Transaction Date
  expr: date_trunc('day', transaction_date)
```

**Classification decision:**

```
Is expr a direct column reference (single identifier, no functions)?
  YES → ATTRIBUTE column
        name: use the dimension `name` as the TS column display name
        column_id: use the physical column name from expr
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

### Measure → ThoughtSpot Column or Formula

Each measure entry:
```yaml
- name: Total Sales
  expr: SUM(product_price * quantity * (1 - discount_percent))
```

**Classification decision:**

```
Is expr a simple aggregate? (single AGG function wrapping a column or simple expression)
  Pattern: AGG(column_name) or AGG(DISTINCT column_name)
  
  YES → MEASURE column
        Extract the aggregate function → aggregation field
        Extract the inner column → column_id
        
  NO  → Formula MEASURE
        Complex expression (ratios, nested aggregates, subqueries)
        Create a formulas[] entry with translated expression
        Create a columns[] entry with formula_id reference
```

**Simple aggregate examples:**

| Measure `expr` | TS `aggregation` | TS column reference |
|---|---|---|
| `SUM(sales)` | `SUM` | `sales` |
| `COUNT(DISTINCT customer_id)` | `COUNT_DISTINCT` | `customer_id` |
| `AVG(tenure)` | `AVERAGE` | `tenure` |
| `MIN(price)` | `MIN` | `price` |
| `MAX(quantity)` | `MAX` | `quantity` |
| `COUNT(*)` | `COUNT` | — (use any non-null column) |

**Complex expression examples (→ formulas[]):**

| Measure `expr` | Reason |
|---|---|
| `SUM(a * b * (1 - c))` | Arithmetic inside aggregate |
| `SUM(x) / COUNT(DISTINCT y)` | Multiple aggregates / ratio |
| `COUNT(DISTINCT x) / (SELECT ...)` | Subquery |

### Filter → Model Description

The `filter:` field is a global WHERE clause. It does not map cleanly to a
ThoughtSpot column or formula. Handle it by:

1. Include it in the model's `description` field:
   `"Imported from Databricks Metric View. Filter: {filter_expression}"`
2. If the filter is a simple boolean expression translatable to a ThoughtSpot
   formula, optionally create a formula column for reference

---

## v1.1 Parsing (Multi-Source)

### Entity → Table TML

Each entity:
```yaml
entities:
  - name: sales
    db_connection: catalog.schema.fact_sales
    primary_key:
      - sale_id
  - name: stores
    db_connection: catalog.schema.dim_stores
    foreign_key:
      entity: sales
      column: store_id
```

Maps to:
- One Table TML per entity, pointing to the `db_connection` table
- The `name` field becomes the table alias in the model

### Joins from primary_key / foreign_key

`primary_key` + `foreign_key` relationships map to ThoughtSpot `joins[]`:

MV entity definition:
```yaml
- name: stores
  foreign_key:
    entity: sales
    column: store_id
```

Corresponding ThoughtSpot join:
```yaml
joins:
  - name: sales_to_stores
    source: sales
    destination: stores
    on: "[sales::store_id] = [stores::store_id]"
    type: RIGHT_OUTER
```

### Column References in v1.1

Dimensions and measures use `entity_alias.column` notation:
```yaml
dimensions:
  - name: Store Name
    expr: stores.store_name
```

Strip the entity alias prefix to get the physical column name.

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
| `CASE WHEN x THEN y ELSE z END` | `if(x, y, z)` |
| `COALESCE(a, b)` | `if(a != null, a, b)` |
| `CONCAT(a, b)` | `concat(a, b)` |

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
