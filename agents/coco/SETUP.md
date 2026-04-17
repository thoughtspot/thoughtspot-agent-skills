# Setup Guide — Snowflake Cortex Skills

---

## Option 1: Stage-based (recommended)

Push files from the repository to a Snowflake internal stage, then ask CoCo to
deploy them to your Workspace. This is the fastest approach for ongoing updates.

### Prerequisites

- Snowflake CLI (`snow`) installed and configured with your account
- Stage `SKILLS.PUBLIC.SHARED` exists in your account

### Step 1: Push files to the stage

Run from the repository root after any update:

```bash
# Skill files
snow stage copy agents/coco/SETUP.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ --overwrite
snow stage copy agents/coco/ts-sv-setup/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-sv-setup/ --overwrite
snow stage copy agents/coco/ts-profile-setup/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-profile-setup/ --overwrite
snow stage copy agents/coco/ts-to-snowflake-sv/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-to-snowflake-sv/ --overwrite
snow stage copy agents/coco/ts-from-snowflake-sv/SKILL.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/ts-from-snowflake-sv/ --overwrite

# Shared reference files (only needed when these change)
snow stage copy agents/shared/mappings/ts-snowflake/ts-from-snowflake-rules.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-snowflake/ --overwrite
snow stage copy agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-snowflake/ --overwrite
snow stage copy agents/shared/mappings/ts-snowflake/ts-snowflake-properties.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-snowflake/ --overwrite
snow stage copy agents/shared/mappings/ts-snowflake/ts-to-snowflake-rules.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/mappings/ts-snowflake/ --overwrite
snow stage copy agents/shared/schemas/snowflake-schema.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/schemas/thoughtspot-tml.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/schemas/ --overwrite
snow stage copy agents/shared/worked-examples/snowflake/ts-from-snowflake.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/snowflake/ --overwrite
snow stage copy agents/shared/worked-examples/snowflake/ts-to-snowflake.md @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/worked-examples/snowflake/ --overwrite
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

### Step 3: Install or upgrade stored procedures

After files are deployed, run:

> /ts-sv-setup

### Keeping updated

When a new version is pushed to the stage — repeat Step 2 and Step 3.

---

## Option 2: Manual upload (no tooling required)

Paste file contents directly into the Workspace. Suitable for first-time setup
without CLI access.

### Workspace file structure

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
│   │   └── thoughtspot-tml.md
│   └── worked-examples/snowflake/
│       ├── ts-from-snowflake.md
│       └── ts-to-snowflake.md
└── skills/
    ├── ts-sv-setup/
    │   └── SKILL.md
    ├── ts-profile-setup/
    │   └── SKILL.md
    ├── ts-to-snowflake-sv/
    │   └── SKILL.md
    └── ts-from-snowflake-sv/
        └── SKILL.md
```

For each file: right-click the target folder in the Workspace file tree →
**New File** → paste the contents from the `agents/coco/` and `agents/shared/`
directories of this repository.

Cortex Code auto-detects skills once `SKILL.md` is in place at the correct path.

> **Note:** No automatic update mechanism with this approach. To update, manually
> replace the changed files.

---

## Path note

Skills reference shared files via `../../shared/`. Two levels up from
`.snowflake/cortex/skills/<skill-name>/SKILL.md` reaches `.snowflake/cortex/`,
where `shared/` sits alongside `skills/`.
