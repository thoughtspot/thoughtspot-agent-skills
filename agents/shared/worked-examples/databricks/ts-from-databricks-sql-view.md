# Worked Example — Databricks Metric View (SELECT Subquery Source) → ThoughtSpot SQL View + Model

End-to-end conversion of a Databricks Metric View whose `source:` is a SELECT
subquery (not a table FQN) into a ThoughtSpot SQL View and Model. Covers the
subquery detection path (option T), filter baked into `sql_query` WHERE clause,
CASE expression translated to nested `if()` with comma syntax, `COUNT(DISTINCT)`
as `unique count`, `COUNT(*)` as `count ( 1 )`, and ratio measures with inlined
aggregates.

The source is `select * from analytics.sales.orders` with a MV-level filter
`order_status = 'completed'`. The Databricks connection in ThoughtSpot is named
`Databricks - Analytics`. The user chose option T (ThoughtSpot SQL View) for the
subquery source.

Verified against live instance 2026-05-28.

> **Style aligned 2026-07-10** — Style aligned with ts-from-databricks.md Key
> Pattern #3 (title-case fallback) and explicit ATTRIBUTE formula
> `column_type` on 2026-07-10 — semantics unchanged from the 2026-05-28 live
> verification.

---

## Input -- MV YAML (v1.1)

```yaml
version: "1.1"
source: "select * from analytics.sales.orders"
filter: "order_status = 'completed'"
dimensions:
  - name: order_id
    expr: order_id
  - name: order_date
    expr: order_date
    display_name: "Order Date"
  - name: order_status
    expr: order_status
    display_name: "Order Status"
  - name: customer_segment
    expr: "CASE WHEN total_amount > 1000 THEN 'Premium' WHEN total_amount > 100 THEN 'Standard' ELSE 'Basic' END"
    display_name: "Customer Segment"
measures:
  - name: total_orders
    expr: "COUNT(*)"
    display_name: "Total Orders"
  - name: total_amount
    expr: "SUM(total_amount)"
    display_name: "Total Amount"
  - name: avg_order_amount
    expr: "SUM(total_amount) / COUNT(DISTINCT order_id)"
    display_name: "Avg Order Amount"
```

---

## Step 1 -- Detect Subquery Source

The `source:` value starts with `select` -- this is a SELECT subquery, not a
three-part table FQN. Per the from-databricks rules, present the user with
options:

```
The Metric View source is a SELECT subquery, not a table reference:
  select * from analytics.sales.orders

How should this be handled?
  D -- Create a Databricks VIEW from this SQL, then use it as the source table
  T -- Create a ThoughtSpot SQL-Based View (sql_view TML) from this SQL
  M -- Map to an existing Unity Catalog table or view (you provide the name)
  S -- Skip -- cannot convert this Metric View
```

User selects **(T)** -- ThoughtSpot SQL View.

This means:
1. Build a `sql_view` TML with the subquery as `sql_query`, referencing the Databricks connection
2. Import the SQL View to get a ThoughtSpot object with a GUID
3. Build the Model TML referencing the SQL View as its table source

---

## Step 2 -- Build the SQL View TML

The MV's `source:` subquery and `filter:` clause are combined into a single
`sql_query`. The filter becomes a WHERE clause appended to the source SQL:

```
select * from analytics.sales.orders WHERE order_status = 'completed'
```

The `sql_view_columns:` list enumerates every column from the query output. Each
column gets a `sql_output_column` matching the SQL column name. Measures get
`column_type: MEASURE` with an `aggregation`; attributes get `column_type: ATTRIBUTE`.

```yaml
sql_view:
  name: Orders_MV_View
  description: "SQL View created from Databricks Metric View subquery source. Filter: order_status = 'completed'."
  connection:
    name: "Databricks - Analytics"
  sql_query: "select * from analytics.sales.orders WHERE order_status = 'completed'"
  sql_view_columns:
  - name: order_id
    sql_output_column: order_id
    properties:
      column_type: ATTRIBUTE
  - name: order_date
    sql_output_column: order_date
    properties:
      column_type: ATTRIBUTE
  - name: order_status
    sql_output_column: order_status
    properties:
      column_type: ATTRIBUTE
  - name: total_amount
    sql_output_column: total_amount
    properties:
      column_type: MEASURE
      aggregation: SUM
```

