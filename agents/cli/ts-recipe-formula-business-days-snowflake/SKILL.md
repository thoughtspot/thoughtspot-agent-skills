---
name: ts-recipe-formula-business-days-snowflake
description: Creates three Snowflake scalar UDFs for calculating business-day (weekday-only) date differences and elapsed time, then shows the ThoughtSpot formula syntax to use them in any Model. Use this skill whenever the user asks about weekday date calculations, business day counts, working day differences, SLA tracking, ticket age, order fulfillment time, or wants to exclude weekends from any date difference in ThoughtSpot or Snowflake. ThoughtSpot's built-in diff_days/diff_hours/diff_minutes count calendar days — if a user needs weekday-only equivalents, invoke this skill.
---

# ThoughtSpot + Snowflake: Business Day UDFs

ThoughtSpot's built-in `diff_days` / `diff_hours` / `diff_minutes` count calendar days. When users need to exclude weekends — SLA tracking, order fulfillment time, invoice payment terms, support ticket aging — there's no native option. This skill closes that gap by deploying three Snowflake scalar UDFs and showing how to call them from ThoughtSpot formulas using `sql_int_op` / `sql_string_op`.

| UDF | Arguments | Returns | Use for |
|---|---|---|---|
| `get_business_minutes_clamped` | `start_ts, end_ts` | INT | Weekday-only elapsed minutes |
| `get_business_days_clamped` | `start_ts, end_ts, inclusive` | INT | Count of weekdays between two timestamps |
| `get_business_duration_str` | `start_ts, end_ts` | STRING | Weekday elapsed time formatted as `HH:MM` |

All three clamp weekend boundaries: if start or end falls on a Saturday or Sunday, the function shifts to the nearest weekday rather than erroring. `get_business_duration_str` internally calls `get_business_minutes_clamped` by fully qualified name, so creation order matters — create minutes first.

Ask one question at a time. Wait for each answer before proceeding.

---

## Prerequisites

- Snowflake profile configured — run `/ts-profile-snowflake` if not
- Snowflake role with `CREATE FUNCTION` privilege on the target schema

---

## Step 1 — Connect to Snowflake

Read `~/.claude/snowflake-profiles.json`. If the file is missing or the array is empty, ask the user to run `/ts-profile-snowflake` first.

If multiple profiles exist, show a numbered list and ask which to use. If exactly one exists, confirm it.

