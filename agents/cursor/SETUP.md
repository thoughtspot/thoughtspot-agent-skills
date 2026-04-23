# Cursor Rules — Setup Guide

A collection of Cursor AI rules for working with ThoughtSpot and Snowflake.

---

## Rules

### `ts-profile-thoughtspot`

Manages ThoughtSpot connection profiles. Stores credentials securely in the OS credential
store (macOS Keychain, Windows Credential Manager, Linux Secret Service), and verifies
connections. Supports token, password, and secret key auth methods.

Trigger by asking: "Set up my ThoughtSpot profile" or "Add a ThoughtSpot connection".

### `ts-profile-snowflake`

Manages Snowflake connection profiles. Supports Python connector (key pair or password)
and Snowflake CLI. Tests the connection and saves the profile for use by other rules.

Trigger by asking: "Set up my Snowflake profile" or "Add a Snowflake connection".

### `ts-convert-to-snowflake-sv`

Converts a ThoughtSpot Worksheet or Model into a Snowflake Semantic View. Exports the
TML definition, maps columns and joins, translates formulas to SQL, and creates the view.

Trigger by asking: "Convert my ThoughtSpot model to a Snowflake Semantic View".

### `ts-convert-from-snowflake-sv`

Reverse-engineers a Snowflake Semantic View into a ThoughtSpot Model. Reads the view
DDL, maps tables and joins, translates SQL expressions to ThoughtSpot formulas, and
imports the result.

Trigger by asking: "Convert my Snowflake Semantic View to a ThoughtSpot model".

### `ts-object-answer-promote`

Promotes formulas and parameters from a saved ThoughtSpot Answer into a Model, making
them available to all users who search against it.

Trigger by asking: "Promote formulas from this Answer to the Model".

---

## Installation

### 1. Clone the repo

```bash
# macOS / Linux
git clone https://github.com/djwaldo/thoughtspot-agent-skills.git ~/Dev/thoughtspot-agent-skills

# Windows (PowerShell)
git clone https://github.com/djwaldo/thoughtspot-agent-skills.git "$env:USERPROFILE\Dev\thoughtspot-agent-skills"
```

### 2. Install Python dependencies

```bash
# Required for all installs
pip install requests pyyaml keyring

# Required only for Snowflake via Python connector (not needed for Snowflake CLI)
pip install snowflake-connector-python cryptography

# Linux only — Secret Service backend for keyring
pip install secretstorage
```

### 3. Install the ts CLI

```bash
# macOS / Linux
pip install -e ~/Dev/thoughtspot-agent-skills/tools/ts-cli

# Windows (PowerShell)
pip install -e "$env:USERPROFILE\Dev\thoughtspot-agent-skills\tools\ts-cli"
```

### 4. Create the shared reference symlink

This makes schemas, mappings, and worked examples available to Cursor rules.

```bash
# macOS / Linux
mkdir -p ~/.cursor
ln -s ~/Dev/thoughtspot-agent-skills/agents/shared ~/.cursor/shared

# Windows (PowerShell — run as Administrator if symlinks require elevated permissions)
New-Item -ItemType Directory -Force "$env:USERPROFILE\.cursor" | Out-Null
New-Item -ItemType SymbolicLink `
  -Path "$env:USERPROFILE\.cursor\shared" `
  -Target "$env:USERPROFILE\Dev\thoughtspot-agent-skills\agents\shared"
```

### 5. Install rules into your project

Run the install script from your project directory:

```bash
# macOS / Linux
cd /path/to/your/project
~/Dev/thoughtspot-agent-skills/agents/cursor/scripts/install.sh

# Windows (PowerShell)
cd C:\path\to\your\project
& "$env:USERPROFILE\Dev\thoughtspot-agent-skills\agents\cursor\scripts\install.ps1"
```

This creates `.cursor/rules/*.mdc` symlinks pointing into the repo. Edits in `~/Dev/`
take effect immediately — no copy step needed.

**To update rules later:** `git pull` in the repo — symlinks pick up changes automatically.

---

## Credential Setup

In Cursor, describe what you want to the AI:

```
Set up my ThoughtSpot connection profile
```

The AI will invoke the `ts-profile-thoughtspot` rule and walk you through:
- Your ThoughtSpot URL, username, and auth method (one question at a time)
- Storing the credential securely in your OS credential store
- Verifying the connection

Then:

```
Set up my Snowflake connection profile
```

The AI will invoke the `ts-profile-snowflake` rule.

All rules support multiple named profiles, so you can switch between environments
(e.g. staging and production) without re-entering credentials.

---

## Requirements

**ThoughtSpot:**
- v8.4 or later, REST API v2 enabled
- User with `DATAMANAGEMENT` or `DEVELOPER` privilege

**Snowflake:**
- Role with `CREATE SEMANTIC VIEW` privilege on the target schema
- Snowflake account with Cortex Analyst / Semantic Views enabled

**Local:**
- Python 3.9+
- Cursor 0.40+
- macOS, Windows 10+, or Linux (with Secret Service / KWallet for keyring)

---

## Contributing

### Rule structure

Each rule is a single `.mdc` file in `agents/cursor/rules/`:

```
rules/
  {skill-name}.mdc     — Cursor frontmatter + full rule instructions
```

Rules share the same reference content as Claude Code skills (`agents/shared/`).
When adding or modifying logic, keep the `.mdc` file in sync with the corresponding
`agents/claude/<skill>/SKILL.md`.

### Credential and secret handling

Identical to Claude Code skills. See `.claude/rules/security.md` for the full policy.
Key rule: credentials are never stored in files or passed through the AI conversation.