**Key points:**
- Top-level key is `sql_view:` -- NOT `view:` and NOT `table:`.
- `connection.name` is required on the SQL View -- it tells ThoughtSpot which
  database connection to execute the query against.
- `sql_query` contains the original SELECT with the MV's `filter:` baked into a
  WHERE clause.
- `sql_output_column` maps to the column names produced by the SQL query output.
  Since the query is `select *`, these are the physical column names from the
  source table.
- The MV filter (`order_status = 'completed'`) is baked into the `sql_query`
  WHERE clause rather than handled as a model-level filter. With option T the
  SQL View IS the data source -- the filter is applied at query execution time.
- `column_type` and `aggregation` are set on the SQL View columns. The Model
  layer can override these, but setting them here provides sensible defaults if
  the SQL View is used directly.

---

## Step 3 -- Import the SQL View

```bash
ts tml import --profile {profile} --policy PARTIAL --create-new
```

The TML is passed via stdin. On success the import response returns the GUID of
the new SQL View object. Record it for Step 4.

Example response:
```json
{
  "object": [
    {
      "response": {"status": {"status_code": "OK"}},
      "header": {
        "identifier": "11111111-2222-3333-4444-555555555555",
        "name": "Orders_MV_View",
        "type": "SQL_VIEW"
      }
    }
  ]
}
```

The SQL View GUID is `11111111-2222-3333-4444-555555555555`.

**Metadata search type:** SQL Views appear as `type: LOGICAL_TABLE` with
`subtype: SQL_VIEW` in search results.

---

## Step 4 -- Parse and Classify MV Columns

### Dimensions

| Name | `expr` | `display_name` | Classification | Reason |
|---|---|---|---|---|
| order_id | `order_id` | -- | Direct ATTRIBUTE | Single column reference |
| order_date | `order_date` | Order Date | Direct ATTRIBUTE | Single column reference |
| order_status | `order_status` | Order Status | Direct ATTRIBUTE | Single column reference |
| customer_segment | `CASE WHEN total_amount > 1000 THEN 'Premium' WHEN total_amount > 100 THEN 'Standard' ELSE 'Basic' END` | Customer Segment | Formula ATTRIBUTE | Multi-branch CASE expression |

### Measures

| Name | `expr` | `display_name` | Classification | Reason |
|---|---|---|---|---|
| total_orders | `COUNT(*)` | Total Orders | Formula MEASURE | `COUNT(*)` has no TS equivalent -- use `count ( 1 )` |
| total_amount | `SUM(total_amount)` | Total Amount | Simple MEASURE | Single `SUM` on one column |
| avg_order_amount | `SUM(total_amount) / COUNT(DISTINCT order_id)` | Avg Order Amount | Formula MEASURE | Ratio of two aggregates -- must inline both |

---

## Step 5 -- Translate Formulas

### Dimension: Customer Segment

Databricks:
```
CASE WHEN total_amount > 1000 THEN 'Premium' WHEN total_amount > 100 THEN 'Standard' ELSE 'Basic' END
```

ThoughtSpot formula:
```
if ( [Orders_MV_View::total_amount] > 1000 , 'Premium' , if ( [Orders_MV_View::total_amount] > 100 , 'Standard' , 'Basic' ) )
```

Multi-branch `CASE WHEN ... WHEN ... ELSE ... END` maps to nested `if()` using
**comma syntax**: `if ( cond , true_val , false_val )`. The comma form and the
keyword form (`if (cond) then true else false`) are both valid ThoughtSpot formula
syntax. This example uses the comma form.

The column reference uses `[Orders_MV_View::total_amount]` -- the SQL View name
as the table qualifier, because the Model sits on top of the SQL View.

### Measure: Total Orders

Databricks:
```
COUNT(*)
```

ThoughtSpot formula:
```
count ( 1 )
```

