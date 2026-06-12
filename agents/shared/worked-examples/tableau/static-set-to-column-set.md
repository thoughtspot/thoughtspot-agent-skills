# Worked Example — Tableau Static Set → ThoughtSpot Column Set

Live-verified 2026-06-12 against `se-thoughtspot` (model `TEST_SV_DMSI_AI_CONTEXT`): the
output TML below imported successfully as a `COHORT_SIMPLE` (set "Focus Categories",
GUID `2d95b710-…`). See `ts-convert-from-tableau` Step 5b (Tableau Sets) and the schema
`agents/shared/schemas/thoughtspot-sets-tml.md`.

A Tableau **static set** (explicit member list) maps to a ThoughtSpot **column set**
(`cohort_type: SIMPLE`, `cohort_grouping_type: GROUP_BASED`).

---

## Input — Tableau TWB XML (static set)

```xml
<group caption='Focus Categories' name='[Focus Categories]' name-style='unqualified'>
  <groupfilter function='union' user:ui-enumeration='inclusive'>
    <groupfilter function='member' level='[Product Category]' member='&quot;Cleaning and Sanitary Products&quot;' />
    <groupfilter function='member' level='[Product Category]' member='&quot;Furniture and decor&quot;' />
    <groupfilter function='member' level='[Product Category]' member='&quot;Electronics&quot;' />
  </groupfilter>
</group>
```

Detection: top-level `<group>` whose groupfilter tree is `function='union'` + `function='member'`
only — no `function='end'` (Top-N), no `function='except'`/`'intersect'` (set ops). This is the
Phase-2a translatable case.

---

## Output — ThoughtSpot column-set TML (`*.cohort.tml`) — VERIFIED

```yaml
# guid omitted on first import (ThoughtSpot assigns one)
cohort:
  name: "Focus Categories"             # from the group's caption=
  worksheet:                           # BINDING IS `worksheet:` — NOT `model:`
    id: TEST_SV_DMSI_AI_CONTEXT        # model display name
    name: TEST_SV_DMSI_AI_CONTEXT
    obj_id: TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY_AI_CONTEXT-889a704f  # model's stable obj_id
  config:
    cohort_type: SIMPLE
    cohort_grouping_type: GROUP_BASED
    anchor_column_id: Product Category # dimension DISPLAY name (works for multi-table models)
    null_output_value: "out"           # OUT label — keep DISTINCT from the cohort name (else formula refs fail)
    combine_non_group_values: true     # default catch-all: every non-member value (incl. NULL) → the "out" group
    groups:
    - name: "in"                       # IN label — distinct from cohort name "Focus Categories"
      combine_type: ALL                # single EQ-list condition; ALL≡ANY here
      conditions:
      - operator: EQ                   # EQ + multi-value list = "in set" (NOT operator: IN)
        column_name: Product Category  # display name
        value:                         # HTML-decoded, quotes stripped, in the column's STORED format
        - Cleaning and Sanitary Products
        - Furniture and decor
        - Electronics
        filter_value_type: STRING      # DATE anchor → DATE_FILTER + date_filter_values instead
```

Import: `ts tml import --create-new --policy ALL_OR_NONE` (JSON array of TML strings on stdin).

---

## Gotchas (all learned from the live test)

- **`worksheet:` not `model:`** — using `model:` fails with `"Invalid save request, Table cant be empty"`.
  The `worksheet.obj_id` (stable id, format `<UPPER_NAME>-<guidprefix>`) comes from the target model's
  exported TML header.
- **Display names** for `anchor_column_id` and `column_name` — even on a multi-table semantic view.
- **`operator: EQ` with a value list** = membership; do not use `operator: IN`.
- **Stored format** — values must match the column's stored values exactly (case/spelling), not Tableau's
  display formatting, or the set matches nothing.
- **Name the cohort DISTINCTLY from its In/Out labels.** A name==label collision (cohort `Focus
  Categories` + group also `Focus Categories`) breaks formula references with *"Search did not find …"*
  (live-verified). Emit group `in` / out `out` (lowercase), distinct from the cohort name.

## Referencing the set IN/OUT (verified)

A column set **is** referenceable in both **search** and **formulas**:
- **Compare In vs Out** → group a measure by the cohort column (`[Amount] [Product Category set]`).
- **In/Out measure** → conditional aggregate, three verified forms (2026-06-12):
  - literal: `sum ( if ( [Product Category set] = 'in' ) then [Amount] else null )` (mirrors `IF [Set] THEN x END`)
  - `sum_if` cohort ref (best for large lists): `sum_if ( [Product Category set] = 'in' , [Amount] )` / `… = 'out'`
  - dimension + member list: `sum_if ( [Product Category] in { 'Electronics' , … } , [Amount] )` /
    `sum_if ( not ( [Product Category] in { … } ) , [Amount] )`
  - the label in the formula must match the cohort's emitted group/out label **exactly (case-sensitive)**.
