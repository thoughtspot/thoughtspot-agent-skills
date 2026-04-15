# Worked Example — ThoughtSpot Worksheet → Snowflake Semantic View

A complete end-to-end mapping from a ThoughtSpot Worksheet TML to the equivalent
Snowflake Semantic View YAML. Consult this when verifying that your output structure
is correct.

---

## Input — ThoughtSpot Worksheet TML

```yaml
guid: 2ea7add9-0ccb-4ac1-90bb-231794ebb377
worksheet:
  name: Retail Sales
  tables:
  - name: fact_sales
  - name: dim_product
  joins:
  - name: sales_to_product
    source: fact_sales
    destination: dim_product
    type: INNER
    is_one_to_one: false
  table_paths:
  - id: fact_sales_1
    table: fact_sales
    join_path:
    - {}
  - id: dim_product_1
    table: dim_product
    join_path:
    - join:
      - sales_to_product
  formulas:
  - name: '# of Products'
    expr: "count ( [dim_product_1::product_id] )"
  worksheet_columns:
  - name: Product
    column_id: dim_product_1::product_name
    properties:
      column_type: ATTRIBUTE
      synonyms: [Item]
  - name: Revenue
    column_id: fact_sales_1::sales_amount
    properties:
      column_type: MEASURE
      aggregation: SUM
      synonyms: [Sales]
      ai_context: Total transaction value for financial analysis.
  - name: Sale Date
    column_id: fact_sales_1::sale_date
    properties:
      column_type: ATTRIBUTE
  - name: Product Count
    formula_id: '# of Products'
    properties:
      column_type: MEASURE
      aggregation: COUNT
```

Associated Table TML for `fact_sales` provides `db: ANALYTICS, schema: PUBLIC,
db_table: FACT_SALES` and the join condition
`"[fact_sales::product_id] = [dim_product::product_id]"`.

---

## Output — Snowflake Semantic View YAML

```yaml
name: retail_sales
description: "Migrated from ThoughtSpot: Retail Sales"

tables:
- name: fact_sales
  base_table:
    database: ANALYTICS
    schema: PUBLIC
    table: FACT_SALES
  time_dimensions:
  - name: sale_date
    synonyms:
    - "Sale Date"
    description: ""
    expr: fact_sales.SALE_DATE
    data_type: DATE
  metrics:
  - name: revenue
    synonyms:
    - "Revenue"
    - "Sales"
    description: "[TS AI Context] Total transaction value for financial analysis."
    expr: SUM(fact_sales.SALES_AMOUNT)

- name: dim_product
  base_table:
    database: ANALYTICS
    schema: PUBLIC
    table: DIM_PRODUCT
  primary_key:
    columns:
    - PRODUCT_ID
  dimensions:
  - name: product
    synonyms:
    - "Product"
    - "Item"
    description: ""
    expr: dim_product.PRODUCT_NAME
    data_type: TEXT
  metrics:
  - name: product_count
    synonyms:
    - "Product Count"
    - "# of Products"
    description: ""
    expr: COUNT(dim_product.PRODUCT_ID)

relationships:
- name: sales_to_product
  left_table: fact_sales
  right_table: dim_product
  relationship_columns:
  - left_column: PRODUCT_ID
    right_column: PRODUCT_ID
```

---

## Key differences from wrong patterns

- `dimensions`, `time_dimensions`, `metrics` are **nested under their table**, not top-level
- Keyword is `metrics`, not `measures`
- `primary_key` is present on `dim_product` (the right-side join table)
- No `relationship_type`, `join_type`, `sample_values`, or `default_aggregation`
