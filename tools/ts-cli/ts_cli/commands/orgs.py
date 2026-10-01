"""ts orgs — search ThoughtSpot orgs."""
from __future__ import annotations

import json
from typing import List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Org management commands.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")


ORGS_SEARCH = "/api/rest/2.0/orgs/search"
_PAGE_SIZE = 50


def _build_payload(offset_val: int, size: int, status: Optional[str] = None,
                   name: Optional[str] = None) -> dict:
    payload: dict = {"record_offset": offset_val, "record_size": size}
    if status:
        payload["status"] = status
    if name:
        payload["name_pattern"] = name
    return payload


def list_orgs(client, *, status: Optional[str] = None,
              name: Optional[str] = None) -> List[dict]:
    """Every Org matching the filters, auto-paginated. Rows carry orgId, orgName,
    description and status. Shared by `ts orgs search` and `ts sets inventory --all-orgs`."""
    all_results: List[dict] = []
    offset = 0
    while True:
        resp = client.post(ORGS_SEARCH, json=_build_payload(offset, _PAGE_SIZE, status, name))
        page = resp.json()
        if not isinstance(page, list) or not page:
            break
        all_results.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return all_results


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
    if limit is not None:
        resp = client.post(ORGS_SEARCH, json=_build_payload(0, limit, status, name))
        print(json.dumps(resp.json()))
        return
    print(json.dumps(list_orgs(client, status=status, name=name)))


@app.command("create")
def create(
    name: str = typer.Argument(..., help="Org name (must be unique cluster-wide)"),
    description: Optional[str] = typer.Option(None, "--description",
                                              help="Org description. `ts tenancy` writes "
                                                   "its marker here so teardown can tell "
                                                   "what it created."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Create an Org.

    Needs cluster administration (`ORG_ADMINISTRATION` under RBAC), and the Orgs feature
    must be enabled. Output: the created Org as JSON, including its numeric `id` — which
    is what org-scoped auth needs, since `auth/token/full` silently ignores an Org NAME.

    Examples:

    \b
      ts orgs create ORG1 -p prod
      ts orgs create ORG1 --description "ts-tenancy-fixture tenant" -p prod
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    payload: dict = {"name": name}
    if description:
        payload["description"] = description
    resp = client.post("/api/rest/2.0/orgs/create", json=payload)
    print(json.dumps(resp.json()))
