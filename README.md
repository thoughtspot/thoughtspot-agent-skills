# ThoughtSpot Skills

A collection of skills and tools for working with ThoughtSpot, packaged for two
runtimes: **Claude Code** and **Snowflake Cortex (CoCo)**.

---

## Repository Structure

```
thoughtspot-skills/
├── agents/
│   ├── claude/     — Claude Code skills (invoked via slash commands in Claude Code)
│   ├── coco/       — Snowflake Cortex skills (deployed in Snowsight Workspaces)
│   └── shared/     — Shared reference files used by both claude and coco skills
│       ├── mappings/ts-snowflake/ — Column, join, formula, and property mapping rules
│       ├── schemas/               — Platform schema references (ThoughtSpot TML, Snowflake Semantic View)
│       └── worked-examples/snowflake/ — End-to-end conversion examples
└── tools/
    └── ts-cli/     — ThoughtSpot CLI used by Claude Code skills at runtime
```

---

## Claude Code Skills

Skills invoked via slash commands in Claude Code. Requires Claude Code and Python.

| Skill | Command | What it does |
|---|---|---|
| `ts-profile-setup` | `/ts-profile-setup` | Add, update, test, or delete ThoughtSpot profiles |
| `snowflake-profile-setup` | `/snowflake-profile-setup` | Add, update, test, or delete Snowflake profiles |
| `ts-model-builder` | `/ts-model-builder` | Build a ThoughtSpot Model from a Snowflake schema or ERD diagram image |
| `ts-to-snowflake-sv` | `/ts-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View |
| `ts-from-snowflake-sv` | `/ts-from-snowflake-sv` | Reverse-engineer a Snowflake Semantic View into a ThoughtSpot Model |

See **[agents/claude/SETUP.md](agents/claude/SETUP.md)** for installation, credential setup, and usage.

---

## Snowflake Cortex Skills (CoCo)

Skills deployed in Snowsight Workspaces via a Snowflake internal stage. No local
install required — runs entirely within Snowflake.

| Skill | What it does |
|---|---|
| `ts-profile-setup` | Add, update, test, or delete ThoughtSpot profiles |
| `ts-sv-setup` | Install or upgrade stored procedures required by the other skills |
| `ts-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View |
| `ts-from-snowflake-sv` | Reverse-engineer a Snowflake Semantic View into a ThoughtSpot Model |

See **[agents/coco/SETUP.md](agents/coco/SETUP.md)** for stage setup and Workspace deployment.

---

## ThoughtSpot CLI

A lightweight Python CLI used by the Claude Code skills at runtime to authenticate
with ThoughtSpot, search metadata, export/import TML, list connections, and create
logical table objects. Located in [`tools/ts-cli/`](tools/ts-cli/).

Commands: `ts auth`, `ts metadata search`, `ts tml export/import`, `ts connections list/get/add-tables`, `ts tables create`.
