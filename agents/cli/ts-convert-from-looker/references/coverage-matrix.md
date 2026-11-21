# Coverage Matrix: LookML → ThoughtSpot Model + Liveboard

What `ts-convert-from-looker` maps and what it does not.
Use this as the canonical limitations reference for audit reports and migration summaries.

---

## Mapped Constructs

### Structure and Schema

| # | LookML Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 1 | `view: name { sql_table_name: DB.SCHEMA.TABLE }` | Table TML | One Table TML per unique physical table |
| 2 | `view: name { derived_table: { sql: "..." } }` | SQL View TML (`*.sql_view.tml`) | PDT scheduling directives stripped; SQL adapted to target warehouse dialect; dimensions → `sql_view_columns:`; measures → `formulas:`. See SKILL.md Step 5b. |
| 3 | `connection: "name"` in model | `connection.name:` in all Table TMLs | By display name, never GUID — Invariant I6 |
| 4 | `explore: name { ... }` | ThoughtSpot Model TML | One model per explore |
| 5 | `explore: name { label: "..." }` | Model `name:` | Prefer label over raw explore name |
| 6 | `join: view_name { type: left_outer \| full_outer \| inner \| cross }` | Model `joins[].type:` | Mapped in Step 6c |
| 7 | `join: view_name { relationship: many_to_one \| one_to_many \| ... }` | Model `joins[].cardinality:` | Mapped in Step 6d |
| 8 | `join: view_name { sql_on: ${a.col} = ${b.col} ;; }` | `joins[].on:` | `${}` → `[TABLE::COL]` substitution |
| 9 | `include: "views/*.view.lkml"` glob | All matching view files parsed | Expanded at parse time |
| 10 | `extends: [parent_view]` | Flattened at parse time | Child fields override parent; new fields appended |

### Dimension Types

| # | LookML `type:` | ThoughtSpot `column_type` | Notes |
|---|---|---|---|
| 11 | `string` | `ATTRIBUTE` | Direct column ref |
| 12 | `number` (non-aggregated / ID) | `ATTRIBUTE` | When used as key or label, not as a metric |
| 13 | `yesno` | `ATTRIBUTE` | Renders as TRUE/FALSE |
| 14 | `date` | `ATTRIBUTE` | |
| 15 | `time` | `ATTRIBUTE` | |
| 16 | `tier` | `ATTRIBUTE` via `if/then/else if` formula | Bucket boundaries from LookML `tiers:` |
| 17 | `duration` (diff between date fields) | `ATTRIBUTE` via `diff_days/diff_months/diff_years` | |
| 18 | `hidden: yes` (used by measures) | Included in TML, no hidden equivalent | `index_type: DONT_INDEX` applied |
| 19 | `label:` | Column `name:` (display name) | Preferred over raw field name |
| 20 | `primary_key: yes` | `column_type: ATTRIBUTE` | FK/PK used in joins |

### Measure Types

| # | LookML `type:` | ThoughtSpot formula | Notes |
|---|---|---|---|
| 21 | `sum` | `sum ( [T::COL] )` | |
| 22 | `count` | `count ( [T::COL] )` | |
| 23 | `count_distinct` | `unique count ( [T::COL] )` formula | Invariant I5: NEVER `aggregation: COUNT_DISTINCT` |
| 24 | `average` | `average ( [T::COL] )` | |
| 25 | `max` | `max ( [T::COL] )` | |
| 26 | `min` | `min ( [T::COL] )` | |
| 27 | `number` (derived, inline SQL) | Inlined + translated ThoughtSpot formula | See SKILL.md §4a |
| 28 | `sum_distinct` | `sum ( [T::COL] )` with user review | Looker deduplication semantics differ |
| 29 | `running_total` | `cumulative_sum ( sum ( [T::COL] ) , [sort_col] )` | Requires sort column identification |
| 30 | `percent_of_total` | `sum([T::COL]) / group_aggregate(sum([T::COL]), {}, query_filters())` | |

### Formula Translation — Scalar SQL Patterns

