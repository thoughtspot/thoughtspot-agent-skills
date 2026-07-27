# Choosing between CSR and CLS — the decision, and the evidence

Reference for [`../SKILL.md`](../SKILL.md) Step 6. Everything here is live-verified on
`nebula-damian-alias`; each row names the round that settled it.

Design: [`2026-07-27-ts-security-columns-skill-design.md`](../../../../docs/superpowers/specs/2026-07-27-ts-security-columns-skill-design.md).
Evidence: [`2026-07-27-ts-security-columns-live-verification.md`](../../../../docs/superpowers/verification/2026-07-27-ts-security-columns-live-verification.md).

---

## 1. The axis: audience, not object

Publication state is a property of the **object**, and it does not select a mechanism. The
question that does is a property of the **audience**.

A published table viewed from its **owning** Org is a *native* row and CSR works there.
The same table viewed from a **tenant** Org is a *published-in* row and only CLS works.
One object, two rows, two mechanisms, both correct at the same time.

| Audience Org's relationship to the object | Mechanism | The precondition that can silently defeat it |
|---|---|---|
| **Native** — that Org owns the object | **CSR** preferred; CLS possible | CSR feature flag. And the object must already be shared, or CSR protects something nobody can open |
| **Published in** — the object lives in another Org | **CLS only** | Strict Object Mode. Unreadable by any API — human gate |

### Why CSR is preferred where it is available

- Declares only the **restricted** columns. CLS requires enumerating every **visible**
  column per group, so three restricted columns on a 40-column table become ~40 × G grants
- A Liveboard whose filter sits on a secured column **stays interactive** under CSR; under
  CLS it **locks**
- Composes with a table-level share instead of being defeated by one

---

## 2. The two mechanisms are not symmetric

| | CLS (`ts share`) | CSR (`ts security column-rules`) |
|---|---|---|
| API | `security/metadata/share` | `security/column/rules/update` + `/fetch` |
| Steps | **One.** The grant IS the access and the restriction | **Two.** Share the object, then filter columns within that access |
| Declares | every visible column per group | only the restricted columns |
| TML | no — permissions live outside TML | yes, a sibling `column_security_rules` document |
| Liveboard filter on a secured column | locks | stays interactive |
| Table/column exclusivity rule | **needed** — same mechanism at two granularities, so the broader defeats the narrower | not needed — different axis entirely |
| Usable by a tenant Org on a published object | **yes** | **no** — `10038 FORBIDDEN` |
| Precondition | Strict Object Mode (unreadable by any API) | feature flag, Beta 10.12+ |
| Availability | GA | Beta, flagged off by default |

**The step-count difference is the root of the rest.** Because CLS is one mechanism at two
granularities, a table grant conveys every column and silently defeats a column grant for
the same (Org, table, group) — hence the exclusivity rule. CSR never decides access in the
first place, so it composes cleanly and needs no such rule.

*Live-verified (round 4):* with **no** object grant at all, a user in a group holding three
column grants opened both the Table and the Model and saw exactly those three columns.
CLS really is one step.

---

## 3. Why CSR cannot serve a tenant on a published object

Two **independent** mechanisms close the door. Either alone would leave a workaround.

| Fact | Round |
|---|---|
| A CSR rule defined in the **owning** Org is enforced only there and does **not travel** with publication — the tenant keeps seeing the column, with no error and no warning in either Org | 3, data plane |
| The tenant Org **cannot define** a rule either: `HTTP 500`, code `10038`, `FORBIDDEN`, `User does not have access to read/modify CSR for these tables` | 4, API |

The `10038` result is attributable rather than suggestive because five controls held
before it: the session was confirmed genuinely in the tenant Org, holding `ADMINISTRATION`
*there*; the same session had just set CSR successfully on that Org's **own native table**;
it had read the published table from that Org; and the owning Org could still write to the
same table. The only remaining variable was publication.

**So `CSR_BLOCKED` is correct as a default**, and `--allow-published` means "owning-Org
scope is genuinely what I want" — never "reach the tenant".

---

## 4. Failure modes that produce a false belief

Each of these succeeds, warns about nothing, and leaves data exposed or an operator
misinformed. They are the reason this skill exists rather than a wrapper.

| Failure | What actually happens |
|---|---|
| **CSR on a published object** | Accepted (`204`), enforced in the owning Org, **ignored in every tenant Org**. Secure a column, publish, believe every tenant is protected — none are |
| **CLS without Strict Object Mode** | Grants accepted and applied without error. They never take effect. Reads back identically to a working grant |
| **Object-level `NO_ACCESS` as a revoke** | Removes the object from **search** only. The entitlement survives: it still opens by direct link with the granted columns. Platform gap, BL-142 |
| **Configuring once in Primary** | Groups are per-Org and CSR does not propagate. N tenant Orgs is N configurations |
| **Table grant alongside column grants** | The table grant conveys every column and defeats the column grants. Refused by `ts share`, but only if both are in the same manifest |
| **Trusting a clean tenant CSR read** | On a published object a tenant `get` returns `[]` while no rule exists, `10023` once one does. `[]` does not mean the tenant can manage CSR |

---

## 5. Detection cheatsheet

| Question | How | Trap |
|---|---|---|
| Native or published-in? | `ts publish status {guid}` | A **failed** read is not "unpublished". Block the row |
| CSR feature on? | first CSR read per Org | `10023` is overloaded — disabled-form vs access-form, distinguish on message text |
| Can this tenant manage CSR? | infer from publication state | **Not probeable by reading.** See the last row of §4 |
| Strict Object Mode? | **human only** | No API exposes it, at all |
| Does the audience hold object access? | `ts share status {guid} --columns --org {org}` | Needed for CSR rows; irrelevant for CLS rows |
| Do the groups exist here? | `ts share resolve` group pre-check | Groups are per-Org |

---

## 6. What the user's own token will not tell you

`ts auth whoami` returns a **per-token** view. A Primary-scoped token reports
`orgs: [{id: 0, name: Primary}]` and `org_privileges: {"0": [...]}` even for a user who is
a full administrator in four Orgs — the tenant-scoped token for the same user reports
`ADMINISTRATION` in that tenant.

Never conclude "this user has no access to Org X" from a token scoped to Org Y. It cost
one verification round to learn that.
