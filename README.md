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
│       ├── mappings/ts-snowflake/       — Column, join, formula, and property mapping rules (Snowflake)
│       ├── mappings/ts-databricks/   — Column, join, formula, and property mapping rules (Databricks UC)
│       ├── schemas/                     — Platform schema references (ThoughtSpot TML, Snowflake SV, UC Metric View)
│       └── worked-examples/snowflake/   — End-to-end Snowflake conversion examples
├── scripts/        — Deployment helpers (pre-commit hook, deploy gate, stage sync)
└── tools/
    ├── ts-cli/     — ThoughtSpot CLI used by Claude Code skills at runtime
    ├── validate/   — Static structural validators for SV YAML and TML (run by pre-commit hook)
    └── smoke-tests/ — End-to-end smoke tests requiring live ThoughtSpot and Snowflake credentials
```

---

## Claude Code Skills

Skills invoked via slash commands in Claude Code. Requires Claude Code and Python.

**Conversion** — move semantic models between ThoughtSpot and data platforms

| Skill | Command | What it does |
|---|---|---|
| `ts-convert-to-snowflake-sv` | `/ts-convert-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View |
| `ts-convert-from-snowflake-sv` | `/ts-convert-from-snowflake-sv` | Reverse-engineer a Snowflake Semantic View into a ThoughtSpot Model |
| `ts-convert-to-databricks-mv` | `/ts-convert-to-databricks-mv` | Convert a ThoughtSpot model to a Databricks Unity Catalog Metric View |

**ThoughtSpot Objects** — author and manage ThoughtSpot Models

| Skill | Command | What it does |
|---|---|---|
| `ts-object-model-builder` | `/ts-object-model-builder` | Build a ThoughtSpot Model from a Snowflake schema or ERD diagram image |
| `ts-object-model-promote` | `/ts-object-model-promote` | Promote formulas and parameters from a saved Answer into a Model |

**Setup** — manage connection profiles and credentials

| Skill | Command | What it does |
|---|---|---|
| `ts-profile-thoughtspot` | `/ts-profile-thoughtspot` | Add, update, test, or delete ThoughtSpot profiles |
| `ts-profile-snowflake` | `/ts-profile-snowflake` | Add, update, test, or delete Snowflake profiles |
| `ts-profile-databricks` | `/ts-profile-databricks` | Add, update, test, or delete Databricks profiles (PAT auth, SQL warehouse) |

See **[agents/claude/SETUP.md](agents/claude/SETUP.md)** for installation, credential setup, and usage.

---

## Snowflake Cortex Skills (CoCo)

Skills deployed in Snowsight Workspaces via a Snowflake internal stage. No local
install required — runs entirely within Snowflake.

| Skill | What it does |
|---|---|
| `ts-profile-thoughtspot` | Add, update, test, or delete ThoughtSpot profiles |
| `ts-setup-sv` | Install or upgrade stored procedures required by the other skills |
| `ts-convert-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View |
| `ts-convert-from-snowflake-sv` | Reverse-engineer a Snowflake Semantic View into a ThoughtSpot Model |

See **[agents/coco/SETUP.md](agents/coco/SETUP.md)** for stage setup and Workspace deployment.

---

## ThoughtSpot CLI

A lightweight Python CLI used by the Claude Code skills at runtime to authenticate
with ThoughtSpot, search metadata, export/import TML, list connections, and create
logical table objects. Located in [`tools/ts-cli/`](tools/ts-cli/).

Commands: `ts auth`, `ts metadata search`, `ts tml export/import`, `ts connections list/get/add-tables`, `ts tables create`.