| # | LookML SQL pattern | ThoughtSpot formula |
|---|---|---|
| 31 | `${TABLE}.COL` | `[VIEW_NAME::COL]` |
| 32 | `${field_name}` (same view) | Inline that field's resolved expression |
| 33 | `${view.field_name}` (cross view) | Inline target field's resolved expression |
| 34 | `1.0 * A / NULLIF(B, 0)` | `safe_divide ( A , B )` — drop `1.0 *` |
| 35 | `NULLIF(expr, 0)` in denominator | `safe_divide()` |
| 36 | `COALESCE(a, b)` | `ifnull ( a , b )` |
| 37 | `CASE WHEN c THEN a ELSE b END` | `if ( c ) then a else b` |
| 38 | `SUM(CASE WHEN cond THEN col END)` | `sum_if ( cond , [T::col] )` |
| 39 | `COUNT(DISTINCT col)` | `unique count ( [T::col] )` |
| 40 | `UPPER(col)` / `LOWER(col)` | `sql_string_op ( "UPPER({0})" , [T::col] )` / `sql_string_op ( "LOWER({0})" , [T::col] )` — no native `upper`/`lower` in ThoughtSpot |
| 41 | `CONCAT(a, b)` | `concat ( a , b )` |
| 42 | Date arithmetic (`DATEADD`, `DATEDIFF`) | `add_days/diff_days/diff_months/diff_years` |
| 43 | `EXTRACT(MONTH FROM col)` | `month ( [T::col] )` |
| 44 | `CURRENT_DATE` / `CURRENT_TIMESTAMP` | `today ()` / `now ()` |

### Filtered Measures

| # | LookML pattern | ThoughtSpot formula |
|---|---|---|
| 45 | `filters: [field: "value"]` on `count_distinct` | `count_if ( [T::FIELD] = 'value' , [T::COL] )` |
| 46 | `filters: [field: "value"]` on `sum` | `sum_if ( [T::FIELD] = 'value' , [T::COL] )` |
| 47 | `filters: [field: "value"]` on `average` | `average_if ( [T::FIELD] = 'value' , [T::COL] )` |
| 48 | Multiple filter conditions | AND-ed together in the condition |

### Dashboard / Liveboard

| # | LookML Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 49 | `dashboard: name` | Liveboard `name:` | |
| 50 | `tile: { type: single_value }` | `KPI` viz | |
| 51 | `tile: { type: looker_column }` | `COLUMN` chart | |
| 52 | `tile: { type: looker_bar }` | A bar-chart intent in the Step 10b build instructions | SpotterViz resolves the actual chart type/TML; this skill describes intent, not literal `chart.type` |
| 53 | `tile: { type: looker_line }` | A line-chart intent in the Step 10b build instructions | |
| 54 | `tile: { type: looker_pie }` | A pie-chart intent in the Step 10b build instructions | |
| 55 | `tile: { type: looker_scatter }` | A scatter/bubble intent in the Step 10b build instructions | |
| 56 | `tile: { type: looker_grid \| table }` | A table intent in the Step 10b build instructions | |
| 57 | `tile: { type: looker_area }` | An area-chart intent in the Step 10b build instructions | |
| 58 | `listen:` dashboard filters | A per-tile scoped-filter description in the Step 10b build instructions, naming which tiles the filter applies to and which it excludes | SpotterViz, not this skill, emits the actual `filters[]`/`excluded_visualizations` TML — verify the scoping took by exporting the built liveboard (see Step 10b point 6) |
| 59 | `measures:` + `dimensions:` on tile | Named in the tile's own description in the Step 10b build instructions | SpotterViz resolves the actual `search_query`/`answer_columns` TML |
| 60 | `sorts:` on tile | Named in the tile's description, if present | SpotterViz resolves sort; no equivalent for a manual/custom sort — log as a gap |
| 61 | `title:` on tile | Used as the tile's name in the Step 10b build instructions | |

---

## Unmapped Constructs (Limitations)

### HIGH — Functionality loss, no workaround

