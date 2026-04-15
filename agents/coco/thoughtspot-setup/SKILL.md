---
name: thoughtspot-setup
description: Manage ThoughtSpot connection profiles for Snowflake workspaces — add, list, update, delete, and test profiles. Sets up External Access Integration, stored procedures for API calls, and stores credentials securely using Snowflake Secrets. Tokens expire after ~24 hours; checks exact expiry time.
---

# ThoughtSpot Setup (Snowflake Workspace)

Manage ThoughtSpot connection profiles stored in a Snowflake table, credentials
stored as Snowflake Secrets, and API access via External Access Integration.
All credential storage uses Snowflake RBAC — secrets are never exposed in query
history, logs, or conversation.

Ask one question at a time. Wait for each answer before moving on.

---

## Prerequisites

This skill requires a database and schemas for storing profiles, secrets, and
temporary procedures. Default location: `SKILLS` database.

```sql
CREATE DATABASE IF NOT EXISTS SKILLS;
CREATE SCHEMA IF NOT EXISTS SKILLS.PUBLIC;
CREATE SCHEMA IF NOT EXISTS SKILLS.TEMP;
```

`SKILLS.PUBLIC` — permanent objects (profiles table, secrets, API procedures)
`SKILLS.TEMP` — temporary objects created during conversion (cleaned up after)

---

## Required Privileges

The user's current role needs these privileges.

### Check current role

```sql
SELECT CURRENT_ROLE();
```

### Minimum privileges needed

| Action | Privilege | Object | SQL to grant (run as SECURITYADMIN or higher) |
|---|---|---|---|
| Create profiles table | CREATE TABLE | SKILLS.PUBLIC schema | `GRANT CREATE TABLE ON SCHEMA SKILLS.PUBLIC TO ROLE {role};` |
| Create secrets | CREATE SECRET | SKILLS.PUBLIC schema | `GRANT CREATE SECRET ON SCHEMA SKILLS.PUBLIC TO ROLE {role};` |
| Create procedures | CREATE PROCEDURE | SKILLS.PUBLIC schema | `GRANT CREATE PROCEDURE ON SCHEMA SKILLS.PUBLIC TO ROLE {role};` |
| Create temp procedures | CREATE PROCEDURE | SKILLS.TEMP schema | `GRANT CREATE PROCEDURE ON SCHEMA SKILLS.TEMP TO ROLE {role};` |
| Read secrets | USAGE | Individual secret | Automatic — the role that creates a secret owns it |
| Use the database/schemas | USAGE | SKILLS database + schemas | `GRANT USAGE ON DATABASE SKILLS TO ROLE {role};` etc. |
| Use External Access | USAGE | Integration | `GRANT USAGE ON INTEGRATION THOUGHTSPOT_API_ACCESS TO ROLE {role};` |
| Create network rules | CREATE NETWORK RULE | SKILLS.PUBLIC schema | `GRANT CREATE NETWORK RULE ON SCHEMA SKILLS.PUBLIC TO ROLE {role};` |

### Quick setup (run as ACCOUNTADMIN)

```sql
GRANT USAGE ON DATABASE SKILLS TO ROLE SE_ROLE;
GRANT USAGE ON SCHEMA SKILLS.PUBLIC TO ROLE SE_ROLE;
GRANT USAGE ON SCHEMA SKILLS.TEMP TO ROLE SE_ROLE;
GRANT CREATE TABLE ON SCHEMA SKILLS.PUBLIC TO ROLE SE_ROLE;
GRANT CREATE SECRET ON SCHEMA SKILLS.PUBLIC TO ROLE SE_ROLE;
GRANT CREATE PROCEDURE ON SCHEMA SKILLS.PUBLIC TO ROLE SE_ROLE;
GRANT CREATE PROCEDURE ON SCHEMA SKILLS.TEMP TO ROLE SE_ROLE;
GRANT CREATE NETWORK RULE ON SCHEMA SKILLS.PUBLIC TO ROLE SE_ROLE;
GRANT CREATE SEMANTIC VIEW ON SCHEMA SKILLS.PUBLIC TO ROLE SE_ROLE;
```

