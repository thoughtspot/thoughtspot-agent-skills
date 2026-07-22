# ThoughtSpot Agent Skills

A collection of skills and tools for working with ThoughtSpot, packaged for
multiple runtimes: **Claude Code**, **Cortex Code CLI**, **Snowsight Workspaces**,
and **Databricks** (Genie Code).

---

## Skills

Skills are grouped by category. The runtime columns show where each skill is
available — each ✓ links to the SKILL.md for that runtime.

### Conversion

Move semantic models between ThoughtSpot and external platforms.

| Skill | What it does | Coverage | CLI | Snowsight | DBX |
|---|---|---|:-:|:-:|:-:|
| [`ts-convert-to-snowflake-sv`](agents/cli/ts-convert-to-snowflake-sv/SKILL.md) | Convert a ThoughtSpot model to a Snowflake Semantic View (single, split by domain, or update existing) | — | [✓](agents/cli/ts-convert-to-snowflake-sv/SKILL.md) | [✓](agents/coco-snowsight/ts-convert-to-snowflake-sv/SKILL.md) | — |
| [`ts-convert-from-snowflake-sv`](agents/cli/ts-convert-from-snowflake-sv/SKILL.md) | Convert a Snowflake Semantic View into a ThoughtSpot Model (single, merge multiple, or update existing) | [coverage](agents/cli/ts-convert-from-snowflake-sv/references/coverage-matrix.md) | [✓](agents/cli/ts-convert-from-snowflake-sv/SKILL.md) | [✓](agents/coco-snowsight/ts-convert-from-snowflake-sv/SKILL.md) | — |
| [`ts-convert-to-databricks-mv`](agents/cli/ts-convert-to-databricks-mv/SKILL.md) | Convert a ThoughtSpot model to a Databricks Metric View (v0.1 single-source or v1.1 multi-source) | — | [✓](agents/cli/ts-convert-to-databricks-mv/SKILL.md) | — | [✓](agents/databricks/skills/ts-convert-to-databricks-mv/SKILL.md) |
| [`ts-convert-from-databricks-mv`](agents/cli/ts-convert-from-databricks-mv/SKILL.md) | Convert a Databricks Metric View into a ThoughtSpot Model (dimensions → attributes, measures → measures/formulas) | [coverage](agents/cli/ts-convert-from-databricks-mv/references/coverage-matrix.md) | [✓](agents/cli/ts-convert-from-databricks-mv/SKILL.md) | — | [✓](agents/databricks/skills/ts-convert-from-databricks-mv/SKILL.md) |
| [`ts-convert-from-tableau`](agents/cli/ts-convert-from-tableau/SKILL.md) | Convert a Tableau workbook (.twb/.twbx) into ThoughtSpot table + model TMLs, with optional dashboard-to-liveboard migration | [coverage](agents/cli/ts-convert-from-tableau/references/coverage-matrix.md) | [✓](agents/cli/ts-convert-from-tableau/SKILL.md) | — | — |
| [`ts-convert-from-looker`](agents/cli/ts-convert-from-looker/SKILL.md) | Convert a Looker LookML project (model + view files) into ThoughtSpot Table and Model TMLs, with optional dashboard-to-liveboard migration | [coverage](agents/cli/ts-convert-from-looker/references/coverage-matrix.md) | [✓](agents/cli/ts-convert-from-looker/SKILL.md) | — | — |
| [`ts-convert-from-qlik`](agents/cli/ts-convert-from-qlik/SKILL.md) | Convert a Qlik Sense app (offline .qvf or Qlik Engine artifacts) into ThoughtSpot Table + Model TML and a tabbed Liveboard, flagging Set Analysis / variables for review | [coverage](agents/cli/ts-convert-from-qlik/references/coverage-matrix.md) | [✓](agents/cli/ts-convert-from-qlik/SKILL.md) | — | — |

### ThoughtSpot Objects

Author, manage, and assess ThoughtSpot Models and environments.

