---
name: ts-security-columns
description: Restrict which columns a group can see on a ThoughtSpot Table or Model, choosing between the two mechanisms — Column Security Rules (CSR) and column-level sharing (CLS) — per Org, and explaining the trade-off. Use when hiding columns from a tenant or an audience, securing sensitive fields, or deciding which column-security mechanism applies to a published object. Drives the `ts share` and `ts security column-rules` pipelines.
---

# ThoughtSpot: Column Security

ThoughtSpot has **two** column-security mechanisms, not one. They are not two flavours of
the same thing: they sit on different axes, have different declaration models, and one of
them silently does nothing if a cluster setting is off.

This skill's job is **choosing the mechanism and explaining the trade-off**, then driving
whichever pipeline that choice implies. It is a decision layer over `ts share` (CLS) and
`ts security column-rules` (CSR).

**The thing to understand before starting:** the mechanism is not selected by the object.
It is selected by the **audience**. "Is this table published?" does not answer the
question — the same table can need CSR for one Org's users and CLS for another's, at the
same time. Step 3 therefore asks who you are protecting *before* Step 4 looks at anything.

Ask one question at a time for **dependent** decisions. Batch **independent** questions
into a single prompt to cut round-trips.

---

## References

| File | Purpose |
|---|---|
| [references/mechanism-decision.md](references/mechanism-decision.md) | The decision table, the evidence behind each row, and the failure modes |
| [references/open-items.md](references/open-items.md) | Unverified behaviour and its status |
| [tools/ts-cli/README.md](../../../tools/ts-cli/README.md) (`ts share`, `ts security column-rules`) | Full flag reference |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config, token persistence |
| [../ts-publish-orgs/SKILL.md](../ts-publish-orgs/SKILL.md) | Publishing — Step 12 hands off to this skill |
| [ts-profile-snowflake (Claude Code)](../../claude/ts-profile-snowflake/SKILL.md) | Snowflake profile — needed only for `--source db` |

---

## Prerequisites

- `ts` CLI installed and on PATH, version **0.110.0+**
- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- Privileges in **every Org you intend to configure**: `ADMINISTRATION`, or
  `DATAMANAGEMENT` (RBAC disabled), or `CAN_MANAGE_WORKSHEET_VIEWS_TABLES` (RBAC enabled).
  Privileges are per-Org — holding them in Primary says nothing about a tenant Org
- For the **CSR** path: Column Security Rules are **Beta, 10.12.0.cl+, feature-flagged off
  by default**. Step 4 detects this
- For the **CLS** path: the cluster must be in **Strict Object Mode**. No API exposes this.
  Step 5 is a hard confirmation gate for exactly that reason
- Optional: Snowflake profile (`/ts-profile-snowflake`) — only for `--source db`

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-security-columns** — restrict which columns each audience can see, choosing between
column security rules (CSR) and column-level sharing (CLS) per Org.

Steps:
  1.  Authenticate ..................................... auto
  2.  Select the Table(s) / Model(s) ................... you choose
  3.  Name the audience: whose users, which groups ..... you choose
  4.  Detect per (Org, object) ......................... auto
  5.  Strict Object Mode gate ........................... you confirm (hard stop)
  6.  Review the mechanism matrix ...................... you confirm
  7.  Source the column→group map, per Org ............. you choose
  8.  Review the grant / rule matrix ................... you confirm
  9.  Dry-run .......................................... auto
 10.  Apply — object access first, then columns ........ you confirm (checkpoint)
 11.  Verify (read back and diff) ...................... auto

Confirmation required: Steps 2, 3, 5, 6, 7, 8, and the checkpoint in Step 10
Auto-executed: Steps 1, 4, 9, 11

Note: the mechanism is chosen per (Org, object), not per object. The same table can
legitimately be CSR in one Org and CLS in another — that is normal, not a conflict.

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Step 1 — Authenticate

Read `~/.claude/thoughtspot-profiles.json`. If missing or empty, prompt the user to run
`/ts-profile-thoughtspot` first. If multiple profiles exist, ask which to use.

```bash
ts auth whoami --profile "{profile_name}"
```

Record `current_org` — it is the Org every un-`--org`'d command below will act in.

**Do not read `orgs` or `org_privileges` from this response as the user's reach.** Both
are a *per-token* view: a Primary-scoped token reports `orgs: [{id: 0, name: Primary}]`
even for a user who is a full administrator in four Orgs. Per-Org privilege is confirmed
in Step 4, per Org, or not at all.

