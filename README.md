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

1. Copy the skill directory into your Claude Code skills folder:

```bash
cp -r thoughtspot-snowflake-semantic-view ~/.claude/skills/
```

2. Configure your ThoughtSpot profile in `~/.claude/thoughtspot-profiles.json`:

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

3. Export the secret key in `~/.zshrc`:

```bash
export THOUGHTSPOT_SECRET_KEY_PROD=your-secret-key
```

4. Configure your Snowflake profile in `~/.claude/snowflake-profiles.json`:

```json
{
  "profiles": [
    {
      "name": "My Snowflake Account",
      "account": "myorg-myaccount",
      "username": "analyst",
      "auth": "key_pair",
      "private_key_path": "~/.ssh/snowflake_private_key.p8",
      "default_warehouse": "MY_WAREHOUSE",
      "default_role": "MY_ROLE"
    }
  ]
}
```

5. Install Python packages for Snowflake connectivity (if not already present):

```bash
pip install snowflake-connector-python cryptography
```

---

## Usage

In Claude Code, invoke the skill with a natural language prompt such as:

```
Convert my ThoughtSpot Retail Sales model to a Snowflake Semantic View
```

or simply:

```
/thoughtspot-snowflake-semantic-view
```

The skill will guide you through selecting a ThoughtSpot model or worksheet,
previewing the generated YAML at a checkpoint before anything is written to
Snowflake, and then creating the view.

---

## Requirements

**ThoughtSpot:**
- v8.4 or later, REST API v2 enabled
- User with `DATAMANAGEMENT` or `DEVELOPER` privilege, or a trusted auth secret key

**Snowflake:**
- Role with `CREATE SEMANTIC VIEW` privilege on the target schema
- Snowflake account where Cortex Analyst / Semantic Views are enabled
