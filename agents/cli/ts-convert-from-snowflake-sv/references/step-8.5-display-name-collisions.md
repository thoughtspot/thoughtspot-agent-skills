# Step 8.5 — Display-name collisions

A Semantic View scopes construct names **per table**, so `FACT_SALES.ORDER_LINE_ID`
and `FACT_OPEN_ORDERS.ORDER_LINE_ID` are distinct and unambiguous there. A
ThoughtSpot Model has **one flat column namespace**, so both want the display name
`Order Line Id` and `build-model` refuses:

```
duplicate display title(s): 129 name(s) claimed by more than one construct: [...]
```

On a wide multi-fact SV this is structural, not a source defect — one real customer
SV produced **129 colliding titles across 322 of 1,010 columns**, concentrated in
the four order/sales-shaped facts. "Fix the SV" is not available when you do not own
it.

---

## Detect and characterise first

```python
import re
from collections import defaultdict

def title(n): return " ".join(w.capitalize() for w in re.split(r"[_\s]+", n))

groups = defaultdict(list)
for block in ("dimensions", "facts", "metrics"):
    for e in parsed[block]:
        groups[title(e["source_column"])].append(e)
dups = {k: v for k, v in groups.items() if len(v) > 1}
```

Report the shape before proposing a fix — the counts drive the choice:

- how many titles collide, over how many columns
- which tables are most involved
- how many are foreign-key IDs (`title.endswith(" Id")`) versus business attributes

---

## Ask the user

The resolution changes the model's whole search surface, so it is the user's call.

```
1,010 columns -> 817 distinct titles. 129 titles collide across 322 columns.
35 are foreign-key IDs; the rest are attributes repeated across grains.

  A  Qualify + hide FK IDs  — the primary fact keeps the bare name, others get a
                              suffix; duplicated FK IDs kept but DONT_INDEX   [recommended]
  B  Qualify everything uniformly — every colliding column gets a table prefix,
                              including the primary fact's; no bare names survive
  C  Keep one, drop the rest — smallest model, loses open-order / quote /
                              consignment detail on those attributes
```

**Why A is the default.** `order number` in a natural-language question almost
always means the invoiced one, so the primary fact should own the bare name. FK
IDs are never search terms — keeping them queryable but out of the search surface
removes clutter without losing data.

---

## Applying option A

1. **Rank the tables.** Primary fact first, then conformed dimensions, then the
   secondary facts. Within a role-played pair prefer the table whose primary key
   the column is (e.g. `DIM_ORGANIZATIONS` owns `Organization Id`).

2. **Suffix the non-primary instances** by mangling `source_column`, and record the
   label so the emitted title can be rewritten to the parenthesised form:

   ```python
   e["source_column"] = f"{e['source_column']}__{label.replace(' ', '_')}"
   e["_display_suffix"] = label      # "Open Orders"
   ```

   Use short business labels, not table names: `FACT_OPEN_ORDERS` → `Open Orders`,
   `DIM_ORDERS` → `Order Lines`, `DIM_CUSTOMIZATION_DETAILS` → `Customization`.

3. **De-index the duplicated FK IDs** — set `is_private = True` on every instance
   of a colliding title ending in ` Id`; `build-model` maps that to
   `index_type: DONT_INDEX`.

4. **Rewrite the emitted titles.** `build-model` derives the title by title-casing
   the mangled name, which yields `Order Number  Open Orders` (double space at the
   `__`). Post-process the model TML to the parenthesised form:

   ```python
   if c["name"].endswith("  " + label):
       c["name"] = c["name"][:-(len(label) + 2)] + f" ({label})"
   ```

5. **Assert uniqueness** before publishing, and re-run `ts tml lint`.

---

## Consequences to carry into the report and the instructions

- The Data Model Instructions must explain the convention, or Spotter has no way to
  know which is which:

  > A column suffixed with a table label in parentheses, e.g. `Order Number (Open
  > Orders)`, is the same logical attribute on a non-primary table. The unsuffixed
  > form always belongs to the primary sales fact.

- Interacts with **Step 7.5**: if a role-play pass runs afterwards, index the base
  dimension's columns by their *base* declared name — the suffix mangling means a
  lookup on the raw `source_column` misses.

- Report the count of disambiguated titles and de-indexed IDs in Step 12.
