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

The second row is **live-verified, not a conservative default** (2026-07-27). CSR is
closed off there by *two independent* mechanisms: a rule defined in the owning Org does
not travel with publication, and the tenant Org cannot define one either — `HTTP 500`,
code **`10038`**, `FORBIDDEN`, with full `ADMINISTRATION` in that Org and a same-session
control write succeeding on that Org's own native table. Either mechanism alone would
leave a workaround; together they close it. CLS in the tenant Org on the same published
object was confirmed working in the same run.

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
| Tenant CSR capability | **Not probeable by reading.** Infer it from publication state | Live-verified 2026-07-27: a tenant read of a published table returns `[]` when no rule exists and `10023` once one does. A clean `[]` therefore proves nothing about whether the tenant could *write*. See §9 |
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

**Revoking CLS is a column-level operation.** Live-verified 2026-07-27: an object-level
`NO_ACCESS` against a group holding column grants removes the object from *search* but
leaves the entitlement intact — the object still opens by direct link, still showing the
granted columns. The intuitive operator action does not do what it looks like it does, so
the skill must say this plainly and must never present an object-level deny as a way to
undo a column grant. Platform gap, BL-142.

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

## 9. Live verification — RESULTS (2026-07-27)

Cluster: profile `nebula-damian-alias`, Orgs Primary (0) / ORG1 (12750490) / ORG2 / ORG3.
Strict Object Mode **ON**, CSR flag **ON**. Baseline captured, restored, diff proven on six
dimensions. Full account:
[`2026-07-27-ts-security-columns-live-verification.md`](../verification/2026-07-27-ts-security-columns-live-verification.md).

**What made this round conclusive** where the second round was not: five controls held
*before* the test, so publication was the only remaining variable — the ORG1 session was
confirmed genuinely in ORG1, holding `ADMINISTRATION` **in ORG1**, having just written CSR
successfully on ORG1's own native table, having read the published table from ORG1, and
with the owning Org able to write to that same table.

| # | Question | Result |
|---|---|---|
| 1 | Can a tenant Org configure **usable** CSR on its **own native** table? | **YES.** `set --org ORG1` on `T4_PER_ORG` against `Demo Retail Group` applied and read back. The second round's failure here really was only the group-name artefact it was diagnosed as |
| 2 | Can a tenant Org configure CSR on a table **published into** it? | **NO.** `HTTP 500`, code **`10038`**, `FORBIDDEN`, `User does not have access to read/modify CSR for these tables`. Attributable to publication, per the controls above. Closes parent spec open item #5 |
| 3 | Does a group holding **only** column grants reach the table? | **YES**, both Table and Model, verified as a real non-admin user. With no object grant at all, `guest4` saw exactly the 3 granted columns. Confirms CLS is one step. Closes parent spec open item #1 |
| 4 | Does a table-level `NO_ACCESS` clear existing column grants? | **NO** — and it does not revoke the entitlement either. The Model drops out of search but still **opens by direct link with the granted columns**. An object-level deny is not a revoke. Platform gap, BL-142 |

**§2.1's second row is confirmed, and for a stronger reason than the design assumed.** CSR
is closed off for a published-in row by *two independent* mechanisms: an owning-Org rule
does not travel (round 3, data plane), and the tenant cannot define one either (this round,
API). Either alone would leave a workaround. `CSR_BLOCKED` is right, and `--allow-published`
is genuinely owning-Org-only scope, never a route to protecting a tenant.

**CLS in the tenant Org on the published object works**, so §2.2's "nothing works" cell
stays a real edge case rather than the normal case.

### Three defects found

1. **BLOCKER — `ts share export --org <tenant>` cannot see tenant-native objects.**
   `share_planning.py:75-79` resolves the object and lists its columns with the
   **default-Org** client; only `_fetch_permissions` is org-scoped. Both `metadata/search`
   probes resolve the same GUID fine with an ORG1-scoped client, so the wrong client is the
   whole bug. This blocks the skill's Step 4 baseline read for precisely the case the skill
   exists to serve. Pre-existing in the shipped `ts share` (PR #346).
   *Secondary:* `_resolve_object`'s typed fallback filters on `metadata_name == identifier`,
   which a GUID never matches, so GUID resolution rests entirely on the untyped probe.
2. **Code `10038` has no translation.** `explain_csr_error` covers `10023` (two forms) and
   `14502` (two forms). `10038` is a third code, reachable by the most predictable tenant
   mistake there is, and it surfaces raw.
3. **The `10023` translation is misleading for this case.** It advises "re-run with a
   profile or Org that holds the needed privilege" when the caller already holds
   `ADMINISTRATION` in that Org and no Org holds it, because the operation is structurally
   impossible. It also fires only once a rule exists — a tenant read of a published table
   with no rules returns a clean `[]`, so `10023` is state-dependent, which is exactly what
   misled the second round.

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
| 1 | Whether a tenant Org can be given usable CSR — native and published halves | **ANSWERED 2026-07-27.** Native: yes. Published-in: no (`10038 FORBIDDEN`). Closes parent spec open item #5 |
| 2 | Whether a group holding only column grants can reach the table | **ANSWERED 2026-07-27: yes**, Table and Model, as a real non-admin user. Closes parent spec open item #1 |
| 3 | Whether a table-level `NO_ACCESS` clears existing column grants | **ANSWERED 2026-07-27: no**, at ACL level. Closes the `ts share` carry-forward |
| 4 | Whether a CLS column grant still *functions* after a table-level `NO_ACCESS` | **ANSWERED 2026-07-27: yes.** Discovery is removed, the entitlement is not. Platform gap, BL-142 |
| 5 | Whether Strict Object Mode ever becomes API-readable | OPEN. If it does, §4's gate becomes a check and the skill drops a manual step |
| 6 | The `ts migrate audit` contract in §5.2 | Deferred to a backlog item against the migrate work |

Items 2 and 4 were settled together in one data-plane session on 2026-07-27, as real
non-admin users in Primary. Only item 5 remains, and nothing depends on it.
