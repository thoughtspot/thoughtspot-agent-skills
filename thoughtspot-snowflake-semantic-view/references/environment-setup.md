# Environment Setup and Connectivity

How to make ThoughtSpot API calls and execute Snowflake SQL depending on your runtime
environment. Determine your environment before Step 1 and use the same method throughout.

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
