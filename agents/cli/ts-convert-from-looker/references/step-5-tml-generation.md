# Step 5 — TML Generation Detail

Reference detail for **Step 5 — Generate Table TMLs**: the full `derived_table:` → SQL
View TML procedure (§5b, including dialect adaptation, `sql_view_columns` construction,
measure handling, the full template, and the self-validation checklist), and the column-
and measure-naming conflict-resolution rules (§5c–§5f). The step's spine (which path to
take for a given view, and the decision to hand-assemble a SQL View vs a Table TML) stays
in `SKILL.md` — this file is what the spine links out to for the full rule/template detail.

---

## 5a. LookML type → ThoughtSpot `data_type` mapping

| LookML `type:` | `db_column_properties.data_type` |
|---|---|
| `string` | `VARCHAR` |
| `number` (integer, ID, key) | `INT64` |
| `number` (float/price) | `DOUBLE` |
| `yesno` | `BOOL` |
| `date` | `DATE` |
| `time`, `timestamp` | `DATE_TIME` |
| `dimension_group: { type: time }` | `DATE_TIME` |
| `tier` | `VARCHAR` |
| `duration` | `DOUBLE` |

When LookML type is ambiguous (e.g. a `number` that could be INT or FLOAT), default to `INT64` — ThoughtSpot will report a type mismatch if wrong, giving a clear signal to switch to `DOUBLE`.

## 5b. Derived tables (derived_table: { sql: ... }) → SQL View TML

When a view block contains `derived_table: { sql: ... }`, generate a **SQL View TML**
(`*.sql_view.tml`) instead of a Table TML. A ThoughtSpot SQL View is a query-backed
logical table — it runs raw SQL against the connection and exposes the result columns
exactly like a physical table. This is the direct equivalent of a Looker PDT.

**What to strip vs. keep:**

| LookML PDT block | Action |
|---|---|
| `derived_table: { sql: ... }` | Keep the SQL — translate dialect, see §5b-i |
| `persist_with:` | Strip — ThoughtSpot has no PDT scheduling |
| `datagroup_trigger:` | Strip |
| `sql_trigger:` | Strip |
| `max_cache_age:` | Strip |
| `explore_source:` (native DT) | **Cannot convert** — surface to user, omit + log |

### §5b-i. SQL dialect adaptation

The LookML PDT SQL is written for the Looker connection's warehouse dialect. Adapt it
for the ThoughtSpot connection's target warehouse before putting it in `sql_query:`.

**BigQuery → Snowflake (most common for qwiklab/training projects):**

| BigQuery pattern | Snowflake equivalent |
|---|---|
| `` `project.dataset.table` `` (backtick-quoted) | `DATABASE.SCHEMA.TABLE` |
| `CAST(x AS STRING)` | `CAST(x AS VARCHAR)` |
| `CAST(x AS INT64)` | `CAST(x AS NUMBER)` |
| `CAST(x AS FLOAT64)` | `CAST(x AS FLOAT)` |
| `DATE_TRUNC(col, MONTH)` | `DATE_TRUNC('MONTH', col)` — argument order flips |
| `TIMESTAMP_TRUNC(col, HOUR)` | `DATE_TRUNC('HOUR', col)` |
| `EXTRACT(YEAR FROM col)` | `EXTRACT(YEAR FROM col)` — same |
| `FORMAT_DATE('%Y-%m', col)` | `TO_CHAR(col, 'YYYY-MM')` |
| `IFNULL(a, b)` | `IFNULL(a, b)` — same |
| `DIV(a, b)` | `FLOOR(a / b)` |
| `SAFE_DIVIDE(a, b)` | `IFF(b = 0, NULL, a / b)` |

`${TABLE}` inside PDT SQL refers to the view's own derived output — it is only valid in
views that reference themselves, which is unusual. More commonly PDT SQL references
other views' physical tables via `cloud-training-demos.looker_ecomm.events` etc.
Resolve `${view.field}` cross-view refs using the dependency graph from Step 3d.

**If the SQL dialect cannot be reliably adapted** (e.g. BigQuery-specific UDFs or
Geography types with no Snowflake equivalent): surface the untranslatable expression,
propose the closest Snowflake alternative, and ask the user to confirm before proceeding.

### §5b-ii. Build sql_view_columns from LookML dimensions

Each `dimension:` / `dimension_group:` in the PDT view maps to a `sql_view_columns[]`
entry. The `sql_output_column` must match the **column alias in the SQL SELECT list** —
not the dimension's `sql:` expression.

Rule: scan the SQL SELECT clause for aliases. Match dimension `sql: ${TABLE}.col_alias`
→ `sql_output_column: col_alias`.

**On a Snowflake-backed ThoughtSpot connection, write both the SQL alias and
`sql_output_column` in UPPERCASE — do this proactively, don't wait for the import
error.** Snowflake normalizes unquoted identifiers to uppercase at query time, so a
`sql_query` with a lowercase `AS session_id` and a `sql_view_columns[].sql_output_column:
session_id` produces a case-sensitive string mismatch against what Snowflake actually
returns, and import fails with `"Column name [session_id, ...] is not present in SQL
query"` even though the SQL is syntactically valid and would run fine standalone. Fix:
explicit `AS SESSION_ID` in the SQL and `sql_output_column: SESSION_ID`, matching case
exactly. This applies per-connection dialect — check what the target connection's
warehouse type is (Step 3c) before assuming case rules; Databricks/Postgres-backed
connections preserve alias case as written and don't need this.

