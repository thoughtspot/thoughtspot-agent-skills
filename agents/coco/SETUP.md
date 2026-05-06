# Setup Guide — ThoughtSpot ↔ Snowflake Skills

These skills run in two environments. **The Cortex Code CLI is the recommended
setup** — it's simpler, faster, and requires no Snowflake-side infrastructure
(no stored procedures, stages, or external access integrations).

| | Cortex Code CLI (recommended) | Snowsight Workspace |
|---|---|---|
| Shell / Python | Full access | Not available |
| ThoughtSpot API | Via `ts` CLI (direct) | Via stored procedures |
| Skill discovery | `.cortex/skills/` (project) or `~/.snowflake/cortex/skills/` (global) | `.snowflake/cortex/skills/` in workspace |
| Shared references | Relative path from skill directory | `.snowflake/cortex/shared/` in workspace |
| Deployment | Local filesystem (symlink or copy) | Stage → workspace copy |
| Stage sync needed | No (files are local) | Yes — after every change |
| Update method | `git pull` | Re-deploy from stage |

Choose the section that matches your environment:

- [Cortex Code CLI Setup](#cortex-code-cli-setup-recommended) — **recommended** — running Cortex Code from your terminal
- [Snowsight Workspace Setup](#snowsight-workspace-setup) — running CoCo inside the Snowflake UI (no local tooling required)

---

## Cortex Code CLI Setup (Recommended)

Install skills on your local machine so Cortex Code discovers them automatically.
In this environment you have full shell access, so skills use the `ts` CLI for
ThoughtSpot API calls instead of stored procedures.

### Prerequisites

- Python 3.9+
- Snowflake CLI (`snow`) — for Semantic View DDL operations
- Git (to clone or update the repo)

### Step 1: Clone the repository

```bash
git clone https://github.com/thoughtspot/thoughtspot-agent-skills.git ~/Dev/thoughtspot-agent-skills
```

### Step 2: Install the `ts` CLI

The `ts` CLI is a Python package that wraps the ThoughtSpot REST API:

```bash
pip install -e ~/Dev/thoughtspot-agent-skills/tools/ts-cli
```

Verify it installed:

```bash
ts --help
```

### Step 3: Install skills into Cortex Code

Cortex Code discovers skills from two locations:

- **Global** (`~/.snowflake/cortex/skills/`) — loaded in every Cortex Code session,
  regardless of which directory you start from
- **Project-level** (`.cortex/skills/` in a directory) — only loaded when you start
  Cortex Code from that directory or a subdirectory of it

Choose the approach that fits your use case:

#### Option A: Global symlinks (for skill developers)

Best for developers contributing to the skills repo. Symlinks mean edits to the
repo take effect immediately across all Cortex Code sessions — just `git pull` and
you're up to date.

```bash
# Create the skills directory if it doesn't exist
mkdir -p ~/.snowflake/cortex/skills

# Symlink each skill
ln -s ~/Dev/thoughtspot-agent-skills/agents/coco/ts-setup-sv \
      ~/.snowflake/cortex/skills/ts-setup-sv

ln -s ~/Dev/thoughtspot-agent-skills/agents/coco/ts-profile-thoughtspot \
      ~/.snowflake/cortex/skills/ts-profile-thoughtspot

ln -s ~/Dev/thoughtspot-agent-skills/agents/coco/ts-convert-to-snowflake-sv \
      ~/.snowflake/cortex/skills/ts-convert-to-snowflake-sv

ln -s ~/Dev/thoughtspot-agent-skills/agents/coco/ts-convert-from-snowflake-sv \
      ~/.snowflake/cortex/skills/ts-convert-from-snowflake-sv

# Symlink shared reference files
ln -s ~/Dev/thoughtspot-agent-skills/agents/shared \
      ~/.snowflake/cortex/shared
```

#### Option B: Global copy (for end users)

Best for users who just want to run the skills without keeping the repo cloned.
To update later, re-run these commands after downloading the latest files.

```bash
mkdir -p ~/.snowflake/cortex/skills

cp -r ~/Dev/thoughtspot-agent-skills/agents/coco/ts-setup-sv ~/.snowflake/cortex/skills/
cp -r ~/Dev/thoughtspot-agent-skills/agents/coco/ts-profile-thoughtspot ~/.snowflake/cortex/skills/
cp -r ~/Dev/thoughtspot-agent-skills/agents/coco/ts-convert-to-snowflake-sv ~/.snowflake/cortex/skills/
cp -r ~/Dev/thoughtspot-agent-skills/agents/coco/ts-convert-from-snowflake-sv ~/.snowflake/cortex/skills/

cp -r ~/Dev/thoughtspot-agent-skills/agents/shared ~/.snowflake/cortex/shared
```

#### Option C: Project-level (scoped to one project)

Best for bundling skills with a specific project so they're only available in that
context. Useful when you want teammates to get the skills automatically when they
clone a project, or when you don't want these skills appearing in unrelated sessions.

**How it works:** Cortex Code checks for a `.cortex/skills/` directory in the current
working directory when it starts. Skills found there are loaded alongside any global
skills. If you `cd` to a different project and start Cortex Code, these skills won't
be visible.

```bash
# From your project root (e.g. ~/Dev/my-analytics-project)
mkdir -p .cortex/skills

ln -s ~/Dev/thoughtspot-agent-skills/agents/coco/ts-setup-sv .cortex/skills/ts-setup-sv
ln -s ~/Dev/thoughtspot-agent-skills/agents/coco/ts-profile-thoughtspot .cortex/skills/ts-profile-thoughtspot
ln -s ~/Dev/thoughtspot-agent-skills/agents/coco/ts-convert-to-snowflake-sv .cortex/skills/ts-convert-to-snowflake-sv
ln -s ~/Dev/thoughtspot-agent-skills/agents/coco/ts-convert-from-snowflake-sv .cortex/skills/ts-convert-from-snowflake-sv

ln -s ~/Dev/thoughtspot-agent-skills/agents/shared .cortex/shared
```

> **Tip:** You can commit the `.cortex/` directory to your project repo (with
> relative symlinks or copied files) so other team members get the skills on clone.

### Step 4: Configure ThoughtSpot credentials

In Cortex Code, run:

```
$ts-profile-thoughtspot
```

This will walk you through registering your ThoughtSpot instance (URL, username,
auth method). Credentials are stored in your OS credential store (macOS Keychain,
Windows Credential Manager, or Linux Secret Service).

### Step 5: Verify

Confirm Cortex Code sees the skills:

```
/skill
```

The skills should appear in the list. You can invoke them with:

```
$ts-convert-to-snowflake-sv
$ts-convert-from-snowflake-sv
$ts-profile-thoughtspot
```

### Keeping CLI updated

```bash
cd ~/Dev/thoughtspot-agent-skills && git pull
```

If you used symlinks, changes take effect immediately. If you copied files, re-run
the copy commands from Step 3.

If the `ts` CLI was updated (check `tools/ts-cli/pyproject.toml` version), re-install:

```bash
pip install -e ~/Dev/thoughtspot-agent-skills/tools/ts-cli
```

---

## Snowsight Workspace Setup

Use this path if you work entirely within the Snowflake UI and don't have (or don't
want) local CLI tooling. Skills are deployed to a Snowsight Workspace via a Snowflake
stage and use stored procedures to call the ThoughtSpot API.

### Prerequisites

- Snowflake CLI (`snow`) installed and configured with your account (for the initial stage push)
- A Snowflake internal stage for the skill files (default: `SKILLS.PUBLIC.SHARED`)

**Using a different stage?**
The scripts default to `@SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex`. To use a
different stage, set the `SNOW_STAGE` environment variable before running:

```bash
export SNOW_STAGE="@MY_DB.MY_SCHEMA.MY_STAGE/skills/.snowflake/cortex"
./scripts/stage-sync.sh
```

The manual `snow stage copy` commands below use `@SKILLS.PUBLIC.SHARED` — substitute
your stage path if you're running them directly.

### Option A: Stage-based (recommended for Snowsight)

#### Step 1: Push files to the stage

Run from the repository root after any update:

```bash
# Skill files
snow stage copy agents/coco/SETUP.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ --overwrite
snow stage copy agents/coco/ts-setup-sv/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-setup-sv/ --overwrite
snow stage copy agents/coco/ts-profile-thoughtspot/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-profile-thoughtspot/ --overwrite
snow stage copy agents/coco/ts-convert-to-snowflake-sv/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-convert-to-snowflake-sv/ --overwrite
snow stage copy agents/coco/ts-convert-from-snowflake-sv/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-convert-from-snowflake-sv/ --overwrite

# Shared reference files (only needed when these change)
snow stage copy agents/shared/mappings/ts-snowflake/ts-from-snowflake-rules.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-snowflake/ --overwrite
snow stage copy agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-snowflake/ --overwrite
snow stage copy agents/shared/mappings/ts-snowflake/ts-snowflake-properties.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-snowflake/ --overwrite
snow stage copy agents/shared/mappings/ts-snowflake/ts-to-snowflake-rules.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-snowflake/ --overwrite
snow stage copy agents/shared/schemas/snowflake-schema.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-connection.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-table-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-formula-patterns.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-model-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-answer-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-liveboard-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-sets-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-view-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-alert-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-feedback-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/worked-examples/snowflake/ts-from-snowflake.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/snowflake/ --overwrite
snow stage copy agents/shared/worked-examples/snowflake/ts-from-snowflake-dunder.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/snowflake/ --overwrite
snow stage copy agents/shared/worked-examples/snowflake/ts-to-snowflake.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/snowflake/ --overwrite
```

Or use the sync script (only uploads changed files):

```bash
./scripts/stage-sync.sh          # changed files only
./scripts/stage-sync.sh --all    # force full upload
```

#### Step 2: Ask CoCo to deploy to Workspace

In your Snowsight Workspace, ask:

> "Deploy skill files from @SKILLS.PUBLIC.SHARED to this workspace"

CoCo reads each file from the stage and writes it to the corresponding workspace path.

**Stage → Workspace path mapping:**

| Stage path | Workspace path |
|---|---|
| `@SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/<name>/SKILL.md` | `.snowflake/cortex/skills/<name>/SKILL.md` |
| `@SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/` | `.snowflake/cortex/shared/` |

#### Step 3: Install stored procedures

After files are deployed, run in the Workspace:

> /ts-setup-sv

This creates the stored procedures (`TS_SEARCH_MODELS`, `TS_EXPORT_TML`, `TS_IMPORT_TML`,
`TS_LIST_CONNECTIONS`), the `THOUGHTSPOT_PROFILES` table, secrets, and external access
integrations needed for the skills to call the ThoughtSpot API from within Snowflake.

### Option B: Manual upload (no tooling required)

Paste file contents directly into the Workspace. Suitable for first-time setup
without CLI access.

**Workspace file structure:**

```
.snowflake/cortex/
├── shared/
│   ├── mappings/ts-snowflake/
│   │   ├── ts-from-snowflake-rules.md
│   │   ├── ts-snowflake-formula-translation.md
│   │   ├── ts-snowflake-properties.md
│   │   └── ts-to-snowflake-rules.md
│   ├── schemas/
│   │   ├── snowflake-schema.md
│   │   ├── thoughtspot-tml.md
│   │   ├── thoughtspot-connection.md
│   │   ├── thoughtspot-table-tml.md
│   │   ├── thoughtspot-model-tml.md
│   │   ├── thoughtspot-feedback-tml.md
│   │   └── thoughtspot-formula-patterns.md
│   └── worked-examples/snowflake/
│       ├── ts-from-snowflake.md
│       ├── ts-from-snowflake-dunder.md
│       └── ts-to-snowflake.md
└── skills/
    ├── ts-setup-sv/
    │   └── SKILL.md
    ├── ts-profile-thoughtspot/
    │   └── SKILL.md
    ├── ts-convert-to-snowflake-sv/
    │   └── SKILL.md
    └── ts-convert-from-snowflake-sv/
        └── SKILL.md
```

For each file: right-click the target folder in the Workspace file tree →
**New File** → paste the contents from the `agents/coco/` and `agents/shared/`
directories of this repository.

After creating files, run `/ts-setup-sv` to install stored procedures.

### Keeping Snowsight updated

When a new version is pushed to the stage — repeat Step 2 and Step 3.

---

## Important Notes

### Stored procedures vs `ts` CLI

The Snowsight skills use stored procedures (`TS_SEARCH_MODELS`, `TS_EXPORT_TML`, etc.)
because the Workspace runtime has no shell access. From the CLI, these same operations
are handled by the `ts` CLI directly.

The `/ts-setup-sv` skill (which installs the stored procedures) is **only needed for
Snowsight**. CLI users do not need to run it unless they also use the Workspace.

### Shared reference paths

Skills reference shared files (schemas, mappings, worked examples) via relative paths:

```
../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md
```

Two levels up from `.snowflake/cortex/skills/<skill-name>/SKILL.md` (or
`~/.snowflake/cortex/skills/<skill-name>/SKILL.md`) reaches the parent where `shared/`
sits alongside `skills/`. This works in both environments as long as the `shared/`
directory is placed at the same level as `skills/`.

### Snowflake connection

Both environments require a Snowflake connection for creating Semantic Views.
- **Snowsight**: Uses the Workspace's active role and warehouse
- **CLI**: Uses the Snowflake CLI (`snow`) or the connection configured in Cortex Code
  (`cortex connections set <name>`)
