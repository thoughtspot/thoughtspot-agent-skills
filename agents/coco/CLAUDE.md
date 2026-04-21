# CoCo Skills — Conventions

Loaded when working in agents/coco/. Covers Snowsight constraints, stage
deployment, and CoCo-specific conventions.

## Runtime constraints

Snowsight Workspaces have no `python3`, `curl`, or direct outbound API calls.
All ThoughtSpot API access is via stored procedures:

- `TS_SEARCH_MODELS` — search for models/worksheets
- `TS_EXPORT_TML` — export TML for a given GUID
- `TS_IMPORT_TML` — import TML back into ThoughtSpot
- `TS_LIST_CONNECTIONS` — list available connections

Do not add steps that require shell commands or direct HTTP calls.

## Deploy is not automatic

Unlike Claude Code skills (which update via symlinks), every change to `agents/coco/`
or `agents/shared/` requires a manual stage push:

```bash
./scripts/stage-sync.sh
```

Or run the individual `snow stage copy` commands from `agents/coco/SETUP.md`.

Always run after `git commit + git push`. Forgetting to stage means CoCo runs stale skill files.

## Stage path mapping

```
agents/coco/                 → @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/skills/
agents/shared/               → @SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex/shared/
```

In the Workspace, skills land at `.snowflake/cortex/skills/<skill-name>/SKILL.md`.

## Reference paths (CoCo convention)

CoCo skills reference shared files via relative paths from the skill directory:

```
../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md
../../shared/schemas/thoughtspot-model-tml.md
```

Do NOT use `~/.claude/shared/...` — that is the Claude Code convention and does not resolve in Snowsight.

## Parity with Claude Code skills

Substantive skill changes (new steps, bug fixes, rule corrections) must also be made in the
corresponding `agents/claude/<skill>/SKILL.md` unless the change is CoCo-specific (e.g.
stored procedure usage, Snowsight UI instructions).

## Stored procedures

Adding or changing a stored procedure requires the user to run `/ts-setup-sv` in their
Workspace after deploying. Document this requirement in the PR description and in the
relevant SKILL.md step.
