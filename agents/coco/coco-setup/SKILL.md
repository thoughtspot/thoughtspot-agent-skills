---
name: coco-setup
description: Install and upgrade the ThoughtSpot stored procedures used by Snowflake Workspace skills (ts-to-snowflake-sv, ts-from-snowflake-sv). Also handles deploying updated skill files from the SKILLS.PUBLIC.SHARED stage to this workspace. Run this once after thoughtspot-setup, and again whenever prompted by another skill that detects an outdated or missing procedure.
---

# CoCo Setup — ThoughtSpot Stored Procedures

Installs or upgrades the ThoughtSpot API stored procedures that the other CoCo skills
depend on. Also deploys updated skill files from the `@SKILLS.PUBLIC.SHARED` stage to
this workspace when requested.

Ask one question at a time. Wait for each answer before proceeding.

---

## Deploying Skill Files from Stage

If the user asks to deploy, update, or sync skill files from the stage, follow these
steps **before** the procedure installation steps below.

**Stage root:** `@SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/`
**Workspace root:** `.snowflake/cortex/`

The mapping is direct — strip the stage prefix and write to the matching workspace path.

### Skills to deploy

For each skill file, read the content from the stage and write it to the workspace:

| Stage path | Workspace path |
|---|---|
| `.../skills/coco-setup/SKILL.md` | `.snowflake/cortex/skills/coco-setup/SKILL.md` |
| `.../skills/thoughtspot-setup/SKILL.md` | `.snowflake/cortex/skills/thoughtspot-setup/SKILL.md` |
| `.../skills/ts-to-snowflake-sv/SKILL.md` | `.snowflake/cortex/skills/ts-to-snowflake-sv/SKILL.md` |
| `.../skills/ts-from-snowflake-sv/SKILL.md` | `.snowflake/cortex/skills/ts-from-snowflake-sv/SKILL.md` |
| `.../skills/SETUP.md` | `.snowflake/cortex/skills/SETUP.md` |

Read each file from the stage using SQL:

```sql
SELECT LISTAGG($1, '\n') WITHIN GROUP (ORDER BY METADATA$FILE_ROW_NUMBER)
FROM @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/{skill_name}/SKILL.md
(FILE_FORMAT => (TYPE = 'CSV' FIELD_DELIMITER = '\x01'
                 FIELD_OPTIONALLY_ENCLOSED_BY = NONE
                 ESCAPE_UNENCLOSED_FIELD = NONE));
```

Write the returned string to the corresponding workspace file, replacing any existing
content. Create parent directories if they do not exist.

### Shared reference files to deploy

Also deploy shared reference files if they have changed:

```sql
-- List all shared files on the stage
LS @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/;
```

For each file returned, read its content (same SQL pattern above) and write to the
matching workspace path under `.snowflake/cortex/shared/`.

### Confirm deployment

After writing all files, display:

```
Skill files deployed from @SKILLS.PUBLIC.SHARED:
  ✓ .snowflake/cortex/skills/coco-setup/SKILL.md
  ✓ .snowflake/cortex/skills/thoughtspot-setup/SKILL.md
  ✓ .snowflake/cortex/skills/ts-to-snowflake-sv/SKILL.md
  ✓ .snowflake/cortex/skills/ts-from-snowflake-sv/SKILL.md
  ✓ .snowflake/cortex/skills/SETUP.md
  ✓ shared reference files ({n} files)

Proceed to install/upgrade stored procedures? (yes/no):
```

If yes, continue to Step 1 below. If no, stop here.

---

## Procedure Inventory

| Procedure | Current version | Purpose |
|---|---|---|
| `TS_SEARCH_MODELS` | **1.1.0** | Search ThoughtSpot for Table/Model objects by name keyword(s) |
| `TS_EXPORT_TML` | **1.0.0** | Export TML definitions from ThoughtSpot (batch) |
| `TS_IMPORT_TML` | **1.0.0** | Import TML definitions into ThoughtSpot (batch) |

---

## Step 1: Check installed versions

Run a single query. If `SKILLS.PUBLIC.SP_VERSIONS` does not exist, treat all procedures
as uninstalled.

