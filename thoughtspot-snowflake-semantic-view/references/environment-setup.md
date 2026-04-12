# Environment Setup and Connectivity

How to make ThoughtSpot API calls and execute Snowflake SQL depending on your runtime
environment. Determine your environment before Step 1 and use the same method throughout.

---

## Known Parsing Pitfalls

### `schema` field name in PyYAML

ThoughtSpot Table TML contains a top-level `schema` key inside the `table` object:
```yaml
table:
  name: DM_DATE_DIM
  db: DUNDERMIFFLIN
  schema: PUBLIC          # <-- this field
  db_table: DM_DATE_DIM
```

When parsed with PyYAML (`yaml.safe_load`) or converted to JSON, this field is stored
as `"schema"` — **not** `"schema_"`. Always access it as:
```python
tbl.get("schema")    # correct
tbl.get("schema_")   # wrong — always returns None
```

The underscore variant is a common mistake. If `schema` appears to be missing, always
print `tbl.keys()` to verify the actual field names before concluding it is absent.

### Schema IS exported by the API

The `/api/rest/2.0/metadata/tml/export` endpoint with `export_fqn: true` and
`export_associated: true` **does** include `schema` in every Table TML that has one
set in ThoughtSpot. Do **not** prompt the user for the schema value unless:
- The `schema` key is genuinely absent from the parsed dict, **and**
- You have printed `tbl.keys()` to confirm it is not just a parsing artefact.

### Debugging parsed TML structure

When inspecting any parsed TML object, always emit all keys before filtering:
```python
print(f"Table keys: {list(tbl.keys())}")
```
This prevents silent misses caused by field name assumptions.

---

## ThoughtSpot Authentication — Token Persistence

Tokens obtained from `/api/rest/2.0/auth/token/full` are session-scoped. In Claude
Code's Bash tool, **shell variables do not persist between separate tool invocations**.
Use one of these patterns:

**Pattern A — Temp file (recommended for this multi-step skill):**
```bash
# Step 1: Fetch and persist
TOKEN=$(curl -s -X POST "{BASE_URL}/api/rest/2.0/auth/token/full" \
  -H "Content-Type: application/json" \
  -d '{"username":"...","secret_key":"...","validity_time_in_sec":3600}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
echo "$TOKEN" > /tmp/ts_token.txt

# Subsequent calls: read from file
TOKEN=$(cat /tmp/ts_token.txt)
curl -s ... -H "Authorization: Bearer $TOKEN" ...

# Cleanup at end of session
rm -f /tmp/ts_token.txt
```

**Pattern B — Single pipeline script:**
Combine all API calls into one `python3` or `bash` heredoc within a single Bash
invocation. Fetch the token once at the top and reuse the variable throughout.

**Pattern C — Inline fetch per call (for one-off calls only):**
```bash
TOKEN=$(curl -s ... | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -s -H "Authorization: Bearer $TOKEN" ...  # same invocation
```

**Do not** set a variable in one Bash call and read it in the next — it will be empty.

---

## ThoughtSpot API Calls

All environments use the same ThoughtSpot REST API v2 endpoints. The only difference
is which HTTP client is available.

**Python `requests` (works in all environments):**
```python
import requests, os

base_url = os.environ["THOUGHTSPOT_BASE_URL"]
token = "..."  # obtained in Step 1

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}",
    "Accept": "application/json",
}

response = requests.post(
    f"{base_url}/api/rest/2.0/metadata/search",
    json={"metadata": [{"type": "LOGICAL_TABLE"}]},
    headers=headers,
)
response.raise_for_status()
data = response.json()
```

**curl (Claude Code / terminal):**
```bash
curl -s -X POST "{THOUGHTSPOT_BASE_URL}/api/rest/2.0/metadata/search" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"metadata": [{"type": "LOGICAL_TABLE"}]}'
```

---

## Snowflake Connection Profiles

Named profiles are stored in `~/.claude/snowflake-profiles.json`. This allows
multiple accounts/roles to be configured without re-entering credentials each run.

**Profile file format:**
```json
{
  "profiles": [
    {
      "name": "ThoughtSpot Partner (AP)",
      "account": "thoughtspot_partner.ap-southeast-2",
      "username": "APJPOC",
      "auth": "key_pair",
      "private_key_path": "~/.ssh/snowflake_private_key.p8",
      "private_key_passphrase_env": ""
    },
    {
      "name": "Production",
      "account": "myorg-myaccount",
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
passphrase = os.environ.get(profile.get('private_key_passphrase_env',''), None)
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
SELECT SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML($$
{yaml}
$$);
```

Python cells — use Snowpark session:
```python
from snowflake.snowpark.context import get_active_session
session = get_active_session()
yaml_content = """..."""
result = session.sql(f"SELECT SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML($${yaml_content}$$)").collect()
print(result[0][0])
```

### Option 2: Snowflake CLI (`snow`)

```bash
snow sql \
  --query "SELECT SYSTEM\$CREATE_SEMANTIC_VIEW_FROM_YAML('\$\$\n{yaml_escaped}\n\$\$');" \
  --database {database} \
  --schema {schema} \
  --role {role}
```

### Option 3: SnowSQL

```bash
snowsql -a {account} -u {user} -r {role} -d {database} -s {schema} \
  -q "SELECT SYSTEM\$CREATE_SEMANTIC_VIEW_FROM_YAML(\$\$\n{yaml}\n\$\$);"
```

### Option 4: Python `snowflake-connector-python`

```python
import snowflake.connector, os

conn = snowflake.connector.connect(
    account=os.environ["SNOWFLAKE_ACCOUNT"],
    user=os.environ["SNOWFLAKE_USER"],
    password=os.environ["SNOWFLAKE_PASSWORD"],
    role="{role}",
    database="{database}",
    schema="{schema}",
)
cur = conn.cursor()
yaml_content = """
name: my_view
...
"""
cur.execute(f"SELECT SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML($${yaml_content}$$)")
print(cur.fetchone())
conn.close()
```

### Option 5: Manual fallback

If no Snowflake connection is available, output the full SQL to the terminal and
ask the user to run it in the Snowflake UI or SnowSight.

---

## Detection Order

Check in this order and use the first available:

1. Are we inside a Snowflake Notebook? → Use Option 1 (Snowpark session)
2. Is `snow` CLI available? (`snow --version`) → Use Option 2
3. Is `snowsql` available? (`snowsql --version`) → Use Option 3
4. Is `snowflake-connector-python` installed? (`python -c "import snowflake.connector"`) → Use Option 4
5. None available → Use Option 5 (manual)
