# RLS on a published object — does it enforce in the tenant Org?

**Date:** 2026-07-27
**Cluster:** `nebula-damian-alias` (test cluster, authorised by the repo owner)
**Answers:** open question 4 in
[`2026-07-15-ts-org-migrate-design.md`](../specs/2026-07-15-ts-org-migrate-design.md)
**Baseline:** captured, restored, diff proven (§5).

## The question, and the answer

> Does a row-level security rule defined on a Model/Table in the **Primary** Org enforce
> for a real non-admin user in an Org the object is **published** to?

**Yes — verified with a real non-admin user against a control.**

This was the highest-stakes unverified assumption in the programme: if RLS did not travel,
every tenant on the single published model would see every other tenant's rows. The prior
was genuinely mixed, because **CSR is Org-scoped and does *not* travel with publication**
(verified 2026-07-26/27), so "defined in Primary" is on its own not sufficient grounds.

RLS turns out to behave differently from CSR, and the structural reason is visible in the
object: an RLS rule lives **inside the Table TML** as part of the object definition, where
a Column Security Rule is a **separate, Org-scoped security object** attached to it.
Publication does not copy the object — the same GUID is made visible in the tenant Org — so
anything carried *in* the definition comes with it.

---

## 1. Method — why a control arm was mandatory

A tenant user seeing **no rows** is ambiguous: it means "RLS is working" or "this user
cannot see the object at all". On a multi-Org cluster the second is the *default* state,
and reading it as the first is exactly the false negative that already cost this programme
a retracted conclusion once (see the ORG1 caution in the CSR verification).

So the fixture had two arms, identical but for the rule:

| Table | RLS rule | Published to | Shared with | Expected for `guest4` |
|---|---|---|---|---|
| `T1_PUBLISH` | `[T1_PUBLISH_1::PROD_NM] = ts_username` | ORG1 | `RLS_TEST` group | **0 rows** |
| `T3_PUBLISH` | *none* — control | ORG1 | `RLS_TEST` group | **rows visible** |

`guest4` is a real non-admin user in ORG1, added to a purpose-made `RLS_TEST` group.
**An admin session would have proved nothing** — admins bypass RLS, and an owning-Org check
passes even when tenant-side behaviour is wrong. That is precisely how the CSR trap stayed
hidden until a real tenant user looked.

The rule `PROD_NM = ts_username` can never match (no product is named `guest4`), so it is a
total row filter — the strongest possible signal.

**Result:** the control showed rows; the RLS table showed none. Confirmed by the repo owner
in an ORG1 session as `guest4`.

---

## 2. What this does NOT establish

Only that RLS **carries and enforces**. It does not establish that RLS can be made
**Org-aware** — that each tenant sees its own rows rather than none. That requires a
predicate keyed on the querying user's Org, and §3 shows the mechanism for it is not
available on this cluster.

For the migration routine, the distinction matters: enforcement carrying means published
RLS is not silently bypassed at cutover, which is the *safety* question. Org-awareness is
the *function* question, and it remains open.

---

## 3. `ts_orgid` does not exist; ABAC formula variables are unavailable here

The natural predicate for single-model tenancy — filter by the querying user's Org — has no
system variable on this build:

```
[T_1::PROD_NM] = ts_orgid
  → ERROR: Search did not find "ts_orgid" in your data or metadata.
```

The documented system variables are only `ts_username` and `ts_groups`. The documented
Org-aware route is `ts_var(varName)` against an **ABAC formula variable**, whose values can
be set per Org — but `ts_var(apj_schema)` is rejected at parse time, and
`template/variables/create` accepts none of `FORMULA`, `RLS`, `USER_PARAMETER`. The only
variable class present is `TABLE_MAPPING`, which is *publishing parameterization* — a
different mechanism that happens to share an endpoint.

Filed as **BL-145**. Two routes remain: a `ts_groups` predicate against a per-Org group
whose name matches a tenant-key column value, or enabling ABAC via RLS on the cluster.

---

## 4. Defect found: a column-less RLS expression imports `OK` and WIPES existing rules

Filed as **BL-144** (Tier 1). Three expressions applied in sequence to one table:

| # | `expr` | Import | Rule afterwards |
|---|---|---|---|
| 1 | `[T_1::PROD_NM] = ts_username` | `OK` | present, correct |
| 2 | `[T_1::PROD_NM] = ts_orgid` | `ERROR` — unknown keyword | unchanged (rule 1 intact) |
| 3 | `ts_orgid = 0` | **`OK`** | **GONE — rule 1 destroyed** |

Row 2 is the control that makes this a defect rather than a syntax complaint: the *same*
unknown keyword errors loudly when a column reference is present and passes silently when
it is not. The rule is discarded before keyword validation, and the caller is told the
import succeeded.

**The failure is silent in the direction that removes security.** An operator believes RLS
is applied; the table is unfiltered; and whatever rule was protecting it is gone.

**Consequence for `ts migrate apply`:** any code path writing `rls_rules` must **read back
and assert the rule survived**, never trusting `status_code: OK`. Relevant wherever the
routine lifts tables carrying RLS.

### Incidental: TML normalisation of `rls_rules`

The importer rewrites what it is given — worth knowing when diffing:

| Field | Submitted | Returned on re-export |
|---|---|---|
| `table_paths[].id` | `T_1` | `T1_PUBLISH_1` — alias renamed |
| `table_paths[].column` | `"[PROD_NM]"` | `["PROD_NM"]` — string becomes a list |

Expressions are rewritten to match the new alias, so a naive TML round-trip comparison
reports a spurious diff.

---

## 5. Baseline restored

| Dimension | Baseline | Final |
|---|---|---|
| `T1_PUBLISH` `rls_rules` | absent | absent |
| `T1_PUBLISH` / `T3_PUBLISH` publication | `[]` | `[]` |
| `schemaName` parameterization | static `ALIAS_TESTS` | restored (HTTP 204) |
| Variables `apj_schema`, `apj_schema_2` | absent | deleted |
| ORG1 groups | Administrator, All, Demo Retail Group | identical (`RLS_TEST` deleted) |
| ORG1 owned Tables | 7 | 7 |
| ORG1/2/3 connections | `APJ_ORG*` | identical |

### Incidental: `ts publish rollback` is not connection-reference-counted

Rolling back one of two objects published to the same Org over the same connection fails:

```
Operation Unsuccessful. Following objects have dependents present:
{"12750490":["5e7e34e2-…"]}          ← the APJ connection
```

The rollback record retracts the connection grant alongside its object, without checking
whether another published object still needs it. Teardown must unpublish **all** objects
sharing a connection before the connection itself — the same ordering constraint as
connection deletion. Worth a `ts publish` fix; not filed yet.