| Skill | What it does | CLI | Snowsight | DBX |
|---|---|:-:|:-:|:-:|
| [`ts-object-answer-promote`](agents/cli/ts-object-answer-promote/SKILL.md) | Promote formulas and parameters from a saved Answer into a Model | [✓](agents/cli/ts-object-answer-promote/SKILL.md) | — | — |
| [`ts-object-model-aggregates`](agents/cli/ts-object-model-aggregates/SKILL.md) | Audit a Model's Liveboards/Answers to recommend, generate, and wire aggregate Models (26.6 aggregate-aware routing) — signature mining, cost-based candidate ranking, gated DDL/TML generation ⚠️ pre-merge, open items unverified | [✓](agents/cli/ts-object-model-aggregates/SKILL.md) | — | — |
| [`ts-object-model-coach`](agents/cli/ts-object-model-coach/SKILL.md) | Prepare a Model for Spotter — review AI Context, synonyms, mine dependent objects, generate improvements | [✓](agents/cli/ts-object-model-coach/SKILL.md) | — | — |
| [`ts-object-model-erd`](agents/cli/ts-object-model-erd/SKILL.md) | Render a Model into a self-contained HTML ERD — tables, joins, columns, RLS, findings — shareable without ThoughtSpot login | [✓](agents/cli/ts-object-model-erd/SKILL.md) | — | — |
| [`ts-object-model-spotql-query`](agents/cli/ts-object-model-spotql-query/SKILL.md) | Query a Model with SpotQL — write Semantic SQL, validate to warehouse SQL, execute, and review results. New to SpotQL? Start with [**Why SpotQL**](agents/cli/ts-object-model-spotql-query/references/architecture.md). | [✓](agents/cli/ts-object-model-spotql-query/SKILL.md) | — | — |
| [`ts-audit`](agents/cli/ts-audit/SKILL.md) | Scan an environment across five angles — AI Readiness, Data Modeling, Human Readiness, Performance, Security — with per-model scorecards and prioritised findings | [✓](agents/cli/ts-audit/SKILL.md) | — | — |
| [`ts-dependency-manager`](agents/cli/ts-dependency-manager/SKILL.md) | Audit dependencies, safely remove or repoint columns across Models, Views, Answers, Liveboards | [✓](agents/cli/ts-dependency-manager/SKILL.md) | — | — |
| [`ts-variable-timezone`](agents/cli/ts-variable-timezone/SKILL.md) | Search, set, or remove timezone values for the `ts_user_timezone` variable at org or user level ⚠️ Beta in 26.5, EA in 26.6 | [✓](agents/cli/ts-variable-timezone/SKILL.md) | — | — |

### Data Loading

| Skill | What it does | CLI | Snowsight | DBX |
|---|---|:-:|:-:|:-:|
| [`ts-load-source-data`](agents/cli/ts-load-source-data/SKILL.md) | Load CSV data into Snowflake (or generate synthetic data from schema definitions) for ThoughtSpot to connect to | [✓](agents/cli/ts-load-source-data/SKILL.md) | — | — |

### Connection Profiles

| Skill | What it does | CLI | Snowsight | DBX |
|---|---|:-:|:-:|:-:|
| [`ts-profile-thoughtspot`](agents/cli/ts-profile-thoughtspot/SKILL.md) | Add, update, test, or delete ThoughtSpot profiles | [✓](agents/cli/ts-profile-thoughtspot/SKILL.md) | [✓](agents/coco-snowsight/ts-profile-thoughtspot/SKILL.md) | — |
| [`ts-profile-snowflake`](agents/claude/ts-profile-snowflake/SKILL.md) | Add, update, test, or delete Snowflake profiles (Claude Code only — Cortex Code manages connections natively) | [✓](agents/claude/ts-profile-snowflake/SKILL.md) | — | — |
| [`ts-profile-databricks`](agents/cli/ts-profile-databricks/SKILL.md) | Add, update, test, or delete Databricks profiles — Service Principal (OAuth M2M), PAT, or existing CLI profile | [✓](agents/cli/ts-profile-databricks/SKILL.md) | — | — |
| [`ts-profile-tableau`](agents/cli/ts-profile-tableau/SKILL.md) | Add, update, test, or delete Tableau Server/Cloud profiles — password or PAT auth | [✓](agents/cli/ts-profile-tableau/SKILL.md) | — | — |

### Recipes

Pre-built analytical capabilities for ThoughtSpot.

| Skill | What it builds | CLI | Snowsight | DBX |
|---|---|:-:|:-:|:-:|
| [`ts-recipe-formula-business-days-snowflake`](agents/cli/ts-recipe-formula-business-days-snowflake/SKILL.md) | Business-day formula: deploy three Snowflake UDFs for weekday-only date arithmetic, then show ThoughtSpot formula syntax | [✓](agents/cli/ts-recipe-formula-business-days-snowflake/SKILL.md) | [✓](agents/coco-snowsight/ts-recipe-formula-business-days-snowflake/SKILL.md) | — |
| [`ts-recipe-formula-hms-display-snowflake`](agents/cli/ts-recipe-formula-hms-display-snowflake/SKILL.md) | Duration display formula: deploy four Snowflake UDFs to format integer seconds/minutes as `HH:MM:SS`, `DD:HH:MM:SS`, `HH:MM`, or `DD:HH:MM` strings | [✓](agents/cli/ts-recipe-formula-hms-display-snowflake/SKILL.md) | [✓](agents/coco-snowsight/ts-recipe-formula-hms-display-snowflake/SKILL.md) | — |

