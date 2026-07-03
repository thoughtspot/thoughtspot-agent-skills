"""ts orgs — search ThoughtSpot orgs."""
from __future__ import annotations

import json
from typing import List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Org management commands.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")


@app.command("search")
def search(
    status: Optional[str] = typer.Option(None, "--status",
                                          help="Filter by org status (e.g. ACTIVE, INACTIVE)"),
    name: Optional[str] = typer.Option(None, "--name", "-n",
                                        help="Filter by org name using SQL LIKE syntax"),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-l",
        help="Max results for a single page (legacy behavior). Omit to "
             "auto-paginate internally and return the full result set — this "
             "is now the default (2026-07 audit finding 14.2)."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Search ThoughtSpot orgs (auto-paginated by default).

    Output: JSON array from POST /api/rest/2.0/orgs/search — the full result
    set unless --limit is given, in which case only that one page is returned.
    Each element has orgId, orgName, description, and status.

    Examples:

    \\b
      ts orgs search
      ts orgs search --status ACTIVE
      ts orgs search --name "%sales%"
      ts orgs search --status ACTIVE --profile production
    """
    client = ThoughtSpotClient(resolve_profile(profile))

    def _build_payload(offset_val: int, size: int) -> dict:
        payload: dict = {
            "record_offset": offset_val,
            "record_size": size,
        }
        if status:
            payload["status"] = status
        if name:
            payload["name_pattern"] = name
        return payload

    if limit is not None:
        resp = client.post("/api/rest/2.0/orgs/search", json=_build_payload(0, limit))
        print(json.dumps(resp.json()))
        return

    page_size = 50
    all_results: List[dict] = []
    offset = 0
    while True:
        resp = client.post("/api/rest/2.0/orgs/search", json=_build_payload(offset, page_size))
        page = resp.json()
        if not isinstance(page, list) or not page:
            break
        all_results.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    print(json.dumps(all_results))
