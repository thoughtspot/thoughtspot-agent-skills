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


class AmbiguousModelName(Exception):
    """Two candidate Models share a name and nothing distinguishes them.

    Raised rather than resolved, because both wrong answers are silent: picking the
    wrong SOURCE migrates the master's own dependents, and picking the wrong TARGET
    repoints content at the object it is supposed to be moving off.
    """


def owning_org_id(client) -> Optional[int]:
    """Numeric id of the Org this client's session is actually in.

    Read back from the session rather than assumed from a `--source-org` argument,
    because `auth/token/full` silently ignores a non-numeric org identifier and falls
    back to the caller's default Org.
    """
    try:
        current = (client.get("/api/rest/2.0/auth/session/user").json()
                   or {}).get("current_org") or {}
        return current.get("id")
    except (Exception, SystemExit):
        return None


def name_matches(client, name: str) -> List[dict]:
    """`[{"guid","owner_org_id"}]` for every EXACT (case-insensitive) name match.

    Returns ALL of them, because the count is the point: an Org that holds both its own
    Model and the published master of the same name has two, and which one is wanted
    depends on whether the caller is asking for the source or the target.
    """
    meta_filter = {
        "type": "LOGICAL_TABLE",
        "name_pattern": name,
        "subtypes": ["WORKSHEET", "AGGR_WORKSHEET"],
    }
    out: List[dict] = []
    for item in _search(client, meta_filter):
        if (item.get("metadata_name") or "").lower() != name.lower():
            continue
        header = item.get("metadata_header") or {}
        out.append({"guid": item.get("metadata_id"),
                    "owner_org_id": header.get("ownerOrgId")})
    return out


def select_source(candidates: List[dict], owner_org_id: Optional[int] = None) -> Optional[str]:
    """The tenant's OWN Model among `candidates` -- the thing being migrated FROM.

    Ownership is the discriminator. An Org-scoped `metadata/search` returns every object
    VISIBLE in that Org, so once the master has been published in, a name match alone can
    return the master -- and treating the master as the source would migrate ITS dependents
    and rename ITS columns.
    """
    if owner_org_id is not None:
        candidates = [c for c in candidates if c.get("owner_org_id") == owner_org_id]
    if not candidates:
        return None
    if len(candidates) > 1:
        raise AmbiguousModelName(
            f"{len(candidates)} Models match and are owned by the same Org "
            f"({', '.join(sorted(c['guid'] for c in candidates))}). Pass a GUID.")
    return candidates[0]["guid"]


def select_target(candidates: List[dict], exclude_owner_org_id: Optional[int] = None,
                  exclude_guid: Optional[str] = None) -> Optional[str]:
    """The published master among `candidates` -- the thing being migrated ONTO.

    A migration target is by definition an object the source Org does NOT own: the whole
    point is to move content off the tenant's copy and onto a governed master published in
    from elsewhere. Both exclusions are needed:

    - `exclude_guid` catches the **same-Org** topology, where source and target Org are one
      and the same and a bare name lookup can return the source object itself. That paired
      a Model with ITSELF and reported `READY` with every column trivially `MATCHED` and an
      empty rename map -- a no-op that passes every gate and surfaces only once someone
      deletes the "old" Model and the content breaks (BL-152).
    - `exclude_owner_org_id` catches the more general case of a same-named Model the source
      Org owns but which is not the one named on the command line.

    Pass `exclude_owner_org_id=None` when the two clients are on DIFFERENT clusters: Org
    ids are only meaningful within one cluster, and `Primary` is `0` on both, so the
    exclusion would refuse a legitimate Primary-to-Primary cross-cluster target.
    """
    if exclude_guid:
        candidates = [c for c in candidates if c.get("guid") != exclude_guid]
    if exclude_owner_org_id is not None:
        candidates = [c for c in candidates if c.get("owner_org_id") != exclude_owner_org_id]
    if not candidates:
        return None
    if len(candidates) > 1:
        raise AmbiguousModelName(
            f"{len(candidates)} candidate target Models match "
            f"({', '.join(sorted(c['guid'] for c in candidates))}). Publish one, or "
            f"remove the duplicate, before migrating onto it.")
    return candidates[0]["guid"]


def find_source_model(client, name: str, owner_org_id: Optional[int] = None) -> Optional[str]:
    """GUID of the Org's own Model named `name`. See `select_source`."""
    return select_source(name_matches(client, name), owner_org_id)


def find_target_model(client, name: str, exclude_owner_org_id: Optional[int] = None,
                      exclude_guid: Optional[str] = None) -> Optional[str]:
    """GUID of the published master named `name` in this client's Org. See `select_target`."""
    return select_target(name_matches(client, name), exclude_owner_org_id, exclude_guid)


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
