"""ts tenancy export — capture a live cluster's topology as a spec.

Attaches to `tenancy.app`, mirroring how `share_planning.py` attaches to `share.app`.
Split from `tenancy.py` under the file-size gate, and along a real seam: everything else
in the group WRITES to the cluster from a spec, while this READS the cluster into one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
import yaml

from ts_cli.commands.tenancy import (
    _all_orgs,
    _org_inventory,
    _profile_option,
    app,
)
from ts_cli.tenancy_plan import spec_from_cluster


def _capture_user(user: Dict[str, Any], org_name: str, reproducible: set,
                  users_by_name: Dict[str, Dict[str, Any]]) -> None:
    """Fold one row into the cross-Org user record, skipping platform accounts."""
    uname = user.get("name")
    if not uname or user.get("system_user"):
        return
    record = users_by_name.setdefault(uname, {
        "name": uname, "display_name": user.get("display_name") or uname,
        "email": user.get("email") or user.get("mail") or "",
        "account_type": user.get("account_type") or "LOCAL_USER",
        "orgs": [], "groups": {}})
    record["orgs"].append(org_name)
    names = [g.get("name") for g in (user.get("user_groups") or [])
             if g.get("name") in reproducible]
    if names:
        record["groups"][org_name] = names


def _capture_org(org_name: str, rows: Dict[str, List[dict]],
                 users_by_name: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One Org's reproducible groups, folding its users into the shared accumulator.

    Platform-owned objects are filtered on the API's own flags — `system_group` for
    `Administrator`/`All`/`System`, `system_user` for `su`/`system`/`tsadmin`/`guest` —
    rather than a hard-coded name list, which would rot. A spec asking to create them
    would be nonsense.
    """
    groups = [{"name": g["name"], "display_name": g.get("display_name") or g["name"],
               "privileges": list(g.get("privileges") or [])}
              for g in rows["groups"] if not g.get("system_group")]
    reproducible = {g["name"] for g in groups}

    for user in rows["users"]:
        _capture_user(user, org_name, reproducible, users_by_name)
    return groups


@app.command("export")
def export_cmd(
    org: List[str] = typer.Option([], "--org",
                                  help="Org to include (repeatable). Omit for every Org."),
    out: Optional[str] = typer.Option(None, "--out", help="Write here instead of stdout"),
    marker: str = typer.Option("ts-tenancy-fixture", "--marker",
                               help="Marker written into the emitted spec"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Capture a live cluster's topology as a spec.

    This is what makes a reference topology trustworthy: it is CAPTURED from a working
    environment rather than transcribed from someone's notes, so it cannot quietly
    disagree with the cluster it claims to describe. It is also the fastest way to
    document an environment somebody else built.

    Emitted specs carry literal Org names. To turn one into a reusable template, replace
    the tenant-specific names with `{TENANT}` by hand — the round trip is deliberately not
    automatic, because guessing which names are tenant-specific would be guessing.

    Examples:

    \b
      ts tenancy export -p prod
      ts tenancy export --org ORG1 --out templates/org1.yaml -p prod
    """
    all_orgs = _all_orgs(profile)
    wanted = set(org) or {o["name"] for o in all_orgs}
    inventory = _org_inventory(profile, [o["name"] for o in all_orgs if o["name"] in wanted])

    users_by_name: Dict[str, Dict[str, Any]] = {}
    groups_by_org = {name: _capture_org(name, rows, users_by_name)
                     for name, rows in inventory.items()}

    # A user with no email cannot be recreated (`users/create` requires it), so emitting
    # one produces a spec that fails validation. Drop them and say so, rather than
    # shipping a capture that cannot be applied.
    emailless = sorted(u["name"] for u in users_by_name.values() if not u["email"])
    if emailless:
        print(f"warning: omitted {len(emailless)} user(s) with no email address "
              f"({', '.join(emailless)}) — `users/create` requires one, so a spec "
              f"containing them could not be applied", file=sys.stderr)

    doc = spec_from_cluster([o for o in all_orgs if o["name"] in wanted], groups_by_org,
                            [u for u in users_by_name.values() if u["email"]], marker=marker)
    text = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, width=100)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(json.dumps({"written": out, "orgs": len(doc["orgs"]),
                          "users": len(doc["users"])}))
    else:
        print(text)
