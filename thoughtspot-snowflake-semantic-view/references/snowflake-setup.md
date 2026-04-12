# Snowflake Setup and Connectivity

How to configure Snowflake connection profiles and execute SQL depending on your
runtime environment. Determine your environment before Step 13 and use the same
method throughout.

---

## Snowflake Connection Profiles

Named profiles are stored in `~/.claude/snowflake-profiles.json`. This allows
multiple accounts/roles to be configured without re-entering credentials each run.

**Profile file format:**
```json
{
  "profiles": [
    {
      "name": "My Snowflake Account",
      "account": "myorg-myaccount",
      "username": "analyst",
      "auth": "key_pair",
      "private_key_path": "~/.ssh/snowflake_private_key.p8",
      "private_key_passphrase_env": "",
      "default_warehouse": "MY_WAREHOUSE",
      "default_role": "MY_ROLE"
    },
    {
      "name": "Production",
      "account": "myorg-prod",
      "username": "analyst",
      "auth": "password",
      "password_env": "SNOWFLAKE_PASSWORD_PROD"
    }
  ]
}
```

**Profile selection at Step 13:**
1. Read `~/.claude/snowflake-profiles.json`
2. If multiple profiles: display numbered list and ask user to select
3. If one profile: show it and confirm before proceeding
4. If no file: ask user for account, username, and auth method; offer to save as a profile

**Auth methods:**

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

```bash
snow sql \
  --query "CALL SYSTEM\$CREATE_SEMANTIC_VIEW_FROM_YAML('DATABASE.SCHEMA', '\$\$\n{yaml_escaped}\n\$\$');" \
  --database {database} \
  --schema {schema} \
  --role {role}
```

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

Check in this order and use the first available:

1. Are we inside a Snowflake Notebook? → Use Option 1 (Snowpark session)
2. Is `snow` CLI available? (`snow --version`) → Use Option 2
3. Is `snowsql` available? (`snowsql --version`) → Use Option 3
4. Is `snowflake-connector-python` installed? (`python3 -c "import snowflake.connector"`) → Use Option 4
5. None available → Use Option 5 (manual)

---

## Notes on `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`

- Use `CALL`, not `SELECT`
- First argument: fully-qualified target schema as a string: `'DATABASE.SCHEMA'`
- Second argument: YAML content in `$$` dollar-quotes (safe for YAML containing single quotes)
- Third argument `TRUE`: dry-run mode — validates without creating
- Always run a dry-run first; only proceed to create if validation passes
