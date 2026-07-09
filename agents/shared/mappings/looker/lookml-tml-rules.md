<!-- currency: looker — 2026-07 (inaugural anchor; verify in next external sweep) -->

# LookML → ThoughtSpot TML Generation Rules

Critical rules for producing valid ThoughtSpot TML from a LookML project.
Every rule here has been verified against a live ThoughtSpot import.

---

## Table TML Rules

### Required fields on every column

```yaml
- name: COLUMN_NAME
  db_column_name: COLUMN_NAME    # always include — even when it equals name
  properties:
    column_type: ATTRIBUTE       # or MEASURE
```

**Omitting `db_column_name` causes silent failures or missing columns on import.**

### MEASURE columns must include `aggregation`

```yaml
- name: NET_REVENUE
  db_column_name: NET_REVENUE
  properties:
    column_type: MEASURE
    aggregation: SUM             # SUM | AVERAGE | COUNT | MIN | MAX
```

### Required `connection` section

Use the exact ThoughtSpot connection display name — never a GUID.

```yaml
table:
  name: ORDER_FACT
  db: {database}
  schema: {schema}
  db_table: ORDER_FACT
  connection:
    name: {connection_name}      # case-sensitive; verify with: ts connections list --profile {p}
```

If import returns `connection not found`, the name or case is wrong.
If it returns `column not found`, the connection does not expose that table.

### No `guid` on first import

Omit `guid` entirely on first import. ThoughtSpot assigns it.
Include `guid` at the **document root** (never nested inside `table:`) only when updating an existing object.

---

## Model TML Rules

### `with:` is required on every join

Every entry in `model_tables[].joins[]` must have a `with:` field naming the table being joined to.

```yaml
# Wrong — missing with:
joins:
- id: CUSTOMER_DIM
  name: CUSTOMER_DIM
  on: '[ORDER_FACT::CUSTOMER_KEY] = [CUSTOMER_DIM::CUSTOMER_KEY]'

# Correct
joins:
- id: CUSTOMER_DIM
  name: CUSTOMER_DIM
  with: CUSTOMER_DIM             # required
  on: '[ORDER_FACT::CUSTOMER_KEY] = [CUSTOMER_DIM::CUSTOMER_KEY]'
  type: LEFT_OUTER
  cardinality: MANY_TO_ONE
```

**Without `with:`, ThoughtSpot throws:** `Compulsory Field worksheet->model_tables->joins->with is not populated`

### Join `id` must equal `name` (Invariant I4)

```yaml
- id: CUSTOMER_DIM
  name: CUSTOMER_DIM             # must be identical to id — case-sensitive
  with: CUSTOMER_DIM
```

### Do not include both sides of a join key in `columns[]`

When a fact table FK and a dim table PK have the same semantic meaning (e.g. ORDER_FACT::STORE_KEY and STORE_DIM::STORE_KEY), include only one side in `columns[]`. The join itself defines the relationship — both sides are redundant and cause a duplicate name error.

**Rule:** keep the fact table FK; drop the dim table PK.

```yaml
# Keep this:
- name: Store Key
  column_id: ORDER_FACT::STORE_KEY
  properties:
    column_type: ATTRIBUTE

# Drop this (redundant — STORE_DIM::STORE_KEY is the same value):
- name: Store Key
  column_id: STORE_DIM::STORE_KEY
```

**Without this fix, ThoughtSpot throws:** `Multiple columns with the same name found: store key`

### Rename non-key duplicate column names with table abbreviation suffix

When two different tables have a column with the same display name (e.g. `STATE` in both CUSTOMER_DIM and STORE_DIM), rename both using `_{table_abbr}`:

| Pattern | Example |
|---|---|
| `{col}_{fact_abbr}` | `unit_cost_of` (ORDER_FACT) |
| `{col}_{dim_abbr}` | `unit_cost_pd` (PRODUCT_DIM) |

Common abbreviations: `of` = ORDER_FACT, `cd` = CUSTOMER_DIM, `pd` = PRODUCT_DIM, `sd` = STORE_DIM, `dd` = DATE_DIM, `prd` = PROMO_DIM.