ThoughtSpot has no `COUNT(*)` syntax. Use `count ( 1 )` as the equivalent.

### Measure: Avg Order Amount

Databricks:
```
SUM(total_amount) / COUNT(DISTINCT order_id)
```

ThoughtSpot formula:
```
sum ( [Orders_MV_View::total_amount] ) / unique count ( [Orders_MV_View::order_id] )
```

Ratio of two aggregates -- both must be inlined in a single formula expression.
Cross-formula references fail during TML import, so each aggregate is written
out directly rather than referencing Total Amount or a separate Order Count formula.

`COUNT(DISTINCT col)` translates to `unique count` (two words, space -- NOT
`unique_count` with underscore).

---

## Step 6 -- Build the Model TML

The Model references the SQL View in `model_tables[]`. Column references use
`[Orders_MV_View::column]` syntax throughout.

```yaml
model:
  name: Orders_MV_Model
  description: "Converted from Databricks Metric View. Source: select * from analytics.sales.orders. Filter baked into SQL View WHERE clause."
  model_tables:
  - name: Orders_MV_View
    fqn: "11111111-2222-3333-4444-555555555555"
  formulas:
  - id: formula_Customer Segment
    name: Customer Segment
    expr: "if ( [Orders_MV_View::total_amount] > 1000 , 'Premium' , if ( [Orders_MV_View::total_amount] > 100 , 'Standard' , 'Basic' ) )"
    properties:
      column_type: ATTRIBUTE
  - id: formula_Total Orders
    name: Total Orders
    expr: "count ( 1 )"
  - id: formula_Avg Order Amount
    name: Avg Order Amount
    expr: "sum ( [Orders_MV_View::total_amount] ) / unique count ( [Orders_MV_View::order_id] )"
  columns:
  - name: Order Id
    column_id: Orders_MV_View::order_id
    properties:
      column_type: ATTRIBUTE
  - name: Order Date
    column_id: Orders_MV_View::order_date
    properties:
      column_type: ATTRIBUTE
  - name: Order Status
    column_id: Orders_MV_View::order_status
    properties:
      column_type: ATTRIBUTE
  - name: Customer Segment
    formula_id: formula_Customer Segment
    properties:
      column_type: ATTRIBUTE
  - name: Total Orders
    formula_id: formula_Total Orders
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
  - name: Total Amount
    column_id: Orders_MV_View::total_amount
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Avg Order Amount
    formula_id: formula_Avg Order Amount
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
  properties:
    is_bypass_rls: false
    join_progressive: true
```

**Key points:**
- `model_tables:` references the SQL View by its ThoughtSpot object name
  (`Orders_MV_View`) and the GUID from Step 3 as the `fqn`.
- Column references use `[Orders_MV_View::column]` syntax -- the SQL View name
  as the table qualifier, not the physical Databricks table name.
- Direct dimensions (Order Id, Order Date, Order Status) use
  `column_id: Orders_MV_View::col`.
- The computed dimension (Customer Segment) uses `formula_id` pointing to the
  `formulas[]` entry with the nested `if()` expression.
- Total Amount is a simple MEASURE (`SUM(total_amount)`) so it uses `column_id`
  directly with `aggregation: SUM` -- no formula needed.
- Total Orders and Avg Order Amount are formula MEASURE columns with
  `aggregation: SUM` as convention (ThoughtSpot evaluates the formula `expr`
  directly and ignores column-level `aggregation` at query time).
- `display_name` from the MV YAML becomes the column `name` in ThoughtSpot.
  Where no `display_name` exists (`order_id`), the `name` field is title-cased
  (`Order Id`) -- matching ts-from-databricks.md Key Pattern #3.
- No MV Filter formula is needed -- the filter is already baked into the SQL
  View's `sql_query` WHERE clause. Every query against the SQL View automatically
  applies the filter.
- `formulas` section appears before `columns` section in the YAML.

---

## Step 7 -- Import the Model

```bash
ts tml import --profile {profile} --policy PARTIAL --create-new
```

The Model TML is passed via stdin. On success the import response returns the GUID.

