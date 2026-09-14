"""ts_cli.report.impact_probes — network-calling dependency-impact checks.

Each function issues its own REST calls and returns a list of hit dicts. They
raise on transport error — callers wrap each in their own try/except, matching
the existing primary/monitor probe pattern in report/__init__.py (a failed
probe must report checked=False, never a silent found=0).

Ported from a live-tested prototype (api_work/column_impact.py, run against a
ThoughtSpot staging instance) that found the shipped `ts metadata report`
implemented only ~4 of its 13 impact-analysis passes. See
agents/cli/ts-convert-from-dbt/references/open-items.md #8.
"""
from __future__ import annotations

import json as _json
from typing import Iterable, List, Optional

import yaml

from ts_cli.client import ThoughtSpotClient
from ts_cli.commands.metadata import _build_dependents_payload, _normalize_dependents_response


def fetch_column_security_rules(
    client: ThoughtSpotClient, table_guid: str, physical_column: str,
) -> List[dict]:
    """Column security rules on `table_guid` that cover `physical_column`.

    POST /api/rest/2.0/security/column/rules/fetch (beta, 10.12.0.cl+).
    """
    resp = client.post("/api/rest/2.0/security/column/rules/fetch", json={
        "tables": [{"identifier": table_guid}],
    })
    hits = []
    for tbl_entry in (resp.json() or []):
        for rule in (tbl_entry.get("column_security_rules") or []):
            col = rule.get("column") or {}
            if (col.get("name") or "").lower() == (physical_column or "").lower():
                hits.append({
                    "column": col.get("name"),
                    "column_id": col.get("id"),
                    "groups": [g.get("name") for g in (rule.get("groups") or [])],
                })
    return hits


def _variable_matches(var: dict, targets: List[str]) -> Optional[List[dict]]:
    """Return the matching value entries for `var` against `targets`, or None.

    A variable "matches" if its own name contains a target, or any of its
    value/value_list entries do. Returns [] (not None) for a name-only match
    with no matching value entries — callers check `is not None`, not truthy.
    """
    name = (var.get("name") or "").lower()
    name_hit = any(t in name for t in targets)
    val_hits = [
        v for v in (var.get("values") or [])
        if any(t in (v.get("value") or "").lower() for t in targets)
        or any(t in s.lower() for t in targets for s in (v.get("value_list") or []))
    ]
    if name_hit or val_hits:
        return val_hits
    return None


def fetch_formula_variables(
    client: ThoughtSpotClient, model_guid: str, target_names: Iterable[str],
) -> List[dict]:
    """Formula (template) variables scoped to `model_guid` referencing a target name.

    POST /api/rest/2.0/template/variables/search (26.4.0.cl+). Matches on the
    variable's own name or any value/value_list expression containing a target.
    Auto-paginates — a model can plausibly have more than one page of variables.
    """
    targets = [t.lower() for t in target_names if t]
    hits: List[dict] = []
    offset = 0
    page = 50
    while True:
        resp = client.post("/api/rest/2.0/template/variables/search", json={
            "variable_details": [{"type": "FORMULA_VARIABLE"}],
            "value_scope": [{"model_identifier": model_guid}],
            "response_content": "METADATA_AND_VALUES",
            "record_size": page,
            "record_offset": offset,
        })
        page_resp = resp.json() or []
        for var in page_resp:
            val_hits = _variable_matches(var, targets)
            if val_hits is not None:
                hits.append({"name": var.get("name") or "", "id": var.get("id"), "values": val_hits})
        if len(page_resp) < page:
            break
        offset += page
    return hits


def _match_targets(haystack: str, targets: List[str]) -> List[str]:
    """Return the subset of `targets` (case-insensitive) present in `haystack`."""
    haystack = haystack.lower()
    return [t for t in targets if t.lower() in haystack]


def _fetch_business_terms(client: ThoughtSpotClient, model_guid: str, targets: List[str]) -> List[dict]:
    """Business terms (NLS feedback) — BUSINESS_TERM entries in a model's FEEDBACK TML."""
    feedback_resp = client.post("/api/rest/2.0/metadata/tml/export", json={
        "metadata": [{"identifier": model_guid, "type": "FEEDBACK"}],
        "export_associated": False,
    })
    feedback_json = feedback_resp.json() or []
    edoc_raw = feedback_json[0].get("edoc", "") if feedback_json else ""
    memory_doc = (yaml.safe_load(edoc_raw) or {}) if edoc_raw else {}

    hits = []
    for fb in ((memory_doc.get("nls_feedback") or {}).get("feedback") or []):
        haystack = " ".join([
            fb.get("search_tokens", "") or "",
            fb.get("feedback_phrase", "") or "",
            str(fb.get("axis_config") or ""),
        ])
        matched = _match_targets(haystack, targets)
        if matched:
            hits.append({
                "source": "business_term", "type": fb.get("type"),
                "phrase": fb.get("feedback_phrase"), "matched": matched,
            })
    return hits


def _ai_memory_haystack(mem: dict) -> str:
    """Flatten one AI-memory entry's content to a searchable string."""
    content = mem.get("content") or {}
    content_str = _json.dumps(content)
    if mem.get("type") == "RECIPE":
        try:
            content_str += " " + _json.dumps(_json.loads(content.get("recipe", "{}")))
        except Exception:
            pass
    return content_str


