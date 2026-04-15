"""ts metadata — search and retrieve ThoughtSpot metadata objects."""
from __future__ import annotations

import json
from typing import List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Metadata search and retrieval commands.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")

# Valid types accepted by POST /api/rest/2.0/metadata/search.
# LOGICAL_TABLE covers tables, worksheets, AND models — subtypes distinguish them.
# Use --subtype to restrict within LOGICAL_TABLE.
_OBJECT_TYPES = [
    "LOGICAL_TABLE",  # tables, worksheets, and models (use --subtype to narrow)
    "LIVEBOARD",      # liveboards (formerly pinboards)
    "ANSWER",         # saved answers
]

# Known subtypes for LOGICAL_TABLE
_SUBTYPES = [
    "WORKSHEET",          # worksheets and models
    "MODEL",              # models (if supported by instance version)
    "ONE_TO_ONE_LOGICAL", # direct connection tables
    "USER_DEFINED",       # uploaded CSV tables
    "AGGR_WORKSHEET",     # views
]


@app.command("search")
def search(
    profile: Optional[str] = _profile_option,
    type: str = typer.Option("LOGICAL_TABLE", "--type", "-t",
                             help="Object type: LOGICAL_TABLE (tables/worksheets/models), LIVEBOARD, ANSWER"),
    subtype: Optional[List[str]] = typer.Option(None, "--subtype", "-s",
                                                help="Subtype filter within LOGICAL_TABLE (repeatable). "
                                                     "E.g. --subtype WORKSHEET to find worksheets and models."),
    name: Optional[str] = typer.Option(None, "--name", "-n",
                                       help="Filter by name using SQL LIKE syntax: "
                                            "%% = any chars, _ = one char. E.g. '%%BIRD%%' or 'Sales_%%'"),
    guid: Optional[str] = typer.Option(None, "--guid", "-g",
                                       help="Filter by GUID (exact match)"),
    tag: Optional[List[str]] = typer.Option(None, "--tag",
                                            help="Filter by tag name or GUID (repeatable)"),
    include_hidden: bool = typer.Option(False, "--include-hidden",
                                        help="Include hidden objects"),
    include_incomplete: bool = typer.Option(False, "--include-incomplete",
                                            help="Include incomplete objects"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results per page"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages automatically"),
) -> None:
    """Search ThoughtSpot metadata objects.

    Output: JSON array from POST /api/rest/2.0/metadata/search.

    LOGICAL_TABLE covers tables, worksheets, and models. Use --subtype WORKSHEET
    to restrict to worksheets and models only.

    Examples:

    \b
      ts metadata search
      ts metadata search --subtype WORKSHEET --name "%BIRD%"
      ts metadata search --subtype WORKSHEET --name "%sales%"
      ts metadata search --guid abc-123-def
      ts metadata search --type LIVEBOARD --all
    """
    client = ThoughtSpotClient(resolve_profile(profile))

    def _build_payload(offset_val: int) -> dict:
        meta_filter: dict = {"type": type}
        if subtype:
            meta_filter["subtypes"] = list(subtype)
        if name:
            meta_filter["name_pattern"] = name
        if guid:
            meta_filter["identifier"] = guid

        payload: dict = {
            "metadata": [meta_filter],
            "record_size": limit,
            "record_offset": offset_val,
            "include_headers": True,
            "include_hidden_objects": include_hidden,
            "include_incomplete_objects": include_incomplete,
        }
        if tag:
            payload["tag_identifiers"] = list(tag)
        return payload

    if not all_pages:
        resp = client.post("/api/rest/2.0/metadata/search", json=_build_payload(offset))
        print(json.dumps(resp.json()))
        return

    # Auto-paginate: collect all results
    all_results: List[dict] = []
    current_offset = offset
    while True:
        resp = client.post("/api/rest/2.0/metadata/search", json=_build_payload(current_offset))
        data = resp.json()
        page = data if isinstance(data, list) else data.get("metadata", [])
        if not page:
            break
        all_results.extend(page)
        if len(page) < limit:
            break
        current_offset += limit

    print(json.dumps(all_results))


@app.command("delete")
def delete_objects(
    guids: List[str] = typer.Argument(..., help="One or more GUIDs to delete"),
    type: str = typer.Option("LOGICAL_TABLE", "--type", "-t",
                             help="Object type: LOGICAL_TABLE, LIVEBOARD, ANSWER"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Delete one or more ThoughtSpot objects by GUID.

    Output: HTTP 204 on success (no body). Raises on error.

    Examples:

    \b
      ts metadata delete abc-123
      ts metadata delete abc-123 def-456 --type LIVEBOARD
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    client.post(
        "/api/rest/2.0/metadata/delete",
        json={"metadata": [{"identifier": g, "type": type} for g in guids]},
    )
    print(json.dumps({"deleted": guids}))


@app.command("get")
def get_object(
    guid: str = typer.Argument(..., help="Object GUID"),
    profile: Optional[str] = _profile_option,
    type: str = typer.Option("LOGICAL_TABLE", "--type", "-t",
                             help="Object type"),
) -> None:
    """Get details of a single metadata object by GUID.

    Output: first matching result from POST /api/rest/2.0/metadata/search.
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post(
        "/api/rest/2.0/metadata/search",
        json={
            "metadata": [{"type": type, "identifier": guid}],
            "record_size": 1,
            "record_offset": 0,
            "include_headers": True,
        },
    )
    data = resp.json()
    results = data if isinstance(data, list) else data.get("metadata", [])
    if not results:
        raise SystemExit(f"No {type} object found with GUID '{guid}'.")
    print(json.dumps(results[0]))
