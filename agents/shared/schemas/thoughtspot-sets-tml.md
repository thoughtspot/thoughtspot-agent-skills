# ThoughtSpot Sets TML — Structure Reference

How ThoughtSpot sets (cohorts) are represented in TML. Sets are custom column groupings —
bins, value groups, or query-based filters — that appear as columns in Answers and Liveboards.

Sets are documented in the ThoughtSpot docs at
[docs.thoughtspot.com — TML Sets](https://docs.thoughtspot.com/cloud/26.4.0.cl/tml-sets).

For how sets appear inside Answer TML (as `cohorts[]`), see
[thoughtspot-answer-tml.md](thoughtspot-answer-tml.md).

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

```yaml
guid: "{set_guid}"              # document root — omit on first import
cohort:
  name: "My Reusable Set"
  description: "Optional description"
  owner: "analyst@company.com"

  model:                        # single-model set
    id: "Model Display Name"
    name: "Model Display Name"
  # OR for multi-model sets:
  models:
  - id: "Model A"
    name: "Model A"
  - id: "Model B"
    name: "Model B"

  config:
    anchor_column_id: Revenue   # column the set operates on
    cohort_type: SIMPLE | ADVANCED
    cohort_grouping_type: BIN_BASED | GROUP_BASED | COLUMN_BASED

    # --- BIN_BASED (column set, continuous ranges) ---
    bins:
      minimum_value: 0.0
      maximum_value: 100.0
      bin_size: 10.0

    # --- GROUP_BASED (column set, named value groups) ---
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

    # --- COLUMN_BASED (query set — results of an embedded search) ---
    hide_excluded_query_values: false    # show/hide rows not in the set
    pass_thru_filter:                    # how outer query filters apply to the embedded search
      accept_all: true                   # accept all outer filters
      # OR selectively:
      include_column_ids: [col_id_1]
      exclude_column_ids: [col_id_2]
    return_column_id: "Product ID"       # the column whose values define set membership

  answer:                               # COLUMN_BASED (query set) only
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
```

---

## Answer-Level Set (inline in Answer TML)

When a set is answer-level (not reusable), it appears in `answer.cohorts[]` without a
GUID. The structure is the same as the `cohort:` body above, minus the `model:` /
`models:` field (the model is inherited from the Answer's `tables[]`).

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
| `hide_excluded_query_values` | `true` hides rows not in the set from the Answer |
| `pass_thru_filter.accept_all` | If `true`, all outer query filters apply to the embedded search |
| `pass_thru_filter.include_column_ids` | Only these columns' filters are passed through |
| `pass_thru_filter.exclude_column_ids` | These columns' filters are blocked |
| `return_column_id` | The column whose values define set membership (the "anchor") |

### `answer` section (query sets only)

Contains a full embedded Answer — the search whose results define the set members. Uses
the same structure as `answer.cohorts[n].answer` in Answer TML. See
[thoughtspot-answer-tml.md](thoughtspot-answer-tml.md) for the full field reference.

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
