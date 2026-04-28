# Runtime-Coverage Convention

Skills in this repo are served across three runtimes:

| Runtime | Layout | What it serves |
|---|---|---|
| `agents/claude/` | `<skill>/SKILL.md` | Claude Code skills (interactive, full reference library) |
| `agents/cursor/` | `rules/<skill>.mdc` (flat) | Cursor AI rules (condensed procedural guides) |
| `agents/coco/` | `<skill>/SKILL.md` | Snowflake Cortex / CoCo skills (Snowsight stored-procedure path) |

Not every skill belongs in every runtime. The rule below documents which
skills should mirror across runtimes and which legitimately diverge — and is
enforced by `tools/validate/check_runtime_coverage.py`.

---

## The principle

**Cursor mirrors Claude.** Both are external IDE-based runtimes that call
ThoughtSpot via the `ts` CLI. Anything Claude can do, Cursor should be able
to do (modulo Cursor's condensed-rule format).

**CoCo legitimately diverges from Claude / Cursor** because it runs inside
Snowsight (no shell, no `ts` CLI, stored-procedure execution model). Some
skills fit CoCo's environment, others don't.

---

## What must mirror

For every skill present in `agents/claude/`, there must be a Cursor `.mdc`
file at `agents/cursor/rules/<skill>.mdc`. The Cursor version is allowed to be
condensed — it doesn't need to replicate every reference file or every step's
inline detail — but it must:

- Match the Claude skill's name (file stem = directory name)
- Match the Claude skill's family (per
  [skill-naming.md](skill-naming.md))
- Cover the same procedural intent (the user can complete the skill's
  primary workflow following only the `.mdc`)
- Reference `~/.cursor/shared/...` for any shared schemas/mappings the skill
  needs (parallel to Claude's `~/.claude/shared/...`)
- Have a `## Changelog` section starting at 1.0.0 when first added

When a Cursor mirror is authored without testing on a real Cursor install
(common — most contributors have only Claude Code), the `.mdc` should open
with a "Untested in Cursor" disclaimer and a pointer to the Claude SKILL.md
as the authoritative source.

---

## CoCo's documented divergences

CoCo's runtime is materially different from Claude/Cursor:

- Runs inside Snowsight (no local shell, no `ts` CLI access)
- Skills execute as stored procedures + worksheets, not as interactive prompts
- Snowflake-specific entry points (`SKILLS.PUBLIC.*` stored procs) replace
  the `ts` CLI calls Claude/Cursor make

This means:

1. **Claude/Cursor skills that depend on the `ts` CLI** can't be ported to
   CoCo without rewriting against Snowflake's stored-procedure model. Most
   are out of scope.
2. **CoCo-only skills exist** that have no Claude/Cursor equivalent —
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
2. **Author the Claude SKILL.md** under `agents/claude/<skill>/`
3. **Author the Cursor `.mdc`** under `agents/cursor/rules/<skill>.mdc`
   (mark "Untested in Cursor" if you don't have Cursor)
4. **For CoCo:** if the skill fits the Snowsight / stored-procedure model,
   author `agents/coco/<skill>/SKILL.md` too. If it doesn't fit, add an entry
   to `EXPECTED_DIVERGENCES` in `tools/validate/check_runtime_coverage.py`
   explaining why
5. The validator runs in pre-commit and fails if any of the above are missing

---

## Validator output

Today's coverage (verified 2026-04-28):

| Skill | Claude | Cursor | CoCo | Notes |
|---|:-:|:-:|:-:|---|
| `ts-convert-from-snowflake-sv` | ✓ | ✓ | ✓ | Full mirror across all runtimes |
| `ts-convert-to-snowflake-sv` | ✓ | ✓ | ✓ | |
| `ts-dependency-manager` | ✓ | ✓ | — | CoCo: graph walk too heavy for Snowsight runtime |
| `ts-object-answer-promote` | ✓ | ✓ | — | CoCo: complex search-query manipulation not supported |
| `ts-object-model-coach` | ✓ | ✓ | — | CoCo: interactive coaching workflow doesn't fit stored-proc model |
| `ts-profile-thoughtspot` | ✓ | ✓ | ✓ | All runtimes need to credentialise to ThoughtSpot |
| `ts-profile-snowflake` | ✓ | ✓ | — | CoCo: lives inside Snowflake, no Snowflake profile needed |
| `ts-setup-sv` | — | — | ✓ | CoCo-only: installs stored procedures CoCo uses |

---

## What this rule does NOT cover

- **Skill content sync** — when a Claude SKILL.md is updated, the Cursor
  `.mdc` may drift. Keeping content in sync is the change-impact map's job
  in `CLAUDE.md` ("agents/cursor/rules/*.mdc | Corresponding agents/claude/
  SKILL.md (keep in sync)"). The runtime-coverage validator only checks
  *existence*, not content currency.
- **Shared file deployment** — `agents/coco/SETUP.md` stage-copy list is
  validated by `check_consistency.py`, not here.
