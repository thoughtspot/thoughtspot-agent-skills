---
name: ts-dependency-cleanup
description: Inspect and cascade-delete ThoughtSpot dependency graphs through the v1 /dependency API — list who references a logical/physical column, table, relationship or pinboard, and delete one object together with everything that depends on it, behind a preview, a TML backup, a pre-apply re-check and a typed confirmation. Use this for a server-side cascade delete or a v1 dependents lookup. To remove or repoint a column while FIXING its dependents (rather than deleting them), use ts-dependency-manager instead.
---

# ThoughtSpot: Dependency Cleanup (v1 `/dependency` API)

Run `/dependency` operations against a ThoughtSpot instance: pick an operation from the
menu, supply the GUIDs, read the result. Seven read-only lookups (six work) plus one
**destructive** operation — a cascade delete (operation 8) — which **works and is
irreversible on the server**. It runs only behind a preview, a TML backup, a re-check of
the preview immediately before applying, and a typed `DELETE`.

**Which dependency skill?**

| Goal | Skill |
|---|---|
| Delete an object **and everything that depends on it**, server-side | **this skill**, operation 8 |
| See who references a column / table / relationship (v1 lookups) | **this skill**, operations 1–6 |
| Remove or repoint a column and **keep** its dependents working (edit their TML) | `ts-dependency-manager` |
| Impact report with risk rating before any change | `ts-dependency-manager` |

The two are siblings, not versions of each other: `ts-dependency-manager` uses the v2 API
and rewrites dependents; this skill uses the v1 `/dependency` family and deletes them.

