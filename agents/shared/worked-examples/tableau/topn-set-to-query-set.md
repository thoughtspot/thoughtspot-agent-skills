# Worked Example — Tableau Top-N/Bottom-N Set → ThoughtSpot Query Set

Live-verified 2026-06-12 against `se-thoughtspot` (model `TEST_SV_DMSI_AI_CONTEXT`): the
structural ground truth TML (Customer State set) exported from a live ThoughtSpot instance.
See `ts-convert-from-tableau` Step 5b (Tableau Sets → Query-set TML emission) and the schema
`agents/shared/schemas/thoughtspot-sets-tml.md`.

A Tableau **Top-N or Bottom-N set** (a `<group>` whose `<groupfilter>` tree contains
`function='end'`) maps to a ThoughtSpot **query set** (`cohort_type: ADVANCED`,
`cohort_grouping_type: COLUMN_BASED`) with an embedded answer holding a rank formula +
a parameter-filter formula. The set's N is driven by a model parameter.

Source workbook: **B2VBWeek11** (`US_WINE_PRODUCTION` — columns `State`, `gallons`, `share`).

---

## Input — Tableau TWB XML

### The parameter (Top or Bottom N)

```xml
<column caption='Top or Bottom N' datatype='integer' default-value='10'
    name='[Parameters].[パラメーター 1]' param-domain-type='range' role='measure'
    type='quantitative' value='10'>
  <range granularity='5' max='25' min='5' />
</column>
```

Detection: `param-domain-type='range'` with a `<range granularity='5' min='5' max='25'/>` →
**stepped range** → `list_config` (enumerate 5 → 25 by step 5: `[5, 10, 15, 20, 25]`), NOT
`range_config`. This is the parameter that will drive the Top-N filter.

### State_TopN set

```xml
<group caption='State_TopN' name='[State_TopN]' name-style='unqualified'>
  <groupfilter function='end' end='top' count='[Parameters].[パラメーター 1]'>
    <groupfilter function='order' collation='default' direction='DESC'>
      <groupfilter expression='SUM([gallons-null-padded])' function='sum'
          level='[gallons-null-padded]' name='[gallons-null-padded]' />
      <groupfilter function='level-members' level='[State]' />
    </groupfilter>
  </groupfilter>
</group>
```

Detection: `function='end'`, `end='top'` → Top-N → `rank(..., 'desc')`.
- `count='[Parameters].[パラメーター 1]'` → **parameter-driven N → dynamic form** (rank +
  parameter-filter formula, N from the migrated model param `topN`). This example uses the
  dynamic form throughout. (A set with a *literal* `count`, e.g. `count='10'`, would instead use
  the simpler **static form** — `search_query: "top 10 [State] [gallons]"` (anchor dimension
  first, then measure), no formulas.)
- `direction='DESC'` + `SUM([gallons-null-padded])` → ordering measure is SUM of `gallons`
  (the `gallons-null-padded` is a null-padding wrapper — use the plain `gallons` column and
  **flag** the dropped nuance).
- `level='[State]'` → anchor/return column = `State`.

### State_BottomN set

```xml
<group caption='State_BottomN' name='[State_BottomN]' name-style='unqualified'>
  <groupfilter function='end' end='bottom' count='[Parameters].[パラメーター 1]'>
    <groupfilter function='order' collation='default' direction='DESC'>
      <groupfilter expression='SUM([gallons-null-padded])' function='sum'
          level='[gallons-null-padded]' name='[gallons-null-padded]' />
      <groupfilter function='level-members' level='[State]' />
    </groupfilter>
  </groupfilter>
</group>
```

Detection: `function='end'`, `end='bottom'` → Bottom-N → `rank(..., 'asc')`.
Everything else is the same as `State_TopN`.

---

## Output (1) — Migrated model parameter block

Add to the model TML's `parameters[]` (omit `id` — ThoughtSpot assigns on import):

```yaml
parameters:
- name: topN
  data_type: INT64
  default_value: '10'
  list_config:
    list_choice:
    - value: '5'
    - value: '10'
    - value: '15'
    - value: '20'
    - value: '25'
  description: ''
```

Note: `default_value` and all `list_choice[].value` entries are **strings** even though
`data_type` is `INT64` — ThoughtSpot requires string values in parameter TML (live-verified).