### No `aggregation` inside `formulas[]` (Invariant I2)

```yaml
# Wrong
formulas:
- id: formula_Total Net Revenue
  name: Total Net Revenue
  expr: sum ( [ORDER_FACT::NET_REVENUE] )
  aggregation: SUM               # NEVER here

# Correct — aggregation belongs only in columns[]
formulas:
- id: formula_Total Net Revenue
  name: Total Net Revenue
  expr: sum ( [ORDER_FACT::NET_REVENUE] )
```

### Every formula needs a paired `columns[]` entry (Invariant I1)

```yaml
formulas:
- id: formula_Order Count
  name: Order Count
  expr: unique count ( [ORDER_FACT::ORDER_ID] )

columns:
- name: Order Count                # must match formula name
  formula_id: formula_Order Count  # must match formula id
  properties:
    column_type: MEASURE
    index_type: DONT_INDEX         # required on computed numeric measures (Invariant I3)
```

### `count_distinct` → `unique count()` formula (Invariant I5)

Never use `aggregation: COUNT_DISTINCT` in a `columns[]` entry.
Always translate `type: count_distinct` to a formula using `unique count()`.

```yaml
# Wrong
- name: Order Count
  column_id: ORDER_FACT::ORDER_ID
  properties:
    column_type: MEASURE
    aggregation: COUNT_DISTINCT    # not supported — causes import error

# Correct
formulas:
- id: formula_Order Count
  name: Order Count
  expr: unique count ( [ORDER_FACT::ORDER_ID] )
```

### No `fqn` on `model_tables[]` entries (batch import)

When importing as a batch (tables + model in one payload), use `name:` only on `model_tables[]`.
ThoughtSpot resolves references by name within the batch — no GUID needed.

```yaml
model_tables:
- name: ORDER_FACT               # name only — no fqn:
  joins:
  - ...
- name: CUSTOMER_DIM             # name only — no fqn:
```

### No duplicate `column_id` values (Invariant I8)

Each physical column may appear in `columns[]` at most once.
If a column is needed in multiple contexts (e.g. as both a filter and a formula input),
use a formula to reference it rather than duplicating the `column_id`.

---

## Batch Import Rules

### Import order in payload

Tables before SQL views before models:

```python
order = (sorted(glob.glob("*.table.tml")) +
         sorted(glob.glob("*.sql_view.tml")) +
         sorted(glob.glob("*.model.tml")))
```

### Zip contains TML files only

The zip for UI import must contain only `.tml` files at the root level — no subdirectories,
no gaps/documentation files.

```bash
zip {explore_name}_tml.zip *.table.tml *.sql_view.tml *.model.tml 2>/dev/null || \
  zip {explore_name}_tml.zip *.table.tml *.model.tml
```

### Expected WARNING during validation (not an error)

```
Table with id null not found. Matching with db/schema/dbTable
```

This is normal for new tables — ThoughtSpot matches by connection + db + schema + table name
when no GUID exists yet. It is a WARNING, not an ERROR; the import will succeed.

---

## Self-Validation Checklist

Before generating any Model TML, run through:

- [ ] I1 — Every `formulas[]` entry has a matching `formula_id:` in `columns[]`
- [ ] I2 — No `aggregation:` key inside any `formulas[]` entry
- [ ] I3 — Every formula-based MEASURE column has `index_type: DONT_INDEX`
- [ ] I4 — Every join's `id:` equals its `name:` exactly (case-sensitive)
- [ ] I4+ — Every join has a `with:` field set to the target table name
- [ ] I5 — All count-distinct measures use `unique count()` formula, never `aggregation: COUNT_DISTINCT`
- [ ] I6 — `connection.name:` is a display name string — no GUIDs
- [ ] I7 — No formula classified as untranslatable without checking the formula reference first
- [ ] I8 — No duplicate `column_id` values in `columns[]`
- [ ] No dim-side join key columns duplicating fact-side FK columns in `columns[]`
- [ ] No duplicate display names across `columns[]` (ThoughtSpot is case-insensitive)
- [ ] `fqn:` absent from `model_tables[]` entries (batch import — name resolution used instead)
