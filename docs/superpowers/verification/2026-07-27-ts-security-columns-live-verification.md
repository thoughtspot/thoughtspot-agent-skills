# `ts-security-columns` — live verification

**Date:** 2026-07-27
**Cluster:** profile `nebula-damian-alias`, Orgs Primary (0) / ORG1 (12750490) / ORG2 / ORG3
**Branch:** `feat/ts-security-columns`
**Baseline:** captured before any change, restored after, diff proven by a final read on
six dimensions (§7).

Verifies the design in
[`2026-07-27-ts-security-columns-skill-design.md`](../specs/2026-07-27-ts-security-columns-skill-design.md)
§9. All four questions ANSWERED. Three defects found, one of them a blocker for the skill.

**Headline:** a tenant Org **cannot** define CSR on an object published into it — HTTP 500,
code **10038**, `FORBIDDEN`. Design §2.1's second row ("published-in → CLS only") is
confirmed as a platform constraint rather than a conservative default.

---

## 1. The control, which is what makes this round conclusive

The second round (`2026-07-26-...-column-rules-live-verification.md` §11) could not
attribute its ORG1 `10023`: the test user's ORG1 privileges "were never confirmed
independently of the call". Every competing explanation is excluded here **before** the
test runs.

| Control | Result |
|---|---|
| Is the ORG1-scoped session really in ORG1? | **Yes.** `current_org: {'id': 12750490, 'name': 'ORG1'}` |
| Does the caller hold privileges *in ORG1*? | **Yes.** `org_privileges: {'12750490': ['ADMINISTRATION', 'AUTHORING', 'USERDATAUPLOADING', 'DATADOWNLOADING', 'DATAMANAGEMENT', 'SHAREWITHALL', 'A3ANALYSIS']}` |
| Can this caller write CSR in ORG1 at all? | **Yes** — §2, on ORG1's own native table |
| Can this caller read CSR on the published table from ORG1? | **Yes** — `[]`, before any rule existed |
| Can this caller write CSR on that same published table from Primary? | **Yes** — §4 |

Worth noting for anyone re-reading the session dump: `auth/session/user` from the
**Primary** token reports `orgs: [{id: 0, name: Primary}]` and
`org_privileges: {"0": [...]}`, which reads like "this user is not in ORG1". That is a
per-token view, not the user's actual reach — the ORG1-scoped token reports full
`ADMINISTRATION` in ORG1. Do not use the Primary-token view to conclude anything about
tenant-Org access.

With those five held, the only variable left in §3 is **publication**.

---

## 2. A tenant Org CAN configure usable CSR on its own native table (item #5, native half)

`T4_PER_ORG` (`d3a688f2-2543-4dcc-9907-b4cdb130c36b`, `orgIds=[12750490]`,
`ownerOrgId=12750490`) is native to ORG1. ORG1's groups are `All`, `Administrator`,
`Demo Retail Group`.

```
$ ts security column-rules set --table d3a688f2-... \
    --rule "UNIT_PRICE_AMT=Demo Retail Group" --org ORG1 -p nebula-damian-alias
applied d3a688f2-...: REPLACE UNIT_PRICE_AMT
```

Read back:

```json
[{"org": "ORG1", "table_guid": "d3a688f2-...", "obj_id": "",
  "column_id": "359df201-7e6c-47e0-93bd-38c6d98556fb",
  "column_name": "UNIT_PRICE_AMT", "group_names": ["Demo Retail Group"],
  "source_table_name": "T4_PER_ORG"}]
```

**ANSWERED: yes.** The second round's failure here (`Invalid group identifiers: Analyst`)
really was only the group-naming artefact it was diagnosed as. Against a group that exists
in the Org, a tenant configures its own CSR normally.

This is the half of open item #5 that matters for the *shared-Org* architecture, and it is
the control for §3.

---

## 3. A tenant Org CANNOT define CSR on an object published into it (item #5, published half)

`T2_PUBLISH` (`d2c12c11-6560-4810-96b8-4b902bbb82dc`) was published Primary → ORG1 for
this test (`ts publish` pipeline; `published_to: ["ORG1"]`, `is_published: true`).

**The guard fires first**, as designed:

```
$ ts security column-rules set --table d2c12c11-... \
    --rule "UNIT_PRICE_AMT=Demo Retail Group" --org ORG1 -p nebula-damian-alias
Refusing to set column security on 'T2_PUBLISH': it is published to ORG1. ...
Pass --allow-published if owning-Org-only scope is genuinely what you want here
```

**With the guard overridden, the platform refuses:**

