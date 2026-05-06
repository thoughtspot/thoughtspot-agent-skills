# Claude Code — Setup

**Most skills now live in `agents/cli/`.** See **[agents/cli/SETUP.md](../cli/SETUP.md)**
for full installation instructions covering both Claude Code and Cortex Code CLI.

This directory contains only **`ts-profile-snowflake`** — a Claude Code-specific skill
for managing local Snowflake connection profiles. Cortex Code CLI users don't need this
(Cortex Code manages Snowflake connections natively via `cortex connections set`).

---

## Installing ts-profile-snowflake (Claude Code only)

After completing the main setup from `agents/cli/SETUP.md`, additionally symlink this skill:

```bash
ln -s ~/thoughtspot-agent-skills/agents/claude/ts-profile-snowflake \
      ~/.claude/skills/ts-profile-snowflake
```

Then run in Claude Code:

```
/ts-profile-snowflake
```

This will walk you through configuring a local Snowflake connection (Python connector
with key pair auth, or Snowflake CLI).

---

## Requirements

See `agents/cli/SETUP.md` for the full requirements list. Additionally for
`ts-profile-snowflake`:

```bash
# Required only if using the Python connector method (not needed for Snowflake CLI)
pip install snowflake-connector-python cryptography
```
