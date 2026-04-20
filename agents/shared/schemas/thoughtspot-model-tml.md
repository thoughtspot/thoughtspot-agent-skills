# ThoughtSpot Model TML — Construction Reference

How to construct a valid ThoughtSpot Model TML for import via the REST API or
stored procedures. Platform-agnostic — applies to any source (Snowflake, Databricks,
Redshift, standalone model creation, etc.).

For Table TML construction, see [thoughtspot-table-tml.md](thoughtspot-table-tml.md).
For parsing exported TML, see [thoughtspot-tml.md](thoughtspot-tml.md).

---

## Full Model TML Structure

```yaml
guid: "{existing_guid}"        # document root — omit on first import; required to update in-place
model:
  name: MODEL_NAME
  description: "Optional description"
  model_tables:
  - name: FACT_TABLE            # exact ThoughtSpot table object name
    fqn: "{table_guid}"         # GUID of the ThoughtSpot table object
    joins:                      # inline joins — only on the FROM (source) table entry
    - with: DIM_TABLE           # must equal the `name:` of the target entry (case-sensitive)
      'on': '[FACT_TABLE::FK_COL] = [DIM_TABLE::PK_COL]'
      type: INNER
      cardinality: MANY_TO_ONE
  - name: DIM_TABLE
    fqn: "{dim_guid}"
    referencing_join: "join_name_from_table_tml"   # Scenario A only — see below
  # Same physical table used twice: give each entry a different alias
  # - name: LOT_DRUGS
  #   alias: LOT_DRUGS_1
  #   fqn: "{guid}"
  # - name: LOT_DRUGS
  #   alias: LOT_DRUGS_2
  #   fqn: "{guid}"
  columns:
  - name: "Display Name"
    column_id: FACT_TABLE::COL_NAME   # TABLE_NAME::col_name — table name (or alias) from model_tables
    properties:
      column_type: ATTRIBUTE    # ATTRIBUTE or MEASURE
  - name: "Revenue"
    column_id: FACT_TABLE::AMOUNT
    properties:
      column_type: MEASURE
      aggregation: SUM
      format_pattern: "#,##0"   # optional display format
      currency_type:
        iso_code: USD           # optional — adds currency symbol
  - name: "FK Column"
    column_id: FACT_TABLE::CUSTOMER_ID
    properties:
      column_type: ATTRIBUTE
      is_hidden: true           # optional — hide FK columns from search bar
  - name: "Order Count"
    formula_id: formula_Order Count   # references a formulas[] entry by its id
    properties:
      column_type: MEASURE
      aggregation: COUNT
      index_type: DONT_INDEX
  formulas:
  - id: formula_Order Count         # id format: "formula_" + name (spaces preserved)
    name: "Order Count"
    expr: "count ( [FACT_TABLE::ORDER_ID] )"
  properties:
    is_bypass_rls: false
    join_progressive: true
    spotter_config:
      is_spotter_enabled: true
```

---

## Field Reference

### Top-level fields

| Field | Required | Notes |
|---|---|---|
| `guid` | On update only | Document root — NOT inside `model:`. Omit on first import. |
| `model.name` | Yes | Display name in ThoughtSpot |
| `model.description` | No | Optional description |
| `model.model_tables` | Yes | One entry per physical ThoughtSpot table |
| `model.columns` | Yes | One entry per visible column/formula in the model |
| `model.formulas` | No | Formula definitions — each must have a matching `columns[]` entry |
| `model.parameters` | No | Runtime input parameters — referenced in formula `expr` as `[Param Name]` |
| `model.filters` | No | Model-level pre-filters applied before any query |
| `model.joins_with` | No | Data augmentation joins at the model level (e.g. joining an uploaded CSV to the model) |
| `model.properties` | No | Model-level settings |

### `model_tables[]` fields

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Exact ThoughtSpot table object name — case-sensitive, copy verbatim |
| `alias` | No | When the same physical table appears more than once (e.g. self-join or two roles for one dim), assign a unique alias per entry. `column_id` then uses the alias as the table prefix: `LOT_DRUGS_1::MOLECULE`. |
| `fqn` | Yes on first import | GUID of the ThoughtSpot table object. After ThoughtSpot processes the TML, it replaces `fqn` with `obj_id`. |
| `obj_id` | After round-trip | ThoughtSpot-assigned content ID (e.g. `DM_ORDER-924f10e2`) — appears after export; use `fqn` on import |
| `id` | No | When present, must equal `name` exactly (same case). ThoughtSpot uses `name` as the join reference target when `id` is absent. Omitting `id` is simpler. |
| `joins` | No | Inline joins FROM this table. Lives on the source (FK) table entry only. |
| `referencing_join` | No | Scenario A only — name of a pre-defined join in the ThoughtSpot Table TML. System-inferred joins have auto-generated names like `SYS_CONSTRAINT_<uuid>`. |

