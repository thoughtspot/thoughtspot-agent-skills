# ThoughtSpot View TML — Structure Reference

How a ThoughtSpot View (also called an "Aggregated Worksheet" or "SQL View") is
represented in TML. Views are query-based logical tables — they can be a data source
for Answers and Liveboards in the same way a Model can.

For dependency tracking: Views reference physical Tables. Answers and Liveboards can
reference Views. If a column is removed from a Table, Views built on that Table are
affected; if a View column is removed, Answers/Liveboards using that View are affected.

**Metadata search identifiers:**
- `type`: `LOGICAL_TABLE`
- `subtype`: `AGGR_WORKSHEET`

---

## Full View TML Structure

```yaml
guid: "<view_guid>"
view:
  name: "View Display Name"
  description: |
    Multi-line description of the View.

  tables:                          # source tables the view is built on
  - name: "Customer_Dimension"
    id:  "Customer_Dimension"      # optional local alias; defaults to name
    fqn: "<table_guid>"            # GUID of the ThoughtSpot Table object — populated by --fqn

  - name: "Orders_Fact"
    fqn: "<table_guid>"

  joins:                           # joins between source tables within this view
  - name: "Customer_to_Orders"
    source:      "Customer_Dimension"
    destination: "Orders_Fact"
    type:        LEFT_OUTER        # RIGHT_OUTER | LEFT_OUTER | INNER | OUTER
    on:          "[Customer_Dimension::Customer_ID] = [Orders_Fact::Customer_ID]"
    is_one_to_one: false

  table_paths:                     # named paths through joins — columns reference these
  - id:    "Customer_Dimension_1"
    table: "Customer_Dimension"
    join_path: []                  # empty = no joins (primary table)

  - id:    "Orders_Fact_1"
    table: "Orders_Fact"
    join_path:
    - join: ["Customer_to_Orders"]

  formulas:                        # calculated columns in the view
  - id:   "formula_Revenue per Customer"
    name: "Revenue per Customer"
    expr: "sum ( [Orders_Fact_1::Revenue] ) / count ( [Customer_Dimension_1::Customer_ID] )"
    properties:
      column_type: MEASURE
      data_type:   DOUBLE
      aggregation: SUM

  filters:                         # row-level filters baked into the view
  - column: "Orders_Fact_1::Status"
    oper:   in
    values:
    - "Active"
    - "Completed"

  search_query: "[Revenue] [Customer Name] [Region]"   # optional; defines underlying query

  view_columns:                    # columns exposed to Answers/Liveboards
  - name:               "Customer Name"
    description:        "Full name of the customer"
    column_id:          "Customer_Dimension_1::Customer_Name"   # <table_path_id>::<column_name>
    phrase:             "customer"
    properties:
      column_type:      ATTRIBUTE
      index_type:       DEFAULT
      index_priority:   5
      synonyms:
      - "client"
      - "buyer"
      is_hidden:        false

  - name:               "Revenue"
    column_id:          "Orders_Fact_1::Revenue"
    properties:
      column_type:      MEASURE
      aggregation:      SUM
      is_additive:      true

  - name:               "Region"
    column_id:          "Customer_Dimension_1::Region"
    properties:
      column_type:      ATTRIBUTE
      geo_config:
        region_name:
        - country:     "United States"
          region_name: "state"

  - name:               "Sale Date"
    column_id:          "Orders_Fact_1::Sale_Date"
    properties:
      column_type:           ATTRIBUTE
      default_date_bucket:   MONTHLY   # DAILY | WEEKLY | MONTHLY | QUARTERLY | YEARLY | HOURLY | AUTO

  - name:               "Revenue per Customer"  # formula column — matches formulas[].name
    column_id:          "formula_Revenue per Customer"   # matches formulas[].id

  joins_with:                      # how OTHER objects can join to this view
  - name:        "View_to_Budget"
    description: "Join view to budget table"
    destination:
      name: "Budget_Table"
      fqn:  "<budget_table_guid>"
    on:   "[Customer_Dimension_1::Region] = [Budget_Table::Region]"
    type: LEFT_OUTER
    is_one_to_one: false
```

---

## Field Reference

| Field | Purpose | Notes |
|---|---|---|
| `guid` | View GUID — document root | Same convention as Model TML |
| `view.name` | Display name | Required |
| `view.tables[].name` | Source table name | Required |
| `view.tables[].fqn` | Source table GUID | Populated by `--fqn` export flag; required for multi-instance portability |
| `view.joins[].source` / `.destination` | Tables in this join | Must match a name in `view.tables[]` |
| `view.joins[].on` | Join expression | Uses `[table_path::column]` syntax |
| `view.table_paths[].id` | Path alias | Referenced by `view_columns[].column_id` |
| `view.table_paths[].table` | Table this path starts from | Must match `view.tables[].name` |
| `view.formulas[].id` | Formula ID | Convention: `"formula_"` + name |
| `view.formulas[].expr` | Formula expression | Column refs use `[table_path_id::column_name]` |
| `view.view_columns[].column_id` | Column reference | Format: `<table_path_id>::<column_name>` or formula ID |
| `view.view_columns[].phrase` | Search keyword | Alternative term for NLP search |
| `view.search_query` | Optional base query string | Defines the underlying search; see #search_query note |

---

## Dependency Management Notes

**When removing a column from a source Table:**
- Find Views with `view.tables[].fqn == table_guid`
- Remove matching entries from `view.view_columns[]` where `column_id` contains the column name
- Remove matching entries from `view.formulas[]` where `expr` references the column
- Remove matching entries from `view.joins[]` where `on` expression references the column
- Update `view.search_query` to remove the column token if present

**When renaming a column in a source Table:**
- Update `view.view_columns[].column_id` — the `<column_name>` part after `::`
- Update `view.formulas[].expr` — replace `[table_path::old_name]` with `[table_path::new_name]`
- Update `view.joins[].on` where the column name appears
- Update `view.search_query` if it contains `[old_name]`

**`column_id` format:**
- For regular columns: `<table_path_id>::<column_name>` (e.g. `Orders_Fact_1::Revenue`)
- For formula columns: the formula `id` value (e.g. `formula_Revenue per Customer`)

**`search_query` note:**
View `search_query` uses the same `[column_name]` bracket syntax as Answer TML. If a view
has a `search_query`, it must be sanitized when a column is removed (same as Answers) —
importing a view with a stale column reference in `search_query` will fail.

---

## Self-validation Checklist

Before importing a modified View TML:

- [ ] `guid:` is at the document root, not nested inside `view:`
- [ ] Every `view_columns[].column_id` uses an existing `table_path_id` from `table_paths[]`
- [ ] Every formula `id` referenced in `view_columns[].column_id` exists in `formulas[]`
- [ ] No `view_columns[]` entries reference a column that was removed
- [ ] Every table in `joins[].source` and `joins[].destination` exists in `tables[]`
- [ ] `search_query` does not reference any removed column names
- [ ] `view.tables[].fqn` values are present (they are required for disambiguation on instances with multiple tables of the same name)
