# `ts share` and `ts-security-columns` — design

**Date:** 2026-07-26
**Status:** DESIGN — API surface live-verified on `nebula-damian-alias`
**Branch:** `feat/ts-security-design`

Two capabilities in the single-model multi-tenancy pattern: making objects visible to end
users, and controlling which columns each tenant sees. They are separate, and column
security has two mechanisms rather than one.

Programme context: `docs/multi-tenancy-platform-plan.md`.

---

## 1. Why two capabilities, not one

**Sharing is not part of publication.** It is needed whether or not anything was
published, and the same `shareMetadata` mechanism also carries column-level security.
Folding it into `ts-publish-orgs` would put a security operation inside a deployment
operation. `ts-publish-orgs` Step 12 therefore hands off rather than implementing.

**Column security is a decision layer, not a wrapper.** Two mechanisms exist with
materially different capabilities, and which one applies is dictated by publication state:

| | Column-level sharing (CLS) | Column security rules (CSR) |
|---|---|---|
| API | `security/metadata/share` | `security/column/rules/update` + `/fetch` |
| TML | **No.** Permissions live outside TML | **Yes**, a separate document (§2.4) |
| Works on published objects | Yes | Accepted and enforced, but Org-scoped: a tenant Org the object is published to stays unprotected (§2.7) |
| Declaration model | Enumerate every **visible** column per group | Declare only the **restricted** columns |
| Liveboard filter on a secured column | Liveboard **locks** | Stays interactive |
| Interacts with table-level share | Yes — a table share defeats it (§2.2) | No, independent axis (§2.5) |
| Availability | GA | Beta 10.12+, **feature-flagged off by default** |

---

## 2. Verified behaviour

Everything here was exercised live on 2026-07-26 against `T1/T2_PUBLISH` and their columns.
All test artefacts were removed; the cluster is back to baseline. Several items contradict
the published documentation.

### 2.1 `shareMetadata` accepts `LOGICAL_COLUMN`, and `message` is top-level

The spec lists supported types as Liveboards, Visualizations, Answers, Models, Views,
Connections and Collections. **`LOGICAL_COLUMN` is accepted and takes effect** despite being
absent from that list. Proven by sharing a column to a group with no prior access and
observing it appear, then reverting with `share_mode: NO_ACCESS`.

Separately, every published example nests `message` inside `notification`. The API rejects
that with `Variable "$message" of required type "String!" was not provided`. It must be
**top-level**, beside `notify_on_share`. This blocks object sharing as much as column
sharing, so it is the first thing any implementation hits.

```json
{"metadata_type": "LOGICAL_COLUMN",
 "metadata_identifiers": ["<column-guid>"],
 "permissions": [{"principal": {"type": "USER_GROUP", "identifier": "Analyst"},
                  "share_mode": "READ_ONLY"}],
 "message": "…",            <- top level, NOT inside notification
 "notify_on_share": false}
```

### 2.2 A table share grants every column

Sharing the **table** to a group granted that group access to all of its columns. So table
grants and column grants are not additive in a safe way: a table share silently defeats
column-level security. They must be treated as **mutually exclusive** per (org, table,
group). See §3.3.

### 2.3 Sharing to a non-existent group fails loudly

`code 13003`, `Principal object does not exist corresponding to the identifier X`. Good:
a missing group cannot silently produce an ungranted object. A client-side pre-check is
still worth having for a readable message, but it is not a safety net against silent damage.

### 2.4 CSR is dual-route — API **and** TML

CSR exports as a **separate TML document**, exactly the `column_alias` pattern. It requires
`export_associated: true` **and** `export_options.export_column_security_rules: true`
(Beta, 10.12+):

```json
{"column_security_rules": {
   "table": {"name": "T2_PUBLISH"},
   "rules": [{"column_name": "PROD_NM",
              "accessible_groups": {"group_name": ["Analyst"]}}]}}
```

Filename `<TABLE>_CSR.column_security_rules.tml`, `info.type` = `column_security_rules`.

**Round-trip verified:** importing a modified document with `create_new: false` added a
second rule, confirmed by reading back through the API. Two gotchas:

- The `table:` reference is **mandatory**. Omitting it fails with
  `Referenced table with name  not found` (`code 14502`).
- `clear_csr: true` alone is rejected; `column_security_rules: []` must accompany it,
  though the docs imply the flag is sufficient.

**Corrected 2026-07-26 against the canonical spec** (`get-rest-api-reference`, operations
`fetchColumnSecurityRules` and `updateColumnSecurityRules`). Four things this section got
wrong or missed; see
[`2026-07-26-ts-security-column-rules-cli-design.md`](2026-07-26-ts-security-column-rules-cli-design.md) §1
for the detail:

