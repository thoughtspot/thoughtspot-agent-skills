# ThoughtSpot Sets TML — Structure Reference

How ThoughtSpot sets (cohorts) are represented in TML. Sets are custom column groupings —
bins, value groups, or query-based filters — that appear as columns in Answers and Liveboards.

Sets are documented in the ThoughtSpot docs at
[docs.thoughtspot.com — TML Sets](https://docs.thoughtspot.com/cloud/26.4.0.cl/tml-sets).

For how sets appear inside Answer TML (as `cohorts[]`), see
[thoughtspot-answer-tml.md](thoughtspot-answer-tml.md).

---

## Column set vs query set (official ThoughtSpot terms)

- **Column set** — scalar, single-column categorization. TML: `cohort.config.cohort_type: SIMPLE`
  with `cohort_grouping_type: BIN_BASED` or `GROUP_BASED`. No aggregation/ranking.
- **Query set** — aggregation/ranking across columns. TML: `cohort_type: ADVANCED` with an embedded
  `cohort.answer{}` (search_query + answer_columns + table) and `groups` over aggregated columns.

Docs: cloud/latest/column-sets, query-sets, tml-sets.

---

## Two Set Scopes

| Scope | Where defined | Who can use it |
|---|---|---|
| **Answer-level** | `answer.cohorts[]` inline in the Answer TML | That Answer only |
| **Reusable** | Standalone TML with top-level `cohort:` key and GUID | Any Answer on the linked Model |

Answer-level sets are exported as part of their parent Answer (they have no independent
GUID). Reusable sets have their own GUID and can be exported, imported, and shared.

---

## Reusable Set TML

The examples below cover all three `cohort_grouping_type` values. `BIN_BASED` and
`GROUP_BASED` are **column sets** (`cohort_type: SIMPLE`). `COLUMN_BASED` is a
**query set** (`cohort_type: ADVANCED`).

```yaml
guid: "{set_guid}"              # document root — omit on first import
cohort:
  name: "My Reusable Set"
  description: "Optional description"
  owner: "analyst@company.com"

  worksheet:                    # data-source binding — use `worksheet:`, NOT `model:`
    id: "Model Display Name"    # (live-verified 26.6.0: `model:` fails import with
    name: "Model Display Name"  #  "Invalid save request, Table cant be empty")
    obj_id: "MODEL_OBJ_ID-<guidprefix>"   # stable object id from the model's exported TML header
  # Multi-model sets: repeat under `worksheets:` (list of {id, name, obj_id}).

  config:
    anchor_column_id: Revenue   # column the set operates on
    cohort_type: SIMPLE | ADVANCED
    cohort_grouping_type: BIN_BASED | GROUP_BASED | COLUMN_BASED

    # --- BIN_BASED (column set — cohort_type: SIMPLE, continuous ranges) ---
    bins:
      minimum_value: 0.0
      maximum_value: 100.0
      bin_size: 10.0

    # --- GROUP_BASED (column set — cohort_type: SIMPLE, named value groups) ---
    groups:
    - name: "High Value"
      conditions:
      - operator: GT
        value: [1000]
        column_name: Revenue
      - operator: BW
        value: [500, 999]
        column_name: Revenue
      combine_type: ANY    # ALL or ANY
    null_output_value: "Unknown"         # label for unmatched rows
    combine_non_group_values: true       # group remaining rows into "Other"
    group_excluded_query_values: "Other" # label for the combined remainder group

    # --- COLUMN_BASED (query set — cohort_type: ADVANCED, results of an embedded search) ---
    # Two forms, by whether N is fixed or parameter-driven:
    #  • STATIC N (fixed): the embedded answer's search_query is a plain "top N …" / "bottom N …"
    #    keyword search — no formulas, no parameter. Anchor dimension FIRST, then measure
    #    (e.g. search_query: "top 10 [Customer State] [Amount]"). Live-verified 2026-06-12.
    #  • DYNAMIC N (parameter-driven): a rank formula + parameter-filter formula, with N read from a
    #    model parameter. Live-verified 2026-06-12 (se-thoughtspot, model TEST_SV_DMSI_AI_CONTEXT). Shown below.
    # (use cohort_type: ADVANCED, cohort_grouping_type: COLUMN_BASED for this config)
    return_column_id: Customer State   # the column whose values define set membership
    hide_excluded_query_values: true
    group_excluded_query_values: "Excluded values"
    pass_thru_filter:
      accept_all: false
      # OR selectively:
      # include_column_ids: [col_id_1]
      # exclude_column_ids: [col_id_2]

  answer:                               # COLUMN_BASED (query set) only
    tables:
    - id: "Model Display Name"
      name: "Model Display Name"
      obj_id: "MODEL_OBJ_ID-<guidprefix>"
    table_paths:
    - id: "Model Display Name_1"        # self-path alias — used by ALL formula refs
      table: "Model Display Name"
    formulas:
    - id: formula_filter
      name: filter
      expr: "[formula_rank] <= [Model Display Name_1::topN] "   # or "<= N" for a literal count
      was_auto_generated: false
    - id: formula_rank
      name: rank
      expr: "rank ( sum ( [Model Display Name_1::Amount] ) , 'desc' )"   # 'asc' for Bottom-N
      properties:
        column_type: ATTRIBUTE
      was_auto_generated: false
    search_query: "[Amount] [Customer State] [formula_rank] [formula_filter] = true"
    answer_columns:
    - name: Customer State
    - name: Total Amount
    - name: rank
    display_mode: TABLE_MODE
    table:
      client_state: ""
      ordered_column_ids:
      - Customer State
      - rank
      - Total Amount
      table_columns:
      - column_id: Customer State
        show_headline: false
      - column_id: Total Amount
        show_headline: false
      - column_id: rank
        show_headline: false
```

---

## Answer-Level Set (inline in Answer TML)

When a set is answer-level (not reusable), it appears in `answer.cohorts[]` without a
GUID. The structure is the same as the `cohort:` body above, minus the `worksheet:`
binding (the model is inherited from the Answer's `tables[]`).

The example below is a **column set** (`cohort_type: SIMPLE`, `cohort_grouping_type: BIN_BASED`).

```yaml
# Inside answer.cohorts[]
- name: "Revenue Bins"
  owner: "analyst@company.com"
  config:
    anchor_column_id: Revenue
    cohort_type: SIMPLE
    cohort_grouping_type: BIN_BASED
    bins:
      minimum_value: 0.0
      maximum_value: 100.0
      bin_size: 10.0
  worksheet:                    # data source reference (Answer-level sets use "worksheet")
    id: "Model Display Name"
    name: "Model Display Name"
    fqn: "{model_guid}"
```

---

## Field Reference

### `config` fields

| Field | Required | Notes |
|---|---|---|
| `anchor_column_id` | Yes | The column this set groups or filters |
| `cohort_type` | Yes | `SIMPLE` = column set (bins or groups); `ADVANCED` = query set |
| `cohort_grouping_type` | Yes | `BIN_BASED` or `GROUP_BASED` (for SIMPLE); `COLUMN_BASED` (for ADVANCED) |

**BIN_BASED config:**

| Field | Notes |
|---|---|
| `bins.minimum_value` | Lowest bin boundary (inclusive) |
| `bins.maximum_value` | Highest bin boundary (exclusive upper bound) |
| `bins.bin_size` | Width of each bin |

**GROUP_BASED config:**

| Field | Notes |
|---|---|
| `groups[].name` | Display label for this group |
| `groups[].conditions[]` | Filter conditions that define group membership |
| `groups[].conditions[].operator` | `EQ`, `NE`, `GT`, `GE`, `LT`, `LE`, `BW` (between), `IN`, `NOT_IN` |
| `groups[].conditions[].value[]` | One or two values depending on operator |
| `groups[].conditions[].column_name` | Column being tested (usually same as `anchor_column_id`) |
| `groups[].combine_type` | `ALL` (AND) or `ANY` (OR) across conditions |
| `null_output_value` | Label for rows that don't match any group |
| `combine_non_group_values` | If `true`, unmatched rows are grouped into one bucket |
| `group_excluded_query_values` | Label for the combined remainder group |

**COLUMN_BASED (Query Set) config:**

| Field | Notes |
|---|---|
| `anchor_column_id` | The dimension whose values define set membership |
| `return_column_id` | Same as `anchor_column_id` for a standard Top-N/Bottom-N set |
| `hide_excluded_query_values` | `true` hides rows not in the set from the Answer (use `true` for Top-N) |
| `group_excluded_query_values` | Label for the excluded/remainder group (e.g. `"Excluded values"`) |
| `pass_thru_filter.accept_all` | If `true`, all outer query filters apply to the embedded search; use `false` for Top-N |
| `pass_thru_filter.include_column_ids` | Only these columns' filters are passed through |
| `pass_thru_filter.exclude_column_ids` | These columns' filters are blocked |

### `answer` section (query sets only — COLUMN_BASED)

Contains a full embedded Answer whose results define the set members. Two forms:
- **Static N (fixed):** `search_query: "top N [dimension] [measure]"` (or `"bottom N …"`) — a
  plain keyword search, anchor dimension first then measure, no formulas, no parameter. Correct
  for a fixed N (live-verified 2026-06-12, set "Static Top 10").
- **Dynamic N (parameter-driven):** a rank formula + parameter-filter formula, with N read from
  a model parameter (live-verified 2026-06-12 on se-thoughtspot). This is the form shown above;
  it stays in sync as the user changes the parameter.

**Static query set — verified export** (set "Static Top 10", se-thoughtspot, model
`TEST_SV_DMSI_AI_CONTEXT`, 2026-06-12). Note the `search_query` order: **anchor dimension first,
then measure**.

```yaml
# guid/obj_id omitted on first import
cohort:
  name: Static Top 10
  answer:
    tables:
    - id: TEST_SV_DMSI_AI_CONTEXT
      name: TEST_SV_DMSI_AI_CONTEXT
      obj_id: TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY_AI_CONTEXT-889a704f
    search_query: "top 10 [Customer State] [Amount]"
    answer_columns:
    - name: Customer State
    - name: Total Amount
    table:
      table_columns:
      - column_id: Customer State
        show_headline: false
      - column_id: Total Amount
        show_headline: false
      ordered_column_ids:
      - Customer State
      - Total Amount
      client_state: ""
    display_mode: TABLE_MODE
  worksheet:
    id: TEST_SV_DMSI_AI_CONTEXT
    name: TEST_SV_DMSI_AI_CONTEXT
    obj_id: TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY_AI_CONTEXT-889a704f
  config:
    cohort_type: ADVANCED
    anchor_column_id: Customer State
    return_column_id: Customer State
    cohort_grouping_type: COLUMN_BASED
    hide_excluded_query_values: false        # false → show "Others" remainder bucket; true → hide non-members
    group_excluded_query_values: Others
    pass_thru_filter:
      accept_all: false
```

### Field reference (dynamic form)

| Field | Notes |
|---|---|
| `answer.tables[]` | Reference to the bound model (`id`, `name`, `obj_id`) |
| `answer.table_paths[]` | Self-path alias — `id` = `"<model display name>_1"`, `table` = `"<model display name>"`. All formula refs use this alias: `[<alias>::<col>]` |
| `answer.formulas[].id: formula_rank` | Rank formula: `rank ( sum ( [<alias>::<measure>] ) , 'desc' )` for Top-N; `'asc'` for Bottom-N. Must set `properties.column_type: ATTRIBUTE` |
| `answer.formulas[].id: formula_filter` | Filter formula: `[formula_rank] <= [<alias>::<paramName>]` (or `<= N` for a literal count). References the model parameter |
| `answer.search_query` | `"[<measure>] [<dimension>] [formula_rank] [formula_filter] = true"` |
| `answer.answer_columns[]` | Dimension, aggregated measure (e.g. `Total <measure>`), and `rank` entries |
| `answer.table.table_columns[].show_headline` | Set `false` on all columns (live-verified) |
| `answer.display_mode` | `TABLE_MODE` |

**Model parameter prerequisite:** the parameter referenced by `formula_filter` must exist
on the model **before** the cohort is imported. Parameters are migrated via the Tableau
`Parameters` datasource → `model.parameters[]`. A Tableau stepped range parameter
(`<range granularity='5' min='5' max='25'/>`) → `list_config` (enumerate min→max by step:
`[5, 10, 15, 20, 25]`), NOT `range_config`.

**Top vs Bottom:** `end='top'` in Tableau → `rank(..., 'desc')`; `end='bottom'` →
`rank(..., 'asc')` (user-confirmed 2026-06-12).

See [thoughtspot-answer-tml.md](thoughtspot-answer-tml.md) for the full Answer field
reference. See `../../shared/worked-examples/tableau/topn-set-to-query-set.md` for a
complete worked example (B2VBWeek11 `US_WINE_PRODUCTION`).

---

## Promoting an Answer-Level Set to Reusable

To convert an answer-level set to a reusable standalone set:

1. Export the parent Answer TML and locate the `cohorts[]` entry.
2. Build a standalone set TML:
   ```python
   import yaml

   cohort_entry = answer_tml["answer"]["cohorts"][0]  # the set to promote

   reusable_set = {
       "cohort": {
           "name": cohort_entry["name"],
           "owner": cohort_entry.get("owner", ""),
           "model": {
               "id": answer_tml["answer"]["tables"][0]["name"],
               "name": answer_tml["answer"]["tables"][0]["name"],
           },
           "config": cohort_entry["config"],
       }
   }
   # Include "answer" section if cohort_type is ADVANCED (query set)
   if cohort_entry.get("answer"):
       reusable_set["cohort"]["answer"] = cohort_entry["answer"]

   set_yaml = yaml.dump(reusable_set, allow_unicode=True, default_flow_style=False)
   ```
3. Import via `ts tml import --policy ALL_OR_NONE`.
4. After import, the set has its own GUID and can be used in any Answer on the same Model.

**Status of this promotion path:** UNTESTED — see `ts-object-answer-promote`
[open-items.md](../claude/ts-object-answer-promote/references/open-items.md) Item 5.

---

## Limitations

- Answer-level sets cannot be used outside their parent Answer until promoted to reusable.
- Reusable sets are scoped to a specific Model (or set of models). They cannot be used
  in Answers on different Models.
- Bin-based sets only support continuous numeric columns.
- Query sets run a full search at render time — complex embedded searches may affect
  Liveboard load performance.