### Setup & Infrastructure

| Skill | What it does | CLI | Snowsight | DBX |
|---|---|:-:|:-:|:-:|
| [`ts-setup-sv`](agents/coco-snowsight/ts-setup-sv/SKILL.md) | Install or upgrade stored procedures required by Snowsight skills | — | [✓](agents/coco-snowsight/ts-setup-sv/SKILL.md) | — |

---

## Getting Started

### 1. Pick your runtime

| Runtime | Best for | Setup guide |
|---|---|---|
| **CLI** — Claude Code + Cortex Code CLI | Full skill catalog, local development, interactive use | [agents/cli/SETUP.md](agents/cli/SETUP.md) |
| **Snowsight** — Snowflake Workspaces | Snowflake-native users, no local install needed | [agents/coco-snowsight/SETUP.md](agents/coco-snowsight/SETUP.md) |
| **Databricks** — Genie Code | Databricks-native users, Asset Bundle deployment | [agents/databricks/SETUP.md](agents/databricks/SETUP.md) |

Each setup guide covers prerequisites, installation, credential configuration, and
verification steps for that runtime.

### 2. CLI quick start

Most users start here. Snowsight and Databricks users — follow the setup guide for
your runtime instead.

```bash
# Clone
git clone https://github.com/thoughtspot/thoughtspot-agent-skills.git ~/thoughtspot-agent-skills

# Install the ts CLI (requires Python 3.9–3.13)
pip install -e ~/thoughtspot-agent-skills/tools/ts-cli

# Symlink skills — see agents/cli/SETUP.md for the full list
```

**Cortex Code CLI:**
```bash
mkdir -p ~/.snowflake/cortex/skills
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-profile-thoughtspot ~/.snowflake/cortex/skills/ts-profile-thoughtspot
ln -s ~/thoughtspot-agent-skills/agents/shared ~/.snowflake/cortex/shared
```

**Claude Code:**
```bash
mkdir -p ~/.claude/skills
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-profile-thoughtspot ~/.claude/skills/ts-profile-thoughtspot
ln -s ~/thoughtspot-agent-skills/agents/shared ~/.claude/shared
ln -s ~/thoughtspot-agent-skills/agents/shared/mappings ~/.claude/mappings
```

Then symlink each skill you want from the [skills catalog](#skills) above. The full
symlink list is in [agents/cli/SETUP.md](agents/cli/SETUP.md).

### 3. ThoughtSpot CLI (`ts`)

A lightweight Python CLI used by CLI skills at runtime to authenticate with
ThoughtSpot, search metadata, export/import TML, list connections, and create
logical table objects. Located in [`tools/ts-cli/`](tools/ts-cli/).

```bash
ts --help
```

Commands: `ts auth`, `ts metadata search`, `ts tml export/import`,
`ts connections list/get/add-tables`, `ts tables create`, `ts profiles list`.

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
│       ├── mappings/looker/             — LookML → ThoughtSpot formula and TML rules
│       ├── schemas/                     — Platform schema references (ThoughtSpot TML, Snowflake SV)
│       └── worked-examples/snowflake/   — End-to-end conversion examples
├── scripts/        — Deployment helpers (pre-commit hook, deploy gate, stage sync)
└── tools/
    ├── ts-cli/     — ThoughtSpot CLI used by CLI skills at runtime
    ├── validate/   — Static validators (runtime coverage, consistency)
    └── smoke-tests/ — End-to-end smoke tests requiring live credentials
```

---

## Contributing

| Resource | What it covers |
|---|---|
| [Quality gates catalog](docs/quality-gates.md) | All 37 validators — what each checks, when it runs, why it exists |
| [Open items index](docs/open-items-index.md) | Cross-skill tracker of unverified assumptions and pending tests |
| [Parity matrix](agents/PARITY.md) | Skill coverage across runtimes (CLI / CoCo / Databricks) |
| [Backlog](docs/backlog.md) | Dated work items (`BL-NNN`) from audits and reviews |
| [CLAUDE.md](CLAUDE.md) | Repo conventions, change-impact map, commit protocol |

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