For `dimension_group: { type: time }` — the PDT SQL typically outputs one timestamp
column. Create **one** `sql_view_columns:` entry for the base timestamp; ThoughtSpot
derives date bucketing at query time, so you don't need separate entries for each
`timeframes:` value.

```yaml
# LookML:
#   dimension_group: event1 {
#     type: time
#     timeframes: [raw, time]
#     sql: ${TABLE}.event1_time ;;
#   }
# SQL SELECT outputs (Snowflake — explicit uppercase alias):  MIN(...) AS EVENT1_TIME

- name: Event1 Time
  sql_output_column: EVENT1_TIME
  data_type: DATE_TIME
  properties:
    column_type: ATTRIBUTE
    index_type: DONT_INDEX
```

### §5b-iii. Handle measures in a SQL View

LookML measures on a PDT view (e.g. `type: count_distinct`) should be expressed as
**model-level formulas in the Model TML** (Step 6) — **not** in the SQL View TML's own
`formulas:` block, and **not** pre-aggregated in the SQL query itself (that would make
the SQL View non-additive).

The SQL View TML exposes raw columns only. The model TML references those columns
using `[SQL_VIEW_NAME::Column Name]` format in its `formulas[]`:

```yaml
# In Events.model.tml — NOT in EVENT_SESSION_FUNNEL.sql_view.tml
formulas:
- id: formula_Session Count
  name: Session Count
  expr: unique count ( [EVENT_SESSION_FUNNEL::Session Id] )
  properties:
    column_type: MEASURE
- id: formula_Count Sessions Event1
  name: Count Sessions Event1
  expr: count_if ( not is_null ( [EVENT_SESSION_FUNNEL::Event1 Time] ) , [EVENT_SESSION_FUNNEL::Session Id] )
  properties:
    column_type: MEASURE
```

Column references in model `formulas[].expr` use `[SQL_VIEW_NAME::Column Name]` where:
- `SQL_VIEW_NAME` is the exact `name:` from the `sql_view:` block (case-sensitive)
- `Column Name` is the `name:` from `sql_view_columns[]` (display name, not `sql_output_column`)

Exception: if a measure is pre-computed as a SELECT alias in the PDT SQL (e.g. a
`total_revenue` column in the SELECT clause), expose it as a MEASURE column directly
in `sql_view_columns:` with `aggregation: SUM`.

### §5b-iv. SQL View TML template

```yaml
sql_view:
  name: {View Display Name}                 # Title Case from LookML view name
  connection:
    name: {connection_name}                 # same confirmed connection as all Table TMLs
  sql_query: |
    {adapted SQL — dialect-corrected, ${TABLE} resolved, PDT directives stripped}
  sql_view_columns:
  - name: {Display Name}                    # Title Case from dimension field name or label:
    sql_output_column: {select_alias}       # must match alias in sql_query SELECT clause
    data_type: {VARCHAR|INT64|DOUBLE|DATE|DATE_TIME|BOOL}   # optional — inferred if omitted
    properties:
      column_type: {ATTRIBUTE|MEASURE}
      index_type: DONT_INDEX                # apply to timestamp columns and hidden dims
  formulas:                                 # optional — for measures derived from SQL View columns
  - id: formula_{Measure Name}
    name: {Measure Name}
    expr: "{ThoughtSpot formula using [ViewName::ColumnName] refs}"
    properties:
      column_type: MEASURE
```

File naming: `{VIEW_NAME}.sql_view.tml` (e.g. `EVENT_SESSION_FUNNEL.sql_view.tml`)

### §5b-v. How the Model TML references a SQL View

In `model_tables[]`, a SQL View is referenced **by name** exactly like a physical Table.
No special syntax is needed — ThoughtSpot resolves it from the import batch:

```yaml
model_tables:
- name: EVENTS                            # physical Table
  joins:
  - with: EVENT_SESSION_FUNNEL            # SQL View — referenced by name
    'on': '[EVENTS::Session Id] = [EVENT_SESSION_FUNNEL::Session Id]'
    type: LEFT_OUTER
    cardinality: MANY_TO_ONE
- name: EVENT_SESSION_FUNNEL              # SQL View listed as a model_table entry too
```

`column_id:` references in the model use the SQL View name and its `sql_view_columns[]`
display name: `EVENT_SESSION_FUNNEL::Session Id`.

### §5b-vi. SQL View self-validation checklist

Before saving a SQL View TML:

