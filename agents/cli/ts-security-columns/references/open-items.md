# ts-security-columns — Open Items

Behaviour that is unverified, or verified and worth recording because it contradicts the
published documentation. Everything here was checked against `nebula-damian-alias`
(Orgs Primary / ORG1 / ORG2 / ORG3, CSR feature flag ON, Strict Object Mode ON) unless
noted.

Full detail lives in
[`docs/superpowers/verification/2026-07-27-ts-security-columns-live-verification.md`](../../../../docs/superpowers/verification/2026-07-27-ts-security-columns-live-verification.md)
and the two earlier rounds it cites.

---

## #1 — Can a tenant Org be given usable CSR? — VERIFIED 2026-07-27

**Answer: it depends on ownership, and the two halves differ.**

| Case | Result |
|---|---|
| Object **native** to the tenant Org | **Yes.** `set --org ORG1` on `T4_PER_ORG` against `Demo Retail Group` applied and read back normally |
| Object **published into** the tenant Org | **No.** `HTTP 500`, code `10038`, `FORBIDDEN`, `User does not have access to read/modify CSR for these tables` |

Attributable rather than suggestive because five controls held first: the session was
confirmed genuinely in ORG1 (`current_org: {id: 12750490}`), holding `ADMINISTRATION`
*in ORG1*, having just written CSR successfully on ORG1's own native table, having read
the published table from ORG1, and with the owning Org still able to write to that same
table. Publication was the only remaining variable.

Closes parent spec open item #5. Together with the round-3 finding that an owning-Org rule
does not travel with publication, CSR is closed off for a tenant on a published object by
**two independent** mechanisms.

---

## #2 — Does a group holding ONLY column grants reach the object? — VERIFIED 2026-07-27

**Answer: yes**, on both Table and Model, confirmed at the data plane as real non-admin
users.

With **no** object grant at all, `guest4` (group `Consumer`, three column grants) opened
`T2_PUBLISH` and `T2_PUBLISH_MODEL` and saw exactly `PROD_NM`, `PROD_CAT_L1`, `AMOUNT` —
`UNIT_PRICE_AMT` and the other 21 were absent. `guest1` (object grant, group `Analyst`)
saw all 25 as the control.

Closes parent spec open item #1 and confirms the design's step-count asymmetry: **CLS is
one step**, CSR is two. Strict Object Mode (ON here) behaved as documented on the Model.

---

## #3 — Does an object-level `NO_ACCESS` revoke a column grant? — VERIFIED 2026-07-27 (platform defect, BL-142)

**Answer: no. It removes discovery, not the entitlement.**

With three column grants left in place, a table-level `NO_ACCESS` on `Consumer`:

- removed the **Model** from search, but it **still opened by direct link**, still showing
  the three granted columns
- left the **Table** reachable via the Data page throughout
- left all three column ACL rows intact on both objects

The Table/Model difference is only which discovery surface each uses. The entitlement is
identical on both.

**Operating rule for the skill:** an object-level `NO_ACCESS` is **not a revoke** when
column grants exist. Revoke at column level. See SKILL.md → Revoking.

Filed as **BL-142** — a partial deny looks effective to the administrator while remaining
live for anyone with a direct link, a bookmark, or an Answer built on the object.

---

## #4 — Does a CLS grant behave identically with Strict Object Mode OFF? — UNVERIFIABLE HERE

**Status: OPEN, and not resolvable on this cluster.** Strict Object Mode is ON, and
toggling a cluster-wide setting to test the negative case is not a reasonable thing to do
on a shared instance.

What is established: the setting cannot be read through any REST API, and the repo owner
confirmed it is ON here. The documented behaviour when OFF is that column grants are
accepted and applied without error and never take effect.

**Why the skill does not depend on resolving it.** The Step 5 gate is a hard stop on an
unconfirmed answer either way, so the skill is correct whether or not the negative case is
ever observed. If ThoughtSpot ever exposes the setting through an API, the gate becomes a
check and the skill drops a manual step.

---

## #5 — `column-rules get` returns a bare `[]` for a resolved table with no rules — NOTED 2026-07-27

Not a defect, a shape note. The earlier record documented
`[{"table_guid": ..., "column_security_rules": []}]` for a table with no rules; this build
returns a bare `[]`.

A genuinely unresolvable identifier still errors loudly (`13003`,
`No table found with name: ...`), so `[]` is not masking a resolution failure. Worth
re-checking on a newer build before anything is built on the response shape.

---

## #6 — Does `ts share status` distinguish a failed revoke? — OPEN (repo follow-up)

Given #3, the combination "no object grant + surviving column grants" is now a
recognisable signature of a revoke that did not do what its operator intended.

`ts share status` currently lists those column rows as unremarkable. It could flag them.
Not blocking the skill — SKILL.md states the rule in the Revoking section — but it is the
place a validator-style guard would belong. Tracked in BL-142's follow-up list.
