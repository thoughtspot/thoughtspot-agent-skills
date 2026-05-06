# Claude Code — Supplementary Skills

This directory contains Claude Code-specific skills that are NOT shared with
Cortex Code CLI.

**All shared skills now live in `agents/cli/`.** See `agents/cli/SETUP.md` for
installation instructions.

## What lives here

| Skill | Purpose |
|---|---|
| `ts-profile-snowflake` | Manage local Snowflake connection profiles. Not needed for Cortex Code CLI (which manages connections natively via `cortex connections set`). |

## Reference paths

Skills here use `~/.claude/` paths (Claude Code convention):
- `~/.claude/shared/schemas/...`
- `~/.claude/skills/<skill>/SKILL.md`

## Adding a skill here

Only add a skill to `agents/claude/` if it is genuinely Claude Code-specific
(i.e. it cannot work in Cortex Code CLI). Otherwise add it to `agents/cli/`.
