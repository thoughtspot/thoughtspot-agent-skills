# Open Items — ts-convert-from-looker

Tracks unverified behaviour, deferred work, and known gaps.
Status: OPEN | VERIFIED | DEFERRED | WONT-FIX

---

## #1 — `type: number` cross-measure SQL inlining edge cases — OPEN

**Question:** When a `type: number` measure references another measure that itself references
a third field via `${}`, does the recursive inline always produce a valid ThoughtSpot formula?

**Known case that works:** `average_order_value` = `1.0 * ${total_net_revenue} / NULLIF(${order_count}, 0)`
→ `safe_divide ( sum ( [ORDER_FACT::NET_REVENUE] ) , unique count ( [ORDER_FACT::ORDER_ID] ) )` — verified.

**Open question:** What if the intermediate measure is itself a `type: number` with multi-step SQL?

**Action:** Test a 3-level chain against a live ThoughtSpot instance.

---

## #2 — `derived_table` SQL View: column list from SELECT — VERIFIED via docs 2026-07-22

**Answer:** Columns are **required**, not inferred. The shared schema
`thoughtspot-sql-view-tml.md` states: `sql_view.sql_view_columns: Yes — At least one
column required` and `sql_output_column: Yes — Must match a column name or alias from
the SQL query output. Case-sensitive.`

The migration must parse SELECT output columns (or accept a user-provided column list)
and emit them in the SQL View TML.

---

## #3 — Multiple explores that share views: one model or separate models — OPEN

**Current default:** One ThoughtSpot model per LookML explore.

**Question:** When two explores share many of the same views (e.g. `order_fact`, `customer_dim`
appear in both `explore: orders` and `explore: marketing`), should the skill offer to merge
them into a single ThoughtSpot model with a superset of joins?

**Trade-offs:**
- Separate models: simpler, closer to LookML semantics, but user must switch between models
- Merged model: single search surface, but may introduce accidental join paths

**Action:** Add a prompt in Step 6 asking the user which approach they prefer when multiple
explores share views. Default to separate models.

---

## #4 — `sql_always_where:` → ThoughtSpot RLS — OPEN

**Question:** Can `sql_always_where:` conditions on an explore be expressed as ThoughtSpot
RLS rules via the API, or do they need to be manually configured in the ThoughtSpot UI?

**Current handling:** Omit + log.

**Action:** Check ThoughtSpot REST API v2 for RLS/row-security endpoints. If available,
add an optional Step 9.5 that creates RLS rules from `sql_always_where:` conditions.

---

## #5 — Liveboard layout grid coordinates — VERIFIED via docs 2026-07-22

**Answer:** `layout` is optional in the liveboard TML schema. ThoughtSpot renders
liveboards with auto-layout when `layout_config` is absent — tiles are arranged in
order. The current handling (emit tiles in order, omit `layout_config`) is correct.

Explicit grid mapping from LookML `tile_size:` hints is a potential enhancement but
not required for a correct migration.

---

## #6 — `value_format_name:` → ThoughtSpot formatting — VERIFIED via docs 2026-07-22

**Answer:** Formatting is available at the **Model column** level via
`properties.format_pattern` (e.g., `"#,##0"`, `"#,##0.0%"`) and
`properties.currency_type.iso_code`. Answer TML does not have `format_pattern`.

Map Looker `value_format_name` to ThoughtSpot `format_pattern` on Model columns:
`usd` → `"$#,##0.00"`, `percent_0` → `"#,##0%"`, `decimal_2` → `"#,##0.00"`, etc.

---

## #7 — `extends:` circular extension detection — OPEN

**Question:** Can LookML view inheritance form a cycle (A extends B extends A)?

**Current handling:** Flatten bottom-up; no cycle check.

**Action:** Add cycle detection to the `extends:` resolution in Step 3b. If a cycle
is detected, surface it as a hard blocker (LookML itself doesn't allow cycles, but
malformed files may contain them).

---

## #8 — `explore: name { from: other_view }` aliasing — OPEN

**Question:** When an explore uses `from:` to alias a view under a different name,
does the resulting join `sql_on:` still reference the original view name or the alias?

