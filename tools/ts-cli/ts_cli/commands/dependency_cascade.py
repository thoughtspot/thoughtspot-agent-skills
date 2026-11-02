"""ts dependency cascade-preview / cascade-delete — server-side cascade delete.

Attaches to the `app` Typer group in `dependency.py` (the `dependency_apply.py` pattern;
`cli.py` imports this module to register the commands).

`cascade-preview` is the dry run: it changes nothing. `cascade-delete` is the only
writing command, and enforces in code what the ts-dependency-manager skill also says
in prose: an admin caller, exactly one object, a typed confirmation, a readable backup
from the same cluster and Org that nothing has changed since, no Sets or feedback the
server would delete unlisted, every object visible to the existence check, and a fresh
preview that matches that backup immediately before the delete. The delete is sent ONCE
and never retried after it may have reached the server (a 401 is re-sent once with a
fresh token: the server rejected it before doing any work).

The scope is the union of the source's preview and the preview of every Table, Model or
View that preview lists, repeated until nothing new appears: whether one preview holds
the full closure of a deep graph is unproven (open item #26), so each extra preview is
cheap insurance.
What it did is decided by checking which objects still exist (v2 `metadata/search`) —
never from the preview, which answers the same for a deleted object as for a live one
with no dependents.

Pure logic lives in `ts_cli.dependency.cascade`.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.commands.dependency import app, _profile_option, present_objects
from ts_cli.dependency.backup import V2_TYPE_MAP, cluster_mismatch
from ts_cli.dependency.cascade import (
    CASCADE_PATH,
    CASCADE_TYPES,
    OWNER_TYPES,
    CascadeError,
    attached_blockers,
    backed_up_deletes,
    backup_problems,
    backup_type,
    cascade_form,
    check_plan,
    classify_gone,
    definite_failure,
    deleted_set,
    feedback_count,
    invisible,
    is_admin,
    mentioned,
    not_available,
    owners_in_scope,
    parse_preview,
    recheck,
    stale,
    summarize,
)
from ts_cli.report.resolver import (
    SourceAmbiguousError,
    SourceUnresolvedError,
    _fetch_table_columns,
    resolve_source,
)
from ts_cli.sets.discover import discover_sets

# Live dry runs of large objects took 250-300 s (PR #692 review); the delete does more.
_TIMEOUT_S = 900

_ADMIN_ONLY = (
    "Cascade delete is limited to ThoughtSpot administrators (the ADMINISTRATION "
    "privilege), and the server refuses even the preview to anyone else. User '{user}' "
    "does not have it. Ask an administrator to run this, or use Remove mode to fix "
    "dependents instead of deleting them."
)


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise typer.Exit(1)


def _emit(result: Dict[str, Any], ok: bool) -> None:
    print(json.dumps(result, indent=2))
    if not ok:
        raise typer.Exit(1)


def _admin_user(client: ThoughtSpotClient) -> str:
    """Return the caller's user name; exit unless they are an administrator."""
    user = client.get("/api/rest/2.0/auth/session/user").json() or {}
    if not is_admin(user):
        _fail(_ADMIN_ONLY.format(user=user.get("name", "?")))
    return user.get("name", "")


def _post(client: ThoughtSpotClient, source_type: str, guid: str, *, apply: bool,
          ) -> Tuple[Optional[int], Any]:
    """One cascade call. Returns (status, parsed body or text). Status is None when the
    outcome is unknown: the client refused to retry an ambiguous failure (a timeout or a
    gateway error — the server may still be working). Never retried after it may have
    reached the server, not even the preview: a preview is a heavy computation, and a
    retry of a timed-out one only stacks more of them on the server."""
    try:
        resp = client.request(
            "POST", CASCADE_PATH, data=cascade_form(source_type, guid, apply=apply),
            raise_for_status=False, idempotent=False, timeout=_TIMEOUT_S)
    except SystemExit:
        if not apply:
            raise
        return None, None
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, resp.text


def _refusal(body: Any) -> Optional[str]:
    """The server's business-rule refusal text (400 METADATA_ERROR), else None."""
    if isinstance(body, dict) and body.get("error_code") == "METADATA_ERROR":
        return str(body.get("details") or body.get("message") or body)
    return None


