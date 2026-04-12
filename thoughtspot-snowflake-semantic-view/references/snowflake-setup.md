# Snowflake Setup and Connectivity

How to configure Snowflake connection profiles and execute SQL depending on your
runtime environment. Determine your environment before Step 13 and use the same
method throughout.

---

## Snowflake Connection Profiles

Named profiles are stored in `~/.claude/snowflake-profiles.json`. This allows
multiple accounts/roles to be configured without re-entering credentials each run.

Each profile has a `method` field (`"cli"` or `"python"`) that controls how SQL is
executed. If `method` is absent it defaults to `"python"`.

**Profile file format:**
```json
{
  "profiles": [
    {
      "name": "My Account (CLI)",
      "method": "cli",
      "cli_connection": "myconnection",
      "default_warehouse": "MY_WAREHOUSE",
      "default_role": "MY_ROLE"
    },
    {
      "name": "My Account (Python / key pair)",
      "method": "python",
      "account": "myorg-myaccount",
      "username": "analyst",
      "auth": "key_pair",
      "private_key_path": "~/.ssh/snowflake_private_key.p8",
      "private_key_passphrase_env": "",
      "default_warehouse": "MY_WAREHOUSE",
      "default_role": "MY_ROLE"
    },
    {
      "name": "Production (Python / password)",
      "method": "python",
      "account": "myorg-prod",
      "username": "analyst",
      "auth": "password",
      "password_env": "SNOWFLAKE_PASSWORD_PROD"
    }
  ]
}
```

**`cli_connection`** maps to a named connection in `~/.snowflake/config.toml`:
```toml
[connections.myconnection]
account = "myorg-myaccount"
user = "analyst"
role = "MY_ROLE"
warehouse = "MY_WAREHOUSE"
```
Auth credentials (key pair, SSO, password) are stored entirely in `config.toml`;
the Claude profile only needs the connection name.

**Profile selection:**
1. Read `~/.claude/snowflake-profiles.json`
2. If multiple profiles: display numbered list and ask user to select
3. If one profile: show it and confirm before proceeding
4. If no file: ask user for account, username, auth method, and whether they prefer
   the CLI or Python connector; offer to save as a profile

**Python auth methods:**

*Key pair (recommended):*
```python
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import os

key_path = os.path.expanduser(profile['private_key_path'])
passphrase = os.environ.get(profile.get('private_key_passphrase_env', ''), None)
passphrase_bytes = passphrase.encode() if passphrase else None

with open(key_path, 'rb') as f:
    private_key = serialization.load_pem_private_key(f.read(), password=passphrase_bytes, backend=default_backend())

private_key_bytes = private_key.private_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)

conn = snowflake.connector.connect(
    account=profile['account'],
    user=profile['username'],
    private_key=private_key_bytes,
    role=role,
    database=database,
    schema=schema,
    warehouse=warehouse,
)
```

*Password:*
```python
conn = snowflake.connector.connect(
    account=profile['account'],
    user=profile['username'],
    password=os.environ.get(profile['password_env']),
    role=role, database=database, schema=schema, warehouse=warehouse,
)
```

**Warehouse selection:** If the profile doesn't specify a warehouse, run
`SHOW WAREHOUSES` after connecting and use the first available (preferably non-suspended),
or ask the user to select from the list.

---

## Snowflake Execution

### Option 1: Snowflake Cortex Code (Notebooks)

SQL cells — execute directly:
```sql
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('DATABASE.SCHEMA', $$
{yaml}
$$);
```

Python cells — use Snowpark session:
```python
from snowflake.snowpark.context import get_active_session
session = get_active_session()
yaml_content = """..."""
result = session.sql(f"CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('DATABASE.SCHEMA', $${yaml_content}$$)").collect()
print(result[0][0])
```

### Option 2: Snowflake CLI (`snow`)

The CLI uses `~/.snowflake/config.toml` for auth. All commands pass `-c {cli_connection}`
to select the named connection (omit if using the default connection).

**Running SHOW commands and parsing output:**

Always add `--format json` so output can be parsed with Python. The `name` field in
SHOW SCHEMAS output and the `column_name` field in SHOW COLUMNS output are the
relevant identifiers.