```
$ ts security column-rules set --table d2c12c11-... \
    --rule "UNIT_PRICE_AMT=Demo Retail Group" --org ORG1 --allow-published -p ...

Failed on d2c12c11-...: REPLACE UNIT_PRICE_AMT: HTTP 500
{"error":{"message":{"debug":{"code":10038, ...,
  "debug":"[\"Error Code: FORBIDDEN ...
    Error Message: User does not have access to read/modify CSR for these tables:
    [d2c12c11-6560-4810-96b8-4b902bbb82dc]\"]"}}}}
```

**ANSWERED: no.** Given §1's controls, this is not privileges, not the feature flag, not
the account, and not the group name. It is publication. Consistent with
`docs/multi-tenancy-platform-plan.md` §4.2 fact 3 — published objects are read-only in
target Orgs — and CSR writes fall under that read-only-ness.

### The door is closed twice over, by two different mechanisms

The design assumed one constraint. There are two, and they are independent:

| Fact | Proven by |
|---|---|
| A CSR rule defined in the **owning** Org does not travel with publication — the tenant keeps seeing the column | Round 3, data plane, `...column-rules-live-verification.md` §15 |
| A CSR rule **cannot be defined in the tenant Org** either — `10038 FORBIDDEN` | This round, §3 above |

Either alone would leave a workaround; together they close it. `CSR_BLOCKED` is therefore
correct as a default, and `--allow-published` is genuinely an owning-Org-only scope
escape hatch, never a route to protecting a tenant.

---

## 4. The owning Org can still write to the same published table

Same table, same moment, same column, from Primary:

```
$ ts security column-rules set --table d2c12c11-... --rule "UNIT_PRICE_AMT=Analyst" \
    --allow-published -p nebula-damian-alias
applied d2c12c11-...: REPLACE UNIT_PRICE_AMT
```

Read back from Primary shows the rule. This is the last leg of the control: the table is
writable, just not from the tenant.

---

## 5. `10023` on a tenant read is STATE-DEPENDENT — and it explains the second round

The same command, same Org, same table, differing only in whether a rule exists:

| State of the published table | `get ... --org ORG1` |
|---|---|
| No CSR rules | `[]` — **succeeds** |
| CSR rules present (set from Primary) | **`10023`**, access-failure form |

The second round set a rule from Primary and then read from ORG1, hit `10023`, and
reasonably read it as a possible privilege artefact. It is not: it is the same
read-only-ness as §3, surfacing only once there is something to read.

**This matters for the skill's detection step.** A clean `[]` from a tenant Org does not
prove the tenant has CSR access — it may only mean there is nothing there yet. Tenant CSR
capability cannot be probed by reading; it has to be inferred from publication state.

---

## 6. CLS DOES work in the tenant Org on the published object

The mechanism design §2.1 nominates for published-in rows, tested in the same state:

```
$ ts share apply --input plan.json -p nebula-damian-alias
[ORG1] LOGICAL_COLUMN: T2_PUBLISH.UNIT_PRICE_AMT -> Demo Retail Group=READ_ONLY
applied 1 share call(s)
```

Reads back in ORG1 as `COLUMN UNIT_PRICE_AMT -> READ_ONLY` for `Demo Retail Group`.

So §2.1's second row is confirmed in **both** directions: CSR structurally refused, CLS
functional. Design §2.2's "no working mechanism" cell stays a genuine edge case (Strict
Object Mode off) rather than the normal case.

Strict Object Mode is **ON** on this cluster, confirmed by the repo owner. `ts share
resolve` emitted its column-grant warning as designed.

**Not verified here:** whether the grant *functions* at the data plane for a real ORG1
non-admin user. That needs a UI session as such a user, as round 3 did. This round proves
the ACL, not the enforcement.

---

## 7. Item 4 — a table-level `NO_ACCESS` does NOT clear existing column grants

Carried forward from the `ts share` record. Tested against the live column grant from §6:

| Step | `Demo Retail Group` grants on `T2_PUBLISH` in ORG1 |
|---|---|
| Before | `COLUMN UNIT_PRICE_AMT -> READ_ONLY` |
| Apply table-level `NO_ACCESS` | `[ORG1] LOGICAL_TABLE: T2_PUBLISH -> Demo Retail Group=NO_ACCESS` |
| After | `COLUMN UNIT_PRICE_AMT -> READ_ONLY` — **1 row, unchanged** |

**ANSWERED: no, it does not clear them**, at the ACL level. `ts share`'s refusal to mix
revoke-and-grant in one manifest is therefore about ordering ambiguity, not about
`NO_ACCESS` being destructive to column grants.

**Scope of the claim:** this is an ACL-level read-back. Whether the column grant still
*functions* after a table-level `NO_ACCESS` is a data-plane question this round does not
reach.

