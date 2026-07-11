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


def filter_by_connection(results: List[dict], connection: Optional[str]) -> List[dict]:
    """Keep only results whose ``metadata_header.dataSourceName`` matches ``connection``.

    Client-side connection scoping — the metadata/search API has no server-side
    connection filter, so callers that want "objects on connection X" fetch and
    then filter on the ``dataSourceName`` field (the verified field — see
    .claude/rules/ts-cli.md and the same pattern in tables.py / ts-audit). Match is
    case-insensitive on the display name; objects with no ``dataSourceName``
    (e.g. worksheets/models, which aren't connection-scoped) never match.

    Pure function — no I/O — so it can be unit-tested without a live instance.
    Returns the list unchanged when ``connection`` is None.
    """
    if not connection:
        return results
    wanted = connection.strip().casefold()
    out: List[dict] = []
    for r in results:
        header = r.get("metadata_header") or r
        ds = header.get("dataSourceName")
        if isinstance(ds, str) and ds.casefold() == wanted:
            out.append(r)
    return out


@app.command("search")
def search(
    profile: Optional[str] = _profile_option,
    type: str = typer.Option("LOGICAL_TABLE", "--type", "-t",
                             help="Object type: LOGICAL_TABLE (tables/worksheets/models), LIVEBOARD, ANSWER"),
    subtype: Optional[List[str]] = typer.Option(None, "--subtype", "-s",
                                                help="Subtype filter within LOGICAL_TABLE (repeatable). "
                                                     "E.g. --subtype WORKSHEET to find worksheets and models."),
    connection: Optional[str] = typer.Option(None, "--connection", "-c",
                                             help="Filter results to a single connection by display name "
                                                  "(client-side match on metadata_header.dataSourceName, "
                                                  "case-insensitive). Objects not scoped to a connection "
                                                  "(worksheets/models) are excluded when this is set."),
    name: Optional[str] = typer.Option(None, "--name", "-n",
                                       help="Filter by name using SQL LIKE syntax: "
                                            "% = any chars, _ = one char. E.g. '%BIRD%' or 'Sales_%'"),
    guid: Optional[str] = typer.Option(None, "--guid", "-g",
                                       help="Filter by GUID (exact match)"),
    tag: Optional[List[str]] = typer.Option(None, "--tag",
                                            help="Filter by tag name or GUID (repeatable)"),
    include_hidden: bool = typer.Option(False, "--include-hidden",
                                        help="Include hidden objects"),
    include_incomplete: bool = typer.Option(False, "--include-incomplete",
                                            help="Include incomplete objects"),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-l",
        help="Max results for a SINGLE page starting at --offset (legacy behavior). "
             "Omit to auto-paginate internally and return the full result set — "
             "this is now the default (2026-07 audit finding 14.2)."),
    offset: int = typer.Option(0, "--offset", help="Pagination offset (only meaningful together with --limit)"),
    all_pages: bool = typer.Option(
        False, "--all",
        help="Deprecated, now a no-op — auto-pagination to the full result set is "
             "the default whenever --limit is omitted. Kept only so existing callers "
             "don't break."),
) -> None:
    """Search ThoughtSpot metadata objects (auto-paginated by default).

    Output: JSON array from POST /api/rest/2.0/metadata/search — the full result
    set across all pages unless --limit is given, in which case only that one
    page (starting at --offset) is returned.

    LOGICAL_TABLE covers tables, worksheets, and models. Use --subtype WORKSHEET
    to restrict to worksheets and models only.

    Examples:

    \b
      ts metadata search
      ts metadata search --subtype WORKSHEET --name "%BIRD%"
      ts metadata search --subtype WORKSHEET --name "%sales%"
      ts metadata search --guid abc-123-def
      ts metadata search --connection "Snowflake Prod"          # only tables on that connection
      ts metadata search --connection "Snowflake Prod" --name "%DIM%"
      ts metadata search --type LIVEBOARD --limit 10   # single page only (legacy)
    """
    client = ThoughtSpotClient(resolve_profile(profile))

    def _build_payload(offset_val: int, size: int) -> dict:
        meta_filter: dict = {"type": type}
        if subtype:
            meta_filter["subtypes"] = list(subtype)
        if name:
            meta_filter["name_pattern"] = name
        if guid:
            meta_filter["identifier"] = guid

        payload: dict = {
            "metadata": [meta_filter],
            "record_size": size,
            "record_offset": offset_val,
            "include_headers": True,
            "include_hidden_objects": include_hidden,
            "include_incomplete_objects": include_incomplete,
        }
        if tag:
            payload["tag_identifiers"] = list(tag)
        return payload

    if limit is not None:
        # Explicit --limit: preserve legacy single-page behavior. --all is a
        # no-op here — an explicit limit always wins.
        resp = client.post("/api/rest/2.0/metadata/search", json=_build_payload(offset, limit))
        data = resp.json()
        if connection:
            # Filtering requires a flat list; normalize the wrapper shape first.
            page = data if isinstance(data, list) else data.get("metadata", [])
            print(json.dumps(filter_by_connection(page, connection)))
        else:
            # No filter → print resp.json() verbatim (legacy contract: whatever
            # shape the API returns, dict wrapper included).
            print(json.dumps(data))
        return

    # Default: auto-paginate and collect the full result set. --all_pages is
    # accepted but unused — this branch now runs whenever --limit is omitted,
    # whether or not the caller also passed --all.
    page_size = 50
    all_results: List[dict] = []
    current_offset = offset
    while True:
        resp = client.post("/api/rest/2.0/metadata/search", json=_build_payload(current_offset, page_size))
        data = resp.json()
        page = data if isinstance(data, list) else data.get("metadata", [])
        if not page:
            break
        all_results.extend(page)
        if len(page) < page_size:
            break
        current_offset += page_size

    print(json.dumps(filter_by_connection(all_results, connection)))


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


