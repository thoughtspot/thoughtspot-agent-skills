"""`ts tenancy` spec handling — parse, template and validate a topology document.

Pure functions, no I/O. Split from `tenancy_plan.py` under the file-size gate: a spec is
read and checked once, while the planners are re-run against changing cluster state, so
the two change for different reasons.

**Groups are per-Org, and that is the whole difficulty.** A group name that exists in the
Primary Org genuinely does not exist in a tenant Org; a `ts share` or column-security
manifest naming it fails there with `Invalid group identifiers: <name>`. So a topology is
only coherent if every (user, Org, group) triple lines up: the user belongs to the Org,
the group exists in *that* Org, and it is that Org's group rather than a same-named group
elsewhere. `validate_spec` refuses a spec where any of those fail, at plan time, rather
than letting a half-built cluster look finished.
"""
from __future__ import annotations

from typing import Any, Dict, List, Set


# The Org that always exists and must never be created or deleted. Naming it once here
# keeps the "never touch Primary" rule from being restated (and diverging) per call site.
PRIMARY_ORG = "Primary"

# Written into the `description` of every object this tool creates, and required before
# teardown will delete anything. A spec naming a pre-existing Org is a realistic mistake;
# without the marker, teardown of such a spec would delete real tenant data.
DEFAULT_MARKER = "ts-tenancy-fixture"

_STEP_ORDER = ("create_org", "create_group", "create_user", "add_group_member")

# Only a LOCAL_USER has a password ThoughtSpot owns. Federated accounts authenticate
# elsewhere, so offering them a password would be meaningless at best and would look like
# a working credential at worst. `build_apply_plan` marks which users can take one.
ACCOUNT_TYPES = {"LOCAL_USER", "LDAP_USER", "SAML_USER", "OIDC_USER", "REMOTE_USER"}
LOCAL_ACCOUNT_TYPE = "LOCAL_USER"

# Placeholders substituted by `substitute_tenant`, matching `ts publish resolve --pattern`
# so the two pipelines read the same way.
TENANT_PLACEHOLDERS = ("{TENANT}", "{TENANT_UPPER}", "{TENANT_LOWER}")


