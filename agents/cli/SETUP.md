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

- Python 3.9+
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

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-dependency-manager \
      ~/.snowflake/cortex/skills/ts-dependency-manager

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-object-answer-promote \
      ~/.snowflake/cortex/skills/ts-object-answer-promote

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-object-model-coach \
      ~/.snowflake/cortex/skills/ts-object-model-coach

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

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-dependency-manager \
      ~/.claude/skills/ts-dependency-manager

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-object-answer-promote \
      ~/.claude/skills/ts-object-answer-promote

ln -s ~/thoughtspot-agent-skills/agents/cli/ts-object-model-coach \
      ~/.claude/skills/ts-object-model-coach

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
