# ThoughtSpot Answer TML — Structure Reference

How a saved ThoughtSpot Answer is represented in TML. Verified against a live instance
by exporting real Answers with formulas, parameters, and sets.

For Model TML construction, see [thoughtspot-model-tml.md](thoughtspot-model-tml.md).
For formula syntax, see [thoughtspot-formula-patterns.md](thoughtspot-formula-patterns.md).

---

## Full Answer TML Structure

```yaml
guid: "{answer_guid}"         # document root — same convention as Model TML
answer:
  name: "Answer Display Name"
  description: "Optional description"
  dynamic_name: "Auto-generated name"   # present when ThoughtSpot assigned the name
  dynamic_description: ""
  display_mode: TABLE_MODE              # TABLE_MODE or CHART_MODE

  tables:                               # data source references (Model, Worksheet, or Table)
  - id: "Data Source Display Name"
    name: "Data Source Display Name"
    fqn: "{data_source_guid}"           # GUID of the underlying Model or Worksheet

  search_query: "[Col1] [Col2] [formula_myformula] top 10"

  answer_columns:                       # columns shown in the answer (by display name)
  - name: "Revenue"
  - name: "Profit Margin"               # formula columns appear here by name
    format:                             # optional display formatting
      category: PERCENTAGE
      isCategoryEditable: true
      percentageFormatConfig:
        decimals: 2.0
  - name: "My Query Set"                # set columns (cohorts) also appear here

  formulas:                             # custom formula definitions
  - id: "formula_Profit Margin"         # convention: "formula_" + name (spaces preserved)
    name: "Profit Margin"
    expr: "[Revenue] - [Cost]"          # bare display-name references, no TABLE:: prefix
    was_auto_generated: false           # true = created by ThoughtSpot AI; false = user-created
  - id: "formula_YoY Growth"
    name: "YoY Growth"
    expr: "( [Revenue] - [Prior Year Revenue] ) / [Prior Year Revenue]"
    was_auto_generated: false
  - id: "formula_Auto Derived"
    name: "Auto Derived"
    expr: "( [Base Count] )"
    was_auto_generated: true            # auto-derived formulas added by ThoughtSpot automatically

  parameters:                           # answer-level runtime parameters
  - id: "e4f38863-78ac-459c-a1fa-245583b71d69"    # UUID assigned by ThoughtSpot
    name: "My Parameter"
    data_type: INT64                    # INT64 | DOUBLE | VARCHAR | DATE | BOOL
    default_value: "10"                 # always a string in TML regardless of data_type
    description: ""

  cohorts:                              # sets (column sets and query sets)
  - name: "Revenue Bins"
    owner: "analyst@company.com"
    config:
      anchor_column_id: Revenue         # column the set is based on
      cohort_type: SIMPLE
      cohort_grouping_type: BIN_BASED
      bins:
        minimum_value: 0.0
        maximum_value: 100.0
        bin_size: 10.0
    worksheet:
      id: "Model Display Name"
      name: "Model Display Name"
      fqn: "{model_guid}"

  - name: "Top 10 Products"
    owner: "analyst@company.com"
    config:
      anchor_column_id: Product ID
      cohort_type: ADVANCED             # ADVANCED = Query Set (embedded Answer)
      cohort_grouping_type: COLUMN_BASED
      hide_excluded_query_values: false
      pass_thru_filter:
        accept_all: true
      return_column_id: Product ID
    answer:                             # embedded search for the query set
      name: "Untitled"
      tables:
      - id: "Model Display Name"
        name: "Model Display Name"
        fqn: "{model_guid}"
      search_query: "top 10 [Amount] [Product ID]"
      answer_columns:
      - name: Product ID
      - name: Total Amount
      display_mode: TABLE_MODE
      table:
        client_state: ''
        ordered_column_ids: [Product ID, Total Amount]
        table_columns:
        - column_id: Product ID
          headline_aggregation: COUNT_DISTINCT
        - column_id: Total Amount
          headline_aggregation: SUM
    worksheet:
      id: "Model Display Name"
      name: "Model Display Name"
      fqn: "{model_guid}"

  table:                                # table visualization configuration
    client_state: ''
    client_state_v2: '{...}'            # opaque JSON blob for frontend state
    ordered_column_ids:
    - Revenue
    - Profit Margin
    table_columns:
    - column_id: Revenue
      headline_aggregation: SUM
    - column_id: Profit Margin
      headline_aggregation: TABLE_AGGR

  chart:                                # chart visualization configuration
    type: KPI                           # KPI | COLUMN | LINE | LINE_STACKED_COLUMN | etc.
    chart_columns:
    - column_id: Revenue
    - column_id: Profit Margin
    axis_configs:
    - y:
      - Revenue
    client_state: ''
    client_state_v2: '{...}'
```

