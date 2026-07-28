from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Set

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
        # Headers carry `ownerOrgId`, which `list_models` needs to tell an Org's OWN
        # objects from ones merely visible in it.
        "include_headers": True,
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


def list_models(client, owner_org_id: Optional[int] = None) -> List[dict]:
    """Models visible to this client, optionally narrowed to those the Org OWNS.

    `owner_org_id` is not a convenience filter. An Org-scoped `metadata/search` returns
    every object VISIBLE in that Org, which includes Primary-owned shared and system
    objects -- so a fleet scan without this counts one Primary-owned Model once per tenant
    Org and reports it as each tenant's blocker. Observed live 2026-07-27: the same
    `T1_PUBLISH_MODEL` GUID came back as a blocker under both ORG1 and ORG2.

    That matters because the number this feeds is the whole point of the Phase 0 scan. A
    tenant's blocker is a Model that tenant OWNS; a Primary-owned Model showing up in its
    search results is visibility, not ownership.

    Same failure mode as `tenancy._groups_in_org`: the row's own header is the authority,
    not which client fetched it.
    """
    items = _search(client, {"type": "LOGICAL_TABLE", "subtypes": ["WORKSHEET", "AGGR_WORKSHEET"]})
    out = []
    for i in items:
        header = i.get("metadata_header") or {}
        if owner_org_id is not None and header.get("ownerOrgId") != owner_org_id:
            continue
        out.append({"guid": i.get("metadata_id"), "name": i.get("metadata_name")})
    return out


def list_dependents(client, model_guid: str) -> List[dict]:
    from ts_cli.commands.metadata import _collect_dependents
    return _collect_dependents(client, model_guid)


def export_dependents(client, dependents: List[dict]) -> List[dict]:
    """Every dependent's parsed TML, in ONE export call.

    API calls must scale with tiers x models, not object count. Split out of
    `used_column_names` so the column scan and the dependent CLASSIFICATION share one
    export instead of each paying for their own.
    """
    if not dependents:
        return []
    from ts_cli.commands.tml import parse_edoc

    resp = client.post("/api/rest/2.0/metadata/tml/export", json={
        "metadata": [{"identifier": d["guid"]} for d in dependents],
        "export_associated": False,
        "export_fqn": True,
        "formattype": "YAML",
    })
    docs = []
    for item in resp.json():
        edoc = item.get("edoc")
        docs.append(parse_edoc(edoc, "YAML") if edoc else {})
    return docs


def used_column_names_in(docs: List[dict], source_col_names: Set[str]) -> Set[str]:
    """Bracketed column tokens present across already-exported dependent documents."""
    lower_to_orig = {n.lower(): n for n in source_col_names}
    used: Set[str] = set()
    for doc in docs:
        for tok in _TOKEN_RE.findall(json.dumps(doc)):
            key = tok.strip().lower()
            if key in lower_to_orig:
                used.add(lower_to_orig[key])
    return used


def used_column_names(client, dependents: List[dict], source_col_names: Set[str]) -> Set[str]:
    """Scan all dependents' TML for bracketed column-name tokens, in ONE export call."""
    if not dependents:
        return set()
    return used_column_names_in(export_dependents(client, dependents), source_col_names)


def subtypes_by_guid(client, guids: Set[str]) -> Dict[str, str]:
    """`{guid: subtype}` for the objects content points at, in ONE search.

    The subtype is what says whether a source is a Model, a View or a Table -- and
    therefore whether the content on it is chargeable or free.
    """
    if not guids:
        return {}
    # Queried BY IDENTIFIER, not by sweeping every LOGICAL_TABLE on the cluster. The
    # sweep worked but cost a full-cluster read per call, which is indefensible inside a
    # dependent walk and would dominate a fleet-wide audit.
    resp = client.post("/api/rest/2.0/metadata/search", json={
        "metadata": [{"identifier": g, "type": "LOGICAL_TABLE"} for g in sorted(guids)],
        "include_headers": True, "record_size": -1, "record_offset": 0})
    out: Dict[str, str] = {}
    for row in resp.json():
        guid = row.get("metadata_id")
        if not guid:
            continue
        header = row.get("metadata_header") or {}
        out[guid] = header.get("type") or row.get("metadata_subtype") or ""
    return out


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