# ---------------------------------------------------------------------------
# `ts metadata dependents` — list all objects that reference the given GUID(s)
# ---------------------------------------------------------------------------

# Per-bucket mapping from the v2 dependents response key to the canonical
# normalized type label emitted in the flat output.
_BUCKET_TO_TYPE = {
    "QUESTION_ANSWER_BOOK": "ANSWER",
    "PINBOARD_ANSWER_BOOK": "LIVEBOARD",
    "LOGICAL_TABLE":        "LOGICAL_TABLE",  # Models / Views / Tables — caller can subtype
    "COHORT":               "SET",
    "FEEDBACK":             "FEEDBACK",
}


def _build_dependents_payload(guids: List[str], type_str: str) -> dict:
    """Build the request body for the v2 dependents query.

    Splits out so it can be unit-tested without hitting the network.
    See references/open-items.md #1 for the verified shape.
    """
    return {
        "metadata":                  [{"identifier": g, "type": type_str} for g in guids],
        "include_dependent_objects": True,
        "dependent_object_version":  "V2",
        "record_size":               -1,
        "record_offset":             0,
    }


def _normalize_dependents_response(resp_json) -> list:
    """Flatten the v2 dependents response into one row per dependent.

    Input shape (per source GUID, per bucket):
      [
        {"metadata_id": "<guid>", ...,
         "dependent_objects": {
           "dependents": {"<guid>": {"QUESTION_ANSWER_BOOK": [{"id":..., "name":...}, ...],
                                     "PINBOARD_ANSWER_BOOK": [...], "LOGICAL_TABLE": [...],
                                     "COHORT": [...], "FEEDBACK": [...]}}}
        }
      ]

    Output:
      [{"source_guid": "<guid>", "guid": "<dep_guid>", "name": "...",
        "type": "ANSWER|LIVEBOARD|LOGICAL_TABLE|SET|FEEDBACK",
        "raw_bucket": "QUESTION_ANSWER_BOOK|...",
        "author_id": "...", "author_display_name": "..."},
       ...]

    Empty buckets are omitted (the API does not return empty keys, but we still skip
    defensively in case the shape changes).
    """
    if not isinstance(resp_json, list):
        return []
    rows = []
    for item in resp_json:
        source_guid = item.get("metadata_id") or item.get("identifier") or ""
        deps = ((item.get("dependent_objects") or {}).get("dependents") or {}).get(source_guid) or {}
        for bucket, entries in deps.items():
            mapped_type = _BUCKET_TO_TYPE.get(bucket, bucket)
            for entry in entries or []:
                rows.append({
                    "source_guid":          source_guid,
                    "guid":                 entry.get("id"),
                    "name":                 entry.get("name"),
                    "type":                 mapped_type,
                    "raw_bucket":           bucket,
                    "author_id":            entry.get("author"),
                    "author_display_name":  entry.get("authorDisplayName"),
                })
    return rows