### `joins[]` fields (inline joins on `model_tables` entry)

| Field | Required | Notes |
|---|---|---|
| `with` | Yes | Must equal the `name:` of the target `model_tables[]` entry exactly (case-sensitive) |
| `on` | Yes | Quote with `'on':` — `on` is a YAML reserved word. Format: `[FROM::fk] = [TO::pk]` |
| `type` | Yes | `INNER`, `LEFT_OUTER`, `RIGHT_OUTER`, `FULL_OUTER`, or `OUTER` (bare — legacy/internal ThoughtSpot value seen on referencing_join style) |
| `cardinality` | Yes | `MANY_TO_ONE` for most fact-to-dimension joins |

### `columns[]` fields

| Field | One of | Notes |
|---|---|---|
| `column_id` | Physical column | Format: `TABLE_NAME::col_name` — TABLE_NAME is the `name:` (or `alias:`) from model_tables |
| `formula_id` | Formula reference | Must match a `formulas[].id` exactly (case-sensitive, spaces included) |
| `name` | Yes (always) | Display name shown in ThoughtSpot search bar |
| `properties.column_type` | Yes | `ATTRIBUTE` or `MEASURE` |
| `properties.aggregation` | No | For MEASURE: `SUM`, `COUNT`, `AVERAGE`, `MIN`, `MAX`, `COUNT_DISTINCT`. Valid on both `column_id` and `formula_id` entries. |
| `properties.index_type` | No | `DONT_INDEX` suppresses text-search indexing. `PREFIX_ONLY` indexes only the string prefix (faster prefix search on long strings). Omit for full indexing (default). |
| `properties.is_hidden` | No | `true` hides the column from the search bar. Use for FK columns and RLS key columns. |
| `properties.is_additive` | No | `true` marks a column as additive — used on semi-additive models to explicitly allow summation across time. |
| `properties.format_pattern` | No | Number display format string. Common values: `"#,##0"` (integer), `"#,##0.0%"` (percentage), `"###0"` (plain). |
| `properties.currency_type.iso_code` | No | ISO currency code (e.g. `USD`, `EUR`) — adds currency symbol and formatting to a measure. |
| `properties.geo_config` | No | Geographic role for the column. See Geo Config below. |
| `properties.spotiq_preference` | No | `"EXCLUDE"` removes the column from SpotIQ auto-analysis (use on lat/long, internal IDs). |
| `properties.search_iq_preferred` | No | `true` flags this column as preferred in Search IQ / natural language queries. |
| `synonyms` | No | Array of alternative names for search. May include `synonym_type: "AUTO_GENERATED"` on auto-inferred synonyms. |

### `formulas[]` fields

| Field | Required | Notes |
|---|---|---|
| `id` | Recommended | Referenced by `columns[].formula_id`. Format: `formula_` + name (spaces preserved). |
| `name` | Yes | Display name |
| `expr` | Yes | ThoughtSpot formula expression. Use `>-` block scalar if expression contains `{ }` curly braces. |
| `properties.column_type` | No | `ATTRIBUTE` or `MEASURE`. Optional in the `formulas[]` entry itself. |

**Never add `aggregation:` to a `formulas[]` entry** — formulas are self-contained through
their `expr`. Adding `aggregation:` causes `FORMULA is not a valid aggregation type`.
Add `aggregation:` to the corresponding `columns[]` entry instead.

**`aggregation:` on formula `columns[]` entries is ignored at query time.** ThoughtSpot
evaluates the formula `expr` directly — the column-level `aggregation` does not re-aggregate
the result. Use `SUM` as the convention for all MEASURE formula columns; do not attempt to
infer a "correct" aggregation from the expression shape (e.g. ratio vs. sum).

### Geo Config

Assign a geographic role so ThoughtSpot can render map charts:

```yaml
# Latitude
properties:
  geo_config:
    latitude: true
  spotiq_preference: "EXCLUDE"   # exclude raw lat/long from auto-analysis

# Longitude
properties:
  geo_config:
    longitude: true
  spotiq_preference: "EXCLUDE"

# Named region (state, zip, county, city, country)
properties:
  geo_config:
    region_name:
      country: "UNITED STATES"
      region_name: "state"   # state | zip code | county | city | country
```