### Sharing profiles with other roles

```sql
GRANT SELECT ON TABLE SKILLS.PUBLIC.THOUGHTSPOT_PROFILES TO ROLE {other_role};
GRANT USAGE ON SECRET SKILLS.PUBLIC.{secret_name} TO ROLE {other_role};
```

---

## Entry Point

```sql
SELECT * FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES;
```

**If table does not exist or is empty:** go directly to [Add](#a--add).

**If profiles exist:** show the menu.

```
ThoughtSpot Profiles

  1. {name}  —  token  —  {base_url}  —  {token_status}
  ...

  L  List profiles
  A  Add a new profile
  U  Update a profile
  D  Delete a profile
  T  Test a profile
  Q  Quit

Enter L / A / U / D / T / Q:
```

---

## L — List

```sql
SELECT
    name, base_url, username, secret_name, token_expires_at,
    CASE WHEN token_expires_at <= CURRENT_TIMESTAMP() THEN 'EXPIRED'
         WHEN token_expires_at <= TIMESTAMPADD('minute', 5, CURRENT_TIMESTAMP()) THEN 'EXPIRING_SOON'
         ELSE 'VALID'
    END AS token_status,
    created_at, updated_at
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES;
```

Show each profile:

```
Profile: {name}
  URL:        {base_url}
  Username:   {username}
  Secret:     {secret_name}
  Expires at: {token_expires_at} ({token_status})
  Created:    {created_at}
  Updated:    {updated_at}
```

---

## A — Add

### Step A1: Create the profiles table (if needed)

```sql
CREATE TABLE IF NOT EXISTS SKILLS.PUBLIC.THOUGHTSPOT_PROFILES (
    name VARCHAR NOT NULL,
    base_url VARCHAR NOT NULL,
    username VARCHAR NOT NULL,
    secret_name VARCHAR NOT NULL,
    token_expires_at TIMESTAMP_NTZ,
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
```

### Step A2: Collect connection details one at a time

```
ThoughtSpot URL (e.g. https://myorg.thoughtspot.cloud):
```
Strip trailing slash. Store as `{base_url}`.

```
Username (email):
```
Store as `{username}`.

```
Profile name: [Production]
```
Default to `Production`. Store as `{profile_name}`.

### Step A3: Obtain the token

```
To get your token:
  1. Log into ThoughtSpot in your browser
  2. Click Develop in the top navigation
  3. Select REST Playground 2.0
  4. Expand the Authentication section
  5. Click Get Current User Token → Try it out → Execute
  6. Copy the token value AND the expiration_time_in_millis from the response body

Paste your token:
```

Store input as `{token_value}`. **Never echo the token back to the user.**

Then ask:
```
Paste the expiration_time_in_millis value (e.g. 1776293905878):
```
Store as `{expiry_millis}`.

### Step A4: Derive names

From `{profile_name}`:
- `{SLUG}` — uppercase, non-alphanumeric → underscores, collapse multiples, strip ends
  e.g. `"My Staging"` → `"MY_STAGING"`
- `{secret_name}` → `THOUGHTSPOT_TOKEN_{SLUG}`

### Step A5: Store credential as Snowflake Secret

**SECURITY: The user must run this SQL themselves.**

```
Run this SQL to store your token securely. Replace <YOUR_TOKEN> with the token you copied:

  CREATE OR REPLACE SECRET SKILLS.PUBLIC.{secret_name}
    TYPE = GENERIC_STRING
    SECRET_STRING = '<YOUR_TOKEN>'
    COMMENT = 'ThoughtSpot bearer token for profile: {profile_name}';
```

**IMPORTANT:** Do NOT execute this SQL on the user's behalf with the actual token.

After confirmation, verify:
```sql
SHOW SECRETS LIKE '{secret_name}' IN SCHEMA SKILLS.PUBLIC;
```

### Step A6: Save profile

```sql
DELETE FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES WHERE name = '{profile_name}';
INSERT INTO SKILLS.PUBLIC.THOUGHTSPOT_PROFILES (name, base_url, username, secret_name, token_expires_at)
SELECT '{profile_name}', '{base_url}', '{username}', '{secret_name}',
       TO_TIMESTAMP({expiry_millis}::NUMBER / 1000);
```

### Step A7: Set up External Access Integration

Extract the hostname from `{base_url}` (e.g. `champagne-master-aws.thoughtspotstaging.cloud`).

**Create the network rule:**
```sql
CREATE OR REPLACE NETWORK RULE SKILLS.PUBLIC.THOUGHTSPOT_API_RULE
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('{hostname}');
```

**Create the External Access Integration (requires ACCOUNTADMIN):**

Check if it already exists:
```sql
SHOW EXTERNAL ACCESS INTEGRATIONS LIKE 'THOUGHTSPOT_API_ACCESS';
```

If not found, instruct the user to run as ACCOUNTADMIN (in a separate worksheet if
the current session cannot switch roles):

```sql
USE ROLE ACCOUNTADMIN;

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION THOUGHTSPOT_API_ACCESS
  ALLOWED_NETWORK_RULES = (SKILLS.PUBLIC.THOUGHTSPOT_API_RULE)
  ALLOWED_AUTHENTICATION_SECRETS = (SKILLS.PUBLIC.{secret_name})
  ENABLED = TRUE;

GRANT USAGE ON INTEGRATION THOUGHTSPOT_API_ACCESS TO ROLE {user_role};
```

After confirmation, verify:
```sql
SHOW EXTERNAL ACCESS INTEGRATIONS LIKE 'THOUGHTSPOT_API_ACCESS';
```

### Step A8: Create permanent API procedures

These procedures are **permanent infrastructure** — created once during setup, reused
by all skills. They live in `SKILLS.PUBLIC` (not TEMP).

**Search procedure:**

```sql
CREATE OR REPLACE PROCEDURE SKILLS.PUBLIC.TS_SEARCH_MODELS(
    PROFILE_NAME VARCHAR,
    QUERY_STRING VARCHAR,
    OWNER_ONLY BOOLEAN
)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'requests')
HANDLER = 'run'
EXTERNAL_ACCESS_INTEGRATIONS = (THOUGHTSPOT_API_ACCESS)
SECRETS = ('ts_token' = SKILLS.PUBLIC.{secret_name})
AS
$$
import requests
import json
import _snowflake

def run(session, profile_name, query_string, owner_only):
    profile = session.sql(f"SELECT base_url, username FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES WHERE name = '{profile_name}'").collect()
    if not profile:
        return {"error": f"Profile '{profile_name}' not found"}

    base_url = profile[0]['BASE_URL'].rstrip('/')
    username = profile[0]['USERNAME']
    token = _snowflake.get_generic_secret_string('ts_token')

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    all_results = []
    offset = 0

    while True:
        body = {
            "metadata": [{"type": "LOGICAL_TABLE"}],
            "record_size": 50,
            "record_offset": offset
        }
        if query_string:
            body["query_string"] = query_string
        if owner_only:
            body["created_by_user_identifiers"] = [username]

        resp = requests.post(f"{base_url}/api/rest/2.0/metadata/search", headers=headers, json=body)

        if resp.status_code in (401, 403):
            return {"error": "Token expired or unauthorized. Run thoughtspot-setup to refresh."}

        resp.raise_for_status()
        page = resp.json()

        if not page:
            break

        for item in page:
            all_results.append({
                "id": item.get("metadata_id"),
                "name": item.get("metadata_name"),
                "type": item.get("metadata_type"),
                "author": item.get("author_name", ""),
            })

        if len(page) < 50:
            break
        offset += 50

    if not all_results and query_string:
        return run(session, profile_name, None, owner_only)

    return {"count": len(all_results), "results": all_results}
$$;
```

**TML Export procedure:**

```sql
CREATE OR REPLACE PROCEDURE SKILLS.PUBLIC.TS_EXPORT_TML(
    PROFILE_NAME VARCHAR,
    GUIDS ARRAY
)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'requests')
HANDLER = 'run'
EXTERNAL_ACCESS_INTEGRATIONS = (THOUGHTSPOT_API_ACCESS)
SECRETS = ('ts_token' = SKILLS.PUBLIC.{secret_name})
AS
$$
import requests
import json
import _snowflake

def run(session, profile_name, guids):
    profile = session.sql(f"SELECT base_url FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES WHERE name = '{profile_name}'").collect()
    if not profile:
        return {"error": f"Profile '{profile_name}' not found"}

    base_url = profile[0]['BASE_URL'].rstrip('/')
    token = _snowflake.get_generic_secret_string('ts_token')

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    body = {
        "metadata": [{"identifier": g} for g in guids],
        "export_fqn": True,
        "export_associated": True
    }

    resp = requests.post(f"{base_url}/api/rest/2.0/metadata/tml/export", headers=headers, json=body)

    if resp.status_code in (401, 403):
        return {"error": "Token expired or unauthorized. Run thoughtspot-setup to refresh."}

    resp.raise_for_status()
    return resp.json()
$$;
```

### Step A9: Confirm

```
ThoughtSpot profile '{profile_name}' configured.
  Secret:     SKILLS.PUBLIC.{secret_name}
  URL:        {base_url}
  Expires at: {token_expires_at}
  Procedures: SKILLS.PUBLIC.TS_SEARCH_MODELS, SKILLS.PUBLIC.TS_EXPORT_TML
  Integration: THOUGHTSPOT_API_ACCESS
```

---

## U — Update

Show numbered profile list and ask which to update. Then show options:

```
  1  URL
  2  Username
  3  Refresh token (token expired — provide a new one)

Enter 1–3:
```

### U1 — Update URL

```sql
UPDATE SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
SET base_url = '{new_base_url}', updated_at = CURRENT_TIMESTAMP()
WHERE name = '{profile_name}';
```

Also update the network rule if the hostname changed:
```sql
CREATE OR REPLACE NETWORK RULE SKILLS.PUBLIC.THOUGHTSPOT_API_RULE
  MODE = EGRESS TYPE = HOST_PORT VALUE_LIST = ('{new_hostname}');
```

### U2 — Update Username

```sql
UPDATE SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
SET username = '{new_username}', updated_at = CURRENT_TIMESTAMP()
WHERE name = '{profile_name}';
```

### U3 — Refresh Token

```
Your ThoughtSpot token has expired or needs refreshing.

To get a new token:
  1. Log into ThoughtSpot → Develop → REST Playground 2.0
  2. Authentication → Get Current User Token → Execute
  3. Copy the new token AND the expiration_time_in_millis value

Run this SQL to update. Replace <YOUR_NEW_TOKEN> with your new token:

  CREATE OR REPLACE SECRET SKILLS.PUBLIC.{secret_name}
    TYPE = GENERIC_STRING
    SECRET_STRING = '<YOUR_NEW_TOKEN>'
    COMMENT = 'ThoughtSpot bearer token for profile: {profile_name}';
```

After confirmation, ask for the new `expiration_time_in_millis` and update:

```sql
UPDATE SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
SET token_expires_at = TO_TIMESTAMP({expiry_millis}::NUMBER / 1000),
    updated_at = CURRENT_TIMESTAMP()
WHERE name = '{profile_name}';
```

**Also update the External Access Integration** to reference the new secret
(requires ACCOUNTADMIN):

```sql
ALTER EXTERNAL ACCESS INTEGRATION THOUGHTSPOT_API_ACCESS
  SET ALLOWED_AUTHENTICATION_SECRETS = (SKILLS.PUBLIC.{secret_name});
```

---

## D — Delete

Confirm, then:
```sql
DROP SECRET IF EXISTS SKILLS.PUBLIC.{secret_name};
DELETE FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES WHERE name = '{profile_name}';
```

---

## T — Test

Check token status and verify secret is accessible:

```sql
SELECT
    name,
    token_expires_at,
    CASE WHEN token_expires_at <= CURRENT_TIMESTAMP() THEN 'EXPIRED'
         WHEN token_expires_at <= TIMESTAMPADD('minute', 5, CURRENT_TIMESTAMP()) THEN 'EXPIRING_SOON'
         ELSE 'VALID'
    END AS token_status
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
WHERE name = '{profile_name}';
```

If VALID, run a test search:
```sql
CALL SKILLS.PUBLIC.TS_SEARCH_MODELS('{profile_name}', NULL, TRUE);
```

On success:
```
Profile '{name}' — connected and verified.
  Token status: VALID (expires {token_expires_at})
  Found {count} models owned by {username}
```

---

## Token Expiry Handling

Check token expiry **before** making any API call:

```sql
SELECT
    name, token_expires_at,
    CASE WHEN token_expires_at <= CURRENT_TIMESTAMP() THEN 'EXPIRED'
         WHEN token_expires_at <= TIMESTAMPADD('minute', 5, CURRENT_TIMESTAMP()) THEN 'EXPIRING_SOON'
         ELSE 'VALID'
    END AS token_status
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
WHERE name = '{profile_name}';
```

- **EXPIRED** or **EXPIRING_SOON**: Prompt user to refresh (U → Refresh token)
- **VALID**: Proceed with API calls

---

## Cleanup

### Temp schema cleanup (after each conversion)

After completing a model conversion, drop all temporary objects in SKILLS.TEMP:

```sql
SHOW PROCEDURES IN SCHEMA SKILLS.TEMP;
SHOW VIEWS IN SCHEMA SKILLS.TEMP;
SHOW TABLES IN SCHEMA SKILLS.TEMP;
-- Drop each one individually
```

### Full removal

```sql
DROP PROCEDURE IF EXISTS SKILLS.PUBLIC.TS_SEARCH_MODELS(VARCHAR, VARCHAR, BOOLEAN);
DROP PROCEDURE IF EXISTS SKILLS.PUBLIC.TS_EXPORT_TML(VARCHAR, ARRAY);
DROP TABLE IF EXISTS SKILLS.PUBLIC.THOUGHTSPOT_PROFILES;
DROP NETWORK RULE IF EXISTS SKILLS.PUBLIC.THOUGHTSPOT_API_RULE;
-- Drop secrets:
SHOW SECRETS IN SCHEMA SKILLS.PUBLIC;
-- Then: DROP SECRET SKILLS.PUBLIC.{secret_name};
-- Drop integration (requires ACCOUNTADMIN):
-- DROP INTEGRATION THOUGHTSPOT_API_ACCESS;
-- Drop schemas:
DROP SCHEMA IF EXISTS SKILLS.TEMP;
```

---

## Error Handling

| Symptom | Action |
|---|---|
| Secret not found | Re-run Add or Update → Refresh token |
| SYSTEM$GET_SECRET_STRING errors | Check role has USAGE on the secret |
| 401 / 403 from ThoughtSpot API | Token expired — run Update → Refresh token |
| Profile table missing | Re-run Add (table is auto-created) |
| External Access Integration missing | Re-run Step A7 as ACCOUNTADMIN |
| Procedure not found | Re-run Step A8 to recreate API procedures |

---

## Technical Reference — For Use by Other Skills

### Search for models

```sql
CALL SKILLS.PUBLIC.TS_SEARCH_MODELS('{profile_name}', '{query}', TRUE);
```

### Export TML

```sql
CALL SKILLS.PUBLIC.TS_EXPORT_TML('{profile_name}', ARRAY_CONSTRUCT('{guid1}', '{guid2}'));
```

### Token Freshness Check

```sql
SELECT name, token_expires_at, token_expires_at > CURRENT_TIMESTAMP() AS is_valid
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
WHERE name = '{profile_name}';
```

### Retrieve credentials in SQL

```sql
SELECT
    p.base_url, p.username, p.secret_name, p.token_expires_at,
    token_expires_at > CURRENT_TIMESTAMP() AS is_valid,
    SYSTEM$GET_SECRET_STRING('SKILLS.PUBLIC.' || p.secret_name) AS token
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES p
WHERE p.name = '{profile_name}';
```
