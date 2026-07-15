<!-- currency: looker — 2026-07 (inaugural anchor; verify in next external sweep) -->

# LookML → ThoughtSpot Formula Translation Reference

Covers all measure types, dimension types, and expression patterns found in
LookML views. Source fixture: `skilltest-orders` (ORDER_FACT + CUSTOMER_DIM).

---

## 1. Syntax Basics

### Column references

| LookML | ThoughtSpot |
|--------|-------------|
| `${TABLE}.COLUMN_NAME` | `[VIEW_NAME::COLUMN_NAME]` |
| `${view_name.field_name}` | inline the target field's expression |
| `${field_name}` (within same view) | inline the field's expression |

**Rule:** ThoughtSpot formulas have no variables or field references — every
cross-field reference must be inlined at translation time.

**Example:**

LookML:
```ruby
measure: average_order_value {
  type: number
  sql: 1.0 * ${total_net_revenue} / NULLIF(${order_count}, 0) ;;
}
measure: total_net_revenue { type: sum; sql: ${TABLE}.NET_REVENUE ;; }
measure: order_count       { type: count_distinct; sql: ${TABLE}.ORDER_ID ;; }
```

ThoughtSpot (fully inlined):
```
safe_divide ( sum ( [ORDER_FACT::NET_REVENUE] ) , unique count ( [ORDER_FACT::ORDER_ID] ) )
```

---

## 2. Measure Type Mapping

| LookML `type:` | ThoughtSpot formula | TS `column_type` | Notes |
|----------------|--------------------|--------------------|-------|
| `sum` | `sum ( [T::COL] )` | `MEASURE` | Standard sum |
| `count` | `count ( [T::COL] )` | `MEASURE` | Includes nulls |
| `count_distinct` | `unique count ( [T::COL] )` | `MEASURE` | **Never** use `aggregation: COUNT_DISTINCT` — Invariant I5 |
| `average` | `average ( [T::COL] )` | `MEASURE` | |
| `max` | `max ( [T::COL] )` | `MEASURE` | |
| `min` | `min ( [T::COL] )` | `MEASURE` | |
| `number` (derived) | inline all `${}` refs, then translate SQL | `MEASURE` | See §4 |
| `sum_distinct` | `sum ( [T::COL] )` grouped by distinct key | `MEASURE` | Rare; use `group_aggregate` if LOD needed |
| `list` | not directly supported | — | Approximate with `concat` or omit |
| `running_total` | `cumulative_sum ( sum([T::COL]), [date_col] )` | `MEASURE` | |
| `percent_of_total` | `sum([T::COL]) / group_aggregate(sum([T::COL]), {}, query_filters())` | `MEASURE` | |

---

## 3. Dimension Type Mapping

| LookML `type:` | ThoughtSpot `column_type` | Notes |
|----------------|--------------------------|-------|
| `string` | `ATTRIBUTE` | Direct column reference |
| `number` | `ATTRIBUTE` (if used as ID/key) or `MEASURE` (if aggregated) | `primary_key: yes` → always `ATTRIBUTE` |
| `yesno` | `ATTRIBUTE` | Boolean; TS renders as TRUE/FALSE |
| `time` | `ATTRIBUTE` | Use TS date functions if derived |
| `date` | `ATTRIBUTE` | |
| `tier` | Translate to `if...then...else` | See §5 |
| `duration` | `diff_days` / `diff_months` / `diff_years` | |
| `location` | Not supported — omit | |

---

## 4. SQL Expression → ThoughtSpot Formula Patterns

### Arithmetic

| SQL / LookML sql: | ThoughtSpot formula |
|-------------------|---------------------|
| `A + B` | `[T::A] + [T::B]` |
| `A - B` | `[T::A] - [T::B]` |
| `A * B` | `[T::A] * [T::B]` |
| `A / B` | `[T::A] / [T::B]` (may produce NULL on zero) |
| `1.0 * A / NULLIF(B, 0)` | `safe_divide ( A_expr , B_expr )` |
| `CASE WHEN ... END` | `if ... then ... else` |
| `COALESCE(A, 0)` | `ifnull ( [T::A] , 0 )` |
| `NULLIF(A, 0)` | use `safe_divide` when in denominator, else `if [T::A] = 0 then null else [T::A]` |
| `IFF(cond, a, b)` | `if ( cond ) then a else b` |

### Aggregates inside SQL expressions

| LookML sql: pattern | ThoughtSpot formula |
|---------------------|---------------------|
| `SUM(${TABLE}.COL)` | `sum ( [T::COL] )` |
| `COUNT(DISTINCT ${TABLE}.COL)` | `unique count ( [T::COL] )` |
| `AVG(${TABLE}.COL)` | `average ( [T::COL] )` |
| `MAX(${TABLE}.COL)` | `max ( [T::COL] )` |
| `MIN(${TABLE}.COL)` | `min ( [T::COL] )` |

### String functions

