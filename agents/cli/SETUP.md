# Setup Guide — CLI Skills (Claude Code & Cortex Code)

These skills work in both **Claude Code** and **Cortex Code CLI**. Both runtimes
have full shell access and use the `ts` CLI for ThoughtSpot API calls.

---

## Prerequisites

### 1. Install a coding agent

**Cortex Code CLI** (recommended for Snowflake users):

| Platform | Command |
|---|---|
| macOS / Linux / WSL | `curl -LsS https://ai.snowflake.com/static/cc-scripts/install.sh \| sh` |
| Windows (PowerShell) | `irm https://ai.snowflake.com/static/cc-scripts/install.ps1 \| iex` |

Then run `cortex` to launch and connect to your Snowflake account.

**Claude Code CLI:**

| Platform | Command |
|---|---|
| macOS / Linux | `curl -fsSL https://claude.ai/install.sh \| bash` |
| Windows / npm | `npm install -g @anthropic-ai/claude-code` |

Then run `claude` to launch.

### 2. Other requirements

- Python 3.9–3.13 (Python 3.14 has a macOS `libexpat` incompatibility — see [Troubleshooting](#troubleshooting))
- Git (to clone or update the repo)

---

## Step 1: Clone the repository

```bash
git clone https://github.com/thoughtspot/thoughtspot-agent-skills.git ~/thoughtspot-agent-skills
```

---

## Step 2: Install the `ts` CLI

```bash
pip install -e ~/thoughtspot-agent-skills/tools/ts-cli
```

> **Python version:** use Python 3.9–3.13. If `pip` defaults to Python 3.14, specify
> the version explicitly: `pip3.12 install -e ~/thoughtspot-agent-skills/tools/ts-cli`
> (install Python 3.12 first with `brew install python@3.12` if needed).

Verify:

```bash
ts --help
```

---

## Step 3: Install skills

Choose your runtime below. Skills are the same — only the install location differs.

### For Cortex Code CLI

```bash
mkdir -p ~/.snowflake/cortex/skills

# Symlink each skill
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-profile-thoughtspot \
      ~/.snowflake/cortex/skills/ts-profile-thoughtspot

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-to-snowflake-sv \
      ~/.snowflake/cortex/skills/ts-convert-to-snowflake-sv

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-from-snowflake-sv \
      ~/.snowflake/cortex/skills/ts-convert-from-snowflake-sv

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-audit \
      ~/.snowflake/cortex/skills/ts-audit

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-dependency-manager \
      ~/.snowflake/cortex/skills/ts-dependency-manager

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-object-answer-promote \
      ~/.snowflake/cortex/skills/ts-object-answer-promote

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-object-model-coach \
      ~/.snowflake/cortex/skills/ts-object-model-coach

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-object-model-spotql-query \
      ~/.snowflake/cortex/skills/ts-object-model-spotql-query

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-variable-timezone \
      ~/.snowflake/cortex/skills/ts-variable-timezone

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-recipe-formula-business-days-snowflake \
      ~/.snowflake/cortex/skills/ts-recipe-formula-business-days-snowflake

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-recipe-formula-hms-display-snowflake \
      ~/.snowflake/cortex/skills/ts-recipe-formula-hms-display-snowflake

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-profile-databricks \
      ~/.snowflake/cortex/skills/ts-profile-databricks

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-to-databricks-mv \
      ~/.snowflake/cortex/skills/ts-convert-to-databricks-mv

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-from-databricks-mv \
      ~/.snowflake/cortex/skills/ts-convert-from-databricks-mv

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-from-tableau \
      ~/.snowflake/cortex/skills/ts-convert-from-tableau

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-profile-tableau \
      ~/.snowflake/cortex/skills/ts-profile-tableau

# Symlink shared reference files
ln -s ~/thoughtspot-agent-skills/agents/shared \
      ~/.snowflake/cortex/shared
```

### For Claude Code

```bash
mkdir -p ~/.claude/skills

# Symlink each skill
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-profile-thoughtspot \
      ~/.claude/skills/ts-profile-thoughtspot

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-to-snowflake-sv \
      ~/.claude/skills/ts-convert-to-snowflake-sv

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-from-snowflake-sv \
      ~/.claude/skills/ts-convert-from-snowflake-sv

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-audit \
      ~/.claude/skills/ts-audit

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-dependency-manager \
      ~/.claude/skills/ts-dependency-manager

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-object-answer-promote \
      ~/.claude/skills/ts-object-answer-promote

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-object-model-coach \
      ~/.claude/skills/ts-object-model-coach

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-object-model-spotql-query \
      ~/.claude/skills/ts-object-model-spotql-query

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-variable-timezone \
      ~/.claude/skills/ts-variable-timezone

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-recipe-formula-business-days-snowflake \
      ~/.claude/skills/ts-recipe-formula-business-days-snowflake

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-recipe-formula-hms-display-snowflake \
      ~/.claude/skills/ts-recipe-formula-hms-display-snowflake

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-profile-databricks \
      ~/.claude/skills/ts-profile-databricks

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-to-databricks-mv \
      ~/.claude/skills/ts-convert-to-databricks-mv

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-from-databricks-mv \
      ~/.claude/skills/ts-convert-from-databricks-mv

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-from-tableau \
      ~/.claude/skills/ts-convert-from-tableau

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-profile-tableau \
      ~/.claude/skills/ts-profile-tableau

# Claude-only: Snowflake profile management
ln -s ~/thoughtspot-agent-skills/agents/claude/ts-profile-snowflake \
      ~/.claude/skills/ts-profile-snowflake

# Symlink shared reference files
ln -s ~/thoughtspot-agent-skills/agents/shared \
      ~/.claude/shared

ln -s ~/thoughtspot-agent-skills/agents/shared/mappings \
      ~/.claude/mappings
```

---

## Step 4: Configure ThoughtSpot credentials

Run in your coding agent:

```
$ts-profile-thoughtspot
```

---

## Step 5: Verify

```
/skill
```

Skills should appear in the list.

---

## Keeping updated

```bash
cd ~/thoughtspot-agent-skills && git pull
```

Symlinks update automatically. If the `ts` CLI version changed:

```bash
pip install -e ~/thoughtspot-agent-skills/tools/ts-cli
```

---

## Notes

### ts-profile-snowflake (Claude Code only)

Claude Code users also install `ts-profile-snowflake` for managing Snowflake
connections locally. Cortex Code CLI users don't need this — Cortex Code manages
Snowflake connections natively via `cortex connections set`.

### No stored procedures needed

CLI skills call the ThoughtSpot API directly. You do NOT need `/ts-setup-sv`
or any stored procedures unless you also use Snowsight Workspaces.

---

## For contributors

### Install git hooks

The repo ships two git hooks. Install both after cloning:

```bash
cd ~/thoughtspot-agent-skills

# Blocks commits that fail static validation (secrets, references, versions, etc.)
ln -s ../../scripts/pre-commit.sh .git/hooks/pre-commit

# Blocks pushes where smoke tests fail against a live ThoughtSpot instance
ln -s ../../scripts/pre-push.sh .git/hooks/pre-push

chmod +x scripts/pre-commit.sh scripts/pre-push.sh
```

### Configure smoke test arguments

Some smoke tests require model names, connection names, or Snowflake profile details
that vary per machine. Copy the example config and fill in your values:

```bash
cp tools/smoke-tests/smoke-config.local.json.example \
   tools/smoke-tests/smoke-config.local.json
# Edit smoke-config.local.json with your values — it is gitignored
```

Skills with all required args configured will run automatically on push.
Skills missing config are skipped with a warning (they don't block the push).

---

## Troubleshooting

### `ts` CLI install fails on Python 3.14 (macOS)

**Symptom:** `pip install` or `pipx install` fails with:
```
ImportError: Symbol not found: _XML_SetAllocTrackerActivationThreshold
```

**Cause:** Python 3.14 from Homebrew is compiled against a newer `libexpat` than the
one shipped with macOS, causing a dynamic library mismatch. The `ts` CLI requires
Python 3.9–3.13.

**Fix:** Install and use Python 3.12 or 3.13:
```bash
brew install python@3.12
pip3.12 install -e ~/thoughtspot-agent-skills/tools/ts-cli
```

If `pipx` is your default install path, point it at a supported Python:
```bash
pipx install --python python3.12 -e ~/thoughtspot-agent-skills/tools/ts-cli
```

> Use `pip install -e` (not `pipx install -e`) — `pipx` is designed for standalone
> PyPI packages, not editable local installs.

### `ts: command not found` after install

The install succeeded but the `ts` command is not on your PATH. Check where pip
installed the script:

```bash
pip show -f thoughtspot-cli | grep "^Location"
```

Then verify the corresponding `bin/` directory is in your PATH, or use:

```bash
python -m ts_cli.cli --help
```
