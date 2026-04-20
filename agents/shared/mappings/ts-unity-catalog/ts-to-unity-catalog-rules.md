# Mapping Rules Reference — ThoughtSpot → Unity Catalog

ThoughtSpot → Unity Catalog Metric View conversion tables. Consult during Steps 7–9
of the convert-ts-to-unity-catalog skill.

---

## Column Type Classification

Apply this decision tree to every column:

```
Is formula_id set?
  YES → measures (if translatable aggregate formula) or
        dimensions (if translatable non-aggregate formula) or
        OMIT (if untranslatable — see Step 9)
  NO  → Is column_type MEASURE?
          YES → measures
          NO  → dimensions
               (including date/timestamp columns — UC has no separate time_dimensions)
```

**Key difference from Snowflake:** Unity Catalog Metric Views have no `time_dimensions`
section. Date and timestamp columns are plain `dimensions`. The `expr` may use date
functions (e.g. `DATE_TRUNC`, `YEAR()`), but the field goes under `dimensions:`.

---

## Aggregation Functions

Used in `expr` for `measures` entries. The aggregation is always **embedded in the expr**
— there is no `default_aggregation` field in UC Metric Views.

| ThoughtSpot `aggregation` | UC `expr` wrapper |
|---|---|
| `SUM` | `SUM(expr)` |
| `COUNT` | `COUNT(expr)` |
| `COUNT_DISTINCT` | `COUNT(DISTINCT expr)` |
| `AVG` / `AVERAGE` | `AVG(expr)` |
| `MIN` | `MIN(expr)` |
| `MAX` | `MAX(expr)` |
| `STD_DEVIATION` | `STDDEV(expr)` *(flag for review — verify Databricks support)* |
| `VARIANCE` | `VARIANCE(expr)` *(flag for review — verify Databricks support)* |
| *(not set on MEASURE)* | `SUM(expr)` *(default)* |

---

## Data Types

Check `db_column_properties.data_type` first (Table TML — most reliable), then fall back
to `db_column_type` (Worksheet TML).

UC Metric View `expr` fields do not require an explicit `data_type` declaration — types
are inferred from the SQL expression. However, the data type determines how ThoughtSpot
column properties map and whether date functions should be applied in `expr`.

| Source field value | Classification | Date expression needed? |
|---|---|---|
| `VARCHAR`, `CHAR`, `TEXT`, `STRING`, `NVARCHAR` | dimension | no |
| `INT`, `INTEGER`, `BIGINT`, `SMALLINT`, `TINYINT` | dimension (or measure if aggregated) | no |
| `FLOAT`, `DOUBLE`, `DECIMAL`, `NUMERIC`, `REAL` | dimension (or measure if aggregated) | no |
| `BOOLEAN`, `BOOL` | dimension | no |
| `DATE` | dimension | optional — `DATE_TRUNC`, `YEAR()`, etc. |
| `DATETIME`, `DATE_TIME` | dimension | optional — `DATE_TRUNC`, etc. |
| `TIMESTAMP`, `TIMESTAMP_NTZ`, `TIMESTAMP_LTZ` | dimension | optional — `DATE_TRUNC`, etc. |
| *(unknown or absent)* | dimension *(default — flag for review)* | no |

**Name-based date heuristics** (use only when `db_column_type` is unavailable):

Column name ends with or equals: `_date`, `_at`, `_time`, `_ts`, `_datetime`,
`date`, `time`, `timestamp` → classify as a date dimension.

---

## Name Generation Rules

When generating UC field names from ThoughtSpot display names:

1. Convert to lowercase.
2. Replace any sequence of non-alphanumeric characters with a single underscore `_`.
3. Strip leading and trailing underscores.
4. If the result is empty, use `field`.
5. If the result starts with a digit, prepend `field_`.
6. Truncate to 255 characters if needed.
7. **Check for semantic loss:** if the original name started with `#` or a symbol that
   carried meaning (e.g. `# of Products` → `of_products`), flag at the checkpoint and
   suggest a more meaningful name (e.g. `product_count`).

Always put the original ThoughtSpot display name in `display_name:` and/or `synonyms:`.

```python
import re
def to_snake(name):
    s = re.sub(r'_+', '_', re.sub(r'[^a-z0-9]', '_', name.lower())).strip('_')
    if not s:            s = 'field'
    elif s[0].isdigit(): s = 'field_' + s
    return s
```

| ThoughtSpot display name | Generated UC name | Flag? |
|---|---|---|
| `Revenue` | `revenue` | no |
| `Sale Date` | `sale_date` | no |
| `# of Products` | `of_products` | **yes** — suggest `product_count` |
| `YoY Growth (%)` | `yoy_growth` | no |
| `2024 Sales` | `field_2024_sales` | no *(digit prefix fixed)* |

---

## Source Table Identification

Unity Catalog Metric Views have exactly one primary `source:` table. All other tables
join to the source (or chain off another join). Identifying the source table correctly
determines the entire join tree structure.

**Algorithm:**

1. Collect all table names from `model_tables[]` (Model TML) or `table_paths[]` (Worksheet TML)
2. Build a set of left_tables and right_tables from all join conditions
3. Identify **fact table candidates** — tables that are left_table in joins but never right_table
4. Among candidates, prefer the one with the most MEASURE columns
5. If multiple candidates remain or all tables appear on both sides, ask the user

