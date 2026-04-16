---
name: thoughtspot-setup
description: Manage ThoughtSpot connection profiles for Snowflake workspaces — add, list, update, delete, and test profiles. Supports both bearer token and password authentication. Sets up External Access Integration, stored procedures for API calls, and stores credentials securely using Snowflake Secrets. Token profiles expire after ~24 hours; password profiles remain valid until the password changes.
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

  1. {name}  —  {auth_type}  —  {base_url}  —  {token_status}
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
    name, base_url, username, auth_type, secret_name, token_expires_at,
    CASE WHEN auth_type = 'password' THEN 'PASSWORD_AUTH'
         WHEN token_expires_at <= CURRENT_TIMESTAMP() THEN 'EXPIRED'
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
  Auth:       {auth_type}
  Secret:     {secret_name}
  Expires at: {token_expires_at} ({token_status})   ← omit for password profiles
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
    auth_type VARCHAR NOT NULL DEFAULT 'token',
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

**⚠ Private IP validation:** If the URL contains a private IP (e.g. `172.x.x.x`,
`10.x.x.x`, `192.168.x.x`), warn the user:
> "Snowflake cannot reach private IP addresses from its cloud network. This will
> only work if you have AWS PrivateLink / Azure Private Link configured between
> Snowflake and your network. Do you want to continue?"

If the user confirms, proceed. Otherwise ask for a public hostname.

```
Username (email or local username):
```
Store as `{username}`.

```
Profile name: [Production]
```
Default to `Production`. Store as `{profile_name}`.

### Step A2b: Choose authentication type

```
Authentication method:
  1  Bearer token (cloud clusters — recommended)
  2  Password (on-premise / IP-based clusters)

Enter 1 or 2:
```

Store as `{auth_type}`: `token` for option 1, `password` for option 2.

### Step A3: Obtain credentials

**If `{auth_type}` = `token`:**

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

**If `{auth_type}` = `password`:**

```
I'll need you to store your password as a Snowflake Secret (Step A5).
No token expiry tracking is needed — the password remains valid until changed.
```

Set `{expiry_millis}` to `NULL`.

### Step A4: Derive names

From `{profile_name}`:
- `{SLUG}` — uppercase, non-alphanumeric → underscores, collapse multiples, strip ends
  e.g. `"My Staging"` → `"MY_STAGING"`
- `{secret_name}` → `THOUGHTSPOT_TOKEN_{SLUG}`

### Step A5: Store credential as Snowflake Secret

**SECURITY: The user must run this SQL themselves.**

**If `{auth_type}` = `token`:**

```
Run this SQL to store your token securely. Replace <YOUR_TOKEN> with the token you copied:

  CREATE OR REPLACE SECRET SKILLS.PUBLIC.{secret_name}
    TYPE = GENERIC_STRING
    SECRET_STRING = '<YOUR_TOKEN>'
    COMMENT = 'ThoughtSpot bearer token for profile: {profile_name}';
```

**If `{auth_type}` = `password`:**

```
Run this SQL to store your password securely. Replace <YOUR_PASSWORD> with your ThoughtSpot password:

  CREATE OR REPLACE SECRET SKILLS.PUBLIC.{secret_name}
    TYPE = GENERIC_STRING
    SECRET_STRING = '<YOUR_PASSWORD>'
    COMMENT = 'ThoughtSpot password for profile: {profile_name}';
```

**IMPORTANT:** Do NOT execute this SQL on the user's behalf with the actual credential.

After confirmation, verify:
```sql
SHOW SECRETS LIKE '{secret_name}' IN SCHEMA SKILLS.PUBLIC;
```

### Step A6: Save profile

```sql
DELETE FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES WHERE name = '{profile_name}';

-- For token auth:
INSERT INTO SKILLS.PUBLIC.THOUGHTSPOT_PROFILES (name, base_url, username, auth_type, secret_name, token_expires_at)
SELECT '{profile_name}', '{base_url}', '{username}', '{auth_type}', '{secret_name}',
       TO_TIMESTAMP({expiry_millis}::NUMBER / 1000);

-- For password auth (expiry is NULL):
INSERT INTO SKILLS.PUBLIC.THOUGHTSPOT_PROFILES (name, base_url, username, auth_type, secret_name, token_expires_at)
SELECT '{profile_name}', '{base_url}', '{username}', 'password', '{secret_name}', NULL;
```