- **Filter to In/Out** → filter the cohort column = `in` / `out`.

### Verified consumption answer TML — In/Out measures (trimmed)

A real, imported answer (auto-generated `client_state_v2`/chart styling omitted — not needed to convert):

```yaml
answer:
  name: "In/Out with formulas"
  tables:
  - id: TEST_SV_DMSI_AI_CONTEXT
    name: TEST_SV_DMSI_AI_CONTEXT
    obj_id: TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY_AI_CONTEXT-889a704f
  formulas:
  - id: formula_inSet
    name: inSet
    expr: "sum_if ( [Product Category set] = 'in' , [Amount] )"
    was_auto_generated: false
  - id: formula_outSet
    name: outSet
    expr: "sum ( if ( [Product Category set] = 'out' ) then [Amount] else null )"
    was_auto_generated: false
  search_query: "[formula_inSet] [formula_outSet]"
  answer_columns:
  - name: inSet
  - name: outSet
  display_mode: TABLE_MODE
```

### Verified consumption answer TML — In vs Out breakdown (set as group-by, trimmed)

```yaml
answer:
  name: "In vs Out breakdown"
  tables:
  - id: TEST_SV_DMSI_AI_CONTEXT
    name: TEST_SV_DMSI_AI_CONTEXT
    obj_id: TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY_AI_CONTEXT-889a704f
  search_query: "[Amount] [Product Category set]"   # the cohort column groups Amount into in/out
  answer_columns:
  - name: "Product Category set"
  - name: "Total Amount"
  chart:
    type: PIE
    chart_columns:
    - column_id: "Product Category set"
    - column_id: "Total Amount"
    axis_configs:
    - x: ["Product Category set"]
      y: ["Total Amount"]
  display_mode: CHART_MODE
```

## Other set kinds

- **Top-N / Bottom-N** (`function='end'` + `order` + `count`) → ThoughtSpot **query set**
  (`cohort_type: ADVANCED`, `COLUMN_BASED`) — now **translated** (Phase 2b, 2026-06-12). See the
  sibling worked example `topn-set-to-query-set.md`.
- **Set operations** (`function='except'`/`'intersect'` of a computed sub-tree) → Phase 2c
  (still deferred — detect + log, never mis-translate).
- **Set actions** (interactive) → no equivalent (logged + omitted).

## `%null%` members — use the `{Null}` grouping value (resolved 2026-06-12, UI-verified)

ThoughtSpot column sets **do** support NULL membership — the literal token is `{Null}`. To **include**
null in a set, add a condition `operator: EQ, value: ["{Null}"]` alongside the member list with
`combine_type: ANY` ("in the list **or** null"):

```yaml
groups:
- name: "My Set"
  combine_type: ANY
  conditions:
  - operator: EQ
    column_name: Product Category
    value: [Cleaning and Sanitary Products, Electronics]
    filter_value_type: STRING
  - operator: EQ            # the %null% member
    column_name: Product Category
    value: ["{Null}"]
    filter_value_type: STRING
```

To **exclude** null (an `except` removing it), just omit it — `combine_non_group_values: true` already
sends nulls to the catch-all "out" bucket. No IF/THEN/ELSE formula alternative is needed for null.

## `except` of a member-list — use `NE` (UI-verified 2026-06-12)

`except {A, B}` → a group with one `operator: NE` condition per excluded value, `combine_type: ALL`
("not A AND not B"). Example — `Category Set` = *all categories except {Furniture, %null%}*:

```yaml
groups:
- name: "Category Set"
  combine_type: ALL
  conditions:
  - operator: NE
    column_name: Category
    value: [Furniture]
    filter_value_type: STRING
  # %null% needs no condition — combine_non_group_values already excludes nulls
```

## Formula-column anchors (UI-verified 2026-06-12)

A set anchored on a **calculated/derived dimension** (e.g. `Year Set` on `YEAR([Order Date])`) is a
valid column set: resolve the Tableau internal calc id → the calc's display name, ensure that calc
exists as a **model formula column** (ATTRIBUTE), and set `anchor_column_id` to that column's display
name. Match `filter_value_type` to the calc's output type (a year → numeric, not `STRING`).