---

## Field Reference

### Top-level

| Field | Required | Notes |
|---|---|---|
| `guid` | On update only | Document root — NOT inside `answer:`. Omit for new answers. |
| `answer.name` | Yes | Display name |
| `answer.description` | No | Optional |
| `answer.dynamic_name` | No | ThoughtSpot-assigned name — appears when the answer name was auto-generated |
| `answer.display_mode` | Yes | `TABLE_MODE` or `CHART_MODE` |
| `answer.tables` | Yes | One entry per data source. Most Answers have exactly one. |
| `answer.search_query` | Yes | ThoughtSpot search bar query string |
| `answer.answer_columns` | Yes | Columns shown in the answer — includes formulas, sets, and physical columns by display name |
| `answer.formulas` | No | Custom formula definitions (see below) |
| `answer.parameters` | No | Answer-level runtime parameters (see below) |
| `answer.cohorts` | No | Sets — column sets (bins/groups) and query sets (see below) |
| `answer.table` | No | Table visualization config (client state, column order, headlines) |
| `answer.chart` | No | Chart visualization config (chart type, axes, client state) |

### `tables[]` fields

| Field | Notes |
|---|---|
| `id` | Display name of the data source (Model or Worksheet) |
| `name` | Same as `id` |
| `fqn` | GUID of the underlying Model or Worksheet — use this to look up the data source |

Most Answers have exactly one entry. The GUID in `fqn` is the direct lookup key for
finding the Model in Step 5 of `ts-object-model-promote`.

### `formulas[]` fields

| Field | Required | Notes |
|---|---|---|
| `id` | Yes | `"formula_"` + name (spaces preserved, same as Model TML convention) |
| `name` | Yes | Display name |
| `expr` | Yes | ThoughtSpot formula expression |
| `was_auto_generated` | No | `true` = ThoughtSpot AI created it; `false` = user-created. Absent means unknown (treat as user-created). |

**No `column_type` or `aggregation` in Answer formula entries.** These properties live
on the underlying Model column, not the Answer formula. When promoting a formula to a
Model, you must infer or ask the user for `column_type` and `aggregation`.

**Column reference format in Answer formulas:** Bare display names (`[Revenue]`) or
formula IDs (`[formula_Vivun Deliverables Count(all)]`). Not the `[TABLE::column]`
format used internally in Models. See open-items.md #3 in `ts-object-model-promote` for
whether bare names work in Model formulas.

**Formula inter-references:** When a formula references another formula, the expression
uses the other formula's `id` (not its display name):
```
expr: "[formula_Count(successful)] / [formula_Count(all)]"
```
This means `[formula_X]` in an Answer expression is a formula reference, not a column
reference.

### `parameters[]` fields

Answer-level runtime parameters. Different from Model-level parameters — they are scoped
to this Answer only and are not reusable.

| Field | Notes |
|---|---|
| `id` | UUID assigned by ThoughtSpot |
| `name` | Display name — referenced in formulas as `[Parameter Name]` |
| `data_type` | `INT64`, `DOUBLE`, `VARCHAR`, `DATE`, `BOOL` |
| `default_value` | Always a string in TML regardless of `data_type` |
| `description` | Optional description |