Save:
- `{sf_profile_name}` — profile name
- `{sf_method}` — `"python"` or `"cli"` (from the profile's `method` field)
- `{cli_connection}` — for `method: cli`
- `{account}`, `{username}`, `{auth}`, `{default_warehouse}`, `{default_role}` — for `method: python`

Test the connection:

**method: cli**
```bash
snow sql -c "{cli_connection}" -q "SELECT CURRENT_USER()"
```

**method: python**
```python
import snowflake.connector, json, pathlib

profiles = json.loads(pathlib.Path("~/.claude/snowflake-profiles.json").expanduser().read_text())
p = next(x for x in profiles if x["name"] == "{sf_profile_name}")

if p.get("auth") == "key_pair":
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    key_path = pathlib.Path("~/.ssh/snowflake_key.p8").expanduser()
    private_key = serialization.load_pem_private_key(
        key_path.read_bytes(), password=None, backend=default_backend()
    )
    private_key_bytes = private_key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()
    )
    conn = snowflake.connector.connect(
        account=p["account"], user=p["username"], private_key=private_key_bytes,
        warehouse=p.get("default_warehouse"), role=p.get("default_role")
    )
else:
    import keyring
    password = keyring.get_password(f"snowflake-{p['name'].lower().replace(' ','-')}", p["username"])
    conn = snowflake.connector.connect(
        account=p["account"], user=p["username"], password=password,
        warehouse=p.get("default_warehouse"), role=p.get("default_role")
    )

cur = conn.cursor()
cur.execute("SELECT CURRENT_USER()")
print(cur.fetchone())
```

If the test fails, refer the user to `/ts-profile-snowflake` for credential troubleshooting.

---

## Step 2 — Collect Target Database and Schema

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

## Step 3 — Create the UDFs

Create the functions in the order below — `get_business_duration_str` calls `get_business_minutes_clamped` by fully qualified name and will fail if that function doesn't exist first.

If any creation step fails, show the error and stop. Don't attempt to create dependent functions after a failure.

### 3a. get_business_minutes_clamped

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

### 3b. get_business_days_clamped

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

### 3c. get_business_duration_str

This function calls `get_business_minutes_clamped` by its fully qualified name — both must live in the same database and schema.

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

**Executing each DDL statement:**

**method: cli**
```python
import subprocess, tempfile, pathlib

for fname, ddl in [
    ("get_business_minutes_clamped", ddl_minutes),
    ("get_business_days_clamped",    ddl_days),
    ("get_business_duration_str",    ddl_duration_str),
]:
    tmp = pathlib.Path(tempfile.mktemp(suffix=".sql"))
    tmp.write_text(ddl)
    r = subprocess.run(
        ["snow", "sql", "-c", "{cli_connection}", "-f", str(tmp)],
        capture_output=True, text=True
    )
    tmp.unlink()
    if r.returncode != 0:
        print(f"FAILED {fname}: {r.stderr or r.stdout}")
        break
    print(f"Created {fname}")
```

**method: python**
```python
for fname, ddl in [
    ("get_business_minutes_clamped", ddl_minutes),
    ("get_business_days_clamped",    ddl_days),
    ("get_business_duration_str",    ddl_duration_str),
]:
    try:
        cur.execute(ddl)
        print(f"Created {fname}")
    except Exception as e:
        print(f"FAILED {fname}: {e}")
        break
```

After all three succeed, confirm:

```
✓ get_business_minutes_clamped created
✓ get_business_days_clamped created
✓ get_business_duration_str created
```

---

## Step 4 — Verify

Run three smoke tests to confirm the UDFs return expected values.

**Test 1:** Mon 2026-01-05 → Fri 2026-01-09, exclusive → 4 business days

```sql
SELECT {target_db}.{target_schema}.get_business_days_clamped(
    '2026-01-05'::TIMESTAMP, '2026-01-09'::TIMESTAMP, FALSE
);
-- Expected: 4
```

**Test 2:** One full business day (Mon 09:00 → Tue 09:00) → 1440 minutes

```sql
SELECT {target_db}.{target_schema}.get_business_minutes_clamped(
    '2026-01-05 09:00:00'::TIMESTAMP, '2026-01-06 09:00:00'::TIMESTAMP
);
-- Expected: 1440
```

**Test 3:** Duration string for same interval → `24:00`

```sql
SELECT {target_db}.{target_schema}.get_business_duration_str(
    '2026-01-05 09:00:00'::TIMESTAMP, '2026-01-06 09:00:00'::TIMESTAMP
);
-- Expected: 24:00
```

If any test returns an unexpected value, show the actual result and re-run `CREATE OR REPLACE` for that function to refresh it.

---

## Step 5 — ThoughtSpot Formula Examples

Present the formula syntax for calling these UDFs inside ThoughtSpot:

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

To add a formula to a ThoughtSpot Model:
  1. Open the Model → Edit
  2. Click + Add formula
  3. Name it (e.g. "Business Days Open", "SLA Minutes Elapsed")
  4. Paste the expression above, replacing [your date column] with the column name

Formula type note:
  sql_int_op   → numeric column (use for counts and minutes)
  sql_string_op → text column (use for HH:MM display)
```

Then ask:

```
Would you like help adding one of these formulas to a specific ThoughtSpot Model? (Y / N)
```

If Y:
1. Check `~/.claude/thoughtspot-profiles.json` — if missing, ask user to run `/ts-profile-thoughtspot` first
2. Verify: `source ~/.zshenv && ts auth whoami --profile "{ts_profile_name}"`
3. Ask: which model, what to name the formula (e.g. `Business Days Open`), which UDF to use, and which date column(s) to pass as arguments
4. Export TML: `ts tml export {model_guid} --profile {ts_profile_name} --fqn --parse`
5. Add **both** of the following to the TML — a formula alone is not enough; without the `columns[]` entry the formula is hidden from users:

   **In `formulas[]`** — the expression:
   ```yaml
   - id: "formula_{formula_name}"          # e.g. formula_Business Days Open
     name: "{formula_name}"
     expr: >-
       sql_int_op ("{target_db}.{target_schema}.get_business_days_clamped({0},{1}, FALSE)", [{date_column}], today())
     properties:
       column_type: MEASURE
   ```
   For `get_business_duration_str` (returns a string), use `column_type: ATTRIBUTE` and wrap with `sql_string_op`.

   **In `columns[]`** — the visible column entry that references the formula:
   ```yaml
   - name: "{formula_name}"
     formula_id: "formula_{formula_name}"  # must match the id above exactly
     properties:
       column_type: MEASURE                # ATTRIBUTE for string UDF
       aggregation: SUM                    # omit for ATTRIBUTE
       index_type: DONT_INDEX
   ```

6. Import: `ts tml import --profile {ts_profile_name} --policy ALL_OR_NONE`
7. Verify the formula appears in the Model — search for the formula name or run `ts metadata search --profile {ts_profile_name} --name "{formula_name}"` to confirm it is indexed.

If N → done.

---

## Error Handling

| Symptom | Action |
|---|---|
| `Insufficient privileges` on CREATE FUNCTION | Ask user to run: `GRANT CREATE FUNCTION ON SCHEMA {target_db}.{target_schema} TO ROLE <role>` (requires schema owner or SYSADMIN) |
| `Unknown function get_business_minutes_clamped` in step 3c | Step 3a failed — fix that error first; the dependency must exist before the string formatter |
| Smoke test returns wrong value | Re-run `CREATE OR REPLACE` for that function; a silent compilation warning may have accepted a stale body |
| `snow: command not found` | Snowflake CLI not installed — install it or switch to Python connector via `/ts-profile-snowflake` |
| `ModuleNotFoundError: snowflake.connector` | Run `pip install snowflake-connector-python cryptography` |
| 401 on ThoughtSpot whoami (Step 5 opt-in) | Token expired — refer user to `/ts-profile-thoughtspot` → U → Refresh credential |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 2.0.0 | 2026-05-13 | Renamed from ts-setup-snowflake-udfs-business-days to ts-recipe-formula-business-days-snowflake; new ts-recipe-* family introduced |
| 1.0.1 | 2026-05-12 | Step 5: explicit formulas[] + columns[] TML pattern; formula alone is hidden without the columns[] entry |
| 1.0.0 | 2026-05-12 | Initial release — deploy three Snowflake business-day UDFs and show ThoughtSpot formula syntax |