def _resolve_target(client, ref: str, source_type: str, column: Optional[str]) -> Dict[str, str]:
    """Resolve the object to delete and the object a backup must use as its source — the
    object itself for a whole-object delete, the Table or Model owning the column for a
    column delete. Checks the type first: the server does not (a Table's GUID sent as
    LOGICAL_COLUMN previews as if it were a column, live 2026-10-30)."""
    try:
        desc = resolve_source(ref, client)
    except (SourceUnresolvedError, SourceAmbiguousError, ValueError) as e:
        _fail(f"{ref}: {e}. Nothing was changed.")
    guid, owner = (_column_of(client, desc, ref, column) if column
                   else _object_and_owner(desc, ref, source_type))
    if not owner.get("guid"):
        _fail(f"Could not find the Table or Model that owns column {guid}. Nothing was changed.")
    try:
        typ = backup_type("LOGICAL_TABLE", owner.get("subtype"))
    except CascadeError as e:
        _fail(f"{owner.get('name') or owner['guid']}: {e}")
    return {"guid": guid, "type": "LOGICAL_COLUMN" if column else source_type,
            "backup_source": {"guid": owner["guid"], "name": owner.get("name") or "", "type": typ}}


def _column_of(client, desc, ref: str, column: str) -> Tuple[str, Dict[str, Any]]:
    """(column GUID, owner) for `--column` on a Table/Model/View."""
    if desc.type != "LOGICAL_TABLE":
        _fail(f"--column needs a Table, Model or View; {ref} is a {desc.type}.")
    hits = [c.get("header") or {} for c in _fetch_table_columns(client, desc.guid)]
    hits = [h for h in hits if h.get("name") == column]
    if len(hits) != 1:
        _fail(f"{desc.name} has {len(hits)} columns named {column!r}. Nothing was changed.")
    return hits[0]["id"], {"guid": desc.guid, "name": desc.name, "subtype": desc.subtype}


def _object_and_owner(desc, ref: str, source_type: str) -> Tuple[str, Dict[str, Any]]:
    """(GUID, owner) for a whole object or a column GUID, after checking the type."""
    if desc.type != source_type:
        _fail(f"{ref} is a {desc.type}, not a {source_type}. Nothing was changed.")
    owner = ({"guid": desc.guid, "name": desc.name, "subtype": desc.subtype}
             if source_type == "LOGICAL_TABLE" else (desc.parent or {}))
    return desc.guid, owner


def _preview_or_exit(client, source_type: str, guid: str) -> Dict[str, Any]:
    status, body = _post(client, source_type, guid, apply=False)
    if not_available(status, body):
        _emit({"status": "NOT_AVAILABLE", "details": str(body)[:500],
               "note": "Cascade delete is switched off on this cluster (API_NOT_ALLOWED). "
                       "Nothing was changed. ThoughtSpot support can enable it; until "
                       "then, use Remove or Repoint mode."}, ok=False)
    if status == 400 and _refusal(body):
        _emit({"status": "REFUSED", "details": _refusal(body),
               "note": "A ThoughtSpot rule blocks this delete. Nothing was changed."}, ok=False)
    if status != 200:
        _fail(f"Cascade preview failed: HTTP {status}: {str(body)[:500]}")
    try:
        return parse_preview(body, guid)
    except CascadeError as e:
        _fail(str(e))


def _scope(client, source_type: str, guid: str) -> Tuple[List[Dict[str, Any]], str]:
    """Every object the cascade deletes besides `guid` — the source's preview, unioned with
    the preview of each Table, Model or View it lists, until nothing new appears — and the
    source preview's CSV."""
    found: Dict[str, Dict[str, Any]] = {}
    queue = [(source_type, guid)]
    seen = {guid}
    csv_text = None
    while queue:
        typ, g = queue.pop(0)
        preview = _preview_or_exit(client, typ, g)
        csv_text = preview["csv"] if csv_text is None else csv_text
        for o in preview["objects"]:
            if o["guid"] == guid:
                continue
            found.setdefault(o["guid"], o)
            if o["type"] in OWNER_TYPES and o["guid"] not in seen:
                seen.add(o["guid"])
                queue.append(("LOGICAL_TABLE", o["guid"]))
    return list(found.values()), csv_text or ""


def _feedback(client, guid: str) -> Optional[int]:
    try:
        resp = client.request("POST", "/api/rest/2.0/metadata/tml/export", raise_for_status=False,
                              json={"metadata": [{"identifier": guid, "type": "FEEDBACK"}],
                                    "export_associated": False, "formattype": "YAML"})
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        return feedback_count(resp.status_code, body)
    except (Exception, SystemExit):
        return None


def _attached(client, objects: List[Dict[str, Any]], guid: str, source_type: str,
              source_name: str) -> List[Dict[str, Any]]:
    """Sets and feedback on the deleted Tables, Models and Views — the cascade deletes
    them without listing them (PR #692 review, live 2026-11-02)."""
    owners = owners_in_scope(objects, guid, source_type)
    names = {o["guid"]: o.get("name") or "" for o in objects}
    names[guid] = source_name
    sets = discover_sets(client, [{"guid": g, "name": names.get(g, "")} for g in sorted(owners)])
    blockers = attached_blockers(owners, sets, {g: _feedback(client, g) for g in owners})
    return [{**b, "owner_name": names.get(b["owner"], "")} for b in blockers]