| SQL / LookML | ThoughtSpot |
|--------------|-------------|
| `UPPER(col)` | `sql_string_op ( "UPPER({0})" , [T::COL] )` — no native `upper` in ThoughtSpot |
| `LOWER(col)` | `sql_string_op ( "LOWER({0})" , [T::COL] )` — no native `lower` in ThoughtSpot |
| `CONCAT(a, b)` | `concat ( [T::A] , [T::B] )` |
| `SUBSTR(col, pos, len)` | `substr ( [T::COL] , pos , len )` |
| `LENGTH(col)` | `strlen ( [T::COL] )` |
| `REPLACE(col, old, new)` | `replace ( [T::COL] , 'old' , 'new' )` |
| `CAST(col AS INTEGER)` | `to_integer ( [T::COL] )` |

### Date functions

| SQL / LookML | ThoughtSpot |
|--------------|-------------|
| `DATEADD(day, 30, col)` | `add_days ( [T::COL] , 30 )` |
| `DATEDIFF(day, a, b)` | `diff_days ( [T::B] , [T::A] )` |
| `DATE_TRUNC('month', col)` | `start_of_month ( [T::COL] )` |
| `DATE_TRUNC('quarter', col)` | `start_of_quarter ( [T::COL] )` |
| `EXTRACT(MONTH FROM col)` | `month ( [T::COL] )` |
| `EXTRACT(YEAR FROM col)` | `year ( [T::COL] )` |
| `EXTRACT(DAY FROM col)` | `day ( [T::COL] )` |
| `CURRENT_DATE` | `today ()` |
| `CURRENT_TIMESTAMP` | `now ()` |

### JSON / VARIANT path access — bracket notation only

A LookML `sql:` expression may carry a warehouse JSON path (e.g. on Snowflake,
`${TABLE}.raw:address.city`). When wrapped in a `sql_*_op` pass-through, ThoughtSpot's
parser **rejects the colon-and-dot syntax** — convert each segment to `['key']` bracket
notation:

| LookML `sql:` (Snowflake colon path) | ThoughtSpot formula |
|--------------|-------------|
| `PARSE_JSON(${TABLE}.RAW):address.city` | `sql_string_op ( "PARSE_JSON({0})['address']['city']" , [T::RAW] )` |