Save `{profile_name}`.

---

## Step 2 — Select the Object(s)

Ask how the user wants to choose:

```
Which Table(s) or Model(s) hold the columns to secure?

  1  Search by name/pattern
  2  I already have the GUID(s)

Enter 1 or 2:
```

For search, show a numbered list with `{name}` — `{guid}` — `{owner}` — `{modified}`:

```bash
ts metadata search --type LOGICAL_TABLE --name "%{pattern}%" --profile "{profile_name}"
```

Save as `{objects}`.

**Securing a Model does not secure its Table, and vice versa.** They carry separate
logical columns with separate GUIDs. If both are reachable by the audience, both need
configuring — ask which the audience actually opens, and prefer covering both when unsure.

---

## Step 3 — Name the Audience

**This is the step the whole skill turns on.** Ask before looking at any object state:

```
Whose users are you protecting these columns from?

  Org(s):   which Org's users should NOT see the restricted columns?
  Group(s): within each Org, which groups SHOULD keep seeing them?
```

Two rules, both non-negotiable:

**Never infer the audience.** Column security decides who sees tenant data. Principals are
always the operator's input, never a default. The `All` group is the most dangerous
default on a secured object.

**Groups are per-Org.** A group name from one Org is meaningless in another —
live-verified: Primary had `Analyst`/`Consumer`/`rls-group-1..5` while ORG1 had only
`Administrator`/`All`/`Demo Retail Group`. Collect groups **per Org**. A manifest naming
the wrong Org's group fails with `Invalid group identifiers: <name>`.

Save as `{audience}`: a list of `(org, [groups])`.

---

## Step 4 — Detect, per (Org, object)

For each object, read publication state:

```bash
ts publish status {guid} --profile "{profile_name}"
```

For each Org in `{audience}`, read existing access and probe CSR availability:

```bash
ts share status {guid} --columns --org "{org}" --profile "{profile_name}"
ts security column-rules get {guid} --org "{org}" --profile "{profile_name}"
```

Build one row per **(Org, object)** and classify each:

| Reading | Classification |
|---|---|
| `owner_org` == this Org | **native** — this Org owns the object |
| this Org appears in `published_to` | **published-in** — the object lives elsewhere |
| `publish status` failed (403, 500, no hit) | **unknown** — block the row, do not assume unpublished |

Three detection traps, all live-verified. Get these wrong and the matrix in Step 6 is
confidently wrong:

**A failed publication read is not "not published".** Only a successful read supports the
claim. Block the row and say why.

**A clean CSR read from a tenant Org proves nothing.** On a published object, a tenant
`get` returns `[]` while no rule exists and `10023` once one does. So `[]` does not mean
"this Org can manage CSR here" — it can equally mean "there is nothing here yet". Tenant
CSR capability is inferred from publication state, never probed by reading.

**`10023` is overloaded.** The disabled-form message means the feature flag is off; the
access-form message means a privilege problem — or, on a published object, the read-only
trap above. Distinguish on message text, never the bare code.

---

## Step 5 — The Strict Object Mode Gate

**Run this before recommending CLS for any row.** Trigger: any **published-in** row (which
has no mechanism but CLS), or a **native** row where the operator elects CLS at Step 6.
Ask once per run — the setting is cluster-wide.

```
CLS (column-level sharing) only takes effect when the cluster is in Strict Object Mode.

No REST API exposes this setting. If it is OFF, column grants are accepted without
error and do nothing at all — the columns stay visible and nothing warns you.

Is Strict Object Mode enabled on this cluster?  [Yes / No / Don't know]
```

| Answer | Do this |
|---|---|
| **Yes** | Proceed. Record the confirmation in the plan artefact so a later reader knows the gate was passed, not skipped |
| **No** | Say plainly that CLS will no-op. For a published-in row that means **no working mechanism exists** — see below. Do not apply |
| **Don't know** | **Stop.** Ask them to confirm in the cluster's configuration, or with a ThoughtSpot admin. Never proceed on an unconfirmed gate |

Do not substitute `ts share resolve`'s column-grant warning for this gate. That warning
arrives at plan time, after the mechanism is already chosen, and is one line in a stream
of output.

### When no mechanism works

**Published object + tenant audience + Strict Object Mode off.** CSR cannot reach that
tenant and CLS does nothing. Say so, name the three real options, and stop:

```
There is no working column-security mechanism for {object} in {org} on this cluster.

  1  Enable Strict Object Mode, then use CLS
  2  Give {org} a native object instead of a published one, then use CSR
  3  Accept the exposure, knowingly

Nothing has been applied.
```

