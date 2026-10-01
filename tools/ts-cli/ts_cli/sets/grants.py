"""Grant provenance on a reusable Set — spec §5.

Live facts (spec §2): sharing an Answer copies a VIEW grant onto each Set it uses, to the
same principal (F7); unsharing does not remove it (F8); you can only build an Answer with a
Set you can already use (F9). DEFINED grants only — EFFECTIVE is meaningless on
admin-heavy clusters (F11).

Parsing keys by `metadata_id` only, never by `metadata_type`: the Set reads back as
`COLUMN` (F6) and an Answer as `QUESTION_ANSWER_BOOK` or `ANSWER` depending on the call.
"""
from __future__ import annotations

import sys
from typing import Dict, List, Optional

PERMS = "/api/rest/2.0/security/metadata/fetch-permissions"
UNKNOWN_GRANTS = [{"principal_id": "", "principal_name": "", "principal_type": "",
                   "permission": "", "provenance": "UNKNOWN"}]


def parse_permissions(resp_json) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for m in (resp_json or {}).get("metadata_permission_details") or []:
        grants = out.setdefault(m.get("metadata_id", ""), [])
        for info in m.get("principal_permission_info") or []:
            for p in info.get("principal_permissions") or []:
                grants.append({"principal_id": p.get("principal_id", ""),
                               "principal_name": p.get("principal_name", ""),
                               "principal_type": info.get("principal_type", ""),
                               "permission": p.get("permission", "")})
    return out


def fetch_grants(client, set_guid: str, consumers: dict) -> Optional[Dict[str, List[dict]]]:
    """DEFINED grants on the Set and each consumer, keyed by GUID; `None` on any failure.

    `None` means UNKNOWN. That covers a request failure, a body that is not a dict, a missing
    or non-list `metadata_permission_details`, and a missing entry for the Set itself. DEFINED
    reports "nothing shared" as a PRESENT entry with an empty principal list (live 2026-07-26,
    commands/share.py), so an absent Set entry is an anomaly, never "no grants". A missing
    CONSUMER entry is tolerated: it can only cost a grant its EXPLAINED label.
    """
    objs = [{"identifier": set_guid, "type": "LOGICAL_COLUMN"}] + [
        {"identifier": d["guid"], "type": d["type"]} for d in consumers.get("dependents", [])]
    try:
        resp = client.post(PERMS, json={"metadata": objs, "permission_type": "DEFINED",
                                        "record_offset": 0, "record_size": -1})
        body = resp.json()
    except (Exception, SystemExit) as exc:
        print(f"fetch-permissions failed for {set_guid}: {exc!r}", file=sys.stderr)
        return None
    if not isinstance(body, dict):
        print(f"fetch-permissions for {set_guid}: body is {type(body).__name__}, not an object",
              file=sys.stderr)
        return None
    if not isinstance(body.get("metadata_permission_details"), list):
        print(f"fetch-permissions for {set_guid}: metadata_permission_details missing or not a list",
              file=sys.stderr)
        return None
    try:
        parsed = parse_permissions(body)
    except Exception as exc:
        print(f"fetch-permissions for {set_guid}: unparseable body: {exc!r}", file=sys.stderr)
        return None
    if set_guid not in parsed:
        print(f"fetch-permissions for {set_guid}: no entry for the Set in the response",
              file=sys.stderr)
        return None
    return parsed


def provenance(set_grants: List[dict], consumer_grants: Dict[str, List[dict]],
               owner_ids: set) -> List[dict]:
    """Label each Set grant. First match wins; REQUIRED before EXPLAINED (spec §5).
    Matching is by same principal — group membership is never expanded. A `NO_ACCESS` row
    is not access, so it is dropped: it must never surface as a revocation candidate. The
    same holds on the consumer side: a `NO_ACCESS` row there explains nothing."""
    granted = {gr["principal_id"] for gs in consumer_grants.values() for gr in gs
               if gr.get("permission") != "NO_ACCESS"}
    out = []
    for gr in set_grants:
        if gr["permission"] == "NO_ACCESS":
            continue
        pid = gr["principal_id"]
        if gr["permission"] == "MODIFY":
            label = "DIRECT"
        elif pid in owner_ids:
            label = "REQUIRED"
        elif pid in granted:
            label = "EXPLAINED"
        else:
            label = "UNEXPLAINED"
        out.append(dict(gr, provenance=label))
    return out
