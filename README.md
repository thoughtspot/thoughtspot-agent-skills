# ThoughtSpot Agent Skills

A collection of skills and tools for working with ThoughtSpot, packaged for
multiple runtimes: **Claude Code**, **Cortex Code CLI**, **Snowsight Workspaces**,
and **Cursor AI**.

---

## Prerequisites

You need one of the following coding agents installed:

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

**Also required:**
- Python 3.9+
- Git

---

## Quick Start (Claude Code or Cortex Code CLI)

```bash
# 1. Clone
git clone https://github.com/thoughtspot/thoughtspot-agent-skills.git ~/thoughtspot-agent-skills

# 2. Install the ts CLI
pip install -e ~/thoughtspot-agent-skills/tools/ts-cli

# 3. Symlink skills (choose your runtime)
```

**Cortex Code CLI:**
```bash
mkdir -p ~/.snowflake/cortex/skills
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-profile-thoughtspot ~/.snowflake/cortex/skills/ts-profile-thoughtspot
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-to-snowflake-sv ~/.snowflake/cortex/skills/ts-convert-to-snowflake-sv
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-from-snowflake-sv ~/.snowflake/cortex/skills/ts-convert-from-snowflake-sv
ln -s ~/thoughtspot-agent-skills/agents/shared ~/.snowflake/cortex/shared
```

**Claude Code:**
```bash
mkdir -p ~/.claude/skills
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-profile-thoughtspot ~/.claude/skills/ts-profile-thoughtspot
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-to-snowflake-sv ~/.claude/skills/ts-convert-to-snowflake-sv
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-convert-from-snowflake-sv ~/.claude/skills/ts-convert-from-snowflake-sv
ln -s ~/thoughtspot-agent-skills/agents/shared ~/.claude/shared
ln -s ~/thoughtspot-agent-skills/agents/shared/mappings ~/.claude/mappings
```

See **[agents/cli/SETUP.md](agents/cli/SETUP.md)** for the full setup (all skills,
credential configuration, and verification steps).

---

## Repository Structure

```
thoughtspot-agent-skills/
├── agents/
│   ├── cli/        — Canonical CLI skills (Claude Code + Cortex Code CLI)
│   ├── claude/     — Claude Code-only skills (ts-profile-snowflake)
│   ├── coco-snowsight/ — Snowsight Workspace skills (stored procedures)
│   ├── cursor/     — Cursor AI rules (.mdc format)
│   └── shared/     — Shared reference files used by all runtimes
│       ├── mappings/ts-snowflake/       — Column, join, formula, and property mapping rules
│       ├── schemas/                     — Platform schema references (ThoughtSpot TML, Snowflake SV)
│       └── worked-examples/snowflake/   — End-to-end conversion examples
├── scripts/        — Deployment helpers (pre-commit hook, deploy gate, stage sync)
└── tools/
    ├── ts-cli/     — ThoughtSpot CLI used by CLI skills at runtime
    ├── validate/   — Static validators (runtime coverage, consistency)
    └── smoke-tests/ — End-to-end smoke tests requiring live credentials
```

---

## CLI Skills (Claude Code & Cortex Code CLI)

These skills work in both **Claude Code** and **Cortex Code CLI**. They use the
`ts` CLI for ThoughtSpot API calls and store credentials in the OS credential store.

**Conversion** — move semantic models between ThoughtSpot and Snowflake

| Skill | What it does |
|---|---|
| `ts-convert-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View (single, split by domain, or update existing) |
| `ts-convert-from-snowflake-sv` | Convert a Snowflake Semantic View into a ThoughtSpot Model (single, merge multiple, or update existing) |

**ThoughtSpot Objects** — author and manage ThoughtSpot Models

| Skill | What it does |
|---|---|
| `ts-object-answer-promote` | Promote formulas and parameters from a saved Answer into a Model |
| `ts-object-model-coach` | Prepare a Model for Spotter — review AI Context, synonyms, mine dependent objects, generate improvements |
| `ts-dependency-manager` | Audit dependencies, safely remove or repoint columns across Models, Views, Answers, Liveboards |
| `ts-variable-timezone` | Search, set, or remove timezone values for the `ts_user_timezone` variable at org or user level ⚠️ Beta in 26.5, EA in 26.6 |

**Setup** — manage connection profiles

| Skill | What it does |
|---|---|
| `ts-profile-thoughtspot` | Add, update, test, or delete ThoughtSpot profiles |
| `ts-profile-snowflake` | Add, update, test, or delete Snowflake profiles (**Claude Code only** — Cortex Code manages Snowflake connections natively) |

See **[agents/cli/SETUP.md](agents/cli/SETUP.md)** for installation and setup.

### ts-variable-timezone version requirements

> ⚠️ **Beta in ThoughtSpot 26.5, Early Access in 26.6 — requires `tscli` flags to enable.**

| ThoughtSpot version | Status | Notes |
|---|---|---|
| 26.5 | Beta | Must be enabled by your ThoughtSpot admin via `tscli` |
| 26.6 | Early Access | Must be enabled by your ThoughtSpot admin via `tscli` |
| Post-GA | Generally Available | Enabled by default |

---

## Snowsight Workspace Skills

Skills deployed in Snowsight Workspaces via a Snowflake internal stage. No local
install required — runs entirely within Snowflake using stored procedures.

| Skill | What it does |
|---|---|
| `ts-profile-thoughtspot` | Add, update, test, or delete ThoughtSpot profiles (uses Snowflake Secrets) |
| `ts-setup-sv` | Install or upgrade stored procedures required by the other skills |
| `ts-convert-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View |
| `ts-convert-from-snowflake-sv` | Convert a Snowflake Semantic View into a ThoughtSpot Model |

See **[agents/coco-snowsight/SETUP.md](agents/coco-snowsight/SETUP.md)** for stage
setup and Workspace deployment.

---

## Cursor AI Rules

Rules installed into `.cursor/rules/` in your project directory. Triggered by natural
language in the Cursor AI chat.

| Rule | What it does |
|---|---|
| `ts-profile-thoughtspot` | Add, update, test, or delete ThoughtSpot profiles |
| `ts-profile-snowflake` | Add, update, test, or delete Snowflake profiles |
| `ts-convert-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View |
| `ts-convert-from-snowflake-sv` | Convert a Snowflake Semantic View into a ThoughtSpot Model |
| `ts-object-answer-promote` | Promote formulas from a saved Answer into a Model |
| `ts-object-model-coach` | Prepare a Model for Spotter — review AI Context, synonyms, mine dependent objects, generate improvements ⚠️ Untested in Cursor |
| `ts-dependency-manager` | Audit dependencies, safely remove or repoint columns across Models, Views, Answers, Liveboards ⚠️ Untested in Cursor |
| `ts-variable-timezone` | Search, set, or remove timezone values for the `ts_user_timezone` variable ⚠️ Beta in 26.5, EA in 26.6, Untested in Cursor |

See **[agents/cursor/SETUP.md](agents/cursor/SETUP.md)** for installation.

---

## ThoughtSpot CLI

A lightweight Python CLI used by CLI skills at runtime to authenticate with
ThoughtSpot, search metadata, export/import TML, list connections, and create
logical table objects. Located in [`tools/ts-cli/`](tools/ts-cli/).

```bash
pip install -e tools/ts-cli
ts --help
```

Commands: `ts auth`, `ts metadata search`, `ts tml export/import`,
`ts connections list/get/add-tables`, `ts tables create`, `ts profiles list`.