```python
left_tables  = {j['left_table']  for j in joins}
right_tables = {j['right_table'] for j in joins}
candidates   = left_tables - right_tables   # never a join target

if len(candidates) == 1:
    source_table = candidates.pop()
elif len(candidates) > 1:
    # Rank by measure count
    source_table = max(candidates, key=lambda t: measure_count.get(t, 0))
else:
    # All tables appear on both sides — ask user
    source_table = ask_user(tables)
```

---

## Join Tree Construction

Convert ThoughtSpot's flat list of join conditions into UC's nested `joins:` hierarchy.

**Input:** flat list of `(left_table, left_col, right_table, right_col)` tuples

**Goal:** tree rooted at `source_table` where each node's children are the tables
it directly joins to

**Algorithm:**

```python
# 1. Build adjacency: which table is the "right" side of joins from each table?
children = {}   # left_table -> list of (right_table, left_col, right_col)
for j in joins:
    children.setdefault(j['left_table'], []).append(j)

# 2. BFS/DFS from source_table to build the nested join structure
def build_joins(table_name, visited=None):
    if visited is None: visited = set()
    visited.add(table_name)
    result = []
    for j in children.get(table_name, []):
        right = j['right_table']
        if right in visited: continue  # cycle guard
        parent_ref = 'source' if table_name == source_table else table_alias(table_name)
        entry = {
            'name': table_alias(right),
            'source': fully_qualified(right),
            'on': f"{parent_ref}.{j['left_col']} = {table_alias(right)}.{j['right_col']}"
        }
        nested = build_joins(right, visited.copy())
        if nested:
            entry['joins'] = nested
        result.append(entry)
    return result
```

**`table_alias(name)`** — Use `to_snake(name)` for the join `name` value. If the same
physical table appears twice (aliased in ThoughtSpot using `model_tables[].alias`), use
the alias directly (it is already unique by design in ThoughtSpot).

**If a table is unreachable** from the source via joins (disconnected component):
- Flag in the Unmapped Report
- Either ask the user for the join condition, or omit it entirely

---

## Column `expr` Construction

After the source table and join tree are established, build `expr` values for each field.

**Source table columns:**

```python
# Column from the main source table — bare column name
expr = physical_col_name
# If reserved word, backtick-quote:
expr = f"`{physical_col_name}`"   # e.g. `date`, `order`, `name`
```

**Joined table columns:**

```python
# Column from a joined table — join_alias.physical_col_name
join_alias = table_alias(table_name)   # flat namespace; works for any nesting depth
expr = f"{join_alias}.{physical_col_name}"
# If reserved word:
expr = f"{join_alias}.`{physical_col_name}`"
```

**Aggregate (measure) exprs:**

```python
# Wrap the base expression in the aggregation function
base_expr = f"{join_alias}.{physical_col_name}"  # or bare for source table
agg_func = agg_map[column.get('aggregation', 'SUM')]
expr = f"{agg_func}({base_expr})"
```

---

## UC Field Entry Templates

**Dimension entry:**
```yaml
- name: "{snake_case_name}"
  expr: "{column_or_expression}"
  display_name: "{original_display_name}"
  synonyms:
    - "{additional ThoughtSpot synonym}"
  comment: "{description or [TS AI Context] {ai_context} if present}"
```

**Measure entry (physical column):**
```yaml
- name: "{snake_case_name}"
  expr: "{AGG}({column_expression})"
  display_name: "{original_display_name}"
  synonyms:
    - "{additional synonym}"
  comment: "{description}"
```

**Measure entry — composed (ratio/derived formula):**
```yaml
- name: "{snake_case_name}"
  expr: "try_divide(MEASURE({numerator_measure_name}), MEASURE({denominator_measure_name}))"
  display_name: "{original_display_name}"
  comment: "{description}"
```

**Measure entry — filtered:**
```yaml
- name: "{snake_case_name}"
  expr: "SUM({column}) FILTER (WHERE {condition})"
  display_name: "{original_display_name}"
  comment: "{description}"
```

**Measure entry — semi-additive (window):**
```yaml
- name: "{snake_case_name}"
  expr: "SUM({column})"
  display_name: "{original_display_name}"
  comment: "{description}"
  window:
    - order: "{date_dimension_name}"
      range: "{trailing N unit | cumulative | current | all}"
      semiadditive: last    # or first
```

**Omit unsupported field** — Do NOT include `data_type` on measures. UC infers types.
Do NOT include placeholder `expr` values for untranslatable formulas.

---

## Relationship Naming Conventions

UC join `name` values serve as both the alias in `on:` clauses and the prefix in `expr`
column references. Choose names that:

1. Match `to_snake(table_display_name)` or `to_snake(alias)` from ThoughtSpot
2. Are globally unique within the metric view
3. Avoid SQL reserved words
4. Match the physical table alias if ThoughtSpot uses `model_tables[].alias`

If two joins use the same physical table (e.g. `DISTRICT` as both `client_district` and
`account_district`), generate distinct names: `client_district`, `account_district`.

---

## Multi-Column Join Conditions

ThoughtSpot join conditions with multiple key pairs (`AND`) map to multi-column `on:` clauses:

**ThoughtSpot:** `[TABLE_A::KEY1] = [TABLE_B::KEY1] AND [TABLE_A::KEY2] = [TABLE_B::KEY2]`

**UC:** `on: source.KEY1 = dim.KEY1 AND source.KEY2 = dim.KEY2`

`OR` join conditions have no clean UC equivalent. Log in Unmapped Report as a manual
review item and use the first condition only, or ask user.
