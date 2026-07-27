from __future__ import annotations

import json
import re
from typing import List, Optional, Set

from ts_cli.migrate.schema import ColumnInfo

_TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")


def export_parsed(client, guid: str) -> dict:
    """Export one object's TML and parse its edoc (mirrors aggregate._export_tml)."""
    from ts_cli.commands.tml import parse_edoc
    resp = client.post("/api/rest/2.0/metadata/tml/export", json={
        "metadata": [{"identifier": guid}],
        "export_associated": False,
        "export_fqn": True,
        "formattype": "YAML",
    })
    return parse_edoc(resp.json()[0]["edoc"], "YAML")


def model_columns(client, model_guid: str, doc: Optional[dict] = None) -> List[ColumnInfo]:
    from ts_cli.commands.tml import detect_tml_type
    if doc is None:
        doc = export_parsed(client, model_guid)
    section = doc.get(detect_tml_type(doc)) or {}
    out: List[ColumnInfo] = []
    for c in section.get("columns", []) or []:
        props = c.get("properties") or {}
        out.append(ColumnInfo(
            name=c.get("name", ""),
            column_id=c.get("column_id", ""),
            column_type=props.get("column_type", ""),
        ))
    return out


def _search(client, meta_filter: dict) -> list:
    resp = client.post("/api/rest/2.0/metadata/search", json={
        "metadata": [meta_filter],
        "record_size": -1,
        "record_offset": 0,
    })
    return resp.json()


def find_model_by_name(client, name: str) -> Optional[str]:
    meta_filter = {
        "type": "LOGICAL_TABLE",
        "name_pattern": name,
        "subtypes": ["WORKSHEET", "AGGR_WORKSHEET"],
    }
    for item in _search(client, meta_filter):
        if (item.get("metadata_name") or "").lower() == name.lower():
            return item.get("metadata_id")
    return None


def list_models(client) -> List[dict]:
    items = _search(client, {"type": "LOGICAL_TABLE", "subtypes": ["WORKSHEET", "AGGR_WORKSHEET"]})
    return [{"guid": i.get("metadata_id"), "name": i.get("metadata_name")} for i in items]


def list_dependents(client, model_guid: str) -> List[dict]:
    from ts_cli.commands.metadata import _collect_dependents
    return _collect_dependents(client, model_guid)


def used_column_names(client, dependents: List[dict], source_col_names: Set[str]) -> Set[str]:
    """Scan all dependents' TML for bracketed column-name tokens, in ONE export call.

    API calls must scale with tiers x models, not object count -- so every
    dependent GUID is exported in a single metadata/tml/export request rather
    than one request per dependent.
    """
    if not dependents:
        return set()

    from ts_cli.commands.tml import parse_edoc

    lower_to_orig = {n.lower(): n for n in source_col_names}
    used: Set[str] = set()
    resp = client.post("/api/rest/2.0/metadata/tml/export", json={
        "metadata": [{"identifier": d["guid"]} for d in dependents],
        "export_associated": False,
        "export_fqn": True,
        "formattype": "YAML",
    })
    for item in resp.json():
        doc = parse_edoc(item["edoc"], "YAML")
        for tok in _TOKEN_RE.findall(json.dumps(doc)):
            key = tok.strip().lower()
            if key in lower_to_orig:
                used.add(lower_to_orig[key])
    return used


def all_cohort_column_rows(client) -> List[dict]:
    """Every `LOGICAL_COLUMN` on the cluster, for the Phase 0 cohort scan.

    ONE call for the whole Org rather than one per Model, because the scan's whole
    justification is being cheap enough to run fleet-wide before committing to Phase 2.
    The caller slices the result per Model via `sets_scan.extract_cohort_columns`.

    Cohort columns must be found this way. They do NOT appear in the Model's TML, so a
    TML inspection reports a clean Model that is in fact blocked -- verified live
    2026-07-26, and the reason a lift-and-shift would drop Sets silently rather than fail.
    """
    return _search(client, {"type": "LOGICAL_COLUMN"})


def column_dependents(client, column_guid: str) -> List[dict]:
    """Objects depending on one cohort column.

    Separate from `list_dependents` (which walks a Model) because the interesting question
    for a blocked tenant is narrower: not "what uses this Model" but "what would have to
    be retired or rebuilt if the Set went away".
    """
    from ts_cli.commands.metadata import _collect_dependents
    return _collect_dependents(client, column_guid)
