# Mapping Rules Reference

ThoughtSpot → Databricks Metric View conversion tables. Consult during Steps 4–9.

---

## Column Type Classification

Apply this decision tree to every column:

```
Is formula_id set?
  YES → measures (if translatable) or OMIT (if untranslatable — see Step 9)
  NO  → Is column_type MEASURE?
          YES → measures
          NO  → dimensions
```

Unlike Snowflake SVs, Databricks Metric Views have no separate `time_dimensions`
category — date/timestamp columns go into `dimensions` alongside all other attributes.

---

## Aggregation Functions

Databricks MV embeds the aggregation in the measure `expr` — same pattern as
Snowflake SVs but with Databricks SQL syntax.

| ThoughtSpot `aggregation` | Databricks MV `expr` wrapper |
|---|---|
| `SUM` | `SUM(expr)` |
| `COUNT` | `COUNT(expr)` |
| `COUNT_DISTINCT` | `COUNT(DISTINCT expr)` |
| `AVG` / `AVERAGE` | `AVG(expr)` |
| `MIN` | `MIN(expr)` |
| `MAX` | `MAX(expr)` |
| `STD_DEVIATION` | `STDDEV(expr)` |
| `VARIANCE` | `VARIANCE(expr)` |
| *(not set on MEASURE)* | `SUM(expr)` *(default)* |

---

## Data Types

Databricks Metric Views do not have an explicit `data_type` field on dimensions
or measures. The data type is inferred from the source table column and the `expr`.

For reference when determining column classification from ThoughtSpot TML:

| Source field value | Databricks type | Classification |
|---|---|---|
| `VARCHAR`, `CHAR`, `TEXT`, `STRING` | `STRING` | dimension |
| `INT`, `INTEGER`, `BIGINT`, `SMALLINT`, `TINYINT`, `INT64` | `BIGINT`/`INT` | dimension or measure |
| `FLOAT`, `DOUBLE`, `DECIMAL`, `NUMERIC`, `REAL`, `NUMBER` | `DOUBLE`/`DECIMAL` | dimension or measure |
| `BOOLEAN`, `BOOL` | `BOOLEAN` | dimension |
| `DATE` | `DATE` | dimension |
| `DATETIME`, `DATE_TIME`, `TIMESTAMP`, `TIMESTAMP_NTZ` | `TIMESTAMP` | dimension |

---

## Name Generation Rules

Databricks MV dimension and measure names support spaces and mixed case —
no snake_case conversion needed. Use the ThoughtSpot display name directly:

```yaml
dimensions:
  - name: Sale Date          # Keep as-is from ThoughtSpot display name
    expr: sale_date
measures:
  - name: Total Revenue      # Keep as-is
    expr: SUM(revenue)
```

If the ThoughtSpot name contains characters that break YAML parsing (colons,
quotes, `#` at start of line), wrap the name in quotes:

```yaml
  - name: "Revenue: YoY Growth (%)"
    expr: ...
```

---

## Expression Rules

### v0.1 — Single Source

Column references in `expr` use the source table's physical column names directly
(no table alias prefix):

```yaml
source: catalog.schema.fact_sales

dimensions:
  - name: Store ID
    expr: store_id              # direct column reference

  - name: Sale Year
    expr: YEAR(sale_date)       # computed expression

measures:
  - name: Total Sales
    expr: SUM(sales_amount)     # aggregate wraps column name
```

### v1.1 — Multi-Source

Column references use `entity_alias.column` prefix:

```yaml
entities:
  - name: sales
    db_connection: catalog.schema.fact_sales
  - name: stores
    db_connection: catalog.schema.dim_stores

dimensions:
  - name: Store Name
    expr: stores.store_name

measures:
  - name: Total Sales
    expr: SUM(sales.sales_amount)
```

---

## Filter Generation

If the ThoughtSpot model has filter formulas that apply globally, they can be
expressed as the `filter:` field:

```yaml
filter: status = 'Active' AND NOT is_deleted
```

Only simple boolean expressions are translatable to `filter:`. Complex
ThoughtSpot filter patterns (parameterized, LOD-based) should be omitted and
logged in the Unmapped Report.

---

## Metric View YAML Templates

### v0.1 — Single Source Table

```yaml
version: 0.1

source: "catalog.schema.table_name"

dimensions:
  - name: "ThoughtSpot display name"
    expr: "physical_column_name or SQL expression"

measures:
  - name: "ThoughtSpot display name"
    expr: "AGG(physical_column_name)"
```

### Untranslatable Formula — OMIT ENTIRELY

Do not include columns whose ThoughtSpot formula cannot be translated to
Databricks SQL. Instead:

1. Omit the column from the generated YAML
2. Log it in the Unmapped Properties Report

---

## Unmapped ThoughtSpot Properties

These ThoughtSpot properties have no Databricks MV equivalent in v0.1:

| ThoughtSpot property | Status | Notes |
|---|---|---|
| `synonyms[]` | **Unmapped** | MV has no synonym support |
| `column.description` | **Unmapped in v0.1** | v1.1 adds `description:` field |
| `ai_context` | **Unmapped** | No equivalent |
| `properties.calendar_type` | **Unmapped** | No equivalent |
| `joins[]` / `referencing_join` | **Unmapped in v0.1** | v1.1 supports `entities` + `primary_key`/`foreign_key` |
| `properties.index_type` | **Unmapped** | Databricks handles indexing internally |
| `properties.index_priority` | **Unmapped** | No equivalent |
| `column_type: UNKNOWN` | **Omit** | Cannot classify — log in report |