# ---------------------------------------------------------------------------
# Phase 2 discovery — what `apply` lifts, and what it binds to
# ---------------------------------------------------------------------------

def scaffolding_objects(client, model_names: List[str]) -> dict:
    """`{"tables": [...], "models": [...]}` of source GUIDs for the named Models.

    The Tables come from each Model's own `model_tables[]` rather than from a search,
    because a search would sweep up every Table in the Org -- including ones this tenant's
    Models do not use, which would then be lifted, renamed and deleted for nothing.
    """
    models: List[str] = []
    tables: List[str] = []
    for name in model_names:
        guid = find_model_by_name(client, name)
        if not guid:
            continue
        models.append(guid)
        doc = export_parsed(client, guid)
        body = doc.get("model") or doc.get("worksheet") or {}
        for entry in body.get("model_tables") or []:
            fqn = entry.get("fqn")
            if fqn and fqn not in tables:
                tables.append(fqn)
    return {"tables": tables, "models": models}


def bespoke_content(client, model_guids: List[str]) -> dict:
    """Tenant-authored dependents of the given Models, split by lift order.

    Views before Answers before Liveboards: intra-batch references remap on import, but
    only for objects already in the batch, and the reference direction runs
    Liveboard -> Answer -> View.
    """
    buckets = {"views": [], "answers": [], "liveboards": []}
    key = {"LOGICAL_TABLE": "views", "ANSWER": "answers", "LIVEBOARD": "liveboards"}
    for guid in model_guids:
        for dep in list_dependents(client, guid):
            dep_type = str(dep.get("type") or dep.get("metadata_type") or "").upper()
            dep_guid = dep.get("id") or dep.get("metadata_id")
            bucket = key.get(dep_type)
            if bucket and dep_guid and dep_guid not in buckets[bucket]:
                buckets[bucket].append(dep_guid)
    return buckets


def connection_names(client) -> List[str]:
    """Connection display names visible in this client's Org.

    Names, never GUIDs: a Table TML's `connection` block resolves by name, and that is
    exactly what makes a same-named connection in the target Org let lifted TML import
    unchanged.
    """
    resp = client.post("/api/rest/2.0/connection/search", json={"record_size": -1})
    return [c.get("name") for c in resp.json() if c.get("name")]


def connection_name_of(client, table_guids: List[str]) -> str:
    """The connection the tenant's scaffolding Tables sit on. Empty string if unknown."""
    for guid in table_guids:
        doc = export_parsed(client, guid)
        conn = (doc.get("table") or {}).get("connection") or {}
        if conn.get("name"):
            return conn["name"]
    return ""


def dependents_through_views(client, model_guid: str, max_depth: int = 4) -> List[dict]:
    """Dependents of a Model, following through any View in the chain.

    `_collect_dependents` is **single-hop**, which undercounts the migration's blast
    radius badly: a tenant with 200 Answers over 4 Views reports 4 dependents, and the 200
    are invisible. They do not need rewriting -- repointing the View covers them -- but
    they are what BREAKS if a View is missed or repointed wrongly, so the audit has to
    show them.

    Each row gains `via_view`: the View it was reached through, or None if direct. That is
    what lets the classifier tell "free, because this View shields it" from "free, reason
    unknown".

    Depth-capped and visited-guarded: Views can stack, and a cycle would otherwise hang a
    fleet-wide audit.
    """
    from ts_cli.migrate.classify import VIEW_BASED, kind_of

    seen = {model_guid}
    out: List[dict] = []
    frontier = [(model_guid, None)]
    for _ in range(max_depth):
        if not frontier:
            break
        next_frontier = []
        for guid, via in frontier:
            for dep in list_dependents(client, guid):
                dep_guid = dep.get("guid")
                if not dep_guid or dep_guid in seen:
                    continue
                seen.add(dep_guid)
                row = dict(dep)
                row["via_view"] = via
                out.append(row)
                # Only Views are worth following: they are the only object that shields
                # what sits on it. Following an Answer would just re-find the Liveboard
                # that embeds it, which is already in scope by its own right.
                subtypes = subtypes_by_guid(client, {dep_guid})
                if kind_of(subtypes.get(dep_guid)) == VIEW_BASED:
                    next_frontier.append((dep_guid, dep_guid))
        frontier = next_frontier
    return out