---

## Step 6 — The Mechanism Matrix

Present one row per (Org, object). Rows may legitimately disagree — say so, because it
looks like a bug and is not:

| Org | Object | Relationship | Mechanism | Why |
|---|---|---|---|---|

The decision, in full, with evidence:
[references/mechanism-decision.md](references/mechanism-decision.md).

| Audience Org's relationship | Mechanism | Rationale |
|---|---|---|
| **native** — that Org owns it | **CSR** (preferred), CLS possible | Declares only the restricted columns; a Liveboard filtered on a secured column stays interactive; composes with a table share rather than being defeated by one |
| **published-in** | **CLS only** | CSR is closed off two ways: an owning-Org rule does not travel with publication, and the tenant cannot define one either (`10038 FORBIDDEN`) |

Two things to say out loud when they apply:

**Protecting N tenant Orgs is N configurations**, each against that Org's own group names.
There is no owning-Org write that propagates. Configuring once in Primary and believing
every tenant is covered is the single most common way to get this wrong.

**CSR on a published object protects the owning Org only.** If a row is native but the
object is also published elsewhere, CSR is correct *for this Org's users* and does nothing
for the tenants. If tenants also need protecting, they need their own rows.

Ask:

```
Apply these mechanisms? (Y / N / change one):
```

---

## Step 7 — Source the column→group map

Ask per Org, because the map is per Org:

```
Where do the column→group rules come from for {org}?

  1  Uniform  — the same restricted columns and groups in every target Org
  2  File     — a CSV of per-Org rows
  3  DB table — a Snowflake governance table with the same columns

Enter 1-3:
```

The two manifests are **not interchangeable**, and the inversion is the thing to get right:

| Mechanism | Manifest | You declare |
|---|---|---|
| CSR | `TS_COLUMN_SECURITY_RULES` | only the **restricted** columns, and who may still see them |
| CLS | `TS_SHARE_GRANTS` | every **visible** column per group |

DDL for either:

```bash
ts security column-rules resolve --init-table      # TS_COLUMN_SECURITY_RULES
ts share resolve --init-table                      # TS_SHARE_GRANTS
```

**Where the map should come from.** Not hand-authored: `ts migrate audit`'s column-usage
map is the intended producer — used columns get granted, unused withheld, one discovery
layer rather than three. It cannot feed this yet (`column-mapping.csv` has no `org_name`,
and usage is recorded only for gap columns). Until it does, the manifest is the contract.
See the design spec §5.

---

## Step 8 — Review the grant / rule matrix

Build the plan(s) without touching anything.

**CSR rows:**

```bash
ts security column-rules resolve --org "{org}" --source uniform \
  --table "{table}" --rule "COL=GROUP1,GROUP2" --profile "{profile_name}" \
  > /tmp/ts_csr_plan.json
```

**CLS rows** — note this is the *visible* column list, not the restricted one:

```bash
ts share export {guid} --org "{org}" --profile "{profile_name}" \
  | ts share resolve --org "{org}" --source uniform --group "{group}" \
      --share-mode READ_ONLY --column "{col}" --column "{col}" \
      --profile "{profile_name}" > /tmp/ts_cls_plan.json
```

Present both, then ask:

```
Do these look correct? (Y / N / edit):
```

Refusals to expect, and what each means:

| Refusal | Meaning |
|---|---|
| `CSR_BLOCKED` | The table is published. CSR would protect the owning Org only. Correct by default — `--allow-published` is for when owning-Org-only scope is genuinely wanted, never for reaching a tenant |
| Exclusivity conflict | The plan has both a table grant and a column grant for one (Org, table, group). A table grant conveys **every** column, so it silently defeats the column grants. Pick one granularity |
| `Invalid group identifiers` | A group from the wrong Org. Re-check Step 3 |

---

## Step 9 — Dry-run

```bash
ts security column-rules apply --input /tmp/ts_csr_plan.json --dry-run --profile "{profile_name}"
ts share apply --input /tmp/ts_cls_plan.json --dry-run --profile "{profile_name}"
```

Show the ordered plan. Nothing has changed at this point.

---

## Step 10 — Apply

**Checkpoint** — confirm before the first mutation:

```
Ready to apply:

  Objects:            {n}
  (Org, object) rows: {n}  ({n} CSR, {n} CLS)
  Groups:             {groups, per Org}
  Strict Object Mode: confirmed {yes/n-a} by the operator
  Columns restricted: {n}

Proceed? (Y / N):
```

