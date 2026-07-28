This file serves the **Concept Mapping** section in
`agents/cli/ts-convert-from-snowflake-sv/SKILL.md` — the full Snowflake Semantic View
DDL construct → ThoughtSpot Model mapping table, consulted throughout Steps 4–9.

---

| Snowflake Semantic View (real DDL format) | ThoughtSpot Model |
|---|---|
| `tables ( DB.SCHEMA.TABLE [primary key (col)] )` | `model_tables[]` — one entry per **physical ThoughtSpot table** |
| `primary key (col)` on a table | Identifies join target — not written into model TML directly |
| `tables ( DB.SCHEMA.TABLE ... comment='...' )` | TS **Table** TML `table.description` — applied as a separate Table-TML update |
| `dimensions ( TABLE.COL as view.NAME [comment='...'] )` | `columns[]` with `column_type: ATTRIBUTE` |
| Dimension with date/timestamp physical column | `columns[]` with `column_type: ATTRIBUTE` (ThoughtSpot infers date type) |
| `metrics ( TABLE.COL as SUM(view.NAME) )` | `columns[]` with `column_type: MEASURE` + aggregation |
| `metrics ( TABLE.COL as complex_sql_expr )` | `formulas[]` with translated ThoughtSpot formula |
| `metrics ( TABLE.COL non additive by (D.col asc nulls last) as SUM(...) )` | `formulas[]` with `last_value(sum(...), query_groups(), {date})` |
| `metrics ( TABLE.COL non additive by (D.col desc nulls last) as SUM(...) )` | `formulas[]` with `first_value(sum(...), query_groups(), {date})` |
| `metrics ( ... OVER (ORDER BY col ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) )` — cumulative/running sum, no `PARTITION BY EXCLUDING` | `formulas[]` with `moving_sum(group_aggregate(agg(...), {[T::PK]}, query_filters()), -1, 0, [T::order_col])` — cannot nest aggregates directly in `moving_sum`; must wrap in `group_aggregate` first. **This is a lossy summary row, not exhaustive:** when the SQL has `PARTITION BY EXCLUDING`, the correct mapping is `cumulative_sum`/`cumulative_average`/etc. instead — see the full PARTITION BY EXCLUDING routing decision table in ts-snowflake-formula-translation.md (Translatable Window Function Patterns) |
| `COUNT_IF(boolean_col)` in metrics | `count_if([T::BOOL_COL], [T::PK])` or `sum ( if ( [T::BOOL_COL] ) then 1 else 0 )` — note parentheses required around BOOL in `if()`. `sum_if([T::BOOL], [T::MEASURE])` also works (L6). |
| `relationships ( REL as FROM(FK) references TO(PK) )` | `referencing_join` in model_tables (Scenario A, pre-defined joins) OR `joins[]` inline (Scenario B) |
| `with synonyms=('Display Name','Alt 1','Alt 2',...)` on a dimension/metric | First → column `name`. Rest → `properties.synonyms` (with `properties.synonym_type: USER_DEFINED`). |
| `comment='...'` on a dimension/metric | column `description` |
| Top-level `comment='...'` (after metrics block) | Model TML `model.description` |
| `with extension (CA='...')` | Not mapped to ThoughtSpot — logged in report |