| # | LookML Construct | Reason | Workaround |
|---|---|---|---|
| L1 | `type: location` (lat/lon) | ThoughtSpot has no spatial column type | Decompose to two separate ATTRIBUTE columns (latitude, longitude); omit spatial-specific formulas |
| L2 | `type: list` | No TS multi-value text column type | Omit + log |
| L3 | Liquid/Jinja templating in `sql_table_name:` or `sql:` (`{{ _user_attributes['schema'] }}`) | Cannot resolve without live Looker connection | Ask user for the resolved literal value |
| L4 | `all_access_grants:` / `required_access_grants:` | Looker permission system has no direct TML equivalent | Omit + log; must reconfigure RLS manually in ThoughtSpot |
| L5 | `persist_with:` / PDT scheduling directives (`datagroup_trigger:`, `sql_trigger:`, `max_cache_age:`) | ThoughtSpot has no PDT scheduling — SQL Views execute at query time | Strip directives; the underlying SQL is translated to SQL View TML (see row #2) |
| L5b | `derived_table: { explore_source: ... }` (native derived table / NDT) | Defined in terms of a Looker explore, not raw SQL — cannot be translated without a live Looker connection | Surface to user, omit + log |

### MEDIUM — Partial translation or review required

| # | LookML Construct | Limitation | Workaround |
|---|---|---|---|
| L6 | `value_format_name:` | No equivalent in Model TML | Log format hints; apply manually in ThoughtSpot Answer/Liveboard |
| L7 | `fields:` on explore (field restriction) | ThoughtSpot shows all model columns | Omit restriction; log in summary; user can hide columns post-import |
| L8 | `set: { fields: [...] }` | LookML field set grouping has no TS equivalent | Ignored at migration time |
| L9 | `sql_always_where:` (session-level row filter) | No equivalent in Model TML | Must configure ThoughtSpot RLS rules separately |
| L10 | `sql_always_having:` (aggregate filter) | No equivalent | Omit + log |
| L11 | Cross-explore field references | ThoughtSpot models are per-explore; cross-explore refs invalid | Flag; user must merge explores into one model if cross-explore queries are needed |
| L12 | `type: sum_distinct` with `sql_distinct_key:` | Deduplication semantics differ from ThoughtSpot | Approximate with `sum()`; flag for review |
| L13 | `looker_funnel` tile type | ThoughtSpot `FUNNEL` chart type is a direct equivalent | SpotterViz builds a `FUNNEL` tile; verify stage order/drop-off |
| L14 | `looker_map` / `looker_geo_choropleth` tile | ThoughtSpot `GEO_AREA`/`GEO_BUBBLE` is a direct equivalent, needs the dimension geo-tagged | SpotterViz builds a geo tile; verify it isn't blank (needs geo config) |
| L15 | Dashboard `link:` (cross-dashboard navigation) | No TS liveboard cross-link equivalent | Omit |
| L16 | `explore: name { from: other_view }` aliasing | Adds a layer of indirection at explore level | Resolve alias to underlying view at parse time; flag if ambiguous |

### LOW — Cosmetic or edge-case

| # | LookML Construct | Limitation | Workaround |
|---|---|---|---|
| L17 | `label:` on explore | Explore label captured; field-level labels in ThoughtSpot are model column names | |
| L18 | `description:` on fields | ThoughtSpot has `description:` on columns — translate where present | Partial — long descriptions may need trimming |
| L19 | `tags:` on fields | ThoughtSpot has no tag equivalent in Model TML | Omit |
| L20 | `view_label:` override on join | Changes how view fields appear in Looker's field picker | ThoughtSpot uses column `name:` — no equivalent |
| L21 | `conditionally_filter:` | Looker UI hint for required filters | No ThoughtSpot equivalent — omit |
| L22 | `datagroup:` definitions | Looker caching policy; not relevant to ThoughtSpot | Omit |
| L23 | `always_filter:` | Looker always-applied filter hint | No ThoughtSpot model equivalent — document for manual Answer/Liveboard filter |
| L24 | `limit:`, `sorts:` on explore | Row limits and default sort on explore | Omit — these are query-time settings in ThoughtSpot |
