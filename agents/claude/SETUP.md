# Claude Code Skills — Setup Guide

A collection of Claude Code skills for working with ThoughtSpot.

---

## Skills

### [`ts-profile-thoughtspot`](ts-profile-thoughtspot/)

Manages ThoughtSpot connection profiles. Stores credentials securely in the macOS
Keychain, wires up `~/.zshenv` for env var persistence, and verifies connections.
Supports token, password, and secret key auth methods.

Run with `/ts-profile-thoughtspot`.

### [`ts-profile-snowflake`](ts-profile-snowflake/)

Manages Snowflake connection profiles. Supports two connection methods: Python
connector (key pair or password auth) and Snowflake CLI. Tests the connection
and saves the profile for use by other skills.

Run with `/ts-profile-snowflake`.

### [`ts-convert-to-snowflake-sv`](ts-convert-to-snowflake-sv/)

Converts a ThoughtSpot Worksheet or Model into a Snowflake Semantic View. Exports
the TML definition via the ThoughtSpot REST API, maps columns and joins to the
Snowflake Semantic View YAML format, translates ThoughtSpot formulas to SQL, and
creates the view via `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`.

Handles case-sensitive Snowflake identifiers, SQL view auto-resolution, multi-model
batch conversion, and generates an Unmapped Properties Report for any ThoughtSpot
features that cannot be represented in the Semantic View format.

Run with `/ts-convert-to-snowflake-sv`.

### [`ts-convert-from-snowflake-sv`](ts-convert-from-snowflake-sv/)

Reverse-engineers a Snowflake Semantic View into a ThoughtSpot Model. Reads the
semantic view DDL via `GET_DDL`, maps tables, relationships, dimensions, and metrics
back to ThoughtSpot TML, translates SQL expressions to ThoughtSpot formulas, and
imports the model via the ThoughtSpot REST API.

Supports two scenarios: building on the underlying physical tables (reusing existing
ThoughtSpot Table objects and joins) or building on the semantic view's base tables
directly (creating new Table objects in the connection).

Run with `/ts-convert-from-snowflake-sv`.

### [`ts-object-answer-promote`](ts-object-answer-promote/)

Promotes formulas and parameters from a saved ThoughtSpot Answer into a Model
definition. Exports the Answer TML to extract formula expressions and parameters, maps
column references from the Answer context to the Model's table paths, validates the
updated Model TML against the self-validation checklist, and imports the change in-place.
Supports parameter promotion, formula inter-dependency detection, duplicate name
handling, and permission checking before import.

Run with `/ts-object-answer-promote`.

### [`ts-dependency-manager`](ts-dependency-manager/)

Safely removes or renames columns and repoints objects across a ThoughtSpot environment.
Scans all Answers, Liveboards, and Models for dependencies on the source object, generates
a risk-rated impact report with hyperlinks, takes TML backups before any change, and
supports full rollback. Supports three operations: remove column(s) from a connection table
or Model, rename a column and propagate the change to all dependents, or repoint Answers
and Liveboards to a different Model with column-gap detection.

Run with `/ts-dependency-manager`.

### [`ts-timezone-variable`](ts-timezone-variable/)

Manages the `ts_user_timezone` template variable — search current assignments, set a
timezone for an org or user (IANA format), or remove a previously set value. Supports
org-level and user-level assignments.

Run with `/ts-timezone-variable`.

### [`ts-coach-model`](ts-coach-model/)

Comprehensively prepares a ThoughtSpot Model for Spotter. Reviews existing AI Context,
synonyms, and description critically with KEEP/ADD/REFINE/REWRITE deltas; mines
dependent Liveboards/Answers (and optionally the underlying Snowflake query history)
for real business language; then generates the user's chosen mix of Column AI Context,
Column Synonyms, Reference Questions, Business Terms, and a Data Model Instructions
draft. Supports an up-front scope menu and per-row Method overrides during review
(Method A: Synonym, Method B: Business Term, Method C: Reference Question).

Run with `/ts-coach-model`.

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
git clone https://github.com/thoughtspot/thoughtspot-agent-skills.git /tmp/thoughtspot-agent-skills

mkdir -p ~/.claude/skills

cp -r /tmp/thoughtspot-agent-skills/agents/claude/ts-profile-thoughtspot ~/.claude/skills/
cp -r /tmp/thoughtspot-agent-skills/agents/claude/ts-profile-snowflake ~/.claude/skills/
cp -r /tmp/thoughtspot-agent-skills/agents/claude/ts-convert-to-snowflake-sv ~/.claude/skills/
cp -r /tmp/thoughtspot-agent-skills/agents/claude/ts-convert-from-snowflake-sv ~/.claude/skills/
cp -r /tmp/thoughtspot-agent-skills/agents/claude/ts-object-answer-promote ~/.claude/skills/
cp -r /tmp/thoughtspot-agent-skills/agents/claude/ts-coach-model ~/.claude/skills/
cp -r /tmp/thoughtspot-agent-skills/agents/claude/ts-timezone-variable ~/.claude/skills/

# Copy shared reference files (schemas, mappings, worked-examples) so skills can read them
cp -r /tmp/thoughtspot-agent-skills/agents/shared ~/.claude/shared
cp -r /tmp/thoughtspot-agent-skills/agents/shared/mappings ~/.claude/mappings