@app.command("dependents")
def dependents(
    guids: List[str] = typer.Argument(..., help="One or more source GUIDs to query"),
    type: str = typer.Option("LOGICAL_TABLE", "--type", "-t",
                             help="Source type: LOGICAL_TABLE (table/model/view) or "
                                  "LOGICAL_COLUMN (column or set/cohort GUID)"),
    raw: bool = typer.Option(False, "--raw",
                             help="Emit the unmodified v2 response array instead of the "
                                  "flat normalized list"),
    profile: Optional[str] = _profile_option,
) -> None:
    """List all objects that depend on the given source GUID(s).

    Wraps POST /api/rest/2.0/metadata/search with include_dependent_objects=true,
    dependent_object_version=V2. Returns Models/Views/Answers/Liveboards/Sets/Feedback
    that reference the source.

    Default output (one row per dependent, flat):

        [{"source_guid": "...", "guid": "...", "name": "...", "type": "ANSWER",
          "raw_bucket": "QUESTION_ANSWER_BOOK", "author_id": "...",
          "author_display_name": "..."}, ...]

    With --raw, returns the v2 response untouched (useful for getting at
    `hasInaccessibleDependents` or other meta-fields).

    For Sets / Cohorts, query with `--type LOGICAL_COLUMN`. RLS rules, alerts, column
    aliases, and column security TML are NOT covered by v2 dependents — see
    `agents/cli/ts-dependency-manager/references/open-items.md` for those.

    Examples:

    \b
      ts metadata dependents 32c062cb-9586-43ff-bc66-bceed7529caf
      ts metadata dependents 32c062cb-9586-43ff-bc66-bceed7529caf --type LOGICAL_COLUMN
      ts metadata dependents abc def ghi --raw
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post(
        "/api/rest/2.0/metadata/search",
        json=_build_dependents_payload(guids, type),
    )
    data = resp.json()
    if raw:
        print(json.dumps(data))
        return
    print(json.dumps(_normalize_dependents_response(data)))


# ---------------------------------------------------------------------------
# `ts metadata report` — full audit (dep walk + TML probes + classification + format)
# ---------------------------------------------------------------------------

@app.command("report")
def report(
    sources: List[str] = typer.Argument(..., help="One or more sources (GUID or N-part name)"),
    profile: Optional[str] = _profile_option,
    format: str = typer.Option("json", "--format", "-f",
                               help="Output format: json (default) | text | md"),
    fast: bool = typer.Option(False, "--fast",
                              help="Skip TML probes (v2 dependents API only)"),
    out: Optional[str] = typer.Option(None, "--out",
                                      help="Write to file instead of stdout"),
    depth: int = typer.Option(3, "--depth", help="Max dep-walk hops (default: 3)"),
) -> None:
    """Audit dependents of one or more sources.

    Examples:

    \b
      ts metadata report DB.SCH.TBL --profile P --format text
      ts metadata report DB.SCH.TBL.COL --profile P --format md --out report.md
      ts metadata report <guid> --profile P --format json --fast
    """
    from ts_cli.report import build_report, build_reports
    from ts_cli.report.formatters import render_text, render_md
    from ts_cli.report.resolver import SourceUnresolvedError, SourceAmbiguousError

    profile_name = resolve_profile(profile)

    try:
        if len(sources) == 1:
            payload = build_report(sources[0], profile=profile_name, with_deep=not fast, max_depth=depth)
        else:
            payload = build_reports(sources, profile=profile_name, with_deep=not fast, max_depth=depth)
    except SourceUnresolvedError as e:
        typer.echo(json.dumps({"error": "unresolved", "input": e.input}), err=True)
        raise typer.Exit(code=2)
    except SourceAmbiguousError as e:
        typer.echo(json.dumps({"error": "ambiguous", "input": e.input,
                               "candidates": [{"guid": c.get("metadata_id"), "name": c.get("metadata_name")}
                                              for c in e.candidates]}), err=True)
        raise typer.Exit(code=2)

    if format == "json":
        text = json.dumps(payload, indent=2)
    elif format == "text":
        if "reports" in payload:
            blocks = []
            for r in payload["reports"]:
                if "error" in r:
                    blocks.append(f"[{r['source'].get('input')}] ERROR: {r['error']}")
                else:
                    blocks.append(render_text(_dict_to_report(r)))
            text = "\n\n---\n\n".join(blocks)
        else:
            text = render_text(_dict_to_report(payload))
    elif format == "md":
        if "reports" in payload:
            blocks = [render_md(_dict_to_report(r)) for r in payload["reports"] if "error" not in r]
            text = "\n\n---\n\n".join(blocks)
        else:
            text = render_md(_dict_to_report(payload))
    else:
        typer.echo(f"unknown format: {format}", err=True)
        raise typer.Exit(code=1)

    if out:
        from pathlib import Path
        Path(out).write_text(text + "\n")
    else:
        print(text)


def _dict_to_report(d: dict):
    """Reconstruct a Report from its dict form (formatters expect dataclass instances)."""
    from ts_cli.report.schema import (
        Report, SourceDescriptor, DependentEntry, Owner, RiskTag,
        CoverageEntry, Classification,
    )
    src_d = d["source"]
    src = SourceDescriptor(
        input=src_d["input"], guid=src_d["guid"], type=src_d["type"],
        name=src_d["name"], parent=src_d.get("parent"),
    )
    deps = []
    for de in d.get("dependents", []):
        owner = None
        if de.get("owner"):
            owner = Owner(id=de["owner"]["id"], display_name=de["owner"]["display_name"])
        deps.append(DependentEntry(
            guid=de["guid"], name=de["name"], type=de["type"],
            subtype=de.get("subtype"), via=de.get("via", "v2_dependents"),
            hops=de.get("hops", 1), owner=owner, modified_at=de.get("modified_at"),
            risk=RiskTag(tag=de["risk"]["tag"], reason=de["risk"]["reason"]),
            matched_columns=de.get("matched_columns", []),
        ))
    coverage = [CoverageEntry(**c) for c in d.get("coverage", [])]
    cls = d["classification"]
    classification = Classification(
        per_dependent=deps,
        aggregate=RiskTag(tag=cls["aggregate"]["tag"], reason=cls["aggregate"]["reason"]),
        recommendation=cls.get("recommendation", ""),
    )
    return Report(
        source=src, walked_at=d["walked_at"], profile=d["profile"],
        dependents=deps, coverage=coverage,
        classification=classification, warnings=d.get("warnings", []),
    )
