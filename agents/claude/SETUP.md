# Claude Code Skills — Setup Guide

A collection of Claude Code skills for working with ThoughtSpot.

---

## Skills

### [`thoughtspot-setup`](thoughtspot-setup/)

Manages ThoughtSpot connection profiles. Stores credentials securely in the macOS
Keychain, wires up `~/.zshenv` for env var persistence, and verifies connections.
Supports token, password, and secret key auth methods.

Run with `/thoughtspot-setup`.

### [`snowflake-setup`](snowflake-setup/)

Manages Snowflake connection profiles. Supports two connection methods: Python
connector (key pair or password auth) and Snowflake CLI. Tests the connection
and saves the profile for use by other skills.

Run with `/snowflake-setup`.

### [`thoughtspot-model-builder`](thoughtspot-model-builder/)

Builds a ThoughtSpot Model from a Snowflake schema or an ERD diagram image. Browses
Snowflake to select tables (or reads a hand-drawn diagram), ensures those tables are
linked in the ThoughtSpot connection, creates logical Table objects, and generates the
final Model with inferred or user-defined joins. Supports table-level and model-level
join strategies. Only creates Models — Worksheets are legacy and are not generated.

Run with `/thoughtspot-model-builder`.

### [`ts-to-snowflake-sv`](ts-to-snowflake-sv/)

Converts a ThoughtSpot Worksheet or Model into a Snowflake Semantic View. Exports
the TML definition via the ThoughtSpot REST API, maps columns and joins to the
Snowflake Semantic View YAML format, translates ThoughtSpot formulas to SQL, and
creates the view via `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`.

Handles case-sensitive Snowflake identifiers, SQL view auto-resolution, multi-model
batch conversion, and generates an Unmapped Properties Report for any ThoughtSpot
features that cannot be represented in the Semantic View format.

Run with `/ts-to-snowflake-sv`.

### [`ts-from-snowflake-sv`](ts-from-snowflake-sv/)

Reverse-engineers a Snowflake Semantic View into a ThoughtSpot Model. Reads the
semantic view DDL via `GET_DDL`, maps tables, relationships, dimensions, and metrics
back to ThoughtSpot TML, translates SQL expressions to ThoughtSpot formulas, and
imports the model via the ThoughtSpot REST API.

Supports two scenarios: building on the underlying physical tables (reusing existing
ThoughtSpot Table objects and joins) or building on the semantic view's base tables
directly (creating new Table objects in the connection).

Run with `/ts-from-snowflake-sv`.

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

mkdir -p ~/.claude/skills

cp -r /tmp/thoughtspot-skills/agents/claude/thoughtspot-setup ~/.claude/skills/
cp -r /tmp/thoughtspot-skills/agents/claude/snowflake-setup ~/.claude/skills/
cp -r /tmp/thoughtspot-skills/agents/claude/thoughtspot-model-builder ~/.claude/skills/
cp -r /tmp/thoughtspot-skills/agents/claude/ts-to-snowflake-sv ~/.claude/skills/
cp -r /tmp/thoughtspot-skills/agents/claude/ts-from-snowflake-sv ~/.claude/skills/

# Also copy shared reference files so skills can read them
cp -r /tmp/thoughtspot-skills/shared ~/.claude/
cp -r /tmp/thoughtspot-skills/mappings ~/.claude/

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
mkdir -p ~/.claude/skills

# Skills (agent-specific entry points)
ln -s ~/Dev/thoughtspot-skills/agents/claude/thoughtspot-setup \
      ~/.claude/skills/thoughtspot-setup

ln -s ~/Dev/thoughtspot-skills/agents/claude/snowflake-setup \
      ~/.claude/skills/snowflake-setup

ln -s ~/Dev/thoughtspot-skills/agents/claude/thoughtspot-model-builder \
      ~/.claude/skills/thoughtspot-model-builder