```bash
# Detect case-sensitive schemas
snow sql -c {cli_connection} \
  --format json \
  -q "SHOW SCHEMAS IN DATABASE {db}" \
| python3 -c "
import json, sys
rows = json.load(sys.stdin)
cs = [r['name'] for r in rows if r['name'] != r['name'].upper()]
print('\n'.join(cs))
"

# Detect case-sensitive columns (schema_ref is quoted if schema is case-sensitive)
snow sql -c {cli_connection} \
  --format json \
  -q 'SHOW COLUMNS IN TABLE {db}.{schema_ref}."{phys_table}"' \
| python3 -c "
import json, sys
rows = json.load(sys.stdin)
cs = [r['column_name'] for r in rows if r['column_name'] != r['column_name'].upper()]
print('\n'.join(cs))
"

# List warehouses
snow sql -c {cli_connection} --format json -q "SHOW WAREHOUSES"
```

**Running CREATE / CALL statements:**

Dollar-quoting (`$$`) is safe in SQL files. Use a Python-written temp file to avoid
shell-escaping issues — especially important when the YAML itself contains `$`:

```python
import subprocess

sql = f"""USE ROLE {role};
USE DATABASE {target_db};
USE SCHEMA {target_schema};
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{target_db}.{target_schema}', $${yaml_content}$$, TRUE);
"""
with open('/tmp/sv_query.sql', 'w') as f:
    f.write(sql)

result = subprocess.run(
    ['snow', 'sql', '-c', cli_connection, '--format', 'json', '-f', '/tmp/sv_query.sql'],
    capture_output=True, text=True
)
print(result.stdout)
if result.returncode != 0:
    print(result.stderr)
```

Replace `TRUE` with nothing (remove the third argument) for the actual CREATE call.

**Cleanup:** Remove the temp SQL file after execution:
```bash
rm -f /tmp/sv_query.sql
```

**Role override:** If the connection's default role needs to be overridden, include
`USE ROLE {role};` at the top of the SQL file (as shown above) rather than passing
`--role` on the command line — the `--role` flag is not supported by all `snow sql`
versions.

### Option 3: SnowSQL

```bash
snowsql -a {account} -u {user} -r {role} -d {database} -s {schema} \
  -q "CALL SYSTEM\$CREATE_SEMANTIC_VIEW_FROM_YAML('DATABASE.SCHEMA', \$\$\n{yaml}\n\$\$);"
```

### Option 4: Python `snowflake-connector-python`

```python
import snowflake.connector

conn = snowflake.connector.connect(
    account=profile['account'],
    user=profile['username'],
    private_key=private_key_bytes,  # or password=...
    role=role,
    database=database,
    schema=schema,
    warehouse=warehouse,
)
cur = conn.cursor()
yaml_content = """
name: my_view
...
"""
cur.execute(f"CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{database}.{schema}', $${yaml_content}$$)")
print(cur.fetchone())
conn.close()
```

### Option 5: Manual fallback

If no Snowflake connection is available, output the full SQL to the terminal and
ask the user to run it in the Snowflake UI or Snowsight.

---

## Detection Order

1. Are we inside a Snowflake Notebook? → Use Option 1 (Snowpark session) regardless of profile
2. Is the selected profile `method: cli`?
   - Verify `snow` is available: `snow --version`
   - If available → Use Option 2
   - If not available → warn the user and fall through to step 4
3. Is the selected profile `method: python` (or method absent)?
   - Verify `snowflake-connector-python` is installed: `python3 -c "import snowflake.connector"`
   - If available → Use Option 4
   - If not available → fall through to step 5
4. No profile / no preferred method? Check in order:
   - `snow --version` succeeds → Use Option 2
   - `snowsql --version` succeeds → Use Option 3
   - `python3 -c "import snowflake.connector"` succeeds → Use Option 4
5. None available → Use Option 5 (manual output)

---

## Notes on `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`

- Use `CALL`, not `SELECT`
- First argument: fully-qualified target schema as a string: `'DATABASE.SCHEMA'`
- Second argument: YAML content in `$$` dollar-quotes (safe for YAML containing single quotes)
- Third argument `TRUE`: dry-run mode — validates without creating
- Always run a dry-run first; only proceed to create if validation passes