- [ ] `sql_query:` SQL is valid for the **target warehouse dialect** (not the original Looker connection dialect)
- [ ] Every `sql_output_column` matches a column name or alias in the `sql_query:` SELECT clause
- [ ] All PDT directives stripped (`persist_with:`, `datagroup_trigger:`, `sql_trigger:`, `max_cache_age:`)
- [ ] `connection.name:` is present — SQL Views require it (unlike Table TMLs where it is also required)
- [ ] No `db:`, `schema:`, or `db_table:` fields — those belong to Table TML only
- [ ] No `search_query:` field — that belongs to `view:` (AGGR_WORKSHEET), not `sql_view:`
- [ ] `column_type:` is nested under `properties:` — not bare at column level
- [ ] No duplicate `name:` values across `sql_view_columns[]`
- [ ] If `formulas[]` present: every `id` follows `"formula_"` + name convention
- [ ] File extension is `.sql_view.tml`

---

## 5c. Column naming

Priority:
1. `label:` if present on the dimension/measure
2. Field name converted to Title Case (underscores → spaces)

Example: `customer_segment` → "Customer Segment"; `label: "Cust Segment"` → "Cust Segment"

## 5d. Column naming conflicts across joined tables

When multiple joined views expose the same field name, the flat `model.columns[]` list requires unique `name:` values. Apply this resolution order:

1. **Fact table columns** keep the simple name (e.g. `Created At`, `Cost`).
2. **Joined dim table columns** that conflict are **prefixed** with the table's label or view name: `Users Created At`, `Inventory Cost`.
3. If two dim tables conflict with each other (not the fact), prefix the less-primary one.

Common conflict patterns in multi-table e-commerce explores:

| Shared field | Fact-side | Joined dim | Joined dim #2 |
|---|---|---|---|
| `created_date` / `created_at` | `Created At` | `Users Created At` | `Inventory Created At` |
| `cost` | — | `Inventory Cost` | `Product Cost` |
| `name` | — | `Product Name` | `Distribution Center Name` |
| `id` (PK) | — | `User Id` (hidden) | `Product Id` (hidden) |

**Record every renaming in the migration gaps file** so analysts know the Looker `view.field` → ThoughtSpot model column name mapping. Example:
```
users.created_date → "Users Created At" (renamed to avoid conflict with order_items.created_date)
```

**Resolving the resolution table's own examples can introduce a *new* collision — check the final name set, not just the pairwise rule.** Applying rule 3 literally (e.g. `products.name` → `"Product Name"`) can collide with an unrelated field that already produces that exact string after its own Title-Case conversion (e.g. `inventory_items.product_name` → `"Product Name"` natively, with no conflict resolution needed). Compute the full set of resolved display names across *all* joined tables first, then re-check for new collisions the renaming itself created — don't treat the pairwise table above as terminal. When a second-order collision like this shows up, keep the field that has no conflict at its natural name, and prefix the *other* one with its view name instead (e.g. `inventory_items.product_name` → `"Inventory Product Name"`, freeing up `"Product Name"` for `products.name`).

## 5e. Measure name collisions across joined views

LookML views very commonly each define their own `measure: count { type: count }` — nearly every dimension view in a typical explore has one. Once these become ThoughtSpot model `formulas[]`, they hit the same uniqueness problem as `5d`, but for **formula display names**, not physical column names — `columns[]`/`formulas[].name` must be unique across the *entire* model (self-validation checklist item 8 in `thoughtspot-model-tml.md`), not just within one Table TML (where every view's own `Count` column is fine in isolation).

Apply the same view-name-prefix convention as `5d`, but for every joined view's measure, not just the fact's:

| LookML | Naive ThoughtSpot formula name | Resolved (unique) name |
|---|---|---|
| `order_items.order_item_count` (fact) | `Order Item Count` | `Order Item Count` (already distinct — keep) |
| `users.count` | `Count` | `Users Count` |
| `products.count` | `Count` | `Products Count` |
| `inventory_items.count` | `Count` | `Inventory Items Count` |
| `distribution_centers.count` | `Count` | `Distribution Centers Count` |

This applies independently in **each** model — the same physical table's `count` measure can resolve to the same name (e.g. `Users Count`) in two different models that both join `USERS`, since each Model TML's `formulas[]`/`columns[]` are scoped to that model only.

## 5f. Hidden dimension-table PKs also need unique names — not just when they collide with the fact

Per `6f` below, every joined dimension table's primary key is included in `model.columns[]` as a hidden `ATTRIBUTE` (so join-key columns resolve and RLS/drill can reference them). When a model joins **more than one** dimension table and each one's PK is plainly named `id` in LookML (a very common pattern — `id`, not `customer_id` or `user_id`), every one of them Title-Cases to the same display name `"Id"`. ThoughtSpot rejects duplicate display names across `columns[]` even when both entries have `is_hidden: true` — this collision is not limited to the "FK vs. dim PK" case already covered by `E2` Case B; it happens purely from having 2+ dim tables in the same model, with no fact-side field involved at all.

Give each dim table's hidden PK a table-prefixed name, e.g. for a model joining `USERS`, `INVENTORY_ITEMS`, `PRODUCTS`, and `DISTRIBUTION_CENTERS`: keep the first one plain (`"Id"` for `USERS`) and prefix the rest — `"Inventory Items Id"`, `"Products Id"`, `"Distribution Centers Id"`. As with `5d`/`5e`, record the mapping in the gaps file.