ln -s ~/Dev/thoughtspot-skills/agents/claude/ts-to-snowflake-sv \
      ~/.claude/skills/ts-to-snowflake-sv

ln -s ~/Dev/thoughtspot-skills/agents/claude/ts-from-snowflake-sv \
      ~/.claude/skills/ts-from-snowflake-sv

# Shared reference docs (mappings and platform knowledge)
ln -s ~/Dev/thoughtspot-skills/mappings ~/.claude/mappings
ln -s ~/Dev/thoughtspot-skills/shared ~/.claude/shared
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

Claude will ask for your ThoughtSpot URL, username, and auth method (one question at
a time), store the credential securely in the macOS Keychain, wire up `~/.zshenv`,
and verify the connection before finishing.

Then run:

```
/snowflake-setup
```

Claude will ask whether you're using the Python connector or Snowflake CLI, walk you
through auth setup (key pair or password), and verify the connection.

Both setup skills support multiple named profiles, so you can switch between
environments (e.g. staging and production) without re-entering credentials.

---

## Usage

All skills are invoked with a slash command in Claude Code. You can also describe
what you want in natural language and Claude will invoke the right skill.

| Skill | Command | What it does |
|---|---|---|
| `thoughtspot-setup` | `/thoughtspot-setup` | Add, update, test, or delete ThoughtSpot profiles |
| `snowflake-setup` | `/snowflake-setup` | Add, update, test, or delete Snowflake profiles |
| `thoughtspot-model-builder` | `/thoughtspot-model-builder` | Build a ThoughtSpot Model from a Snowflake schema or ERD image |
| `ts-to-snowflake-sv` | `/ts-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View |
| `ts-from-snowflake-sv` | `/ts-from-snowflake-sv` | Reverse-engineer a Snowflake Semantic View into a ThoughtSpot Model |

Example for the conversion skill:

```
Convert my ThoughtSpot Retail Sales model to a Snowflake Semantic View
```

The conversion skill will guide you through:
1. Selecting a ThoughtSpot model or worksheet (by GUID, search, or browse)
2. Choosing where in Snowflake to create the view
3. Reviewing the generated YAML and any unmapped properties
4. Dry-run validation, then creating the view

You can convert multiple models in one session — the skill reuses your selected
profiles and credentials across the batch.

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
- macOS (Keychain used for credential storage)

---

## Contributing

### Skill structure

Each skill lives in its own directory with a `SKILL.md` as the entry point:

```
skill-name/
  SKILL.md          — frontmatter + full skill instructions
  references/       — supporting reference docs (optional)
    open-items.md   — unknowns to test before the skill is complete
    *.md            — lookup tables, schema references, worked examples
```

`SKILL.md` must start with YAML frontmatter:

```yaml
---
name: skill-name
description: One sentence shown in Claude Code's skill picker — be specific about inputs and outputs.
---
```

Skills reference other skills by path (never by copying content):

```markdown
[~/.claude/skills/thoughtspot-setup/SKILL.md](~/.claude/skills/thoughtspot-setup/SKILL.md)
```

### Credential and secret handling

- Credentials are never stored in skill files or passed through the Claude Code conversation
- Passwords and tokens live in the macOS Keychain, exported via `~/.zshenv`
- Temporary files written to `/tmp/` must be removed at the end of the skill
- No API keys, tokens, passwords, profile JSON files, or `.env` files in commits — the `.gitignore` covers common patterns but use judgement

### Tracking unknowns

If a skill depends on API behaviour that hasn't been verified against a live instance,
document it in `references/open-items.md` with:
- What needs testing and why it matters
- A self-contained test script
- A space to record the finding

Don't merge a skill with unresolved open items unless they are explicitly marked as
low-risk or deferred.

### Pull requests

- One skill (or one coherent change to an existing skill) per PR
- Update the skills table in this README for any new skill
- Add the symlink command to the Developer Install section
- If the skill requires a new Python dependency, add it to both install sections