- CSR is **not** purely declarative. Each column rule's `group_access` names an
  `operation`: `ADD`, `REMOVE` or `REPLACE`. The API is both incremental and declarative,
  which is what makes an idempotent `set` possible.
- `update` takes **one table per call** (`identifier` is a scalar). The "all or none"
  rollback is per call, not per run, so multi-table work is a loop the caller owns.
- The `clear_csr` rejection above is **schema validation, not a bug**:
  `column_security_rules` is a required field. It will not be "fixed", so always emit both.
- Per-column **`is_unsecured: true`** exists, distinct from whole-table `clear_csr`.
  Unsecuring one column does not require a read-modify-write of the table.

### 2.5 CSR is independent of the share ACL

With CSR active on two columns, the table's grant list was unchanged. CSR governs column
visibility on a separate axis from sharing, which is why it does not collide with liveboard
filters the way CLS does.

### 2.6 CSR is feature-flagged

Before enablement every CSR call returned `403 code 10023`,
`Column Security rule feature is disabled`. Any skill must detect this and say so, rather
than surfacing a bare 403.

### 2.7 CSR on a published object is accepted, but Org-scoped -- supersedes the earlier "No"

Expected, per this section's original wording (and §1's comparison table): the platform
refuses to define CSR on a published object. Observed instead, live-verified with real
non-admin user sessions on `nebula-damian-alias`: a CSR rule restricting a column to a group
is **accepted** (`HTTP 204`) on a table published from Primary into tenant Org ORG1, and is
**enforced in Primary**, hiding the column from an out-of-group user on both the Table and
the Model -- but the same column stayed fully **visible** in ORG1. A CSR rule is scoped to
the Org it was defined in and does not travel with publication.

This supersedes the flat "No" this document and `docs/multi-tenancy-platform-plan.md` §4.3
previously stated. The operating consequence: configure CSR per Org, against that Org's own
groups, because groups are per-Org and a rule defined against one Org's group names cannot
reach across the Org boundary. Full evidence:
`docs/superpowers/verification/2026-07-26-ts-security-column-rules-live-verification.md` §15.

---

## 3. `ts share`

### Surface

```
ts share export  <guid> [<guid> ...] [--org O ...] --profile P
ts share resolve --org O [--org O] --source uniform|file|db [--csv F | --table T] --profile P
ts share apply   --input grants.json [--dry-run] --profile P
ts share status  <guid> [--org O ...] --profile P
```

Mirrors the `ts publish` pipeline and the `ts alias` source conventions, so the three read
the same way.

### The grant model

The unit is **(org, object, group, share_mode)**, with an optional column. One manifest
covers both granularities:

```sql
TS_SHARE_GRANTS (
    org_name        VARCHAR NOT NULL,
    object_identifier VARCHAR NOT NULL,
    object_type     VARCHAR NOT NULL,   -- LOGICAL_TABLE | LIVEBOARD | ANSWER
    column_name     VARCHAR,            -- blank = object grant; set = column grant
    group_name      VARCHAR NOT NULL,
    share_mode      VARCHAR NOT NULL,   -- READ_ONLY | MODIFY | NO_ACCESS
    PRIMARY KEY (org_name, object_identifier, column_name, group_name)
)
```

`--source uniform` applies the same grants to every target Org, which is the common case
given the pattern is the same groups in every Org. `file`/`db` express per-Org variation
without enumerating identical rows per tenant.

### 3.3 Rules the tool enforces

**Table and column grants are mutually exclusive per (org, table, group).** Following §2.2,
a manifest containing both for the same triple is **refused**, because the table grant
silently defeats the column grants. This turns the operating rule into something checkable:

| Table | Grant at |
|---|---|
| No secured columns | table level |
| Has secured columns | column level only, never both |

**Groups are per-Org and must exist.** `resolve` fails at plan time naming the Org and
group, rather than letting the run hit `13003` mid-apply.

**The ALL group is the default for published models, and the most dangerous default on a
secured table.** The same exclusivity rule applies: on a table with secured columns, ALL
receives column grants, never a table grant.

**Never infer the audience.** Sharing decides who sees tenant data, so principals and share
mode are always the operator's input, never a default.

---

## 4. `ts-security-columns`

The skill's job is choosing the mechanism and explaining the trade-off, not calling one API.

```
1  Authenticate
2  Select the Table(s)
3  Detect publication state + CSR feature availability      auto
4  Choose the mechanism (or accept the forced one)          you confirm
5  Source the column→group map                              you choose
6  Review the grant/rule matrix                             you confirm
7  Dry-run                                                  auto
8  Apply                                                    you confirm
9  Verify (fetch back and diff)                             auto
```

**Step 3 is the interesting one.** Published objects force CLS. Unpublished objects prefer
CSR, but only if the feature is enabled (§2.6); otherwise CLS is the only option and the
skill should say why.