### `properties` fields

| Field | Default | Notes |
|---|---|---|
| `is_bypass_rls` | false | Set true to bypass row-level security |
| `join_progressive` | true | ThoughtSpot execution hint — always set true |
| `spotter_config.is_spotter_enabled` | true | Enables Spotter (AI search) for this model |

### `parameters[]` fields

Runtime input parameters that users can set at query time. Referenced in `formulas[].expr` using bracket notation: `[Parameter Name]` (same syntax as a column reference but with no `TABLE::` prefix).

```yaml
parameters:
- id: "4aa0677f-b1e6-40c2-a33e-7da656820710"  # UUID assigned by ThoughtSpot
  name: FTE Hourly Rate
  data_type: INT64        # INT64 | DOUBLE | DATE | VARCHAR
  default_value: "40"    # always a string in TML regardless of data_type
  description: ""
```

Parameter references in formula expressions: `[FTE Hourly Rate]` — no `TABLE::` separator. ThoughtSpot resolves these at query time. Parameters with no `TABLE::` prefix are untranslatable to Snowflake Semantic View SQL (no runtime parameter equivalent).

### `filters[]` fields

Model-level pre-filters applied before any query. Column references use display name (not `column_id`).

```yaml
filters:
- column:
  - "Query Stats Is System"   # display name of the column to filter on
  oper: in                    # in | not_in | between | eq | ne | lt | le | gt | ge
  values:
  - "false"

# Range filter
- column:
  - "Order Date"
  oper: between
  values:
  - "03/01/2000"
  - "03/01/2025"

# Formula-backed boolean filter
- column:
  - "wsFilter"               # formula column name (boolean expression)
  oper: in
  values:
  - "true"
```

### `joins_with[]` at model level

Data augmentation joins — used to join an uploaded CSV or external dataset directly to the model. Distinct from `model_tables[].joins[]`. Includes an `is_one_to_one` flag.

```yaml
joins_with:
- name: "ModelName_to_UploadedDataset"
  destination:
    name: "Demo set - Department Budgets"
    fqn: "{table_guid}"
  'on': "[ModelName::department] = [Demo set - Department Budgets::Department]"
  type: LEFT_OUTER
  is_one_to_one: true
```

---

## GUID and Updates

**`guid` at document root — never inside `model:`:**

```yaml
guid: "{existing_model_guid}"   # MUST be first key in the document
model:
  name: MODEL_NAME
  # ...
```

`guid` nested under `model:` (e.g. `model: { guid: ... }`) is **silently ignored** —
ThoughtSpot creates a new duplicate object with the same name. This is the most common
cause of "update creates a new model" failures.

**First import:** omit `guid`. After import, record the GUID from the response.

**Finding an existing GUID:**
```bash
ts metadata search --subtype WORKSHEET --name '%{model_name}%' --profile {profile}
```

**Deleting a duplicate:**
```bash
ts metadata delete {wrong_guid} --profile {profile}
```

---

## Join Scenarios

### Scenario A — Pre-defined joins (Table TML has `joins_with`)

Use when the ThoughtSpot Table objects already have `joins_with` entries defined.
The model references these joins by name via `referencing_join`:

```yaml
model_tables:
- name: FACT_TABLE
  fqn: "{fact_guid}"
- name: DIM_TABLE
  fqn: "{dim_guid}"
  referencing_join: "FACT_TABLE_to_DIM_TABLE"  # name from Table TML's joins_with[]
```

To find the join name: export the FROM table's TML → find `joins_with[]` → match entry
where `destination.name` equals the TO table name → use that entry's `name` value.

### Scenario B — Inline joins (no pre-defined joins, or new table objects)

Use when Table objects have no `joins_with`, or when tables were just created and
have no pre-defined joins. The `joins:` array lives on the source (FK) table entry:

```yaml
model_tables:
- name: FACT_TABLE        # FK side — joins array goes here
  fqn: "{fact_guid}"
  joins:
  - with: DIM_TABLE       # target table's name:
    'on': '[FACT_TABLE::FK_COL] = [DIM_TABLE::PK_COL]'
    type: INNER
    cardinality: MANY_TO_ONE
- name: DIM_TABLE         # PK side — no joins array
  fqn: "{dim_guid}"
```