class SpecError(ValueError):
    """A spec that cannot be applied. Raised at parse/validate time, never mid-apply."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _require_mapping(doc: Any, what: str) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        raise SpecError(f"{what} must be a mapping, got {type(doc).__name__}")
    return doc


def _parse_orgs(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    orgs: List[Dict[str, str]] = []
    for entry in doc.get("orgs") or []:
        if isinstance(entry, str):
            entry = {"name": entry}
        entry = _require_mapping(entry, "orgs[]")
        name = _as_str(entry.get("name"))
        if not name:
            raise SpecError("every orgs[] entry needs a name")
        orgs.append({"name": name, "description": _as_str(entry.get("description"))})
    return orgs


def _parse_group(entry: Any, org_name: str) -> Dict[str, Any]:
    if isinstance(entry, str):
        entry = {"name": entry}
    entry = _require_mapping(entry, f"groups[{org_name}][]")
    name = _as_str(entry.get("name"))
    if not name:
        raise SpecError(f"every groups[{org_name}][] entry needs a name")
    return {"name": name,
            "display_name": _as_str(entry.get("display_name")) or name,
            "description": _as_str(entry.get("description")),
            "privileges": [str(p) for p in (entry.get("privileges") or [])]}


def _parse_groups(doc: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    raw = _require_mapping(doc.get("groups") or {}, "groups")
    return {_as_str(org): [_parse_group(e, _as_str(org)) for e in (entries or [])]
            for org, entries in raw.items()}


def _parse_user(entry: Any) -> Dict[str, Any]:
    entry = _require_mapping(entry, "users[]")
    name = _as_str(entry.get("name"))
    if not name:
        raise SpecError("every users[] entry needs a name")
    account_type = _as_str(entry.get("account_type")).upper() or LOCAL_ACCOUNT_TYPE
    if account_type not in ACCOUNT_TYPES:
        raise SpecError(
            f"user '{name}' has account_type '{account_type}'; expected one of "
            f"{', '.join(sorted(ACCOUNT_TYPES))}")
    memberships = _require_mapping(entry.get("groups") or {}, f"users[{name}].groups")
    return {"name": name,
            "display_name": _as_str(entry.get("display_name")) or name,
            "email": _as_str(entry.get("email")),
            "account_type": account_type,
            "orgs": [_as_str(o) for o in (entry.get("orgs") or []) if _as_str(o)],
            "groups": {_as_str(org): [_as_str(g) for g in (names or []) if _as_str(g)]
                       for org, names in memberships.items()}}


def parse_spec(doc: Any) -> Dict[str, Any]:
    """Normalise a spec document into the shape the planners consume.

    Returns:

        {"marker": str,
         "orgs":   [{"name", "description"}],
         "groups": {org_name: [{"name", "display_name", "description", "privileges"}]},
         "users":  [{"name", "display_name", "email", "account_type", "orgs": [...],
                     "groups": {org_name: [group_name]}}]}

    Shape errors raise `SpecError`. Cross-references are checked separately by
    `validate_spec`, so a caller can report every problem at once rather than one per run.
    """
    doc = _require_mapping(doc, "spec")
    return {"marker": _as_str(doc.get("marker")) or DEFAULT_MARKER,
            "orgs": _parse_orgs(doc),
            "groups": _parse_groups(doc),
            "users": [_parse_user(e) for e in (doc.get("users") or [])]}


# ---------------------------------------------------------------------------
# Tenant templating
# ---------------------------------------------------------------------------

def substitute_tenant(doc: Any, tenant: str) -> Any:
    """Replace `{TENANT}` placeholders throughout a spec document.

    Onboarding tenant number forty-seven is the same topology with a different Org name.
    Without templating that means a copy-pasted spec per tenant, and copy-pasted specs
    drift -- one gets a group the others do not, and nobody notices until a share fails in
    exactly one Org. One template plus `--tenant` keeps the topology identical by
    construction.

    Placeholders mirror `ts publish resolve --pattern` so the two pipelines read the same:

        {TENANT}        the value as given
        {TENANT_UPPER}  upper-cased
        {TENANT_LOWER}  lower-cased

    Substitution walks the parsed structure rather than the raw text, so a tenant name
    containing YAML-significant characters cannot reshape the document.
    """
    if not tenant:
        return doc
    replacements = {"{TENANT}": tenant,
                    "{TENANT_UPPER}": tenant.upper(),
                    "{TENANT_LOWER}": tenant.lower()}

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            for token, value in replacements.items():
                node = node.replace(token, value)
            return node
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, dict):
            return {walk(k): walk(v) for k, v in node.items()}
        return node

    return walk(doc)


def unresolved_placeholders(doc: Any) -> List[str]:
    """Placeholder tokens still present after substitution.

    A spec applied without `--tenant` would otherwise create an Org literally named
    `{TENANT}` -- which succeeds, looks wrong only on close reading, and is tedious to
    unpick. The command layer refuses on a non-empty result.
    """
    found: Set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, str):
            for token in TENANT_PLACEHOLDERS:
                if token in node:
                    found.add(token)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(key)
                walk(value)

    walk(doc)
    return sorted(found)


# ---------------------------------------------------------------------------
# Validation — the per-Org coherence rules
# ---------------------------------------------------------------------------

def declared_orgs(spec: Dict[str, Any]) -> Set[str]:
    """Every Org the spec can legitimately reference: the ones it creates, plus Primary.

    Primary is always present on a cluster and is never created, but a spec may put groups
    and users in it -- the reference topology does exactly that.
    """
    return {o["name"] for o in spec["orgs"]} | {PRIMARY_ORG}


def _check_orgs(spec: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    seen: Set[str] = set()
    for org in spec["orgs"]:
        if org["name"] == PRIMARY_ORG:
            problems.append(
                f"orgs[] must not contain '{PRIMARY_ORG}': it always exists and is never "
                f"created or deleted. Put its groups under groups[{PRIMARY_ORG}] instead.")
        if org["name"] in seen:
            problems.append(f"duplicate org '{org['name']}'")
        seen.add(org["name"])
    return problems


def _check_groups(spec: Dict[str, Any], known_orgs: Set[str]) -> List[str]:
    problems: List[str] = []
    for org_name, entries in spec["groups"].items():
        if org_name not in known_orgs:
            problems.append(
                f"groups[{org_name}] refers to an Org the spec does not create "
                f"(known: {', '.join(sorted(known_orgs))})")
        seen: Set[str] = set()
        for group in entries:
            if group["name"] in seen:
                problems.append(f"duplicate group '{group['name']}' in Org '{org_name}'")
            seen.add(group["name"])
    return problems


def _check_user(user: Dict[str, Any], spec: Dict[str, Any],
                known_orgs: Set[str]) -> List[str]:
    problems: List[str] = []
    if not user["email"]:
        problems.append(f"user '{user['name']}' needs an email (the API requires it)")

    user_orgs = set(user["orgs"])
    for org_name in sorted(user_orgs - known_orgs):
        problems.append(
            f"user '{user['name']}' is assigned to Org '{org_name}', which the spec does "
            f"not create")

    for org_name, group_names in sorted(user["groups"].items()):
        if org_name not in user_orgs:
            problems.append(
                f"user '{user['name']}' joins group(s) in Org '{org_name}' but is not a "
                f"member of it -- add '{org_name}' to that user's orgs")
            continue
        declared = {g["name"] for g in spec["groups"].get(org_name, [])}
        for group_name in group_names:
            if group_name not in declared:
                problems.append(
                    f"user '{user['name']}' joins group '{group_name}' in Org "
                    f"'{org_name}', but that Org declares no such group. Groups are "
                    f"per-Org: a group of the same name in another Org is a different "
                    f"principal and will not resolve here.")
    return problems


def validate_spec(spec: Dict[str, Any]) -> List[str]:
    """Every cross-reference problem in the spec, as human-readable strings.

    Empty list means the spec is coherent. Returns ALL problems rather than raising on the
    first, because a topology mistake is usually systematic (one Org's groups wrong
    everywhere) and fixing them one run at a time is miserable.

    The four rules, in the order they bite in practice:

    1. An Org referenced by groups or users must be one the spec creates, or Primary.
    2. A user's group memberships must be in Orgs that user actually belongs to.
    3. Every group a user joins must be declared for THAT Org. This is the per-Org trap:
       `Analyst` existing in Primary says nothing about `Analyst` in ORG1, and a manifest
       naming it there fails with `Invalid group identifiers`.
    4. Names must be unique within their scope, or "create if absent" silently collapses
       two entries into one.
    """
    known_orgs = declared_orgs(spec)
    problems = _check_orgs(spec) + _check_groups(spec, known_orgs)

    seen_users: Set[str] = set()
    for user in spec["users"]:
        if user["name"] in seen_users:
            problems.append(f"duplicate user '{user['name']}'")
        seen_users.add(user["name"])
        problems.extend(_check_user(user, spec, known_orgs))
    return problems