**Steps 5 to 8 mirror `ts alias` exactly for the CSR path**, because CSR shares the
`column_alias` shape: a sibling TML document exported behind a flag. The pipeline is
`export → build → import` with a CSV or DB source, and the same `--init-table` idiom.

### Where the column→group map comes from

Not hand-authored. From the column-usage map `ts migrate audit` already computes: columns a
tenant actually uses get granted, unused ones are withheld. See
`docs/multi-tenancy-platform-plan.md` §4.1 — one discovery layer, not three.

---

## 5. Migration additions

### 5.1 `CSR_BLOCKER`

CSR cannot be defined on published objects, so a tenant whose source Tables carry CSR cannot
have that configuration carried onto the published Model. A third audit status alongside
`GAP_BLOCKER` and `SET_BLOCKER`; `apply` refuses by default.

### 5.2 `--csr map-to-cls`, opt-in only

A CSR-to-CLS mapping exists but is **not** the 1:1 it appears to be, for three reasons:

**It is asymmetric.** CSR declares only restricted columns; CLS requires enumerating every
visible column per group. Three CSR rules on a 40-column table become roughly 40 × G
grants — the permission-shaped version of the object explosion the pattern exists to avoid.

**It can break working liveboards.** Under CSR a liveboard whose filter sits on a secured
column stays interactive; under CLS it locks. This is a functional regression, not a config
translation.

**It is a security transform.** Getting it wrong exposes data, which warrants a reviewable
artefact and an explicit opt-in rather than a default.

The flag therefore emits a reviewable grant manifest; it does not apply anything. The audit
reports the expansion count and the list of liveboards that would lock, so the choice is
informed per tenant.

### 5.3 Preserve the original CSR TML

Because CSR round-trips through TML (§2.4), the migration should write the exported
`column_security_rules` document into the plan directory. When CSR lands on published
objects, restoring a tenant's original configuration is then a single import rather than
reconstruction from the CLS grants.

The tenant path across the transition:

```
CSR (today, unpublished)
  └─► CLS (through the transition, if mapped)
        └─► CSR (restored from the preserved TML, once supported on published objects)
```

### 5.4 The per-tenant decision

Both Sets support and CSR-on-published are expected in the same 3-to-6-month window. For a
tenant carrying CSR, waiting may beat mapping. The audit's expansion count and at-risk
liveboard count are what should decide that per tenant, not a blanket rule.

---

## 6. Open items

| # | Item | Status |
|---|---|---|
| 1 | Can a group holding only column grants reach the table at all, or does it also need a table-level grant of some kind? | OPEN. §2.5 shows CSR is independent of the ACL, but the CLS equivalent is untested |
| 2 | Does strict object security have to be enabled for CLS to behave as documented? | **ANSWERED: yes.** Strict Object Mode must be on for column-level sharing to apply to a Model. It cannot be read through any available REST API, and CLS grants applied without it succeed silently and do nothing. `ts share resolve` now warns whenever a plan carries column grants. Confirmed by the repo owner. |
| 3 | Does CSR TML survive a lift-and-shift into a different Org, given the `table:` reference is by name? | **ANSWERED: only where a same-named table exists.** Importing a CSR document into an Org that lacks the table fails with error code 14502 and a message naming the table, so the reference resolves per-Org by name. Verified live. |
| 4 | Behaviour of `share_mode: NO_ACCESS` on a column that was never granted | OPEN, likely a harmless no-op |
| 5 | Whether a tenant Org can be given *usable* CSR at all, given that group names do not resolve across the Org boundary (a rule naming a Primary group is meaningless in a tenant Org) | OPEN. §2.7 settles that a rule set in the owning Org does not travel; still unverified is whether a rule configured directly in a tenant Org, against that Org's own groups, behaves as documented there |

None block building `ts share`, which rests only on verified behaviour.

---

## 7. Build order

1. **`ts share` CLI** — object + column grants, the manifest, the exclusivity check.
   Unblocks `ts-publish-orgs` Step 12 immediately.
2. **`ts security column-rules`**, the CSR path, both routes. Designed in
   [`2026-07-26-ts-security-column-rules-cli-design.md`](2026-07-26-ts-security-column-rules-cli-design.md):
   `get` / `export` read, `resolve` plans, `apply` executes over the API, and
   `build` / `import` executes over TML. Scoped wider than the "API path" named here
   because the two routes share one plan, and §5.3's TML preservation needs the export.
3. **`ts-security-columns` skill** — the decision layer over both, CSR path mirroring
   `ts alias`.
4. **Migration additions** — `CSR_BLOCKER`, the opt-in mapping, CSR TML preservation.

Steps 1 and 2 are independent and both useful standalone.