**Import order: model (with parameter) → cohort.** The set's formula references the
parameter, which must exist on the model before the cohort is imported.

---

## Output (2) — Query-set TML files

### `State_TopN.cohort.tml` — Top-N (rank desc)

```yaml
# guid omitted on first import (ThoughtSpot assigns one)
cohort:
  name: "State_TopN"
  answer:
    tables:
    - id: US_WINE_PRODUCTION
      name: US_WINE_PRODUCTION
      obj_id: US_WINE_PRODUCTION-<model-obj-id-prefix>
    table_paths:
    - id: US_WINE_PRODUCTION_1
      table: US_WINE_PRODUCTION
    formulas:
    - id: formula_filter
      name: filter
      expr: "[formula_rank] <= [US_WINE_PRODUCTION_1::topN] "
      was_auto_generated: false
    - id: formula_rank
      name: rank
      expr: "rank ( sum ( [US_WINE_PRODUCTION_1::gallons] ) , 'desc' )"
      properties:
        column_type: ATTRIBUTE
      was_auto_generated: false
    search_query: "[gallons] [State] [formula_rank] [formula_filter] = true"
    answer_columns:
    - name: State
    - name: Total gallons
    - name: rank
    table:
      table_columns:
      - column_id: State
        show_headline: false
      - column_id: Total gallons
        show_headline: false
      - column_id: rank
        show_headline: false
      ordered_column_ids:
      - State
      - rank
      - Total gallons
      client_state: ""
    display_mode: TABLE_MODE
  worksheet:
    id: US_WINE_PRODUCTION
    name: US_WINE_PRODUCTION
    obj_id: US_WINE_PRODUCTION-<model-obj-id-prefix>
  config:
    cohort_type: ADVANCED
    anchor_column_id: State
    return_column_id: State
    cohort_grouping_type: COLUMN_BASED
    hide_excluded_query_values: true
    group_excluded_query_values: "Excluded values"
    pass_thru_filter:
      accept_all: false
```

### `State_BottomN.cohort.tml` — Bottom-N (rank asc)

Identical to `State_TopN.cohort.tml` except:
- `cohort.name`: `"State_BottomN"`
- `formula_rank.expr`: `"rank ( sum ( [US_WINE_PRODUCTION_1::gallons] ) , 'asc' )"`
  — `'asc'` for Bottom-N (user-confirmed 2026-06-12).

```yaml
# guid omitted on first import
cohort:
  name: "State_BottomN"
  answer:
    tables:
    - id: US_WINE_PRODUCTION
      name: US_WINE_PRODUCTION
      obj_id: US_WINE_PRODUCTION-<model-obj-id-prefix>
    table_paths:
    - id: US_WINE_PRODUCTION_1
      table: US_WINE_PRODUCTION
    formulas:
    - id: formula_filter
      name: filter
      expr: "[formula_rank] <= [US_WINE_PRODUCTION_1::topN] "
      was_auto_generated: false
    - id: formula_rank
      name: rank
      expr: "rank ( sum ( [US_WINE_PRODUCTION_1::gallons] ) , 'asc' )"
      properties:
        column_type: ATTRIBUTE
      was_auto_generated: false
    search_query: "[gallons] [State] [formula_rank] [formula_filter] = true"
    answer_columns:
    - name: State
    - name: Total gallons
    - name: rank
    table:
      table_columns:
      - column_id: State
        show_headline: false
      - column_id: Total gallons
        show_headline: false
      - column_id: rank
        show_headline: false
      ordered_column_ids:
      - State
      - rank
      - Total gallons
      client_state: ""
    display_mode: TABLE_MODE
  worksheet:
    id: US_WINE_PRODUCTION
    name: US_WINE_PRODUCTION
    obj_id: US_WINE_PRODUCTION-<model-obj-id-prefix>
  config:
    cohort_type: ADVANCED
    anchor_column_id: State
    return_column_id: State
    cohort_grouping_type: COLUMN_BASED
    hide_excluded_query_values: true
    group_excluded_query_values: "Excluded values"
    pass_thru_filter:
      accept_all: false
```

---

## Structural ground truth — verified Customer State set export

The TML below was exported from a live ThoughtSpot instance on se-thoughtspot (model
`TEST_SV_DMSI_AI_CONTEXT`, 2026-06-12). It confirms the rank + filter formula structure,
`table_paths`, `show_headline: false`, `cohort_type: ADVANCED`, `cohort_grouping_type:
COLUMN_BASED`, `hide_excluded_query_values`, `group_excluded_query_values`,
`pass_thru_filter.accept_all: false`, and binding via `worksheet:`.