Canonical rule:
[../../schemas/thoughtspot-formula-patterns.md](../../schemas/thoughtspot-formula-patterns.md#json--variant-path-access--bracket-notation-only).
The bracket form must be valid SQL for the explore's warehouse dialect — verified for
Snowflake (2026-07-15); confirm for BigQuery/Redshift/etc. before relying on it.

---

## 5. LookML `type: tier` → ThoughtSpot `if...then...else`

LookML:
```ruby
dimension: order_size_tier {
  type: tier
  tiers: [1, 5, 10, 25]
  sql: ${TABLE}.QUANTITY_ORDERED ;;
}
```

ThoughtSpot:
```
if ( [ORDER_FACT::QUANTITY_ORDERED] < 1 ) then "< 1"
else if ( [ORDER_FACT::QUANTITY_ORDERED] < 5 ) then "1 - 4"
else if ( [ORDER_FACT::QUANTITY_ORDERED] < 10 ) then "5 - 9"
else if ( [ORDER_FACT::QUANTITY_ORDERED] < 25 ) then "10 - 24"
else "25+"
```

---

## 6. LookML `filters:` on Measures → `count_if` / `average_if`

LookML:
```ruby
measure: completed_orders {
  type: count_distinct
  sql: ${TABLE}.ORDER_ID ;;
  filters: [order_status: "Complete"]
}
```

ThoughtSpot — use `count_if`:
```
count_if ( [ORDER_FACT::ORDER_STATUS] = 'Complete' , [ORDER_FACT::ORDER_ID] )
```

For filtered sums, use `if...then...else` inside `sum`:
```
sum ( if [ORDER_FACT::ORDER_STATUS] = 'Complete' then [ORDER_FACT::NET_REVENUE] else 0 )
```

---

## 6a. Null Checks in `count_if` / `sum_if` Conditions

LookML filtered measures sometimes check for non-null values using SQL `IS NOT NULL`.

**Do NOT use `is_null()` or `isnull()` in ThoughtSpot formulas.** These functions are
not supported on all ThoughtSpot instances (e.g. ps-internal.thoughtspot.cloud rejects
them with `Search did not find "is_null ("` errors).

**Correct pattern — use `!= null` comparison:**

| LookML / SQL intent | ThoughtSpot formula |
|---------------------|---------------------|
| `col IS NOT NULL` | `[T::col] != null` |
| `col IS NULL` | `[T::col] = null` |
| `not is_null([col])` | `[col] != null` |

Example — counting sessions that reached an event:

LookML:
```ruby
measure: count_sessions_event1 {
  type: count_distinct
  sql: ${event_session_funnel.session_id} ;;
  filters: [event_session_funnel.event1_time: "-NULL"]
}
```

ThoughtSpot:
```
count_if ( [EVENT_SESSION_FUNNEL::Event1 Time] != null , [EVENT_SESSION_FUNNEL::Session Id] )
```

Multi-condition (funnel step 1 → 2 in order):
```
count_if (
  [EVENT_SESSION_FUNNEL::Event1 Time] != null
  and [EVENT_SESSION_FUNNEL::Event2 Time] != null
  and [EVENT_SESSION_FUNNEL::Event1 Time] < [EVENT_SESSION_FUNNEL::Event2 Time]
  , [EVENT_SESSION_FUNNEL::Session Id]
)
```

---

## 7. Cross-View Field References (`explore` joins)

LookML resolves `${customer_dim.region}` through the explore join.
ThoughtSpot resolves cross-table references through Model joins.

**Pattern:** Replace `${view.field}` with `[DIM_TABLE::COLUMN]` — ThoughtSpot
uses the join defined in the Model TML to resolve it automatically.

LookML (in explore tile):
```
dimension: region { sql: ${customer_dim.region} ;; }
```

ThoughtSpot search query or formula:
```
[CUSTOMER_DIM::REGION]
```

---

## 8. Model Conversion Invariants (quick reference)

| # | Rule |
|---|------|
| I1 | Every `formulas[]` entry needs a matching `columns[]` entry — otherwise the formula is silently dropped |
| I2 | No `aggregation:` key inside `formulas[]` blocks |
| I3 | `index_type: DONT_INDEX` on any computed numeric measure column |
| I4 | Join `id` must exactly equal join `name` |
| I5 | `count_distinct` → `unique count()` formula, NEVER `aggregation: COUNT_DISTINCT` |
| I6 | Connection referenced by name, not GUID |
| I7 | Check ThoughtSpot formula reference before declaring a pattern untranslatable |
| I8 | No duplicate `column_id` values across the entire `columns[]` list |

---

## 9. Fixture Translation: `skilltest-orders`

Complete translation of all measures from `order_fact.view.lkml`.

### `total_net_revenue` (`type: sum`)
```ruby
# LookML
measure: total_net_revenue { type: sum; sql: ${net_revenue} ;; }
# net_revenue is a hidden dimension: sql: ${TABLE}.NET_REVENUE
```
ThoughtSpot formula:
```
sum ( [ORDER_FACT::NET_REVENUE] )
```
`column_type: MEASURE`

---

### `order_count` (`type: count_distinct`)
```ruby
# LookML
measure: order_count { type: count_distinct; sql: ${TABLE}.ORDER_ID ;; }
```
ThoughtSpot formula:
```
unique count ( [ORDER_FACT::ORDER_ID] )
```
`column_type: MEASURE` — Invariant I5 applies; do NOT use `aggregation: COUNT_DISTINCT`.

---

### `average_order_value` (`type: number`, cross-measure)
```ruby
# LookML
measure: average_order_value {
  type: number
  sql: 1.0 * ${total_net_revenue} / NULLIF(${order_count}, 0) ;;
}
```
ThoughtSpot formula (all refs inlined):
```
safe_divide ( sum ( [ORDER_FACT::NET_REVENUE] ) , unique count ( [ORDER_FACT::ORDER_ID] ) )
```
`column_type: MEASURE`, `index_type: DONT_INDEX` (Invariant I3)

---

### Customer dimensions (pass-through via join)

| LookML field | ThoughtSpot column_id | column_type |
|---|---|---|
| `customer_dim.region` | `CUSTOMER_DIM::REGION` | ATTRIBUTE |
| `customer_dim.customer_segment` | `CUSTOMER_DIM::CUSTOMER_SEGMENT` | ATTRIBUTE |
| `customer_dim.loyalty_tier` | `CUSTOMER_DIM::LOYALTY_TIER` | ATTRIBUTE |

No formula needed — these are direct column references resolved through the Model join.

---

## 10. ThoughtSpot Advanced Patterns (from Formula Guide v10.14)

### % of Total (using `group_aggregate`)
```
sum ( [T::REVENUE] ) / group_aggregate ( sum ( [T::REVENUE] ) , {} , query_filters() )
```

### 3-Row Moving Average
```
moving_average ( sum ( [T::REVENUE] ) , 3 , -1 , [DATE_DIM::FULL_DATE] )
```

### Semi-Additive (last inventory balance)
```
last_value ( sum ( [T::INVENTORY] ) , { [PRODUCT_DIM::PRODUCT_KEY] } , [DATE_DIM::FULL_DATE] )
```

### Running Total
```
cumulative_sum ( sum ( [T::REVENUE] ) , [DATE_DIM::FULL_DATE] )
```

### Conditional Channel Group (from `retail_model_export.tml`)
```
if ( [ORDER_FACT::ORDER_CHANNEL] in { "EMAIL" , "SMS" } ) then "Digital Direct"
else if ( [ORDER_FACT::ORDER_CHANNEL] in { "STORE" } ) then "In-Store"
else "Other"
```
