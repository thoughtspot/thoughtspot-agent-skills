"""`ts tenancy` planning engine — ordered, idempotent steps from a validated spec.

Pure functions, no I/O, so the whole decision surface is unit-testable without a live
instance (`.claude/rules/ts-cli.md`).

**What this exists for.** Exercising the multi-tenancy pattern end to end — publish,
alias, share, secure — needs a cluster with several Orgs, users assigned to those Orgs,
and per-Org groups with the right members. Standing that up was undocumented tribal
knowledge (BL-137). The same engine serves production tenant onboarding, which is the
same operation with a stricter safety posture; see `build_teardown_plan`.

Spec parsing, templating and validation live in `tenancy_spec.py` and are re-exported here
so callers have one import site.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ts_cli.tenancy_spec import (  # noqa: F401 -- re-exported for one import site
    ACCOUNT_TYPES,
    DEFAULT_MARKER,
    LOCAL_ACCOUNT_TYPE,
    PRIMARY_ORG,
    TENANT_PLACEHOLDERS,
    SpecError,
    declared_orgs,
    parse_spec,
    substitute_tenant,
    unresolved_placeholders,
    validate_spec,
)

_STEP_ORDER = ("create_org", "create_group", "create_user", "add_group_member")


def _index(current: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Live state flattened into the sets every planner asks the same questions of."""
    current = current or {}
    return {
        "orgs": set(current.get("orgs") or []),
        "groups": {org: set(names) for org, names in (current.get("groups") or {}).items()},
        "users": set(current.get("users") or []),
        "members": {(org, group, user)
                    for org, groups in (current.get("members") or {}).items()
                    for group, users in groups.items()
                    for user in users},
    }


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def _plan_orgs(spec, have):
    return [{"kind": "create_org", "org": o["name"], "description": o["description"]}
            for o in spec["orgs"] if o["name"] not in have["orgs"]]


def _plan_groups(spec, have):
    steps = []
    for org_name in sorted(spec["groups"]):
        for group in spec["groups"][org_name]:
            if group["name"] in have["groups"].get(org_name, set()):
                continue
            steps.append({"kind": "create_group", "org": org_name, "group": group["name"],
                          "display_name": group["display_name"],
                          "description": group["description"],
                          "privileges": list(group["privileges"])})
    return steps


def _plan_users(spec, have):
    return [{"kind": "create_user", "user": u["name"], "display_name": u["display_name"],
             "email": u["email"], "account_type": u["account_type"],
             # Only a local account can be given a password. A federated user
             # authenticates against the IdP, so the command layer must not try.
             "accepts_password": u["account_type"] == LOCAL_ACCOUNT_TYPE,
             "orgs": list(u["orgs"])}
            for u in spec["users"] if u["name"] not in have["users"]]


def _plan_members(spec, have):
    steps = []
    for user in spec["users"]:
        for org_name in sorted(user["groups"]):
            for group_name in user["groups"][org_name]:
                if (org_name, group_name, user["name"]) in have["members"]:
                    continue
                steps.append({"kind": "add_group_member", "org": org_name,
                              "group": group_name, "user": user["name"]})
    return steps


