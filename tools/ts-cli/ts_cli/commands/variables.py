"""ts variables — manage ThoughtSpot template variable values."""
from __future__ import annotations

import json
from typing import List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Template variable management commands.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")


@app.command("search")
def search(
    identifier: Optional[str] = typer.Argument(None,
                                                help="Variable name or ID (omit for all variables)"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Search template variables and their current assignments.

    Output: JSON array from POST /api/rest/2.0/template/variables/search.
    Each element has id, name, variable_type, and a values[] array of assignments.
    Each assignment has: value, org_identifier, principal_type, principal_identifier.

    Examples:

    \\b
      ts variables search
      ts variables search ts_user_timezone
      ts variables search ts_user_timezone --profile production
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    payload: dict = {
        "record_offset": 0,
        "record_size": 50,
        "response_content": "METADATA_AND_VALUES",
    }
    if identifier:
        payload["variable_details"] = [{"identifier": identifier}]
    resp = client.post("/api/rest/2.0/template/variables/search", json=payload)
    print(json.dumps(resp.json()))


@app.command("set")
def set_value(
    variable: str = typer.Argument(..., help="Variable name or ID (e.g. ts_user_timezone)"),
    value: str = typer.Argument(..., help="Value to set"),
    org: List[str] = typer.Option(..., "--org", help="Org name (repeatable for multiple orgs)"),
    user: List[str] = typer.Option([], "--user",
                                   help="Username for user-level assignment (repeatable). "
                                        "Omit for org level."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Set (REPLACE) a template variable value for one or more orgs.

    Use --user to apply at user level within each org. Omit --user for org-level.
    Repeat --org and/or --user to apply across multiple orgs and users in one API call.
    Each (org, user) pair becomes one scope entry; all share the same variable value.

    Output: empty on success (HTTP 204). Raises on error.

    Examples:

    \\b
      ts variables set ts_user_timezone Pacific/Honolulu --org Primary
      ts variables set ts_user_timezone Europe/London --org Primary --org Sales
      ts variables set ts_user_timezone America/New_York --org Primary --user alice@example.com
      ts variables set ts_user_timezone Asia/Kolkata --org Primary --user a@x.com --user b@x.com
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    scopes = []
    for org_name in org:
        if user:
            for username in user:
                scopes.append({
                    "org_identifier": org_name,
                    "principal_type": "USER",
                    "principal_identifier": username,
                })
        else:
            scopes.append({"org_identifier": org_name})

    client.post("/api/rest/2.0/template/variables/update-values", json={
        "variable_assignment": [{
            "variable_identifier": variable,
            "variable_values": [value],
            "operation": "REPLACE",
        }],
        "variable_value_scope": scopes,
    })


@app.command("remove")
def remove_value(
    variable: str = typer.Argument(..., help="Variable name or ID"),
    value: str = typer.Argument(..., help="Value to remove (must match current assigned value)"),
    org: List[str] = typer.Option(..., "--org", help="Org name (repeatable for multiple orgs)"),
    user: List[str] = typer.Option([], "--user",
                                   help="Username for user-level removal (repeatable). "
                                        "Omit for org level."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Remove a template variable value for one or more orgs.

    The value argument must match the currently assigned value exactly.
    Use `ts variables search` first to confirm the current value if unsure.
    Repeat --org and/or --user to remove across multiple orgs and users in one API call.

    Output: empty on success (HTTP 204). Raises on error.

    Examples:

    \\b
      ts variables remove ts_user_timezone Pacific/Honolulu --org Primary
      ts variables remove ts_user_timezone Europe/London --org Primary --org Sales
      ts variables remove ts_user_timezone America/New_York --org Primary --user alice@example.com
      ts variables remove ts_user_timezone Asia/Kolkata --org Primary --user a@x.com --user b@x.com
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    scopes = []
    for org_name in org:
        if user:
            for username in user:
                scopes.append({
                    "org_identifier": org_name,
                    "principal_type": "USER",
                    "principal_identifier": username,
                })
        else:
            scopes.append({"org_identifier": org_name})

    client.post("/api/rest/2.0/template/variables/update-values", json={
        "variable_assignment": [{
            "variable_identifier": variable,
            "variable_values": [value],
            "operation": "REMOVE",
        }],
        "variable_value_scope": scopes,
    })
