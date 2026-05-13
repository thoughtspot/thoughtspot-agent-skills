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
Ready to create 4 UDFs in {target_db}.{target_schema}:

  format_seconds_to_hms(seconds)     → STRING  e.g. 3665 → '01:01:05'
  format_seconds_to_dhms(seconds)    → STRING  e.g. 90061 → '01:01:01:01'
  format_minutes_to_hm(minutes)      → STRING  e.g. 65 → '01:05'
  format_minutes_to_dhm(minutes)     → STRING  e.g. 1501 → '01:01:01'

Existing functions with these names will be replaced (CREATE OR REPLACE).

Proceed? (Y / N)
```

---

## Step 3 — Create the UDFs

All four UDFs are independent. If any creation step fails, show the error and stop — do not attempt subsequent UDFs.

### 3a. format_seconds_to_hms

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

### 3b. format_seconds_to_dhms

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

### 3c. format_minutes_to_hm

```sql
CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.format_minutes_to_hm(minutes INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(minutes / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(minutes, 60)::STRING, 2, '0')
$$;
```

### 3d. format_minutes_to_dhm

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

**Executing each DDL statement:**

**method: cli**
```python
import subprocess, tempfile, pathlib

udfs = [
    ("format_seconds_to_hms",  ddl_hms),
    ("format_seconds_to_dhms", ddl_dhms),
    ("format_minutes_to_hm",   ddl_hm),
    ("format_minutes_to_dhm",  ddl_dhm),
]
for fname, ddl in udfs:
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
for fname, ddl in udfs:
    try:
        cur.execute(ddl)
        print(f"Created {fname}")
    except Exception as e:
        print(f"FAILED {fname}: {e}")
        break
```

After all four succeed, confirm:

```
✓ format_seconds_to_hms created
✓ format_seconds_to_dhms created
✓ format_minutes_to_hm created
✓ format_minutes_to_dhm created
```

---

## Step 4 — Verify

Run four spot checks to confirm the UDFs return expected values.

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

If any test returns an unexpected value, re-run `CREATE OR REPLACE` for that function.

---

## Step 5 — ThoughtSpot Formula Examples

Present the formula syntax for calling these UDFs inside ThoughtSpot:

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

These formulas produce ATTRIBUTE (string) columns — suitable for display, not aggregation.

To add a formula to a ThoughtSpot Model:
  1. Open the Model → Edit
  2. Click + Add formula
  3. Name it (e.g. "Call Duration", "Handle Time Display")
  4. Paste the expression above, replacing [seconds column] or [minutes column]
     with your actual column name
```

Then ask:

```
Would you like help adding one of these formulas to a specific ThoughtSpot Model? (Y / N)
```

If Y:
1. Check `~/.claude/thoughtspot-profiles.json` — if missing, ask user to run `/ts-profile-thoughtspot` first
2. Verify: `source ~/.zshenv && ts auth whoami --profile "{ts_profile_name}"`
3. Ask: which model, what to name the formula (e.g. `Call Duration`), which UDF to use, and which integer column to pass as argument
4. Export TML: `ts tml export {model_guid} --profile {ts_profile_name} --fqn --parse`
5. Add **both** entries to the TML — a formula entry alone is hidden from users; the `columns[]` entry is what makes it visible:

   **In `formulas[]`:**
   ```yaml
   - id: "formula_{formula_name}"
     name: "{formula_name}"
     expr: >-
       sql_string_op ("{target_db}.{target_schema}.format_seconds_to_hms({0})", [{seconds_column}])
     properties:
       column_type: ATTRIBUTE
   ```

   **In `columns[]`:**
   ```yaml
   - name: "{formula_name}"
     formula_id: "formula_{formula_name}"   # must match id above exactly
     properties:
       column_type: ATTRIBUTE
       index_type: DONT_INDEX
   ```

   Note: `column_type: ATTRIBUTE` and no `aggregation` — these UDFs return strings and cannot be summed.

6. Import: `ts tml import --profile {ts_profile_name} --policy ALL_OR_NONE`
7. Confirm the formula is visible: search for the formula name in the Model.

If N → done.

---

## Error Handling

| Symptom | Action |
|---|---|
| `Insufficient privileges` on CREATE FUNCTION | `GRANT CREATE FUNCTION ON SCHEMA {target_db}.{target_schema} TO ROLE <role>` (requires schema owner or SYSADMIN) |
| Smoke test returns wrong value | Re-run `CREATE OR REPLACE` for that function |
| `snow: command not found` | Snowflake CLI not installed — install it or switch to Python connector via `/ts-profile-snowflake` |
| `ModuleNotFoundError: snowflake.connector` | Run `pip install snowflake-connector-python cryptography` |
| 401 on ThoughtSpot whoami (Step 5 opt-in) | Token expired — refer user to `/ts-profile-thoughtspot` → U → Refresh credential |
| Formula shows as MEASURE not ATTRIBUTE in ThoughtSpot | The `column_type` in both `formulas[]` and `columns[]` must be `ATTRIBUTE` for string UDFs |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-05-13 | Initial release — deploy four Snowflake duration-display UDFs and show ThoughtSpot formula syntax |
