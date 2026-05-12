---
name: ts-setup-snowflake-udfs-business-days
description: Creates three Snowflake scalar UDFs for calculating business-day (weekday-only) date differences and elapsed time, then shows the ThoughtSpot formula syntax to use them in any Model. Use this skill whenever the user asks about weekday date calculations, business day counts, working day differences, SLA tracking, ticket age, order fulfillment time, or wants to exclude weekends from any date difference in ThoughtSpot or Snowflake. ThoughtSpot's built-in diff_days/diff_hours/diff_minutes count calendar days — if a user needs weekday-only equivalents, invoke this skill.
---

# ThoughtSpot + Snowflake: Business Day UDFs

ThoughtSpot's built-in `diff_days` / `diff_hours` / `diff_minutes` count calendar days. This skill deploys three Snowflake scalar UDFs that exclude weekends and shows how to call them from ThoughtSpot formulas using `sql_int_op` / `sql_string_op`.

| UDF | Arguments | Returns | Use for |
|---|---|---|---|
| `get_business_minutes_clamped` | `start_ts, end_ts` | INT | Weekday-only elapsed minutes |
| `get_business_days_clamped` | `start_ts, end_ts, inclusive` | INT | Count of weekdays between two timestamps |
| `get_business_duration_str` | `start_ts, end_ts` | STRING | Weekday elapsed time formatted as `HH:MM` |

All three clamp weekend boundaries to the nearest weekday. `get_business_duration_str` calls `get_business_minutes_clamped` by fully qualified name — create minutes first.

Ask one question at a time. Wait for each answer before proceeding.

---

## Prerequisites

- Role with `CREATE FUNCTION` privilege on the target schema
- Access to run SQL in the target database

---

## Step 1 — Collect Target Database and Schema

Ask:

```
Which Snowflake database should these UDFs be created in?
(e.g. ANALYTICS, PROD_DB)
```

Save as `{target_db}` (uppercase).

```
Which schema within {target_db}?
(e.g. PUBLIC, SHARED, UTILS)
```

Save as `{target_schema}` (uppercase).

Confirm before creating anything:

```
Ready to create 3 UDFs in {target_db}.{target_schema}:

  get_business_minutes_clamped(start_ts, end_ts)            → INT
  get_business_days_clamped(start_ts, end_ts, inclusive)    → INT
  get_business_duration_str(start_ts, end_ts)               → STRING

Weekend boundaries are clamped to the nearest weekday.
Existing functions with these names will be replaced (CREATE OR REPLACE).

Proceed? (Y / N)
```

---

## Step 2 — Create the UDFs

Run each statement below in sequence. `get_business_duration_str` depends on `get_business_minutes_clamped` — if step 2a fails, stop and do not proceed.

### 2a. get_business_minutes_clamped

```sql
CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.get_business_minutes_clamped(
    start_ts TIMESTAMP, end_ts TIMESTAMP
)
RETURNS INT
AS
$$
    DATEDIFF('minute',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('second', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('second', -1, DATEADD('day', -1, DATE_TRUNC('day', end_ts)))
            ELSE end_ts
        END
    )
    - (DATEDIFF('week',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('second', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('second', -1, DATEADD('day', -1, DATE_TRUNC('day', end_ts)))
            ELSE end_ts
        END
    ) * 2 * 1440)
$$;
```

### 2b. get_business_days_clamped

```sql
CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.get_business_days_clamped(
    start_ts TIMESTAMP, end_ts TIMESTAMP, inclusive BOOLEAN
)
RETURNS INT
AS
$$
    (DATEDIFF('day',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('day', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('day', -2, DATE_TRUNC('day', end_ts))
            ELSE end_ts
        END
    ) + CASE WHEN inclusive THEN 1 ELSE 0 END)
    - (DATEDIFF('week',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('day', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('day', -2, DATE_TRUNC('day', end_ts))
            ELSE end_ts
        END
    ) * 2)
$$;
```

### 2c. get_business_duration_str

