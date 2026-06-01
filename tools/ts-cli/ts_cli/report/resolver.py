"""ts_cli.report.resolver — parse user-provided source input and resolve to GUID."""
from __future__ import annotations

import enum
import re
from typing import Optional

from ts_cli.client import ThoughtSpotClient

# 36-char UUID with hyphens at canonical positions.
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class InputKind(enum.Enum):
    GUID = "guid"
    ONE_PART_NAME = "one_part"
    TWO_PART_NAME = "two_part"
    THREE_PART_NAME = "three_part"
    FOUR_PART_NAME = "four_part"


def looks_like_guid(s: str) -> bool:
    """True iff s is a canonical 36-char UUID."""
    return bool(_GUID_RE.match(s or ""))


def classify_input(s: str) -> InputKind:
    """Return the InputKind for a user-provided source argument."""
    if looks_like_guid(s):
        return InputKind.GUID
    parts = s.split(".")
    n = len(parts)
    if n == 1:
        return InputKind.ONE_PART_NAME
    if n == 2:
        return InputKind.TWO_PART_NAME
    if n == 3:
        return InputKind.THREE_PART_NAME
    if n == 4:
        return InputKind.FOUR_PART_NAME
    raise ValueError(f"Cannot classify input: {s!r}")


from .schema import SourceDescriptor


class SourceUnresolvedError(Exception):
    """No metadata object matched the input."""
    def __init__(self, input_: str):
        super().__init__(f"No metadata object matched: {input_!r}")
        self.input = input_


class SourceAmbiguousError(Exception):
    """More than one metadata object matched the input."""
    def __init__(self, input_: str, candidates: list):
        super().__init__(f"Input {input_!r} matched {len(candidates)} objects; specify GUID")
        self.input = input_
        self.candidates = candidates


def _search(client: ThoughtSpotClient, body: dict) -> list:
    """Call metadata/search and return the list of results."""
    resp = client.post("/api/rest/2.0/metadata/search", json=body)
    data = resp.json()
    return data if isinstance(data, list) else data.get("metadata", [])


def _to_descriptor(input_str: str, hit: dict, parent: Optional[dict] = None) -> SourceDescriptor:
    return SourceDescriptor(
        input=input_str,
        guid=hit.get("metadata_id") or hit.get("metadata_header", {}).get("id"),
        type=hit.get("metadata_type") or "LOGICAL_TABLE",
        name=hit.get("metadata_name") or hit.get("metadata_header", {}).get("name", ""),
        parent=parent,
    )


def resolve_source(input_str: str, client: ThoughtSpotClient) -> SourceDescriptor:
    """Resolve a user-provided source string to a SourceDescriptor.

    Raises SourceUnresolvedError / SourceAmbiguousError on failure cases.
    """
    kind = classify_input(input_str)
    if kind in (InputKind.GUID, InputKind.ONE_PART_NAME):
        # For GUIDs and bare single-part identifiers, look up by identifier.
        hits = _search(client, {
            "metadata": [{"identifier": input_str}],
            "record_size": 1,
            "include_headers": True,
        })
        if not hits:
            raise SourceUnresolvedError(input_str)
        return _to_descriptor(input_str, hits[0])

    # Name lookup: use exact name match (no SQL-LIKE wildcards).
    hits = _search(client, {
        "metadata": [{"type": "LOGICAL_TABLE", "name_pattern": input_str}],
        "record_size": 10,
        "include_headers": True,
    })
    # Filter to exact-name matches only.
    hits = [h for h in hits if (h.get("metadata_name") or "") == input_str]
    if not hits:
        raise SourceUnresolvedError(input_str)
    if len(hits) > 1:
        raise SourceAmbiguousError(input_str, hits)
    return _to_descriptor(input_str, hits[0])
