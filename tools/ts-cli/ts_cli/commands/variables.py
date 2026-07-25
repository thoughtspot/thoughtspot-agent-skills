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

# Variable types accepted by POST /api/rest/2.0/template/variables/create.
# CONNECTION_PROPERTY_PER_PRINCIPAL is disabled by default and needs ThoughtSpot
# Support to enable it on the instance.
VARIABLE_TYPES = (
    "TABLE_MAPPING",                     # databaseName / schemaName / tableName
    "CONNECTION_PROPERTY",               # accountName / warehouse / user / password / role
    "CONNECTION_PROPERTY_PER_PRINCIPAL",  # as above, per user or group (support-gated)
    "FORMULA_VARIABLE",                  # formula and rule logic via ts_var()
)


def build_create_variable_payload(
    var_type: str, name: str, *, sensitive: bool = False, data_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the request body for POST /api/rest/2.0/template/variables/create.

    ``data_type`` is required for FORMULA_VARIABLE and rejected for every other
    type. Its *value* is deliberately not validated: the published docs give two
    conflicting lists (VARCHAR/BIGINT/INT/FLOAT vs VARCHAR/INT32/INT64/DOUBLE),
    so an unrecognised-but-valid type must not be blocked client-side. The API
    is left to reject a genuinely bad one.

    Pure — no I/O — so it is unit-testable without a live instance.
    """
    if var_type not in VARIABLE_TYPES:
        raise ValueError(f"Unknown variable type '{var_type}'. Expected one of: {', '.join(VARIABLE_TYPES)}")
    if var_type == "FORMULA_VARIABLE":
        if not data_type:
            raise ValueError("data_type is required for FORMULA_VARIABLE (e.g. VARCHAR, DATE)")
    elif data_type:
        raise ValueError(f"--data-type is only valid for FORMULA_VARIABLE, not {var_type}")

    payload: Dict[str, Any] = {"type": var_type, "name": name, "is_sensitive": sensitive}
    if data_type:
        payload["data_type"] = data_type
    return payload


@app.command("create")
def create_variable(
    name: str = typer.Argument(..., help="Variable name (must be unique across ALL orgs on the instance)"),
    type: str = typer.Option(..., "--type", "-t",
                             help=f"Variable type: {' | '.join(VARIABLE_TYPES)}"),
    sensitive: bool = typer.Option(False, "--sensitive",
                                   help="Mark the variable as holding sensitive values (e.g. a password). "
                                        "Assign the value from your own terminal — never through a skill prompt."),
    data_type: Optional[str] = typer.Option(None, "--data-type",
                                            help="Value data type. Required for FORMULA_VARIABLE "
                                                 "(e.g. VARCHAR, INT64, DATE); invalid for other types."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Create a template variable for parameterizing metadata objects.

    Names are unique instance-wide, not per-org — creating a duplicate fails.
    Run `ts variables search` first if unsure.

    A new variable has no values. Assign them per-org with `ts variables set`
    before publishing anything that depends on it: publish fails closed when a
    variable has no value in a target org.

    Output: JSON variable object from POST /api/rest/2.0/template/variables/create,
    including the generated `id`.

    Examples:

    \\b
      ts variables create apj_schema --type TABLE_MAPPING
      ts variables create sf_password --type CONNECTION_PROPERTY --sensitive
      ts variables create region_var --type FORMULA_VARIABLE --data-type VARCHAR
    """
    payload = build_create_variable_payload(type, name, sensitive=sensitive, data_type=data_type)
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post("/api/rest/2.0/template/variables/create", json=payload)
    print(json.dumps(resp.json()))


@app.command("delete")
def delete_variables(
    variables: List[str] = typer.Argument(..., help="One or more variable names or IDs"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Delete one or more template variables.

    Uses POST /api/rest/2.0/template/variables/delete, which takes a batch
    `identifiers[]` array. (The per-identifier
    POST /api/rest/2.0/template/variables/{identifier}/delete path is deprecated;
    the batch endpoint was confirmed live on 2026-07-25.)

    Deletion fails if the variable is still bound to an object — unparameterize
    the fields first with `ts metadata unparameterize`.

    Output: empty on success (HTTP 204). Raises on error.

    Examples:

    \\b
      ts variables delete apj_schema
      ts variables delete apj_schema apj_db region_var
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    client.post("/api/rest/2.0/template/variables/delete",
                json={"identifiers": list(dict.fromkeys(variables))})


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
