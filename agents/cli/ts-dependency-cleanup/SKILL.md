---
name: ts-dependency-cleanup
description: Inspect and delete ThoughtSpot dependency graphs via the v1 /dependency API family — list dependents by type, list objects referencing a logical/physical column, table, relationship or pinboard, and cascade-delete objects with their dependents behind a mandatory preview, TML backup and typed confirmation. Authenticates with a v1 session-login cookie.
---

# ThoughtSpot: Dependency Manager v2

Run `/dependency` operations against a ThoughtSpot instance: pick an operation from the
menu, supply the GUIDs, read the result. Seven read-only lookups (six work) plus one
**destructive** operation — a cascade delete (operation 8) — which **works and is
irreversible on the server**. It runs only behind a preview, a TML backup and a typed
`DELETE`.

> **Live-verified against `https://172.32.51.133:8443` (2026-09-01 to 2026-09-07).** The
> v1 `/dependency/*` family is present on this build — the repo-wide "v1 is gone" concern
> does not apply here. **Seven of the eight operations work, including the delete; only
> operation 7 (pinboard) is broken.** This is build-specific: re-run the probe in
> [references/open-items.md](references/open-items.md) before trusting it elsewhere.
> The migration path to a `ts dependency` CLI group is open item #6.
>
> **Purge (`dependency/purge`) is deliberately not part of this release.** Its route is
> live, but it takes no parameters and its scope — possibly every soft-deleted object on
> the instance — is unverified (open item #8). It must not be called from this skill.

## Operation status on this build

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

Operation 1 is the only POST. Operations 2–7 are **GET with query parameters** — POST
returns `405 Method Not Allowed`.

Ask one question at a time for **dependent** decisions. Batch **independent** questions
into a single prompt to cut round-trips.

---

## References

| File | Purpose |
|---|---|
| [references/open-items.md](references/open-items.md) | Live probe results (2026-09-01), verified verbs and response shapes, and the remaining unknowns |
| [../ts-dependency-manager/SKILL.md](../ts-dependency-manager/SKILL.md) Step 7 / Step 11 | The `ts dependency backup` / `ts dependency rollback` contract operation 8's backup reuses |

---

## Prerequisites

- A ThoughtSpot profile for the target cluster — run `/ts-profile-thoughtspot` if none exists
- The profile's credential env var must be set in the calling shell
- The user must have **MODIFY** or **FULL** access on any object touched by operation 8
- The `ts` CLI (`pip install -e tools/ts-cli`) with the **same profile** — operation 8's
  TML backup and rollback run through `ts dependency backup` / `ts dependency rollback`

Credentials follow the repo-wide convention (`.claude/rules/security.md`): the profile
in `~/.claude/thoughtspot-profiles.json` holds `base_url`, `username` and the **name** of
an env var (`password_env`); the secret itself lives in the OS keychain and is exported
into the shell. This skill reads the profile, then reads the env var it names.

**Never accept the password in conversation, and never echo it.** Pass it to `curl` only
by variable reference, so no literal credential reaches the transcript or a captured
permission rule.

For a self-signed cluster the profile carries `verify_ssl: false` — pass `-k` to every
`curl` when it is set, and only then.

---

## Step 1 — Authenticate (v1 session login)

The v1 `/dependency/*` endpoints are **cookie-authenticated**. Bearer tokens are not used
here. Log in once per session and reuse the cookie jar for every later call.

Read `~/.claude/thoughtspot-profiles.json` (a top-level JSON array). If it is missing or
empty, stop and send the user to `/ts-profile-thoughtspot`.

If several profiles exist, show a numbered pick list of `name — base_url`; if exactly
one, show it and confirm. Save `{base_url}` (no trailing slash), `{username}`,
`{password_env}` and `{verify_ssl}`.

Confirm the credential is present **without revealing it**:

```bash
[ -n "${!password_env}" ] && echo "credential present" || echo "MISSING — export it first"
```

If it is missing, stop and tell the user to export it in their own terminal.

Log in, storing the cookie in a jar outside the repo:

```bash
V1="{base_url}/callosum/v1/tspublic/v1"
JAR="$(mktemp -t ts_dep_cookies)"

curl -sS -k -c "$JAR" -o /dev/null -w 'login -> %{http_code}\n' \
  -X POST "$V1/session/login" \
  --data-urlencode "username={username}" \
  --data-urlencode "password=$THOUGHTSPOT_PASSWORD_{SLUG}" \
  --data-urlencode "rememberme=true"
```

Verify the cookie works before offering the menu:

```bash
curl -sS -k -b "$JAR" -o /dev/null -w 'session/info -> %{http_code}\n' "$V1/session/info"
```

`200` → proceed. `401` → the credential is wrong or expired; stop and report. Do not
retry a login automatically — repeated failures can lock the account.

The cookie jar is a live credential. Never print its contents, and delete it at the end
of the session (see Cleanup).

---

## Step 0 — Overview

On invocation, display this before doing any work:

---
**ts-dependency-cleanup** — inspect and delete ThoughtSpot dependency graphs via the `/dependency` API family.

### Operations

```
  Read-only — inspect who references what:
    1  List dependents            requires TYPE + ID(s)
    2  Referencing a logical column        ID(s)
    3  Referencing a logical table         ID(s)
    4  Referencing a logical relationship  ID(s)
    5  Referencing a physical column       ID(s)
    6  Referencing a physical table        ID(s)
    7  Referencing a pinboard              ID(s)   [BROKEN on this build — 500]

  Destructive — preview, TML backup and typed confirmation, always:
    8  Delete objects with their dependents   TYPE + ID(s)  [preview by default]

    Q  Quit
```

Operations 1–6 may be run in any order, repeatedly, in one session, and all work.

Operation 8 defaults to `apply_changes=false` — a preview that changes nothing. Applying
it for real requires a successful TML backup of everything in the preview **and** a
typed `DELETE`.

Operation 7 returns a server-side 500 on this build. The skill reports it; it must not
substitute a different endpoint to work around it.

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

1. **Print a table in the response** with one row per object: type, name, GUID. Never
   summarise as a bare count ("12 objects deleted") and never point at a file path as
   the answer to "what was affected?".
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
# logical types — direct
curl -sS -k -b "$JAR" -G "$V1/metadata/list" \
  --data-urlencode "type=LOGICAL_COLUMN" --data-urlencode "batchsize=50"

# physical types — via a one-to-one logical table's details
curl -sS -k -b "$JAR" -G "$V1/metadata/details" \
  --data-urlencode "type=LOGICAL_TABLE" --data-urlencode 'id=["<table-guid>"]'
```

Offer to look GUIDs up this way rather than demanding the user paste them.

### Collecting `id`

`id` is **mandatory** and is a JSON array of GUID strings — `["guid-1", "guid-2"]` —
even for a single GUID. Prompt:

```
Enter one or more GUIDs, comma-separated:
```

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

> **Note — `PINBOARD` is not a valid `type`.** Operation 1 cannot reach pinboards; use
> operation 7, which has its own endpoint. This asymmetry is in the API, not a gap here.

### The call template

Every operation uses the same shape — only the path and body differ:

Operations 2–7 are **GET**, with the id array as a query parameter:

```bash
curl -sS -k -b "$JAR" -G "$V1/dependency/{endpoint}" \
  --data-urlencode 'id=["guid-1","guid-2"]' \
  -w '\n%{http_code}\n'
```

Operation 1 is **POST**, form-encoded, and additionally takes `type`:

```bash
curl -sS -k -b "$JAR" -w '\n%{http_code}\n' \
  -X POST "$V1/dependency/listdependents" \
  --data-urlencode 'type={TYPE}' \
  --data-urlencode 'id=["guid-1","guid-2"]'
```

`$V1` and `$JAR` come from Step 1. Prefix, verbs and encoding are all live-verified.
A `405` means the wrong verb — check the status table; do not switch encoding.

Print the HTTP status alongside the body. On a non-2xx, show the status and response
verbatim, then return to the menu — never retry silently and never fall back to a
different endpoint.

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
| 7 | Referencing a pinboard | `/dependency/pinboard` | GET | `id` — **500 on this build** |

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

## Operation 8 — Delete objects with their dependents

**Endpoint (verified 2026-09-03):**

```
POST {base_url}/callosum/v1/dependency/delete-with-dependents
```

Note the prefix: **`/callosum/v1/dependency/`** — *not* `/callosum/v1/tspublic/v1/`,
which is where operations 1–7 live and which returns 404 for this endpoint. The two
halves of this skill sit on different prefixes. Use `$D` for this one:

```bash
D="{base_url}/callosum/v1/dependency"
```

### Parameters — four, all required except the last

| Param | Required | Values | Notes |
|---|---|---|---|
| `type` | **yes** | `LOGICAL_TABLE`, `LOGICAL_COLUMN` | Omit → `400 INVALID_METADATA_TYPE` |
| `id` | **yes** | `["guid-1","guid-2"]` | JSON-array string, even for one GUID |
| `operation_type` | **yes** | `DELETE_OBJECT_CASCADE` | Omit → `400 INVALID_OPERATION_TYPE`. The name is `operation_type` — `operation`, `operationType`, `op_type` are all rejected |
| `apply_changes` | no | `false` (default), `true` | Omitting behaves exactly as `false` — verified |

### 8a — Preview with `apply_changes=false`

Always call once with `apply_changes=false` first, whatever the user asked for:

```bash
curl -sS -k -b "$JAR" -w '\n%{http_code}\n' \
  -X POST "$D/delete-with-dependents" \
  --data-urlencode 'type=LOGICAL_COLUMN' \
  --data-urlencode 'id=["guid-1"]' \
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

**This response is the authoritative blast radius — the operation 1–6 lookups are not.**
Verified 2026-09-07: `dependency/logicalcolumn` reported **4** dependents for column
`cbeafa3a-7c10-4033-8062-bd44c2d2245c` while the cascade actually removed **12** objects. The eight extra were
answers built on a *model* that was itself in the cascade, so their names gave no hint
of the column. Never size a delete from a lookup; size it from this `dependents` field.

Render `dependents` **in the chat** per the Output contract above — a full table of type,
name and GUID, plus a per-type count and a total. `[]` means the object has no dependents
and only it would be deleted. If the payload is unreadable, **stop** — do not proceed to 8b.

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
Where should the TML backup be saved?

  1  /tmp/   (default — ephemeral, cleared on reboot)
  2  Custom path   (recommended — somewhere durable)

Enter 1 or a path [default: 1]:
```

**2. Identify the source object** — the plan's `source` slot, which the backup always
includes:

| `type` | Source object | Why |
|---|---|---|
| `LOGICAL_COLUMN` | The **Table or Model that owns the column** | It is *modified*, not deleted — rolling it back in place restores the column |
| `LOGICAL_TABLE` | The requested object itself | It is deleted; see the caveat below |

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
| `LOGICAL_TABLE` (`SQL_VIEW` / `AGGR_WORKSHEET`) | `VIEW` |
| `LOGICAL_TABLE` (`ONE_TO_ONE_LOGICAL`) | `TABLE` |

An unrecognised type or subtype → **stop and show it to the user**. Do not guess; the
type decides rollback order.

**4. Run the backup** with every unique preview object as a `delete` entry:

```bash
echo '{
  "operation": "REMOVE",
  "source": {"guid": "<source-guid>", "type": "<TABLE|MODEL>", "name": "<source-name>"},
  "delete": [ {"guid": "<full-guid>", "type": "ANSWER", "name": "<name>"}, ... ],
  "out_dir": "<chosen-location>"
}' | ts dependency backup --profile {name}
```

Non-zero exit → **stop**. Report the error verbatim; nothing has been deleted and no
backup was written. On success, print the backup directory and check the manifest holds
**1 + N** entries (source + every unique preview object). A count mismatch → stop.

**Rollback** — if the delete must be undone, `ts dependency rollback --backup-dir
<dir> --profile {name}`. Be plain with the user about what it cannot do:

- Deleted objects are re-imported with **new GUIDs**. Anything that referenced an
  original GUID — including objects outside the preview, or ones you cannot see
  (cross-Org, RLS-restricted, Spotter feedback) — stays broken.
- Sets / Cohorts / Alerts / Spotter feedback on deleted objects are not restored.
- For a **`LOGICAL_TABLE`** delete, the requested object sits in the source slot, which
  rollback updates *in place* at its original GUID. Whether that recreates a deleted
  object is **not verified** (open item #20) — if it fails, re-import that file with
  `ts tml import` as a new object.

### 8c — Typed confirmation

```
This will delete {N} objects, including {M} dependents you did not name:

  {type}  {name}  {full-36-char-guid}
  ...