**Order matters on the CSR path, and it is not cosmetic.** CSR filters columns *within*
access the object share already granted — it does not grant access itself. Apply object
access first:

```bash
# 1. CSR path only: the object share must exist first
ts share apply --input /tmp/ts_object_grants.json --profile "{profile_name}"

# 2. then the column rules
ts security column-rules apply --input /tmp/ts_csr_plan.json --profile "{profile_name}"

# CLS path: one call — the grant IS the access and the restriction
ts share apply --input /tmp/ts_cls_plan.json --profile "{profile_name}"
```

If the audience holds no object access on a CSR row and the operator declines to grant it,
**refuse that row**. A protected object nobody can open is not a security outcome.

`ts security column-rules apply` is one call per (Org, table) and its rollback is per
call, so a mid-loop failure leaves earlier tables applied. Report what landed.

---

## Step 11 — Verify

```bash
ts security column-rules get {guid} --org "{org}" --profile "{profile_name}"
ts share status {guid} --columns --org "{org}" --profile "{profile_name}"
```

Diff against the Step 4 baseline and report per (Org, object).

**State the limit of this verification rather than implying coverage it does not have.** A
CLS grant reads back **identically** whether Strict Object Mode is on or off. The read
proves the ACL, not the enforcement. If Step 5's gate was answered from memory rather than
checked, this step will not catch it.

The only way to prove enforcement is to open the object as a real non-admin user in that
Org. Offer that as a final check on anything sensitive — and if they do it, make sure they
confirm which **Org** the session is in. On a multi-Org cluster "I see nothing" is the
expected result almost everywhere, so an unqualified sighting proves nothing.

---

## Revoking

**An object-level `NO_ACCESS` is not a revoke when column grants exist.** Live-verified:
it removes the object from *search* while leaving the entitlement fully intact — the
object still opens by direct link, still showing the granted columns. The Table stays
reachable via the Data page throughout. This is a platform gap (BL-142), not a
configuration mistake, and nothing warns.

| To undo | Do this |
|---|---|
| A CLS column grant | `ts share` with `--share-mode NO_ACCESS` **and the same `--column` flags**. Column level, always |
| A CSR rule | `ts security column-rules clear --table {t} [--column COL] --org {org}` |
| An object grant that auto-created column rows | Revoke the object grant **and** each column — the auto-created column rows survive the object revoke |

Never present an object-level deny as a way to undo a column grant.

---

## Cleanup

```bash
rm -f /tmp/ts_csr_plan.json /tmp/ts_cls_plan.json /tmp/ts_object_grants.json
```

---

## Error Handling

| Symptom | Action |
|---|---|
| `10023`, message says the feature is disabled | CSR is feature-flagged off. Beta, 10.12.0.cl+. Not a permissions problem — ask ThoughtSpot to enable it, or use CLS |
| `10023`, message says access is denied | Check publication **before** privileges. On a published object read from a tenant Org this is the read-only trap, and no Org holds the missing privilege. Otherwise it is an ordinary per-Org privilege gap |
| `10038` / `FORBIDDEN` / `does not have access to read/modify CSR` | The tenant Org cannot define CSR on an object published into it. Use CLS for that Org. Not fixable with privileges |
| `CSR_BLOCKED: ... is published to {org}` | Working as designed. CSR would protect the owning Org only. Use CLS for the tenant |
| `CSR_BLOCKED: publication state could not be determined` | The read failed and the row is blocked deliberately. Fix the read; do not reach for `--allow-published` |
| `Invalid group identifiers: {name}` | A group from another Org. Groups are per-Org — re-collect them for this Org |
| `14502 Referenced table with name {name} not found` | The CSR TML names a table absent from the target Org. The document is fine; import it where that table exists |
| `14502 Referenced table with name  not found` (doubled space) | The CSR document is missing its mandatory `table:` reference |
| `Column '{c}' is not secured, cannot mark as unsecured` | A stale `--prune` plan. Re-run `resolve` to refresh against current state |
| Exclusivity conflict on a manifest | A table grant conveys every column and defeats the column grants. Choose one granularity per (Org, table, group) |
| Columns applied but users still see them | Check Strict Object Mode (CLS) — grants no-op silently when it is off. For CSR on a published object, check whether the audience is in a tenant Org, where the rule never applied |
| `ts share export` cannot resolve a tenant-native object | Needs ts-cli **0.110.0+**; earlier builds resolved only in the default Org |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-07-27 | Initial release |