> **Live-verified on one internal test cluster (2026-09-01 to 2026-09-07).** The v1
> `/dependency/*` family is present on that build — the repo-wide "v1 is gone" concern
> does not apply there. **Seven of the eight operations work, including the delete; only
> operation 7 (pinboard) is broken.** This is build-specific: re-run the probe in
> [references/open-items.md](references/open-items.md) before trusting it elsewhere.
>
> **Purge (`dependency/purge`) is deliberately not part of this release.** Its route is
> live, but it takes no parameters and its scope — possibly every soft-deleted object on
> the instance — is unverified (open item #8, BL-411). It must not be called from this
> skill.

## Operation status on the verified build

| # | Operation | Endpoint | Verb | Status |
|---|---|---|---|---|
| 1 | List dependents | `dependency/listdependents` | **POST** (form) | Works — all 4 types |
| 2 | Referencing a logical column | `dependency/logicalcolumn` | **GET** | Works |
| 3 | Referencing a logical table | `dependency/logicaltable` | **GET** | Works |
| 4 | Referencing a logical relationship | `dependency/logicalrelationship` | **GET** | Works |
| 5 | Referencing a physical column | `dependency/physicalcolumn` | **GET** | Works |
| 6 | Referencing a physical table | `dependency/physicaltable` | **GET** | Works |
| 7 | Referencing a pinboard | `dependency/pinboard` | GET | **BROKEN — 500 NPE** |
| 8 | Delete with dependents | `dependency/delete-with-dependents` † | **POST** (form) | Works — **destructive** |

† **Operation 8 is on a different prefix**: `/callosum/v1/dependency/`, *not*
`/callosum/v1/tspublic/v1/` where 1–7 live. Requesting it under the tspublic prefix
returns 404 — which is why three earlier passes wrongly recorded it as absent.
Operation 8 also requires **two parameters beyond `id`**: `type` and
`operation_type=DELETE_OBJECT_CASCADE`.

Operation 1 is the only POST among 1–7. Operations 2–7 are **GET with query
parameters** — POST returns `405 Method Not Allowed`.

Ask one question at a time for **dependent** decisions. Batch **independent** questions
into a single prompt to cut round-trips.

---

## Why raw REST (a documented exception)

`.claude/rules/ts-cli.md` says skills call ThoughtSpot through `ts`, never directly, and
the repo is otherwise free of v1 endpoints. This skill is an exception, for two reasons
that hold today:

1. **No v2 equivalent.** The `/dependency` family exists only under v1. There is nothing
   to migrate to.
2. **Cookie auth.** The endpoints were verified with a v1 `session/login` cookie. `ts`'s
   client speaks v2 bearer tokens only, and whether a bearer token is accepted here is
   unverified.

The exception is kept narrow. Only the endpoints in the status table above, plus
`session/login`, `session/info`, `session/logout`, `metadata/list` and `metadata/details`,
are called with `curl`. **Everything that protects the user from operation 8 runs through
`ts`**: the TML backup (`ts dependency backup`) and the restore (`ts dependency rollback`).
The smoke test is the one named entry in `EXEMPT_FILES` in
`tools/validate/check_no_v1_endpoints.py`.

**Exit:** open item #6. Once a bearer token is verified against these endpoints, move them
into a `ts dependency` subcommand, so the safety rules below (TLS, single id, pre-apply
re-check) are enforced in code rather than by these instructions. Then delete this
section and the validator exemption.

---

## References

| File | Purpose |
|---|---|
| [references/open-items.md](references/open-items.md) | Live probe results, verified verbs and response shapes, and the remaining unknowns |
| [../ts-dependency-manager/SKILL.md](../ts-dependency-manager/SKILL.md) Step 7 / Step 11 | The `ts dependency backup` / `ts dependency rollback` contract operation 8's backup reuses |

---

## Prerequisites

- A ThoughtSpot profile for the target cluster — run `/ts-profile-thoughtspot` if none exists
- The profile's credential env var must be set in the calling shell
- The user must have **MODIFY** or **FULL** access on any object touched by operation 8
- The `ts` CLI **v0.192.0 or later** (`pip install -e tools/ts-cli`) with the **same
  profile**. Operation 8's backup and rollback run through `ts dependency backup` /
  `ts dependency rollback`. 0.192.0 is the release whose rollback carries new GUIDs into
  the restored dependents, restores SQL Views first, and exits non-zero on a failed
  restore. Check with `ts --version`; older than 0.192.0, or no `--version` option at all
  (an older CLI) → stop and ask the user to upgrade.

Credentials follow the repo-wide convention (`.claude/rules/security.md`): the profile
in `~/.claude/thoughtspot-profiles.json` holds `base_url`, `username` and the **name** of
an env var (`password_env`); the secret itself lives in the keychain and is exported
into the shell. This skill reads the profile, then reads the env var it names.

**Never accept the password in conversation, and never echo it.** It reaches `curl`
only on **stdin** (`printenv … | curl --data-urlencode password@-`), so it never appears
in a command line, in `ps` output, in the transcript, or in a captured permission rule.

---

## Step 1 — Authenticate (v1 session login)

The v1 `/dependency/*` endpoints are **cookie-authenticated**. Bearer tokens are not used
here. Log in once per session and reuse the cookie for every later call.

Read `~/.claude/thoughtspot-profiles.json` (a top-level JSON array). If it is missing or
empty, stop and send the user to `/ts-profile-thoughtspot`.

If several profiles exist, show a numbered pick list of `name — base_url`; if exactly
one, show it and confirm. Save `{name}`, `{slug}` (the profile slug, per
`ts-profile-thoughtspot`), `{base_url}` (no trailing slash), `{username}`,
`{password_env}` and `{verify_ssl}`.

**The profile must use password auth.** v1 `session/login` takes a password. If the
profile has no `password_env` (a token or secret-key profile), stop and tell the user this
skill needs a password profile; never substitute another field for `{password_env}`.

Confirm the credential is present **without revealing it**:

```bash
[ -n "{password_env}" ] && printenv -- "{password_env}" >/dev/null \
  && echo "credential present" || echo "MISSING — export it first"
```

If it is missing, stop and tell the user to export it in their own terminal. (`printenv`
with no name lists every variable and exits 0, so the name is checked for emptiness first;
an empty name must never reach the login below, which would send the whole environment.)

### 1a — Create the session directory

**Each Bash call is a fresh shell — variables do not survive between calls.** So the
session lives in a fixed directory, and every later block re-derives its path from the
slug. It sits under `$HOME`, not the shared `/tmp`: later blocks *source* `$S/env`, so a
directory another local user could create first would run their code in the shell that
holds the password. That directory holds the cookie jar, a curl config file, and the two base URLs:

```bash
S="$HOME/.cache/ts_dep_cleanup_{slug}"
mkdir -p "$S" && chmod 700 "$S"
[ -d "$S" ] && [ ! -L "$S" ] && [ -O "$S" ] \
  || { echo "STOP: $S is not a private directory you own"; exit 1; }
{
  echo 'silent'
  echo 'show-error'
  echo "cookie = \"$S/cookies\""
  echo "cookie-jar = \"$S/cookies\""
  echo 'connect-timeout = 15'
  echo 'max-time = 120'
  if [ "{verify_ssl}" = "false" ]; then echo 'insecure'; fi
} > "$S/curlrc"
printf 'V1=%s\nD=%s\n' \
  "{base_url}/callosum/v1/tspublic/v1" \
  "{base_url}/callosum/v1/dependency" > "$S/env"
chmod 600 "$S/curlrc" "$S/env"
```

**TLS verification is decided once, here, by the profile.** `insecure` is written into
`curlrc` only when the profile sets `verify_ssl: false`. Every call below reads that file
with `curl -K`. **Never add `-k` to a call by hand.** A certificate error on a profile
without `verify_ssl: false` means the user must fix the profile or the certificate. It
does not mean you should turn verification off.

Every call also inherits a 15-second connect timeout and a 120-second total timeout, so
a hung cluster fails instead of blocking the session.

### 1b — Log in

```bash
S="$HOME/.cache/ts_dep_cleanup_{slug}"; . "$S/env"
[ -n "{password_env}" ] || { echo "STOP: no password_env"; exit 1; }
printenv -- "{password_env}" | tr -d '\n' | curl -K "$S/curlrc" -o /dev/null \
  -w 'login -> %{http_code}\n' \
  -X POST "$V1/session/login" \
  --data-urlencode "username={username}" \
  --data-urlencode "password@-" \
  --data-urlencode "rememberme=false"
chmod 600 "$S/cookies"
```

`rememberme=false`: the session ends at logout (see Cleanup) rather than outliving it.

Verify the cookie works before offering the menu:

```bash
S="$HOME/.cache/ts_dep_cleanup_{slug}"; . "$S/env"
curl -K "$S/curlrc" -o /dev/null -w 'session/info -> %{http_code}\n' "$V1/session/info"
```

`200` → proceed. `401` → the credential is wrong or expired; stop and report. Do not
retry a login automatically — repeated failures can lock the account.

The cookie jar is a live credential. Never print its contents. Cleanup logs the session
out and deletes the directory.

**Every call template below starts with the same line**:

```bash
S="$HOME/.cache/ts_dep_cleanup_{slug}"; . "$S/env"
```

---

## Step 0 — Overview

On invocation, display this before doing any work:

---
**ts-dependency-cleanup** — inspect and cascade-delete ThoughtSpot dependency graphs via the v1 `/dependency` API.

To *fix* dependents instead of deleting them, use `ts-dependency-manager`.

### Operations

```
  Read-only — inspect who references what:
    1  List dependents            requires TYPE + ID(s)
    2  Referencing a logical column        ID(s)
    3  Referencing a logical table         ID(s)
    4  Referencing a logical relationship  ID(s)
    5  Referencing a physical column       ID(s)
    6  Referencing a physical table        ID(s)
    7  Referencing a pinboard              ID(s)   [BROKEN on the verified build — 500]

  Destructive — preview, TML backup, re-check and typed confirmation, always:
    8  Delete one object with its dependents   TYPE + exactly ONE ID  [preview by default]

    Q  Quit
```

Operations 1–6 may be run in any order, repeatedly, in one session, and all work.

Operation 8 defaults to `apply_changes=false` — a preview that changes nothing. Applying
it for real requires a successful TML backup of everything in the preview, a fresh
preview that matches the backup exactly, **and** a typed `DELETE`.

Operation 7 returns a server-side 500 on the verified build. The skill reports it; it
must not substitute a different endpoint to work around it.

Ready to start? [Y / N]
---

Do not show the menu until the user confirms.

---

## Entry Point

After Step 0, show the operation menu and read one selection:

```
Which operation? Enter 1–8, or Q to quit:
```

Save `{operation}` and go to the matching section. After any operation completes,
**return to this menu** rather than exiting — these are meant to be chained.

---

## Shared — input handling

Every operation takes `id`; operations 1 and 8 also take `type`.

### Output contract — always render results in the chat

**Every object list this skill produces must be printed in the chat response, in full.**
A file in a temp/scratchpad directory is **not** a delivery channel: the user frequently
cannot open it, and for operation 8 the list is the only record of an irreversible
deletion. A CSV is a convenience *in addition to* the chat table, never instead of it.

Rules, and they apply to every operation:

1. **Print a table in the response** with one row per object: type, name, GUID (plus
   author for operation 8). Never summarise as a bare count ("12 objects deleted") and
   never point at a file path as the answer to "what was affected?".
2. **Never truncate the object list.** Long is fine. If a *CSV* has repeated rows (the
   delete response repeats a liveboard once per pinned child), de-duplicate to unique
   objects for the table, state both numbers ("28 CSV rows = 12 unique objects"), and
   show the child relationships separately.
3. **Also write the CSV** to a path outside the repo, print the path, and say plainly
   that it is session-scoped temp storage the user should copy elsewhere if they want
   to keep it.
4. If the user asks where a list is, or cannot reach the file, **paste it in the chat
   immediately** — do not re-point them at the path.
5. **Never abbreviate a GUID. Ever.** Print all 36 characters of the 8-4-4-4-12 value,
   every time, everywhere — tables, prose, summaries, confirmation prompts, error
   reports. Writing `cbeafa3a…` or `8a730793-…` puts a literal ellipsis in the text, so
   the user who copies it gets a truncated string **plus the ellipsis** and has to go
   hunting for the real value. A shortened GUID is not a concise GUID; it is a useless
   one. This is the single most common way this skill's output gets rendered worthless.
6. **When you need to refer to an object briefly in prose, use its name, not a shortened
   GUID** — "the Sales & Merchandising model", not "the 8a730793… model". Prose
   readability is the reason people truncate; the name solves it without breaking copy.
7. **Emit a copy-ready block after any multi-object table.** A fenced code block, one
   full GUID per line, nothing else on the line:

   ```
   8a730793-5379-4ecd-aa4b-68dd9a602aef
   51194061-9063-4842-8cc2-d98bdbce8b54
   ```

   Table cells can wrap or get visually clipped in a narrow terminal; a fenced block
   copies cleanly and is what the user actually feeds back into the next command. When
   the ids are needed as an `id` argument, also offer the ready-made JSON array form.

### Finding GUIDs

Users rarely have GUIDs to hand. Sourcing them is **not uniform across types** — this
is verified, and the physical case is the awkward one:

| Type needed | How to get it |
|---|---|
| `LOGICAL_TABLE`, `LOGICAL_COLUMN`, `LOGICAL_RELATIONSHIP`, pinboards | `GET metadata/list?type=<TYPE>&batchsize=N` — works directly |
| `PHYSICAL_TABLE`, `PHYSICAL_COLUMN` | **`metadata/list` returns 500 for these.** Instead call `GET metadata/details?type=LOGICAL_TABLE&id=["<one-to-one-table-guid>"]` and read `physicalTableGUID` / `physicalColumnGUID` out of the response |

```bash
S="$HOME/.cache/ts_dep_cleanup_{slug}"; . "$S/env"
# logical types — direct
curl -K "$S/curlrc" -G "$V1/metadata/list" \
  --data-urlencode "type=LOGICAL_COLUMN" --data-urlencode "batchsize=50"

# physical types — via a one-to-one logical table's details
curl -K "$S/curlrc" -G "$V1/metadata/details" \
  --data-urlencode "type=LOGICAL_TABLE" --data-urlencode 'id=["<table-guid>"]'
```

Offer to look GUIDs up this way rather than demanding the user paste them.

### Collecting `id`

`id` is **mandatory** and is a JSON array of GUID strings — `["guid-1", "guid-2"]` —
even for a single GUID. Prompt:

```
Enter one or more GUIDs, comma-separated:
```

(For operation 8, prompt for exactly one — see its parameter table.)

Build the array from the answer and show it back before calling:

```
id = ["32c062cb-9586-43ff-bc66-bceed7529caf", "7f1e0a44-1b2c-4d3e-9f80-aa11bb22cc33"]

Proceed? (Y / N):
```

Reject and re-prompt if the list is empty, or if any entry is not a 36-character
8-4-4-4-12 hex GUID. Do not silently drop a malformed entry — name it and ask again.

### Collecting `type` (operation 1)

`type` is **mandatory** for operation 1. (Operation 8 takes a narrower set — see its
parameter table.) Valid values, offered as a numbered pick:

```
  1  PHYSICAL_COLUMN
  2  PHYSICAL_TABLE
  3  LOGICAL_COLUMN
  4  LOGICAL_TABLE
  5  LOGICAL_RELATIONSHIP
```

Reject anything outside this set — do not pass a free-text value through.

> **Note — `PINBOARD` is not a documented `type`.** Operation 1 cannot reach pinboards;
> use operation 7, which has its own endpoint. Whether the server rejects
> `type=PINBOARD` or merely leaves it undocumented is unverified (open item #9) — do not
> send it.

### The call template

Every operation uses the same shape — only the path and body differ:

Operations 2–7 are **GET**, with the id array as a query parameter:

```bash
S="$HOME/.cache/ts_dep_cleanup_{slug}"; . "$S/env"
curl -K "$S/curlrc" -G "$V1/dependency/{endpoint}" \
  --data-urlencode 'id=["guid-1","guid-2"]' \
  -w '\n%{http_code}\n'
```

Operation 1 is **POST**, form-encoded, and additionally takes `type`:

```bash
S="$HOME/.cache/ts_dep_cleanup_{slug}"; . "$S/env"
curl -K "$S/curlrc" -w '\n%{http_code}\n' \
  -X POST "$V1/dependency/listdependents" \
  --data-urlencode 'type={TYPE}' \
  --data-urlencode 'id=["guid-1","guid-2"]'
```

Prefix, verbs and encoding are all live-verified. A `405` means the wrong verb — check
the status table; do not switch encoding.

Print the HTTP status alongside the body. On a non-2xx, show the status and response
verbatim, then return to the menu — never retry silently and never fall back to a
different endpoint. A curl exit code of `28` is a timeout: report it as such.

---

## Operations 1–7 — read-only lookups

These seven differ only in endpoint and inputs; the flow is identical. Collect inputs,
confirm, call, render.

| # | Operation | Endpoint | Verb | Inputs |
|---|---|---|---|---|
| 1 | List dependents | `/dependency/listdependents` | POST | `type` + `id` |
| 2 | Referencing a logical column | `/dependency/logicalcolumn` | GET | `id` |
| 3 | Referencing a logical table | `/dependency/logicaltable` | GET | `id` |
| 4 | Referencing a logical relationship | `/dependency/logicalrelationship` | GET | `id` |
| 5 | Referencing a physical column | `/dependency/physicalcolumn` | GET | `id` |
| 6 | Referencing a physical table | `/dependency/physicaltable` | GET | `id` |
| 7 | Referencing a pinboard | `/dependency/pinboard` | GET | `id` — **500 on the verified build** |

**Operation 7 is broken server-side.** It returns `500` with a `NullPointerException` in
`DependencyService.referencingObjectsOfPinboards` for every id form tried, including
valid pinboard GUIDs. Report it and move on — there is no client-side fix (open item #11).

### Rendering the result

**Verified response shape** (identical for operations 1–6):

```json
{ "<source-guid>": { "<BUCKET_TYPE>": [ { ...full metadata header... } ] } }
```

Keyed by the source GUID, then bucketed by dependent object type. Buckets observed
live: `PINBOARD_ANSWER_BOOK` (liveboards), `QUESTION_ANSWER_BOOK` (answers) and
`LOGICAL_TABLE` (the physical endpoints return the logical tables built on them). A
single response can carry several buckets at once. Each entry is a **46-field**
metadata header — `id`, `name`, `authorDisplayName`, `created`, `modified`, `isDeleted`
and much else. Render every object in the chat per the Output contract — the useful
fields, not the whole header:

```
Dependents of 9a527010-0f4c-4b1a-9c33-6f2b1d8e4a77 (LOGICAL_TABLE):  1 object

  PINBOARD_ANSWER_BOOK   Object Usage   74852035-6b1e-4d92-8a07-3c5f9e2b1d40   System User

Copy-ready GUIDs:
74852035-6b1e-4d92-8a07-3c5f9e2b1d40
```

Two empty forms mean different things, and the difference matters:

| Response | Meaning |
|---|---|
| `{"<guid>":{}}` | The GUID was found; it genuinely has **0 dependents** |
| `{}` | The GUID is **not of the endpoint's type** — e.g. a logical GUID sent to `physicalcolumn`. Not an error, and easy to misread as "no dependents" |

Say "0 dependents" explicitly for the first, and "wrong object type for this endpoint"
for the second. An empty section reads like a failed call.

> **These lookups are not a delete blast radius.** They report objects referencing the
> id *directly*. A cascade delete also takes everything downstream of those objects, so
> the real count can be several times larger — 4 reported vs 12 deleted, live on
> 2026-09-07 (see open item #19). If the user's goal is a delete, get the scope from
> operation 8's `apply_changes=false` response, never from here.

---

## Operation 8 — Delete one object with its dependents

**Endpoint (verified 2026-09-03):**

```
POST {base_url}/callosum/v1/dependency/delete-with-dependents
```

Note the prefix: **`/callosum/v1/dependency/`** (`$D`) — *not*
`/callosum/v1/tspublic/v1/` (`$V1`), which is where operations 1–7 live and which
returns 404 for this endpoint.

### Parameters — four, all required except the last

| Param | Required | Values | Notes |
|---|---|---|---|
| `type` | **yes** | `LOGICAL_TABLE`, `LOGICAL_COLUMN` | Omit → `400 INVALID_METADATA_TYPE` |
| `id` | **yes** | `["guid"]` — **exactly one GUID** | JSON-array string. The API accepts several, but **this skill refuses more than one**: the backup takes a single source object, so a second GUID (e.g. a column on another table) could not be backed up or restored correctly. To delete several objects, run operation 8 once per object |
| `operation_type` | **yes** | `DELETE_OBJECT_CASCADE` | Omit → `400 INVALID_OPERATION_TYPE`. The name is `operation_type` — `operation`, `operationType`, `op_type` are all rejected |
| `apply_changes` | no | `false` (default), `true` | Omitting behaves exactly as `false` — verified |

If the user gives more than one GUID, say why only one is accepted and ask which to run
first. Do not split the list and loop on your own.

### 8a — Preview with `apply_changes=false`

Always call once with `apply_changes=false` first, whatever the user asked for. Save the
response; 8b and 8d read it:

```bash
S="$HOME/.cache/ts_dep_cleanup_{slug}"; . "$S/env"
curl -K "$S/curlrc" -o "$S/preview.json" -w 'preview -> %{http_code}\n' \
  -X POST "$D/delete-with-dependents" \
  --data-urlencode 'type={TYPE}' \
  --data-urlencode 'id=["{guid}"]' \
  --data-urlencode 'operation_type=DELETE_OBJECT_CASCADE' \
  --data-urlencode 'apply_changes=false'
```

**Verified success shape (200):**

```json
{
  "dependents": { "<guid>": [ /* dependent objects, [] when none */ ] },
  "csv": "sourceColumnGUID,sourceColumnName,dependentGUID,dependentName,dependentType,dependentSubType,childGUID,childName,childType,author,lastModified,views,orgName\n..."
}
```

**This response is the best scope estimate available. Size a delete from it, never from a
lookup.** Verified 2026-09-07: `dependency/logicalcolumn` reported **4** dependents for
column `cbeafa3a-7c10-4033-8062-bd44c2d2245c` while the cascade actually removed **12**
objects. The eight extra were answers built on a *model* that was itself in the cascade,
so their names gave no hint of the column. **It is not proven complete:** whether
`dependents` carries the full closure of a graph deeper than two hops has not been
probed (open item #19). 8d's post-apply diff exists for that reason.

Render `dependents` **in the chat** per the Output contract above — a full table of type,
name, author and GUID, plus a per-type count and a total. `[]` means the object has no
dependents and only it would be deleted. If the payload is unreadable, **stop** — do not
proceed to 8b.

Also save the `csv` field (a ready-made export of the impact set) outside the repo and
print its path. The CSV is a **record** of what is being removed, not a means of
recovery — that is 8b's job. It supplements the chat table; it never replaces it.

### 8b — TML backup (non-negotiable, always runs)

**A successful TML export of everything the preview lists must exist before 8d runs.**
The `/dependency` API has no undo, and #19 shows the cascade is wider than any lookup
predicts, so this step is not optional and is not skipped for a "small" delete. Backup
failure aborts operation 8 — never proceed with a partial backup.

It reuses the sibling skill's codified backup rather than re-implementing it:
`ts dependency backup` exports every object first and **writes nothing if any export
fails**, then writes one file per object plus a `manifest.json` that
`ts dependency rollback` reads.

**1. Pick the backup location.** Ask:

```
Where should the TML backup be saved? It is the only way back from this delete.

  1  ~/ts_dependency_backups/   (default — durable)
  2  Custom path

Enter 1 or a path [default: 1]:
```

**2. Identify the source object** — the plan's `source` slot, which the backup always
includes:

| `type` | Source object | `source_deleted` | Why |
|---|---|---|---|
| `LOGICAL_COLUMN` | The **Table or Model that owns the column** | `false` | It is *modified*, not deleted — rolling it back in place restores the column |
| `LOGICAL_TABLE` | The requested object itself | **`true`** | It is deleted. `source_deleted: true` makes rollback re-create it under a new GUID instead of updating a GUID that no longer exists |

The `/dependency` responses do not name a column's owning object. Ask the user for it
(offer `ts metadata search --profile {name} --name "%keyword%"` to find it), export its
TML once, and **confirm the column's name — `sourceColumnName` in the preview CSV —
appears in it** before proceeding. A wrong source object means the column cannot be
restored.

**3. Map each preview dependent** to the backup's type vocabulary:

| Preview `dependentType` (`dependentSubType`) | Backup `type` |
|---|---|
| `PINBOARD_ANSWER_BOOK` | `LIVEBOARD` |
| `QUESTION_ANSWER_BOOK` | `ANSWER` |
| `LOGICAL_TABLE` (`WORKSHEET`) | `MODEL` |
| `LOGICAL_TABLE` (`SQL_VIEW`) | `SQL_VIEW` |
| `LOGICAL_TABLE` (`AGGR_WORKSHEET`) | `VIEW` |
| `LOGICAL_TABLE` (`ONE_TO_ONE_LOGICAL`) | `TABLE` |

An unrecognised type or subtype → **stop and show it to the user**. Do not guess. (The
restore order is taken from each exported TML's own top-level key, so this column only
labels the plan; an unknown subtype still signals a shape nobody has tested.)

**4. Run the backup** with every unique preview object as a `delete` entry:

```bash
echo '{
  "operation": "REMOVE",
  "source": {"guid": "<source-guid>", "type": "<TABLE|MODEL|SQL_VIEW|VIEW>", "name": "<source-name>"},
  "source_deleted": <false for LOGICAL_COLUMN | true for LOGICAL_TABLE>,
  "delete": [ {"guid": "<full-guid>", "type": "ANSWER", "name": "<name>"}, ... ],
  "out_dir": "<chosen-location>"
}' | ts dependency backup --profile {name}
```

For a `LOGICAL_TABLE` delete, leave the requested object out of `delete` — it is already
the source. Non-zero exit → **stop**. Report the error verbatim; nothing has been deleted
and no backup was written. On success, print the backup directory and check the manifest
holds **1 + N** entries (source + every unique preview object other than the source). A
count mismatch → stop.

**Rollback** — if the delete must be undone:

```bash
ts dependency rollback --backup-dir <dir> --profile {name}
```

It restores tables and SQL Views first, then Models, Views, Answers and Liveboards. Each
re-created object's new GUID is written into the objects restored after it, so a
restored Answer binds to the restored Model. **Check the result. Do not just report that
it ran:**

- **Exit code 1, or a non-empty `failed[]`** → the restore is partial. List every failed
  object with its error and its backup file (from `manifest.json`). Say plainly that the
  restore is incomplete. Never report a rollback as done unless the exit code is 0 and
  `failed` is empty. A `failed` entry carrying `created_guid` **does exist** on the
  cluster under that GUID despite the error; say so.
- **Finishing a partial restore:** fix the cause, then re-run the **same** command. It
  resumes from `rollback_state.json` in the backup directory: objects already restored
  are skipped (`skipped[]`) and their new GUIDs are reused, so nothing is created twice
  and no dependent binds to a deleted original. An object whose referenced object is
  still unrestored is refused, not imported against a dead GUID. Never delete
  `rollback_state.json` to "retry cleanly" — that re-creates every object already
  restored.
- **After a partial delete** run the same full command: rollback checks each backed-up
  object first and skips (`skipped[]`, "still exists") any the delete left in place, so
  survivors are not duplicated and restored dependents bind to them.
- **`warnings[]`** → objects that were restored with a platform notice (a Model's routine
  `WARNING`). They are restored; show the notices.
- **`new_guids`** → show the `old GUID → new GUID` table. Every re-created object has a
  new GUID.

Be plain with the user about what rollback cannot do:

- Anything **outside the backup** that referenced an original GUID stays broken. That
  includes bookmarks and embeds, cross-Org references, objects the user cannot see
  (RLS-restricted), and Spotter feedback.
- Sets, Cohorts, Alerts and Spotter feedback on deleted objects are not restored.
- **Restoring an operation 8 cascade has not yet been run live** (open item #20). The
  logic above is unit-tested; a live run on disposable objects is the open step. Say so
  on the confirmation screen.

### 8c — Typed confirmation

Build the screen from the 8a preview. Take each object's author from the preview CSV's
`author` column. Count the objects whose author is not the logged-in `{username}` — the
cascade deletes other people's work, and the user must see that:

```
This will delete {N} objects, including {M} dependents you did not name.
{K} of them belong to other users.

  {type}  {name}  {author}  {full-36-char-guid}
  ...

Copy-ready GUIDs of everything above:
  {one full GUID per line, nothing else}

The deletion is irreversible on the server. A TML backup of all {N} objects is at
  {backup_dir}
Rollback (`ts dependency rollback`) re-creates them with NEW GUIDs and re-links them to
each other. References from anything outside this list stay broken. Restoring an
operation 8 cascade has not yet been verified live.
The preview CSV is at {path} (session-scoped temp storage — copy it to keep it).

Type DELETE to apply, or anything else to cancel:
```

Accept only the exact string `DELETE`. Never accept `Y`, `yes`, or lower-case `delete`.

Every GUID in this prompt is the **full 36 characters** (contract rule 5). This is the
last screen before an irreversible delete: a truncated id here means the user cannot
look up what they are about to lose, and cannot record it afterwards.

### 8d — Re-check, then apply

The server recomputes the cascade when it applies. Anything saved on the object between
the 8a preview and now would be deleted without a backup — for example an Answer someone
creates while 8b exports. So **re-run the preview immediately before applying**, and
apply only if it lists exactly what was backed up.

**1. Re-check:**

```bash
S="$HOME/.cache/ts_dep_cleanup_{slug}"; . "$S/env"
curl -K "$S/curlrc" -o "$S/recheck.json" -w 'recheck -> %{http_code}\n' \
  -X POST "$D/delete-with-dependents" \
  --data-urlencode 'type={TYPE}' \
  --data-urlencode 'id=["{guid}"]' \
  --data-urlencode 'operation_type=DELETE_OBJECT_CASCADE' \
  --data-urlencode 'apply_changes=false'
python3 - "$S/recheck.json" "<backup_dir>/manifest.json" "{guid}" "{TYPE}" <<'EOF'
import json, sys
recheck, manifest, guid, typ = sys.argv[1:]
deps = json.load(open(recheck))["dependents"].get(guid, [])
now = {d["id"] for d in deps if d.get("id")}
objs = json.load(open(manifest))["objects"]
backed = {o["guid"] for o in objs if o["intent"] == "DELETE"}
if typ == "LOGICAL_TABLE":
    now.add(guid)   # the source itself is deleted, and backed up as a DELETE
new, gone = sorted(now - backed), sorted(backed - now)
print(json.dumps({"match": not new and not gone, "not_backed_up": new, "no_longer_listed": gone}))
EOF
```

Any status other than `200`, or `"match": false` → **do not apply.**

- `not_backed_up` → objects the cascade would now delete that have no backup. Show
  them, then go back to 8a for a fresh preview, a fresh backup and a fresh confirmation.
- `no_longer_listed` → the scope shrank. That is harmless to the backup, but the user
  confirmed a different list. Go back to 8a.

**2. Apply** — only after a matching re-check, and straight away. The re-check narrows
the race to a few seconds; it does not close it. The diff after the apply catches what
slips through:

```bash
S="$HOME/.cache/ts_dep_cleanup_{slug}"; . "$S/env"
curl -K "$S/curlrc" --max-time 600 -o "$S/applied.json" -w 'apply -> %{http_code}\n' \
  -X POST "$D/delete-with-dependents" \
  --data-urlencode 'type={TYPE}' \
  --data-urlencode 'id=["{guid}"]' \
  --data-urlencode 'operation_type=DELETE_OBJECT_CASCADE' \
  --data-urlencode 'apply_changes=true'
echo "curl exit: $?"
```

**3. If the apply did not return `200`:**

| Outcome | Meaning | Action |
|---|---|---|
| `400 METADATA_ERROR` | A business rule refused it | See 8e. Nothing was deleted |
| Any other non-200, curl exit `28` (timeout), or `000` | **Unknown.** The server may have acted before failing | **Never re-send the apply.** Run the 8d re-check call once more and compare it with the 8a preview, **then check the source itself** with `metadata/details` (an absent `storables` array reads as gone — **unverified, open item #23**: compare against the same call made before the apply, which must show `storables`). An empty entry for `{guid}` means the source may **still exist** with no dependents left — that is a partial delete, not a full one. Only when the source is gone *and* none of its backed-up dependents remain did the delete happen: report the backed-up set as what was removed and go to the post-apply checks. If the preview is unchanged, nothing was applied: report the failure verbatim and stop. If only part of it changed, the delete is **partial**: say so plainly, list what is gone and what remains, and point to the backup |

**4. After a `200`:**

- **Print the full deleted-object table in the chat** — one row per unique object (type,
  name, author, GUID), grouped by type with counts and a total, per the Output contract.
  This is the only record of an irreversible action; a count alone or a file path is not
  an acceptable report.
- **Diff the applied response against the backup manifest.** Name every deleted object
  that has no backup file, under the heading **"Deleted WITHOUT a backup"**. Rollback
  cannot restore those. The user must see this in the response, not discover it later.
- **Flag the requested GUID if it is missing from the response.** A partial delete is the
  dangerous outcome and must not pass silently.
- Save the applied `csv` alongside the table, print the path, and note it is
  session-scoped temp storage to copy elsewhere.
- Print the backup directory again, with the rollback command.
- Confirm the source is gone with `metadata/details` for `{guid}`. An absent `storables`
  array reads as deleted, but that reading is **unverified (open item #23)**: run the
  same call *before* the apply as a control (it must show `storables`), and say the check
  is unverified when you report it. **Do not take an empty lookup as proof.** A lookup
  answers `{"<guid>":{}}` (see operations 1–6) both for an object that is gone and for
  one that still exists with no dependents, so it cannot tell a full delete from a
  partial one. Spot-check deleted dependents the same way.

### 8e — Business-rule refusals are normal, and are not your bug

The API enforces referential rules and returns `400 METADATA_ERROR` with the reason in
`details`. **Verified example:**

```json
{"error_code":"METADATA_ERROR","message":"Failed to process metadata",
 "details":"Error Code: INVALID_OPERATION ... Deleting columns linked to filters is not allowed"}
```

These are **column-specific** — a control column returned `200` for the identical request
shape, so a refusal is about that object, not the request. When one occurs:

1. Surface the `details` message verbatim — it names the actual blocker
2. Do **not** retry, reshape the request, or switch endpoints to get around it
3. Explain what must change first (e.g. remove the filter referencing the column), and
   let the user decide

Seen so far: `Deleting columns linked to filters is not allowed`.

---

## Error Handling

| Symptom | Likely cause | Action |
|---|---|---|
| `404` on every endpoint | v1 removed on this build | Stop. Report it; point at `ts-dependency-manager` (v2 APIs) as the working alternative. The family was present on the verified build (2026-09-01), but this is build-specific |
| `404` on one endpoint only | Wrong path prefix | The verified prefix is `/callosum/v1/tspublic/v1`. The bare `/tspublic/v1` returns a 404 HTML page — do not fall back to it |
| `401` / `403` | Session cookie missing, expired, or lacks scope | Re-run Step 1b once. If it fails again, stop — do not loop; repeated failures can lock the account. Confirm MODIFY/FULL for operation 8 |
| `SSL_connect` / certificate error | Self-signed cluster, or a real certificate problem | Stop. If the cluster is known to be self-signed, the user sets `verify_ssl: false` on the profile and you re-run Step 1a. **Never add `-k` to a call** |
| curl exit `28` | Timeout | Report it. For a read, the user may retry. For an operation 8 apply, follow 8d step 3 — never re-send |
| Connection refused / `000` | Cluster down or unreachable from this network | Check the host is up before debugging the call |
| `400` with an id complaint | `id` not sent as a JSON array string | Confirm the array form `["guid"]`, including for a single GUID |
| `405 Method Not Allowed` | Wrong verb | Operations 2–7 are GET; only operation 1 is POST. Check the status table — this is not an encoding problem |
| `500` on `pinboard` | Server-side NPE in `referencingObjectsOfPinboards` | Known broken on the verified build (open item #11). Report and move on |
| `404` on `delete-with-dependents` | Wrong prefix | It is on `/callosum/v1/dependency/`, not `/callosum/v1/tspublic/v1/`. Fix the prefix — do not conclude the endpoint is absent |
| User gives several GUIDs for operation 8 | One backup source per run | Explain, ask which to run first, run operation 8 once per object |
| `ts dependency backup` non-zero exit | Export failed (permissions, token, invalid object) | Stop operation 8. Nothing was deleted or written. Report the error verbatim |
| 8d re-check does not match the backup | The cascade changed after the backup | Do not apply. Back to 8a |
| `ts dependency rollback` exit 1 | One or more objects failed to restore | Report every `failed[]` entry with its error and backup file. Do not call the rollback done |
| User asks to purge | Out of scope for this release | Refuse. `dependency/purge` takes no parameters and its scope is unverified (open item #8) — do not call it, not even to "check" |
| `400 INVALID_METADATA_TYPE` | `type` missing | Send `type=LOGICAL_TABLE` or `LOGICAL_COLUMN` |
| `400 INVALID_OPERATION_TYPE` | `operation_type` missing | Send `operation_type=DELETE_OBJECT_CASCADE` (that exact param name) |
| `400 METADATA_ERROR` on delete | A business rule blocks it | Read `details` — it names the blocker (e.g. column linked to a filter). Report verbatim; do not retry or reshape |
| `{"<guid>":{}}` | Genuinely 0 dependents | Report "0 dependents" — do not retry |
| `{}` (no guid key) | GUID is not of the endpoint's object type | Say so — do not report it as "no dependents" |

Never work around a failing call by switching endpoints or hand-rolling a different
request shape. Report it and stop.

---

## Cleanup

End the server session, then delete the session directory. It holds a live cookie:

```bash
S="$HOME/.cache/ts_dep_cleanup_{slug}"; . "$S/env"
curl -K "$S/curlrc" -o /dev/null -w 'logout -> %{http_code}\n' -X POST "$V1/session/logout"
rm -rf "$S"
```

Run this even if the session ended with an error. Before you do, copy any CSV the user
wants to keep out of `$S`.

Leave the operation 8 backup directory in place — it is the user's only rollback path.
Remind them where it is.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-10-23 | Initial release. Eight `/dependency` operations behind one menu, authenticated via v1 session login (cookie in a per-profile session directory, password passed on stdin, logout at cleanup), reading `base_url` / `username` / `password_env` / `verify_ssl` from `~/.claude/thoughtspot-profiles.json`; TLS verification is set once from the profile in a curl config file, and every call has a timeout. **Ops 1-6** (`listdependents` POST + the five GET per-type lookups) and **op 8** (`delete-with-dependents`, cascade) are live-verified; **op 7** (`pinboard`) returns a server-side 500 NPE. Op 8 sits on the `/callosum/v1/dependency/` prefix, not the `/callosum/v1/tspublic/v1/` prefix ops 1-7 use. It takes exactly one GUID, and runs only after a mandatory `apply_changes=false` preview, a non-negotiable `ts dependency backup` TML export of every previewed object (`source_deleted` for a table delete; rollback via `ts dependency rollback`, which re-links restored objects and fails loudly on a partial restore), a re-run of the preview that must match the backup, and a typed `DELETE` on a screen that names each object's author. A failed or timed-out apply is never re-sent. `dependency/purge` is deliberately excluded: no parameters, unverified scope (open item #8). Raw REST is a documented exception (no v2 equivalent; exit is open item #6). Output contract requires full 36-character GUIDs and in-chat object tables. The op 8 preview is the scope to trust: the ops 1-6 lookups under-report cascade scope (4 reported vs 12 deleted, live 2026-09-07 -- open item #19). |