### Step A7: Set up External Access Integration

Extract the hostname from `{base_url}` (e.g. `champagne-master-aws.thoughtspotstaging.cloud`).

**Create or update the network rule:**

**IMPORTANT — Multi-profile support:** The network rule must include hostnames for
**ALL** existing profiles, not just the new one. First query existing profiles:

```sql
SELECT DISTINCT base_url FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES;
```

Extract all hostnames (including the new one) and include them all:

```sql
CREATE OR REPLACE NETWORK RULE SKILLS.PUBLIC.THOUGHTSPOT_API_RULE
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('{hostname_1}', '{hostname_2}', ...);
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

-- Include ALL secrets from ALL profiles:
CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION THOUGHTSPOT_API_ACCESS
  ALLOWED_NETWORK_RULES = (SKILLS.PUBLIC.THOUGHTSPOT_API_RULE)
  ALLOWED_AUTHENTICATION_SECRETS = (SKILLS.PUBLIC.{secret_1}, SKILLS.PUBLIC.{secret_2}, ...)
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
-- List ALL profile secrets here. When adding a new profile, add its secret.
-- Also update the get_secret_for_profile() mapping inside the procedure body.
SECRETS = ('ts_secret_slug1' = SKILLS.PUBLIC.{secret_1}, 'ts_secret_slug2' = SKILLS.PUBLIC.{secret_2}, ...)
AS
$$
import requests
import json
import _snowflake

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
        return s, {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }, None
    else:
        return None, {
            "Authorization": f"Bearer {secret_value}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }, None

def get_secret_for_profile(secret_name):
    # Map each secret_name to its SECRETS clause alias.
    # When adding a new profile, add its secret here and in the SECRETS clause.
    mapping = {
        # 'THOUGHTSPOT_TOKEN_EXAMPLE': 'ts_secret_example',
    }
    key = mapping.get(secret_name)
    if not key:
        return None
    return _snowflake.get_generic_secret_string(key)

def run(session, profile_name, query_string, owner_only):
    profile = session.sql(f"SELECT base_url, username, auth_type, secret_name FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES WHERE name = '{profile_name}'").collect()
    if not profile:
        return {"error": f"Profile '{profile_name}' not found"}

    row = profile[0].as_dict()
    base_url = row['BASE_URL'].rstrip('/')
    username = row['USERNAME']
    auth_type = row.get('AUTH_TYPE', 'token')
    secret_name = row['SECRET_NAME']
    secret_value = get_secret_for_profile(secret_name)
    if not secret_value:
        return {"error": f"Secret '{secret_name}' not mapped. Recreate procedures via Step A8."}
    verify_ssl = not base_url.startswith('https://172.') and not base_url.startswith('https://10.')

    http_session, headers, err = get_session_headers(base_url, username, secret_value, auth_type, verify_ssl)
    if err:
        return {"error": err}

    def do_post(url, json_body):
        if http_session:
            return http_session.post(url, headers=headers, json=json_body, verify=verify_ssl)
        return requests.post(url, headers=headers, json=json_body, verify=verify_ssl)

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

        resp = do_post(f"{base_url}/api/rest/2.0/metadata/search", body)

        if resp.status_code in (401, 403):
            return {"error": "Unauthorized. Run thoughtspot-setup to refresh credentials."}

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
-- List ALL profile secrets here. When adding a new profile, add its secret.
-- Also update the get_secret_for_profile() mapping inside the procedure body.
SECRETS = ('ts_secret_slug1' = SKILLS.PUBLIC.{secret_1}, 'ts_secret_slug2' = SKILLS.PUBLIC.{secret_2}, ...)
AS
$$
import requests
import json
import _snowflake

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
        return s, {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }, None
    else:
        return None, {
            "Authorization": f"Bearer {secret_value}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }, None

def get_secret_for_profile(secret_name):
    mapping = {
        # 'THOUGHTSPOT_TOKEN_EXAMPLE': 'ts_secret_example',
    }
    key = mapping.get(secret_name)
    if not key:
        return None
    return _snowflake.get_generic_secret_string(key)

def run(session, profile_name, guids):
    profile = session.sql(f"SELECT base_url, username, auth_type, secret_name FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES WHERE name = '{profile_name}'").collect()
    if not profile:
        return {"error": f"Profile '{profile_name}' not found"}

    row = profile[0].as_dict()
    base_url = row['BASE_URL'].rstrip('/')
    username = row['USERNAME']
    auth_type = row.get('AUTH_TYPE', 'token')
    secret_name = row['SECRET_NAME']
    secret_value = get_secret_for_profile(secret_name)
    if not secret_value:
        return {"error": f"Secret '{secret_name}' not mapped. Recreate procedures via Step A8."}
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
  3  Refresh token (token auth — provide a new one)
  4  Update password (password auth — provide a new one)

Enter 1–4:
```