---

## 8. Defects found — all three FIXED on this branch

### 8.1 BLOCKER — `ts share export --org <tenant>` cannot see tenant-native objects — FIXED

`ts_cli/commands/share_planning.py:75-79`:

```python
base = _client_for_org(profile)                    # <- no org
resolved = _resolve_object(base, identifier)
resolved["columns"] = _table_columns(base, resolved["guid"])
```

Resolution and column listing run in the **default Org**; only `_fetch_permissions`
(line 89) is org-scoped. So `ts share export <guid> --org ORG1` fails outright for any
object native to ORG1:

```
$ ts share export d3a688f2-... --org ORG1 -p nebula-damian-alias
Invalid value: Could not resolve 'd3a688f2-...'.
```

Both the untyped and typed `metadata/search` probes resolve that GUID fine **when issued
with an ORG1-scoped client** — verified directly. The failure is purely that the wrong
client is used.

This blocks the skill's Step 4 baseline read for exactly the case the skill exists to
handle: a tenant Org's own objects. It is pre-existing in the shipped `ts share`
(PR #346), not introduced here.

**Secondary, same area.** `_resolve_object`'s typed fallback filters
`h.get("metadata_name") == identifier`. When `identifier` is a GUID that never matches,
so GUID resolution depends entirely on the untyped probe at line 223. The untyped probe
returns `400 code 10002` ("Specify the metadata_type for identifier ...") when the
identifier is unknown *in the current Org*, which is why the failure above presents as a
400 rather than an empty result.

### 8.2 Code `10038` has no error translation — FIXED

`explain_csr_error` (design §6 of the column-rules CLI spec) covers `10023` in two forms
and `14502` in two forms. `10038` is a **third code**, reachable by the most predictable
tenant mistake there is, and it surfaces raw.

### 8.3 The `10023` translation is actively misleading for this case — FIXED

Current wording ends:

> Groups and privileges are per-Org, so a token scoped to a tenant Org can lack what the
> Primary Org token has. **Re-run with a profile or Org that holds the needed privilege.**

For the §5 case that advice is wrong and costly. The caller **holds `ADMINISTRATION` in
that Org**, and no profile or Org holds the privilege, because the operation is
structurally impossible on a published object from a tenant Org. The operator is sent to
audit privileges that are already correct.

**Fixes, ts-cli v0.110.0.** `_find_object` returns `None` instead of raising so a caller
can try another Org; its typed fallback now matches on `metadata_id` as well as
`metadata_name`; `_resolve_object_in_orgs` tries the default Org first, then each `--org`,
returning the client that found the object so columns are listed in the right context;
ambiguity inside any one Org still raises rather than falling through. `explain_csr_error`
gains a `10038` branch and the `10023` branch now leads with the publication check.
Re-verified live: `ts share export d3a688f2-... --org ORG1` now resolves `T4_PER_ORG` with
all 10 columns and ORG1's grants, and the three pre-existing paths (by name, Primary-owned
with and without `--org`) are unchanged. 3515 unit tests pass.

### 8.4 Shape note, not a defect

`column-rules get` returns a bare `[]` for a resolved table with no rules on this build,
where the earlier record documented `[{"table_guid": ..., "column_security_rules": []}]`.
A genuinely unresolvable name still errors loudly (`13003`, `No table found with name:
...`), so `[]` is not masking a resolution failure.

---

## 9. Baseline restored — diff proven

| Dimension | Baseline | Final | ✓ |
|---|---|---|---|
| `T2_PUBLISH` publication | `published_to: []`, `is_published: false` | identical | ✓ |
| `T2_PUBLISH` CSR (Primary) | `[]` | `[]` | ✓ |
| `T4_PER_ORG` CSR (ORG1) | `[]` | `[]` | ✓ |
| `T2_PUBLISH` `schema` field | literal `ALIAS_TESTS`, unparameterized | `"db": "AGENT_SKILLS", "schema": "ALIAS_TESTS"` | ✓ |
| Variable `apj_schema` | absent | absent | ✓ |
| `Demo Retail Group` grants on `T2_PUBLISH` in ORG1 | none | 0 rows | ✓ |

Restoration used `ts publish rollback` against the record written by `apply`
(`unpublished from ORG1`, `deleted variable(s) apj_schema`, `rollback complete`), plus
explicit `column-rules clear` in both Orgs and a `NO_ACCESS` revoke of the column grant.

---

## 10. Open items after this round