rm -rf /tmp/thoughtspot-agent-skills
```

> To update the skill later, repeat the above steps. Your profile and credential
> files are not affected.

### 2. Install Python dependencies

```bash
# Required for all installs (ThoughtSpot API calls + cross-platform credential store)
pip install requests pyyaml keyring

# Required only if connecting to Snowflake via Python connector (not needed for Snowflake CLI)
pip install snowflake-connector-python cryptography

# Linux only — Secret Service backend for keyring
pip install secretstorage
```

Then complete [Credential Setup](#credential-setup) below.

---

## Developer Install

For users who want to modify the skill, track changes in git, or contribute back.

### 1. Clone the repo

```bash
git clone https://github.com/thoughtspot/thoughtspot-agent-skills.git ~/Dev/thoughtspot-agent-skills
```

### 2. Create symlinks into Claude Code

```bash
mkdir -p ~/.claude/skills

# Skills (agent-specific entry points)
ln -s ~/Dev/thoughtspot-agent-skills/agents/claude/ts-profile-thoughtspot \
      ~/.claude/skills/ts-profile-thoughtspot

ln -s ~/Dev/thoughtspot-agent-skills/agents/claude/ts-profile-snowflake \
      ~/.claude/skills/ts-profile-snowflake

ln -s ~/Dev/thoughtspot-agent-skills/agents/claude/ts-convert-to-snowflake-sv \
      ~/.claude/skills/ts-convert-to-snowflake-sv

ln -s ~/Dev/thoughtspot-agent-skills/agents/claude/ts-convert-from-snowflake-sv \
      ~/.claude/skills/ts-convert-from-snowflake-sv

ln -s ~/Dev/thoughtspot-agent-skills/agents/claude/ts-object-answer-promote \
      ~/.claude/skills/ts-object-answer-promote

ln -s ~/Dev/thoughtspot-agent-skills/agents/claude/ts-coach-model \
      ~/.claude/skills/ts-coach-model

ln -s ~/Dev/thoughtspot-agent-skills/agents/claude/ts-timezone-variable \
      ~/.claude/skills/ts-timezone-variable

# Shared reference docs (schemas, mappings, worked-examples)
ln -s ~/Dev/thoughtspot-agent-skills/agents/shared ~/.claude/shared
ln -s ~/Dev/thoughtspot-agent-skills/agents/shared/mappings ~/.claude/mappings
```

Claude Code reads through the symlinks automatically. Edits in `~/Dev/` take effect
immediately — no copy step needed.

### 3. Install Python dependencies

```bash
# Required for all installs (ThoughtSpot API calls + cross-platform credential store)
pip install requests pyyaml keyring

# Required only if connecting to Snowflake via Python connector (not needed for Snowflake CLI)
pip install snowflake-connector-python cryptography

# Linux only — Secret Service backend for keyring
pip install secretstorage
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
/ts-profile-thoughtspot
```

Claude will ask for your ThoughtSpot URL, username, and auth method (one question at
a time), store the credential securely in your OS credential store, wire up your shell
profile (macOS/Linux), and verify the connection before finishing.

Then run:

```
/ts-profile-snowflake
```

Claude will ask whether you're using the Python connector or Snowflake CLI, walk you
through auth setup (key pair or password), and verify the connection.

All setup skills support multiple named profiles, so you can switch between
environments (e.g. staging and production) without re-entering credentials.

---

## Usage

All skills are invoked with a slash command in Claude Code. You can also describe
what you want in natural language and Claude will invoke the right skill.

**Conversion** — move semantic models between ThoughtSpot and data platforms

| Skill | Command | What it does |
|---|---|---|
| `ts-convert-to-snowflake-sv` | `/ts-convert-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View |
| `ts-convert-from-snowflake-sv` | `/ts-convert-from-snowflake-sv` | Reverse-engineer a Snowflake Semantic View into a ThoughtSpot Model |

**ThoughtSpot Objects** — author and manage ThoughtSpot Models

| Skill | Command | What it does |
|---|---|---|
| `ts-object-answer-promote` | `/ts-object-answer-promote` | Promote formulas and parameters from a saved Answer into a Model |
| `ts-dependency-manager` | `/ts-dependency-manager` | Remove or rename columns and repoint objects — with impact report, TML backup, and rollback |
| `ts-coach-model` | `/ts-coach-model` | Comprehensively prepare a Model for Spotter: review existing AI assets, mine dependent objects + Snowflake history, generate Column AI Context / Synonyms / Reference Questions / Business Terms / Data Model Instructions draft |

**Setup** — manage connection profiles and credentials

| Skill | Command | What it does |
|---|---|---|
| `ts-profile-thoughtspot` | `/ts-profile-thoughtspot` | Add, update, test, or delete ThoughtSpot profiles |
| `ts-profile-snowflake` | `/ts-profile-snowflake` | Add, update, test, or delete Snowflake profiles |

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
- Python 3.9+
- macOS, Windows 10+, or Linux (with Secret Service / KWallet for keyring)

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
[~/.claude/skills/ts-profile-thoughtspot/SKILL.md](~/.claude/skills/ts-profile-thoughtspot/SKILL.md)
```

### Credential and secret handling

- Credentials are never stored in skill files or passed through the Claude Code conversation
- Passwords and tokens live in the OS credential store (macOS Keychain, Windows Credential Manager, Linux Secret Service), with optional export via shell profile (`~/.zshenv` on macOS/Linux)
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
