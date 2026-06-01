"""ts_cli.report.walker — per-source-type dependency walk.

Wraps the existing `ts metadata dependents` logic
(`_build_dependents_payload` + `_normalize_dependents_response`)
with multi-hop logic for Table → Model → Answers/Liveboards.
"""
from __future__ import annotations

from typing import List

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
