"""ts tenancy — provision an Org/user/group topology from a declarative spec.

Two audiences, one engine. A **test fixture** (BL-137: stand up the multi-tenancy
platform's cluster state reproducibly) and **production tenant onboarding** (create a real
tenant's Org, groups and users) are the same operation; only the safety posture and the
account model differ. Both are served here, and the differences are explicit:

- `account_type` is per user, so a federated tenant gets `SAML_USER`/`OIDC_USER` and is
  never offered a password.
- `--tenant` substitutes `{TENANT}` through a template, so one spec onboards N tenants
  without a copy-pasted file per tenant.
- `teardown` needs the marker AND every Org named on the command line AND `--yes`.

The rest of onboarding is already CLI surface: `ts connections create` → `ts load` →
`ts publish` → `ts alias` → `ts share` / `ts security column-rules`. This command owns the
topology those depend on and nothing beyond it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
import yaml

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.commands.share import _client_for_org, _resolve_org_id, assert_org_context
from ts_cli.tenancy_plan import (
    PRIMARY_ORG,
    build_apply_plan,
    build_teardown_plan,
    diff_topology,
    format_plan,
    is_complete,
    parse_spec,
    spec_from_cluster,
    substitute_tenant,
    unresolved_placeholders,
    validate_spec,
)

app = typer.Typer(help="Provision an Org/user/group topology from a declarative spec.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")
_spec_option = typer.Option(..., "--spec", help="Path to the topology spec (YAML)")
_tenant_option = typer.Option(None, "--tenant",
                              help="Value substituted for {TENANT} / {TENANT_UPPER} / "
                                   "{TENANT_LOWER} throughout the spec")

# Where a created user's marker is stamped. Users have no `description`, unlike Orgs and
# groups, so provenance goes in extended_properties — which `users/search` returns.
_USER_MARKER_KEY = "ts_tenancy_marker"


def _load_spec(spec_path: str, tenant: Optional[str]) -> Dict[str, Any]:
    """Read, template, validate. Every refusal happens here, before any network call."""
    raw = yaml.safe_load(Path(spec_path).read_text(encoding="utf-8"))
    rendered = substitute_tenant(raw, tenant or "")
    leftover = unresolved_placeholders(rendered)
    if leftover:
        raise typer.BadParameter(
            f"spec still contains {', '.join(leftover)} — pass --tenant. Applying it as-is "
            f"would create objects named literally '{leftover[0]}'.")
    spec = parse_spec(rendered)
    problems = validate_spec(spec)
    if problems:
        for problem in problems:
            print(f"  ✗ {problem}", file=sys.stderr)
        raise typer.BadParameter(
            f"{len(problems)} problem(s) in the spec. Nothing was changed.")
    return spec


_PAGE = 200


def _search(client: ThoughtSpotClient, path: str,
            payload: Optional[Dict[str, Any]] = None) -> List[dict]:
    """Auto-paginating search — the caller always gets the full result set.

    Per `.claude/rules/ts-cli.md`: a single fixed page silently truncates on a cluster
    larger than the page size, which for a provisioning tool means reporting an object as
    missing and then failing to create it because it already exists.
    """
    results: List[dict] = []
    offset = 0
    while True:
        body = dict(payload or {})
        body.update({"record_offset": offset, "record_size": _PAGE})
        data = client.post(path, json=body).json()
        page = data if isinstance(data, list) else (data.get("metadata") or [])
        if not page:
            break
        results.extend(page)
        if len(page) < _PAGE:
            break
        offset += _PAGE
    return results


def _org_inventory(profile: Optional[str],
                   org_names: List[str]) -> Dict[str, Dict[str, List[dict]]]:
    """Per-Org group and user rows, read through that Org's own client.

    The single place the per-Org read happens, so `_read_cluster` and `export` cannot
    diverge on it — and they were the two call sites most likely to, since both apply the
    `_groups_in_org` attribution filter and getting that wrong in one but not the other
    would be invisible until a spec was applied.

    An Org that cannot be read is reported as empty with a warning rather than crashing
    the run: `apply` will then try to create what it needs and fail loudly there, which is
    a better error than an opaque read failure at inventory time.
    """
    inventory: Dict[str, Dict[str, List[dict]]] = {}
    for org_name in org_names:
        client = _client_for_org(profile, None if org_name == PRIMARY_ORG else org_name)
        try:
            group_rows = _search(client, "/api/rest/2.0/groups/search")
            user_rows = _search(client, "/api/rest/2.0/users/search")
        except (Exception, SystemExit):
            print(f"warning: could not read Org '{org_name}'; treating as empty",
                  file=sys.stderr)
            continue
        inventory[org_name] = {"groups": _groups_in_org(group_rows, org_name),
                               "users": user_rows}
    return inventory


def _all_orgs(profile: Optional[str]) -> List[Dict[str, str]]:
    base = ThoughtSpotClient(resolve_profile(profile))
    rows = _search(base, "/api/rest/2.0/orgs/search")
    out = [{"name": r.get("orgName") or r.get("name") or "",
            "description": r.get("description") or ""} for r in rows]
    return [o for o in out if o["name"]]


def _groups_in_org(rows: List[dict], org_name: str) -> List[dict]:
    """Group rows that genuinely belong to `org_name`.

    An Org-scoped `groups/search` is NOT sufficient on its own: read from Primary it
    returns groups from EVERY Org, so Primary's list arrives contaminated with each
    tenant's groups. Live-observed — `Demo Retail Group` appeared three times under
    Primary (once per tenant Org), and a user was consequently recorded as belonging to a
    Primary group of that name, which does not exist.

    That is precisely the per-Org attribution error this command exists to prevent, so the
    row's own `orgs` field is the authority, not which client fetched it. Rows without an
    `orgs` field are kept, so a build that omits it degrades to the old behaviour rather
    than silently dropping every group.
    """
    kept = []
    for row in rows:
        if not row.get("name"):
            continue
        orgs = row.get("orgs")
        if orgs is None:
            kept.append(row)
            continue
        if any((o.get("name") if isinstance(o, dict) else o) == org_name for o in orgs):
            kept.append(row)
    return kept


def _note_user(user: Dict[str, Any], uname: str, marker: str, acc: Dict[str, Any]) -> None:
    """Record a user once across all Orgs, flagging those carrying the marker."""
    if uname in acc["seen"]:
        return
    acc["seen"].add(uname)
    acc["users"].append(uname)
    props = user.get("extended_properties") or {}
    if marker and props.get(_USER_MARKER_KEY) == marker:
        acc["marked_users"].append(uname)


def _accumulate_org(org_name: str, rows: Dict[str, List[dict]], marker: str,
                    acc: Dict[str, Any]) -> None:
    """Fold one Org's group and user rows into the cluster reading."""
    this_org_groups = {g["name"] for g in rows["groups"]}
    acc["groups"][org_name] = sorted(this_org_groups)
    acc["marked_groups"][org_name] = [g["name"] for g in rows["groups"]
                                      if marker and marker in (g.get("description") or "")]
    acc["members"][org_name] = {}
    for user in rows["users"]:
        uname = user.get("name")
        if not uname:
            continue
        _note_user(user, uname, marker, acc)
        for group in user.get("user_groups") or []:
            # Attribute a membership to THIS Org only when the group is this Org's: a user
            # search carries their groups across Orgs with no attribution.
            gname = group.get("name")
            if gname and gname in this_org_groups:
                acc["members"][org_name].setdefault(gname, []).append(uname)


