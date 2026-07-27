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

### The Databricks Genie runtime (`agents/databricks/`)

`agents/databricks/skills/` is a **fourth, deliberately-separate** runtime — Databricks
Genie Code skills deployed by `agents/databricks/deploy.sh` into a workspace `.assistant/`
path. It is intentionally **outside** the cli/claude/coco mirror-and-version tooling:

- Its skills (`ts-convert-from-databricks-mv`, `ts-convert-to-databricks-mv`) are **thin
  shells** that defer all conversion logic to the shared mappings/schemas in `agents/shared/`
  — they are not line-for-line mirrors of the CLI skills, so the version-mirror model in
  `check_mirror_sync.py` (which the CoCo mirrors use) does not apply and they carry no
  `synced-from` markers.
- They **are** now shown in `agents/PARITY.md` (the `databricks` column) so the matrix is no
  longer blind to them, and `generate_parity.py` scans `agents/databricks/skills/`.
- `check_runtime_coverage.py` and the CLAUDE.md change-impact mirror set deliberately do NOT
  include this runtime — keeping parity with the Genie skills is a manual review against the
  shared mappings, not an automated gate.

---

## The principle

**CLI is the primary runtime.** CoCo Snowsight and Databricks Genie exist
only for conversions to/from their respective databases (plus the auth and
setup infrastructure those conversions need). All other skills live in CLI only.

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

Today's coverage (verified 2026-07-22):

CoCo Snowsight carries only the Snowflake conversion pipeline + its auth/setup
infrastructure. All other skills are CLI-only.

| Skill | Claude/CLI | CoCo | Notes |
|---|:-:|:-:|---|
| `ts-convert-from-snowflake-sv` | ✓ | ✓ | Snowflake conversion pipeline |
| `ts-convert-to-snowflake-sv` | ✓ | ✓ | Snowflake conversion pipeline |
| `ts-profile-thoughtspot` | ✓ | ✓ | Auth — conversions need ThoughtSpot access |
| `ts-setup-sv` | — | ✓ | CoCo-only: installs stored procedures CoCo uses |
| All other skills | ✓ | — | CLI-only: CoCo scoped to conversion pipeline |

---

## What this rule does NOT cover

- **Skill content sync** — when a CLI SKILL.md is updated, the CoCo mirror
  may drift. Keeping content in sync is the change-impact map's job
  in `CLAUDE.md`. The runtime-coverage validator only checks
  *existence*, not content currency.
- **Shared file deployment** — `agents/coco-snowsight/SETUP.md` stage-copy list is
  validated by `check_consistency.py`, not here.