def build_apply_plan(spec: Dict[str, Any],
                     current: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Ordered, idempotent steps to bring the cluster to the spec's topology.

    `current` is the live reading; omit it to plan against an empty cluster. Anything
    already present is skipped rather than recreated, so a run that failed halfway is
    simply re-run -- the normal case when standing up an environment, not the exception.

    Order is a real dependency chain, not a preference: an Org must exist before a group
    can be created inside it, and both before a user can be added to that Org's group.
    """
    have = _index(current)
    steps = (_plan_orgs(spec, have) + _plan_groups(spec, have)
             + _plan_users(spec, have) + _plan_members(spec, have))
    steps.sort(key=lambda s: (_STEP_ORDER.index(s["kind"]), s.get("org", ""),
                              s.get("group", ""), s.get("user", "")))
    return steps


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def diff_topology(spec: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, List[str]]:
    """What the spec wants that the cluster does not have.

    Deliberately one-directional: extra Orgs, groups and users on the cluster are NOT
    reported as drift. A shared cluster always carries objects no spec knows about, and
    flagging them would make `verify` permanently red and therefore ignored.
    """
    have = _index(current)
    return {
        "missing_orgs": [s["org"] for s in _plan_orgs(spec, have)],
        "missing_groups": [f"{s['org']}/{s['group']}" for s in _plan_groups(spec, have)],
        "missing_users": [s["user"] for s in _plan_users(spec, have)],
        "missing_members": [f"{s['org']}/{s['group']}/{s['user']}"
                            for s in _plan_members(spec, have)],
    }


def is_complete(diff: Dict[str, List[str]]) -> bool:
    return not any(diff.values())


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------

def _teardown_users(spec, have, marked, allowed, marker, refusals):
    steps = []
    for user in spec["users"]:
        name = user["name"]
        if name not in have["users"]:
            continue
        # A user is only in scope if EVERY Org they belong to was explicitly named.
        # Deleting one who also belongs to an Org outside the teardown would remove them
        # from that Org too -- a side effect nobody asked for.
        outside = sorted({o for o in user["orgs"] if o != PRIMARY_ORG} - allowed)
        if outside:
            refusals.append(f"user '{name}' — also belongs to {', '.join(outside)}, which "
                            f"was not named with --org; left alone")
        elif name not in marked["users"]:
            refusals.append(f"user '{name}' — not marked '{marker}', so it was not created "
                            f"by this spec; left alone")
        else:
            steps.append({"kind": "delete_user", "user": name})
    return steps


def _teardown_groups(spec, have, marked, allowed, marker, refusals):
    steps = []
    for org_name in sorted(spec["groups"]):
        for group in spec["groups"][org_name]:
            gname = group["name"]
            if gname not in have["groups"].get(org_name, set()):
                continue
            if org_name not in allowed:
                refusals.append(f"group '{org_name}/{gname}' — Org '{org_name}' was not "
                                f"named with --org; left alone")
            elif gname not in marked["groups"].get(org_name, set()):
                refusals.append(f"group '{org_name}/{gname}' — not marked '{marker}'; "
                                f"left alone")
            else:
                steps.append({"kind": "delete_group", "org": org_name, "group": gname})
    return steps


def _teardown_orgs(spec, have, marked, allowed, marker, refusals):
    steps = []
    for org in spec["orgs"]:
        name = org["name"]
        if name == PRIMARY_ORG:
            refusals.append(f"Org '{PRIMARY_ORG}' — never deleted")
        elif name not in have["orgs"]:
            continue
        elif name not in allowed:
            refusals.append(f"Org '{name}' — not named with --org; left alone")
        elif name not in marked["orgs"]:
            refusals.append(f"Org '{name}' — not marked '{marker}'; left alone")
        else:
            steps.append({"kind": "delete_org", "org": name})
    return steps


def build_teardown_plan(spec: Dict[str, Any], current: Dict[str, Any],
                        marker: Optional[str] = None,
                        allowed_orgs: Optional[Set[str]] = None) -> Tuple[
                            List[Dict[str, Any]], List[str]]:
    """Reverse-order deletions, plus the list of things deliberately REFUSED.

    Returns `(steps, refusals)`. Refusals are not errors -- they are the safety rail
    working, and the caller should print them so an operator sees what was left alone.

    THREE independent things must line up before anything is deleted, so that no single
    mistake -- a mistyped spec, a stale marker, a copy-pasted command -- can lose a tenant:

    - **Marker required.** Only objects whose description carries the spec's marker are
      deleted. A spec naming an Org that already existed for real reasons is an easy
      mistake to make; without this, teardown would delete it.
    - **Explicitly named Orgs.** `allowed_orgs` is the set named on the command line. An
      Org in the spec but absent from it is refused -- the spec alone is never sufficient
      authority to delete. `None` means "no Org was named", which refuses everything
      rather than defaulting to permissive.
    - **Primary is never deleted**, whatever a spec says.

    Order is the reverse dependency chain: users, then groups, then Orgs.
    """
    marker = marker or spec.get("marker") or DEFAULT_MARKER
    allowed = set(allowed_orgs or ())
    have = _index(current)
    raw_marked = current.get("marked") or {}
    marked = {"orgs": set(raw_marked.get("orgs") or []),
              "groups": {o: set(n) for o, n in (raw_marked.get("groups") or {}).items()},
              "users": set(raw_marked.get("users") or [])}

    refusals: List[str] = []
    steps = (_teardown_users(spec, have, marked, allowed, marker, refusals)
             + _teardown_groups(spec, have, marked, allowed, marker, refusals)
             + _teardown_orgs(spec, have, marked, allowed, marker, refusals))
    return steps, refusals


# ---------------------------------------------------------------------------
# Export — capture a live cluster as a spec
# ---------------------------------------------------------------------------

def _export_group(group: Dict[str, Any]) -> Dict[str, Any]:
    name = group.get("name")
    return {"name": name, "display_name": group.get("display_name") or name,
            "privileges": list(group.get("privileges") or [])}


def _export_user(user: Dict[str, Any]) -> Dict[str, Any]:
    name = user.get("name")
    memberships = {org: sorted(set(names))
                   for org, names in (user.get("groups") or {}).items() if names}
    return {"name": name,
            "display_name": user.get("display_name") or name,
            "email": user.get("email") or "",
            "account_type": user.get("account_type") or LOCAL_ACCOUNT_TYPE,
            "orgs": sorted(set(user.get("orgs") or [])),
            "groups": dict(sorted(memberships.items()))}


def spec_from_cluster(orgs: Iterable[Dict[str, Any]],
                      groups_by_org: Dict[str, List[Dict[str, Any]]],
                      users: Iterable[Dict[str, Any]],
                      marker: str = DEFAULT_MARKER) -> Dict[str, Any]:
    """Build a spec document from live cluster readings.

    This is what makes the shipped reference topology trustworthy: it is CAPTURED from a
    working environment rather than transcribed from someone's notes, so it cannot quietly
    disagree with the cluster it claims to describe.

    Primary is excluded from `orgs` (it is never created) but its groups and user
    memberships are kept, because the reference topology puts real groups there.
    """
    out_orgs = [{"name": o["name"], "description": o.get("description") or ""}
                for o in orgs if o.get("name") and o["name"] != PRIMARY_ORG]
    out_groups = {org: sorted((_export_group(g) for g in entries if g.get("name")),
                              key=lambda g: g["name"])
                  for org, entries in groups_by_org.items() if entries}
    out_users = [_export_user(u) for u in users if u.get("name")]
    return {"marker": marker,
            "orgs": sorted(out_orgs, key=lambda o: o["name"]),
            "groups": dict(sorted(out_groups.items())),
            "users": sorted(out_users, key=lambda u: u["name"])}


_PLAN_LINE = {
    "create_org": lambda s: f"create org      {s['org']}",
    "create_group": lambda s: (f"create group    {s['org']}/{s['group']}  "
                               f"({','.join(s.get('privileges') or []) or 'none'})"),
    "create_user": lambda s: f"create user     {s['user']}  orgs={','.join(s['orgs'])}",
    "add_group_member": lambda s: f"add member      {s['org']}/{s['group']} <- {s['user']}",
    "delete_user": lambda s: f"DELETE user     {s['user']}",
    "delete_group": lambda s: f"DELETE group    {s['org']}/{s['group']}",
    "delete_org": lambda s: f"DELETE org      {s['org']}",
}


def format_plan(steps: List[Dict[str, Any]]) -> List[str]:
    """One human-readable line per step, for --dry-run and progress output."""
    return [_PLAN_LINE[s["kind"]](s) for s in steps if s["kind"] in _PLAN_LINE]