**`joins:` at model top level causes "destination is missing" error.** Always nest
inside the source table's `model_tables[]` entry.

---

## Formula Visibility

**Every formula must appear in `columns[]`** via `formula_id:` — formulas defined in
`formulas[]` but not referenced in `columns[]` are not surfaced in the model.

```yaml
formulas:
- id: formula_Revenue            # step 1: define the formula
  name: "Revenue"
  expr: "sum ( [DM_ORDER_DETAIL::LINE_TOTAL] )"

- id: formula_Inventory Balance
  name: "Inventory Balance"
  expr: >-                        # >- required when expr contains { } curly braces
    last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )

columns:
- name: "Revenue"                 # step 2: surface it as a column
  formula_id: formula_Revenue
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX

- name: "Inventory Balance"
  formula_id: formula_Inventory Balance
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX
```

`formula_id` must match the formula's `id` exactly — case-sensitive, spaces included.

---

## `column_id` Construction

Format: `TABLE_NAME::col_name`

- `TABLE_NAME` is the `name:` value from the corresponding `model_tables[]` entry
- `col_name` is the column's `name` from the **ThoughtSpot Table TML** (which may differ
  from the physical warehouse column name if the table was created with a display name)

Always export and read the Table TML to get authoritative column names — never guess
from the warehouse schema alone.

---

## Self-Validation Checklist

Run before every import. Fix all issues silently before showing the user.

| # | Check | What to verify |
|---|---|---|
| 1 | YAML validity | Parse the TML string; no syntax errors |
| 2 | `model_tables[].name` | Every name is the exact ThoughtSpot table object name (case-sensitive) |
| 3 | `referencing_join` values | Every value matches a join name from the exported Table TML |
| 4 | `column_id` table prefix | Each prefix (before `::`) matches a `name:` or `alias:` in `model_tables[]` |
| 5 | `column_id` column suffix | Each suffix (after `::`) matches a column name in the ThoughtSpot Table TML |
| 6 | No duplicate `column_id` | No two `columns[]` entries share the same `column_id` |
| 7 | No `aggregation:` on formulas | No `formulas[]` entry has an `aggregation:` field |
| 8 | No duplicate display names | Every `name` across `columns[]` and `formulas[]` is unique |
| 9 | `column_type` placement | Where present on columns, `column_type` is under `properties:` — not bare |
| 10 | Every formula in `columns[]` | Every `formulas[].id` has a matching `formula_id:` in `columns[]` |
| 11 | `last_value` YAML encoding | Any formula `expr` containing `{ }` uses `>-` block scalar |
| 12 | `guid` placement | If updating, `guid` is at document root — not inside `model:` |

---

## Common Import Errors

| Error | Cause | Fix |
|---|---|---|
| `duplicate column_id` | Same `column_id` in two `columns[]` entries | Convert the COUNT_DISTINCT duplicate to a formula: `unique count ( [TABLE::col] )` |
| `referencing_join not found` | Join name wrong or join doesn't exist at the Table object level | Re-export the Table TML and verify the join name |
| `column_id not found` | Wrong column name suffix | Export Table TML and use the exact `name` from `table.columns[]` |
| `destination is missing` | `joins:` placed at model top level instead of inside a `model_tables[]` entry | Move joins inside the FROM table's entry |
| `{table_name} does not exist in schema` | `with:` value doesn't match any `name:` in `model_tables[]` | Copy the target table's `name:` verbatim |
| `Compulsory Field … joins(N)->with is not populated` | Missing `with:` field on a join | Add `with: {target_name}` to every join |
| `No enum constant ColumnTypeEnum` | `column_type:` is bare (not under `properties:`) | Nest: `properties: column_type: ATTRIBUTE` |
| `FORMULA is not a valid aggregation type` | `aggregation:` set on a `formulas[]` entry | Remove `aggregation:` from formulas — put it on the `columns[]` entry instead |
| `duplicate column name {name}` | Two columns/formulas share the same display `name` | FK columns often duplicate PK column names — prefix: "Order Customer Id" vs "Customer Id" |
| `Multiple tables have same alias` | Two `model_tables[]` entries share the same `name` with no `alias` | Add distinct `alias:` values when the same table appears more than once |
| `fqn resolution failed` | GUID is stale or from a different instance | Re-retrieve the GUID for the table |
| YAML mapping error on formula | Formula `expr` with `{ }` written as inline string | Use `>-` block scalar for the `expr` value |
| YAML parse error | Non-printable characters in strings | Strip non-printable chars before serialising |
