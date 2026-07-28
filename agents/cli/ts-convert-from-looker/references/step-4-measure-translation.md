# Step 4 — Measure & Dimension Translation Detail

Reference detail for **Step 4 — Resolve field references and classify**: the full
dimension/measure classification tables and the §4a SQL-pattern table for derived
measures, plus the §4b filtered-measure worked example. The step's spine (when to
classify, the §4c column-uniqueness rule, and the Invariant references) stays in
`SKILL.md` — this file is what the spine links out to for the full mapping tables.

---

## Dimensions → ThoughtSpot columns

| LookML `type:` | ThoughtSpot `column_type` | Notes |
|---|---|---|
| `string` | `ATTRIBUTE` | |
| `number` (not aggregated) | `ATTRIBUTE` | Used as an ID / key |
| `yesno` | `ATTRIBUTE` | |
| `date`, `time` | `ATTRIBUTE` | |
| `tier` | `ATTRIBUTE` → converted to `if/then/else` formula | See formula translation |
| `duration` | `ATTRIBUTE` → `diff_days/diff_months/diff_years` formula | |
| `location` | **Unsupported** — flag + omit | No TS spatial type |

## Measures → ThoughtSpot formulas

| LookML `type:` | ThoughtSpot formula | column_type | Notes |
|---|---|---|---|
| `sum` | `sum ( [T::COL] )` | MEASURE | |
| `count` | `count ( [T::COL] )` | MEASURE | |
| `count_distinct` | `unique count ( [T::COL] )` | MEASURE | Invariant I5: NEVER `aggregation: COUNT_DISTINCT` |
| `average` | `average ( [T::COL] )` | MEASURE | |
| `max` | `max ( [T::COL] )` | MEASURE | |
| `min` | `min ( [T::COL] )` | MEASURE | |
| `number` (derived) | Translate inlined SQL to TS formula | MEASURE | See §4a |
| `sum_distinct` | `sum ( [T::COL] )` (with user confirmation of grouping intent) | MEASURE | |
| `running_total` | `cumulative_sum ( sum ( [T::COL] ) , [date_col] )` | MEASURE | |
| `percent_of_total` | `sum([T::COL]) / group_aggregate(sum([T::COL]), {}, query_filters())` | MEASURE | |
| `list` | **Unsupported** — omit + log | — | |

## §4a — Translating `type: number` (derived measure) SQL

After inlining all `${}` references, translate the resulting SQL expression:

| SQL pattern | ThoughtSpot formula |
|---|---|
| `1.0 * A / NULLIF(B, 0)` | `safe_divide ( A_formula , B_formula )` — drop the `1.0 *` multiplier |
| `SUM(col) / SUM(other)` | `safe_divide ( sum ( [T::col] ) , sum ( [T::other] ) )` |
| `CASE WHEN ... END` | `if ( cond ) then a else b` |
| `COALESCE(a, 0)` | `ifnull ( a , 0 )` |
| `NULLIF(a, 0)` (not in denominator) | `if ( a = 0 ) then null else a` |
| SQL arithmetic | Direct TS arithmetic (`+`, `-`, `*`, `/`) |
| `SUM(CASE WHEN cond THEN col END)` | `sum_if ( cond , [T::col] )` |

## §4b — Filtered measures (`filters:` on measures)

LookML:
```ruby
measure: complete_orders {
  type: count_distinct
  sql: ${TABLE}.ORDER_ID ;;
  filters: [order_status: "Complete"]
}
```

ThoughtSpot:
```
count_if ( [ORDER_FACT::ORDER_STATUS] = 'Complete' , [ORDER_FACT::ORDER_ID] )
→ column_type: MEASURE, index_type: DONT_INDEX
```

For `filters:` with multiple conditions: AND them together:
```
sum_if ( [T::STATUS] = 'Complete' and [T::CHANNEL] = 'ONLINE' , [T::REVENUE] )
```
