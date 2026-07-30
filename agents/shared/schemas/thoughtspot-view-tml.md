<!-- currency: thoughtspot — 2026-07 (view_columns[] column-reference field corrected from `column_id` to `search_output_column`, and five property rows added, from a 500-document TML property census on se-thoughtspot 2026-07-30 — 42 of 42 real Views, 265 of 265 columns; `column_id` observed zero times) -->

# ThoughtSpot View TML — Structure Reference (AGGR_WORKSHEET)

> ### ⚠️ Corrected 2026-07-30 — `view_columns[]` uses `search_output_column`, not `column_id`
>
> An earlier revision of this file documented `view_columns[].column_id` (format
> `<table_path_id>::<column_name>`) as the View column-reference field. **That field does not
> appear in real View TML.** A read-only property census of 500 logical-table TML documents on
> `se-thoughtspot` (2026-07-30) covered **all 42** `AGGR_WORKSHEET` objects on the cluster:
>
> | Observation | Count |
> |---|---|
> | `view_columns[]` entries carrying `search_output_column` | **265 / 265** (42 / 42 Views) |
> | `view_columns[]` entries carrying `column_id` | **0** |
> | `search_output_column` values containing `::` | **0** |
> | Distinct `view_columns[]` keys observed, ever | exactly three: `name`, `search_output_column`, `properties` |
>
> `search_output_column` is **not** a table-path reference. It is the column's label *in the
> View's own `search_query` output*, including the aggregation or bucket prefix ThoughtSpot's
> search result uses. In **256 of 265** columns it equals `name`; where it differs, the difference is
> exactly that prefix (figures and the full key-path inventory: [the census report](../../../docs/reviews/2026-07-30-tml-census.md)) — `name: YM` / `search_output_column: Month(YM)`,
> `name: LINEAMOUNT` / `search_output_column: Total LINEAMOUNT`,
> `name: row_count` / `search_output_column: Average num_rows`. A **formula** column is referenced
> the same way, by the `formulas[].name` (not the `formulas[].id`): `name: prev_year` /
> `search_output_column: prev_year`.
>
> This also means a View's semantics live in `search_query` — the aggregation and filtering are in
> the search string, and `view_columns[]` only names and decorates its output columns.
>
> **Scope caveat, stated by the census itself.** 42 Views on one SE demo cluster is decisive for
> *this* build, but it is one cluster. `column_id` may be a legacy or version-gated spelling that
> this cluster no longer emits. Treat `search_output_column` as the field to generate and to read;
> if a second cluster produces `column_id`, tolerate it on input rather than assuming the census
> was wrong. Re-running the census against a second cluster is tracked as **BL-190** (census follow-up
> **T3**, folded into that entry's scope).
>
> Note that `thoughtspot-sql-view-tml.md` lists "using `search_output_column`" as a *common import
> error* — that is correct for `sql_view:` (whose field is `sql_output_column`) and does **not**
> apply here. The two document types genuinely differ.

How a ThoughtSpot View (Aggregated Worksheet) is represented in TML. Views are
search-query-based logical tables — they can be a data source for Answers and
Liveboards in the same way a Model can.

**This is NOT a SQL View.** For the `sql_view:` TML type (query-backed views that
run raw SQL against a database connection), see
[thoughtspot-sql-view-tml.md](thoughtspot-sql-view-tml.md).

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
    id:   "Customer_to_Orders"     # observed equal to name; emitted alongside it
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
    was_auto_generated: false      # always emitted when a View has formulas (46/46 observed)
    properties:
      column_type: MEASURE
      # data_type / aggregation under formulas[].properties: never observed on a real View
      # (only column_type, on 4 of 46 formula entries). Treat both as unverified.

  filters:                         # row-level filters baked into the view
  - column: "Orders_Fact_1::Status"
    oper:   in
    values:
    - "Active"
    - "Completed"

  search_query: "[Revenue] [Customer Name] [Region]"   # optional; defines underlying query

  view_columns:                    # columns exposed to Answers/Liveboards
  # Only three keys are ever emitted: name, search_output_column, properties.
  - name:                 "Customer Name"
    search_output_column: "Customer Name"        # label in the search_query output — NOT table_path::col
    properties:
      column_type:      ATTRIBUTE
      index_type:       DONT_INDEX
      value_casing:     UNKNOWN

  - name:                 "Revenue"
    search_output_column: "Total Revenue"        # aggregation prefix present in the search output
    properties:
      column_type:      MEASURE
      aggregation:      SUM
      currency_type:
        iso_code:       USD

  - name:                 "Region"
    search_output_column: "Region"
    properties:
      column_type:      ATTRIBUTE
      geo_config:
        region_name:                             # a DICT, not a list — see the note below
          country:     "UNITED STATES"
          region_name: "state"

  - name:                 "Sale Date"
    search_output_column: "Month(Sale Date)"     # bucket prefix present in the search output
    properties:
      column_type:      ATTRIBUTE
      format_pattern:   "MMM yyyy"

  - name:                 "Revenue per Customer"  # formula column
    search_output_column: "Revenue per Customer"  # matches formulas[].NAME, not formulas[].id
    properties:
      column_type:      MEASURE

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

### `view_columns[].properties` — census-observed vocabulary

The census (2026-07-30, all 42 Views / 265 columns on `se-thoughtspot`) observed only these
seven properties. Everything else our earlier revision listed —
`synonyms`, `index_priority`, `is_hidden`, `is_additive`, `default_date_bucket`, and the
`description` / `phrase` / `column_id` sibling keys — was **never emitted**, so treat those as
unverified for the `view:` type rather than as documented.

| Property | Occ | Docs | Notes |
|---|--:|--:|---|
| `column_type` | 265 | 42/42 | `ATTRIBUTE` / `MEASURE` — always present |
| `aggregation` | 104 | 35/42 | **Wider vocabulary than any other document type** — see below |
| `index_type` | 126 | 36/42 | `DONT_INDEX` only, in every sighting |
| `value_casing` | 75 | 10/42 | `UNKNOWN` only. Was documented as Table-only; it is on Views too |
| `format_pattern` | 13 | 11/42 | `MMM yyyy`, `q yyyy`, and note the quoted-literal date form `yyyyMMdd HH':'mm':'ss` |
| `currency_type.iso_code` | 5 | 5/42 | `USD`, `JPY`. Only the `iso_code` form was seen on a View |
| `geo_config.region_name` | 1 | 1/42 | A **dict**, `{country, region_name}` — see below |

**`geo_config.region_name` is a dict, not a list.** This file previously documented it as a list
of `{country, region_name}` objects. The single live sighting (`LMS Banking View`, column `State`)
is a dict — matching `thoughtspot-model-tml.md`, which had it right. Emit the dict form.
`thoughtspot-sql-view-tml.md` carries the same list-shaped error and is corrected alongside.

**`aggregation` on a View column takes values no other document type uses.** Beyond the
nine documented elsewhere (`SUM COUNT AVERAGE MIN MAX COUNT_DISTINCT NONE STD_DEVIATION
VARIANCE`), the census observed:

| Value | Occ | Where |
|---|--:|---|
| `MOVING_SUM` | 2 | `Growth View` col `prev_year`; `GA - Moving Sum Test` col `Test formula` |
| `RANK` | 1 | `Rank Sales, Quota` col `Rank Sales` |
| `SQL_INT_AGGREGATE_OP` | 1 | `% of Total Test` col `Rank` |

These are the *window-function* aggregation kinds a View's search output can carry, and they
appear **only** on `view:` documents. Verified across all 500 census documents:
`model:` columns used `{SUM, AVERAGE, COUNT, COUNT_DISTINCT, MIN}`, `table:` columns
`{SUM, AVERAGE, COUNT, COUNT_DISTINCT}`, `sql_view:` columns `{SUM, AVERAGE}` — none of the three
carries a window value. A reader that validates View columns against the Model/Table enum will
reject real ThoughtSpot output.

---

## Field Reference

| Field | Purpose | Notes |
|---|---|---|
| `guid` | View GUID — document root | Same convention as Model TML |
| `view.name` | Display name | Required |
| `view.tables[].name` | Source table name | Required |
| `view.tables[].fqn` | Source table GUID | Populated by `--fqn` export flag; required for multi-instance portability |
| `view.joins[].source` / `.destination` | Tables in this join | Must match a name in `view.tables[]` |
| `view.joins[].id` | Join id | Observed emitted alongside `name` and equal to it. Only 1 of 42 Views has `joins` at all, and that entry carries **only** `id`, `name`, `source`, `destination` — `on`, `type` and `is_one_to_one` were never observed on a `view.joins[]` entry |
| `view.joins[].on` | Join expression | Uses `[table_path::column]` syntax. Never observed in the census — unverified for the `view:` type |
| `view.table_paths[].id` | Path alias | Referenced by `view.formulas[].expr`. **Not** by `view_columns[]`, which uses `search_output_column` |
| `view.table_paths[].table` | Table this path starts from | Must match `view.tables[].name` |
| `view.formulas[].id` | Formula ID | Convention: `"formula_"` + name |
| `view.formulas[].name` | Formula display name | **This is what `view_columns[].search_output_column` matches for a formula column** — not the `id` |
| `view.formulas[].expr` | Formula expression | Column refs use `[table_path_id::column_name]`, or `[column_name]` where the View is single-table |
| `view.formulas[].was_auto_generated` | AI-generated flag | Boolean. Observed on **46 of 46** View formula entries — always emitted when a View has formulas. Asymmetric with Models, where it was never emitted (0 of 555) |
| `view.view_columns[].name` | Display name | Required. Always present |
| `view.view_columns[].search_output_column` | **Column reference** | Required — the column's label in the `search_query` output, including any aggregation/bucket prefix (`Total Revenue`, `Month(YM)`). **Never** `table_path::column`. For a formula column it matches `formulas[].name`. See the correction banner at the top of this file |
| `view.search_query` | Base query string | **Required in practice — observed on 42 of 42 Views.** This is where a View's actual semantics live: the aggregation and the filtering are in the search string, not in `view_columns[]`. See #search_query note |

---

## Dependency Management Notes

**When removing a column from a source Table:**
- Find Views with `view.tables[].fqn == table_guid`
- Remove matching entries from `view.view_columns[]` where `search_output_column` (or `name`)
  refers to the column — note this is a **label match, not a `table_path::column` match**, so it
  must tolerate an aggregation or bucket prefix (`Total Revenue`, `Month(Sale Date)`)
- Remove matching entries from `view.formulas[]` where `expr` references the column
- Remove matching entries from `view.joins[]` where `on` expression references the column
- Update `view.search_query` to remove the column token if present — **this is the load-bearing
  edit**, since the View's semantics live in the search string

**When renaming a column in a source Table:**
- Update `view.view_columns[].search_output_column` — preserving any aggregation/bucket prefix
- Update `view.formulas[].expr` — replace `[table_path::old_name]` with `[table_path::new_name]`
- Update `view.joins[].on` where the column name appears
- Update `view.search_query` if it contains `[old_name]`

**`search_output_column` format:**
- For regular columns: the search-output label, e.g. `Revenue`, `Total Revenue`, `Month(YM)`.
  Equal to `name` in **256 of 265** observed columns; where it differs, the difference is the
  aggregation or bucket prefix. **Never contains `::`** (0 of 265). Corpus and per-column figures:
  [the census report](../../../docs/reviews/2026-07-30-tml-census.md)
- For formula columns: the `formulas[].name` value (e.g. `Revenue per Customer`) — **not** the
  `formulas[].id`

**`search_query` note:**
View `search_query` uses the same `[column_name]` bracket syntax as Answer TML. If a view
has a `search_query`, it must be sanitized when a column is removed (same as Answers) —
importing a view with a stale column reference in `search_query` will fail.

---

## Self-validation Checklist

Before importing a modified View TML:

- [ ] `guid:` is at the document root, not nested inside `view:`
- [ ] Every `view_columns[]` entry carries `name`, `search_output_column` and `properties` — and
      **no `column_id`**, which is not a field of this document type
- [ ] Every `view_columns[].search_output_column` names a column the `search_query` actually
      outputs (including its aggregation/bucket prefix), not a `table_path::column` reference
- [ ] Every formula surfaced in `view_columns[]` is matched by `formulas[].name`, not `formulas[].id`
- [ ] `table_paths[].id` values are referenced from `formulas[].expr` (they are **not** referenced
      from `view_columns[]`)
- [ ] No `view_columns[]` entries reference a column that was removed
- [ ] `geo_config.region_name` is emitted as a **dict**, not a list
- [ ] Every table in `joins[].source` and `joins[].destination` exists in `tables[]`
- [ ] `search_query` does not reference any removed column names
- [ ] `view.tables[].fqn` values are present (they are required for disambiguation on instances with multiple tables of the same name)
