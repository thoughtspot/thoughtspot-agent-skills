# Claude Code Skills — Setup Guide

A collection of Claude Code skills for working with ThoughtSpot.

---

## Skills

### [`setup-ts-profile`](setup-ts-profile/)

Manages ThoughtSpot connection profiles. Stores credentials securely in the macOS
Keychain, wires up `~/.zshenv` for env var persistence, and verifies connections.
Supports token, password, and secret key auth methods.

Run with `/setup-ts-profile`.

### [`setup-snowflake-profile`](setup-snowflake-profile/)

Manages Snowflake connection profiles. Supports two connection methods: Python
connector (key pair or password auth) and Snowflake CLI. Tests the connection
and saves the profile for use by other skills.

Run with `/setup-snowflake-profile`.

### [`object-ts-model-builder`](object-ts-model-builder/)

Builds a ThoughtSpot Model from a Snowflake schema or an ERD diagram image. Browses
Snowflake to select tables (or reads a hand-drawn diagram), ensures those tables are
linked in the ThoughtSpot connection, creates logical Table objects, and generates the
final Model with inferred or user-defined joins. Supports table-level and model-level
join strategies. Only creates Models — Worksheets are legacy and are not generated.

Run with `/object-ts-model-builder`.

### [`convert-ts-to-snowflake-sv`](convert-ts-to-snowflake-sv/)

Converts a ThoughtSpot Worksheet or Model into a Snowflake Semantic View. Exports
the TML definition via the ThoughtSpot REST API, maps columns and joins to the
Snowflake Semantic View YAML format, translates ThoughtSpot formulas to SQL, and
creates the view via `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`.

Handles case-sensitive Snowflake identifiers, SQL view auto-resolution, multi-model
batch conversion, and generates an Unmapped Properties Report for any ThoughtSpot
features that cannot be represented in the Semantic View format.

Run with `/convert-ts-to-snowflake-sv`.

### [`convert-ts-from-snowflake-sv`](convert-ts-from-snowflake-sv/)

Reverse-engineers a Snowflake Semantic View into a ThoughtSpot Model. Reads the
semantic view DDL via `GET_DDL`, maps tables, relationships, dimensions, and metrics
back to ThoughtSpot TML, translates SQL expressions to ThoughtSpot formulas, and
imports the model via the ThoughtSpot REST API.

Supports two scenarios: building on the underlying physical tables (reusing existing
ThoughtSpot Table objects and joins) or building on the semantic view's base tables
directly (creating new Table objects in the connection).

Run with `/convert-ts-from-snowflake-sv`.

### [`setup-databricks-profile`](setup-databricks-profile/)

Manages Databricks connection profiles for Unity Catalog skills. Stores PAT tokens
securely in the macOS Keychain, wires up `~/.zshenv`, and verifies the connection
against a configured SQL warehouse. Required before running `/convert-ts-to-unity-catalog`.

Run with `/setup-databricks-profile`.

### [`object-ts-model-promote`](object-ts-model-promote/)

Promotes formulas and parameters from a saved ThoughtSpot Answer into a Model
definition. Exports the Answer TML to extract formula expressions and parameters, maps
column references from the Answer context to the Model's table paths, validates the
updated Model TML against the self-validation checklist, and imports the change in-place.
Supports parameter promotion, formula inter-dependency detection, duplicate name
handling, and permission checking before import.

Run with `/object-ts-model-promote`.

### [`convert-ts-to-unity-catalog`](convert-ts-to-unity-catalog/)

Converts a ThoughtSpot Worksheet or Model into a Databricks Unity Catalog Metric View.
Exports the TML definition via the ThoughtSpot REST API, identifies the fact/source
table, builds a hierarchical join tree, maps columns to UC dimensions and measures,
translates ThoughtSpot formulas to Databricks SQL (with special handling for composed
measures, filtered aggregates, and semi-additive window measures), and creates the view
via `CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML`.

