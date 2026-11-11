"""Export one reusable Set's TML to a file (`ts sets inventory --export-tml`). Read-only.

A reusable Set is a standalone object with its own GUID, so the public
`POST /api/rest/2.0/metadata/tml/export` returns it by GUID alone: a document whose top-level
key is `cohort:` (live-verified 2026-11-11 on se-thoughtspot, set "Top Brands"; first seen
2026-06-12 on "Static Top 10"). What is NOT public is finding the GUIDs in the first place —
that is `discover.py`'s job.

Spec §7 applies: an export that fails, is refused, or returns anything other than this Set's
cohort TML is reported as failed and writes no file. A file is never written from a body we
could not confirm is the Set asked for.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

import yaml

TML_EXPORT = "/api/rest/2.0/metadata/tml/export"

_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_name(value: str, fallback: str = "unnamed") -> str:
    """A single path segment: no separators, no leading or trailing dots, never empty."""
    cleaned = _UNSAFE.sub("_", str(value or "")).strip(" ._")
    return cleaned[:120] or fallback


def tml_path(dest: Path, org_label: str, set_ref: dict) -> Path:
    """`<dest>/<org>/<Set name>__<guid>.cohort.tml`. The GUID keeps two Sets with the
    same name (on different Models, or the same Model) from overwriting each other."""
    return (Path(dest) / safe_name(org_label, "default")
            / f"{safe_name(set_ref.get('name'))}__{safe_name(set_ref['guid'])}.cohort.tml")


def _check(body, guid: str) -> Tuple[Optional[str], Optional[str]]:
    """(TML text, None) when `body` is this Set's cohort TML, else (None, reason)."""
    if not isinstance(body, list) or not body or not isinstance(body[0], dict):
        return None, f"unexpected export response: {str(body)[:200]}"
    item = body[0]
    status = ((item.get("info") or {}).get("status") or {})
    if status.get("status_code") != "OK":
        return None, f"export status {status.get('status_code')!r}: " \
                     f"{status.get('error_message') or ''}".strip()
    edoc = item.get("edoc")
    if not isinstance(edoc, str) or not edoc.strip():
        return None, "export returned no TML"
    try:
        doc = yaml.safe_load(edoc)
    except yaml.YAMLError as exc:
        return None, f"export TML does not parse: {exc}"
    if not isinstance(doc, dict) or not isinstance(doc.get("cohort"), dict):
        keys = sorted(doc) if isinstance(doc, dict) else type(doc).__name__
        return None, f"export is not Set (cohort) TML: top-level {keys}"
    if doc.get("guid") not in (None, guid):
        return None, f"export returned a different object ({doc.get('guid')})"
    return _as_yaml(edoc, doc), None


def _as_yaml(edoc: str, doc: dict) -> str:
    """YAML TML. The server can answer JSON however `formattype` is set (seen on
    se-thoughtspot 2026-11-11, for a Model as well as a Set), so a JSON body is re-emitted
    as YAML with its key order kept; a YAML body is written exactly as received."""
    if not edoc.lstrip().startswith("{"):
        return edoc if edoc.endswith("\n") else edoc + "\n"
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=1000)


def export_set_tml(client, set_ref: dict, path: Path) -> Optional[str]:
    """Write the Set's TML (YAML, with FQNs so it re-imports against the right Model) to
    `path`. Returns None on success, else the reason it failed; no file is written then."""
    body = {"metadata": [{"identifier": set_ref["guid"]}], "export_fqn": True,
            "formattype": "YAML"}
    try:
        resp = client.post(TML_EXPORT, json=body, raise_for_status=False)
        if getattr(resp, "status_code", 200) >= 400:
            return f"HTTP {resp.status_code}: {str(getattr(resp, 'text', ''))[:200]}"
        edoc, reason = _check(resp.json(), set_ref["guid"])
    except Exception as exc:  # noqa: BLE001 — any failure is reported, never swallowed
        return f"export call failed: {exc!r}"
    if reason:
        return reason
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(edoc, encoding="utf-8")
    return None
