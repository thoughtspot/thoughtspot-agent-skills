# `ts share` — live verification

**Date:** 2026-07-26
**Cluster:** `nebula-damian-alias` (`https://172.32.62.254:8443`), profile `nebula-damian-alias`
**Authenticated as:** `tsadmin` (ADMINISTRATION), session Org `Primary`
**CLI:** ts-cli 0.108.0 from branch `feat/ts-share`, installed into an isolated venv so the
operator's global `ts` was left untouched
**Object under test:** `T2_PUBLISH` (`d2c12c11-6560-4810-96b8-4b902bbb82dc`),
`ONE_TO_ONE_LOGICAL`, 25 columns
**Orgs on the cluster:** `Primary` (0), `ORG1` (12750490), `ORG2` (535312919), `ORG3` (443705360)

**Cluster state: returned to baseline, proven by diff.** See §7.

---

## Scope note

At verification time every `T*_PUBLISH` object had `metadata_header.orgIds == [0]` — nothing
was published to any tenant Org. Object and column grants were therefore exercised in
`Primary`, which is where the design spec's original probing also ran. The **per-Org**
machinery (name→id resolution, the org-context assertion, the per-Org group check) was
verified against `ORG1`/`ORG2` directly; applying a grant *inside* a tenant Org to a
*published* object is not covered here and remains an open item (§8).

---

## 1. `export` — object, column GUIDs, existing grants

```
$ ts share export d2c12c11-6560-4810-96b8-4b902bbb82dc -p nebula-damian-alias
resolved d2c12c11-... -> T2_PUBLISH (LOGICAL_TABLE, 25 column(s))
```

Envelope carried `subtype: ONE_TO_ONE_LOGICAL` and all 25 columns with their GUIDs
(`PROD_ID` → `56178d47-…`, `PROD_NM` → `ff2dfa4d-…`, `SUPPLIER_REGION` → `5ba36e2d-…`, …).

**Confirms** that `metadata/search` with `include_details: true` is a working source of
column GUIDs, which LOGICAL_COLUMN sharing needs and Table TML does not carry.

---

## 2. `resolve` — both granularities, and the CSV source

```
# column-level
planned 2 grant(s): 0 object-level, 2 column-level, across 1 org(s)
# object-level
planned 1 grant(s): 1 object-level, 0 column-level, across 1 org(s)
```

`--dry-run` on the column plan produced exactly one batched call:

```json
{"steps": [{"org_name": "Primary", "metadata_type": "LOGICAL_COLUMN",
  "metadata_identifiers": ["5ba36e2d-…", "ff2dfa4d-…"],
  "permissions": [{"principal": {"type": "USER_GROUP", "identifier": "Analyst"},
                   "share_mode": "READ_ONLY"}],
  "labels": ["T2_PUBLISH.SUPPLIER_REGION", "T2_PUBLISH.PROD_NM"]}],
 "message": "Access granted by ts share.", "notify_on_share": false}
```

`--source file` with a CSV mixing Orgs and granularities also planned cleanly:

```
planned 3 grant(s): 1 object-level, 2 column-level, across 2 org(s)
summary: {"orgs": ["ORG1", "Primary"], "groups": ["Analyst", "Demo Retail Group"], …}
```

---

## 3. A column grant takes effect — `LOGICAL_COLUMN` confirmed

`Analyst` had **no** prior access to `T2_PUBLISH` or any of its columns (baseline: 78 rows,
zero involving `Analyst`).

```
$ ts share apply -i grants-column.json -p nebula-damian-alias
[Primary] LOGICAL_COLUMN: T2_PUBLISH.SUPPLIER_REGION, T2_PUBLISH.PROD_NM -> Analyst=READ_ONLY
applied 1 share call(s)
```

Read-back diff against baseline — exactly six new rows, on exactly the two granted columns:

