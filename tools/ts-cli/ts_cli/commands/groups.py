"""ts groups — create, search and populate ThoughtSpot groups.

**Every command here is Org-scoped, and that is the point.** Groups are per-Org: a group
named `Analyst` in the Primary Org and one named `Analyst` in a tenant Org are different
principals, and a `ts share` or column-security manifest naming the wrong one fails with
`Invalid group identifiers: <name>`. So `--org` is not a filter, it decides which Org the
group is created in or read from, and it resolves to a numeric id before use because
`auth/token/full` silently ignores an Org NAME (see `share._resolve_org_id`).
"""
from __future__ import annotations

import json
from typing import List, Optional

import typer

from ts_cli.commands.share import (
    _client_for_org,
    assert_org_context,
)

app = typer.Typer(help="Group management commands (per-Org).")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")
_org_option = typer.Option(None, "--org",
                           help="Org to act in. Groups are per-Org, so this decides which "
                                "Org the group belongs to — not merely which to filter.")


def _client(profile: Optional[str], org: Optional[str]):
    """An Org-scoped client whose session is ASSERTED to be in that Org before any write.

    Org scoping fails silently when the platform does not honour the field it was given,
    and a silent failure here creates a group in the wrong Org — which then looks present
    to an admin and missing to the tenant.
    """
    client = _client_for_org(profile, org)
    if org:
        assert_org_context(client, org, profile)
    return client


@app.command("search")
def search_groups(
    name: Optional[str] = typer.Option(None, "--name", "-n",
                                       help="Filter by name using SQL LIKE syntax"),
    org: Optional[str] = _org_option,
    profile: Optional[str] = _profile_option,
) -> None:
    """List the groups that exist in one Org.

    The fastest way to see the per-Org group topology, and the first thing to check when a
    manifest fails with `Invalid group identifiers`.

    Examples:

    \b
      ts groups search -p prod
      ts groups search --org ORG1 -p prod
      ts groups search --org ORG1 --name "%retail%" -p prod
    """
    from ts_cli.commands.tenancy import _search   # auto-paginating; one implementation

    client = _client(profile, org)
    payload: dict = {"name_pattern": name} if name else {}
    print(json.dumps(_search(client, "/api/rest/2.0/groups/search", payload)))


@app.command("create")
def create_group(
    name: str = typer.Argument(..., help="Group name (unique within its Org)"),
    display_name: Optional[str] = typer.Option(None, "--display-name",
                                               help="Defaults to the group name"),
    description: Optional[str] = typer.Option(None, "--description",
                                              help="`ts tenancy` writes its marker here so "
                                                   "teardown can tell what it created"),
    privilege: List[str] = typer.Option([], "--privilege",
                                        help="Privilege to grant (repeatable), e.g. "
                                             "AUTHORING, A3ANALYSIS, DATADOWNLOADING"),
    user: List[str] = typer.Option([], "--user",
                                   help="User to add as a member (repeatable). The user "
                                        "must already belong to this Org."),
    org: Optional[str] = _org_option,
    profile: Optional[str] = _profile_option,
) -> None:
    """Create a group IN ONE ORG.

    Needs `ADMINISTRATION` (`GROUP_ADMINISTRATION` under RBAC) **in that Org** — privileges
    are per-Org too, so holding them in Primary says nothing about a tenant Org.

    Examples:

    \b
      ts groups create Analyst --privilege AUTHORING --privilege A3ANALYSIS -p prod
      ts groups create "Demo Retail Group" --org ORG1 --privilege AUTHORING -p prod
    """
    client = _client(profile, org)
    payload: dict = {"name": name, "display_name": display_name or name}
    if description:
        payload["description"] = description
    if privilege:
        payload["privileges"] = list(privilege)
    if user:
        payload["user_identifiers"] = list(user)
    resp = client.post("/api/rest/2.0/groups/create", json=payload)
    print(json.dumps(resp.json()))


@app.command("add-member")
def add_member(
    group: str = typer.Argument(..., help="Group name or GUID, resolved within --org"),
    user: List[str] = typer.Option(..., "--user",
                                   help="User to add (repeatable). Must already belong to "
                                        "this Org."),
    org: Optional[str] = _org_option,
    profile: Optional[str] = _profile_option,
) -> None:
    """Add users to a group in one Org.

    Uses `operation: ADD`, so existing members are kept — this is additive, not a replace,
    and re-running it with the same users is harmless.

    A user who is not a member of `--org` cannot be added to a group there; add them to
    the Org first (`ts users create --org`, or the Org's own update endpoint).

    Examples:

    \b
      ts groups add-member Analyst --user guest1 -p prod
      ts groups add-member "Demo Retail Group" --org ORG1 --user guest1 --user guest4 -p prod
    """
    client = _client(profile, org)
    resp = client.post(f"/api/rest/2.0/groups/{group}/update",
                       json={"user_identifiers": list(user), "operation": "ADD"})
    body = resp.text.strip()
    print(json.dumps({"group": group, "org": org or "", "added": list(user),
                      "response": body[:200] if body else "OK"}))
