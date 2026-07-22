<!-- status: PARTIALLY IMPLEMENTED — I9 refinement landed (PR #247); vestigial phase-file cleanup tracked as BL-125 -->

# Proposal: retire the vestigial phased-import emission in `ts tableau build-model`

**Repo:** `thoughtspot/thoughtspot-agent-skills`
**Owner:** Anuj Seth
**Affects:** `ts tableau build-model` (GENERATE-mode file emission); shared invariant I9
**Type:** codification / simplification (audit angle #11); conversion-consistency (#9)
**Status:** proposal, re-baselined after Damian's review. Docs only; the code follow-up is scoped below.

> **Correction (2026-07-15).** The first version of this doc claimed the Tableau
> `build-model` path costs **N+1 import round-trips** and proposed collapsing them to a
> single pass. That premise was wrong, and Damian caught it. The runtime is **already
> single-pass** in the way that matters: it does **base + one merged formula import** (two
> calls total), and the merged import relies on `[formula_<Name>]` id-references resolving
> in one pass — which they do. There are no per-level round-trips at runtime to eliminate.
> What is actually left is smaller and real: (1) refine invariant I9, and (2) stop emitting
> the `*.phase1+.model.tml` files that nothing consumes. This doc is rewritten around those
> two. Power BI is dropped as a driver — its converter was never N+1 either.

---

## What is actually true (corrected)

Two separate mechanisms were conflated in the original framing.

**1. The reference token — consistent, single-pass, correct.** Both the Tableau path and the
Power BI converter write a cross-reference as `[formula_<Name>]` (an **id-reference**). See
`ts_cli/model_builder.py::add_formula_prefix` and `fix_bare_refs`. Id-references resolve on
first import and are **order-independent** (verified 2026-07-09 — Evidence below). So all
formulas import in a single pass. No change is proposed here.

**2. The runtime import path — already two calls, not N+1.** The `ts-convert-from-tableau`
skill (SKILL.md Step 7) imports in two calls:

- **Phase 1:** import `{slug}.phase0.model.tml` (the base — `model_tables`, physical
  `columns`, `joins`, `parameters`; **no formulas**). One call.
- **Phase 2:** add **all** formulas at once via a separate `ts tableau build-model
  --existing-guid` call. That path (`_import_with_retry` in `commands/tableau.py`) imports
  the whole merged model in **one** `tml/import` call, and only re-imports if the server
  rejects a specific formula — dropping the failing formula (and cascade-dropping its
  dependents) and retrying. That retry loop is **error recovery**, not per-level phasing; on
  a clean model it runs exactly once.

So the runtime cost is **2 import calls**, independent of dependency depth. The "N+1" figure
came from reading `split_for_phased_import` (which builds N+1 cumulative phase dicts) as if
the runtime imported each one. It does not.

**3. The vestigial part.** `split_for_phased_import` still **writes** `{slug}.phase1.model.tml`,
`{slug}.phase2.model.tml`, … (one per dependency level) to disk in GENERATE mode. The skill's
own docs already say these are dead weight:

- SKILL.md Step 5b: *"The `.phase1+` files are not consumed anywhere in this skill's import
  flow: formulas are added independently in Step 7 Phase 2, via a separate `build-model
  --existing-guid` call."*
- SKILL.md Step 6: the pre-import validation *"only wants the base, so pass `--model-phase
  base` to drop every `*.phase1.model.tml`+ file (unused by this skill)."*

We emit files, then document that they are unused, then filter them out again. That is the
thing worth removing.

---

## Invariant I9 — split out to its own PR

Refining I9 to distinguish id-references (single-pass, safe) from display-name references
(fail on first import) is independent of any code change and lands on its own:

**→ PR #247** (`docs(I9): distinguish id-refs (single-pass) from display-name formula refs`).

That PR carries the rewritten I9 wording and the matching root-`CLAUDE.md` line. It does not
depend on this proposal; this proposal does not re-litigate it.

---

## The proposal (what remains)

**Retire the vestigial phased-formula emission in GENERATE mode.** `ts tableau build-model`
(no `--existing-guid`) should emit:

- `{slug}.phase0.model.tml` — the base model (unchanged; this is what Step 7 Phase 1 imports).
- **one** formulas artifact (all formulas, topologically ordered, id-referenced) — matching
  what Step 7 Phase 2's `--existing-guid` merge actually imports in a single call.

Stop writing `{slug}.phase1.model.tml … phaseN.model.tml`. Nothing imports them; the skill
already filters them out.

Keep, unchanged:

- `_import_with_retry`'s **drop-and-retry error recovery** in the MERGE path — this is the
  real robustness mechanism (untranslatable formula → drop + cascade-drop dependents +
  retry) and is orthogonal to level-phasing.
- `build_formula_levels` topological ordering — still used to order formulas within the
  single merged import so a formula never precedes one it references.

Net effect: fewer emitted files, GENERATE output that matches what the runtime actually
imports, and one less "why are these files here / oh they're unused" round for the next
reader (audit angle #11, agentic → deterministic-and-simpler). No round-trips change,
because there were never N+1 of them.

---

## Evidence (confirms the runtime is already correct)

### Controlled experiment (VALIDATE_ONLY, ps-internal, 2026-07-09)

Minimal one-table model; formula `XRefDerived` references formula
`XRefBase = sum([CALL_CENTER::CC_EMPLOYEES])`. Imported via
`POST /api/rest/2.0/metadata/tml/import` with `import_policy: VALIDATE_ONLY`.

| Reference style | Dependency listed first | Dependent listed first (forward) |
|---|:-:|:-:|
| **id-ref** `[formula_XRefBase]` | **OK** | **OK** |
| **name-ref** `[XRefBase]` | ERROR | ERROR |

- id-references validated cleanly, **independent of declaration order**.
- name-references failed identically either way:
  `Formula addition failed. ... Search did not find "XRefBase + 1" in your data or metadata`
  — the name was parsed as search tokens, not resolved as a formula reference.

### Create-time head-to-head (actual create, ps-internal, 2026-07-09)

A 2-level chain: `XRefL2 = [formula_XRefL1] * 2` → `XRefL1 = [formula_XRefL0] + 1` →
`XRefL0 = sum([CALL_CENTER::CC_EMPLOYEES])`. Imported with `import_policy: ALL_OR_NONE`
(genuine create), then exported back and deleted.

| Arm | Import calls | Result |
|---|:-:|---|
| Single-pass, topologically ordered (L0,L1,L2) | **1** | **OK** — all 3 formulas present on export |
| Single-pass, **forward** order (L2,L1,L0 declared) | **1** | **OK** — create succeeded regardless of order |

A dangling cross-reference fails **at create** with `Formula addition failed`, so a
successful create with all formulas intact on export proves every id-reference resolved
during creation — including the two-level transitive chain, order-independent. This is why
Step 7 Phase 2's single merged import is sufficient and the per-level phase files add nothing.

### Prior create-time evidence

A ~44-formula Power BI → ThoughtSpot conversion (same `[formula_<Name>]` id-refs + topological
ordering) was created on the same build in a single merged import and rendered correctly.

---

## Why phasing exists (archaeology — kept, and it supports the change)

Worth recording so the change is made with eyes open, not by deleting code whose purpose was
forgotten.

I9 was added in **#110** ("add I9/I10 invariants") from a **live import failure** during the
Weighted Usage migration on se-thoughtspot (2026-06-19): *"formula-to-formula bracket
references fail on first import."* Phased import (`split_for_phased_import`) was then built
into the first `build-model` in **#128** (v0.18.0) as one of 8 formula-import failure modes
from the CPG Merch migration, and validated at scale (163 formulas, 6 dependency levels).

So phasing was deliberate and battle-tested — but it does **two separable jobs**:

- **(a) dependency-level ordering** — subsumed by single-pass id-refs + topological sort
  within one import. This is the part the phase1+ *emission* represented, and it is what is
  safe to retire.
- **(b) formula-error recovery** — `_import_with_retry` + `filter_unresolvable_formulas`.
  This is a different mechanism, lives in the MERGE path, and is **kept**.

The one thing history does **not** settle: whether the failing refs in #110/#128 were
**display-name** refs (which our evidence shows still fail) or **id** refs (which resolve
single-pass). I9's original wording predates the id-ref convention, so it most likely
describes name-refs. **Confirm with Damian:** were the Weighted Usage / CPG failures
name-refs? If so, retiring the phase1+ emission carries no risk — recovery stays, ordering
moves into the single merged import that already runs.

---

## Scope of the code follow-up (separate PR, if this lands)

- `ts_cli/model_builder.py` / `ts_cli/commands/tableau.py`: GENERATE mode emits base +
  **one** ordered formulas artifact; stop writing `*.phase1+.model.tml`. `_import_with_retry`
  and `build_formula_levels` unchanged.
- SKILL.md (`ts-convert-from-tableau`): drop the Step 5b/Step 6 caveats about unused phase1+
  files (they stop existing); MINOR skill version bump + changelog.
- `tools/ts-cli` version bump (MINOR) with `__init__.py`/`pyproject.toml` in sync
  (`check_version_sync.py`); `CHANGELOG.md` entry.
- Tests in `tools/ts-cli/tests/` for the new single-artifact emitter (pure functions, no live
  cluster — per `.claude/rules/ts-cli.md`).
- I9 wording lands separately in **PR #247**.

## Appendix: reproduction script

Uses a ThoughtSpot profile / secret you already have; prints no secrets. VALIDATE_ONLY —
creates nothing.

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