| # | Item | Status |
|---|---|---|
| 1 | Can a tenant Org be given usable CSR? | **ANSWERED.** Native object: yes (§2). Published-in object: no, `10038 FORBIDDEN` (§3). Closes parent spec open item #5 |
| 2 | Does a table-level `NO_ACCESS` clear existing column grants? | **ANSWERED: no** at ACL level (§7), and §11 shows it does not clear the *entitlement* either — only discovery |
| 3 | Can a group holding only column grants reach the table at all? | **ANSWERED: yes**, both Table and Model (§11). Closes parent spec open item #1 |
| 4 | Does a CLS column grant still function after a table-level `NO_ACCESS`? | **ANSWERED: yes** — the data stays readable by direct link; only search discovery is removed (§11). Platform gap, BL-142 |
| 5 | Is Strict Object Mode ever API-readable? | OPEN, unchanged |

---

## 11. Fourth round (2026-07-27) — the data plane, as real non-admin users

Items 3 and 4 of §10 needed a UI session as a genuine non-admin. Run by the repo owner
against Primary, with `guest1` and `guest4`.

### Setup

Two arms on `T2_PUBLISH` (Table) and `T2_PUBLISH_MODEL` (Model), from a clean baseline
where only `Administrator`/`tsadmin`/`su` held anything:

| Group | User | Object grant | Column grants |
|---|---|---|---|
| `Analyst` | `guest1` | `READ_ONLY` | all 25, auto-created by the object grant |
| `Consumer` | `guest4` | **none** | exactly 3: `PROD_NM`, `PROD_CAT_L1`, `AMOUNT` |

`guest1` and `guest4` share `Demo Retail Group` and `ShareWithAll`, so those cannot
discriminate; `Analyst` (guest1 only) and `Consumer` (guest4 only) are the discriminating
pair. Both users are members of all four Orgs and default to `current_org: Primary`.

**A false negative worth recording.** The first `guest4` observation was made in ORG1,
where neither object exists (`T2_PUBLISH` was unpublished by then), and read as "column
grants convey no access". It does not: it is an artefact of testing in the wrong Org. Any
data-plane test on a multi-Org cluster has to state which Org the session was in, because
"I see nothing" is the expected result almost everywhere.

### Item 3 — a group holding ONLY column grants DOES reach the object

**ANSWERED: yes**, on both surfaces. With no object grant whatsoever, `guest4` opened
`T2_PUBLISH` and `T2_PUBLISH_MODEL` and saw **exactly the three granted columns**;
`UNIT_PRICE_AMT` and the other 21 were absent. `guest1` (object grant) saw all 25, which
is the control proving the objects were reachable and the grants were what differed.

This closes parent spec open item #1 and confirms the design's step-count asymmetry:
**CLS really is one step** — the column grant is simultaneously the access and the
restriction — while CSR is two. Strict Object Mode (ON here) is doing its documented job
on the Model.

### Item 4 — an object-level `NO_ACCESS` removes DISCOVERY, not the entitlement

**ANSWERED, and it is a platform gap rather than a clean yes/no.**

With the three column grants left in place, a table-level `NO_ACCESS` was applied to
`Consumer` on both objects. The ACL kept all three column rows on both (third instance of
that behaviour, now on explicitly-granted columns rather than auto-created ones). At the
data plane:

| Surface | After the deny |
|---|---|
| `T2_PUBLISH` (Table) | still visible, still the 3 columns |
| `T2_PUBLISH_MODEL` (Model) | **gone from search** — but **opens normally by direct link**, still showing the 3 columns |

The Table/Model split is **not** two security models. The entitlement is identical on
both; only the discovery surface differs, because a Model is reached mainly through search
and a Table through the Data page. The deny removed the object from search and left the
column-level entitlement fully intact.

**The operating rule, and it is the security-relevant one:**

> An object-level `NO_ACCESS` is **not a revoke** when column grants exist. It removes the
> object from discovery while leaving the data readable. To revoke CLS, revoke at COLUMN
> level.

**Why this is a product gap, not merely a quirk.** A partial deny is worse than either a
real deny or no deny at all: it looks effective to the administrator who applied it, while
remaining live for anyone holding a direct link, a bookmark, or an Answer or Liveboard
built on the object. The intuitive operator action -- "remove their access to this table"
-- demonstrably does not do what it appears to. This is the same failure class as the
CSR-on-published trap: the write succeeds, nothing warns, and a false belief is created.
Filed as BL-142.

It also retro-justifies `ts share`'s refusal to mix revoke-and-grant in one manifest, and
argues that `ts share status` should call out surviving column grants when the object
grant is absent, rather than listing them as unremarkable rows.

### Baseline restored

Both objects back to 78 grant rows with only `Administrator`/`tsadmin`/`su`, matching the
captured baseline.