Handles multi-hop snowflake schemas, SQL view auto-resolution, multi-model batch
conversion, and generates an Unmapped Properties Report for any ThoughtSpot features
that cannot be represented in the Metric View format.

Run with `/convert-ts-to-unity-catalog`.

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
git clone https://github.com/djwaldo/thoughtspot-skills.git /tmp/thoughtspot-skills

mkdir -p ~/.claude/skills

cp -r /tmp/thoughtspot-skills/agents/claude/setup-ts-profile ~/.claude/skills/
cp -r /tmp/thoughtspot-skills/agents/claude/setup-snowflake-profile ~/.claude/skills/
cp -r /tmp/thoughtspot-skills/agents/claude/setup-databricks-profile ~/.claude/skills/
cp -r /tmp/thoughtspot-skills/agents/claude/object-ts-model-builder ~/.claude/skills/
cp -r /tmp/thoughtspot-skills/agents/claude/convert-ts-to-snowflake-sv ~/.claude/skills/
cp -r /tmp/thoughtspot-skills/agents/claude/convert-ts-from-snowflake-sv ~/.claude/skills/
cp -r /tmp/thoughtspot-skills/agents/claude/convert-ts-to-unity-catalog ~/.claude/skills/
cp -r /tmp/thoughtspot-skills/agents/claude/object-ts-model-promote ~/.claude/skills/

# Copy shared reference files (schemas, mappings, worked-examples) so skills can read them
cp -r /tmp/thoughtspot-skills/agents/shared ~/.claude/shared
cp -r /tmp/thoughtspot-skills/agents/shared/mappings ~/.claude/mappings

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

# Required for Databricks Unity Catalog skills (convert-ts-to-unity-catalog)
pip install databricks-sql-connector
```

Then complete [Credential Setup](#credential-setup) below.

---

## Developer Install

For users who want to modify the skill, track changes in git, or contribute back.

### 1. Clone the repo

```bash
git clone https://github.com/djwaldo/thoughtspot-skills.git ~/Dev/thoughtspot-skills
```

### 2. Create symlinks into Claude Code

```bash
mkdir -p ~/.claude/skills

# Skills (agent-specific entry points)
ln -s ~/Dev/thoughtspot-skills/agents/claude/setup-ts-profile \
      ~/.claude/skills/setup-ts-profile

ln -s ~/Dev/thoughtspot-skills/agents/claude/setup-snowflake-profile \
      ~/.claude/skills/setup-snowflake-profile

ln -s ~/Dev/thoughtspot-skills/agents/claude/object-ts-model-builder \
      ~/.claude/skills/object-ts-model-builder

ln -s ~/Dev/thoughtspot-skills/agents/claude/convert-ts-to-snowflake-sv \
      ~/.claude/skills/convert-ts-to-snowflake-sv

ln -s ~/Dev/thoughtspot-skills/agents/claude/convert-ts-from-snowflake-sv \
      ~/.claude/skills/convert-ts-from-snowflake-sv

ln -s ~/Dev/thoughtspot-skills/agents/claude/setup-databricks-profile \
      ~/.claude/skills/setup-databricks-profile

ln -s ~/Dev/thoughtspot-skills/agents/claude/convert-ts-to-unity-catalog \
      ~/.claude/skills/convert-ts-to-unity-catalog

ln -s ~/Dev/thoughtspot-skills/agents/claude/object-ts-model-promote \
      ~/.claude/skills/object-ts-model-promote

# Shared reference docs (schemas, mappings, worked-examples)
ln -s ~/Dev/thoughtspot-skills/agents/shared ~/.claude/shared
ln -s ~/Dev/thoughtspot-skills/agents/shared/mappings ~/.claude/mappings
```

Claude Code reads through the symlinks automatically. Edits in `~/Dev/` take effect
immediately — no copy step needed.

### 3. Install Python dependencies

```bash
# Required for all installs (ThoughtSpot API calls)
pip install requests pyyaml

# Required only if connecting to Snowflake via Python connector (not needed for Snowflake CLI)
pip install snowflake-connector-python cryptography