```sql
SELECT p.PROCEDURE_NAME,
       COALESCE(v.VERSION, 'not installed') AS installed_version,
       p.EXPECTED_VERSION
FROM (
    SELECT 'TS_SEARCH_MODELS' AS PROCEDURE_NAME, '1.1.0' AS EXPECTED_VERSION
    UNION ALL SELECT 'TS_EXPORT_TML',  '1.0.0'
    UNION ALL SELECT 'TS_IMPORT_TML',  '1.0.0'
) p
LEFT JOIN SKILLS.PUBLIC.SP_VERSIONS v ON v.PROCEDURE_NAME = p.PROCEDURE_NAME
ORDER BY p.PROCEDURE_NAME;
```

Display the results:

```
Stored Procedure Status
  TS_EXPORT_TML     v1.0.0   ✓ up to date
  TS_IMPORT_TML     —        ✗ not installed
  TS_SEARCH_MODELS  v1.0.0   ↑ upgrade available (→ v1.1.0)
```

**If all procedures are up to date:** confirm and exit.

```
All stored procedures are up to date. No action needed.
```

**Otherwise**, count how many need action and ask:

```
{n} procedure(s) need to be installed or upgraded:
  • TS_IMPORT_TML  (not installed)
  • TS_SEARCH_MODELS  (v1.0.0 → v1.1.0)

Install / upgrade now? (yes/no):
```

Stop if the user says no.

---

## Step 2: Check profiles and build secrets mapping

The stored procedures authenticate with ThoughtSpot using Snowflake Secrets — one
secret per profile. Before generating the procedure DDL, retrieve all profiles:

```sql
SELECT name, secret_name FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES ORDER BY name;
```

**If no profiles are returned:** stop and tell the user:

```
No ThoughtSpot profiles found. Run `/thoughtspot-setup` first to add at least
one profile, then re-run coco-setup.
```

**If profiles exist:** build the secrets mapping used in every procedure definition.

For each profile, derive a slug:
- Uppercase the `name`
- Replace non-alphanumeric characters with `_`
- Collapse multiple underscores, strip leading/trailing underscores
- Prefix with `ts_`

Example: profile name `"My Production"` → slug `ts_MY_PRODUCTION`

Build two artefacts (used in Step 3):

**`{SECRETS_CLAUSE}`** — the SECRETS clause embedded in each `CREATE OR REPLACE PROCEDURE`:
```
SECRETS = ('ts_slug_1' = SKILLS.PUBLIC.SECRET_NAME_1,
           'ts_slug_2' = SKILLS.PUBLIC.SECRET_NAME_2, ...)
```

**`{SECRET_MAPPING}`** — the Python dict in `get_secret_for_profile()`:
```python
mapping = {
    'SECRET_NAME_1': 'ts_slug_1',
    'SECRET_NAME_2': 'ts_slug_2',
    ...
}
```

Display the mapping that will be embedded and ask the user to confirm the secrets exist:

```
The following secrets will be included in each procedure:

  ts_slug_1  →  SKILLS.PUBLIC.SECRET_NAME_1
  ts_slug_2  →  SKILLS.PUBLIC.SECRET_NAME_2

These secrets must exist before proceeding. Verify:
```

```sql
SHOW SECRETS LIKE '%THOUGHTSPOT%' IN SCHEMA SKILLS.PUBLIC;
```

If any secrets are missing, stop and direct the user to `/thoughtspot-setup` to create them.

---

## Step 3: Install / upgrade all procedures

Batch all DDL into a **single** `snowflake_sql_execute` call to minimise UI prompts.
The call must contain, in order:

1. `CREATE TABLE IF NOT EXISTS SKILLS.PUBLIC.SP_VERSIONS` (idempotent)
2. `CREATE OR REPLACE PROCEDURE SKILLS.PUBLIC.TS_SEARCH_MODELS` (v1.1.0)
3. `CREATE OR REPLACE PROCEDURE SKILLS.PUBLIC.TS_EXPORT_TML` (v1.0.0)
4. `CREATE OR REPLACE PROCEDURE SKILLS.PUBLIC.TS_IMPORT_TML` (v1.0.0)
5. `MERGE INTO SKILLS.PUBLIC.SP_VERSIONS` (update version tracking)

