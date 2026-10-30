"""ts dependency cascade-preview / cascade-delete — server-side cascade delete.

Attaches to the `app` Typer group in `dependency.py` (the `dependency_apply.py` pattern;
`cli.py` imports this module to register the commands).

`cascade-preview` is the dry run: it changes nothing. `cascade-delete` is the only
writing command, and enforces in code what the ts-dependency-manager skill also says
in prose: an admin caller, exactly one object, a typed confirmation, a readable backup
from the same cluster that nothing has changed since, and a fresh preview that matches
that backup immediately before the delete. The delete is sent ONCE and never retried.
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
from typing import Any, Dict, Optional, Set, Tuple

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.commands.dependency import app, _profile_option
from ts_cli.dependency.backup import V2_TYPE_MAP
from ts_cli.dependency.cascade import (
    CASCADE_PATH,
    CASCADE_TYPES,
    CascadeError,
    backed_up_deletes,
    backup_problems,
    backup_type,
    cascade_form,
    check_plan,
    classify_gone,
    deleted_set,
    is_admin,
    mentioned,
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
    gateway error — the server may still be working)."""
    try:
        resp = client.request(
            "POST", CASCADE_PATH, data=cascade_form(source_type, guid, apply=apply),
            raise_for_status=False, idempotent=not apply, timeout=600 if apply else 120)
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


