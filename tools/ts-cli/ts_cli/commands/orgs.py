"""ts orgs — search ThoughtSpot orgs."""
from __future__ import annotations

import json
from typing import Optional

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
    limit: int = typer.Option(200, "--limit", "-l", help="Max results"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Search ThoughtSpot orgs.

    Output: JSON array from POST /api/rest/2.0/orgs/search.
    Each element has orgId, orgName, description, and status.

    Examples:

    \\b
      ts orgs search
      ts orgs search --status ACTIVE
      ts orgs search --name "%sales%"
      ts orgs search --status ACTIVE --profile production
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    payload: dict = {
        "record_offset": 0,
        "record_size": limit,
    }
    if status:
        payload["status"] = status
    if name:
        payload["name_pattern"] = name
    resp = client.post("/api/rest/2.0/orgs/search", json=payload)
    print(json.dumps(resp.json()))
