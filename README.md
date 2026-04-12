# ThoughtSpot Claude Code Skills

A collection of Claude Code skills for working with ThoughtSpot.

---

## Skills

### [`thoughtspot-snowflake-semantic-view`](thoughtspot-snowflake-semantic-view/)

Converts a ThoughtSpot Worksheet or Model into a Snowflake Semantic View. Exports
the TML definition via the ThoughtSpot REST API, maps columns and joins to the
Snowflake Semantic View YAML format, translates ThoughtSpot formulas to SQL, and
creates the view via `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`.

---

## Installation

### 1. Copy the skill

```bash
cp -r thoughtspot-snowflake-semantic-view ~/.claude/skills/
```

### 2. Configure ThoughtSpot

Create `~/.claude/thoughtspot-profiles.json`:

```json
{
  "profiles": [
    {
      "name": "Production",
      "base_url": "https://myorg.thoughtspot.cloud",
      "username": "analyst@company.com",
      "secret_key_env": "THOUGHTSPOT_SECRET_KEY_PROD"
    }
  ]
}
```

Export the secret key in `~/.zshrc` (or `~/.bashrc`):

```bash
export THOUGHTSPOT_SECRET_KEY_PROD=your-secret-key
```

### 3. Configure Snowflake

The skill connects to Snowflake using the **Python connector** — the recommended
approach because Python is already required for the ThoughtSpot API calls and the
skill's profile system integrates with it directly.

Install the required packages:

```bash
pip install snowflake-connector-python cryptography
```

Create `~/.claude/snowflake-profiles.json`. Two auth methods are supported:

**Key pair (recommended):**
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
    }
  ]
}
```

To generate a key pair if you don't already have one:
```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out ~/.ssh/snowflake_private_key.p8 -nocrypt
openssl rsa -in ~/.ssh/snowflake_private_key.p8 -pubout -out ~/.ssh/snowflake_public_key.pub
```
Then assign the public key to your Snowflake user:
```sql
ALTER USER analyst SET RSA_PUBLIC_KEY='<contents of snowflake_public_key.pub>';
```

**Password:**
```json
{
  "profiles": [
    {
      "name": "My Snowflake Account",
      "account": "myorg-myaccount",
      "username": "analyst",
      "auth": "password",
      "password_env": "SNOWFLAKE_PASSWORD",
      "default_warehouse": "MY_WAREHOUSE",
      "default_role": "MY_ROLE"
    }
  ]
}
```

Export the password in `~/.zshrc`:
```bash
export SNOWFLAKE_PASSWORD=your-password
```

> **Other connection methods:** If you have the [Snowflake CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli/index) (`snow`) or SnowSQL installed, the skill will detect and use them as fallbacks. However, those tools require their own separate auth configuration and are not covered here.

---

## Usage

In Claude Code, invoke the skill with a natural language prompt such as:

```
Convert my ThoughtSpot Retail Sales model to a Snowflake Semantic View
```

The skill will guide you through:
1. Selecting a ThoughtSpot model or worksheet (by GUID, search, or browse)
2. Previewing the generated Semantic View YAML and an unmapped properties report
3. Choosing where in Snowflake to create the view
4. Creating the view (with a dry-run validation first)

---

## Requirements

**ThoughtSpot:**
- v8.4 or later, REST API v2 enabled
- User with `DATAMANAGEMENT` or `DEVELOPER` privilege, or a trusted auth secret key

**Snowflake:**
- Role with `CREATE SEMANTIC VIEW` privilege on the target schema
- Snowflake account where Cortex Analyst / Semantic Views are enabled
- Python 3.8+