Copy-ready GUIDs of everything above:
  {one full GUID per line, nothing else}

The deletion is irreversible on the server. A TML backup of all {N} objects is at
  {backup_dir}
Rollback (`ts dependency rollback`) re-creates them with NEW GUIDs — references to the
old GUIDs from anything outside this list will stay broken.
The preview CSV is at {path} (session-scoped temp storage — copy it to keep it).

Type DELETE to apply, or anything else to cancel:
```

Accept only the exact string `DELETE`. Never accept `Y`, `yes`, or lower-case `delete`.

Every GUID in this prompt is the **full 36 characters** (contract rule 5). This is the
last screen before an irreversible delete: a truncated id here means the user cannot
look up what they are about to lose, and cannot record it afterwards.

### 8d — Apply

Re-run the identical call with `apply_changes=true`. Then:

- **Print the full deleted-object table in the chat** — one row per unique object (type,
  name, GUID), grouped by type with counts and a total, per the Output contract. This is
  the only record of an irreversible action; a count alone or a file path is not an
  acceptable report.
- **Diff the applied response against the 8a preview and call out any object that
  appears now but not there** — the cascade can be wider than anything the lookups
  showed, and the user must see that in the response, not discover it later.
- **Flag any requested GUID missing from the response** — a partial delete is the
  dangerous outcome and must not pass silently
- Save the applied `csv` alongside the table, print the path, and note it is
  session-scoped temp storage to copy elsewhere
- Print the backup directory again, with the rollback command
- Re-run the matching lookup (operations 1–6) per id and confirm it now returns empty,
  and spot-check individual objects via `metadata/details` (an absent `storables` array
  confirms deletion)

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
| `404` on every endpoint | v1 removed on this build | Stop. Report it; point at `ts-dependency-manager` (v2 APIs) as the working alternative. Verified present on 172.32.51.133 (2026-09-01) but this is build-specific |
| `404` on one endpoint only | Wrong path prefix | The verified prefix is `/callosum/v1/tspublic/v1`. The bare `/tspublic/v1` returns a 404 HTML page — do not fall back to it |
| `401` / `403` | Session cookie missing, expired, or lacks scope | Re-run Step 1 once. If it fails again, stop — do not loop; repeated failures can lock the account. Confirm MODIFY/FULL for operation 8 |
| `SSL_connect` / cert error | Self-signed cluster | Confirm `verify_ssl: false` on the profile and that `-k` is passed |
| Connection refused / `000` | Cluster down or unreachable from this network | Check the host is up before debugging the call |
| `400` with an id complaint | `id` not sent as a JSON array string | Confirm the array form `["guid"]`, including for a single GUID |
| `405 Method Not Allowed` | Wrong verb | Operations 2–7 are GET; only operation 1 is POST. Check the status table — this is not an encoding problem |
| `500` on `pinboard` | Server-side NPE in `referencingObjectsOfPinboards` | Known broken on this build (open item #11). Report and move on |
| `404` on `delete-with-dependents` | Wrong prefix | It is on `/callosum/v1/dependency/`, not `/callosum/v1/tspublic/v1/`. Fix the prefix — do not conclude the endpoint is absent |
| `ts dependency backup` non-zero exit | Export failed (permissions, token, invalid object) | Stop operation 8. Nothing was deleted or written. Report the error verbatim |
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

Delete the cookie jar — it holds a live session:

```bash
rm -f "$JAR"
```

Leave the operation 8 backup directory in place — it is the user's only rollback path.
Remind them where it is.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-09-08 | Initial release. Eight `/dependency` operations behind one menu, authenticated via v1 session login (`session/login` -> cookie jar), reading `base_url` / `username` / `password_env` from `~/.claude/thoughtspot-profiles.json`. **Ops 1-6** (`listdependents` POST + the five GET per-type lookups) and **op 8** (`delete-with-dependents`, cascade) are live-verified; **op 7** (`pinboard`) returns a server-side 500 NPE. Op 8 sits on the `/callosum/v1/dependency/` prefix, not the `/callosum/v1/tspublic/v1/` prefix ops 1-7 use, and runs only after a mandatory `apply_changes=false` preview, a non-negotiable `ts dependency backup` TML export of every previewed object (rollback via `ts dependency rollback`), and a typed `DELETE`. `dependency/purge` is deliberately excluded: no parameters, unverified scope (open item #8). Output contract requires full 36-character GUIDs and in-chat object tables -- a truncated GUID copies with its ellipsis, and a scratchpad CSV is not a delivery channel. Op 8's `apply_changes=false` preview is the authoritative blast radius: the ops 1-6 lookups under-report cascade scope (4 reported vs 12 deleted, live 2026-09-07 -- open item #19). |
