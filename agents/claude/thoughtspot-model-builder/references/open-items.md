# Open Items — ThoughtSpot Model Builder

Unknowns that must be tested against a real ThoughtSpot + Snowflake instance before
the relevant parts of the skill can be finalized. Each item has a test procedure and
a space to record what was found.

---

## Item 1 — Does `connection/update` require re-supplying Snowflake credentials?

**Why it matters:** The `POST /tspublic/v1/connection/update` endpoint's documented
request body includes a `configuration` block containing Snowflake credentials
(account, user, password/key). If this is required, the skill must read the Snowflake
password from the macOS Keychain for the selected profile and include it in the payload.
If it can be omitted, the skill is simpler and safer.

**Also test:** Whether the v1 endpoint accepts a Bearer token (obtained via the v2 auth
flow) or requires a different auth mechanism (e.g. session cookie).

**Status:** UNTESTED

**Test procedure:**

```python
import requests, json

# Auth using your existing ThoughtSpot token
token = open("/tmp/ts_token.txt").read().strip()
base_url = "https://YOUR_INSTANCE.thoughtspot.cloud"
connection_id = "YOUR_CONNECTION_GUID"

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Test 1: fetchConnection with Bearer token
resp = requests.post(
    f"{base_url}/tspublic/v1/connection/fetchConnection",
    json={"connection_id": connection_id, "includeColumns": True},
    headers=headers,
)
print("fetchConnection status:", resp.status_code)
# If 401/403: Bearer token not accepted by v1 — may need session cookie or v1 login

# Test 2: connection/update without configuration block
# First, get current state from fetchConnection response above
current_state = resp.json()
payload = {
    "connection_id": connection_id,
    "metadata": {
        # No "configuration" key — test if omitting it is accepted
        "externalDatabases": current_state.get("externalDatabases", [])
    }
}
resp2 = requests.post(
    f"{base_url}/tspublic/v1/connection/update",
    json=payload,
    headers=headers,
)
print("update without credentials:", resp2.status_code, resp2.text[:300])
```

**What to record:**
- Does `fetchConnection` accept Bearer token? Y / N
- Does `connection/update` work without `configuration` block? Y / N
- If credentials required: which fields exactly (password, OAuth token, key pair)?

**Finding:**

```
[Record result here]
```

---

## Item 2 — How to list and read Snowflake Semantic Views

**Why it matters:** If the user selects a Snowflake Semantic View as input, the skill
needs to (a) list available semantic views and (b) read the view definition to get
pre-classified dimensions, metrics, and time dimensions. The exact SQL commands are
not confirmed.

**Status:** UNTESTED

**Test procedure:**

```sql
-- Test each of these in a Snowflake worksheet and record which ones work:

-- Option A
SHOW SEMANTIC VIEWS IN SCHEMA {db}.{schema};

-- Option B
SHOW SEMANTIC VIEWS IN DATABASE {db};

-- Option C
SELECT * FROM {db}.INFORMATION_SCHEMA.SEMANTIC_VIEWS;

-- Reading the definition (try after listing works):
SELECT SYSTEM$GET_SEMANTIC_VIEW('{db}.{schema}.{view_name}');
-- or:
SELECT GET_DDL('SEMANTIC_VIEW', '{db}.{schema}.{view_name}');
```

**What to record:**
- Which SHOW command works?
- What columns does it return (name, schema, database, created_on, etc.)?
- Which command reads the full definition?
- What format is the definition returned in (YAML, JSON, DDL)?
- Does the definition include dimension/metric/time_dimension classification?

**Finding:**

```
[Record result here]
```

---

## Item 3 — Does `connection/update` auto-create ThoughtSpot Table objects?

**Why it matters:** In the ThoughtSpot UI, adding tables to a connection automatically
creates corresponding Table metadata objects (logical tables of type `DATA_SOURCE`).
If the API behaves the same way, Step 4 (TML import for Table objects) may be
unnecessary or needs to handle the case where objects already exist. If the API
does NOT auto-create them, Step 4 is always required.

**Status:** UNTESTED

**Test procedure:**

1. Pick a Snowflake table that does NOT currently exist in your ThoughtSpot instance.
2. Add it to the connection via `connection/update` (once Item 1 is resolved).
3. Immediately search for it in ThoughtSpot metadata:

```python
resp = requests.post(
    f"{base_url}/api/rest/2.0/metadata/search",
    json={"metadata": [{"type": "LOGICAL_TABLE"}], "record_size": 100},
    headers=headers,
)
tables = resp.json().get("metadata_details", [])
match = [t for t in tables if t.get("header", {}).get("name") == "YOUR_TABLE_NAME"]
print("Auto-created object:", match)
```

