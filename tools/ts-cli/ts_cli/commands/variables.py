"""ts variables — manage ThoughtSpot template variable values."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

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
    """Search template variables and their current assignments (auto-paginated).

    Output: JSON array from POST /api/rest/2.0/template/variables/search — the
    full result set across all pages (same pattern as `ts connections list`),
    not capped at one page.
    Each element has id, name, variable_type, and a values[] array of assignments.
    Each assignment has: value, org_identifier, principal_type, principal_identifier.

    Examples:

    \\b
      ts variables search
      ts variables search ts_user_timezone
      ts variables search ts_user_timezone --profile production
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    page_size = 50
    all_results: List[dict] = []
    offset = 0
    while True:
        payload: dict = {
            "record_offset": offset,
            "record_size": page_size,
            "response_content": "METADATA_AND_VALUES",
        }
        if identifier:
            payload["variable_details"] = [{"identifier": identifier}]
        resp = client.post("/api/rest/2.0/template/variables/search", json=payload)
        page = resp.json()
        if not isinstance(page, list) or not page:
            break
        all_results.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    print(json.dumps(all_results))


def _build_variable_assignments(value: str, org: List[str], user: List[str]) -> List[Dict[str, Any]]:
    """Build the ``variable_assignment[]`` entries shared by set_value and remove_value.

    One entry per (org[, user]) scope; all share the same assigned value. This is
    the org x user scope-expansion logic that used to be duplicated verbatim
    between the two commands (2026-07 audit finding 6.4) — both now call this.
    """
    assignments: List[Dict[str, Any]] = []
    for org_name in org:
        if user:
            for username in user:
                assignments.append({
                    "assigned_values": [value],
                    "org_identifier": org_name,
                    "principal_type": "USER",
                    "principal_identifier": username,
                })
        else:
            assignments.append({
                "assigned_values": [value],
                "org_identifier": org_name,
            })
    return assignments


def _build_variable_update_payload(
    value: str, org: List[str], user: List[str], *, operation: str,
) -> Dict[str, Any]:
    """Build the request body for POST .../template/variables/{identifier}/update-values.

    Verified via ``get-rest-api-reference(apiName="putVariableValues")``: ``operation``
    is top-level and each ``variable_assignment[]`` entry carries its own scope
    (``org_identifier`` / ``principal_type`` / ``principal_identifier``) plus
    ``assigned_values``. The variable identifier itself goes in the URL path, not
    the body — see ``set_value`` / ``remove_value``.
    """
    return {
        "operation": operation,
        "variable_assignment": _build_variable_assignments(value, org, user),
    }


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

    Uses POST /api/rest/2.0/template/variables/{identifier}/update-values — the
    identifier (name or GUID) goes directly in the URL path, one variable per call.
    This replaces the deprecated batch endpoint
    POST /api/rest/2.0/template/variables/update-values, removed per the
    26.4.0.cl deprecation notice (`putVariableValues` is the documented
    replacement for `updateVariableValues`; 2026-07 audit finding 13.1). Semantics
    (REPLACE/ADD/REMOVE/RESET) are unchanged.

    Output: empty on success (HTTP 204). Raises on error.

    Examples:

    \\b
      ts variables set ts_user_timezone Pacific/Honolulu --org Primary
      ts variables set ts_user_timezone Europe/London --org Primary --org Sales
      ts variables set ts_user_timezone America/New_York --org Primary --user alice@example.com
      ts variables set ts_user_timezone Asia/Kolkata --org Primary --user a@x.com --user b@x.com
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    client.post(
        f"/api/rest/2.0/template/variables/{quote(variable, safe='')}/update-values",
        json=_build_variable_update_payload(value, org, user, operation="REPLACE"),
    )


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

    Uses POST /api/rest/2.0/template/variables/{identifier}/update-values — see
    the `ts variables set` docstring for the per-identifier endpoint migration note.

    Output: empty on success (HTTP 204). Raises on error.

    Examples:

    \\b
      ts variables remove ts_user_timezone Pacific/Honolulu --org Primary
      ts variables remove ts_user_timezone Europe/London --org Primary --org Sales
      ts variables remove ts_user_timezone America/New_York --org Primary --user alice@example.com
      ts variables remove ts_user_timezone Asia/Kolkata --org Primary --user a@x.com --user b@x.com
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    client.post(
        f"/api/rest/2.0/template/variables/{quote(variable, safe='')}/update-values",
        json=_build_variable_update_payload(value, org, user, operation="REMOVE"),
    )
