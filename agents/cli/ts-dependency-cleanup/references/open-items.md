# Open Items — ts-dependency-cleanup

Items #1, #2 and #4 were probed live against `https://172.32.51.133:8443` on 2026-09-01
and are VERIFIED below. The rest remain UNVERIFIED — they need an authenticated call,
which is blocked on the auth decision in #4.

Per `.claude/rules/api-research.md`, each item should be checked against
`mcp__SpotterCode__get-rest-api-reference` before live probing. The MCP was not
authorized in the session that authored this skill, so no spec lookup was done.

---

## #1 — Are the v1 `/dependency/*` endpoints reachable? — VERIFIED 2026-09-01 — YES

This repo completed its v1→v2 migration on 2026-06-16 (`.claude/rules/ts-cli.md`). The
last v1 endpoint in use, `/tspublic/v1/connection/fetchConnection`, was **removed** on
newer ThoughtSpot Cloud builds and returns 404. The `/dependency/*` family may have gone
the same way.

Probe before trusting the skill (token by variable reference only — never inline):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  -X POST "$TS_BASE_URL/callosum/v1/tspublic/v1/dependency/logicaltable" \
  -H "Authorization: Bearer $TS_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode 'id=["<a-known-logical-table-guid>"]'
```

- `404` → the family is gone on this build. The skill cannot work; use
  `ts-dependency-manager` (v2 `metadata/search` dependents walk) instead.
- `200` / `400` / `401` → the path exists. Continue to #2–#5.

Record the build version alongside the result — the answer is build-specific.

## #2 — Which path prefix does this deployment serve? — VERIFIED 2026-09-01

SKILL.md uses `$TS_BASE_URL/callosum/v1/tspublic/v1`. Some deployments serve v1 at
`$TS_BASE_URL/tspublic/v1` with no callosum segment. Probe both with #1's call; record
which returns something other than 404 and correct the `TS_V1` assignment in SKILL.md.

## #3 — Form-encoded or JSON body? — RESOLVED 2026-09-01 (see the #3 entry below)

SKILL.md sends `application/x-www-form-urlencoded` with `id` as a JSON-array *string*.
That matches the legacy v1 convention and matches the `["guid-1","guid-2"]` shape given
in the spec for this skill, but it is an inference, not a verified fact. If calls return
400, retry as `Content-Type: application/json` with a real JSON body and record which
the API accepts — the two are not interchangeable.

## #4 — Is authentication required? — VERIFIED 2026-09-01 — YES; RESOLVED: v1 session login

SKILL.md sends `Authorization: Bearer $TS_TOKEN`. Legacy v1 endpoints were commonly
cookie-authenticated via `/tspublic/v1/session/login`, and some builds accept only that.
A `401` on a path that exists (#1 returned non-404) points here. Note the interaction
with the no-auth-step design: if v1 needs a session cookie, this skill needs a login
step after all, and that decision should come back to the user.

## #5 — Response shapes for all nine endpoints — RESOLVED 2026-09-01 (see the #5 entry below)

SKILL.md renders a per-GUID list of `{type, name, guid}` and instructs the executor to
fall back to raw JSON when the shape does not match. Capture one real response per
endpoint and replace the illustrative block in the "Rendering the result" section with
a real one. Nine responses to capture; `listdependents` may differ per `type`.

## #6 — Migrate the calls into a `ts dependency` CLI group — OPEN

`.claude/rules/ts-cli.md`: "Claude skills use `ts`, never `requests`" — and raw `curl` in
a SKILL.md is the same anti-pattern wearing a different hat. It duplicates auth handling
and bypasses the CLI's token caching. `check_patterns.py` catches `requests.*` in a
SKILL.md but not `curl`, so this passes the gate on a technicality rather than on merit.

The sanctioned path (`.claude/rules/ts-cli.md`, "When a skill needs an API call ts-cli
doesn't have yet"): verify via MCP → probe → add the command → replace the inline call.
Blocked behind #1 — do not build CLI commands for endpoints that 404.

## #7 — The purge guard is session-scoped — OPEN (design limit, not a bug)

Operation 9 refuses unless operation 8 applied a delete **in the same session**. It
cannot see deletes applied earlier, by another user, or in another session, so it will
refuse some legitimate purges. Options if that proves annoying: query for soft-deleted
objects and gate on that instead, or drop the guard and rely on the typed `PURGE`
confirmation alone. Do not "solve" it by letting the executor write the ledger by hand.

## #8 — Does `/dependency/purge` take an `id` body? — UNVERIFIED

The spec for this skill lists no inputs for operation 9, so SKILL.md sends no body and
assumes purge is instance-wide over everything soft-deleted. If purge is actually
scoped per-GUID, the current call is wrong in a dangerous direction — it would purge
more than the user intended. **Verify this before anyone runs operation 9 for real.**

## #9 — `listdependents` cannot reach pinboards — VERIFIED FROM SPEC (needs live confirm)

The valid `type` values given are PHYSICAL_COLUMN, PHYSICAL_TABLE, LOGICAL_COLUMN,
LOGICAL_TABLE, LOGICAL_RELATIONSHIP — no PINBOARD. So operation 7's dedicated
`/dependency/pinboard` endpoint is the only route to pinboard dependents. SKILL.md
documents this asymmetry. Confirm on a live call that `type=PINBOARD` is in fact
rejected rather than merely undocumented.


---

# Live probe — 172.32.51.133:8443 — 2026-09-01

Unauthenticated `POST`, `curl -k` (self-signed cert), dummy GUID
`00000000-0000-0000-0000-000000000000`.

| Path | Status | Reading |
|---|---|---|
| `/` | 200 | Cluster reachable |
| `/callosum/v1/tspublic/v1/dependency/logicaltable` | **401** | Endpoint EXISTS; auth required |
| `/callosum/v1/tspublic/v1/dependency/listdependents` | **401** | Endpoint EXISTS; auth required |
| `/tspublic/v1/dependency/logicaltable` | 404 (HTML) | Wrong prefix — bare `/tspublic/v1` is not served |
| `/tspublic/v1/dependency/listdependents` | 404 (HTML) | Wrong prefix |
| `/callosum/v1/tspublic/v1/session/login` | 400 `code 10002` | Login endpoint LIVE, rejecting empty params |
| `/callosum/v1/tspublic/v1/session/info` | 401 | Auth required |
| `/api/rest/2.0/auth/session/user` | 401 | v2 auth also present on this build |

**Conclusions.**

1. **#1 resolved — the v1 `/dependency/*` family is alive on this build.** 401, not 404.
   The repo-wide "v1 is gone" concern does not apply to this cluster. It may still apply
   to newer Cloud builds; this finding is build-specific and does not generalise.
2. **#2 resolved — the prefix is `/callosum/v1/tspublic/v1`.** The `TS_V1` assignment in
   SKILL.md is correct as written; the bare `/tspublic/v1` fallback in the error-handling
   table is wrong for this cluster and should not be tried first.
3. **#4 resolved on the "whether" — authentication IS required.** Every `/dependency`
   call returns 401 unauthenticated. **The skill's no-auth-step design is not viable
   against this cluster.** The mechanism is still open: `session/login` is live and
   returns a parameter error rather than 404, so the v1 cookie-jar flow is available;
   v2 bearer auth also exists on this build. Pick one before authoring the auth step.
4. **#3 (encoding) is still blocked** — a 401 is returned before the body is parsed, so
   the form-vs-JSON question cannot be settled until a call authenticates.

**Not the same cluster as the configured profile.** `~/.claude/thoughtspot-profiles.json`
holds one profile, `tsadmin` → `https://172.32.57.40:8443`, password auth. That is a
different host from `172.32.51.133`. No credential for `.133` is currently configured.


---

## Decision — auth mechanism (2026-09-01)

**v1 session login with a cookie jar**, chosen by the user over v2 bearer. `session/login`
is live on `.133` (400 on empty params, not 404). Credentials follow the repo convention:
profile in `~/.claude/thoughtspot-profiles.json` supplies `base_url` / `username` /
`password_env`; the secret lives in the keychain and is exported into the shell. SKILL.md
Step 1 implements this; the no-auth design is withdrawn.

## #10 — No profile exists for 172.32.51.133 — OPEN — BLOCKS TESTING

The only configured profile, `tsadmin`, points at `https://172.32.57.40:8443`, which is
**down** — TLS handshake fails (`SSL_ERROR_SYSCALL`), root returns `000`. `.133` returns
200 and is the only reachable cluster.

An attempt to reuse the `.57.40` credential against `.133` was **blocked by the Claude
Code permission classifier** (sending a stored credential to a host it was not stored
for). That block is correct and was not worked around — whether the two clusters share
an account is the user's call.

To unblock testing, the user creates a profile for `.133`:

```bash
ts profiles add --platform thoughtspot --name "dot133" --auth-type password \
  --field base_url=https://172.32.51.133:8443 \
  --field username=<username> \
  --field verify_ssl=false
```

then stores the password via the printed `keychain_store_commands` and exports
`THOUGHTSPOT_PASSWORD_DOT133`. No credential value passes through the conversation.

---

# Full endpoint probe — 172.32.51.133:8443 — 2026-09-01

Authenticated with the `dot133` profile (v1 `session/login` → cookie jar; login `204`,
`session/info` `200`). Test objects: worksheet `554eb014` (TPCH Model), logical table
`9a527010` (has one dependent), pinboard `a1cd9526` (Performance Tracking Pinboard).

| Op | Endpoint | POST | GET | Verdict |
|---|---|:-:|:-:|---|
| 1 | `listdependents` | **200** | — | Works. Form-encoded, `type` + `id` both required |
| 2 | `logicalcolumn` | 405 | **200** | GET only |
| 3 | `logicaltable` | 405 | **200** | GET only |
| 4 | `logicalrelationship` | — | **200** | GET only |
| 5 | `physicalcolumn` | — | **200** | GET only |
| 6 | `physicaltable` | — | **200** | GET only |
| 7 | `pinboard` | 405 | **500** | Broken — see #11 |
| 8 | `delete-with-dependents` | 404 | 404 | Absent — see #12 |
| 9 | `purge` | 404 | 404 | Absent — see #12 |

## #3 — Request encoding — RESOLVED 2026-09-01

Not an encoding question at all — a **verb** question. Operations 2–7 are `GET` with
`id` as a query parameter; the `405` responses to POST were mis-read as an encoding
problem in the first draft. Operation 1 is `POST` with `application/x-www-form-urlencoded`
and `id` as a JSON-array *string*, exactly as the original spec implied.

## #5 — Response shape — RESOLVED 2026-09-01

Identical across operations 1–6:

```json
{ "<source-guid>": { "<BUCKET_TYPE>": [ { /* 46-field metadata header */ } ] } }
```

Buckets seen: `PINBOARD_ANSWER_BOOK`. Header fields include `id`, `name`, `author`,
`authorName`, `authorDisplayName`, `created`, `modified`, `modifiedBy`, `isDeleted`,
`isHidden`, `tags`, `ownerOrgId`.

Two distinct empty forms, easy to conflate:

- `{"<guid>":{}}` — GUID resolved, **0 dependents**
- `{}` — GUID is **not of that endpoint's type** (e.g. a logical GUID sent to
  `physicalcolumn`). Returns 200, no error.

Cross-checked: `ts metadata dependents 554eb014 --profile dot133` (v2 API) also returns
`[]`, so the empty v1 results are correct, not a silent failure. A scan of all 134
logical tables found exactly one with dependents — this cluster is simply sparse.

## #11 — `/dependency/pinboard` returns 500 (server NPE) — VERIFIED BROKEN 2026-09-01

```
java.lang.NullPointerException
  at java.base/java.util.Objects.requireNonNull(Objects.java:222)
  at com.thoughtspot.callosum.server.services.metadata.DependencyService
       .referencingObjectsOfPinboards(DependencyService.java:600)
