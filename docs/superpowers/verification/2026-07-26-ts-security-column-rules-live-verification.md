# `ts security column-rules` -- live verification

**Date:** 2026-07-27
**Cluster:** `nebula-damian-alias`, profile `nebula-damian-alias`
**Authenticated as:** `tsadmin` (ADMINISTRATION), same session Org (`Primary`) as the `ts share`
verification (`docs/superpowers/verification/2026-07-26-ts-share-live-verification.md`)
**CLI:** ts-cli 0.109.0 from branch `feat/ts-security-column-rules`
**Tables under test:** `T1`, `T2`, `T3_PUBLISH` (design spec §8's chosen set)
**Orgs on the cluster:** `Primary` (0), `ORG1` (12750490), `ORG2` (535312919), `ORG3` (443705360)

**Cluster state: returned to baseline, proven by a final read.** See §9.

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
object) stays open -- see §8.

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

## 10. Open items

| # | Item | Status |
|---|---|---|
| 1 | §8 Q6 -- the refusal shape for CSR on a published object | OPEN -- needs a table published first. Not published on this cluster (see Scope note); this is the same gap the `ts share` verification left open for an end-to-end grant on a published object in a tenant Org. |
| 2 | Carried forward from the `ts share` verification: does a table-level `NO_ACCESS` clear existing column grants? | OPEN -- untested here too. Unrelated to CSR's own mechanism, but cheap to settle alongside item 1 once a published object is available. |

Neither blocks `ts security column-rules`. Both are worth resolving before
`ts-security-columns` (parent spec §4) needs to reason about published objects.