Only show option 3 for `auth_type = 'token'` profiles.
Only show option 4 for `auth_type = 'password'` profiles.

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

### U4 — Update Password

For `auth_type = 'password'` profiles:

```
Run this SQL to update your password. Replace <YOUR_NEW_PASSWORD> with your new ThoughtSpot password:

  CREATE OR REPLACE SECRET SKILLS.PUBLIC.{secret_name}
    TYPE = GENERIC_STRING
    SECRET_STRING = '<YOUR_NEW_PASSWORD>'
    COMMENT = 'ThoughtSpot password for profile: {profile_name}';
```

**Also update the External Access Integration** to reference the refreshed secret
(requires ACCOUNTADMIN):

```sql
ALTER EXTERNAL ACCESS INTEGRATION THOUGHTSPOT_API_ACCESS
  SET ALLOWED_AUTHENTICATION_SECRETS = (SKILLS.PUBLIC.{secret_name});
```

Update the profile timestamp:
```sql
UPDATE SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
SET updated_at = CURRENT_TIMESTAMP()
WHERE name = '{profile_name}';
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
    name, auth_type,
    token_expires_at,
    CASE WHEN auth_type = 'password' THEN 'PASSWORD_AUTH'
         WHEN token_expires_at <= CURRENT_TIMESTAMP() THEN 'EXPIRED'
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

Check token expiry **before** making any API call (token auth profiles only):

```sql
SELECT
    name, auth_type, token_expires_at,
    CASE WHEN auth_type = 'password' THEN 'PASSWORD_AUTH'
         WHEN token_expires_at <= CURRENT_TIMESTAMP() THEN 'EXPIRED'
         WHEN token_expires_at <= TIMESTAMPADD('minute', 5, CURRENT_TIMESTAMP()) THEN 'EXPIRING_SOON'
         ELSE 'VALID'
    END AS token_status
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
WHERE name = '{profile_name}';
```

- **PASSWORD_AUTH**: No expiry check needed — proceed with API calls
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
| 401 / 403 from ThoughtSpot API | Token expired or password incorrect — run Update to refresh |
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
SELECT name, auth_type, token_expires_at,
    CASE WHEN auth_type = 'password' THEN TRUE
         ELSE token_expires_at > CURRENT_TIMESTAMP()
    END AS is_valid
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
WHERE name = '{profile_name}';
```

### Retrieve credentials in SQL

```sql
SELECT
    p.base_url, p.username, p.auth_type, p.secret_name, p.token_expires_at,
    CASE WHEN p.auth_type = 'password' THEN TRUE
         ELSE token_expires_at > CURRENT_TIMESTAMP()
    END AS is_valid,
    SYSTEM$GET_SECRET_STRING('SKILLS.PUBLIC.' || p.secret_name) AS secret_value
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES p
WHERE p.name = '{profile_name}';
```