```yaml
guid: 224998d4-7ed9-454c-bb61-085ab3cfd246          # OMIT on first import
obj_id: CustomerStateset-224998d4
cohort:
  name: Customer State set
  answer:
    tables:
    - id: TEST_SV_DMSI_AI_CONTEXT
      name: TEST_SV_DMSI_AI_CONTEXT
      obj_id: TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY_AI_CONTEXT-889a704f
    table_paths:
    - id: TEST_SV_DMSI_AI_CONTEXT_1
      table: TEST_SV_DMSI_AI_CONTEXT
    formulas:
    - id: formula_filter
      name: filter
      expr: "[formula_rank] <= [TEST_SV_DMSI_AI_CONTEXT_1::topN] "
      was_auto_generated: false
    - id: formula_rank
      name: rank
      expr: "rank ( sum ( [TEST_SV_DMSI_AI_CONTEXT_1::Amount] ) , 'desc' )"
      properties:
        column_type: ATTRIBUTE
      was_auto_generated: false
    search_query: "[Amount] [Customer State] [formula_rank] [formula_filter] = true"
    answer_columns:
    - name: Customer State
    - name: Total Amount
    - name: rank
    table:
      table_columns:
      - column_id: Customer State
        show_headline: false
      - column_id: Total Amount
        show_headline: false
      - column_id: rank
        show_headline: false
      ordered_column_ids:
      - Customer State
      - rank
      - Total Amount
      client_state: ""
    display_mode: TABLE_MODE
  owner: damian.waldron@thoughtspot.com
  worksheet:
    id: TEST_SV_DMSI_AI_CONTEXT
    name: TEST_SV_DMSI_AI_CONTEXT
    obj_id: TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY_AI_CONTEXT-889a704f
  config:
    cohort_type: ADVANCED
    anchor_column_id: Customer State
    return_column_id: Customer State
    cohort_grouping_type: COLUMN_BASED
    hide_excluded_query_values: true
    group_excluded_query_values: Excluded values
    pass_thru_filter:
      accept_all: false
```

### Consuming the set in an Answer

```yaml
answer:
  search_query: "[Amount] [Customer State set]"
  answer_columns:
  - name: Customer State set
  - name: Total Amount
```

---

## Dropped nuances — flagged for review

The B2VBWeek11 workbook has the following nuances that are **dropped** in translation
(flag each in the Step 7 review and Step 12 report):

| Tableau feature | What was dropped | Flag text |
|---|---|---|
| `gallons-null-padded` ordering measure | Null-padding on the ordering measure was dropped; using plain `gallons` | "Dropped null-padding on ordering measure — verify ranking matches the Tableau set" |
| California include/exclude condition | The extra conditional exclude on California was dropped | "Dropped California exclude condition — verify set membership" |
| Top/Bottom toggle param (a separate P3 parameter) | The toggle-between-top-and-bottom logic was not migrated | "Two separate sets (State_TopN and State_BottomN) replace the Tableau toggle — verify which set is used where" |

---

## Gotchas

- **`worksheet:` not `model:`** — same rule as column sets (live-verified). `model:` fails
  with `"Invalid save request, Table cant be empty"`.
- **`table_paths` alias** — all formula `expr` column refs use `[<alias>::<col>]` where
  alias = `<model display name>_1`. `answer_columns`, `config`, and `table.*` use plain
  display names (no alias prefix).
- **`answer_columns` measure name** — ThoughtSpot generates the aggregated display name
  `Total <measure>` for a SUM formula. Use that exact string (e.g. `Total gallons`).
- **`show_headline: false`** — required on all `table.table_columns[]` (live-verified).
- **Model parameter must exist first** — import the model (with `parameters[]`) before the
  cohort. The set's `formula_filter` references the parameter; importing the cohort first
  fails with a missing-column error.
- **Stepped range → `list_config`** — `range_config` cannot express the step size; enumerate
  the choices explicitly as `list_choice[]` values (strings even for INT64 params).
- **No top-level `guid` on first import** — ThoughtSpot assigns the GUID. Export the cohort
  after import to get the GUID for re-import in place.
