# ts-publish-orgs — Open Items

Behaviour that is unverified, or verified and worth recording because it contradicts the
published documentation. Everything here was checked against `nebula-damian-alias`
(Orgs enabled: Primary + ORG1/ORG2/ORG3, Snowflake connection `APJ`) unless noted.

Full detail, including reproductions, lives in
[`docs/superpowers/specs/2026-07-25-ts-publish-orgs-design.md`](../../../../docs/superpowers/specs/2026-07-25-ts-publish-orgs-design.md) §2.5.

---

## #1 — Substitution inside a target Org — DEFERRED 2026-07-26

**Question.** Does a target Org's TML export show the substituted value, and does a user
*inside* that Org query the right data?

**Status:** DEFERRED to a follow-up. Not blocking: everything up to the Org boundary is
verified, including that the object is published (`metadata_header.orgIds`), the Connection
is granted, and the source Org still resolves correctly.

**Why deferred.** Verifying it needs an org-scoped token. `POST /api/rest/2.0/auth/session/org`
returns 404 on this build, and the org-scoped token auth added on `feat/ts-org-migrate`
(`client.py`, optional `org_id`) has not merged. Once it lands, this becomes:

```bash
# with an ORG3-scoped token
ts tml export {table_guid} --profile {org3_profile}
# expect: db/schema showing the ORG3 values, not ${tokens} and not the Primary values
```

**What is verified meanwhile.** The Primary Org query path, end to end: parameterize →
publish → `searchdata` returns rows. The failure mode when a variable is unset is also
verified and is loud (`Object '...' does not exist`), so a wrong substitution would not be
silent.

---

## #2 — `parameterize-fields` throws on a Falcon-backed table — VERIFIED 2026-07-26 (platform defect)

Parameterizing a Logical Table with no connection returns HTTP 500 with a Java stack trace:

```
code 10000
java.lang.NullPointerException
  at ...LogicalTableParameterizationHandler.parameterize(LogicalTableParameterizationHandler.java:84)
```

The docs state that default system tables cannot be parameterized, but the code does not
guard for it. The call is atomic in effect: the Table was unmodified afterwards.

**Handled in the skill.** `ts publish export` marks such clusters `parameterizable: false`,
`selectable_clusters` never returns them, and the command warns naming the tables. Reported
to ThoughtSpot (`~/Dev/ts-publish-orgs-issue-2026-07-26.md`, issue 2).

---

## #3 — Owner-Org validation is missing platform-side — VERIFIED 2026-07-26 (platform defect)

Parameterizing an object whose owner Org has no value for the variable breaks that Org
silently. Publish validation covers **target** Orgs only.

**Handled in the skill.** `ts publish resolve` always includes the owner Org and pins it to
the field's current value, never a pattern expansion. Reported (issue 1).

Worth knowing when extending the tooling: this bit twice, days apart, through two different
entry points, because a second code path had not been updated. Any new entry point into
parameterization must go through `resolve`.

---

## #4 — Cohort scope is wider than documented — VERIFIED 2026-07-26 (platform defect)

An **unused** cohort column on a Model blocks publishing the Model and every Answer and
Liveboard on it. The Table beneath the Model publishes fine.

**Handled in the skill.** `ts publish export` reports `cohort_columns`, checking every object
in the closure rather than just the roots, because the column is owned by the Model.
Reported (issue 7).

---

## #5 — Publish/unpublish cascade asymmetry — VERIFIED 2026-07-26 (platform defect)

Publish cascades to dependencies unconditionally; unpublish only with
`include_dependencies: true`. Both return a bare `204`, so the caller cannot see what
changed. Siblings sharing a Model deadlock on `code 13152`.

**Handled in the skill.** `unpush` defaults to retracting dependencies, `13152` is translated
into the working retraction order, and the Rollback section documents the sequence.
Reported (issue 6).

---

## #6 — Connection-property variables are not discovered — OPEN

`ts publish export` clusters Table fields only. `CONNECTION_PROPERTY` variables
(`accountName`, `warehouse`, `role`, `user`, `password`) and `CONNECTION_CONFIG`
(`impersonate_user`) are not planned, though `ts metadata parameterize --type CONNECTION`
exists as a primitive.

**Impact.** Tenants split by *schema* are fully covered. Tenants in different Snowflake
accounts, or needing a per-Org warehouse identity, are not.

**Intended design when built.** Two tiers, enforced rather than trusted:

| Tier | Fields | Handling |
|---|---|---|
| Non-secret | `databaseName`, `schemaName`, `tableName`, `warehouse`, `role`, `accountName`, `impersonate_user` | Config file or governance table. Reviewable, diffable |
| Secret | `user`, `password` | **Refused** from any config source. Created `is_sensitive: true`; the admin sets the value from their own terminal |

`impersonate_user` is the preferred identity mechanism: the connection authenticates once
with a service account holding impersonate rights, so no per-user password exists anywhere.
Spec-read only; not yet exercised live.

---

## #7 — `--source db` is Snowflake-only — OPEN (BL-136)

Every `--source db` path in the repo assumes Snowflake. Databricks users have the CSV path
only. Tracked as [BL-136](../../../../docs/backlog.md); the two platforms share no cursor
shape, so the abstraction belongs at "give me rows".

---

## #8 — Sharing is a separate capability, not yet built — OPEN (by design)

Publication makes an object present in a target Org; it is visible only to that Org's
administrators until shared. This skill stops at that boundary on purpose.

Sharing is deliberately **not** part of publication: it is needed whether or not anything
was published, and the same `shareMetadata` mechanism also carries column-level security.
Folding it in would put a security operation inside a deployment operation.

Step 12 hands off. Until a `ts-security-sharing` skill exists, the user is pointed at
`POST /api/rest/2.0/security/metadata/share`.

**To verify when that skill is built.** The `shareMetadata` spec lists its supported types
as Liveboards, Visualizations, Answers, Models, Views, Connections and Collections, and does
**not** list `LOGICAL_COLUMN`. Column-level sharing is known to work in practice, so either
the list is incomplete or columns take a different shape. Confirm live before designing a
CLI around it.

---
