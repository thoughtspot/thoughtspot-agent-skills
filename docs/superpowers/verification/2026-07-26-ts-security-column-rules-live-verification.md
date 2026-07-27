# `ts security column-rules` -- live verification

**Date:** 2026-07-27
**Cluster:** `nebula-damian-alias`, profile `nebula-damian-alias`
**Authenticated as:** `tsadmin` (ADMINISTRATION), same session Org (`Primary`) as the `ts share`
verification (`docs/superpowers/verification/2026-07-26-ts-share-live-verification.md`)
**CLI:** ts-cli 0.109.0 from branch `feat/ts-security-column-rules`
**Tables under test:** `T1`, `T2`, `T3_PUBLISH` (design spec §8's chosen set); `T2_PUBLISH`,
parameterized and published for the second round (§11)
**Orgs on the cluster:** `Primary` (0), `ORG1` (12750490), `ORG2` (535312919), `ORG3` (443705360)

**Cluster state: returned to baseline, proven by a final read.** See §9 (first round) and
§11 (second round, `T2_PUBLISH` fully restored -- schema, publication and CSR). A third
round (§15, 2026-07-27) is a manual UI data-plane test run by the repo owner on his own
test cluster; that cluster's restoration is his own, outside this document's tool
access, and not re-verified here.

---

## Scope note

All three tables carry `metadata_header.orgIds == [0]` and `ownerOrgId == 0` on this
cluster -- the same "nothing published to any tenant Org" state the `ts share`
verification found. This is what made the *earlier* `_published_orgs` defect
(fixed before this verification round, not one of the four below) so consequential: reading
`orgIds` as "published into" rather than "owning Org plus published-to" would have read
`[0]` as "published to Org 0", marking every table on this Org-enabled cluster
`CSR_BLOCKED`. That earlier fix is why this round's plans were not refused outright.
Because nothing here is actually published, §8 Q6 (the refusal shape on a published
object) stays open in THIS round -- taken up with a genuinely published table in the
second round, §11.

Baseline `get` across all three tables, captured before any change:

```json
[]  // T1: column_security_rules: []
[]  // T2: column_security_rules: []
[]  // T3_PUBLISH: column_security_rules: []
```

---

## 1. `fetch` / `get` -- response shape (§8 Q3)

```
$ ts security column-rules get T2 -p nebula-damian-alias
```

Observed verbatim:

```json
[{"table_guid":"...","obj_id":null,"column_security_rules":[]}]
```

**Confirms** the response is a BARE ARRAY with snake_case keys, not the prose example's
`data`-envelope with camelCase (`columnSecurityRules`, `objId`). The response *schema* was
the accurate half of the spec's two documented shapes; the prose example was wrong.
`normalise_fetch_response`'s snake_case branch is what actually ran; its camelCase branch
is dead on this build (kept -- another build could differ -- but unexercised in practice).

---

## 2. `set` -- per-column `REPLACE` is scoped (§8 Q1)

The single most important unknown in the design spec: whether a per-column `REPLACE`
touches only the named column, or whether `update` is secretly a whole-table replace that
would make `set` unsafe without a read-modify-write.

```
$ ts security column-rules set --table T2 --rule "PROD_NM=Analyst" -p nebula-damian-alias
applied T2: REPLACE PROD_NM

$ ts security column-rules set --table T2 --rule "UNIT_PRICE_AMT=Consumer" \
    -p nebula-damian-alias
applied T2: REPLACE UNIT_PRICE_AMT
```

Read-back after both calls:

```
  PROD_NM          -> ['Analyst']
  UNIT_PRICE_AMT   -> ['Consumer']
```

**Confirms** a per-column `REPLACE` is genuinely scoped: securing `PROD_NM` did not touch
`UNIT_PRICE_AMT`'s rule set in the second, separate `set` call, and both rules coexist.
`set` is safe as an idempotent per-column call and does not need to become a
read-modify-write. The design spec's §3.2 caveat, `set --help`'s "NOT YET LIVE-VERIFIED",
and the README's matching line are all now stale and have been removed (Finding D, §8.4).
Verified for `REPLACE` on a single table; `set` itself is otherwise unchanged.

---

## 3. `update` -- response handling (§8 Q2)

Every successful `update` call in this session returned **HTTP 200**, matching the design
spec's live-probing note and not the documented 204. The spec's "treat any 2xx as success,
parse no body" reading needed no code change -- it was already right.

---

## 4. Unsecuring a never-secured column errors, not a no-op (§8 Q4)

```
$ ts security column-rules clear --table T2 --column PROD_CAT_L1 -p nebula-damian-alias
```

`PROD_CAT_L1` had no rule at the time. Observed verbatim, HTTP 400:

```json
{"error":{"message":{"debug":{"code":10002,"debug":"[\"Column 'PROD_CAT_L1' is not secured, cannot mark as unsecured\"]"}}}}
```

**Contradicts** the parent spec's guess that the analogous case was "likely a harmless
no-op". Before this round, `explain_csr_error` returned `None` for it, so the operator saw
the whole JSON blob with incident GUIDs instead of the platform's (perfectly clear) own
wording. This matters for `--prune`: pruning computes `unsecure` from columns confirmed
secured at plan time, so a plan is safe when fresh, but a column unsecured by something
else between `resolve` and `apply` makes that plan entry stale and the apply fails
partway through, on this exact error. Fixed -- Finding C, §8.3.

---

## 5. Import across Orgs -- `table:` resolves per-Org by name (§8 Q5)

Importing a `T2_PUBLISH_CSR.column_security_rules.tml` document (with a correct,
non-empty `table: {name: T2_PUBLISH}` reference) into an Org that has no table named
`T2_PUBLISH` returned **HTTP 200**, with the failure buried in the body:

```json
[{"response": {"status": {"error_message": "Referenced table with name T2_PUBLISH not found.", "status_code": "ERROR", "error_code": 14502}}, "request_index": 0}]
```

`echo $?` after that call: **`0`**.

**Confirms** the `table:` reference resolves per-Org by name: the document itself was
correct, the target Org simply had no same-named table. A CSR document is therefore
portable only to Orgs that have a same-named table -- it does not carry the table's
identity with it the way a GUID reference would. Answers parent spec open item #3.

This one `import` produced two of the four defects at once:

- The CLI reported **SUCCESS** (exit 0) for an import that changed nothing (Finding A).
- `explain_csr_error` translated this exact body as "the document is missing its
  `table:` reference" -- false, since the reference was present and correct (Finding B).

Both are fixed; see §8.

---

## 6. Securing a column for nobody is a reachable state (§8 Q7, added during verification)

```
$ ts security column-rules set --table T2 --rule "COST=" -p nebula-damian-alias
applied T2: REPLACE COST
```

`build_update_payload` emits `group_identifiers: []` for this case. The call returned
success (204/200, no body), and a read-back showed `COST` present with an empty group
list -- secured, visible to nobody.

**Confirms** "secured for nobody" is a real, reachable state on this platform, not just a
theoretical one the manifest schema allows. Validates both the `"COL="` CLI flag sentinel
and the blank `group_name` manifest sentinel (`TS_COLUMN_SECURITY_RULES.group_name = ''`).

Two benign divergences from the platform's own TML export noticed while checking this:
the platform's exported document carries `table.fqn` (the table GUID) alongside
`table.name`; ours emits `name` only, which is arguably the better choice for portability
since a GUID from one Org will not resolve in another (§5 above). And for a column secured
for nobody, the platform's own export *omits* the `accessible_groups` key entirely, where
ours emits `accessible_groups: {group_name: []}`. Our parser reads the platform's bare
form correctly -- verified, it round-trips to `[]`. Neither divergence is a defect; both
are recorded here for anyone diffing our TML against a platform export.

---

## 7. Also confirmed

- **Feature flag is enabled** on this cluster: every `fetch`/`update` call returned 200,
  never 403 with code 10023. The `_FEATURE_DISABLED_RE` flag-detection path was therefore
  not exercised live this round.
- **Org-scoped auth works and lands correctly.** Requesting `ORG1` minted a token whose
  session `current_org` was `{'id': 12750490, 'name': 'ORG1'}`, matching the resolved
  numeric id, so `assert_org_context` passed rather than catching a fallback. (The `ts
  share` verification is where the org-scoped-auth-is-silent defect was originally found
  and fixed; this round confirms the fix holds for CSR's own calls too.)

---

## 8. Findings that changed the implementation

### 8.1 `import` reports SUCCESS on a failed import -- fixed

`metadata/tml/import` returns HTTP 200 even when the per-item import failed (§5 above).
`import_cmd` only checked `resp.ok`, so it printed the failure body and exited 0 -- the
exact "reports success having changed nothing" failure mode this whole feature exists to
guard against.

**Fix:** a new, platform-neutral `tml_import_failures(import_result)` helper in
`ts_cli/tml_common.py`, beside `extract_imported_guid` (same file, same "two response
shapes" concern -- status lives at `response.status.status_code` regardless of which GUID
shape a given build returns). `import_cmd` now reads it and exits non-zero on any failed
item, routing the message through `explain_csr_error` first and falling back to the
platform's own `error_message`.

**Deliberately not done here:** `ts alias import` and `ts tml import` almost certainly
have the same gap (both check only `resp.ok`). Wiring them to the same helper is a
follow-up, kept out of this PR to limit blast radius.

### 8.2 `explain_csr_error` misdiagnosed a real 14502 -- fixed

The pre-fix regex matched the bare code `14502` and translated every occurrence,
regardless of whether the table name was empty or present, as "the document is missing
its `table:` reference". §5's response has the name present and correct -- the message
was false and would have sent an operator to edit a document that was already fine.

**Fix:** a second regex (`_MISSING_TABLE_NAMED_RE`) captures a non-empty name between
"with name" and "not found". When it captures something, the message now says the named
table was not found in the target Org and that CSR documents are portable only to Orgs
with a same-named table. When it does not (the doubled-space empty-name case, or a bare
code mention with no name text at all), the original "missing reference" wording is kept
unchanged.

### 8.3 Unsecuring a never-secured column had no translation -- fixed

§4 above. The platform's own wording (`"Column 'X' is not secured, cannot mark as
unsecured"`) was buried under raw JSON with incident GUIDs.

**Fix:** `explain_csr_error` now matches this message, surfaces the platform's own
column name, and adds that a stale `--prune` plan is the likely cause -- re-running
`resolve` refreshes it against current state.

### 8.4 The per-column `REPLACE` caveat is stale -- removed

§2 above settled design spec §8 item 1. `set --help` and the README both carried a
"NOT YET LIVE-VERIFIED" caveat naming that item; both now state plainly that a per-column
`REPLACE` is scoped, dated 2026-07-27 against this cluster, and note the verification was
for REPLACE on a single table -- `set` itself is unchanged.

---

## 9. Baseline restored

```
T1:        column_security_rules: []
T2:        column_security_rules: []
T3_PUBLISH: column_security_rules: []
```

Every rule set during verification (`PROD_NM`, `UNIT_PRICE_AMT`, `COST` on `T2`;
`PROD_CAT_L1`'s clear attempt, which never took effect) was cleared with `clear --table
T2` (whole-table) at the end of the session. The final `get` across all three tables
shows zero secured columns anywhere -- the same state the baseline `get` showed at the
start.

---

## 10. Open items (as they stood at the end of the first round)

| # | Item | Status |
|---|---|---|
| 1 | §8 Q6 -- the refusal shape for CSR on a published object | OPEN -- needs a table published first. Not published on this cluster (see Scope note); this is the same gap the `ts share` verification left open for an end-to-end grant on a published object in a tenant Org. |
| 2 | Carried forward from the `ts share` verification: does a table-level `NO_ACCESS` clear existing column grants? | OPEN -- untested here too. Unrelated to CSR's own mechanism, but cheap to settle alongside item 1 once a published object is available. |

Neither blocks `ts security column-rules`. Both are worth resolving before
`ts-security-columns` (parent spec §4) needs to reason about published objects.

Item 1 is taken up in the second round below (§11); item 2 remains open (see §14).

---

## 11. Second round (2026-07-27) -- Q6: CSR on a genuinely published object

This round closes item 1 above: get an actual published table and test CSR against it,
rather than reasoning about the refusal in the abstract.

### Setup -- publishing needs parameterization first

`T2_PUBLISH` was not parameterized yet. Trying `ts publish push` against it unprepared
was the first thing attempted, to confirm the sibling command's own failure mode:

```
$ ts publish push T2_PUBLISH --org ORG1 -p nebula-damian-alias
Object 'T2_PUBLISH' is not parameterized, so it cannot be published...
```

**Fails CLOSED with a translated, actionable message**, not a bare API error -- good
sibling-command behaviour, and the reason Q6 needed a variable at all. `T2_PUBLISH`'s
schema field was then bound to a template variable (the table's schema was `ALIAS_TESTS`
beforehand) and the table was published to ORG1. `metadata_header` afterwards read:

```
orgIds=[0, 12750490]  ownerOrgId=0  is_published: true
```

`published_org_ids(header)` on this same header returned `[12750490]` -- see §12 for why
this matters beyond Q6.

### CSR from the OWNING Org: succeeds and takes effect

```
$ ts security column-rules set --table T2_PUBLISH --rule "PROD_NM=Analyst" \
    -p nebula-damian-alias
```

Returned **HTTP 204**. Read-back:

```
  PROD_NM  -> ['Analyst']
```

`T2_PUBLISH` remained published (`orgIds` unchanged) throughout. **The platform does NOT
refuse CSR on a published object**, at least on this build and from the owning Org. This
disproves the premise the design spec §3.3, the parent spec's comparison table, and
`docs/multi-tenancy-platform-plan.md` §4.3 all stated -- "CSR cannot be defined on
published objects" -- as a claim about platform behaviour. `CSR_BLOCKED` and
`--allow-published` are UNCHANGED by this finding; see "What this does not settle" below
for why the refusal stays.

### Reading CSR as the tenant Org (ORG1): a 10023 access error

```
$ ts security column-rules get T2_PUBLISH --org ORG1 -p nebula-damian-alias
```

Observed verbatim, **HTTP 500**:

```json
{"error":{"message":{"debug":{"code":10023, ..., "debug":"[\"User does not have access to rea[d]...\"]"}}}}
```

Code 10023 here means an access failure, not the feature flag -- the cluster's CSR
feature is demonstrably ON (the owning-Org update above just succeeded). This is Finding
F (§13) and is what shows code 10023 is overloaded.

### Modifying CSR as the tenant Org (ORG1): blocked before read-only-ness could be tested

```
$ ts security column-rules set --table T2_PUBLISH --rule "PROD_NM=Analyst" \
    --org ORG1 -p nebula-damian-alias
```

Failed on `Invalid group identifiers: Analyst` -- groups are per-Org, and `Analyst` in
ORG1 is a different principal from `Analyst` in the owning Org (the same gotcha
`explain_share_error` already translates for `ts share`). This failure is a group-naming
artefact of the test setup, not a signal about CSR's own access model, so it does not
tell us whether ORG1 could modify CSR on this table if it named a group that actually
exists there.

### What this round settles, and what it does not

**Settled:** the platform accepts CSR on a published object from the owning Org. The
CLI's blanket "cannot be defined" justification was wrong and is corrected (design spec
§3.3, this branch's docstrings, README, CLAUDE.md).

**Still unknown:** whether a TENANT Org can see or use a CSR rule set that way. The one
read attempt from ORG1 hit an access error (10023, access-form) that may be a per-Org
privilege artefact of the test user rather than a product rule -- the test user's ORG1
privileges were never confirmed independently of this call. The one modify attempt from
ORG1 failed on a per-Org group-name mismatch before it could test read-only-ness either
way. Neither result closes the question. `CSR_BLOCKED` therefore stays the default:
refusing is the conservative choice given a genuine unknown, `--allow-published` is the
escape hatch for an operator who wants to try it anyway, and this open question is now
named explicitly rather than hidden behind a false certainty.

### Cleanup -- full restoration, proven by a final read

1. CSR cleared on `T2_PUBLISH` (`clear --table T2_PUBLISH`) -- confirmed **zero CSR
   rows** by a final `get`.
2. `T2_PUBLISH` unpublished from ORG1 -- `metadata_header.orgIds` back to `[0]`.
3. The schema field's template-variable binding removed (`unparameterize`) -- the
   table's schema back to the literal `ALIAS_TESTS` it carried before this round.
4. The template variable itself deleted.

All four confirmed by a final read, matching the state before this round started.

---

## 12. Second round -- other confirmations

- **Publication detection is correct in BOTH directions.** The `ts share` verification
  round had only exercised the UNPUBLISHED case (`orgIds == [0]` reading as not
  published). This round exercises the PUBLISHED case for the first time: header
  `orgIds=[0, 12750490] ownerOrgId=0`, and `published_org_ids(header)` returned
  `[12750490]` -- the owning Org correctly excluded, the tenant Org correctly included.
  The other half of the Critical-1 fix (`orgIds` includes the owning Org, so reading
  every id in it as "published into" over-blocks) is now live-verified for a genuinely
  published table, not just reasoned about.
- **`ts publish push` fails closed on an unparameterized object** with a translated,
  actionable message (§11 above) rather than a bare API error -- confirmed good
  sibling-command behaviour, and the reason this round needed to parameterize
  `T2_PUBLISH` before it could test Q6 at all.

---

## 13. Second round -- two more defects found and fixed

### 13.1 Finding E -- `_try_search` could not actually swallow anything

`ts_cli/commands/share.py`'s `_try_search` (shared by `ts share` and this CLI's
`_resolve_object`) wrapped its one `metadata/search` attempt in `except Exception`, to
let resolution fall through to the next candidate type. `ts_cli/client.py` raises
`SystemExit` on an API error, not a plain exception, and `SystemExit` derives from
`BaseException`, which `except Exception` does not catch.

**Observed:** resolving a table BY NAME (`ts security column-rules resolve --table
T2_PUBLISH`) probes untyped first (`{"identifier": "T2_PUBLISH"}`), which the platform
rejects with:

```
HTTP 400 code 10002: Invalid parameter values: {"metadata":"Specify the metadata_type for identifier T2_PUBLISH"}
```

That `SystemExit` propagated straight out of `_resolve_object` and killed the process
instead of falling through to the typed-candidate loop -- resolving by NAME failed
outright, though the same call by GUID worked, and the README's own examples resolve by
name. `ts share status T2_PUBLISH` (also by name) hit the identical crash: this defect
is PRE-EXISTING in the shipped `ts share` (PR #346), inherited here by reusing
`_resolve_object` as designed, not introduced by this branch.

**Fix:** catch `(Exception, SystemExit)` explicitly in `_try_search`, with the docstring
now naming `client.py` as the `SystemExit` raiser so a future reader does not
"simplify" it back to `except Exception` alone. Confirmed `ts share`'s existing test
suite still passes after the fix (32/32 in `test_share_commands.py`).

### 13.2 Finding F -- error code 10023 is overloaded

§11's ORG1 read (`does not have access to read`) and the first round's feature-flag
case (`Column Security rule feature is disabled`) both carry code 10023, and
`explain_csr_error`'s pre-fix regex keyed on the bare code alone -- so it would have
announced the feature was flagged off on a cluster where it plainly is not, sending an
operator to ask ThoughtSpot to enable a flag that is already on. Same defect class as
the 14502 overload (first round, Finding B).

**Fix:** disambiguate on the accompanying message text, not the code alone. Only the
disabled-form text (`"Column Security rule feature is disabled"`) produces the
feature-flag message; the access-form text (`"does not have access"`) alongside code
10023 produces a distinct message naming the Org-scoped access problem and that groups
and privileges are per-Org. A bare 10023 with neither text present falls through to
`None`, like any other unrecognised body, rather than guessing which of the two it is.

---

## 14. Open items, updated

| # | Item | Status |
|---|---|---|
| 1 | Whether a tenant Org can see or use CSR set from the owning Org on a published table | **STILL OPEN** (§11). Narrowed from "the refusal shape on a published object" (now settled: the platform accepts it from the owning Org) to specifically the tenant-visibility question. |
| 2 | Carried forward from the `ts share` verification: does a table-level `NO_ACCESS` clear existing column grants? | STILL OPEN, unchanged. Unrelated to CSR's own mechanism. |

Neither blocks `ts security column-rules`. Both are worth resolving before
`ts-security-columns` (parent spec §4) needs to reason about published objects.

---

## 15. Third round (2026-07-27) -- Q6 conclusively answered: CSR is Org-scoped

Item 1 above (§14) is now closed. The first two rounds were both API-level probing from
an admin session; this round is a manual data-plane test on the repo owner's own test
cluster, driven from the ThoughtSpot UI as real non-admin users, which is what settles
the tenant-visibility question the second round's 10023/group-mismatch results could
not.

### Setup

- Table `T2_PUBLISH`, owned by the Primary Org, published to tenant Org ORG1.
- A CSR rule restricted column `UNIT_PRICE_AMT` to group `Analyst`.
- `Analyst` exists in the Primary Org and does **NOT** exist in ORG1 -- confirmed: ORG1's
  only groups are `Administrator`, `All`, `Demo Retail Group`. This is deliberate: if the
  rule were somehow honoured in ORG1, no ORG1 user could ever satisfy it (no `Analyst`
  group to belong to), so any visibility of the column in ORG1 can only mean the rule
  was not applied there at all, not that some ORG1 user happened to qualify.
- The object was shared (Model, and the Table) in BOTH Orgs, so real non-admin users
  could actually open it and the test reflects what a user sees, not an API response.

### Results, observed in the UI as non-admin users

- **In Primary:** `guest4` (member of `Consumer`, not `Analyst`) could **NOT** see
  `UNIT_PRICE_AMT`, on both the Table and the Model. CSR **is** enforced in the owning
  Org, even though the table is published -- consistent with the second round's API-level
  finding that the owning-Org write succeeds and takes effect.
- **In ORG1:** the column **WAS** displayed, fully, to a non-admin user with no group
  that could possibly satisfy the rule. CSR set in the owning Org is **NOT** enforced for
  the tenant.

### Conclusion

**A CSR rule is scoped to the Org it was defined in.** Setting CSR on a published table
therefore protects the owning Org and silently leaves every tenant Org unprotected. No
error, no warning, at write time or at read time in either Org. An operator can secure a
column, publish the object, and believe every tenant is protected while none of them
are.

This is the exact opposite of what the design originally assumed. The design said "the
platform refuses CSR on published objects" (already disproven in the second round: it
returns 204 and enforces it locally). The true situation, now settled, is worse and more
subtle than either the original assumption or the second round's open question: it
*succeeds*, it *appears* to work (nothing about the write, or about reading CSR back
from the owning Org, looks wrong), and it creates a false belief rather than an error.

### The parent comparison table's row is right in outcome, wrong in mechanism

The parent spec's comparison table (and `docs/multi-tenancy-platform-plan.md` §4.3)
state "works on published objects: No" for CSR. The practical *outcome* that row is
gesturing at -- CSR does not protect a published object's tenants -- is correct. The
*mechanism* it implies -- that the platform refuses the operation -- is not: the
platform accepts the write and silently confines it to the defining Org. A reader who
takes the row at face value would expect an error and be surprised there is none. Both
documents still need this correction; it is out of scope for this branch (see the top
of the design spec) and should be made separately.

### Per-Org configuration is not a workaround, it is the model

The tenant-side result means CSR has to be configured **per-Org, against that Org's own
groups** -- there is no single owning-Org rule that reaches every tenant. This is exactly
what the `org_name` key in the `TS_COLUMN_SECURITY_RULES` manifest table is for: a
manifest row names the Org it applies to, and `resolve --source uniform --org ORG1
--org ORG2 ...` (or `file`/`db` with per-Org rows) is how an operator expresses "secure
this column in every one of these Orgs, against each Org's own group names" rather than
expecting one write to propagate.

### Cleanup

The finding was produced and verified entirely on the repo owner's own test cluster,
outside this fix task's own tool access (no cluster contact was made to produce this
report). Restoration of that cluster's state is the repo owner's own responsibility and
is not re-verified here.

---

## 16. Open items, final

| # | Item | Status |
|---|---|---|
| 1 | Whether a tenant Org can see or use CSR set from the owning Org on a published table | **ANSWERED (§15).** It cannot: CSR is scoped to the Org that defined it and does not travel with publication. `set` now carries the same CSR_BLOCKED guard as `resolve`/`build`/`apply`. |
| 2 | Carried forward from the `ts share` verification: does a table-level `NO_ACCESS` clear existing column grants? | STILL OPEN, unchanged. Unrelated to CSR's own mechanism. |

Only item 2 remains, and it does not block `ts security column-rules`. The parent
spec's comparison table and `docs/multi-tenancy-platform-plan.md` §4.3 both still need
the mechanism correction described in §15 above -- tracked there, not fixed on this
branch.
