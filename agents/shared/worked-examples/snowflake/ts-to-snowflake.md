# Worked Example — ThoughtSpot Worksheet → Snowflake Semantic View

End-to-end conversion of the `Retail Sales` Worksheet to a Snowflake Semantic View
named `retail_sales`. Covers column classification, formula translation, name
generation, and relationship mapping.

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

Associated Table TML for `fact_sales`: `db: ANALYTICS, schema: PUBLIC, db_table: FACT_SALES`.
Associated Table TML for `dim_product`: `db: ANALYTICS, schema: PUBLIC, db_table: DIM_PRODUCT`.
Join condition from `fact_sales` Table TML: `[fact_sales::product_id] = [dim_product::product_id]`.

---

## Parse the Worksheet TML

**Tables and table_paths:**

| table_path id | table | join_path | Role |
|---|---|---|---|
| `fact_sales_1` | `fact_sales` | (none — empty) | Fact / left side |
| `dim_product_1` | `dim_product` | via `sales_to_product` | Dimension / right side |

**Joins:**

| Name | Source | Destination | Type |
|---|---|---|---|
| `sales_to_product` | `fact_sales` | `dim_product` | INNER |

`dim_product` is the destination — it becomes the `right_table` in the relationship
and requires a `primary_key` in the semantic view.

**Columns:**

| Display Name | column_id / formula_id | column_type | aggregation | Other |
|---|---|---|---|---|
| Product | `dim_product_1::product_name` | ATTRIBUTE | — | synonyms: [Item] |
| Revenue | `fact_sales_1::sales_amount` | MEASURE | SUM | synonyms: [Sales], ai_context set |
| Sale Date | `fact_sales_1::sale_date` | ATTRIBUTE | — | — |
| Product Count | formula `# of Products` | MEASURE | COUNT | — |

---

## Fetch Table Details

Export Table TML for `fact_sales` and `dim_product` to get physical `db`, `schema`,
`db_table` values and the join condition column names.

**From `fact_sales` Table TML:**
- `db: ANALYTICS`, `schema: PUBLIC`, `db_table: FACT_SALES`
- `joins_with` entry for `dim_product`: `on: "[fact_sales::product_id] = [dim_product::product_id]"`
  → FK column: `PRODUCT_ID`, PK column: `PRODUCT_ID`

**From `dim_product` Table TML:**
- `db: ANALYTICS`, `schema: PUBLIC`, `db_table: DIM_PRODUCT`
- PK column (from join condition above): `PRODUCT_ID`

**`base_table` values (UPPERCASE = case-insensitive, no quoting needed):**

| Table | database | schema | table |
|---|---|---|---|
| fact_sales | ANALYTICS | PUBLIC | FACT_SALES |
| dim_product | ANALYTICS | PUBLIC | DIM_PRODUCT |

---

## Classify Columns

Apply the classification decision tree to each column:

| Display Name | formula_id? | column_type | db_column_type / name | → Semantic View section |
|---|---|---|---|---|
| Product | no | ATTRIBUTE | `product_name` — no date suffix | **dimensions** |
| Revenue | no | MEASURE | — | **metrics** |
| Sale Date | no | ATTRIBUTE | `sale_date` — name ends with `_date` → date | **time_dimensions** |
| Product Count | yes (`# of Products`) | MEASURE | — | **metrics** (if translatable) |

**Sale Date classification note:** `column_type` is ATTRIBUTE but the column name ends with
`_date`. Apply the name-based date heuristic — classify as `time_dimensions`.

---

## Translate Formulas

**Formula: `# of Products`**

ThoughtSpot expression: `count ( [dim_product_1::product_id] )`

Translation:
- `count(...)` → `COUNT(...)` (direct mapping)
- `[dim_product_1::product_id]` → resolve `dim_product_1` table_path → `dim_product` table → `dim_product.PRODUCT_ID`
- Result: `COUNT(dim_product.PRODUCT_ID)`

✓ Translatable — add as `metrics` entry on `dim_product`.

---

## Generate Snowflake Names

Apply the name generation rules (lowercase, non-alphanumeric → underscore, strip ends):

| ThoughtSpot Display Name | Generated Name | Flag? |
|---|---|---|
| Product | `product` | no |
| Revenue | `revenue` | no |
| Sale Date | `sale_date` | no |
| Product Count | `product_count` | no |
| `# of Products` (formula name used as synonym) | `of_products` | **yes** — semantic loss from `#` prefix; override with `product_count` (matches display name) |
| Retail Sales (view name) | `retail_sales` | no |

**Review checkpoint presented to user:**

```
Name to review:
  ⚠ Formula '# of Products' → 'of_products' (# stripped — semantic loss)
    Suggestion: use 'product_count' (matches the 'Product Count' display name)
    Override? [product_count]:
```
User accepts `product_count`.

---

## Build Relationship

From the join: `sales_to_product` — `fact_sales` → `dim_product`, join column `PRODUCT_ID`.

```yaml
relationships:
- name: sales_to_product
  left_table: fact_sales
  right_table: dim_product
  relationship_columns:
  - left_column: PRODUCT_ID
    right_column: PRODUCT_ID
```

`dim_product` is the right_table → add `primary_key: columns: [PRODUCT_ID]` to its table entry.

---

## Dry-Run Validation

```sql
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('ANALYTICS.PUBLIC', $$
name: retail_sales
...
$$, TRUE);
```

Returns success — proceed to create.

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

## Key patterns from this example

1. **Column classification order matters.** `Sale Date` has `column_type: ATTRIBUTE` in the
   ThoughtSpot TML, but the name-based date heuristic overrides it to `time_dimensions`.
   Always check `db_column_type` (from Table TML) first, then fall back to name heuristics.

2. **Formula columns resolve via table_path.** `[dim_product_1::product_id]` uses the
   `table_path id` (`dim_product_1`), not the table name. Look up the table_path to find
   the underlying table (`dim_product`), then emit `dim_product.PRODUCT_ID`.

3. **`primary_key` on the right-side join table.** The `destination` of a ThoughtSpot join
   becomes the `right_table` in the relationship and requires `primary_key` in the semantic
   view. Extract the PK column from the join condition in the Table TML.

4. **`primary_key.columns` must be bare unquoted identifiers.** Even for case-sensitive
   lowercase columns, do not use `'"col"'` quoting — Cortex Analyst rejects it. Use
   the plain name (`product_id`, not `'"product_id"'`).

5. **Name generation: flag semantic loss.** `# of Products` → `of_products` loses the
   count intent. Always flag these at the review checkpoint and suggest a better name.
   The original name is preserved in `synonyms` so Cortex Analyst can still find it.

6. **`ai_context` becomes `[TS AI Context]` prefix in `description`.** The `Revenue`
   column's `ai_context` value is prepended with `[TS AI Context] ` and written to
   the semantic view `description` field.

7. **`dimensions`, `time_dimensions`, `metrics` are nested under their table.** They are
   NOT top-level keys. Each table entry owns its columns.

8. **Keyword is `metrics`, not `measures`.** Using `measures` is a schema error that
   causes a parse failure at creation time.