Substitute `{SECRETS_CLAUSE}` and `{SECRET_MAPPING}` (built in Step 2) into each
procedure definition below before executing.

---

### SP_VERSIONS table

```sql
CREATE TABLE IF NOT EXISTS SKILLS.PUBLIC.SP_VERSIONS (
    procedure_name  VARCHAR     NOT NULL,
    version         VARCHAR     NOT NULL,
    installed_at    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_sp_versions PRIMARY KEY (procedure_name)
);
```

---

### TS_SEARCH_MODELS — v1.1.0

Accepts an array of name keywords. If the array contains one non-empty keyword, uses
server-side `name_pattern` filtering for efficiency. If it contains multiple keywords,
fetches all objects and filters client-side. If the array is empty or contains only
empty strings, returns all objects.

```sql
CREATE OR REPLACE PROCEDURE SKILLS.PUBLIC.TS_SEARCH_MODELS(
    PROFILE_NAME  VARCHAR,
    NAME_KEYWORDS ARRAY,
    OWNER_ONLY    BOOLEAN
)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'requests')
HANDLER = 'run'
EXTERNAL_ACCESS_INTEGRATIONS = (THOUGHTSPOT_API_ACCESS)
{SECRETS_CLAUSE}
AS
$$
import requests
import json
import _snowflake

_VERSION = '1.1.0'

def get_session_headers(base_url, username, secret_value, auth_type, verify_ssl=True):
    if auth_type == 'password':
        s = requests.Session()
        login_resp = s.post(
            f"{base_url}/api/rest/2.0/auth/session/login",
            json={"username": username, "password": secret_value},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            verify=verify_ssl
        )
        if login_resp.status_code in (401, 403):
            return None, None, "Invalid credentials. Run thoughtspot-setup to update password."
        login_resp.raise_for_status()
        return s, {"Content-Type": "application/json", "Accept": "application/json"}, None
    else:
        return None, {
            "Authorization": f"Bearer {secret_value}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }, None

def get_secret_for_profile(secret_name):
    {SECRET_MAPPING}
    key = mapping.get(secret_name)
    if not key:
        return None
    return _snowflake.get_generic_secret_string(key)

def run(session, profile_name, name_keywords, owner_only):
    profile = session.sql(
        f"SELECT base_url, username, auth_type, secret_name "
        f"FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES WHERE name = '{profile_name}'"
    ).collect()
    if not profile:
        return {"error": f"Profile '{profile_name}' not found"}

    row = profile[0].as_dict()
    base_url   = row['BASE_URL'].rstrip('/')
    username   = row['USERNAME']
    auth_type  = row.get('AUTH_TYPE', 'token')
    secret_name = row['SECRET_NAME']
    secret_value = get_secret_for_profile(secret_name)
    if not secret_value:
        return {"error": f"Secret '{secret_name}' not mapped. Run /coco-setup to reinstall procedures."}
    verify_ssl = not base_url.startswith('https://172.') and not base_url.startswith('https://10.')

    http_session, headers, err = get_session_headers(base_url, username, secret_value, auth_type, verify_ssl)
    if err:
        return {"error": err}

    def do_post(url, json_body):
        if http_session:
            return http_session.post(url, headers=headers, json=json_body, verify=verify_ssl)
        return requests.post(url, headers=headers, json=json_body, verify=verify_ssl)

    # Build keyword list — filter out empty strings
    keywords = [k for k in (name_keywords or []) if k and k.strip()]
    # Use server-side filtering only when there is exactly one keyword (efficient)
    single_kw = keywords[0] if len(keywords) == 1 else None

    all_results = []
    offset = 0

    while True:
        meta_filter = {"type": "LOGICAL_TABLE"}
        if single_kw:
            meta_filter["name_pattern"] = f"%{single_kw}%"

        body = {
            "metadata": [meta_filter],
            "record_size": 50,
            "record_offset": offset
        }
        if owner_only:
            body["created_by_user_identifiers"] = [username]

        resp = do_post(f"{base_url}/api/rest/2.0/metadata/search", body)
        if resp.status_code in (401, 403):
            return {"error": "Unauthorized. Run thoughtspot-setup to refresh credentials."}
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break

        for item in page:
            all_results.append({
                "id":     item.get("metadata_id"),
                "name":   item.get("metadata_name"),
                "type":   item.get("metadata_type"),
                "author": item.get("author_name", ""),
            })

        if len(page) < 50:
            break
        offset += 50

    # Client-side filtering for multiple keywords
    if len(keywords) > 1:
        kws_lower = [k.lower() for k in keywords]
        all_results = [r for r in all_results if any(k in r["name"].lower() for k in kws_lower)]

    return {"count": len(all_results), "results": all_results}
$$;
```

