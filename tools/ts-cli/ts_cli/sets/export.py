"""Export one reusable Set's TML to a file (`ts sets inventory --export-tml`). Read-only.

A reusable Set is a standalone object with its own GUID, so the public
`POST /api/rest/2.0/metadata/tml/export` returns it by GUID alone: a document whose top-level
key is `cohort:` (live-verified 2026-11-11 on se-thoughtspot, 11 Sets; open item #9). What
the public API does not give is a Model's Sets in practical time: the Model's associated
export returned none, and a cluster-wide `LOGICAL_COLUMN` search did not finish in 2h45m.
Finding the GUIDs is `discover.py`'s job.

Spec §7 applies: an export that fails, is refused, or returns anything other than this Set's
cohort TML is reported as failed and writes no file. A file is never written from a body we
could not confirm is the Set asked for, and the TML is written exactly as the server sent it,
never re-serialised (a YAML round trip can change string values).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

from ts_cli.commands.tml import strip_nonprintable
from ts_cli.tml_common import export_item_doc

TML_EXPORT = "/api/rest/2.0/metadata/tml/export"

# Anything but word characters (Unicode letters and digits included), dot, space and hyphen.
_UNSAFE = re.compile(r"[^\w. -]+")


# Bytes, not characters: file systems cap a name at 255 bytes (ext4, XFS, Btrfs), and a
# CJK character is 3 bytes in UTF-8. 200 leaves room for "__<guid>.cohort.tml" (49 bytes).
_MAX_NAME_BYTES = 200


def safe_name(value: str, fallback: str = "unnamed") -> str:
    """A single path segment: no separators, no leading or trailing dots, never empty, and
    at most `_MAX_NAME_BYTES` in UTF-8, cut on a character boundary."""
    cleaned = _UNSAFE.sub("_", str(value or "")).strip(" ._")
    cut = cleaned.encode("utf-8")[:_MAX_NAME_BYTES].decode("utf-8", errors="ignore")
    return cut.rstrip(" ._") or fallback


def tml_path(dest: Path, org_label: str, set_ref: dict) -> Path:
    """`<dest>/<org>/<Set name>__<guid>.cohort.tml`. The GUID keeps two Sets with the
    same name (on different Models, or the same Model) from overwriting each other."""
    return (Path(dest) / safe_name(org_label, "default")
            / f"{safe_name(set_ref.get('name'))}__{safe_name(set_ref['guid'])}.cohort.tml")


def _check(body, guid: str) -> Tuple[Optional[str], Optional[str]]:
    """(TML text as received, None) when `body` is this Set's cohort TML, else (None, reason)."""
    if not isinstance(body, list) or not body:
        return None, f"unexpected export response: {str(body)[:200]}"
    item = body[0]
    edoc = item.get("edoc") if isinstance(item, dict) else None
    # Strip non-printables for the CHECK only (thoughtspot-tml.md: a raw C1 character such
    # as U+0095 breaks the YAML parser); the file is still written exactly as received.
    probe = dict(item, edoc=strip_nonprintable(edoc)) if isinstance(edoc, str) else item
    try:
        doc, reason = export_item_doc(probe)
    except Exception as exc:  # noqa: BLE001 — unparseable TML is a failed export
        return None, f"export TML does not parse: {exc}"
    if reason:
        return None, reason
    if not isinstance(doc.get("cohort"), dict):
        return None, f"export is not Set (cohort) TML: top-level {sorted(doc)}"
    info_id = (item.get("info") or {}).get("id")
    for got in (doc.get("guid"), info_id):
        if got not in (None, guid):
            return None, f"export returned a different object ({got})"
    if not isinstance(edoc, str):
        return None, "export TML is not text"
    return (edoc if edoc.endswith("\n") else edoc + "\n"), None


def export_set_tml(client, set_ref: dict, path: Path) -> Optional[str]:
    """Write the Set's TML (YAML, with FQNs so it re-imports against the right Model) to
    `path`. Returns None on success, else the reason it failed; no file is written then.

    `edoc_format` is the v2 key (`formattype` is ignored: live, it returned JSON for
    YAML). Should the server still answer JSON, that JSON is written as received —
    ThoughtSpot imports JSON TML too (VALIDATE_ONLY, live 2026-11-11)."""
    body = {"metadata": [{"identifier": set_ref["guid"]}], "export_fqn": True,
            "edoc_format": "YAML"}
    try:
        resp = client.post(TML_EXPORT, json=body, raise_for_status=False)
        if getattr(resp, "status_code", 200) >= 400:
            return f"HTTP {resp.status_code}: {str(getattr(resp, 'text', ''))[:200]}"
        text, reason = _check(resp.json(), set_ref["guid"])
    # The client raises SystemExit after its own retries, or when re-auth fails: one
    # Set's failure must not end the inventory (the sibling modules catch it the same way).
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        return f"export call failed: {exc!r}"
    if reason:
        return reason
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        return f"could not write {path}: {exc}"
    return None