```sql
CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.get_business_duration_str(
    start_ts TIMESTAMP, end_ts TIMESTAMP
)
RETURNS STRING
AS
$$
    FLOOR({target_db}.{target_schema}.get_business_minutes_clamped(start_ts, end_ts) / 60)
    || ':'
    || LPAD(MOD({target_db}.{target_schema}.get_business_minutes_clamped(start_ts, end_ts), 60), 2, '0')
$$;
```

After all three succeed, confirm:

```
✓ get_business_minutes_clamped created
✓ get_business_days_clamped created
✓ get_business_duration_str created
```

---

## Step 3 — Verify

```sql
-- Expected: 4
SELECT {target_db}.{target_schema}.get_business_days_clamped(
    '2026-01-05'::TIMESTAMP, '2026-01-09'::TIMESTAMP, FALSE);

-- Expected: 1440
SELECT {target_db}.{target_schema}.get_business_minutes_clamped(
    '2026-01-05 09:00:00'::TIMESTAMP, '2026-01-06 09:00:00'::TIMESTAMP);

-- Expected: 24:00
SELECT {target_db}.{target_schema}.get_business_duration_str(
    '2026-01-05 09:00:00'::TIMESTAMP, '2026-01-06 09:00:00'::TIMESTAMP);
```

If any returns an unexpected value, re-run `CREATE OR REPLACE` for that function to refresh it.

---

## Step 4 — ThoughtSpot Formula Examples

```
The UDFs are ready. Here's how to use them in ThoughtSpot formulas:

Business days between a date column and today (exclusive):
  sql_int_op ("{target_db}.{target_schema}.get_business_days_clamped({0},{1}, FALSE)", [your date column], today())

Business days between two date columns (inclusive):
  sql_int_op ("{target_db}.{target_schema}.get_business_days_clamped({0},{1}, TRUE)", [start date], [end date])

Weekday elapsed time as HH:MM string:
  sql_string_op ("{target_db}.{target_schema}.get_business_duration_str({0},{1})", [your date column], today())

Weekday-only minutes elapsed:
  sql_int_op ("{target_db}.{target_schema}.get_business_minutes_clamped({0},{1})", [start date], [end date])

To add a formula in ThoughtSpot:
  1. Open the Model → Edit → + Add formula
  2. Paste the expression with your column names substituted and give it a name
     (e.g. "Business Days Open")
  3. Save the formula — this creates the formula definition, but the column
     entry is also required for the formula to be visible to users.
  4. If adding via TML: you must add BOTH a formulas[] entry AND a matching
     columns[] entry with formula_id. Without the columns[] entry the formula
     is hidden. See the TML pattern note below.
```

> **TML pattern — both entries are required:**
>
> ```yaml
> formulas:
> - id: "formula_Business Days Open"
>   name: "Business Days Open"
>   expr: >-
>     sql_int_op ("{target_db}.{target_schema}.get_business_days_clamped({0},{1}, FALSE)", [{date_column}], today())
>   properties:
>     column_type: MEASURE
>
> columns:
> # ... existing columns ...
> - name: "Business Days Open"
>   formula_id: "formula_Business Days Open"   # must match id above exactly
>   properties:
>     column_type: MEASURE
>     aggregation: SUM
>     index_type: DONT_INDEX
> ```
>
> For `get_business_duration_str` (returns a string): use `sql_string_op`, `column_type: ATTRIBUTE`, and omit `aggregation`.

---

## Error Handling

| Symptom | Action |
|---|---|
| `Insufficient privileges` on CREATE FUNCTION | `GRANT CREATE FUNCTION ON SCHEMA {target_db}.{target_schema} TO ROLE <role>` (requires schema owner or SYSADMIN) |
| `Unknown function get_business_minutes_clamped` in step 2c | Step 2a failed — fix that first; the dependency must exist |
| Smoke test returns wrong value | Re-run `CREATE OR REPLACE` for that function |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.1 | 2026-05-12 | Step 4: explicit formulas[] + columns[] TML pattern; formula alone is hidden without the columns[] entry |
| 1.0.0 | 2026-05-12 | Initial release |
