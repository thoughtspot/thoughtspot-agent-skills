# Runtime-Coverage Convention

Skills in this repo are served across two runtimes:

| Runtime | Layout | What it serves |
|---|---|---|
| `agents/cli/` | `<skill>/SKILL.md` | Canonical CLI skills (Claude Code + Cortex Code CLI; interactive, full reference library). `agents/claude/` is a Claude-only annex holding `ts-profile-snowflake`. |
| `agents/coco-snowsight/` | `<skill>/SKILL.md` | Snowflake Cortex / CoCo skills (Snowsight stored-procedure path) |

Not every skill belongs in every runtime. The rule below documents which
skills should mirror across runtimes and which legitimately diverge — and is
enforced by `tools/validate/check_runtime_coverage.py`, which scans
`agents/cli/`, `agents/claude/`, and `agents/coco-snowsight/` and merges skills by
name.

---

## The principle

**CoCo legitimately diverges from Claude / CLI** because it runs inside
Snowsight (no shell, no `ts` CLI, stored-procedure execution model). Some
skills fit CoCo's environment, others don't.

---

## CoCo's documented divergences

CoCo's runtime is materially different from Claude/CLI:

- Runs inside Snowsight (no local shell, no `ts` CLI access)
- Skills execute as stored procedures + worksheets, not as interactive prompts
- Snowflake-specific entry points (`SKILLS.PUBLIC.*` stored procs) replace
  the `ts` CLI calls Claude/CLI make

This means:

1. **Claude/CLI skills that depend on the `ts` CLI** can't be ported to
   CoCo without rewriting against Snowflake's stored-procedure model. Most
   are out of scope.
2. **CoCo-only skills exist** that have no Claude/CLI equivalent —
   typically setup procs (`ts-setup-sv` installs the procedures CoCo itself
   uses).
3. **`ts-profile-snowflake` doesn't exist in CoCo** because CoCo IS in
   Snowflake — there's nothing to credentialise.

The validator's `EXPECTED_DIVERGENCES` map encodes these intentional
omissions. Adding to it requires a one-line justification in the comment.

---

## Adding a new skill

In a single PR:

1. **Pick a family** per [skill-naming.md](skill-naming.md)
2. **Author the CLI SKILL.md** under `agents/cli/<skill>/`
3. **For CoCo:** if the skill fits the Snowsight / stored-procedure model,
   author `agents/coco-snowsight/<skill>/SKILL.md` too. If it doesn't fit, add an entry
   to `EXPECTED_DIVERGENCES` in `tools/validate/check_runtime_coverage.py`
   explaining why
4. The validator runs in pre-commit and fails if any of the above are missing

---

## Validator output

Today's coverage (verified 2026-06-14):

| Skill | Claude/CLI | CoCo | Notes |
|---|:-:|:-:|---|
| `ts-convert-from-databricks-mv` | ✓ | — | CoCo: Databricks CLI not available in Snowsight runtime |
| `ts-convert-from-snowflake-sv` | ✓ | ✓ | Full mirror across all runtimes |
| `ts-convert-to-databricks-mv` | ✓ | — | CoCo: Databricks CLI not available in Snowsight runtime |
| `ts-convert-to-snowflake-sv` | ✓ | ✓ | |
| `ts-dependency-manager` | ✓ | — | CoCo: graph walk too heavy for Snowsight runtime |
| `ts-object-answer-promote` | ✓ | — | CoCo: complex search-query manipulation not supported |
| `ts-object-model-coach` | ✓ | — | CoCo: interactive coaching workflow doesn't fit stored-proc model |
| `ts-profile-databricks` | ✓ | — | CoCo: Snowsight runs inside Snowflake, no Databricks profile needed |
| `ts-profile-thoughtspot` | ✓ | ✓ | All runtimes need to credentialise to ThoughtSpot |
| `ts-profile-snowflake` | ✓ | — | CoCo: lives inside Snowflake, no Snowflake profile needed |
| `ts-setup-sv` | — | ✓ | CoCo-only: installs stored procedures CoCo uses |

---

## What this rule does NOT cover

- **Skill content sync** — when a CLI SKILL.md is updated, the CoCo mirror
  may drift. Keeping content in sync is the change-impact map's job
  in `CLAUDE.md`. The runtime-coverage validator only checks
  *existence*, not content currency.
- **Shared file deployment** — `agents/coco-snowsight/SETUP.md` stage-copy list is
  validated by `check_consistency.py`, not here.