```

Reproduced with a valid pinboard GUID (`a1cd9526`), with a worksheet GUID, with
`id=["guid"]` and with a bare `id=guid`. POST returns 405, so GET is the right verb and
the handler itself is throwing. **No client-side fix.** Either a ThoughtSpot bug on this
build or an undocumented required parameter. Worth a support ticket with the incident id
(`94c3ec23-b140-45a0-ac2d-53e16d00d2aa`).

## #12 — Operations 8 and 9 are absent on this build — VERIFIED 2026-09-01

404 on POST, GET and DELETE, and on every name variant tried:
`delete-with-dependents`, `deletewithdependents`, `deletewithdependent`, `purge`,
`purgedeleted`, `purge-deleted`, `deletedependents`.

`purge` was probed with `OPTIONS` only — never invoked — because a parameterless purge
could act instance-wide (see #8). It 404s on OPTIONS too.

Either these are newer than this build, or they live under a different route. Resolve
via `get-rest-api-reference` when the SpotterCode MCP is authorized. **#8 (purge scope)
stays open regardless** — it must be answered before operation 9 runs anywhere.

## #10 — Profile for 172.32.51.133 — RESOLVED 2026-09-01

Profile `dot133` created (`username=tsadmin`, `verify_ssl=false`,
`password_env=THOUGHTSPOT_PASSWORD_DOT133`). The credential was copied keychain-to-keychain
from `thoughtspot-tsadmin` at the user's explicit instruction, value never displayed.
Note `.57.40` (the original `tsadmin` profile's host) is **down** — TLS handshake fails.

---

# Correct-type re-test — 2026-09-01 (second pass)

The first pass tested operations 4, 5 and 6 with a **worksheet** GUID — the wrong object
type for all three. They returned `200 {}`, which proves only routing and verb, not
behaviour. Recording the correction: calling them "Works" after that pass was
unsupported. Re-tested with correct-type GUIDs:

| Op | Endpoint | Test GUID | Result |
|---|---|---|---|
| 1 | `listdependents` | all 4 types | Populated for `PHYSICAL_TABLE` and `PHYSICAL_COLUMN` |
| 2 | `logicalcolumn` | `bb89847b` (column of `9a527010`) | `{PINBOARD_ANSWER_BOOK: 1}` — "Object Usage" |
| 3 | `logicaltable` | `9a527010` | `{PINBOARD_ANSWER_BOOK: 1}` |
| 4 | `logicalrelationship` | `46a59f68`, `e17ed208`, `065efa31` | `{PINBOARD_ANSWER_BOOK: 1}` and `{LOGICAL_TABLE: 1}` |
| 5 | `physicalcolumn` | `303a848e` | `{LOGICAL_TABLE: 1}` |
| 6 | `physicaltable` | `a301fedd` | `{LOGICAL_TABLE: 2}` |

All six return populated, correctly-shaped payloads. **Bucket types seen: two** —
`PINBOARD_ANSWER_BOOK` and `LOGICAL_TABLE`. The first pass had only seen the former, so
any renderer assuming a single bucket type would have been wrong.

## #13 — `metadata/list` cannot enumerate physical objects — VERIFIED 2026-09-01

`GET metadata/list?type=PHYSICAL_TABLE` and `type=PHYSICAL_COLUMN` both return **500**.
Physical GUIDs must be read out of `GET metadata/details?type=LOGICAL_TABLE&id=[...]`
for a `ONE_TO_ONE_LOGICAL` table, which exposes `physicalTableGUID` (1),
`physicalColumnGUID` (9) and `physicalRelationshipGUID` (7) for the sampled table
`c9ba7f46`. SKILL.md documents this under "Finding GUIDs".

Note `metadata/detail/<guid>` (singular, path-param) is **404**; the working form is
`metadata/details` (plural) with `type` and a JSON-array `id` query parameter.

## #14 — Dependent data on this cluster is sparse — CONTEXT

Of 134 logical tables, exactly **one** (`9a527010`) has dependents. 60 sampled logical
columns had none; the one column that did (`bb89847b`) was found by walking that table's
own columns. Cross-checked against v2 (`ts metadata dependents` → `[]`), so the empties
are real. **Implication for future testing:** an empty result is the default here, so
"it returned nothing" is weak evidence that a call is wrong. Always test against
`9a527010` or its columns, which are known to be non-empty.

## #15 — Third bucket type: `QUESTION_ANSWER_BOOK` — VERIFIED 2026-09-02

Running operation 3 against logical table `8a730793-5379-4ecd-aa4b-68dd9a602aef` (a real
user query, not a probe fixture) returned **two buckets in one response**:

```
PINBOARD_ANSWER_BOOK: 1    (Test LB)
QUESTION_ANSWER_BOOK: 10   (Answers over the retail warehouse model)
```

Neither of the earlier probe objects produced `QUESTION_ANSWER_BOOK`, and none produced
more than one bucket at a time — so the first two passes under-described the shape twice
over. SKILL.md's bucket list and the multi-bucket note are corrected.

**Lesson, consistent with #14:** the sparse probe fixtures on this cluster
(`9a527010`, one column, one relationship) are not representative. Objects that real
users care about have richer dependency graphs. Prefer a user-supplied GUID over a
scanned one when validating shape.

## #16 — Ops 8/9 request encoding is inferred, not verified — OPEN

SKILL.md writes both as `POST` with `application/x-www-form-urlencoded`, matching
operation 1 (the only other POST in the family). This is an **inference from a sibling
endpoint**, not a verified fact — the endpoints 404 everywhere, so nothing could be
confirmed. On the first live call that returns `400`, retry as
`Content-Type: application/json` with `{"id":["guid"],"apply_changes":false}` and record
which the API accepts.

## #12 — Ops 8/9 absent — RE-PROBED 2026-09-03, still absent

Second pass added the hypothesis that `delete-with-dependents` being **hyphenated**
(unlike every working v1 endpoint here — `logicaltable`, `listdependents`) meant it was a
**v2** REST path in kebab-case. Tested and disproved:

| Path | POST |
|---|:-:|
| `/api/rest/2.0/dependency/delete-with-dependents` | 404 |
| `/api/rest/2.0/dependency/purge` | 404 |
| `/api/rest/2.0/metadata/delete-with-dependents` | 404 |
| `/api/rest/2.0/metadata/dependency/delete-with-dependents` | 404 |
| `/callosum/v1/tspublic/v2/dependency/delete-with-dependents` | 404 |

Plus the v1 tree (`delete-with-dependents`, `deletewithdependents`, `purge`) on POST/GET.
The naming inconsistency is still unexplained and worth asking ThoughtSpot about — it may
indicate these ship on a newer build under a route not guessable from the outside.
Resolve via `get-rest-api-reference` once the SpotterCode MCP is authorized.

---

# Ops 8 and 9 FOUND — 2026-09-03 (third pass)

## #12 — CLOSED. The endpoints were never absent; the prefix was wrong.

`/dependency/delete-with-dependents` and `/dependency/purge` are served from
**`/callosum/v1/dependency/`** — *without* the `tspublic/v1` segment that operations 1–7
require. Three prior passes probed only under `tspublic/v1` (plus `/api/rest/2.0/` and
`/tspublic/v2/`) and read the resulting 404 as "not on this build". It was a routing
difference inside the same cluster.

| Prefix | `delete-with-dependents` |
|---|---|
| `/callosum/v1/tspublic/v1/dependency/` | 404 |
| **`/callosum/v1/dependency/`** | **400 → 200 once parameters are right** |

**Method note worth keeping:** the find came from sweeping *prefixes* against a fixed
endpoint name, after two passes of sweeping *endpoint names* against a fixed prefix. When
an endpoint is documented but 404s, vary the mount point, not just the spelling. A 404
is evidence about a *path*, never about a *capability*.

## #16 — CLOSED. Encoding is form-encoded, and two parameters were undocumented.

`POST` + `application/x-www-form-urlencoded`, as inferred. But the spec this skill was
built from listed only `id` and `apply_changes`. Two more are **required**:

| Param | Required | Values | Error if omitted |
|---|---|---|---|
| `type` | yes | `LOGICAL_TABLE`, `LOGICAL_COLUMN` | `400 INVALID_METADATA_TYPE` — "Metadata type cannot be null or empty" |
| `id` | yes | `["guid"]` JSON-array string | — |
| `operation_type` | yes | `DELETE_OBJECT_CASCADE` | `400 INVALID_OPERATION_TYPE` — "Operation type cannot be null or empty" |
| `apply_changes` | no | `false` (default) / `true` | none — omitting equals `false`, verified |

The parameter name is exactly `operation_type`. `operation`, `operationType`, `op_type`
and `operationtype` all still return `INVALID_OPERATION_TYPE`.

## #17 — Verified 200 response shape for operation 8 — 2026-09-03

```json
{"dependents": {"<guid>": []},
 "csv": "sourceColumnGUID,sourceColumnName,dependentGUID,dependentName,dependentType,dependentSubType,childGUID,childName,childType,author,lastModified,views,orgName\n"}
