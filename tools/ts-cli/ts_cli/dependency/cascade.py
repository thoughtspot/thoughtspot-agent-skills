"""ts_cli.dependency.cascade — pure logic behind `ts dependency cascade-preview`/`cascade-delete`.

A cascade delete removes an object AND everything that depends on it, in one server-side
call: `POST /callosum/v1/dependency/delete-with-dependents`. The endpoint has no v2
equivalent. It is called with the normal v2 bearer token (live-verified 2026-10-30, the
same way `sets/discover.py` calls `/callosum/v1/metadata/detail`), takes a FORM body
(JSON is answered 415), and is admin-only even for the preview (a non-admin gets 403
"Tenant privilege required"). Request shape and parameter names were established by the
ts-dependency-cleanup investigation (PR #666, its open items #12, #16, #17).

Why the preview, and not the dependents lookup, sizes a delete: a lookup returns DIRECT
dependents only, while the cascade takes everything downstream of them too — 4 reported
vs 12 deleted, live 2026-09-07 (ts-dependency-manager open-items #26). Whether the
preview's `dependents[<guid>]` list itself holds the full closure of a deep graph is NOT
proven, so the scope read here is every object the response mentions anywhere: each
`dependents` key's list and every CSV `dependentGUID`.

The preview cannot say whether a delete happened: for an object that is already gone it
answers `{"dependents": {"<guid>": []}}`, the same as a live object with no dependents
(live 2026-10-30). Outcomes are decided by existence checks instead (`classify_gone`).

PURE functions only — no network, no filesystem. The I/O shell is
`ts_cli.commands.dependency_cascade`.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, Iterable, List, Optional, Set

from ts_cli.report.resolver import looks_like_guid

CASCADE_PATH = "/callosum/v1/dependency/delete-with-dependents"
CASCADE_TYPES = ("LOGICAL_TABLE", "LOGICAL_COLUMN")
ADMIN_PRIVILEGE = "ADMINISTRATION"
CONFIRM_WORD = "DELETE"

# Preview `type` (+ `subType` for LOGICAL_TABLE) → the type vocabulary
# `ts dependency backup` / `rollback` use. An unlisted pair is refused, never guessed.
_BACKUP_TYPE = {
    ("PINBOARD_ANSWER_BOOK", None): "LIVEBOARD",
    ("QUESTION_ANSWER_BOOK", None): "ANSWER",
    ("LOGICAL_TABLE", "WORKSHEET"): "MODEL",
    ("LOGICAL_TABLE", "SQL_VIEW"): "SQL_VIEW",
    ("LOGICAL_TABLE", "AGGR_WORKSHEET"): "VIEW",
    ("LOGICAL_TABLE", "ONE_TO_ONE_LOGICAL"): "TABLE",
}


class CascadeError(ValueError):
    """A preview or plan this module refuses to act on. The message is user-facing."""


def is_admin(session_user: Dict[str, Any]) -> bool:
    """True when `auth/session/user` lists the ADMINISTRATION privilege."""
    return ADMIN_PRIVILEGE in (session_user.get("privileges") or [])


def cascade_form(source_type: str, guid: str, *, apply: bool) -> Dict[str, str]:
    """The form body for one cascade call. `apply=False` is the preview (dry run)."""
    if source_type not in CASCADE_TYPES:
        raise CascadeError(f"type must be one of {', '.join(CASCADE_TYPES)}, got {source_type!r}.")
    return {
        "type": source_type,
        "id": json.dumps([guid]),
        "operation_type": "DELETE_OBJECT_CASCADE",
        "apply_changes": "true" if apply else "false",
    }


def backup_type(dependent_type: str, subtype: Optional[str]) -> str:
    key = (dependent_type, subtype or None) if dependent_type == "LOGICAL_TABLE" else (dependent_type, None)
    if key not in _BACKUP_TYPE:
        raise CascadeError(
            f"Unsupported object type {dependent_type}/{subtype or '-'} (Sets and uploaded "
            "tables are not handled). Stopping rather than guessing how to back it up or "
            "restore it.")
    return _BACKUP_TYPE[key]


def _csv_rows(csv_text: Any) -> List[Dict[str, str]]:
    if not isinstance(csv_text, str):
        raise CascadeError("The cascade response's 'csv' field is not text; refusing to read it.")
    return [r for r in csv.DictReader(io.StringIO(csv_text)) if r.get("dependentGUID")]


def mentioned(resp_json: Any, guid: str) -> Dict[str, Dict[str, Any]]:
    """Every object a cascade response names besides `guid`: GUID → what is known of it.

    Reads each `dependents` key's list, not only `dependents[guid]`, and every CSV row,
    because whether `dependents[guid]` alone is the full closure is unproven. Raises
    CascadeError on any shape it cannot read — an unreadable answer is never "nothing".
    """
    if not isinstance(resp_json, dict) or not isinstance(resp_json.get("dependents"), dict):
        raise CascadeError("The cascade response has no 'dependents' map; refusing to read it.")
    if guid not in resp_json["dependents"]:
        raise CascadeError(f"The cascade response does not mention {guid}; refusing to read it.")
    out = _from_dependents(resp_json["dependents"], guid)
    _add_csv_rows(out, _csv_rows(resp_json.get("csv", "")), guid)
    return out


def _from_dependents(deps: Dict[str, Any], guid: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for entries in deps.values():
        if entries is None:
            continue
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            raise CascadeError("A 'dependents' entry is not a list of objects; refusing to read it.")
        for e in entries:
            if e.get("id") and e["id"] != guid:
                out.setdefault(e["id"], {"name": e.get("name"), "dependent_type": e.get("type"),
                                         "subtype": e.get("subType"), "author": e.get("authorName")})
    return out


def _add_csv_rows(out: Dict[str, Dict[str, Any]], rows: List[Dict[str, str]], guid: str) -> None:
    for row in rows:
        if row["dependentGUID"] == guid:
            continue
        info = out.setdefault(row["dependentGUID"], {
            "name": row.get("dependentName"), "dependent_type": row.get("dependentType"),
            "subtype": row.get("dependentSubType") or None, "author": None})
        # The `dependents` entries carry no usable author (authorName is null, live
        # 2026-10-30); the CSV does, and the Org the object lives in.
        info["author"] = row.get("author") or info.get("author")
        info["org"] = row.get("orgName") or info.get("org")


def parse_preview(resp_json: Any, guid: str) -> Dict[str, Any]:
    """Normalise a cascade preview into one row per object it would delete besides `guid`.

    Returns `{"objects": [{guid, name, type, dependent_type, subtype, author, org}], "csv"}`.
    """
    objects = [{"guid": g, "name": i.get("name"), "type": backup_type(i.get("dependent_type") or "", i.get("subtype")),
                "dependent_type": i.get("dependent_type"), "subtype": i.get("subtype"),
                "author": i.get("author"), "org": i.get("org")}
               for g, i in mentioned(resp_json, guid).items()]
    return {"objects": objects, "csv": resp_json.get("csv") or ""}


def summarize(objects: List[Dict[str, Any]], username: str) -> Dict[str, Any]:
    """Counts the confirmation screen needs: per type, total, and owned by someone else
    (an object whose author the server did not report is counted separately, never as
    the caller's)."""
    counts: Dict[str, int] = {}
    for o in objects:
        counts[o["type"]] = counts.get(o["type"], 0) + 1
    return {"counts": counts, "total": len(objects),
            "owned_by_others": sum(1 for o in objects if o.get("author") and o["author"] != username),
            "author_unknown": sum(1 for o in objects if not o.get("author"))}


def deleted_set(objects: Iterable[Dict[str, Any]], guid: str, source_type: str) -> Set[str]:
    """Every GUID the cascade deletes that a backup must hold. A LOGICAL_TABLE source is
    itself deleted; a LOGICAL_COLUMN's owning Table or Model is modified, not deleted."""
    s = {o["guid"] for o in objects}
    if source_type == "LOGICAL_TABLE":
        s.add(guid)
    return s


def backed_up_deletes(manifest: Dict[str, Any]) -> Set[str]:
    return {o["guid"] for o in manifest.get("objects") or [] if o.get("intent") == "DELETE"}


def check_plan(plan: Any) -> Dict[str, str]:
    """Validate a `cascade-delete` plan. Returns `{guid, type, backup_dir}`."""
    if not isinstance(plan, dict):
        raise CascadeError("The plan must be a JSON object.")
    if plan.get("confirm") != CONFIRM_WORD:
        raise CascadeError(f'The plan must carry "confirm": "{CONFIRM_WORD}" exactly.')
    guid = plan.get("guid")
    if not isinstance(guid, str) or not looks_like_guid(guid):
        raise CascadeError(
            "The plan must name exactly ONE object by its GUID ('guid'). "
            "To delete several objects, run the preview, backup and delete once per object.")
    if plan.get("type") not in CASCADE_TYPES:
        raise CascadeError(f"'type' must be one of {', '.join(CASCADE_TYPES)}.")
    if not plan.get("backup_dir"):
        raise CascadeError("'backup_dir' is required: a `ts dependency backup` of the preview.")
    return {"guid": guid, "type": plan["type"], "backup_dir": plan["backup_dir"]}


def backup_problems(manifest: Dict[str, Any], guid: str, source_type: str,
                    backup_source: str, readable: Dict[str, bool]) -> List[str]:
    """Why this backup cannot protect this delete; empty when it can.

    `readable` maps each manifest entry's `backup_file` to whether it exists and parses.
    """
    problems = []
    if (manifest.get("source_object") or {}).get("guid") != backup_source:
        problems.append(f"its source is {(manifest.get('source_object') or {}).get('guid')}, "
                        f"not {backup_source}")
    entries = {o.get("guid"): o for o in manifest.get("objects") or []}
    want_intent = "DELETE" if source_type == "LOGICAL_TABLE" else "FIX_SOURCE"
    if (entries.get(backup_source) or {}).get("intent") != want_intent:
        problems.append(f"it holds no {want_intent} entry for {backup_source}")
    for o in manifest.get("objects") or []:
        if not readable.get(o.get("backup_file") or "", False):
            problems.append(f"the backup file for {o.get('guid')} is missing or unreadable")
    return problems


def recheck(now: Set[str], manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Compare a fresh preview with the backup. Apply only when `match` is True."""
    backed = backed_up_deletes(manifest)
    not_backed_up = sorted(now - backed)
    no_longer_listed = sorted(backed - now)
    return {"match": not not_backed_up and not no_longer_listed,
            "not_backed_up": not_backed_up, "no_longer_listed": no_longer_listed}


def stale(modified_ms: Dict[str, Optional[int]], backup_epoch_ms: int) -> List[str]:
    """Objects modified after the backup was taken. Their backup no longer matches them,
    so a rollback would restore old content. Unknown modification time counts as stale."""
    return sorted(g for g, m in modified_ms.items() if m is None or m > backup_epoch_ms)


def classify_gone(expected: Set[str], gone: Set[str]) -> str:
    """`APPLIED` — everything expected is gone; `NOT_APPLIED` — nothing is; else `PARTIAL`."""
    if expected and gone >= expected:
        return "APPLIED"
    return "NOT_APPLIED" if not (gone & expected) else "PARTIAL"
