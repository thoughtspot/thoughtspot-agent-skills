# ThoughtSpot Skills

A collection of skills and tools for working with ThoughtSpot, packaged for two
runtimes: **Claude Code** and **Snowflake Cortex (CoCo)**.

---

## Repository Structure

```
thoughtspot-skills/
├── claude/     — Claude Code skills (invoked via slash commands in Claude Code)
├── coco/       — Snowflake Cortex skills (deployed in Snowsight Workspaces)
└── cli/        — ThoughtSpot CLI used by Claude Code skills at runtime
```

---

## Claude Code Skills

Skills invoked via slash commands in Claude Code. Requires Claude Code and Python.

| Skill | Command | What it does |
|---|---|---|
| `thoughtspot-setup` | `/thoughtspot-setup` | Add, update, test, or delete ThoughtSpot profiles |
| `snowflake-setup` | `/snowflake-setup` | Add, update, test, or delete Snowflake profiles |
| `thoughtspot-model-builder` | `/thoughtspot-model-builder` | Build a ThoughtSpot Model from a Snowflake schema or ERD image |
| `thoughtspot-snowflake-semantic-view` | `/thoughtspot-snowflake-semantic-view` | Convert a ThoughtSpot model to a Snowflake Semantic View |

See **[claude/SETUP.md](claude/SETUP.md)** for installation, credential setup, and usage.

---

## Snowflake Cortex Skills (CoCo)

Skills deployed in Snowsight Workspaces via a connected Git repository. No local
install required — runs entirely within Snowflake.

| Skill | What it does |
|---|---|
| `thoughtspot-snowflake-semantic-view` | Convert a ThoughtSpot model to a Snowflake Semantic View |

See **[coco/SETUP.md](coco/SETUP.md)** for Git repository setup and Workspace deployment.

---

## ThoughtSpot CLI

A lightweight Python CLI used by the Claude Code skills at runtime to authenticate
with ThoughtSpot, search metadata, and export TML. Located in [`cli/`](cli/).