# Required for Databricks Unity Catalog skills (convert-ts-to-unity-catalog)
pip install databricks-sql-connector
```

### 4. Install the pre-commit hook

Runs validation checks automatically before every commit:

```bash
ln -s ../../scripts/pre-commit.sh .git/hooks/pre-commit
```

Then complete [Credential Setup](#credential-setup) below.

---

## Credential Setup

The setup skills handle all configuration interactively — you won't need to manually
edit config files or construct shell commands.

In Claude Code, run:

```
/setup-ts-profile
```

Claude will ask for your ThoughtSpot URL, username, and auth method (one question at
a time), store the credential securely in the macOS Keychain, wire up `~/.zshenv`,
and verify the connection before finishing.

Then run:

```
/setup-snowflake-profile
```

Claude will ask whether you're using the Python connector or Snowflake CLI, walk you
through auth setup (key pair or password), and verify the connection.

If you'll be using the Databricks Unity Catalog skills, also run:

```
/setup-databricks-profile
```

Claude will ask for your workspace hostname, SQL warehouse HTTP path, and guide you
through storing a Personal Access Token in the macOS Keychain.

All setup skills support multiple named profiles, so you can switch between
environments (e.g. staging and production) without re-entering credentials.

---

## Usage

All skills are invoked with a slash command in Claude Code. You can also describe
what you want in natural language and Claude will invoke the right skill.

**Conversion** — move semantic models between ThoughtSpot and data platforms

| Skill | Command | What it does |
|---|---|---|
| `convert-ts-to-snowflake-sv` | `/convert-ts-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View |
| `convert-ts-from-snowflake-sv` | `/convert-ts-from-snowflake-sv` | Reverse-engineer a Snowflake Semantic View into a ThoughtSpot Model |
| `convert-ts-to-unity-catalog` | `/convert-ts-to-unity-catalog` | Convert a ThoughtSpot model to a Databricks Unity Catalog Metric View |

**ThoughtSpot Objects** — author and manage ThoughtSpot Models

| Skill | Command | What it does |
|---|---|---|
| `object-ts-model-builder` | `/object-ts-model-builder` | Build a ThoughtSpot Model from a Snowflake schema or ERD image |
| `object-ts-model-promote` | `/object-ts-model-promote` | Promote formulas and parameters from a saved Answer into a Model |

**Setup** — manage connection profiles and credentials

| Skill | Command | What it does |
|---|---|---|
| `setup-ts-profile` | `/setup-ts-profile` | Add, update, test, or delete ThoughtSpot profiles |
| `setup-snowflake-profile` | `/setup-snowflake-profile` | Add, update, test, or delete Snowflake profiles |
| `setup-databricks-profile` | `/setup-databricks-profile` | Add, update, test, or delete Databricks profiles (PAT, SQL warehouse) |

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

**Databricks (for convert-ts-to-unity-catalog):**
- Databricks workspace with Unity Catalog enabled
- SQL warehouse running and accessible
- Personal Access Token with `CREATE TABLE` on the target UC schema

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
[~/.claude/skills/setup-ts-profile/SKILL.md](~/.claude/skills/setup-ts-profile/SKILL.md)
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

### Before committing changes

Run the validation suite to catch common issues before they reach GitHub:

```bash
python tools/validate/check_references.py     # verify all file paths in SKILL.md files exist
python tools/validate/check_patterns.py       # detect known TML and code anti-patterns
python tools/validate/check_yaml.py           # validate YAML code blocks in .md files
python tools/validate/check_version_sync.py   # confirm ts-cli version is in sync
pytest tools/ts-cli/tests/                    # unit tests for CLI functions (no live API needed)
```

All checks should pass before opening a PR. See `tools/validate/README.md` for details.

### Pull requests

- One skill (or one coherent change to an existing skill) per PR
- Update the skills table in this README for any new skill
- Add the symlink command to the Developer Install section
- If the skill requires a new Python dependency, add it to both install sections
