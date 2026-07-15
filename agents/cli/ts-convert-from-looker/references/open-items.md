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

## #2 — `derived_table` SQL View: column list from SELECT — OPEN

**Question:** When generating a SQL View TML from a LookML `derived_table: { sql: "..." }`,
should the column list in the TML be derived by parsing the SELECT clause, or should we
rely on ThoughtSpot's schema inference at import time?

**Concern:** If the SQL references CTEs or complex subqueries, parsing SELECT columns
at migration time is error-prone. ThoughtSpot may infer columns on import.

**Action:** Test a simple `derived_table` SQL View import against a live ThoughtSpot instance.
Confirm whether `columns:` in the SQL View TML is required or optional.

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

## #5 — Liveboard layout grid coordinates — OPEN

**Question:** LookML dashboards with `layout: newspaper` and `tile_size:` hints — can
these be mapped to ThoughtSpot's 12-column responsive grid layout?

**Known:** ThoughtSpot liveboard tiles use `layout_config.default_config` with
`position: {x, y, height, width}`. LookML newspaper layout tiles have implicit
ordering but no pixel coordinates.

**Current handling:** Tiles are emitted in order; layout coordinates not set (ThoughtSpot
uses auto-layout when `layout_config` is absent).

**Action:** Verify whether ThoughtSpot renders liveboards correctly without explicit
`layout_config`. Document the auto-layout behaviour.

---

## #6 — `value_format_name:` → ThoughtSpot formatting — OPEN

**Question:** Is there a way to apply number formatting (`usd`, `percent_0`, `decimal_2`)
in ThoughtSpot Model TML, or only in Answer/Liveboard TML?

**Current handling:** Logged as "format hints to apply manually."

**Action:** Check `thoughtspot-answer-tml.md` and `thoughtspot-liveboard-tml.md` for
format spec fields on `answer_columns`. If present, apply them in Step 10c when
building viz column specs.

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

## #9 — `looker_waterfall` chart type — OPEN

**Question:** Does ThoughtSpot support a WATERFALL chart type in Liveboard TML?

**Current handling:** Mapped in coverage matrix as supported.

**Action:** Confirm `type: WATERFALL` is valid in `chart.type:` in Liveboard Answer TML.
If not, fall back to `BAR` and log.

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
