"""ts users — search ThoughtSpot users and groups."""
from __future__ import annotations

import json
from typing import List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="User and group management commands.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")


@app.command("search")
def search_users(
    name: Optional[str] = typer.Option(None, "--name", "-n",
                                        help="Search by name or email using SQL LIKE syntax"),
    org: List[str] = typer.Option([], "--org",
                                   help="Filter to org name(s) (repeatable)"),
    account_status: Optional[str] = typer.Option(None, "--account-status",
                                                   help="Filter by account status (e.g. ACTIVE)"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Search ThoughtSpot users.

    Output: JSON array from POST /api/rest/2.0/users/search.
    Each element has id, name, displayName, mail, and accountStatus.

    Examples:

    \\b
      ts users search
      ts users search --name "%alice%"
      ts users search --name "%alice%" --org Primary --account-status ACTIVE
      ts users search --org Primary --org Sales --limit 50
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    payload: dict = {
        "record_offset": 0,
        "record_size": limit,
    }
    if name:
        payload["name_pattern"] = name
    if org:
        payload["org_identifiers"] = list(org)
    if account_status:
        payload["account_status"] = account_status
    resp = client.post("/api/rest/2.0/users/search", json=payload)
    print(json.dumps(resp.json()))


@app.command("groups")
def search_groups(
    name: Optional[str] = typer.Option(None, "--name", "-n",
                                        help="Search by group name using SQL LIKE syntax"),
    org: List[str] = typer.Option([], "--org",
                                   help="Filter to org name(s) (repeatable)"),
    include_users: bool = typer.Option(False, "--include-users",
                                        help="Include users array in each group result"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Search ThoughtSpot groups.

    Output: JSON array from POST /api/rest/2.0/groups/search.
    Each element has id, name, displayName, and optionally a users[] array.

    Examples:

    \\b
      ts users groups
      ts users groups --name "%admins%"
      ts users groups --name "%sales%" --org Primary --include-users
      ts users groups --org Primary --include-users --limit 10
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    payload: dict = {
        "record_offset": 0,
        "record_size": limit,
        "include_users": include_users,
    }
    if name:
        payload["name_pattern"] = name
    if org:
        payload["org_identifiers"] = list(org)
    resp = client.post("/api/rest/2.0/groups/search", json=payload)
    print(json.dumps(resp.json()))