---

### TS_EXPORT_TML — v1.0.0

```sql
CREATE OR REPLACE PROCEDURE SKILLS.PUBLIC.TS_EXPORT_TML(
    PROFILE_NAME VARCHAR,
    GUIDS        ARRAY
)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'requests')
HANDLER = 'run'
EXTERNAL_ACCESS_INTEGRATIONS = (THOUGHTSPOT_API_ACCESS)
{SECRETS_CLAUSE}
AS
$$
import requests
import json
import _snowflake

_VERSION = '1.0.0'

def get_session_headers(base_url, username, secret_value, auth_type, verify_ssl=True):
    if auth_type == 'password':
        s = requests.Session()
        login_resp = s.post(
            f"{base_url}/api/rest/2.0/auth/session/login",
            json={"username": username, "password": secret_value},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            verify=verify_ssl
        )
        if login_resp.status_code in (401, 403):
            return None, None, "Invalid credentials. Run thoughtspot-setup to update password."
        login_resp.raise_for_status()
        return s, {"Content-Type": "application/json", "Accept": "application/json"}, None
    else:
        return None, {
            "Authorization": f"Bearer {secret_value}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }, None

def get_secret_for_profile(secret_name):
    {SECRET_MAPPING}
    key = mapping.get(secret_name)
    if not key:
        return None
    return _snowflake.get_generic_secret_string(key)

def run(session, profile_name, guids):
    profile = session.sql(
        f"SELECT base_url, username, auth_type, secret_name "
        f"FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES WHERE name = '{profile_name}'"
    ).collect()
    if not profile:
        return {"error": f"Profile '{profile_name}' not found"}

    row = profile[0].as_dict()
    base_url    = row['BASE_URL'].rstrip('/')
    username    = row['USERNAME']
    auth_type   = row.get('AUTH_TYPE', 'token')
    secret_name = row['SECRET_NAME']
    secret_value = get_secret_for_profile(secret_name)
    if not secret_value:
        return {"error": f"Secret '{secret_name}' not mapped. Run /coco-setup to reinstall procedures."}
    verify_ssl = not base_url.startswith('https://172.') and not base_url.startswith('https://10.')

    http_session, headers, err = get_session_headers(base_url, username, secret_value, auth_type, verify_ssl)
    if err:
        return {"error": err}

    def do_post(url, json_body):
        if http_session:
            return http_session.post(url, headers=headers, json=json_body, verify=verify_ssl)
        return requests.post(url, headers=headers, json=json_body, verify=verify_ssl)

    body = {
        "metadata": [{"identifier": g} for g in guids],
        "export_fqn": True,
        "export_associated": True
    }

    resp = do_post(f"{base_url}/api/rest/2.0/metadata/tml/export", body)
    if resp.status_code in (401, 403):
        return {"error": "Unauthorized. Run thoughtspot-setup to refresh credentials."}
    resp.raise_for_status()
    return resp.json()
$$;
```

---

### TS_IMPORT_TML — v1.0.0

