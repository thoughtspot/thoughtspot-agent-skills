# ThoughtSpot Agent Skills

A collection of skills and tools for working with ThoughtSpot, packaged for three
runtimes: **Claude Code**, **Snowflake Cortex (CoCo)**, and **Cursor AI**.

---

## Repository Structure

```
thoughtspot-agent-skills/
├── agents/
│   ├── claude/     — Claude Code skills (invoked via slash commands in Claude Code)
│   ├── coco/       — Snowflake Cortex skills (deployed in Snowsight Workspaces)
│   ├── cursor/     — Cursor AI rules (installed via symlinks into .cursor/rules/)
│   └── shared/     — Shared reference files used by all runtimes
│       ├── mappings/ts-snowflake/       — Column, join, formula, and property mapping rules (Snowflake)
│       ├── schemas/                     — Platform schema references (ThoughtSpot TML, Snowflake SV)
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
| `ts-convert-to-snowflake-sv` | `/ts-convert-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View; auto-detects multi-fact domains and offers to split into one view per domain |
| `ts-convert-from-snowflake-sv` | `/ts-convert-from-snowflake-sv` | Reverse-engineer a Snowflake Semantic View into a ThoughtSpot Model; supports merging multiple Semantic Views into one model |

**ThoughtSpot Objects** — author and manage ThoughtSpot Models

| Skill | Command | What it does |
|---|---|---|
| `ts-object-answer-promote` | `/ts-object-answer-promote` | Promote formulas and parameters from a saved Answer into a Model |
| `ts-coach-model` | `/ts-coach-model` | Comprehensively prepare a Model for Spotter — review existing AI Context / synonyms / description, mine dependent Liveboards/Answers and (optionally) Snowflake query history, then generate Column AI Context, Synonyms, Reference Questions, Business Terms, and a Data Model Instructions draft |
| `ts-dependency-manager` (WIP) | `/ts-dependency-manager` | Audit dependencies, then safely remove or repoint columns across Models, Views, Answers, Liveboards, and Sets — with TML backup, post-import verification, and rollback |

**Setup** — manage connection profiles and credentials

| Skill | Command | What it does |
|---|---|---|
| `ts-profile-thoughtspot` | `/ts-profile-thoughtspot` | Add, update, test, or delete ThoughtSpot profiles |
| `ts-profile-snowflake` | `/ts-profile-snowflake` | Add, update, test, or delete Snowflake profiles |

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

## Cursor AI Rules

Rules installed into `.cursor/rules/` in your project directory. Triggered by natural language
in the Cursor AI chat — no slash commands required.

| Rule | Trigger phrase | What it does |
|---|---|---|
| `ts-profile-thoughtspot` | "Set up my ThoughtSpot profile" | Add, update, test, or delete ThoughtSpot profiles |
| `ts-profile-snowflake` | "Set up my Snowflake profile" | Add, update, test, or delete Snowflake profiles |
| `ts-convert-to-snowflake-sv` | "Convert my ThoughtSpot model to a Snowflake Semantic View" | Convert a ThoughtSpot model to a Snowflake Semantic View |
| `ts-convert-from-snowflake-sv` | "Convert my Snowflake Semantic View to a ThoughtSpot model" | Reverse-engineer a Snowflake Semantic View into a ThoughtSpot Model |
| `ts-object-answer-promote` | "Promote formulas from this Answer to the Model" | Promote formulas and parameters from a saved Answer into a Model |

See **[agents/cursor/SETUP.md](agents/cursor/SETUP.md)** for installation and credential setup.

---

## ThoughtSpot CLI

A lightweight Python CLI used by the Claude Code skills at runtime to authenticate
with ThoughtSpot, search metadata, export/import TML, list connections, and create
logical table objects. Located in [`tools/ts-cli/`](tools/ts-cli/).

Commands: `ts auth`, `ts metadata search`, `ts tml export/import`, `ts connections list/get/add-tables`, `ts tables create`.
