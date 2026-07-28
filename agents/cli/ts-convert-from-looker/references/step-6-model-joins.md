# Step 6 — Model Join Translation Detail

Reference detail for **Step 6 — Generate Model TML(s)**: the full Model TML template
(§6a), the join-SQL-translation worked example (§6b), the join-type mapping table (§6c),
the cardinality mapping table (§6d), and the join-key column handling table (§6f). The
step's spine (one model per explore, the invariant checklist §6e, and which columns go
where) stays in `SKILL.md` — this file is what the spine links out to for the full
mapping tables and template.

---

## 6a. Model TML template

```yaml
model:
  name: {Explore Label or Name}
  model_tables:
  # Fact table — defines its joins to direct dims
  - name: {FACT_TABLE_NAME}             # exact ThoughtSpot table object name (case-sensitive)
    joins:
    - with: {DIM_TABLE_NAME}            # must match a model_tables[].name exactly
      'on': '[{FACT_TABLE}::{FK_COL}] = [{DIM_TABLE}::{PK_COL}]'   # 'on' MUST be quoted — YAML reserved word
      type: LEFT_OUTER                  # from join type: — see §6c; FULL_OUTER invalid, use OUTER
      cardinality: MANY_TO_ONE          # from relationship: — see §6d
  # Dim table entry — no joins: array unless it is itself a mid-chain table (see chained join pattern below)
  - name: {DIM_TABLE_NAME}
  # Chained join pattern (A→B→C→D): each intermediate table defines its own joins:
  # - name: {B_TABLE}
  #   joins:
  #   - with: {C_TABLE}
  #     'on': '[{B}::{fk}] = [{C}::{pk}]'
  #     type: LEFT_OUTER
  #     cardinality: MANY_TO_ONE
  # - name: {C_TABLE}
  #   joins:
  #   - with: {D_TABLE}
  #     'on': '[{C}::{fk}] = [{D}::{pk}]'
  #     type: LEFT_OUTER
  #     cardinality: MANY_TO_ONE
  # - name: {D_TABLE}

  formulas:                             # one entry per LookML measure — NO aggregation: here (Invariant I2)
  - id: formula_{Formula Name}          # id format: "formula_" + display name (spaces preserved)
    name: {Formula Name}
    expr: "{ThoughtSpot formula using [TABLE_NAME::Col Name] references}"
    properties:
      column_type: MEASURE

  columns:
  # ── From fact table: all analytical dimensions ──
  - name: {Fact Dimension Name}
    column_id: "{FACT_TABLE}::{Col Name}"   # Col Name = Table TML column display name (Step 5c)
    properties:
      column_type: ATTRIBUTE
  # Base numeric column used by a formula: list as ATTRIBUTE + DONT_INDEX (I8 — formula does aggregation)
  - name: {Base Numeric Name}
    column_id: "{FACT_TABLE}::{Num Col}"
    properties:
      column_type: ATTRIBUTE
      index_type: DONT_INDEX
  # FK column on fact side: DO NOT add to columns[] — only in Table TML for join resolution (Step 6f)

  # ── From joined dim table: PK hidden + all useful attributes ──
  - name: {Dim PK Display Name}         # always list dim PK with is_hidden: true (Step 6f)
    column_id: "{DIM_TABLE}::{PK_Col}"
    properties:
      column_type: ATTRIBUTE
      is_hidden: true
  - name: {Dim Attribute Name}          # apply §5d conflict resolution for shared names
    column_id: "{DIM_TABLE}::{Attr Col}"
    properties:
      column_type: ATTRIBUTE

  # ── Formula columns: one per formulas[] entry — Invariant I1 ──
  - name: {Formula Name}               # must match formulas[].name exactly (case-sensitive)
    formula_id: formula_{Formula Name} # must match formulas[].id exactly
    properties:
      column_type: MEASURE
      aggregation: SUM                  # convention: SUM for all formula measures (I2)
      index_type: DONT_INDEX            # Invariant I3

  properties:
    is_bypass_rls: false
    join_progressive: true
```

---

## 6b. Join SQL translation

LookML `sql_on:` → ThoughtSpot `'on':` by replacing `${view.field}` with `[VIEW::col_display_name]`.

The column reference in `'on':` uses the **Table TML column display name** (Title Case from
field name, or `label:` if present) — NOT the physical `db_column_name`.

```
# LookML
sql_on: ${order_fact.customer_key} = ${customer_dim.customer_key} ;;

# ThoughtSpot  (customer_key → Title Case → "Customer Key")
'on': '[ORDER_FACT::Customer Key] = [CUSTOMER_DIM::Customer Key]'
```

## 6c. Join type mapping

| LookML `type:` | ThoughtSpot `type:` |
|---|---|
| `left_outer` (default) | `LEFT_OUTER` |
| `full_outer` | `OUTER` |
| `inner` | `INNER` |
| `cross` | `CROSS` |

**`FULL_OUTER` is not valid in Model TML inline joins.** ThoughtSpot raises `"Invalid value FULL_OUTER … Allowed values are INNER, LEFT_OUTER, OUTER, RIGHT_OUTER"`. Use `OUTER` instead.

## 6d. Cardinality mapping

| LookML `relationship:` | ThoughtSpot `cardinality:` |
|---|---|
| `many_to_one` (default) | `MANY_TO_ONE` |
| `one_to_many` | `ONE_TO_MANY` |
| `many_to_many` | `MANY_TO_MANY` |
| `one_to_one` | `ONE_TO_ONE` |

## 6f. Join key column handling

The join `'on':` clause references Table TML column names directly. Whether a join key
column appears in `model.columns[]` depends on which side of the join it is on:

| Column | In Table TML? | In model `columns[]`? | Why |
|---|---|---|---|
| **Fact table FK** (e.g. `order_fact.customer_key`) | ✓ Yes | ✗ No | Used only for the join condition — not an analytical column |
| **Dim table PK** (e.g. `customer_dim.customer_key`) | ✓ Yes | ✓ Yes (`is_hidden: true`) | Canonical key of the dimension; keep hidden so it doesn't clutter search |

The FK column must exist in the fact table's Table TML (the join `'on':` references it), but
it should **not** be added to the model's `columns[]` list. This avoids a duplicate display
name conflict when fact and dim both have a field named e.g. `customer_key`, and it keeps
the model clean — FK columns have no analytical value on their own.
