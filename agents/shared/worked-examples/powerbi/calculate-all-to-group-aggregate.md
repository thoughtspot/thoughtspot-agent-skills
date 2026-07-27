<!-- currency: powerbi — 2026-07 (verified on ps-internal) -->
# Worked example — CALCULATE(m, ALL(col)) → group_aggregate

`CALCULATE` with `ALL` / `REMOVEFILTERS` / `ALLSELECTED` of specific columns removes those
columns from the filter/group context — a normalized baseline. ThoughtSpot's equivalent is
`group_aggregate` with the columns subtracted from the current group set. Verified live
(normalized turnover: baseline constant across Gender while actual turnover varied).

## Pattern
```
CALCULATE([TO %], ALL(Employee[Gender]), ALL(Employee[Ethnicity]))
```
becomes
```
group_aggregate([formula_TO %],
                query_groups()  - {[Employee::Gender], [Employee::Ethnicity]},
                query_filters() - {[Employee::Gender], [Employee::Ethnicity]})
```

- `query_groups() - {cols}` keeps every current grouping **except** the neutralized ones.
- `query_filters() - {cols}` does the same for filters.
- `group_aggregate({}, {})` = grand total.
- Fires only for `ALL(Table[Col])` (a specific column), **not** `ALL(WholeTable)`.

## Gotchas (verified)
- The group-set needs **qualified** `[Table::Col]` refs inside a model formula.
- **Indexing lag**: the formula imports clean, but `searchdata` may return "column not found"
  for ~15s before the group-set resolves — retry before concluding it failed.
- Prove it by breaking the measure out **by** a neutralized dimension (e.g. Gender): the
  baseline reads flat, the actual varies.