def _fetch_ai_memory(client: ThoughtSpotClient, model_guid: str, targets: List[str]) -> List[dict]:
    """AI memory (rules/recipes) referencing a target name."""
    mem_resp = client.post("/api/rest/2.0/ai/memory/export", json={
        "sources": [{"identifiers": [model_guid], "type": "DATA_MODEL"}],
    })
    mem_json = mem_resp.json() or {}
    mem_content = mem_json.get("content", "") or ""
    mem_doc = (yaml.safe_load(mem_content) or {}) if mem_content else {}

    hits = []
    for mem in (mem_doc.get("memories") or []):
        matched = _match_targets(_ai_memory_haystack(mem), targets)
        if matched:
            content = mem.get("content") or {}
            label = content.get("rule_definition") or content.get("user_query") or str(content)[:120]
            hits.append({
                "source": "ai_memory", "type": mem.get("type"),
                "phrase": label, "matched": matched,
            })
    return hits


def fetch_business_terms_and_ai_memory(
    client: ThoughtSpotClient, model_guid: str, target_names: Iterable[str],
) -> List[dict]:
    """Business terms (NLS feedback) + AI memory entries referencing a target name.

    Two sources, combined: FEEDBACK-type TML export (`nls_feedback.feedback[]`,
    BUSINESS_TERM entries) and POST /api/rest/2.0/ai/memory/export (rules/recipes).
    """
    targets = [t for t in target_names if t]
    return _fetch_business_terms(client, model_guid, targets) + _fetch_ai_memory(client, model_guid, targets)


def fetch_sql_view_hits(client: ThoughtSpotClient, physical_column: str) -> List[dict]:
    """Org-wide SQL views whose raw SQL text references `physical_column`.

    Most expensive probe here — the dependents API does not track column
    references inside a SQL view's raw query text, so this enumerates every
    SQL_VIEW LOGICAL_TABLE object in the org and text-scans its TML. O(number
    of SQL views in the org), not O(dependents of the source).
    """
    sv_guids: List[str] = []
    offset = 0
    page = 50
    while True:
        resp = client.post("/api/rest/2.0/metadata/search", json={
            "metadata": [{"type": "LOGICAL_TABLE"}],
            "include_headers": True,
            "record_size": page,
            "record_offset": offset,
        })
        page_resp = resp.json() or []
        for r in page_resp:
            h = r.get("metadata_header") or {}
            if (h.get("subType") or h.get("type", "")) == "SQL_VIEW":
                sv_guids.append(r["metadata_id"])
        if len(page_resp) < page:
            break
        offset += page

    if not sv_guids:
        return []

    hits: List[dict] = []
    batch = 10
    for i in range(0, len(sv_guids), batch):
        chunk = sv_guids[i:i + batch]
        tml_resp = client.post("/api/rest/2.0/metadata/tml/export", json={
            "metadata": [{"identifier": g} for g in chunk],
            "export_associated": False,
        })
        for item in (tml_resp.json() or []):
            edoc_raw = item.get("edoc", "{}")
            doc = _json.loads(edoc_raw) if isinstance(edoc_raw, str) else edoc_raw
            from .tml_probes import find_sql_view_column_uses
            hit = find_sql_view_column_uses(doc, physical_column)
            if hit:
                hits.append(hit)
    return hits


def fetch_custom_actions_for_guids(client: ThoughtSpotClient, affected_guids: Iterable[str]) -> List[dict]:
    """Custom actions that are global, or explicitly scoped to any GUID in affected_guids."""
    guid_set = set(affected_guids)
    resp = client.post("/api/rest/2.0/customization/custom-actions/search", json={
        "include_metadata_associations": True,
        "include_group_associations": False,
    })
    hits = []
    for action in (resp.json() or []):
        is_global = (action.get("default_action_config") or {}).get("visibility", False)
        assoc_guids = {a["identifier"] for a in (action.get("metadata_association") or [])}
        matched = assoc_guids & guid_set
        if is_global or matched:
            hits.append({
                "id": action.get("id"), "name": action.get("name"),
                "is_global": is_global, "matched_guids": sorted(matched),
            })
    return hits


def fetch_scheduled_reports(client: ThoughtSpotClient, liveboard_guids: Iterable[str]) -> List[dict]:
    """Scheduled reports (9.4.0.cl+) scoped to any of `liveboard_guids`.

    Informational only — the schedule keeps running; delivered output will be
    missing data once the column is actually removed.
    """
    guids = list(liveboard_guids)
    if not guids:
        return []
    resp = client.post("/api/rest/2.0/schedules/search", json={
        "metadata": [{"identifier": g, "type": "LIVEBOARD"} for g in guids],
        "record_size": -1,
        "record_offset": 0,
    })
    hits = []
    for s in (resp.json() or []):
        lb = s.get("metadata") or {}
        hits.append({
            "id": s.get("id"), "name": s.get("name"),
            "liveboard": lb.get("name") or lb.get("id"),
            "status": s.get("status"),
        })
    return hits


def find_column_guid_by_name(
    client: ThoughtSpotClient, name: str, owner_guid: str,
) -> Optional[str]:
    """Find a LOGICAL_COLUMN GUID by exact name, owned by `owner_guid`."""
    resp = client.post("/api/rest/2.0/metadata/search", json={
        "metadata": [{"identifier": name, "type": "LOGICAL_COLUMN"}],
        "include_headers": True,
        "record_size": 50,
        "record_offset": 0,
    })
    for r in (resp.json() or []):
        if (r.get("metadata_header") or {}).get("owner") == owner_guid:
            return r.get("metadata_id")
    return None


def walk_one_hop(
    client: ThoughtSpotClient, guid: str, qtype: str, hops: int,
) -> List[dict]:
    """Single (non-recursive) dependents hop for one GUID, tagged with `hops`.

    Used for cascading walks (formula columns, SQL views) that aren't part of
    the main recursive walk in walker.py — those objects are discovered mid-report,
    after the primary walk already ran.
    """
    resp = client.post(
        "/api/rest/2.0/metadata/search",
        json=_build_dependents_payload([guid], qtype),
    )
    rows = _normalize_dependents_response(resp.json())
    for row in rows:
        row["hops"] = hops
    return rows
