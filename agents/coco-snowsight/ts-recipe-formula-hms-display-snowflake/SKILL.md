---
name: ts-recipe-formula-hms-display-snowflake
description: Creates four Snowflake scalar UDFs that format integer durations (seconds or minutes) as human-readable time strings — HH:MM:SS, DD:HH:MM:SS, HH:MM, DD:HH:MM — then shows the ThoughtSpot formula syntax to display them in any Model. Use this skill whenever the user asks about displaying durations, formatting elapsed time, converting seconds or minutes to a readable format, showing call duration, handle time, SLA elapsed time, ticket age as HH:MM:SS, or any scenario where an integer count of seconds or minutes should appear as a formatted time string in ThoughtSpot.
---

# ThoughtSpot + Snowflake: Duration Display UDFs

ThoughtSpot stores durations as integer columns (seconds or minutes) but cannot natively format them as `HH:MM:SS`. This skill deploys four Snowflake scalar UDFs that convert integer durations to formatted strings, then shows how to call them from ThoughtSpot formulas using `sql_string_op`.

| UDF | Input | Returns | Example |
|---|---|---|---|
| `format_seconds_to_hms` | `seconds INT` | STRING | 3665 → `01:01:05` |
| `format_seconds_to_dhms` | `seconds INT` | STRING | 90061 → `01:01:01:01` |
| `format_minutes_to_hm` | `minutes INT` | STRING | 65 → `01:05` |
| `format_minutes_to_dhm` | `minutes INT` | STRING | 1501 → `01:01:01` |

All four UDFs are independent — no creation order constraint.

Ask one question at a time. Wait for each answer before proceeding.

---

## Prerequisites

- Role with `CREATE FUNCTION` privilege on the target schema
- Access to run SQL in Snowsight

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
Ready to create 4 UDFs in {target_db}.{target_schema}:

  format_seconds_to_hms(seconds)     → STRING  e.g. 3665 → '01:01:05'
  format_seconds_to_dhms(seconds)    → STRING  e.g. 90061 → '01:01:01:01'
  format_minutes_to_hm(minutes)      → STRING  e.g. 65 → '01:05'
  format_minutes_to_dhm(minutes)     → STRING  e.g. 1501 → '01:01:01'

Existing functions with these names will be replaced (CREATE OR REPLACE).

Proceed? (Y / N)
```

---

## Step 2 — Create the UDFs

Run each statement in Snowsight. All four are independent — any can be skipped if not needed.

### 2a. format_seconds_to_hms

```sql
CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.format_seconds_to_hms(seconds INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(seconds / 3600)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(seconds, 3600) / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(seconds, 60)::STRING, 2, '0')
$$;
```

### 2b. format_seconds_to_dhms

```sql
CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.format_seconds_to_dhms(seconds INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(seconds / 86400)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(seconds, 86400) / 3600)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(seconds, 3600) / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(seconds, 60)::STRING, 2, '0')
$$;
```

### 2c. format_minutes_to_hm

```sql
CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.format_minutes_to_hm(minutes INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(minutes / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(minutes, 60)::STRING, 2, '0')
$$;
```

### 2d. format_minutes_to_dhm

```sql
CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.format_minutes_to_dhm(minutes INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(minutes / 1440)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(minutes, 1440) / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(minutes, 60)::STRING, 2, '0')
$$;
```

After all succeed, confirm:

```
✓ format_seconds_to_hms created
✓ format_seconds_to_dhms created
✓ format_minutes_to_hm created
✓ format_minutes_to_dhm created
```

---

## Step 3 — Verify

```sql
-- Expected: 01:01:05  (1h 1m 5s)
SELECT {target_db}.{target_schema}.format_seconds_to_hms(3665);

-- Expected: 01:01:01:01  (1d 1h 1m 1s)
SELECT {target_db}.{target_schema}.format_seconds_to_dhms(90061);

-- Expected: 01:05  (1h 5m)
SELECT {target_db}.{target_schema}.format_minutes_to_hm(65);

-- Expected: 01:01:01  (1d 1h 1m)
SELECT {target_db}.{target_schema}.format_minutes_to_dhm(1501);
```

If any returns an unexpected value, re-run `CREATE OR REPLACE` for that function.

---

## Step 4 — ThoughtSpot Formula Examples

```
The UDFs are ready. Here's how to use them in ThoughtSpot formulas:

Format a seconds column as HH:MM:SS:
  sql_string_op ("{target_db}.{target_schema}.format_seconds_to_hms({0})", [seconds column])

Format a seconds column as DD:HH:MM:SS:
  sql_string_op ("{target_db}.{target_schema}.format_seconds_to_dhms({0})", [seconds column])

Format a minutes column as HH:MM:
  sql_string_op ("{target_db}.{target_schema}.format_minutes_to_hm({0})", [minutes column])

Format a minutes column as DD:HH:MM:
  sql_string_op ("{target_db}.{target_schema}.format_minutes_to_dhm({0})", [minutes column])

To add a formula in ThoughtSpot:
  1. Open the Model → Edit → + Add formula
  2. Paste the expression with your column name substituted and give it a name
     (e.g. "Call Duration", "Handle Time Display")
  3. Save the formula — also add a matching columns[] entry if editing via TML.
```

> **TML pattern — both entries are required:**
>
> ```yaml
> formulas:
> - id: "formula_Call Duration"
>   name: "Call Duration"
>   expr: >-
>     sql_string_op ("{target_db}.{target_schema}.format_seconds_to_hms({0})", [{seconds_column}])
>   properties:
>     column_type: ATTRIBUTE
>
> columns:
> # ... existing columns ...
> - name: "Call Duration"
>   formula_id: "formula_Call Duration"   # must match id above exactly
>   properties:
>     column_type: ATTRIBUTE
>     index_type: DONT_INDEX
> ```
>
> Note: `column_type: ATTRIBUTE` and no `aggregation` — these UDFs return strings and cannot be summed.

> Note: editing TML directly requires the `ts` CLI (Claude Code only). In Snowsight,
> use the ThoughtSpot UI or run `/ts-recipe-formula-hms-display-snowflake` in a Claude Code session.

---

## Error Handling

| Symptom | Action |
|---|---|
| `Insufficient privileges` on CREATE FUNCTION | `GRANT CREATE FUNCTION ON SCHEMA {target_db}.{target_schema} TO ROLE <role>` |
| Smoke test returns wrong value | Re-run `CREATE OR REPLACE` for that function |
| Formula shows as MEASURE in ThoughtSpot | Set `column_type: ATTRIBUTE` in both `formulas[]` and `columns[]` |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-05-13 | Initial release |
