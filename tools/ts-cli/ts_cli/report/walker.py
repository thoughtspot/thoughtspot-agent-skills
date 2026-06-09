"""ts_cli.report.walker — per-source-type dependency walk.

Wraps the existing `ts metadata dependents` logic
(`_build_dependents_payload` + `_normalize_dependents_response`)
with multi-hop logic for Table → Model → Answers/Liveboards.
"""
from __future__ import annotations

from typing import List, Optional

from ts_cli.client import ThoughtSpotClient
from ts_cli.commands.metadata import (
    _build_dependents_payload,
    _normalize_dependents_response,
)
from .schema import DependentEntry, Owner, RiskTag, SourceDescriptor


def dependents_query_type_for(source: SourceDescriptor) -> str:
    """Map a SourceDescriptor.type to the type argument expected by
    POST /api/rest/2.0/metadata/search dependents query.

    Tables / Models / Views / Answers / Liveboards → LOGICAL_TABLE/LIVEBOARD/ANSWER
    Columns / Sets (cohorts)                       → LOGICAL_COLUMN
    """
    t = source.type
    if t == "LOGICAL_COLUMN":
        return "LOGICAL_COLUMN"
    if t == "LIVEBOARD":
        return "LIVEBOARD"
    if t == "ANSWER":
        return "ANSWER"
    # LOGICAL_TABLE covers tables, models, and views.
    return "LOGICAL_TABLE"


def walk_dependents(source: SourceDescriptor, client: ThoughtSpotClient) -> List[dict]:
    """Direct (one-hop) dependents for `source`. Returns the flat normalized list."""
    resp = client.post(
        "/api/rest/2.0/metadata/search",
        json=_build_dependents_payload([source.guid], dependents_query_type_for(source)),
    )
    return _normalize_dependents_response(resp.json())


def walk_dependents_recursive(
    source: SourceDescriptor,
    client: ThoughtSpotClient,
    *,
    max_depth: int = 3,
) -> List[dict]:
    """Walk dependents up to `max_depth` hops, deduped by GUID.

    Each output row carries a `hops` field indicating distance from source.
    """
    seen: dict = {}            # guid -> row
    frontier = [(source.guid, dependents_query_type_for(source), 0)]
    while frontier:
        guid, qtype, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        resp = client.post(
            "/api/rest/2.0/metadata/search",
            json=_build_dependents_payload([guid], qtype),
        )
        rows = _normalize_dependents_response(resp.json())
        for row in rows:
            if row["guid"] in seen:
                continue
            row["hops"] = depth + 1
            seen[row["guid"]] = row
            # Decide next-hop query type for this dependent.
            next_type = _next_hop_type(row)
            if next_type is not None:
                frontier.append((row["guid"], next_type, depth + 1))
    return list(seen.values())


def _next_hop_type(row: dict) -> Optional[str]:
    """Return the dependents-query type to use when walking through `row`.

    - Models, Views, Answers, Liveboards -> LOGICAL_TABLE / ANSWER / LIVEBOARD
    - Sets (COHORT bucket)               -> LOGICAL_COLUMN (queries the set as a column)
    - Feedback                           -> None (no further walk; feedback is a leaf)
    """
    t = row.get("type")
    bucket = row.get("raw_bucket")
    if bucket == "FEEDBACK":
        return None
    if bucket == "COHORT":
        return "LOGICAL_COLUMN"
    if t == "ANSWER":
        return "ANSWER"
    if t == "LIVEBOARD":
        return "LIVEBOARD"
    return "LOGICAL_TABLE"


def row_to_entry(row: dict) -> DependentEntry:
    """Convert a normalized dependents row into a DependentEntry.

    Owner is set from author_* fields when present.
    Modified-at is left as None here; tml_probes can fill it later.
    Risk is set to a placeholder LOW tag; the classifier replaces it.
    """
    author_id = row.get("author_id")
    author_name = row.get("author_display_name")
    owner = Owner(id=author_id, display_name=author_name) if author_id else None
    return DependentEntry(
        guid=row["guid"],
        name=row["name"],
        type=row["type"],
        subtype=None,
        via="v2_dependents",
        hops=row.get("hops", 1),
        owner=owner,
        modified_at=None,
        risk=RiskTag(tag="LOW", reason="placeholder — classifier overrides"),
    )