**Promotion impact:** A formula that references `[Parameter Name]` (where `Parameter Name`
matches an entry in `parameters[]`) cannot be cleanly promoted to a Model. The Model would
need a matching parameter with the same name. Answer-level parameters cannot be promoted —
they are scoped to the Answer only.

### `cohorts[]` fields — Sets

Sets appear as `cohorts[]` in Answer TML and are also listed in `answer_columns[]` by name.
They are **not** `formulas[]` entries.

| Field | Notes |
|---|---|
| `name` | Display name — same name that appears in `answer_columns[]` |
| `owner` | Email of the user who created the set |
| `config.cohort_type` | `SIMPLE` = Column Set; `ADVANCED` = Query Set |
| `config.cohort_grouping_type` | `BIN_BASED`, `GROUP_BASED` (for SIMPLE); `COLUMN_BASED` (for ADVANCED) |
| `config.anchor_column_id` | The column the set is based on |
| `config.bins` | Bin-based set config: `minimum_value`, `maximum_value`, `bin_size` |
| `config.groups` | Group-based set config: named groups with conditions |
| `answer` | Query set only: embedded Answer that defines the set members |
| `worksheet` | Data source reference (id, name, fqn) |

**Answer-level vs reusable sets:**
- **Answer-level** (what appears in `cohorts[]` above): scoped to this Answer only.
  These cannot be used in other Answers.
- **Reusable sets**: standalone TML objects with a top-level `cohort:` key and their
  own GUID. These can be shared across Answers like Model columns.

Reusable set TML structure (separate file):
```yaml
guid: "{set_guid}"
cohort:
  name: "My Reusable Set"
  description: ""
  owner: "analyst@company.com"
  model:                         # or `models:` for multi-model sets
    id: "Model Display Name"
    name: "Model Display Name"
  config:
    # same config structure as answer-level cohorts
```

When an Answer uses a reusable set, the `cohorts[]` entry in the Answer TML will include
a GUID reference to the standalone set object.

### `answer_columns[]` fields

Lists all columns visible in the Answer by display name. Includes physical columns,
formula columns, and set columns (cohorts). No column_type or aggregation metadata here.

The only additional field is `format:` for display formatting (PERCENTAGE, NUMBER, etc.).

---

## Key Differences from Model TML

| Aspect | Answer TML | Model TML |
|---|---|---|
| Formula `column_type` | Absent — must infer when promoting | In `columns[].properties` |
| Formula `aggregation` | Absent — must infer when promoting | In `columns[].properties` (never in `formulas[]`) |
| Column references | Bare display name `[Revenue]` or formula ID `[formula_X]` | `[TABLE_NAME::col_name]` |
| Formula inter-refs | `[formula_formula_id]` using the id field | `[formula_name]` using the display name |
| Parameters | Answer-level, scoped to Answer | Model-level, reusable |
| Sets | `cohorts[]` — answer-level only | Not in Model TML (sets reference Models) |
| `was_auto_generated` | Present on formulas | Absent |
| Data source | `tables[].fqn` GUID | `model_tables[].fqn` GUID |

---

## Detecting Formula vs Set Columns

When parsing `answer_columns[]`, distinguish formula columns from set columns:

```python
formula_names = {f["name"] for f in answer.get("formulas", [])}
set_names     = {c["name"] for c in answer.get("cohorts", [])}

for col in answer.get("answer_columns", []):
    name = col["name"]
    if name in formula_names:
        kind = "formula"
    elif name in set_names:
        kind = "set"
    else:
        kind = "physical column"
```

---

## Detecting Parameter References in Formulas

A formula references an Answer-level parameter when its expression contains `[Name]`
where `Name` matches a `parameters[].name`:

```python
import re

param_names = {p["name"] for p in answer.get("parameters", [])}

def uses_parameter(expr, param_names):
    refs = re.findall(r'\[([^\]]+)\]', expr)
    return [r for r in refs if r in param_names]
```

Formulas with parameter references need special handling when promoting to a Model —
the Model must have a matching parameter, or the formula expression must be modified.