_BLOCKED = ("The delete would also remove the Sets or Spotter feedback listed in "
            "'attached' (or they could not be checked), and the server's preview does not "
            "list them, so they cannot be backed up or restored here. Nothing was changed. "
            "Back up and remove them first (or move them to another Model), then run the "
            "preview again.")


@app.command("cascade-preview")
def cascade_preview_cmd(
    ref: str = typer.Argument(..., help="GUID or name of the Table/Model/View (or a column's GUID)."),
    source_type: str = typer.Option("LOGICAL_TABLE", "--type", help=f"One of: {', '.join(CASCADE_TYPES)}."),
    column: Optional[str] = typer.Option(None, "--column", help="Delete only this column of REF."),
    profile: Optional[str] = _profile_option,
) -> None:
    """DRY RUN: list everything a cascade delete would remove. Changes nothing.

    Administrators only. Output: JSON with one row per object (guid, name, type, author,
    org), counts per type, the total, how many belong to other users or to an unknown
    author, the object to back up (`backup_source`), any Sets or feedback the delete
    would remove unlisted (`attached`), and the server's CSV. `source.guid` is the GUID
    to pass to `cascade-delete`. `status` is PREVIEW, or BLOCKED (exit 1) when
    `attached` is not empty — `cascade-delete` refuses those.
    """
    if source_type not in CASCADE_TYPES:
        _fail(f"--type must be one of {', '.join(CASCADE_TYPES)}.")
    client = ThoughtSpotClient(resolve_profile(profile))
    user = _admin_user(client)
    target = _resolve_target(client, ref, source_type, column)
    objects, csv_text = _scope(client, target["type"], target["guid"])
    attached = _attached(client, objects, target["guid"], target["type"],
                         target["backup_source"]["name"])
    _emit({"status": "BLOCKED" if attached else "PREVIEW",
           "source": {"guid": target["guid"], "type": target["type"]},
           "requested_by": user, "objects": objects, **summarize(objects, user),
           "source_deleted": target["type"] == "LOGICAL_TABLE",
           "backup_source": target["backup_source"], "attached": attached,
           **({"note": _BLOCKED} if attached else {}), "csv": csv_text}, ok=not attached)


