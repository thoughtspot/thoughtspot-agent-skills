# ThoughtSpot Agent Skills

A collection of skills and tools for working with ThoughtSpot, packaged for
multiple runtimes: **Claude Code**, **Cortex Code CLI**, **Snowsight Workspaces**,
and **Databricks** (Genie Code).

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
- Python 3.9–3.13 (Python 3.14 has a macOS `libexpat` incompatibility — see [Troubleshooting](#troubleshooting))
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
│   ├── databricks/ — Databricks runtime (Genie Code, Asset Bundles)
│   └── shared/     — Shared reference files used by all runtimes
│       ├── mappings/ts-snowflake/       — Column, join, formula, and property mapping rules
│       ├── mappings/ts-databricks/      — ThoughtSpot ↔ Databricks Metric View mapping rules
│       ├── mappings/tableau/            — Tableau → ThoughtSpot formula and TML rules
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

**Conversion** — move semantic models between ThoughtSpot and external platforms

| Skill | What it does | Coverage |
|---|---|---|
| `ts-convert-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View (single, split by domain, or update existing) | — |
| `ts-convert-from-snowflake-sv` | Convert a Snowflake Semantic View into a ThoughtSpot Model (single, merge multiple, or update existing) | [coverage](agents/cli/ts-convert-from-snowflake-sv/references/coverage-matrix.md) |
| `ts-convert-to-databricks-mv` | Convert a ThoughtSpot model to a Databricks Metric View (v0.1 single-source or v1.1 multi-source) | — |
| `ts-convert-from-databricks-mv` | Convert a Databricks Metric View into a ThoughtSpot Model (dimensions → attributes, measures → measures/formulas) | — |
| `ts-convert-from-tableau` | Convert a Tableau workbook (.twb/.twbx) into ThoughtSpot table + model TMLs, with optional dashboard-to-liveboard migration | [coverage](agents/cli/ts-convert-from-tableau/references/coverage-matrix.md) |

**ThoughtSpot Objects** — author and manage ThoughtSpot Models

| Skill | What it does |
|---|---|
| `ts-object-answer-promote` | Promote formulas and parameters from a saved Answer into a Model |
| `ts-object-model-coach` | Prepare a Model for Spotter — review AI Context, synonyms, mine dependent objects, generate improvements |
| `ts-object-model-spotql-query` | Query a Model with SpotQL — write Semantic SQL, validate it to warehouse SQL, execute it, and review the data results |
| `ts-audit` | Scan an environment across five angles — AI Readiness, Data Modeling, Human Readiness, Performance, Security — with per-model scorecards and prioritised findings |
| `ts-dependency-manager` | Audit dependencies, safely remove or repoint columns across Models, Views, Answers, Liveboards |
| `ts-variable-timezone` | Search, set, or remove timezone values for the `ts_user_timezone` variable at org or user level ⚠️ Beta in 26.5, EA in 26.6 |

**Connection Profiles** — manage credentials and connections

| Skill | What it does |
|---|---|
| `ts-profile-thoughtspot` | Add, update, test, or delete ThoughtSpot profiles |
| `ts-profile-snowflake` | Add, update, test, or delete Snowflake profiles (**Claude Code only** — Cortex Code manages Snowflake connections natively) |
| `ts-profile-databricks` | Add, update, test, or delete Databricks profiles — Service Principal (OAuth M2M), PAT, or existing CLI profile |

**Recipes** — pre-built analytical capabilities for ThoughtSpot

| Skill | What it builds | Platform |
|---|---|---|
| `ts-recipe-formula-business-days-snowflake` | Business-day formula: deploy three Snowflake UDFs for weekday-only date arithmetic, then show ThoughtSpot formula syntax | Snowflake |
| `ts-recipe-formula-hms-display-snowflake` | Duration display formula: deploy four Snowflake UDFs to format integer seconds/minutes as `HH:MM:SS`, `DD:HH:MM:SS`, `HH:MM`, or `DD:HH:MM` strings | Snowflake |

See **[agents/cli/SETUP.md](agents/cli/SETUP.md)** for installation and setup.

---

## Snowsight Workspace Skills

Skills deployed in Snowsight Workspaces via a Snowflake internal stage. No local
install required — runs entirely within Snowflake using stored procedures.

| Skill | What it does |
|---|---|
| `ts-profile-thoughtspot` | Add, update, test, or delete ThoughtSpot profiles (uses Snowflake Secrets) |
| `ts-setup-sv` | Install or upgrade stored procedures required by the other skills |
| `ts-recipe-formula-business-days-snowflake` | Deploy three Snowflake scalar UDFs for weekday-only date arithmetic, then show ThoughtSpot formula syntax |
| `ts-recipe-formula-hms-display-snowflake` | Deploy four Snowflake scalar UDFs to format integer seconds/minutes as `HH:MM:SS`, `DD:HH:MM:SS`, `HH:MM`, or `DD:HH:MM` |
| `ts-convert-to-snowflake-sv` | Convert a ThoughtSpot model to a Snowflake Semantic View |
| `ts-convert-from-snowflake-sv` | Convert a Snowflake Semantic View into a ThoughtSpot Model |

See **[agents/coco-snowsight/SETUP.md](agents/coco-snowsight/SETUP.md)** for stage
setup and Workspace deployment.

---

## Databricks Skills (Genie Code)

Skills deployed to a Databricks workspace via Asset Bundles. Uses
`ThoughtSpotClient` — a single-file Python class with full ts-cli parity,
consumed via `%run` in Databricks notebooks.

| Skill | What it does |
|---|---|
| `ts-convert-to-databricks-mv` | Convert a ThoughtSpot model to a Databricks Metric View |
| `ts-convert-from-databricks-mv` | Convert a Databricks Metric View into a ThoughtSpot Model |

**Also included:**

| Notebook | Purpose |
|---|---|
| `ts_client.py` | ThoughtSpotClient — 22 methods, auth via Databricks Secrets, in-memory token caching |
| `ts_profile_setup.py` | Widget-driven profile creation (stores credentials in Databricks Secrets) |
| `token_refresh.py` | Scheduled job for credential rotation (12h cron) |

See **[agents/databricks/SETUP.md](agents/databricks/SETUP.md)** for deployment
with `databricks bundle deploy`.

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

If you installed via `pipx`, point it at a supported Python:
```bash
pipx install --python python3.12 -e ~/thoughtspot-agent-skills/tools/ts-cli
```

> Note: also use `pip install -e` (not `pipx install -e`) — `pipx` is designed for
> standalone PyPI packages, not editable local installs.