```sql
CREATE OR REPLACE PROCEDURE SKILLS.PUBLIC.TS_IMPORT_TML(
    PROFILE_NAME  VARCHAR,
    TMLS          ARRAY,
    VALIDATE_ONLY BOOLEAN
)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'requests')
HANDLER = 'run'
EXTERNAL_ACCESS_INTEGRATIONS = (THOUGHTSPOT_API_ACCESS)
{SECRETS_CLAUSE}
AS
$$
import requests
import json
import _snowflake

_VERSION = '1.0.0'

def get_session_headers(base_url, username, secret_value, auth_type, verify_ssl=True):
    if auth_type == 'password':
        s = requests.Session()
        login_resp = s.post(
            f"{base_url}/api/rest/2.0/auth/session/login",
            json={"username": username, "password": secret_value},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            verify=verify_ssl
        )
        if login_resp.status_code in (401, 403):
            return None, None, "Invalid credentials. Run thoughtspot-setup to update password."
        login_resp.raise_for_status()
        return s, {"Content-Type": "application/json", "Accept": "application/json"}, None
    else:
        return None, {
            "Authorization": f"Bearer {secret_value}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }, None

def get_secret_for_profile(secret_name):
    {SECRET_MAPPING}
    key = mapping.get(secret_name)
    if not key:
        return None
    return _snowflake.get_generic_secret_string(key)

def run(session, profile_name, tmls, validate_only):
    profile = session.sql(
        f"SELECT base_url, username, auth_type, secret_name "
        f"FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES WHERE name = '{profile_name}'"
    ).collect()
    if not profile:
        return {"error": f"Profile '{profile_name}' not found"}

    row = profile[0].as_dict()
    base_url    = row['BASE_URL'].rstrip('/')
    username    = row['USERNAME']
    auth_type   = row.get('AUTH_TYPE', 'token')
    secret_name = row['SECRET_NAME']
    secret_value = get_secret_for_profile(secret_name)
    if not secret_value:
        return {"error": f"Secret '{secret_name}' not mapped. Run /coco-setup to reinstall procedures."}
    verify_ssl = not base_url.startswith('https://172.') and not base_url.startswith('https://10.')

    http_session, headers, err = get_session_headers(base_url, username, secret_value, auth_type, verify_ssl)
    if err:
        return {"error": err}

    def do_post(url, json_body):
        if http_session:
            return http_session.post(url, headers=headers, json=json_body, verify=verify_ssl)
        return requests.post(url, headers=headers, json=json_body, verify=verify_ssl)

    import_policy = "VALIDATE_ONLY" if validate_only else "ALL_OR_NONE"
    body = {
        "metadata_tmls": list(tmls),
        "import_policy": import_policy
    }

    resp = do_post(f"{base_url}/api/rest/2.0/metadata/tml/import", body)
    if resp.status_code in (401, 403):
        return {"error": "Unauthorized. Run thoughtspot-setup to refresh credentials."}
    resp.raise_for_status()
    return resp.json()
$$;
```

---

### SP_VERSIONS update

After all three `CREATE OR REPLACE PROCEDURE` statements, record the installed versions:

```sql
MERGE INTO SKILLS.PUBLIC.SP_VERSIONS AS t
USING (
    SELECT 'TS_SEARCH_MODELS' AS procedure_name, '1.1.0' AS version
    UNION ALL SELECT 'TS_EXPORT_TML',  '1.0.0'
    UNION ALL SELECT 'TS_IMPORT_TML',  '1.0.0'
) AS s ON t.procedure_name = s.procedure_name
WHEN MATCHED THEN UPDATE SET
    t.version      = s.version,
    t.installed_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
    (procedure_name, version, installed_at)
    VALUES (s.procedure_name, s.version, CURRENT_TIMESTAMP());
```

---

## Step 4: Confirm

Display final status:

```
Stored procedures installed successfully.

  TS_SEARCH_MODELS  v1.1.0   ✓
  TS_EXPORT_TML     v1.0.0   ✓
  TS_IMPORT_TML     v1.0.0   ✓

You can now use /ts-to-snowflake-sv and /ts-from-snowflake-sv.
```

---

## When to re-run coco-setup

Re-run this skill when:
- A new ThoughtSpot profile is added via `/thoughtspot-setup` — the new profile's secret
  must be added to the SECRETS clause of every procedure
- Another skill reports "Stored procedure not found" or "Secret not mapped"
- A new version of the skill is deployed (the other skills will show ↑ in their Step 1 check)