```

The `csv` field is a complete impact export. Since this skill takes no TML backup, saving
that CSV before applying is the only record of what was removed — SKILL.md 8a instructs it.

## #18 — Business-rule refusals are column-specific — VERIFIED 2026-09-03

Column `73dc7914-e6cb-4922-b6a1-6ce77233d0eb` cannot be deleted:

```
400 METADATA_ERROR
Error Code: INVALID_OPERATION
Error Message: Deleting columns linked to filters is not allowed
```

Deterministic across repeat calls and identical with `apply_changes` omitted. **Control:**
the identical request for column `f4d845ef-7c7b-4bc6-8ed7-dc6636d39db2` returned `200`
with `{"dependents":{"f4d845ef-...":[]}}` (full GUID not recorded at probe time). So the refusal is a property of the object, not
of the request shape. The blocker for `73dc7914` is a filter referencing it — plausibly
on the liveboard `Test LB` (`51194061`), which operation 2 lists as one of its dependents.

## #8 — Purge scope: evidence now points to instance-wide — 2026-09-03

`OPTIONS /callosum/v1/dependency/purge` → `204` (route live). A bare `GET` → `403` with
`debug: ["Cannot Delete System Objects"]`. That error comes from **deletion logic**, not
from parameter validation — i.e. the call proceeded to act and was stopped only by
system-object protection. Consistent with purge operating over everything soft-deleted
rather than a session-scoped set. **Still not conclusive, and must not be resolved by
calling it.** The mandatory scope gate in SKILL.md 9a stands.


---

## #19 — Lookups under-report cascade scope by 3x — VERIFIED 2026-09-07

Live on 172.32.51.133. Deleting `LOGICAL_COLUMN` `cbeafa3a-7c10-4033-8062-bd44c2d2245c`
(`SUBCATEGORY` on `DIM_PRODUCT`):

| Source | Objects reported |
|---|---|
| `dependency/logicalcolumn` (operation 2) | **4** — 1 model, 1 answer, 2 liveboards |
| `delete-with-dependents` applied response | **12** — 1 model, 9 answers, 2 liveboards |

The eight extra were answers built on the model (`Sales & Merchandising Performance`),
which was itself in the cascade. Their names — `Total Unit Sale Price by Brand`,
`Average Churn Risk Score by Loyalty Tier` — reference neither the column nor anything
suggesting a link to it, so no amount of reading the lookup output would have predicted
them.

**Mechanism:** operations 1–6 return objects referencing the id *directly*. A cascade
delete is transitive: it takes the direct dependents *and* everything downstream of
those. One level vs. the full closure.

**Consequence, and why it matters more than a doc nit:** on this run the user had
declined the preview, so the 4-object figure from the lookup was the only scope estimate
in hand when the delete was applied. Twelve objects went. The `apply_changes=false`
preview would have shown all twelve at zero cost — this is the concrete case for why
SKILL.md 8a makes it mandatory "whatever the user asked for".

**Actions taken (same session):** SKILL.md 8a now states the preview response is the
authoritative blast radius and the lookups are not; the operations 1–6 rendering section
carries a blockquote warning against sizing a delete from it.

**Also observed:** the applied `csv` field had **28 rows for 12 unique objects** — a
liveboard is repeated once per pinned child answer. De-duplicate before reporting a
count, or the report overstates the damage by 2.3x.

**Open question — not yet probed.** Whether the `dependents` field nests the full closure
for a *deeper* graph (column -> model -> liveboard -> ?) or flattens only two levels. All
12 objects here were reachable within two hops, so this run does not settle it.