```
added:
  ('5ba36e2d-…' SUPPLIER_REGION, 'Analyst', 'READ_ONLY', shared='NO_ACCESS')
  ('5ba36e2d-…' SUPPLIER_REGION, 'guest1',  'READ_ONLY', shared='NO_ACCESS')
  ('5ba36e2d-…' SUPPLIER_REGION, 'guest2',  'READ_ONLY', shared='NO_ACCESS')
  ('ff2dfa4d-…' PROD_NM,         'Analyst', 'READ_ONLY', shared='NO_ACCESS')
  ('ff2dfa4d-…' PROD_NM,         'guest1',  'READ_ONLY', shared='NO_ACCESS')
  ('ff2dfa4d-…' PROD_NM,         'guest2',  'READ_ONLY', shared='NO_ACCESS')
removed: (none)
```

**Confirms spec §2.1** — `LOGICAL_COLUMN` is accepted and takes effect. No other column
was touched. Sharing to a group also materialises a row per member user (`guest1`,
`guest2`), which is worth knowing before diffing row counts.

Reverting with `share_mode: NO_ACCESS` returned the set to 78 rows, `RESTORED`, no extras
and nothing missing.

---

## 4. A table grant grants EVERY column — the exclusivity rule, measured

```
$ ts share apply -i grants-object.json -p nebula-damian-alias
[Primary] LOGICAL_TABLE: T2_PUBLISH -> Analyst=READ_ONLY
applied 1 share call(s)
```

Read-back diff: **78 rows added** from one table-level grant.

| Where | Rows added |
|---|---|
| The table itself | 3 (`Analyst`, `guest1`, `guest2` at `READ_ONLY`) |
| Its columns | 75 — **all 25 columns** × 3 principals |

**Confirms spec §2.2 with numbers.** One table grant conveys `READ_ONLY` on every column
in the table, so a table grant sitting beside column grants for the same (org, table,
group) does not merely overlap them — it makes the column selection meaningless. This is
the behaviour `find_exclusivity_conflicts` refuses on.

Reverted with `NO_ACCESS`; baseline restored.

---

## 5. The refusals fire, with non-zero exit

| Refusal | Command | Exit | Message |
|---|---|:-:|---|
| Table + column grants for one (org, table, group) | `share apply -i grants-conflict.json --dry-run` | **1** | `Refusing to apply: the manifest mixes table-level and column-level grants.` … `org 'Primary' / table 'T2_PUBLISH' / group 'Analyst': table grant (READ_ONLY) alongside column grant(s) on PROD_NM, SUPPLIER_REGION` |
| Group does not exist | `share resolve --org Primary --group NoSuchGroup` | **2** | `Refusing to plan: … org 'Primary': group 'NoSuchGroup' does not exist` |
| Org does not exist | `share resolve --org NoSuchOrg` | **2** | `Org 'NoSuchOrg' does not exist. Known orgs: ORG1, ORG2, ORG3, Primary` |

The conflict refusal was tested on a manifest hand-edited **after** `resolve` (the object
and column plans concatenated), which is exactly the case the duplicated check in `apply`
exists for.

---

## 6. Findings that changed the implementation

### 6.1 Org scoping by NAME silently runs in the caller's default Org — **fixed**

The first version passed `--org ORG1` straight to `ThoughtSpotClient(org=...)`.

```
$ TS_ORG=ORG1      ts auth whoami   →  current_org = {'id': 0,        'name': 'Primary'}   # WRONG, silent
$ TS_ORG=12750490  ts auth whoami   →  current_org = {'id': 12750490, 'name': 'ORG1'}      # correct
$ TS_ORG=535312919 ts auth whoami   →  current_org = {'id': 535312919,'name': 'ORG2'}      # correct
```

`auth/token/full` honours `org_id` (int) and **silently ignores** `org_identifier` (a name)
— `client.py`'s own comment says so, and this is it biting. Consequence, had it shipped: a
manifest row for `ORG1` would have had its grant applied in `Primary`, and the
group-existence check would have validated `Primary`'s groups. Both silently. This is the
worst available failure mode for a security command, and nothing in the response indicates
it happened.