def _readable(path: str) -> bool:
    try:
        with open(path) as f:
            json.load(f)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _load_backup(backup_dir: str) -> Dict[str, Any]:
    """The backup's manifest — or exit, having deleted nothing."""
    manifest_path = os.path.join(backup_dir, "manifest.json")
    try:
        with open(manifest_path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        _fail(f"Cannot read the backup manifest {manifest_path}: {e}. Nothing was deleted.")


def _checks_before_delete(client, guid: str, source_type: str,
                          manifest: Dict[str, Any]) -> Tuple[Set[str], Dict[str, str]]:
    """Every refusal that comes before the delete is sent. Returns the GUIDs the delete
    removes (`before`) and the objects to watch, typed for v2 search (`typed`)."""
    mismatch = cluster_mismatch(manifest, client.base_url, client.org)
    if mismatch:
        _fail(f"{mismatch} Nothing was deleted.")
    _admin_user(client)
    owner = _resolve_target(client, guid, source_type, None)["backup_source"]
    backup_source = owner["guid"]
    files = {o.get("backup_file") or "": _readable(o.get("backup_file") or "")
             for o in manifest.get("objects") or []}
    problems = backup_problems(manifest, guid, source_type, backup_source, files)
    if problems:
        _emit({"status": "BAD_BACKUP", "problems": problems,
               "note": "This backup cannot protect this delete. Nothing was deleted."}, ok=False)

    objects, _ = _scope(client, source_type, guid)
    attached = _attached(client, objects, guid, source_type, owner["name"])
    if attached:
        _emit({"status": "BLOCKED", "attached": attached, "note": _BLOCKED}, ok=False)
    before = deleted_set(objects, guid, source_type)
    check = recheck(before, manifest)
    if not check["match"]:
        _emit({"status": "RECHECK_MISMATCH", **check,
               "note": "What would be deleted changed since the backup. Nothing was deleted. "
                       "Run the preview, backup and confirmation again."}, ok=False)

    # Objects to watch: everything to be deleted, plus the column itself and its owner
    # (modified in place) for a column delete.
    typed = {o["guid"]: V2_TYPE_MAP[o["type"]] for o in objects}
    typed[guid] = source_type
    if source_type == "LOGICAL_COLUMN":
        typed[backup_source] = "LOGICAL_TABLE"
    present = present_objects(client, typed)
    unseen = invisible(typed, present)
    if unseen:
        _emit({"status": "NOT_VISIBLE", "not_visible": unseen,
               "note": "The existence check cannot see these objects (another Org, or a "
                       "type it cannot look up), so it could not confirm what the delete "
                       "did. Nothing was deleted."}, ok=False)
    changed = stale(present, manifest)
    if changed:
        _emit({"status": "STALE_BACKUP", "changed_since_backup": changed,
               "note": "These objects changed after the backup (or the backup does not "
                       "record when they were last changed), so a rollback would restore "
                       "old content. Nothing was deleted. Take a new backup."}, ok=False)
    return before, typed


_NOTES = {
    "APPLIED": "Everything listed is confirmed gone.",
    "PARTIAL": "Some objects are gone and some still exist. Do NOT run the delete again; "
               "offer the rollback (it re-creates only what is gone).",
    "NOT_APPLIED": "The server failed and every object still exists.",
    "UNKNOWN": "The call timed out, hit a gateway error, or gave no clear answer, and "
               "nothing is gone YET; the server may still be working. Do NOT run the "
               "delete again. Wait, then run cascade-preview and check the objects.",
}


def _report_after_delete(client, result: Dict[str, Any], guid: str, source_type: str,
                         status: Optional[int], body: Any, before: Set[str],
                         typed: Dict[str, str], manifest: Dict[str, Any]) -> None:
    """The delete has been sent: decide what happened from which objects still exist,
    always print a status, never re-send."""
    expected: Set[str] = before | {guid}
    try:
        gone = (set(typed) - set(present_objects(client, typed))) & expected
    except (Exception, SystemExit):
        _emit({**result, "status": "UNKNOWN", "http_status": status, "expected": sorted(expected),
               "note": "The delete was sent, but whether the objects still exist could not be "
                       "checked. Do NOT run the delete again. Run cascade-preview and check "
                       "the objects before anything else."}, ok=False)
    outcome = classify_gone(expected, gone)
    if outcome == "NOT_APPLIED" and not definite_failure(status, body):
        outcome = "UNKNOWN"     # nothing proves the server stopped: it may still be working
    try:
        named = set(mentioned(body, guid)) | ({guid} if source_type == "LOGICAL_TABLE" else set())
        readable = True
    except CascadeError:
        named, readable = set(), False
    without_backup = sorted(named - backed_up_deletes(manifest)) if status == 200 else []
    _emit({**result, "status": outcome, "http_status": status,
           "server_response": None if status in (None, 200) else str(body)[:1000],
           "deleted": sorted(gone), "still_present": sorted(expected - gone),
           "deleted_without_backup": without_backup, "response_readable": readable,
           "note": _NOTES[outcome]},
          ok=outcome == "APPLIED" and status == 200 and readable and not without_backup)


@app.command("cascade-delete")
def cascade_delete_cmd(
    profile: Optional[str] = _profile_option,
) -> None:
    """Delete ONE object and everything that depends on it. IRREVERSIBLE on the server.

    Reads a plan JSON on stdin:

    \b
      {"guid": "<source.guid from cascade-preview>", "type": "LOGICAL_TABLE" | "LOGICAL_COLUMN",
       "backup_dir": "<ts dependency backup output dir>", "confirm": "DELETE"}

    Refuses, sending nothing, unless the caller is an administrator, the backup came from
    this cluster and Org with every file readable, nothing in it changed since it was
    taken, no Sets or feedback would be deleted unlisted, every object is visible to the
    existence check, and a fresh preview lists exactly the objects backed up for
    deletion. Sends the delete once. Output: JSON whose `status` is APPLIED, PARTIAL,
    NOT_APPLIED, UNKNOWN, REFUSED, NOT_AVAILABLE, BLOCKED, NOT_VISIBLE, RECHECK_MISMATCH,
    STALE_BACKUP or BAD_BACKUP. Exit 0 only for APPLIED, with every object confirmed gone
    and backed up.
    """
    try:
        plan = check_plan(json.load(sys.stdin))
    except json.JSONDecodeError as e:
        _fail(f"Invalid JSON on stdin: {e}")
    except CascadeError as e:
        _fail(str(e))
    guid, source_type, backup_dir = plan["guid"], plan["type"], plan["backup_dir"]
    manifest = _load_backup(backup_dir)
    resolved_profile = resolve_profile(profile)
    client = ThoughtSpotClient(resolved_profile)
    before, typed = _checks_before_delete(client, guid, source_type, manifest)

    status, body = _post(client, source_type, guid, apply=True)
    result: Dict[str, Any] = {
        "source": {"guid": guid, "type": source_type}, "backup_dir": backup_dir,
        "rollback": f"ts dependency rollback --backup-dir {shlex.quote(backup_dir)} "
                    f"--profile {shlex.quote(resolved_profile)}"}
    if status == 400 and _refusal(body):
        _emit({**result, "status": "REFUSED", "details": _refusal(body),
               "note": "A ThoughtSpot rule blocks this delete. Nothing was deleted."}, ok=False)
    _report_after_delete(client, result, guid, source_type, status, body, before, typed, manifest)
