# `ts-security-columns` skill — design

**Date:** 2026-07-27
**Status:** DESIGN — supersedes parent spec §4
**Branch:** `feat/ts-security-columns`

Step 3 of the build order in
[`2026-07-26-ts-security-sharing-design.md`](2026-07-26-ts-security-sharing-design.md) §7.
Steps 1 and 2 both shipped: `ts share` (PR #346, ts-cli v0.108.0) and
`ts security column-rules` (PR #347, ts-cli v0.109.0, live-verified).

This document covers the skill only. Migration additions (parent spec §5) stay out of
scope.

Programme context: [`docs/multi-tenancy-platform-plan.md`](../../multi-tenancy-platform-plan.md)
§4.1, §4.3.

---

## 1. What this supersedes, and why

Parent spec §4 defines the skill as nine steps whose third is:

> Detect publication state + CSR feature availability → choose the mechanism

That framing cannot produce a correct answer, and the reason is the finding that landed
after it was written. **CSR is Org-scoped.** A published table can carry CSR that is
fully enforced in its owning Org while every tenant Org it was published to sees the
column in the clear — no error at write time, no warning at read time, in either Org
([live-verification §15](../verification/2026-07-26-ts-security-column-rules-live-verification.md)).

So "is the object published?" is a property of the *object*, and it does not select a
mechanism. The question that does is a property of the **audience**: *whose users are
you protecting, and what is their Org's relationship to this object?*

Three further live findings reshape the design and are treated as premises throughout:

| Finding | Consequence for the skill |
|---|---|
| CLS requires **Strict Object Mode**, and no API can read it. Grants applied without it succeed silently and do nothing | A human confirmation gate before the skill may *recommend* CLS. §4 |
| The mechanisms differ in **step count** — CSR is two steps over orthogonal axes, CLS is one | The plan is two ordered artefacts on the CSR path, one on the CLS path. §3 |
| **Groups are per-Org.** Primary had `Analyst`/`Consumer`/`rls-group-1..5`; ORG1 had only `Administrator`/`All`/`Demo Retail Group` | The column→group map is sourced **per Org**, never once and reused. §5 |

---

## 2. The decision layer

### 2.1 The axis

Evaluated **per (Org, object)**, not per object:

| The audience Org's relationship to the object | Mechanism | The precondition that silently defeats it |
|---|---|---|
| **Native** — that Org owns the object | **CSR** preferred; CLS possible | CSR feature flag (`403`/`10023`, disabled-form). And the object must **already be shared** in that Org, or CSR protects something nobody can open |
| **Published in** — the object lives in another Org | **CLS only** | **Strict Object Mode.** Unreadable by any API. Human gate, §4 |

Read the rows carefully: they key on the **audience Org's** relationship, not the object's
state. A published table viewed from its **owning** Org is a *native* row and CSR works
there — publication does not disqualify it. The same table viewed from a tenant Org is a
*published-in* row. One object, two rows, two mechanisms. That is the whole reframe in one
example.

CSR is preferred wherever it is available, for three reasons already established: it
declares only the *restricted* columns rather than enumerating every visible column per
group (parent spec §1), a Liveboard whose filter sits on a secured column stays
interactive rather than locking, and it composes cleanly with a table-level share instead
of being defeated by one.

### 2.2 The cell where nothing works

There is a fourth outcome the original framing cannot express, and the skill must be able
to state it plainly rather than reaching for the least-bad API call:

> **Published object + tenant audience + Strict Object Mode off.**
> CSR does not reach the tenant. CLS is accepted and does nothing. There is no working
> column-security mechanism for this configuration on this cluster.

The skill names the three real options — enable Strict Object Mode; give that tenant a
native object instead of a published one; accept the exposure knowingly — and stops. It
does not apply anything.

### 2.3 The per-Org multiplier

Protecting N tenant Orgs is **N configurations**, each against that Org's own group
names. There is no owning-Org write that propagates. This is why both manifests are keyed
by `org_name`, and it is the single most common way an operator will get this wrong:
configuring once in Primary and believing every tenant is covered.

The skill therefore never presents a single mechanism verdict for an object. It presents
**one row per (Org, object)**, and those rows can legitimately disagree — the same table
can be CSR in Primary and CLS in ORG1, and usually should be.

### 2.4 Detection

| Input | How | Failure handling |
|---|---|---|
| Publication state per table | `ts security column-rules resolve` (uses `publish_plan.published_org_ids`) or `ts publish status` | A **failed** read is not "unpublished". It blocks the row, matching the CLI's `CSR_BLOCKED: publication state could not be determined` behaviour |
| CSR feature flag | First CSR read per Org; `10023` **disabled-form** message | `10023` is **overloaded** — the access-denied form means the caller lacks CSR privileges in that Org, not that the feature is off. The skill must distinguish on message text, as `explain_csr_error` does |
| Strict Object Mode | **Human only.** No API | §4 |
| Groups available in the Org | `ts share resolve` group pre-check | A manifest naming a group from another Org fails with `Invalid group identifiers: <name>` |
| Object access for the audience | `ts share status <guid> --columns --org O` | No access → CSR is refused for that row, §3 |

---

## 3. Step count drives the plan shape

CSR is **two steps over orthogonal axes**: the object must be shared first — the Model,
optionally the Table — or the user cannot open it at all, and CSR then filters columns
*within* that access. CLS is **one step**: the grant is both the access and the security.

The skill therefore does not produce one artefact.

**CSR path** — two manifests, applied in order:

```
1. TS_SHARE_GRANTS          object grants   ── ts share resolve → apply
2. TS_COLUMN_SECURITY_RULES restricted cols ── ts security column-rules resolve → apply
```

Object grants go first. If the audience holds no object access and the operator declines
to grant it, CSR is **refused for that row**, not applied — a protected object nobody can
open is not a security outcome, it is a broken one.

**CLS path** — one manifest carrying column grants only:

```
1. TS_SHARE_GRANTS          column grants   ── ts share resolve → apply
```

with the table/column exclusivity rule enforced by `share_plan.find_exclusivity_conflicts`:
a table grant and a column grant for the same (Org, table, group) are the same mechanism
at two granularities, so the broader defeats the narrower and the plan is refused rather
than merged. CSR has no equivalent rule and needs none.

---

## 4. The Strict Object Mode gate

CLS's precondition is unreadable by any API, and a CLS grant applied without it **succeeds
silently and does nothing**. Recommending a mechanism that silently no-ops is worse than
recommending nothing, so the confirmation is a **step with a stop**, not a warning to
notice.

`ts share resolve` already warns whenever a plan carries column grants. The skill must not
rely on the operator reading that: the warning arrives at plan time, after the mechanism
has been chosen, and it is one line in a stream of output.

The gate runs **before the skill may recommend CLS for any row**:

| Answer | Behaviour |
|---|---|
| **Yes** | CLS recommendation proceeds. The confirmation is recorded in the plan artefact so a later reader knows the gate was passed rather than skipped |
| **No** | The skill states that CLS will no-op. For a published-object row that means §2.2 — no working mechanism. It presents the three options and stops |
| **Don't know** | **Stop.** Print how to check (cluster configuration, with a ThoughtSpot admin). Never proceed on an unconfirmed gate |

The gate is asked **once per run**, not per row — Strict Object Mode is cluster-wide. It
fires on either trigger: a **published-in** row, which has no mechanism but CLS and is
known from step 4's detection; or a **native** row where the operator elects CLS over the
preferred CSR at step 6. In the second case the gate runs before that election is
accepted, not after.

---

## 5. Where the column→group map comes from

### 5.1 The decision: define the contract, defer the transform

Parent spec §4.1 and plan §4.1 both name `ts migrate audit`'s column-usage map as the
producer: used columns get granted, unused withheld, one discovery layer rather than
three. That is the right target. It cannot be the source today, for two **structural**
reasons rather than one branch-timing reason:

1. **`column-mapping.csv` has no `org_name`.** Its header is
   `model, tenant_column, tenant_column_id, published_column, status`
   (`ts_cli/migrate/mapping.py`). Both security manifests are Org-keyed, and must be,
   because groups are per-Org (§2.3).
2. **Usage is only recorded for gap columns.** `classify_columns`
   (`ts_cli/migrate/match.py:23`) computes `GAP_BLOCKER if used else GAP` — but only on
   the branch where the column has no published counterpart. `MATCHED` and
   `BINDING_MISMATCH` rows carry no usage flag, and `MATCHED` columns are precisely the
   ones a column-security manifest grants or withholds.

`ts migrate` also being Phase 1 on the unmerged `feat/ts-org-migrate` is the lesser
problem; even merged as-is, the artefact would not carry what the skill needs.

**So:** the skill consumes the two already-shipped manifest shapes through
`--source uniform|file|db`, and this spec records the contract the transform must satisfy.
That contract is filed as a backlog item against the migrate work, so it lands where the
transform will be built rather than as a note here.

### 5.2 The contract `ts migrate audit` must satisfy

For an auto-source to become possible, `column-mapping.csv` needs two additions:

| Column | Why |
|---|---|
| `org_name` | The tenant Org the row's Model belongs to. Both manifests are Org-keyed; without it the transform cannot emit a valid row |
| `used` | Boolean, on **every** row — not only gap rows. This is the used/unused split the grant decision turns on |

With both present the transform is mechanical:

```
used   = true   →  grant   (CLS: a TS_SHARE_GRANTS column row)
used   = false  →  withhold (CSR: a TS_COLUMN_SECURITY_RULES row, restricted)
```

Note the inversion: CSR declares the **restricted** columns, CLS enumerates the **visible**
ones. The two manifests are not interchangeable and must not be modelled as one.

### 5.3 What the skill offers today

| Source | Use |
|---|---|
| `uniform` | Same restricted columns and group names in every target Org. The common case |
| `file` | A CSV expressing per-Org variation |
| `db` | A Snowflake governance table, same columns |
| *(future)* `audit` | `ts migrate audit` output, once §5.2 lands |

`--init-table` emits the DDL for either manifest, matching `ts share` and `ts publish`.

---

## 6. Architecture

### 6.1 Two-manifest orchestrator, no CLI changes

The skill owns the **decision, the ordering and the gates**. It drives the shipped
pipelines unchanged.

```
                   ┌─ ts share export ─► ts share resolve ─► ts share apply
decision layer ────┤    (object grants, then CLS column grants)
                   │
                   └─ ts security column-rules resolve ─┬─► apply         (API route)
                                                        └─► build ─► import (TML route)
```

Two alternatives were rejected:

**A fused `ts security columns resolve`** emitting one plan spanning both mechanisms.
It would give a cleaner runtime, but it introduces a third plan format and a new CLI
surface for something the skill can already sequence — against `.claude/rules/ts-cli.md`'s
"do not add a CLI command speculatively". Revisit only if a second consumer appears.

**A decision-only advisor** that recommends and prints commands. Safest, but every sibling
skill delivers dry-run → apply → verify, and an advisor cannot enforce the ordering
constraint in §3 that makes the CSR path work.

### 6.2 Which CSR route

`apply` (API) is the default. `build` → `import` (TML) is offered when the operator wants
the reviewable `column_security_rules` document — the artefact parent spec §5.3 wants
preserved into a migration plan directory. Both consume the same plan JSON, so the choice
is presentation, not semantics.

### 6.3 Steps

```
 1  Authenticate                                          auto
 2  Select the Table(s) / Model(s)                        you choose
 3  Name the audience: which Org's users, which groups    you choose
 4  Detect per (Org, object): native vs published-in,
    CSR flag, existing object access                      auto
 5  Strict Object Mode gate (once, if any row is
    published-in)                                         you confirm — hard stop
 6  Present the per-(Org, object) mechanism matrix        you confirm
 7  Source the column→group map, per Org                  you choose
 8  Review the grant / rule matrix                        you confirm
 9  Dry-run both routes                                   auto
10  Apply — object grants first, then columns             you confirm (checkpoint)
11  Verify: fetch back and diff                           auto
```

Step 3 before step 4 is deliberate and is the whole reframe: the audience is named first,
because the audience selects the mechanism (§2.1). Step 6 presents rows that may
legitimately disagree with each other (§2.3).

Step 11 verifies through the same read paths the CLIs already expose
(`ts security column-rules get`, `ts share status --columns`), and diffs against the
baseline captured in step 4. It cannot verify what no API exposes: a CLS grant reads back
identically whether Strict Object Mode is on or off. The skill says so rather than
implying the verify covers it.

---

## 7. Naming: a new `ts-security-*` family

`ts-security-columns` matches no family in `.claude/rules/skill-naming.md`. Adding one:

| Family | Pattern | Semantic | Members |
|---|---|---|---|
| `ts-security-*` | `ts-security-{aspect}` | Cross-object, cross-Org security configuration that **chooses between mechanisms** rather than driving one. Second token names the aspect secured (`columns`, `rls`) | `ts-security-columns`, `ts-security-rls` *(planned)* |

**Why no existing family fits.** `ts-object-*` is a single-object scoped operation; this
spans a set of objects across a set of Orgs and produces per-(Org, object) verdicts.
`ts-dependency-*` rewrites the dependency graph; this changes no object definition at all.
`ts-audit` is read-only. `ts-publish-*` distributes an object; this restricts one.

**Why the family is warranted rather than a one-off allowlist entry.** It mirrors the
`ts security` CLI group shipped in v0.109.0, which was named for exactly this reason —
`ts security column-rules` names the *mechanism* explicitly, leaving `ts security rls` as
the reserved sibling. The skill layer should mirror that boundary, not blur it.

Three updates in the same PR, per the rule: the family table, `FAMILY_PATTERNS` in
`tools/validate/check_skill_naming.py`, and the root `CLAUDE.md` change-impact map.

---

## 8. Runtime coverage

CLI only. CoCo Snowsight cannot invoke the `ts` CLI, and the skill is an orchestration
layer over two CLI pipelines with a mandatory interactive gate — there is no
stored-procedure shape for it. An `EXPECTED_DIVERGENCES` entry in
`tools/validate/check_runtime_coverage.py` records this.

---

## 9. Live verification plan

Cluster: profile `nebula-damian-alias`. Orgs Primary / ORG1 / ORG2 / ORG3.
`T1/T2/T3_PUBLISH` owned by Primary and unpublished; ORG1 has its own
`T4/T5/T6_PER_ORG`. Users `guest1-4` and `rlsgroup1-5user` in Primary; `guest1` also in
ORG1's `Demo Retail Group`. CSR feature flag ON. **Strict Object Mode ON** — confirmed by
the repo owner, 2026-07-27, which makes the CLS path testable for the first time.

Baseline captured before anything changes, restored afterwards, and the diff proven by a
final read — the discipline the previous two rounds used.

| # | Question | Method | Settles |
|---|---|---|---|
| 1 | Can a tenant Org configure **usable** CSR on its **own native** table? | CSR in ORG1 on `T4_PER_ORG` against `Demo Retail Group`, verified as a real non-admin ORG1 user | Parent spec open item #5, native half. The prior attempt failed only on a group-name artefact (`Analyst` does not exist in ORG1), not a product rule |
| 2 | Can a tenant Org configure usable CSR on a table **published into** it? | Republish `T2_PUBLISH` into ORG1 (parameterize → publish), retry CSR there against an ORG1 group, confirm ORG1 privileges **independently of the call** so a repeat `10023` is diagnosable | Parent spec open item #5, published half — the question §2.1's second row depends on |
| 3 | Does a group holding **only** column grants reach the table at all? | CLS column grant in ORG1 with no table grant, opened as a real non-admin user | Parent spec open item #1. Untestable before; load-bearing for the entire CLS path |
| 4 | Does a table-level `NO_ACCESS` clear existing column grants? | Grant columns, then table-level `NO_ACCESS`, then read back | The `ts share` carry-forward, and the reason `ts share` refuses revoke-and-grant in one manifest |

Item 2 mutates the cluster non-trivially and is unwound in reverse: unpublish →
unparameterize → delete the template variable. `ts publish push` fails closed on an
unparameterized object, so the parameterize step is mandatory, not incidental.

Findings land in
`docs/superpowers/verification/2026-07-27-ts-security-columns-live-verification.md`.

**If item 2 shows a tenant Org cannot configure CSR on a published object**, §2.1's second
row is confirmed as a platform constraint rather than a conservative default. **If it
shows the tenant can**, the row changes: CSR becomes available for published objects
configured tenant-side, and `ts security column-rules`'s `CSR_BLOCKED` default deserves
revisiting in a follow-up. Either outcome is a real answer; the design does not depend on
which.

---

## 10. Out-of-scope corrections this PR still makes

`agents/cli/ts-publish-orgs/SKILL.md` Step 12 tells users:

> Column security rules **cannot be defined on published objects**, so publishing commits
> the tenant to column-level sharing.

That is the disproven claim, on the page that hands off to this skill. The conclusion it
draws is accidentally right for a tenant audience and wrong for the owning Org's own
users, and the mechanism it states is wrong outright. Corrected here, because leaving the
handoff page contradicting the skill it hands off to is worse than a slightly wider diff.

Parent spec §5.1 (`CSR_BLOCKER`) still carries the same claim. It is migration scope
(parent spec §5), untouched here, and tracked by BL-141.

---

## 11. Open items

| # | Item | Status |
|---|---|---|
| 1 | Whether a tenant Org can be given usable CSR — native and published halves | Under test, §9 items 1–2. Parent spec open item #5 |
| 2 | Whether a group holding only column grants can reach the table | Under test, §9 item 3. Parent spec open item #1 |
| 3 | Whether a table-level `NO_ACCESS` clears existing column grants | Under test, §9 item 4 |
| 4 | Whether Strict Object Mode ever becomes API-readable | OPEN. If it does, §4's gate becomes a check and the skill drops a manual step |
| 5 | The `ts migrate audit` contract in §5.2 | Deferred to a backlog item against the migrate work |
