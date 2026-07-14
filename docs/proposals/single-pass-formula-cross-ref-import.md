# Proposal: single-pass formula cross-reference import for `ts-convert-*` skills

**Repo:** `thoughtspot/thoughtspot-agent-skills`
**Owner:** Anuj Seth
**Affects:** `ts tableau build-model` (and the incoming `ts powerbi build-model`); shared invariant I9
**Type:** performance + codification (audit angles #14 and #11); conversion-consistency (#9)
**Status:** proposal (docs only, no code change here). Gate #1 closed and gate #2 investigated (see "Verification gate"); one confirmation with Damian outstanding before the code change is raised.

---

## TL;DR

The Tableau `build-model` path resolves formula cross-references by **phased multi-pass
import**: it splits the model into dependency levels and imports one level per pass, so a
formula never references a not-yet-created formula within a single pass. That costs
**N+1 import round-trips** (N = number of dependency levels).

Evidence on a current ps-internal build shows a model using **id-references**
(`[formula_<Name>]`) resolves cross-references in a **single import pass**, independent of
formula declaration order. If that holds under an actual create (the one thing still to
confirm), we can make single-pass the default, keep phased import as an automatic fallback,
and drop the extra round-trips — for both the Tableau skill and the incoming Power BI skill,
from one shared code path.

This is deliberately framed as a question to settle with evidence, not an assertion that the
current design is wrong. Invariant I9 came from real import failures; the proposal explains
why those failures do not apply to id-references, and names the check that must confirm it.

---

## Background: how cross-references work today

Two separate things are involved. They are easy to conflate.

**1. The reference token — already consistent.** Both the current Tableau path and the
Power BI converter write a cross-reference the same way: `[formula_<Name>]`.
See `ts_cli/model_builder.py::add_formula_prefix` (`[Name]` → `[formula_Name]`) and
`fix_bare_refs`. There is no divergence here, and none is proposed.

**2. The resolution strategy — where the cost is.** `ts_cli/model_builder.py::split_for_phased_import`
(driven by `ts_cli/tableau/dag.py::build_formula_levels`) splits one model TML into phases:

- Phase 0: tables + columns + joins + parameters, no formulas
- Phase 1..N: formulas added cumulatively by dependency level (level 0 references no other
  formula; level 1 references level 0; and so on), each phase a complete model TML
  re-imported with a `guid` to update.

Per its docstring, "Each phase is a complete model TML dict with `guid` field for update," so
the build-model flow imports **N+1 times**, each pass persisting the next dependency level so
the following pass never contains a forward reference. This is the concrete implementation of
invariant I9's "use a two-pass import."

> Confirm at the call site (`ts_cli/commands/tableau.py`, `build-model`) that each phase is a
> separate `tml/import` HTTP call — the function shape and the module description
> ("phased-import orchestration facade") indicate it is; worth stating exactly in the PR.

## Invariant I9 today

From `agents/shared/schemas/thoughtspot-model-tml.md` (mirrored in the root `CLAUDE.md`
"Critical TML invariants"):

> Formula cross-references (`[Other Formula]`) fail on first import — inline the expression or
> use a two-pass import (I9)

The proposal's core claim: **I9 is precisely true for display-name references
(`[Other Formula]`) and does not apply to id-references (`[formula_<Name>]`).**

---

## The proposal

1. Make **single-pass import with topological ordering** the default for formula
   cross-references: emit all formulas in one model TML, ordered so a formula appears after
   the formulas it references, using the existing `[formula_<Name>]` token.
2. Keep `split_for_phased_import` as an **automatic fallback**: if a single-pass import
   returns **any formula-addition failure** (not only a cross-reference resolution error),
   fall back to the phased + drop-and-retry path, so the formula-error-recovery behaviour is
   preserved when single-pass hits an untranslatable formula. No capability is lost; the
   phased code stays.
3. Put the assembly in **one shared code path** that both `ts tableau build-model` and
   `ts powerbi build-model` call, so the two conversion skills stay consistent by
   construction (audit angle #9) and any future fix lands once.
4. Refine invariant I9 to distinguish the two reference kinds (text below).

Net effect: N+1 import round-trips collapse to 1 in the common case (audit angle #14,
"redundant API round-trips"), with a safe fallback for builds that still need phasing.

### Proposed I9 rewrite

> **I9 — Formula cross-references.** A cross-reference by **display name** (`[Other Formula]`)
> fails on first import: the importer treats the name as search tokens, not a formula
> reference. Reference other formulas by **id** (`[formula_<Name>]`) instead. Id-references
> resolve on first import and are order-independent on current builds (verified
> 2026-07-09, see the conversion skills' `open-items.md`). Prefer a single-pass import with
> id-references and topological ordering; the phased/multi-pass path
> (`split_for_phased_import`) remains as a fallback for builds where single-pass id-ref
> creation fails.

---

## Evidence

### Controlled experiment (VALIDATE_ONLY, ps-internal, 2026-07-09)

Minimal one-table model; formula `XRefDerived` references formula
`XRefBase = sum([CALL_CENTER::CC_EMPLOYEES])`. Imported via
`POST /api/rest/2.0/metadata/tml/import` with `import_policy: VALIDATE_ONLY`.

| Reference style | Dependency listed first | Dependent listed first (forward) |
|---|:-:|:-:|
| **id-ref** `[formula_XRefBase]` | **OK** | **OK** |
| **name-ref** `[XRefBase]` | ERROR | ERROR |

- id-references validated cleanly, **independent of declaration order** (ordered and forward
  both passed).
- name-references failed identically either way:
  `Formula addition failed. Formula: XRefDerived, Error: Search did not find "XRefBase + 1"
  in your data or metadata. Expecting one of the valid keywords ...` — the name was parsed as
  search tokens, not resolved as a formula reference.

This directly supports the I9 refinement: the failure I9 warns about is the **name-ref** case.

### Create-time head-to-head (actual create, ps-internal, 2026-07-09)

A 2-level chain: `XRefL2 = [formula_XRefL1] * 2` → `XRefL1 = [formula_XRefL0] + 1` →
`XRefL0 = sum([CALL_CENTER::CC_EMPLOYEES])`. Imported with `import_policy: ALL_OR_NONE`
(genuine create), then exported back and deleted.

| Arm | Import calls | Result |
|---|:-:|---|
| Single-pass, topologically ordered (L0,L1,L2) | **1** | **OK** — all 3 formulas present on export |
| Single-pass, **forward** order (L2,L1,L0 declared) | **1** | **OK** — create succeeded regardless of order |
| Phased (level-cumulative: L0, then +L1, then +L2) | **3** | OK — same result, 3× the round-trips |

A dangling cross-reference fails **at create** with `Formula addition failed` (the same error
the name-ref case produces). So a successful create with all formulas intact on export is
direct proof that every id-reference resolved during creation — including the two-level
transitive chain, and independent of declaration order.

Caveat (honest): a post-create `searchdata [XRefL2]` did not return a computed value (HTTP 500
after ~30s of retries), a query-path/indexing issue on a throwaway sample-table model — not a
cross-reference failure. The resolution claim rests on create-success + export, not on the
data query.

### Prior create-time evidence

Separately, a ~44-formula model with multi-level cross-references (a Power BI → ThoughtSpot
conversion, same `[formula_<Name>]` id-refs + topological ordering) was created on the same
build in a single import pass and rendered correctly.

### Reproduction

Self-contained script in the appendix. It mints a token, builds the two variants over any
existing base table, and runs VALIDATE_ONLY. It creates nothing (VALIDATE_ONLY does not
persist).

---

## Verification gate

The honest part, and the reason the proposal keeps phasing as a fallback rather than deleting it.

1. **Create-time head-to-head — CLOSED (2026-07-09).** Genuine single-pass `create` of a
   2-level transitive chain succeeded in **1 import call**, ordered and forward, with all
   formulas intact on export; the phased path produced the same result in **3 calls**. See
   Evidence. Remaining sub-checks: deeper chains (5+ levels) and large models (see #3).
2. **Why was phasing introduced? — INVESTIGATED 2026-07-09, one confirmation left.** Git
   history is unusable here: the published repo is a single squashed commit, so there is no
   original phasing PR or commit message to read. From the code, phasing does two separable
   jobs: (a) **dependency-level ordering** (`split_for_phased_import`), which is exactly what
   single-pass id-refs replace; and (b) **formula-error recovery** (`_import_with_retry` +
   `filter_unresolvable_formulas`: drop the failing formula, cascade-drop its dependents,
   retry), plus a human review checkpoint (SKILL Step 7). Because ordering and error-recovery
   are separate mechanisms, collapsing ordering to single-pass does not remove error
   recovery; the retry path stays and the fallback (proposal item 2) triggers on any formula
   error. The one sharp question left for Damian: **was the phasing for cross-reference
   ordering, or for the formula-drop retry loop?** If ordering, single-pass id-refs handle it
   and phasing is fallback-only; if the retry loop, that mechanism is untouched by this change.
3. **Depth and size — PARTIALLY OPEN.** Confirmed to depth 2 (above). Still worth a deep
   transitive chain (5+ levels) and a large model, to be sure phasing was not guarding
   scale/timeout rather than ordering.
4. **Build coverage — OPEN.** Confirmed on current ps-internal only. Check the oldest
   ThoughtSpot build the skills still support, since I9 is build-sensitive.

With #1 closed, single-pass is proven for the common case on the current build; #2 governs
whether phasing is "fallback only" or "still required for some builds." Either way the
fallback stays, so nothing regresses.

---

## Scope of changes (if it lands)

- `ts_cli/model_builder.py` / `ts_cli/commands/tableau.py`: single-pass assembly as default;
  phased path retained as fallback. Extract the shared cross-ref assembly so
  `ts powerbi build-model` reuses it (do not reimplement).
- `agents/shared/schemas/thoughtspot-model-tml.md`: refine I9 (text above); mirror the one-
  line invariant in the root `CLAUDE.md`.
- Tests in `tools/ts-cli/tests/` for the single-pass assembler and the fallback trigger
  (pure functions, no live cluster — per `.claude/rules/ts-cli.md`).
- `tools/ts-cli` version bump (MINOR — new capability) with `__init__.py`/`pyproject.toml`
  kept in sync (`check_version_sync.py`); `CHANGELOG.md` repo entry.
- Record the verified finding in the relevant skills' `references/open-items.md`.

## Why this is a good-citizen change, not an override

- It **keeps** the phased path as a fallback; nothing regresses.
- It moves cross-ref resolution into **shared** code, which is the repo's own principle for a
  ThoughtSpot-side concern and satisfies the conversion-consistency auditor (#9).
- It is motivated by the repo's own audit angles: fewer API round-trips (#14) and
  agentic/deterministic-and-simpler codification (#11).
- It refines an invariant **with evidence and a named verification gate**, rather than
  contradicting it.

---

## Appendix: reproduction script

Uses a ThoughtSpot profile / secret you already have; prints no secrets. Run with any 3.x
Python that has `requests` + `pyyaml`.

```python
import json, yaml, requests

BASE  = "https://<your-cluster>.thoughtspot.cloud"
TOKEN = "<full-access bearer token>"      # mint via /api/rest/2.0/auth/token/full; never commit
TABLE = "CALL_CENTER"                       # any existing base table in the org
NUMCOL = "CC_EMPLOYEES"                      # any numeric column on that table

def model_tml(name, base_first, use_id_ref):
    basef = {"id": "formula_XRefBase", "name": "XRefBase",
             "expr": f"sum([{TABLE}::{NUMCOL}])"}
    ref  = "[formula_XRefBase]" if use_id_ref else "[XRefBase]"
    derf = {"id": "formula_XRefDerived", "name": "XRefDerived", "expr": f"{ref} + 1"}
    formulas = [basef, derf] if base_first else [derf, basef]
    return yaml.safe_dump({"model": {
        "name": name,
        "model_tables": [{"name": TABLE}],
        "formulas": formulas,
        "columns": [
            {"name": "XRefBase",    "formula_id": "formula_XRefBase",
             "properties": {"column_type": "MEASURE"}},
            {"name": "XRefDerived", "formula_id": "formula_XRefDerived",
             "properties": {"column_type": "MEASURE"}},
        ],
    }}, sort_keys=False)

def validate(tml):
    h = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    r = requests.post(f"{BASE}/api/rest/2.0/metadata/tml/import", headers=h,
                      json={"metadata_tmls": [tml], "import_policy": "VALIDATE_ONLY"})
    it = r.json()[0]; st = it.get("response", it).get("status", {})
    return st.get("status_code"), (st.get("error_message") or "")

for label, base_first, use_id in [
    ("id-ref  ordered", True,  True),
    ("id-ref  forward", False, True),
    ("name-ref ordered", True,  False),
    ("name-ref forward", False, False),
]:
    print(label, "->", validate(model_tml(f"ZZ XRef {label}", base_first, use_id)))
```