def _present(client: ThoughtSpotClient, typed: Dict[str, str]) -> Dict[str, Optional[int]]:
    """GUID → `modified` (ms) for each object in `typed` (GUID → v2 metadata type) that
    still exists. An absent GUID is gone (live 2026-10-30: v2 search returns nothing for
    a deleted object, one row for a live one)."""
    if not typed:
        return {}
    rows = client.post("/api/rest/2.0/metadata/search", json={
        "metadata": [{"identifier": g, "type": t} for g, t in typed.items()],
        "record_size": -1, "include_headers": True}).json()
    return {r.get("metadata_id"): (r.get("metadata_header") or {}).get("modified")
            for r in rows if r.get("metadata_id") in typed}


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
    if status == 400 and _refusal(body):
        _emit({"status": "REFUSED", "details": _refusal(body),
               "note": "A ThoughtSpot rule blocks this delete. Nothing was changed."}, ok=False)
    if status != 200:
        _fail(f"Cascade preview failed: HTTP {status}: {str(body)[:500]}")
    try:
        return parse_preview(body, guid)
    except CascadeError as e:
        _fail(str(e))


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
    author, the object to back up (`backup_source`), and the server's CSV. `source.guid`
    is the GUID to pass to `cascade-delete`.
    """
    if source_type not in CASCADE_TYPES:
        _fail(f"--type must be one of {', '.join(CASCADE_TYPES)}.")
    client = ThoughtSpotClient(resolve_profile(profile))
    user = _admin_user(client)
    target = _resolve_target(client, ref, source_type, column)
    preview = _preview_or_exit(client, target["type"], target["guid"])
    _emit({"status": "PREVIEW", "source": {"guid": target["guid"], "type": target["type"]},
           "requested_by": user, "objects": preview["objects"],
           **summarize(preview["objects"], user),
           "source_deleted": target["type"] == "LOGICAL_TABLE",
           "backup_source": target["backup_source"], "csv": preview["csv"]}, ok=True)


def _readable(path: str) -> bool:
    try:
        with open(path) as f:
            json.load(f)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _load_backup(backup_dir: str) -> Tuple[Dict[str, Any], int]:
    """(manifest, the time it was written in ms) — or exit, having deleted nothing."""
    manifest_path = os.path.join(backup_dir, "manifest.json")
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
        return manifest, int(os.path.getmtime(manifest_path) * 1000)
    except (OSError, ValueError) as e:
        _fail(f"Cannot read the backup manifest {manifest_path}: {e}. Nothing was deleted.")


def _checks_before_delete(client, guid: str, source_type: str, manifest: Dict[str, Any],
                          backup_ms: int) -> Tuple[Set[str], Dict[str, str]]:
    """Every refusal that comes before the delete is sent. Returns the GUIDs the delete
    removes (`before`) and the objects to watch, typed for v2 search (`typed`)."""
    if manifest.get("base_url") != client.base_url:
        _fail(f"The backup was taken from {manifest.get('base_url')}, not {client.base_url}. "
              "Nothing was deleted.")
    _admin_user(client)
    backup_source = _resolve_target(client, guid, source_type, None)["backup_source"]["guid"]
    files = {o.get("backup_file") or "": _readable(o.get("backup_file") or "")
             for o in manifest.get("objects") or []}
    problems = backup_problems(manifest, guid, source_type, backup_source, files)
    if problems:
        _emit({"status": "BAD_BACKUP", "problems": problems,
               "note": "This backup cannot protect this delete. Nothing was deleted."}, ok=False)

    objects = _preview_or_exit(client, source_type, guid)["objects"]
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
    changed = stale(_present(client, typed), backup_ms)
    if changed:
        _emit({"status": "STALE_BACKUP", "changed_since_backup": changed,
               "note": "These objects changed after the backup, so a rollback would restore "
                       "old content. Nothing was deleted. Take a new backup."}, ok=False)
    return before, typed


_NOTES = {
    "APPLIED": "Everything listed is confirmed gone.",
    "PARTIAL": "Some objects are gone and some still exist. Do NOT run the delete again; "
               "offer the rollback.",
    "NOT_APPLIED": "The server failed and every object still exists.",
    "UNKNOWN": "The call timed out or hit a gateway error and nothing is gone YET; the "
               "server may still be working. Do NOT run the delete again. Wait, then run "
               "cascade-preview and check the objects.",
}


def _report_after_delete(client, result: Dict[str, Any], guid: str, source_type: str,
                         status: Optional[int], body: Any, before: Set[str],
                         typed: Dict[str, str], manifest: Dict[str, Any]) -> None:
    """The delete has been sent: decide what happened from which objects still exist,
    always print a status, never re-send."""
    expected: Set[str] = before | {guid}
    try:
        gone = (set(typed) - set(_present(client, typed))) & expected
    except (Exception, SystemExit):
        _emit({**result, "status": "UNKNOWN", "http_status": status, "expected": sorted(expected),
               "note": "The delete was sent, but whether the objects still exist could not be "
                       "checked. Do NOT run the delete again. Run cascade-preview and check "
                       "the objects before anything else."}, ok=False)
    outcome = classify_gone(expected, gone)
    if status is None and outcome == "NOT_APPLIED":
        outcome = "UNKNOWN"     # a timeout or gateway error: the server may still be working
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
    this cluster with every file readable, nothing in it changed since it was taken, and
    a fresh preview lists exactly the objects backed up for deletion. Sends the delete
    once. Output: JSON whose `status` is APPLIED, PARTIAL, NOT_APPLIED, UNKNOWN, REFUSED,
    RECHECK_MISMATCH, STALE_BACKUP or BAD_BACKUP. Exit 0 only for APPLIED, with every
    object confirmed gone and backed up.
    """
    try:
        plan = check_plan(json.load(sys.stdin))
    except json.JSONDecodeError as e:
        _fail(f"Invalid JSON on stdin: {e}")
    except CascadeError as e:
        _fail(str(e))
    guid, source_type, backup_dir = plan["guid"], plan["type"], plan["backup_dir"]
    manifest, backup_ms = _load_backup(backup_dir)
    resolved_profile = resolve_profile(profile)
    client = ThoughtSpotClient(resolved_profile)
    before, typed = _checks_before_delete(client, guid, source_type, manifest, backup_ms)

    status, body = _post(client, source_type, guid, apply=True)
    result: Dict[str, Any] = {
        "source": {"guid": guid, "type": source_type}, "backup_dir": backup_dir,
        "rollback": f"ts dependency rollback --backup-dir {shlex.quote(backup_dir)} "
                    f"--profile {shlex.quote(resolved_profile)}"}
    if status == 400 and _refusal(body):
        _emit({**result, "status": "REFUSED", "details": _refusal(body),
               "note": "A ThoughtSpot rule blocks this delete. Nothing was deleted."}, ok=False)
    _report_after_delete(client, result, guid, source_type, status, body, before, typed, manifest)
