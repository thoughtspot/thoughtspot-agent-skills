"""Reusable Set discovery — shared by `ts sets`, `ts migrate scan-sets`/`apply`, and the audit.

One call per Model to the internal cohort listing (Confluence SAGE/4309319694; live-verified
read-only on se-thoughtspot 2026-10-02 with the v2 bearer token, 0.3–1.7s per Model):

    GET /callosum/v1/metadata/detail/{model_guid}
        ?type=LOGICAL_TABLE&showhidden=false&dropquestiondetails=false&fetchcohortcolumnsonly=true

Why not the public routes (spec §2): Model dependents omit Sets (F1); a cluster-wide
LOGICAL_COLUMN search did not finish in 2h45m on se-thoughtspot (Appendix A). `doUpdate`
is deliberately not sent — a read does not need it and its effect is undocumented.
Membership is the presence of `cohortConfig`: a Set's header `type` is often blank (F2).
This endpoint is private and undocumented; a 404 here means the build moved it.
"""
from __future__ import annotations

from typing import Dict, List, Optional

COHORT_DETAIL = "/callosum/v1/metadata/detail/{guid}"
EXPORT = "/api/rest/2.0/metadata/tml/export"
_PARAMS = {"type": "LOGICAL_TABLE", "showhidden": "false",
           "dropquestiondetails": "false", "fetchcohortcolumnsonly": "true"}


def _note(kind: str, obj: str, detail: str) -> dict:
    return {"kind": kind, "object": obj, "detail": detail}


def parse_cohort_columns(rows, model: dict) -> List[dict]:
    out = []
    for r in rows or ():
        cfg = r.get("cohortConfig")
        if not isinstance(cfg, dict):
            continue
        h = r.get("header") or {}
        out.append({"guid": h.get("id", ""), "name": h.get("name") or cfg.get("name", ""),
                    "model_guid": model["guid"], "model_name": model["name"],
                    "author": h.get("authorName", ""), "cohort_type": cfg.get("cohort_type", ""),
                    "grouping_type": cfg.get("cohort_grouping_type", ""),
                    "anchor_column": cfg.get("anchor_column_id", "")})
    return sorted(out, key=lambda s: s["name"].casefold())


def discover_sets(client, models: List[dict]) -> dict:
    result: Dict = {"sets": {}, "incomplete": [], "notes": []}
    for m in models:
        try:
            resp = client.get(COHORT_DETAIL.format(guid=m["guid"]), params=dict(_PARAMS),
                              timeout=120)
            rows = resp.json()
        except (Exception, SystemExit) as exc:  # the client exits after its own retries
            result["incomplete"].append(m["guid"])
            result["notes"].append(_note("discovery_failed", m["name"], f"cohort listing failed: {exc!r}"))
            continue
        if not isinstance(rows, list):
            result["incomplete"].append(m["guid"])
            result["notes"].append(_note("discovery_failed", m["name"],
                                         f"unexpected cohort listing response: {str(rows)[:200]}"))
            continue
        result["sets"][m["guid"]] = parse_cohort_columns(rows, m)
    return result


def by_owner(result: dict) -> Dict[str, List[dict]]:
    out = {g: [{"name": s["name"], "guid": s["guid"]} for s in sets]
           for g, sets in result.get("sets", {}).items() if sets}
    for g in result.get("incomplete", []):
        out[g] = [{"name": "(discovery incomplete)", "guid": ""}]
    return out


def export_doc(client, guid: str) -> Optional[dict]:
    from ts_cli.commands.tml import parse_edoc
    try:
        resp = client.post(EXPORT, json={"metadata": [{"identifier": guid}],
                                         "export_associated": False, "export_fqn": True,
                                         "formattype": "YAML"})
        return parse_edoc(resp.json()[0]["edoc"], "YAML")
    except (Exception, SystemExit):
        return None
