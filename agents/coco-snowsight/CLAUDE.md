# CoCo Snowsight Skills — Conventions

Loaded when working in agents/coco-snowsight/. Covers Snowsight Workspace
constraints, stage deployment, and Snowsight-specific conventions.

## Runtime constraints

Snowsight Workspaces have no `python3`, `curl`, or direct outbound API calls.
All ThoughtSpot API access is via stored procedures:

- `TS_SEARCH_MODELS` — search for models/worksheets
- `TS_EXPORT_TML` — export TML for a given GUID
- `TS_IMPORT_TML` — import TML back into ThoughtSpot
- `TS_LIST_CONNECTIONS` — list available connections

Do not add steps that require shell commands or direct HTTP calls.

Do NOT use the `ts` CLI — it is not available in Snowsight. The `ts` CLI is for
the CLI runtime only (see `agents/cli/`).

## Deploy is not automatic

Every change to `agents/coco-snowsight/` or `agents/shared/` requires a manual
stage push:

```bash
./scripts/stage-sync.sh
```

Or run the individual `snow stage copy` commands from `agents/coco-snowsight/SETUP.md`.

Always run after `git commit + git push`. Forgetting to stage means CoCo runs stale skill files.

## Stage path mapping

The default stage is `@SKILLS.PUBLIC.SHARED`; override with `SNOW_STAGE` env var (see SETUP.md).

```
agents/coco-snowsight/       → $SNOW_STAGE/skills/
agents/shared/               → $SNOW_STAGE/shared/
```

In the Workspace, skills land at `.snowflake/cortex/skills/<skill-name>/SKILL.md`.

## Reference paths (CoCo Snowsight convention)

CoCo Snowsight skills reference shared files via relative paths from the skill directory:

```
../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md
../../shared/schemas/thoughtspot-model-tml.md
```

Do NOT use `~/.claude/shared/...` — that is the Claude Code convention and does not resolve in Snowsight.

## Parity with other agents

Substantive skill changes (new steps, bug fixes, rule corrections) must also be made in:
- `agents/claude/<skill>/SKILL.md` — Claude Code version
- `agents/cli/<skill>/SKILL.md` — Cortex Code CLI version

Unless the change is Snowsight-specific (e.g. stored procedure usage, Snowsight UI
instructions). See `agents/PARITY.md` for the full cross-agent mapping.

## Stored procedures

Adding or changing a stored procedure requires the user to run `/ts-setup-sv` in their
Workspace after deploying. Document this requirement in the PR description and in the
relevant SKILL.md step.
