---
name: repo-publisher
description: Commit, push to GitHub, and sync changed CoCo/shared files to the Snowflake stage — atomically, in the correct order. Use this instead of running git and stage-sync manually to avoid partial publishes.
---

# Repo Publisher

Handles the full commit → push → stage sequence in a single atomic operation.
Partial publishes (pushed to GitHub but forgot the stage, or vice versa) are the
most common source of CoCo skill drift. This agent prevents that.

## What it does

### Step 1: Confirm changed files

```bash
git status --short
git diff --stat
```

Show the user which files will be committed. Confirm before proceeding.

### Step 2: Stage and commit

```bash
git add <specific changed files>   # never git add -A without reviewing
git commit -m "<descriptive message>"
```

Commit message format: `<verb>: <what changed> — <why if non-obvious>`
Examples:
- `fix: ts-from-snowflake-sv join cardinality default — was MANY_TO_MANY, should be MANY_TO_ONE`
- `add: ts-model-builder skill (Claude + CoCo)`
- `update: formula translation reference — add safe_divide pattern`

### Step 3: Push to GitHub

```bash
git push origin main
```

Confirm push succeeded before proceeding to stage sync.

### Step 4: Sync to Snowflake stage (conditional)

Check which committed files are in `agents/coco/` or `agents/shared/`:

```bash
git diff HEAD~1 --name-only | grep -E "^agents/(coco|shared)/"
```

If any match:

```bash
./scripts/stage-sync.sh
```

If no CoCo/shared files changed: skip stage sync and report "No stage sync needed."

### Step 5: Report

```
repo-publisher summary
======================
Committed:  <list of files>
Pushed:     main → origin (SHA: abc1234)
Stage sync: <list of files uploaded> | No sync needed

Next steps (if applicable):
- Reload your Snowsight Workspace to pick up skill changes
- Run /ts-sv-setup if stored procedures changed
```

## Guardrails

- Never force-push
- Never use `git add -A` — always add specific files
- If `./scripts/stage-sync.sh` fails, report the error and stop — do not mark publish as complete
- If working tree has unrelated changes, commit only the files relevant to this publish and leave the rest staged/unstaged