Example response:
```json
{
  "object": [
    {
      "response": {"status": {"status_code": "OK"}},
      "header": {
        "identifier": "66666666-7777-8888-9999-aaaaaaaaaaaa",
        "name": "Orders_MV_Model",
        "type": "LOGICAL_TABLE",
        "metadata_type": "WORKSHEET"
      }
    }
  ]
}
```

The Model GUID is `66666666-7777-8888-9999-aaaaaaaaaaaa`.

**Metadata type note:** ThoughtSpot reports Models as `metadata_type: WORKSHEET`
with `subtype: MODEL` in detailed search results. The import response shows
`type: LOGICAL_TABLE`.

---

## Step 8 -- Verification

Confirm both objects exist via metadata search:

```bash
ts metadata search --profile {profile} --subtype SQL_VIEW --name "Orders_MV_View"
```

```json
[
  {
    "metadata_id": "11111111-2222-3333-4444-555555555555",
    "metadata_name": "Orders_MV_View",
    "metadata_type": "LOGICAL_TABLE",
    "metadata_sub_type": "SQL_VIEW"
  }
]
```

```bash
ts metadata search --profile {profile} --subtype WORKSHEET --name "Orders_MV_Model"
```

```json
[
  {
    "metadata_id": "66666666-7777-8888-9999-aaaaaaaaaaaa",
    "metadata_name": "Orders_MV_Model",
    "metadata_type": "LOGICAL_TABLE",
    "metadata_sub_type": "MODEL"
  }
]
```

Both objects confirmed: SQL_VIEW (`Orders_MV_View`) and MODEL (`Orders_MV_Model`).

---

## Key Patterns

1. **`sql_view:` is the correct TML type for subquery sources.** When the user
   picks option T, the subquery becomes a ThoughtSpot SQL View (`sql_view:` TML
   type). This is NOT the same as a View (`view:` / `AGGR_WORKSHEET`) -- see
   `thoughtspot-sql-view-tml.md` for the distinction.

2. **MV filter baked into `sql_query` WHERE clause.** Because the SQL View IS
   the data source, the filter is applied at query execution time by appending it
   to the source SQL: `select * from ... WHERE order_status = 'completed'`. No
   separate boolean formula or model-level `filters:` section is needed.

3. **CASE translates to nested `if()` with comma syntax.** Multi-branch
   `CASE WHEN a THEN x WHEN b THEN y ELSE z END` becomes
   `if ( a , x , if ( b , y , z ) )`. The comma form (`if(cond, true, false)`)
   and the keyword form (`if (cond) then true else false`) are both valid
   ThoughtSpot formula syntax -- this example uses the comma form.

4. **`COUNT(DISTINCT col)` translates to `unique count` (two words with space).**
   NOT `unique_count` with underscore. Never use `aggregation: COUNT_DISTINCT`
   on a `column_id` -- ThoughtSpot silently overrides `column_type` to ATTRIBUTE.

5. **`COUNT(*)` translates to `count ( 1 )`.** ThoughtSpot has no `COUNT(*)`
   syntax. The literal `1` is passed as the argument.

6. **Ratio measures inline both aggregates.** Cross-formula references fail
   during TML import. `SUM(total_amount) / COUNT(DISTINCT order_id)` becomes a
   single formula: `sum([col]) / unique count([col])`. Do not reference other
   formula columns.

7. **Model references SQL View via `[SQL_VIEW_NAME::column]` syntax.** The SQL
   View name (`Orders_MV_View`) acts as the table qualifier in all column
   references: `[Orders_MV_View::total_amount]`, `[Orders_MV_View::order_id]`.

8. **`sql_output_column` maps to SQL query output column names.** Each
   `sql_view_columns[]` entry's `sql_output_column` must match a column name or
   alias produced by the `sql_query`. For `select *`, these are the physical
   column names from the source table.

9. **`connection.name` required on SQL View, not on Model.** The SQL View
   specifies `connection.name: "Databricks - Analytics"` because it executes SQL
   against the database. The Model inherits the connection through the SQL View --
   no connection reference is needed on the Model TML.
