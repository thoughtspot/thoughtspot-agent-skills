# Setup Guide — Snowsight Workspace

Deploy ThoughtSpot ↔ Snowflake skills to a Snowsight Workspace. Skills are
deployed via a Snowflake internal stage and use stored procedures to call the
ThoughtSpot API (since the Workspace runtime has no shell access).

> **Prefer the CLI?** See `agents/cli/SETUP.md` for the simpler Cortex Code
> CLI setup — no stored procedures, stages, or external access integrations needed.

---

## Prerequisites

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

---

## Option A: Stage-based (recommended)

### Step 1: Push files to the stage

Run from the repository root after any update:

```bash
# Skill files
snow stage copy agents/coco-snowsight/SETUP.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ --overwrite
snow stage copy agents/coco-snowsight/ts-setup-sv/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-setup-sv/ --overwrite
snow stage copy agents/coco-snowsight/ts-profile-thoughtspot/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-profile-thoughtspot/ --overwrite
snow stage copy agents/coco-snowsight/ts-convert-to-snowflake-sv/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-convert-to-snowflake-sv/ --overwrite
snow stage copy agents/coco-snowsight/ts-convert-from-snowflake-sv/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-convert-from-snowflake-sv/ --overwrite
snow stage copy agents/coco-snowsight/ts-recipe-formula-business-days-snowflake/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-recipe-formula-business-days-snowflake/ --overwrite
snow stage copy agents/coco-snowsight/ts-recipe-formula-hms-display-snowflake/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-recipe-formula-hms-display-snowflake/ --overwrite

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
snow stage copy agents/shared/schemas/ts-model-conversion-invariants.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-answer-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-liveboard-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-sets-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-view-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-alert-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-feedback-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/mappings/ts-databricks/ts-from-databricks-rules.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-databricks/ --overwrite
snow stage copy agents/shared/mappings/ts-databricks/ts-to-databricks-rules.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-databricks/ --overwrite
snow stage copy agents/shared/mappings/ts-databricks/ts-databricks-formula-translation.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-databricks/ --overwrite
snow stage copy agents/shared/mappings/ts-databricks/ts-databricks-properties.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-databricks/ --overwrite
snow stage copy agents/shared/schemas/databricks-metric-view.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/mappings/tableau/tableau-formula-translation.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/tableau/ --overwrite
snow stage copy agents/shared/mappings/tableau/tableau-tml-rules.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/tableau/ --overwrite
snow stage copy agents/shared/worked-examples/snowflake/ts-from-snowflake.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/snowflake/ --overwrite
snow stage copy agents/shared/worked-examples/snowflake/ts-from-snowflake-dunder.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/snowflake/ --overwrite
snow stage copy agents/shared/worked-examples/snowflake/ts-to-snowflake.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/snowflake/ --overwrite
snow stage copy agents/shared/worked-examples/snowflake/ts-from-snowflake-identifier-resolution.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/snowflake/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-sql-view-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/worked-examples/tableau/liveboard-kpi-sparkline.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/tableau/ --overwrite
snow stage copy agents/shared/worked-examples/tableau/static-set-to-column-set.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/tableau/ --overwrite
snow stage copy agents/shared/worked-examples/tableau/topn-set-to-query-set.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/tableau/ --overwrite
snow stage copy agents/shared/worked-examples/databricks/ts-to-databricks.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/databricks/ --overwrite
snow stage copy agents/shared/worked-examples/databricks/ts-from-databricks.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/databricks/ --overwrite
snow stage copy agents/shared/worked-examples/databricks/ts-from-databricks-sql-view.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/databricks/ --overwrite
```

Or use the sync script (only uploads changed files):

```bash
./scripts/stage-sync.sh          # changed files only
./scripts/stage-sync.sh --all    # force full upload
```

### Step 2: Ask CoCo to deploy to Workspace

In your Snowsight Workspace, ask:

> "Deploy skill files from @SKILLS.PUBLIC.SHARED to this workspace"

CoCo reads each file from the stage and writes it to the corresponding workspace path.

**Stage → Workspace path mapping:**

| Stage path | Workspace path |
|---|---|
| `@SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/<name>/SKILL.md` | `.snowflake/cortex/skills/<name>/SKILL.md` |
| `@SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/` | `.snowflake/cortex/shared/` |

### Step 3: Install stored procedures

After files are deployed, run in the Workspace:

> /ts-setup-sv

This creates the stored procedures (`TS_SEARCH_MODELS`, `TS_EXPORT_TML`, `TS_IMPORT_TML`,
`TS_LIST_CONNECTIONS`), the `THOUGHTSPOT_PROFILES` table, secrets, and external access
integrations needed for the skills to call the ThoughtSpot API from within Snowflake.

---

## Option B: Manual upload (no tooling required)

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
│   └── worked-examples/
│       ├── snowflake/
│       │   ├── ts-from-snowflake.md
│       │   ├── ts-from-snowflake-dunder.md
│       │   └── ts-to-snowflake.md
│       └── tableau/
│           ├── liveboard-kpi-sparkline.md
│           ├── static-set-to-column-set.md
│           └── topn-set-to-query-set.md
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
**New File** → paste the contents from the `agents/coco-snowsight/` and `agents/shared/`
directories of this repository.

After creating files, run `/ts-setup-sv` to install stored procedures.

---

## Keeping updated

When a new version is pushed to the stage — repeat Step 2 and Step 3.

---

## Important Notes

### Stored procedures

The Snowsight skills use stored procedures (`TS_SEARCH_MODELS`, `TS_EXPORT_TML`, etc.)
because the Workspace runtime has no shell access.

The `/ts-setup-sv` skill installs these procedures. It must be re-run when:
- A new ThoughtSpot profile is added
- Procedures are upgraded (new skill version deployed)

### Shared reference paths

Skills reference shared files via relative paths from the skill directory:

```
../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md
```

Two levels up from `.snowflake/cortex/skills/<skill-name>/SKILL.md` reaches the
parent where `shared/` sits alongside `skills/`.

### Snowflake connection

The Snowsight skills use the Workspace's active role and warehouse for SQL
operations (creating Semantic Views).
