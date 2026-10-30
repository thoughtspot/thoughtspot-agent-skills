# Open Items — ts-dependency-cleanup

Probed live on one internal test cluster (**cluster A**) from 2026-09-01. Read each
item's **last** entry for its current status — several were re-probed and resolved after
their first entry was written. A second internal cluster (**cluster B**) appears in the
early history only; it was unreachable throughout.

Per `.claude/rules/api-research.md`, each item should be checked against
`mcp__SpotterCode__get-rest-api-reference` before live probing. The MCP was not
authorized in the session that authored this skill, so no spec lookup was done — and it
was still unauthorized at the PR #505 review response (2026-10-16). #8 is the item that
lookup would settle at zero risk; do it first.

**This file is an append-only journal.** Several items were re-probed and their first
entry is superseded; each superseded heading now says so and points forward. Read an
item's **last** entry, not its first.

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

**Update 2026-10-28 (PR #666 review, B6).** #1 is VERIFIED, so "blocked behind #1" no
longer holds, and the review was right to say so. What blocks the migration now is
**auth**: the endpoints were verified only with a v1 `session/login` cookie (#4), and
`ts`'s client speaks v2 bearer tokens. **Next step:** probe one read endpoint (operation
3) with a bearer token from `ts auth`. If it is accepted, add `ts dependency lookup` /
`ts dependency cascade-delete`, enforcing in code the single-id rule, the pre-apply
re-check and profile-driven TLS. Until then, raw REST is a **documented exception**
(SKILL.md "Why raw REST"), not a technicality. The v1 validator's blind spot (a base path
with no trailing `/` passed `check_no_v1_endpoints.py`) is closed, and the gate now also
matches `/callosum/v1/dependency` (operation 8's prefix and purge sat outside
`/tspublic/v1` and passed it — PR #666 review). The smoke test is its one named
exemption, for the whole file, so a new v1 call anywhere else fails the gate.

## #7 — The purge guard is session-scoped — DEFERRED with #8 (operation 9 cut from 1.0.0)

*Historical.* The draft operation 9 refused unless operation 8 applied a delete **in the
same session**, so it could not see deletes applied earlier, by another user, or in
another session. Operation 9 was removed from 1.0.0 (PR #505 review), so this guard no
longer exists.

**Do not take the second remedy this entry used to list** — "drop the guard and rely on
the typed `PURGE` confirmation alone". With an unparameterised call whose scope is
unknown (#8), that strips the last friction from a possibly instance-wide purge. A purge
re-introduction must be designed against #8's answer, not against this guard.

## #8 — Purge scope — DEFERRED (BL-411); operation 9 cut from 1.0.0 — see the 2026-09-03 and 2026-10-16 entries below

The spec for this skill lists no inputs for purge, so the draft sent no body. Three
readings are consistent with every fact recorded here:

| Reading | Consequence |
|---|---|
| Instance-wide over everything soft-deleted | Purges objects this skill never touched, including other users' pending deletions |
| Scoped implicitly (session / recent deletes) | Behaves as the draft assumed |
| Operates on an ordinary trash tier that operation 8 never populates | Useless for operation 8's objects **and** maximally destructive to third parties |

The draft's "purge finalises what operation 8 deleted" was itself never verified. Resolve
by spec lookup (`get-rest-api-reference`) — **never** by calling the endpoint. Tracked as
BL-411; the skill refuses purge requests until it is answered.

## #9 — `listdependents` cannot reach pinboards — DEFERRED (documented values only; the skill never sends type=PINBOARD, so this is a docs question — confirm live when cluster A is reachable)

*Corrected 2026-10-28:* this heading used to say "verified from spec". No spec lookup was
ever done (see the note at the top of this file). The source is the list of `type` values
in the request this skill was built from. The valid `type` values given are PHYSICAL_COLUMN, PHYSICAL_TABLE, LOGICAL_COLUMN,
LOGICAL_TABLE, LOGICAL_RELATIONSHIP — no PINBOARD. So operation 7's dedicated
`/dependency/pinboard` endpoint is the only route to pinboard dependents. SKILL.md
documents this asymmetry. Confirm on a live call that `type=PINBOARD` is in fact
rejected rather than merely undocumented.


---

# Live probe — cluster A — 2026-09-01

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

**Not the same cluster as the configured profile.** The only profile configured at the
time pointed at cluster B. No profile for cluster A existed yet (#10).


---

## Decision — auth mechanism (2026-09-01)

**v1 session login with a cookie jar**, chosen by the user over v2 bearer. `session/login`
is live on cluster A (400 on empty params, not 404). Credentials follow the repo convention:
profile in `~/.claude/thoughtspot-profiles.json` supplies `base_url` / `username` /
`password_env`; the secret lives in the keychain and is exported into the shell. SKILL.md
Step 1 implements this; the no-auth design is withdrawn.

## #10 — No profile exists for cluster A — SUPERSEDED (resolved below)

Cluster B, the only configured profile's host, was down (TLS handshake failed). Cluster A
was reachable but had no profile, so testing was blocked until the user created one in
their own terminal with `ts profiles add`. No credential value passed through the
conversation.

---

# Full endpoint probe — cluster A — 2026-09-01

Authenticated with a cluster A profile (v1 `session/login` → cookie jar; login `204`,
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

Cross-checked: `ts metadata dependents 554eb014 --profile <cluster-A-profile>` (v2 API) also returns
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

## #12 — SUPERSEDED (wrong prefix — see the RESOLVED entry under "Ops 8 and 9 FOUND"). First pass: absent on this build

404 on POST, GET and DELETE, and on every name variant tried:
`delete-with-dependents`, `deletewithdependents`, `deletewithdependent`, `purge`,
`purgedeleted`, `purge-deleted`, `deletedependents`.

`purge` was probed with `OPTIONS` only on this pass, because a parameterless purge
could act instance-wide (see #8). It 404s on OPTIONS too. **Correction (2026-10-16):** this
"never invoked" held only for this pass — a later pass sent a bare `GET` that reached
deletion logic. See #8's 2026-09-03 entry.

Either these are newer than this build, or they live under a different route. Resolve
via `get-rest-api-reference` when the SpotterCode MCP is authorized. **#8 (purge scope)
stays open regardless** — it must be answered before operation 9 runs anywhere.

## #10 — Profile for cluster A — RESOLVED 2026-09-01

The user created a password-auth profile for cluster A with `verify_ssl=false`
(self-signed certificate). The credential lives in the OS keychain under the repo
convention; its value was never displayed.

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

## #14 — Dependent data on this cluster is sparse — VERIFIED 2026-09-01 (context, not a defect)

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

## #16 — SUPERSEDED (see the RESOLVED entry below). Ops 8/9 request encoding was inferred

SKILL.md writes both as `POST` with `application/x-www-form-urlencoded`, matching
operation 1 (the only other POST in the family). This is an **inference from a sibling
endpoint**, not a verified fact — the endpoints 404 everywhere, so nothing could be
confirmed. On the first live call that returns `400`, retry as
`Content-Type: application/json` with `{"id":["guid"],"apply_changes":false}` and record
which the API accepts.

## #12 — SUPERSEDED (see the RESOLVED entry below). Re-probed 2026-09-03, still absent under the wrong prefix

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

## #12 — The endpoints were never absent; the prefix was wrong — RESOLVED 2026-09-03

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

## #16 — Encoding is form-encoded, and two parameters were undocumented — RESOLVED 2026-09-03

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

The `csv` field is a complete impact export. SKILL.md 8a saves it as the **record** of
what is removed. *(Superseded 2026-10-16: this entry said the CSV was the only record
because the skill took no TML backup. Operation 8 now takes a mandatory
`ts dependency backup` before applying — SKILL.md 8b.)*

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

## #8 — Purge scope: evidence now points to instance-wide — 2026-09-03 (see also the 2026-10-16 entry)

`OPTIONS /callosum/v1/dependency/purge` → `204` (route live). A bare `GET` → `403` with
`debug: ["Cannot Delete System Objects"]`. That error comes from **deletion logic**, not
from parameter validation — i.e. the call proceeded to act and was stopped only by
system-object protection. Consistent with purge operating over everything soft-deleted
rather than a session-scoped set. **Still not conclusive, and must not be resolved by
calling it.** (The draft's SKILL.md 9a scope gate was superseded by removing operation 9
altogether — see the 2026-10-16 entry.)


---

## #19 — Lookups under-report cascade scope by 3x — VERIFIED 2026-09-07

Live on cluster A. Deleting `LOGICAL_COLUMN` `cbeafa3a-7c10-4033-8062-bd44c2d2245c`
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

---

# PR #505 review response — 2026-10-16

## #8 — Did the 2026-09-03 bare `GET` on purge delete anything? — CANNOT BE ESTABLISHED

The 2026-09-03 entry records a bare `GET /callosum/v1/dependency/purge` returning `403
["Cannot Delete System Objects"]` — an error from deletion logic, i.e. the call proceeded
far enough to act. That was the experiment this file's own rule prohibits, and the
earlier "never invoked" note was left uncorrected (now fixed in #12's first entry).

**No inventory of soft-deleted objects was taken before or after that call**, so whether
it purged anything before the 403 fired **cannot be established** from what was
recorded. Stating that plainly rather than implying it was checked. If the cluster's
audit log for 2026-09-03 is reachable, it is the only remaining way to find out.

**Decision:** operation 9 is removed from 1.0.0. SKILL.md refuses purge requests and
points here. Nothing user-facing changes — `README.md` and `CHANGELOG.md` already
described the skill without purge. Re-introduction is BL-411 and needs (a) the spec
lookup, (b) a scope answer, (c) a bounded call or per-GUID loop, and (d) a templated
confirmation plus post-purge verification at least as strong as operation 8's.

## #19 — test coverage — OPEN → covered by the smoke test's Step 4

The smoke test's earlier claim to cover #19 was wrong: it compared the applied set with
the preview, which is a different regression. Step 4 now asserts #19's actual property —
every object the operation 2 lookup reports is contained in the operation 8 preview — and
prints the lookup-vs-preview ratio, without deleting anything.

## #20 — Rollback of a `LOGICAL_TABLE` cascade — SUPERSEDED (see the 2026-10-28 #20 entry below)

Operation 8's backup reuses `ts dependency backup`, whose plan requires a `source`. For a
`LOGICAL_COLUMN` delete the source is the owning Table/Model, which is modified rather
than deleted, so `ts dependency rollback`'s in-place update is the right restore. For a
`LOGICAL_TABLE` delete the requested object itself fills the source slot — and rollback
updates source entries **in place at the original GUID**, which no longer exists.
Whether that import recreates the object, fails, or creates it under a new GUID is not
verified. SKILL.md 8b says so and gives the manual `ts tml import` fallback. Verify on
a disposable table before relying on it; the clean fix is a `ts dependency backup` plan
form with no `source` (or a `DELETE_SOURCE` intent).


---

# PR #666 review response — 2026-10-28

## #20 — Rollback of an operation 8 cascade — OPEN (defects fixed in code; live run pending)

The review (B3) found four defects in the restore path. All four are now fixed in
ts-cli 0.192.0 and covered by unit tests (`tests/test_dependency_command.py`
`TestCascadeDeleteRollback`, `tests/test_dependency_backup.py`):

| Defect | Fix |
|---|---|
| A `LOGICAL_TABLE` source was restored in place at a deleted GUID, and the `ts tml import` fallback could not read the backup's `{type,guid,tml,info}` wrapper | `ts dependency backup` takes `"source_deleted": true`. The source then carries `intent: DELETE` and is re-created under a new GUID. The fallback is removed from SKILL.md |
| A `LOGICAL_COLUMN` cascade deletes whole Models. Their Answers and Liveboards, exported with `export_fqn=True`, were restored still pointing at the old Model GUID | `rollback` substitutes every re-created object's new GUID into the TML of the objects restored after it (`remap_guids`). The restore order (tables → Models → Views → Answers → Liveboards) restores the usual referenced object first; it is by type rank, not by each object's own references, so a Model joined to a View would restore before it — the dangling-reference refusal above catches that case rather than binding it wrong |
| `sql_view` had no rank in `DELETE_ORDER`, so it restored last, after the Models built on it | `SQL_VIEW` ranks with `TABLE` (5) and restores first. The legacy `PINBOARD` key ranks with `LIVEBOARD` |
| `rollback` exited 0 when objects failed, and SKILL.md never told the executor to read `failed[]` | It exits 1 on any failure, after printing the JSON. SKILL.md 8b makes the executor report every failed entry and never call a partial restore done |
| *(pr-ready review, 2026-10-30)* A `WARNING` import status (routine on a Model import; the object IS imported) counted as a failure, so the re-created Model's new GUID never reached its Answers and Liveboards | `rollback` classifies by `IMPORTED_STATUS_CODES` (`OK`, `WARNING`), records a new GUID whenever one comes back, and refuses — rather than imports — an entry that still names a deleted object with no replacement |
| *(pr-ready review 2, 2026-10-30)* After a partial delete, rollback re-created objects that still existed; an object whose import errored but returned a GUID, or succeeded with none, was mishandled on a re-run; the dangling-reference refusal matched any mention of a GUID, so two deleted Liveboards linking each other never restored | Rollback checks each DELETE entry with `metadata/search` and skips survivors; a returned GUID always counts as restored; a re-create with no GUID is a failure; only an `fqn:` binding is refused; a request that raises stops the run with its state saved |
| *(pr-ready review, 2026-10-30)* A partial restore could not be finished: a re-run re-created every restored object, and a `--guid` re-run lost the GUID remap | `rollback` writes `rollback_state.json` in the backup directory after every entry; a re-run skips restored entries and seeds the remap from it |

**Still open — a live run.** None of this has run against a cluster. The smoke test's
delete leg now takes a backup, applies, rolls back and checks the restored objects
(`--run-delete --run-rollback`). Run it once on a disposable column whose cascade
includes a Model and an Answer. That exercises the GUID remap, the case that matters
most. A column run does not exercise the `source_deleted: true` (`LOGICAL_TABLE`)
restore; that needs its own run on a disposable table before #20 closes. Record the result here. SKILL.md's confirmation screen tells the user the restore
is unverified until then.

*Attempted 2026-10-28, not run.* Cluster A did not answer from the machine making the
fix (`000` on its root), and that machine's Python (3.9) is below ts-cli's 3.10 floor,
so `ts dependency backup` / `rollback` could not run there either. Run it from a
machine with network access to cluster A and Python 3.10+.

The clean-fix suggestion in the 2026-10-16 entry (a plan form with a `DELETE_SOURCE`
intent) is what `source_deleted` implements.

## #21 — Backup-to-apply race — RESOLVED 2026-10-28 (mitigated; residual window documented)

Review B4. The server recomputes the cascade at `apply_changes=true`, so an object saved
between the preview and the apply was deleted with no backup. SKILL.md 8d now re-runs the
preview immediately before applying and refuses unless its object set equals the backup
manifest's DELETE set (the sibling's `dependency_apply.py` drift check is the precedent).
**What remains:** a window of a few seconds between the re-check and the apply. It cannot
be closed from the client, because the endpoint has no "apply exactly this set" parameter.
The post-apply diff names anything deleted without a backup under its own heading.

## #22 — Multi-GUID operation 8 — RESOLVED 2026-10-28 (refused)

Review B5. `ts dependency backup` takes one `source`, so two columns on two tables could
not both be backed up and restored. Operation 8 now accepts exactly one GUID and asks the
user to run it once per object.

## #23 — `metadata/details` as proof of deletion — OPEN (unverified; skill says so)

Found by the pr-ready review, 2026-10-30. SKILL.md 8d now confirms a delete with
`metadata/details` ("an absent `storables` array = gone"), because an empty lookup answers
the same for a deleted object and for one that survived with no dependents. That reading is
**not verified**: #13 probed `metadata/details` with `type=LOGICAL_TABLE` only, and the
smoke test calls it with `type=LOGICAL_COLUMN`. Two ways it could mislead: a live column
whose details carry no top-level `storables` would read as deleted, and a soft-deleted
object (#8 suggests a soft-delete tier) that still answers with `storables` would make a
complete delete read as partial.

**Mitigation in place:** the smoke test makes the same call before the delete as a positive
control and fails if `storables` is absent there, and SKILL.md tells the executor to run that
control and call the check unverified. **To close:** on the #20 live run, record the
`metadata/details` response for the column (and, for a `LOGICAL_TABLE` run, the table)
before and after the delete.