**Example:**
```lkml
explore: orders {
  from: order_fact          # explore named 'orders' but based on view 'order_fact'
  join: customer_dim {
    sql_on: ${orders.customer_key} = ${customer_dim.customer_key} ;;
  }
}
```

**Question:** Does `${orders.customer_key}` resolve to `ORDER_FACT::CUSTOMER_KEY`?

**Current handling:** Resolve alias to underlying view at parse time.

**Action:** Verify with a fixture that uses `from:` aliasing. Confirm the ThoughtSpot
table name in the join `on:` clause uses the physical view name (ORDER_FACT), not the alias.

---

## #9 — `looker_waterfall` chart type — VERIFIED via docs 2026-07-22

**Answer:** `WATERFALL` is confirmed valid in `thoughtspot-chart-types.md`
(dim + measure, running contribution). The coverage matrix mapping is correct.

---

## #10 — `type: list` workaround via SQL — OPEN

**Question:** When a LookML `type: list` dimension aggregates values (e.g. `GROUP_CONCAT`),
is there a ThoughtSpot `sql_string_aggregate_op("LISTAGG(...)")` pass-through equivalent?

**Current handling:** Omit + log as unsupported.

**Action:** Check if `sql_string_aggregate_op` works for this use case. If so, promote
from L2 (HIGH unsupported) to a translated construct with a PT1 (pass-through) marker.

---

## #11 — `ts tml import` CLI flag is `--policy` not `--import-policy` — VERIFIED

**Finding (2026-06, qwiklab_ecomm migration):** `ts tml import` uses `--policy` (not
`--import-policy`). Using `--import-policy` produces `No such option: --import-policy`.

**Also verified (2026-06, stdin-only era — superseded, see update below):**
- `PARTIAL` is the recommended policy for first-run migrations — objects that parse
  correctly import even if others fail.

**Update (2026-07-11, audit 5.1):** ts-cli v0.27.0 added `--file`/`--dir` to `ts tml
import`/`ts tml lint`, so the stdin-JSON-array requirement above no longer holds — a
directory path is now accepted directly. SKILL.md Step 8 migrated from the
`python3 -c "...json.dumps(...)..." | ts tml import` wrapper to
`ts tml import --dir {output_dir} --order tableau --policy PARTIAL --create-new
--profile {name}`. The `--policy` (not `--import-policy`) flag name finding above is
unaffected and still applies.

**SKILL.md:** Step 8 updated with the `--dir`/`--order tableau` invocation.

---

## #12 — SQL View `sql_output_column` must be UPPERCASE for Snowflake — VERIFIED

**Finding (2026-06, qwiklab_ecomm migration):** Snowflake normalizes all unquoted
identifiers to uppercase. ThoughtSpot's `sql_output_column` comparison is case-sensitive,
so lowercase values like `session_id` do not match Snowflake's `SESSION_ID`.

**Error symptom:** `Column name [session_id, identifier, ...] is not present in SQL query`

**Fix:** Every `sql_output_column` value must be UPPERCASE, and the SQL SELECT must
use explicit `AS UPPERCASE_ALIAS` forms. Do not use `SELECT *` — always write an explicit
column list with uppercase aliases.

**Reference:** [thoughtspot-sql-view-tml.md](../../../shared/schemas/thoughtspot-sql-view-tml.md) — Snowflake note added to `sql_view_columns[]` section.

---

## #13 — `is_null()` / `isnull()` not supported on all ThoughtSpot instances — VERIFIED

**Finding (2026-06, qwiklab_ecomm migration on ps-internal.thoughtspot.cloud):**
The formula functions `is_null()` and `isnull()` are rejected with:
`Search did not find "is_null (" in your data or metadata. Expecting one of the valid keywords...`

**Fix:** Use `[col] != null` for "is not null" and `[col] = null` for "is null" in
all ThoughtSpot formula expressions.

Example:
```
# WRONG — not universally supported:
count_if ( not is_null ( [T::Col] ) , [T::Id] )

# CORRECT:
count_if ( [T::Col] != null , [T::Id] )
```

**Reference:** [lookml-to-ts-formula-translation.md](../../../shared/mappings/looker/lookml-to-ts-formula-translation.md) — §6a added.