**What to record:**
- Does the Table object appear immediately after `connection/update`? Y / N
- If yes: does it have columns already populated?
- If yes: can it be used in a model without a separate TML import?
- Does it appear in the ThoughtSpot UI under Data > Connections > [connection] > Tables?

**Finding:**

```
[Record result here]
```

---

## Item 4 — Does TML re-import update an existing Table object or create a duplicate?

**Why it matters:** If a Table object already exists (either auto-created in Item 3
or previously imported), re-importing the same TML without a `guid` will create a
duplicate. With a `guid`, it should update. The skill needs to handle both cases
correctly: fetch the existing GUID before importing, and include it if the object exists.

**Status:** UNTESTED

**Test procedure:**

```python
# Step 1: Import a Table TML without a guid
table_tml_no_guid = """
table:
  name: TEST_IMPORT_TABLE
  db: MY_DB
  schema: MY_SCHEMA
  db_table: TEST_TABLE
  connection:
    name: My Connection
    fqn: {connection_id}
  columns:
  - name: ID
    db_column_name: ID
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: INT64
"""

resp = requests.post(
    f"{base_url}/api/rest/2.0/metadata/tml/import",
    json={"metadata_tmls": [table_tml_no_guid], "import_policy": "PARTIAL", "create_new": True},
    headers=headers,
)
print("First import:", resp.status_code, resp.json())

# Step 2: Import the same TML again — does it create a duplicate or error?
resp2 = requests.post(
    f"{base_url}/api/rest/2.0/metadata/tml/import",
    json={"metadata_tmls": [table_tml_no_guid], "import_policy": "PARTIAL", "create_new": True},
    headers=headers,
)
print("Second import:", resp2.status_code, resp2.json())

# Step 3: Search for the table — how many objects exist?
resp3 = requests.post(
    f"{base_url}/api/rest/2.0/metadata/search",
    json={"metadata": [{"type": "LOGICAL_TABLE"}]},
    headers=headers,
)
matches = [t for t in resp3.json().get("metadata_details", [])
           if t.get("header", {}).get("name") == "TEST_IMPORT_TABLE"]
print(f"Objects found: {len(matches)}")
```

**What to record:**
- Does second import create a duplicate? Y / N
- Does it error? What error message?
- Correct pattern: fetch GUID of existing object, include `guid:` in TML on re-import?

**Finding:**

```
[Record result here]
```

---

## Item 5 — Table-level joins: can the Model TML omit the `joins` section?

**Why it matters:** If joins are defined at the table level (`joins_with` in Table TML),
ThoughtSpot should inherit them automatically when building a model. If this is the case,
the `model` TML does not need a `joins` section — only `model_tables` and `table_paths`
are needed. If ThoughtSpot does NOT auto-inherit, the model TML must redeclare the joins.

Also unclear: when table-level joins exist, does `table_paths` still need to reference
join names in `join_path`, or can all `join_path` entries be `[{}]`?

**Status:** UNTESTED

**Test procedure:**

1. Create two Table TMLs — one fact table with a `joins_with` pointing to a dimension table.
2. Import both. Verify the join appears in ThoughtSpot (Data > Tables > [table] > Joins).
3. Create a Model TML that references both tables but has NO `joins` section:

```yaml
model:
  name: Test Join Inheritance
  model_tables:
  - name: FACT_TABLE
    id: FACT_TABLE_1
  - name: DIM_TABLE
    id: DIM_TABLE_1
  table_paths:
  - id: FACT_TABLE_1
    table: FACT_TABLE
    join_path:
    - {}
  - id: DIM_TABLE_1
    table: DIM_TABLE
    join_path:
    - {}          # empty — not referencing any join name
  columns:
  - name: Test Measure
    column_id: FACT_TABLE_1::AMOUNT
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Dim Name
    column_id: DIM_TABLE_1::NAME
    properties:
      column_type: ATTRIBUTE
```

4. Import the model. Does it import successfully?
5. Open the model in ThoughtSpot — does it show the join from the table level?
6. Run a search against the model that spans both tables — does it join correctly?

**What to record:**
- Does the model import succeed without a `joins` section? Y / N
- Are table-level joins visible/active in the model? Y / N
- Does `join_path` need to reference join names or can it be `[{}]` for all tables?

**Finding:**

```
[Record result here]
```
