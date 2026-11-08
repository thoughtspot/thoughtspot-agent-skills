# CLI Skills — Conventions

Loaded when working in agents/cli/. These skills are the canonical source for
both **Claude Code** and **Cortex Code CLI** users. Both runtimes have full shell
access and use the `ts` CLI for ThoughtSpot API calls.

## Who uses this directory

| Runtime | Symlink location | Notes |
|---|---|---|
| Claude Code | `~/.claude/skills/<skill>` → `agents/cli/<skill>` | Also symlink `agents/claude/ts-profile-snowflake` |
| Cortex Code CLI | `~/.snowflake/cortex/skills/<skill>` → `agents/cli/<skill>` | Snowflake connections handled natively |

## Runtime: ts CLI

All ThoughtSpot API calls go through the `ts` command (`pip install -e tools/ts-cli`).
Use `ts` subcommands rather than raw REST calls when a subcommand covers the operation.
The CLI handles token caching, Keychain access, and expiry automatically.

Common calls:

```bash
ts auth whoami --profile {name}
ts metadata search --profile {name} --subtype WORKSHEET --name "%keyword%"
ts tml export {guid} --profile {name} --fqn --associated
ts connections list --profile {name}
ts tables create --profile {name}   # reads JSON spec from stdin
```

## Credential storage

Credentials are stored in the OS credential store (macOS Keychain, Windows
Credential Manager, Linux Secret Service) managed by the `ts-profile-thoughtspot`
skill. The `ts` CLI reads credentials from the keychain automatically.

Do NOT reference Snowflake Secrets, External Access Integrations, or stored
procedures for ThoughtSpot access — those belonged to the retired Snowsight runtime.

## Reference paths

Skills reference shared files via relative paths from the skill directory:

```
../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md
../../shared/schemas/thoughtspot-model-tml.md
```

This convention resolves correctly from both `~/.claude/skills/<skill>/` and
`~/.snowflake/cortex/skills/<skill>/` because both have a `shared/` directory
at the same relative location.

Do NOT use `~/.claude/shared/...` — that path works only for Claude Code and
breaks the shared convention.

## Snowflake connections

- **Cortex Code CLI**: Uses the active connection (`cortex connections set`)
- **Claude Code**: Uses `ts-profile-snowflake` skill (in `agents/claude/`)

## No mirrors to keep in step

This directory is the only copy of each skill. The CoCo Snowsight and Databricks
Genie runtimes, which carried mirrors of some of these skills, were retired on
2026-11-08 (archived at git tag `runtimes-archive-2026-11-08`), so a skill change no
longer has a second copy to update. See `.claude/rules/runtime-coverage.md`.