def _read_cluster(profile: Optional[str], orgs_of_interest: List[str],
                  marker: str) -> Dict[str, Any]:
    """Current Orgs, per-Org groups, users and memberships — plus what carries the marker."""
    org_rows = _all_orgs(profile)
    org_names = [o["name"] for o in org_rows]
    targets = [o for o in orgs_of_interest if o in org_names] or [PRIMARY_ORG]

    acc: Dict[str, Any] = {"groups": {}, "marked_groups": {}, "members": {},
                           "users": [], "marked_users": [], "seen": set()}
    for org_name, rows in _org_inventory(profile, targets).items():
        _accumulate_org(org_name, rows, marker, acc)

    return {"orgs": org_names, "groups": acc["groups"], "users": acc["users"],
            "members": acc["members"],
            "marked": {"orgs": [o["name"] for o in org_rows
                                if marker and marker in (o["description"] or "")],
                       "groups": acc["marked_groups"], "users": acc["marked_users"]}}


def _spec_orgs(spec: Dict[str, Any]) -> List[str]:
    names = {o["name"] for o in spec["orgs"]} | set(spec["groups"]) | {PRIMARY_ORG}
    for user in spec["users"]:
        names.update(user["orgs"])
    return sorted(names)


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

@app.command("apply")
def apply_cmd(
    spec_path: str = _spec_option,
    tenant: Optional[str] = _tenant_option,
    password_env: Optional[str] = typer.Option(
        None, "--password-env",
        help="Environment variable holding the initial password for LOCAL_USER accounts. "
             "The VALUE is read from the environment and never echoed. Federated accounts "
             "(SAML/OIDC/LDAP) never receive one."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan, change nothing"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Create whatever the spec describes that does not already exist.

    Idempotent: anything present is skipped, so a run that failed halfway is simply re-run.
    That is the normal case when standing up an environment, not the exception.

    Order is a dependency chain, not a preference — an Org before its groups, both before
    a user can join one of those groups.

    Examples:

    \b
      ts tenancy apply --spec tools/fixtures/tenancy-reference.yaml --dry-run -p prod
      ts tenancy apply --spec templates/tenant.yaml --tenant ACME -p prod
      export TS_TENANCY_PASSWORD=...        # in your own terminal
      ts tenancy apply --spec f.yaml --password-env TS_TENANCY_PASSWORD -p prod
    """
    spec = _load_spec(spec_path, tenant)
    current = _read_cluster(profile, _spec_orgs(spec), spec["marker"])
    steps = build_apply_plan(spec, current)

    if not steps:
        print(json.dumps({"applied": 0, "message": "topology already matches the spec"}))
        return
    for line in format_plan(steps):
        print(f"  {line}", file=sys.stderr)
    if dry_run:
        print(json.dumps({"dry_run": True, "steps": steps}))
        return

    secret = None
    if password_env:
        secret = os.environ.get(password_env)
        if not secret:
            raise typer.BadParameter(
                f"--password-env named '{password_env}' but that variable is unset or "
                f"empty. Export it in your own shell; do not pass the value as a flag.")

    base = ThoughtSpotClient(resolve_profile(profile))
    applied = 0
    for step in steps:
        kind = step["kind"]
        if kind == "create_org":
            base.post("/api/rest/2.0/orgs/create",
                      json={"name": step["org"],
                            "description": _stamp(step.get("description"), spec["marker"])})
        elif kind == "create_group":
            client = _org_client(profile, step["org"])
            body: Dict[str, Any] = {
                "name": step["group"], "display_name": step["display_name"],
                "description": _stamp(step.get("description"), spec["marker"])}
            if step.get("privileges"):
                body["privileges"] = step["privileges"]
            client.post("/api/rest/2.0/groups/create", json=body)
        elif kind == "create_user":
            body = {"name": step["user"], "display_name": step["display_name"],
                    "email": step["email"], "account_type": step["account_type"],
                    "org_identifiers": step["orgs"],
                    "extended_properties": {_USER_MARKER_KEY: spec["marker"]}}
            if secret and step["accepts_password"]:
                body["password"] = secret
                body["trigger_activation_email"] = False
            base.post("/api/rest/2.0/users/create", json=body)
        elif kind == "add_group_member":
            client = _org_client(profile, step["org"])
            client.post(f"/api/rest/2.0/groups/{step['group']}/update",
                        json={"user_identifiers": [step["user"]], "operation": "ADD"})
        applied += 1

    print(json.dumps({"applied": applied, "marker": spec["marker"]}))


def _stamp(description: Optional[str], marker: str) -> str:
    """Put the marker in the description without losing what the spec said.

    Teardown keys off this, so every created object has to carry it — but an operator's
    own description is worth keeping, so the marker is appended rather than substituted.
    """
    text = (description or "").strip()
    return f"{text} [{marker}]".strip() if text else f"[{marker}]"


def _org_client(profile: Optional[str], org_name: str) -> ThoughtSpotClient:
    """Org-scoped client with the session asserted, except for Primary (the default)."""
    if org_name == PRIMARY_ORG:
        return ThoughtSpotClient(resolve_profile(profile))
    client = _client_for_org(profile, org_name)
    assert_org_context(client, org_name, profile)
    return client


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

@app.command("verify")
def verify_cmd(
    spec_path: str = _spec_option,
    tenant: Optional[str] = _tenant_option,
    profile: Optional[str] = _profile_option,
) -> None:
    """Report what the spec wants that the cluster does not have. Exit 1 if incomplete.

    One-directional by design: Orgs, groups and users the cluster has but the spec does
    not mention are NOT reported. A shared cluster always carries objects no spec knows
    about, and flagging them would make `verify` permanently red and therefore ignored.

    Examples:

    \b
      ts tenancy verify --spec tools/fixtures/tenancy-reference.yaml -p prod
      ts tenancy verify --spec templates/tenant.yaml --tenant ACME -p prod
    """
    spec = _load_spec(spec_path, tenant)
    current = _read_cluster(profile, _spec_orgs(spec), spec["marker"])
    diff = diff_topology(spec, current)
    print(json.dumps({"complete": is_complete(diff), **diff}))
    if not is_complete(diff):
        for key, values in diff.items():
            for value in values:
                print(f"  missing {key[len('missing_'):]}: {value}", file=sys.stderr)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------

@app.command("teardown")
def teardown_cmd(
    spec_path: str = _spec_option,
    org: List[str] = typer.Option([], "--org",
                                  help="Org to tear down (repeatable). REQUIRED: an Org in "
                                       "the spec but not named here is refused. The spec "
                                       "alone is never sufficient authority to delete."),
    tenant: Optional[str] = _tenant_option,
    yes: bool = typer.Option(False, "--yes", help="Confirm deletion. Required."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan, change nothing"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Delete what this spec created — and refuse everything else.

    **Three independent things must line up**, so no single mistake loses a tenant:
    the object carries the spec's marker, its Org was named with `--org`, and `--yes` was
    passed. A user belonging to any Org outside the named set is refused too, because
    deleting them would strip them from that Org as a side effect.

    Refusals are printed, not silent — they are the safety rail working, and an operator
    should see what was left alone and why.

    Examples:

    \b
      ts tenancy teardown --spec f.yaml --org ORG1 --dry-run -p prod
      ts tenancy teardown --spec f.yaml --org ORG1 --org ORG2 --yes -p prod
    """
    spec = _load_spec(spec_path, tenant)
    current = _read_cluster(profile, _spec_orgs(spec), spec["marker"])
    steps, refusals = build_teardown_plan(spec, current, allowed_orgs=set(org))

    for refusal in refusals:
        print(f"  refused: {refusal}", file=sys.stderr)
    for line in format_plan(steps):
        print(f"  {line}", file=sys.stderr)

    if not steps:
        print(json.dumps({"deleted": 0, "refused": len(refusals),
                          "message": "nothing in scope — see refusals on stderr"}))
        return
    if dry_run:
        print(json.dumps({"dry_run": True, "steps": steps, "refused": refusals}))
        return
    if not yes:
        raise typer.BadParameter(
            f"{len(steps)} object(s) would be DELETED. Re-run with --yes to confirm, or "
            f"--dry-run to review the plan.")

    base = ThoughtSpotClient(resolve_profile(profile))
    deleted = 0
    for step in steps:
        if step["kind"] == "delete_user":
            base.post(f"/api/rest/2.0/users/{step['user']}/delete", json={})
        elif step["kind"] == "delete_group":
            _org_client(profile, step["org"]).post(
                f"/api/rest/2.0/groups/{step['group']}/delete", json={})
        elif step["kind"] == "delete_org":
            base.post(f"/api/rest/2.0/orgs/{step['org']}/delete", json={})
        deleted += 1

    print(json.dumps({"deleted": deleted, "refused": len(refusals)}))


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------
