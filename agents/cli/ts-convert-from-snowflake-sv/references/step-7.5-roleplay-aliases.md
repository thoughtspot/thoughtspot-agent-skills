# Step 7.5 — Role-played dimension aliases (I14)

A Semantic View scopes construct names **per table**, so declaring several
relationships from one table to the same target is legal and idiomatic there:

```sql
FACT_SALES_TO_DIM_TIME_TRANSACTION as FACT_SALES(TRANSACTION_DATE_ID) references DIM_TIME(DATE_ID),
FACT_SALES_TO_DIM_TIME_SHIP        as FACT_SALES(SHIP_DATE_ID)        references DIM_TIME(DATE_ID),
```

A ThoughtSpot Model has **one flat join graph**. Two joins between the same
ordered pair leave the join path ambiguous and **the Model will not load**.
`ts tml lint` invariant **I14** rejects this, so `ts snowflake build-model`
refuses rather than emitting an unloadable Model:

```
I14: 'FACT_SALES' joins 'DIM_TIME' 8 times (FACT_SALES_TO_DIM_TIME_TRANSACTION,
FACT_SALES_TO_DIM_TIME_ORDER_DATE, ...) — the join path is ambiguous and
ThoughtSpot will not load the Model. Give each role its own aliased
model_tables entry (name: the physical table, alias: a unique per-role id) and
point one join at each.
```

This is common, not exceptional — a sales SV typically role-plays a date
dimension across order/ship/booked/promise/request dates, and an employee
dimension across account-team roles.

---

## When this step runs

After Step 7 (join discovery), before Step 8 (assemble the tables map). Detect
it directly from `parsed.json` rather than waiting for the lint failure:

```python
from collections import Counter
pairs = Counter((r["from_table"], r["to_table"]) for r in parsed["relationships"])
roleplay = {k: v for k, v in pairs.items() if v > 1}
```

If `roleplay` is empty, skip to Step 8.

---

## Procedure

### 1. Present the plan and get the trim decision

Show the user each role-played pair, then ask for the scope. **The column trim
is theirs to choose** — it is the one part that is not mechanical, and the naive
answer is actively harmful: a 56-column date dimension aliased 14 times adds
784 near-duplicate columns and degrades NL search more than the ambiguity it
fixed.

```
DIM_TIME is joined 23 times across 5 tables — 15 distinct date roles:
  FACT_SALES         8   transaction, order, ship, scheduled ship, booked, promise, request, web creation
  FACT_OPEN_ORDERS   6   order, scheduled ship, booked, promise, request, web creation
  FACT_CONSIGNMENTS  5   memo order, memo ship, memo review, purchase return, last update
  DIM_QUOTES         2   quote created, quote expiration
  FACT_QUOTES        2   quote created, quote expiration

DIM_TIME has 56 columns. Aliasing every role with the full set adds 784 columns.

  A  All roles, trimmed columns (~12 grouping columns per alias)   [recommended]
  B  All roles, full column set
  C  Core roles only — name which; the rest stay on the primary path
```

### 2. Pick the primary role per physical table

**One role keeps the base node.** Aliasing every role leaves the base table with
no joins — a disconnected node. Give the base entry to the default role and its
full column set:

- a date dimension → the transaction/invoice date (what an unqualified date
  question means)
- a role-played dimension with an obvious principal → that one (e.g. Sales
  Director among five account-team roles)
- otherwise → the role the SV's own `ai_sql_generation` text treats as default

### 3. Synthesize the alias table entries

Append one `tables[]` entry per non-primary role to `parsed.json`, with `name`
the **physical** table and `alias` a unique node id. `build_node_id_map` then
mints the alias node automatically — it keys on the physical name appearing more
than once with a differing alias:

```python
d["tables"].append({
    "fqn": base["fqn"], "alias": "DIM_TIME_SHIP_DATE", "name": "DIM_TIME",
    "primary_key": ["DATE_ID"], "synonyms": [],
    "comment": f"{base['comment']} Role-played as Ship Date.",
    "is_subquery": False, "subquery_sql": None,
})
```

### 4. Repoint the relationships

For each non-primary role, set `to_table` to the alias node id. Leave the
primary role pointing at the physical name.

### 5. Duplicate the trimmed column set per alias

Copy the chosen columns from the base dimension's parsed entries, setting
`source_table` and `alias_table` to the alias node. Give each a unique display
name — suffix the declared name, and mark the join key private:

```python
e = dict(base_col)
e["source_table"] = e["alias_table"] = "DIM_TIME_SHIP_DATE"
e["source_column"] = f"{decl}__Ship_Date"     # -> "Fiscal Year (Ship Date)"
e["is_private"] = (decl == "DATE_ID")          # join key: DONT_INDEX
```

> **Index the columns by their BASE declared name.** If a display-name
> collision pass has already run, non-primary instances carry a `__Label`
> suffix, so a lookup on the raw `source_column` misses. Strip at `__` first.

A workable 12-column grouping set for a date dimension: calendar date, fiscal
year, fiscal quarter name + order, fiscal month name + order, fiscal
month-year name, fiscal week name, week order, month id, quarter id, day-of-week
name. Keep relative-period flags and offsets (`is_ytd`, `month_offset`,
`same_date_id_last_year`) on the **base node only** — they answer "relative to
today", which has one meaning per model, and duplicating them multiplies the
search surface for no gain.

### 6. Add the aliases to `tables.json`

Every alias needs an entry mapping to the physical table, or
`build-model` raises `relationship to_table '<alias>' not in tables map`:

```json
{ "DIM_TIME_SHIP_DATE": { "name": "DIM_TIME", "fqn": "{dim_time_guid}" } }
```

Aliases do **not** need their own Table TML — an alias is a second reference to
the same underlying Table object.

### 7. Re-translate and assert

Re-run `translate-formulas` (the parsed doc changed), then confirm no pair
survives twice before building:

```python
pairs = Counter((r["from_table"], r["to_table"]) for r in d["relationships"])
assert not {k: v for k, v in pairs.items() if v > 1}
```

---

## What the emitted TML looks like

`build-model` handles the shape; this is what to expect when reviewing it.
Note the asymmetry — **`with:` carries the alias, the `on` clause uses physical
names on both sides**, and `column_id` uses the alias prefix:

```yaml
model_tables:
- name: FACT_SALES
  joins:
  - name: FACT_SALES_TO_DIM_TIME_SHIP
    with: DIM_TIME_SHIP_DATE
    'on': "[FACT_SALES::SHIP_DATE_ID] = [DIM_TIME::DATE_ID]"
    type: LEFT_OUTER
    cardinality: MANY_TO_ONE
- name: DIM_TIME
- name: DIM_TIME
  alias: DIM_TIME_SHIP_DATE
columns:
- name: "Fiscal Year"
  column_id: DIM_TIME::YEAR
- name: "Fiscal Year (Ship Date)"
  column_id: DIM_TIME_SHIP_DATE::YEAR
```

---

## Report it in Step 12, and simplify the instructions

Role-play aliases move the date-path routing out of prose and into structure, so
the Data Model Instructions get shorter and better. Replace per-date-key join
routing ("for ship-date questions use `ship_date_id = dim_time.date_id`") with
naming guidance:

> Each date context is its own dimension. Unqualified date columns are the
> transaction date and are the default; otherwise use the suffixed set —
> `Fiscal Month Name (Ship Date)` for "sales by ship month". Relative-period
> flags (`Is Ytd`, `Month Offset`) exist on the transaction date only.

Include in the Step 12 report: the alias count per physical table, the trim
applied, and which role kept the base node.