**Fix:** `_resolve_org_id` resolves the name via `orgs/search` before the client is built
and refuses an unknown name; `assert_org_context` then reads the session's real Org back and
refuses on mismatch, before any grant and before the group check. Verified:

```
resolved ORG1 -> 12750490
_client_for_org('Primary') -> current_org = {'id': 0,        'name': 'Primary'}   assert OK
_client_for_org('ORG1')    -> current_org = {'id': 12750490, 'name': 'ORG1'}      assert OK
_client_for_org('ORG2')    -> current_org = {'id': 535312919,'name': 'ORG2'}      assert OK
```

The group check now demonstrably reads the right Org. `ORG1`'s groups are
`['Administrator', 'All', 'Demo Retail Group']` — no `Analyst`:

```
$ ts share resolve --org ORG1 --group Analyst …     → exit 2, "org 'ORG1': group 'Analyst' does not exist"
$ ts share resolve --org ORG1 --group "Demo Retail Group" … → exit 0, planned 1 grant(s)
```

`Analyst` **does** exist in `Primary`, so before the fix that first command would have
passed. Four regression tests cover the resolution and the assertion.

### 6.2 `shared_permission` is not the field to read — **docs corrected**

Every successful share above left `shared_permission` at `NO_ACCESS`, exactly as it was for
every principal beforehand; the granted access appeared in `permission`. The field names
say the opposite of what they do on this build.

The implementation's docstrings, `README.md` and the plan had all told the reader to verify
against `shared_permission` — which would make a working share look like a no-op. Corrected
in `share_plan.permission_rows`, `share status`, and the README: read `permission`, and
treat a principal *appearing* where it was absent as the signal.

### 6.3 `permission_type: DEFINED` hides everything — **removed**

`fetch-permissions` with `permission_type: DEFINED` returned HTTP 200 with an entry whose
`principal_permission_info` was empty, for an object with three principals on it:

```
permission_type=None:      HTTP 200, 3 principals (Administrator/su/tsadmin, MODIFY)
permission_type=DEFINED:   HTTP 200, 0 principals
permission_type=EFFECTIVE: HTTP 200, 3 principals
```

`ts share status` would have printed `[]` and read as "nobody can see this" for any object
nothing had been shared with. The parameter is no longer sent; the API's default returns
every principal and both columns.

### 6.4 An ambiguous object name is refused

Not a live finding but a hazard noticed while writing it up: resolving a *name* with
`record_size: 1` would silently pick one of two same-named tables and grant access to the
wrong data. `_resolve_object` now requires a single exact-name match and refuses ambiguity,
naming the candidate GUIDs.

---

## 7. Baseline restored

```
baseline rows 78 | final rows 78
RESTORED
```

Compared as sorted `(guid, principal_name, permission, shared_permission)` tuples across
`T2_PUBLISH` and all 25 columns: no extra rows, none missing. Every grant created during
verification was revoked with a `NO_ACCESS` manifest through the same code path.

---

## 8. Open items

| # | Item | Status |
|---|---|---|
| 1 | Apply a grant *inside* a tenant Org to a *published* object, end to end. Nothing was published on this cluster, so §3/§4 ran in `Primary`. The per-Org machinery is verified (§6.1) but not an end-to-end tenant grant | OPEN — needs a published object; this is `ts-publish-orgs` Step 12's own test |
| 2 | Does a table-level `NO_ACCESS` clear existing column grants? Determines whether a revoke-then-grant could ever be safe inside one manifest | OPEN — untested. The tool refuses the combination, so nothing depends on the answer today |
| 3 | Is `shared_permission` meaningful at all on this build, or dead? §6.2 only establishes it is not "what sharing granted" | OPEN — cosmetic; `permission` is sufficient |
| 4 | Can a group holding only column grants reach the table at all? (spec §6 item 1) | OPEN — unchanged by this work |

None block `ts share`. Items 1 and 2 are worth resolving before `ts-security-columns`
(spec §4) relies on the CLS path.
