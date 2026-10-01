"""Grant provenance on a reusable Set — spec §5.

Live facts (spec §2): sharing an Answer copies a VIEW grant onto each Set it uses, to the
same principal (F7); unsharing does not remove it (F8); you can only build an Answer with a
Set you can already use (F9). DEFINED grants only — EFFECTIVE is meaningless on
admin-heavy clusters (F11).

Parsing keys by `metadata_id` only, never by `metadata_type`: the Set reads back as
`COLUMN` (F6) and an Answer as `QUESTION_ANSWER_BOOK` or `ANSWER` depending on the call.
"""
from __future__ import annotations

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

    A Set guid absent from the result is returned as-is (the caller reads it as no grants):
    the API returns one entry per requested object, so absence is not a failure signal.
    """
    objs = [{"identifier": set_guid, "type": "LOGICAL_COLUMN"}] + [
        {"identifier": d["guid"], "type": d["type"]} for d in consumers.get("dependents", [])]
    try:
        resp = client.post(PERMS, json={"metadata": objs, "permission_type": "DEFINED"})
        return parse_permissions(resp.json())
    except (Exception, SystemExit):
        return None


def provenance(set_grants: List[dict], consumer_grants: Dict[str, List[dict]],
               owner_ids: set) -> List[dict]:
    """Label each Set grant. First match wins; REQUIRED before EXPLAINED (spec §5).
    Matching is by same principal — group membership is never expanded."""
    granted = {gr["principal_id"] for gs in consumer_grants.values() for gr in gs}
    out = []
    for gr in set_grants:
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
