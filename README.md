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

Choose the path that fits your use case:

- **[Quick Install](#quick-install)** — just want to run the skill, no development
- **[Developer Install](#developer-install)** — want to modify the skill or contribute changes

Both paths require the same [credential setup](#credential-setup) afterwards.

---

## Quick Install

For users who want to run the skill without managing a local repo.

### 1. Copy the skill files

```bash
# Clone once to get the files, then copy them into place
git clone https://github.com/<org>/thoughtspot-skills.git /tmp/thoughtspot-skills

mkdir -p ~/.claude/skills ~/.claude/references

cp -r /tmp/thoughtspot-skills/thoughtspot-snowflake-semantic-view ~/.claude/skills/
cp /tmp/thoughtspot-skills/references/*.md ~/.claude/references/

rm -rf /tmp/thoughtspot-skills
```

> To update the skill later, repeat the above steps. Your profile and credential
> files are not affected.

### 2. Install Python dependencies

```bash
# Required for all installs (ThoughtSpot API calls)
pip install requests pyyaml

# Required only if connecting to Snowflake via Python connector (not needed for Snowflake CLI)
pip install snowflake-connector-python cryptography
```

Then complete [Credential Setup](#credential-setup) below.

---

## Developer Install

For users who want to modify the skill, track changes in git, or contribute back.

### 1. Clone the repo

```bash
git clone https://github.com/<org>/thoughtspot-skills.git ~/Dev/thoughtspot-skills
```

### 2. Create symlinks into Claude Code

```bash
mkdir -p ~/.claude/skills ~/.claude/references

ln -s ~/Dev/thoughtspot-skills/thoughtspot-snowflake-semantic-view \
      ~/.claude/skills/thoughtspot-snowflake-semantic-view

ln -s ~/Dev/thoughtspot-skills/references \
      ~/.claude/references
```

Claude Code reads through the symlinks automatically. Edits in `~/Dev/` take effect
immediately — no copy step needed.

### 3. Install Python dependencies

```bash
# Required for all installs (ThoughtSpot API calls)
pip install requests pyyaml

# Required only if connecting to Snowflake via Python connector (not needed for Snowflake CLI)
pip install snowflake-connector-python cryptography
```

Then complete [Credential Setup](#credential-setup) below.

---

## Credential Setup

The setup skills handle all configuration interactively — you won't need to manually
edit config files or construct shell commands.

In Claude Code, run:

```
/thoughtspot-setup
```

Claude will ask for your ThoughtSpot URL, username, and credential (one question at
a time), store everything securely in the macOS Keychain, and verify the connection
before finishing.

Then run:

```
/snowflake-setup
```

Claude will ask whether you're using the Python connector or Snowflake CLI, walk you
through auth setup (key pair or password), and verify the connection.

---

## Usage

In Claude Code, start the skill with:

```
/thoughtspot-snowflake-semantic-view
```

Or describe what you want in natural language:

```
Convert my ThoughtSpot Retail Sales model to a Snowflake Semantic View
```

The skill will guide you through:
1. Selecting a ThoughtSpot model or worksheet (by GUID, search, or browse)
2. Choosing where in Snowflake to create the view
3. Reviewing the generated YAML and any unmapped properties
4. Dry-run validation, then creating the view

---

## Requirements

**ThoughtSpot:**
- v8.4 or later, REST API v2 enabled
- User with `DATAMANAGEMENT` or `DEVELOPER` privilege

**Snowflake:**
- Role with `CREATE SEMANTIC VIEW` privilege on the target schema
- Snowflake account with Cortex Analyst / Semantic Views enabled

**Local:**
- Python 3.8+
- macOS (Keychain used for credential storage; see `references/credential-storage.md` for Linux alternatives)
