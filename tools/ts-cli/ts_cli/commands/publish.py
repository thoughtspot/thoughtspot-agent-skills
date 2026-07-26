"""ts publish — publish metadata objects from the Primary Org to target Orgs.

Orgs Publishing keeps ONE object in the Primary Org and makes it visible in
target Orgs; there is no copy and GUIDs are unchanged. Per-Org variation comes
from template variables bound to Table/Connection fields
(`ts metadata parameterize`).

Endpoint shapes and behaviour verified live on 2026-07-25 (see
docs/superpowers/specs/2026-07-25-ts-publish-orgs-design.md §2.5):

- POST /api/rest/2.0/security/metadata/publish    (204, no body)
- POST /api/rest/2.0/security/metadata/unpublish  (204, no body)
- publication state is readable from `metadata_header.orgIds`, so `status`
  needs no per-Org authentication.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Dict, List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Publish objects from the Primary Org to target Orgs.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")

# LOGICAL_TABLE covers both Tables and Models. Connections are NOT publishable:
# they are granted to the target Org automatically as a dependency.
PUBLISHABLE_TYPES = ("LOGICAL_TABLE", "LIVEBOARD", "ANSWER")


def _validate(identifiers: List[str], obj_type: str, orgs: List[str]) -> List[str]:
    if obj_type not in PUBLISHABLE_TYPES:
        raise ValueError(
            f"'{obj_type}' cannot be published. Expected one of: {', '.join(PUBLISHABLE_TYPES)}. "
            f"(A CONNECTION is granted to the target Org automatically as a dependency.)"
        )
    deduped = list(dict.fromkeys(identifiers))
    if not deduped:
        raise ValueError("Specify at least one object to publish")
    if not orgs:
        raise ValueError("Specify at least one org")
    return deduped


def build_publish_payload(
    identifiers: List[str], obj_type: str, orgs: List[str], *, skip_validation: bool = False,
) -> Dict[str, Any]:
    """Build the request body for POST /api/rest/2.0/security/metadata/publish.

    ``skip_validation`` defaults to False and should stay that way. It disables
    EVERY validation in the call, not just the variable-coverage check, and lets
    an unparameterized object publish so that the target Org silently reads the
    Primary Org's hardcoded database and schema. Use a uniform-value variable
    instead when every Org genuinely shares one table.

    Pure — no I/O — so it is unit-testable without a live instance.
    """
    deduped = _validate(identifiers, obj_type, orgs)
    return {
        "metadata": [{"identifier": i, "type": obj_type} for i in deduped],
        "org_identifiers": list(orgs),
        "skip_validation": skip_validation,
    }


def build_unpublish_payload(
    identifiers: List[str], obj_type: str, orgs: List[str], *,
    include_dependencies: bool = True, force: bool = False,
) -> Dict[str, Any]:
    """Build the request body for POST /api/rest/2.0/security/metadata/unpublish.

    ``include_dependencies`` defaults to True, unlike the API's own required
    field, because with False the Connection stays granted to the target Orgs
    after the object is retracted (verified live). A rollback that leaves the
    Connection behind is not a rollback.
    """
    deduped = _validate(identifiers, obj_type, orgs)
    return {
        "metadata": [{"identifier": i, "type": obj_type} for i in deduped],
        "org_identifiers": list(orgs),
        "include_dependencies": include_dependencies,
        "force": force,
    }


def publication_rows(search_results: List[dict], org_index: Dict[int, str]) -> List[dict]:
    """Summarise `metadata/search` results as per-object publication state.

    `metadata_header.orgIds` lists the owning Org plus every Org the object is
    published to, so publication state is readable from the Primary Org with no
    extra authentication. The owning Org is excluded from ``published_to`` so the
    field means "additionally visible in".

    Unknown Org ids degrade to their string form rather than being dropped.

    Pure — no I/O.
    """
    rows: List[dict] = []
    for result in search_results:
        header = result.get("metadata_header") or {}
        owner_org_id = header.get("ownerOrgId")
        org_ids = header.get("orgIds") or []
        published = [org_index.get(i, str(i)) for i in org_ids if i != owner_org_id]
        rows.append({
            "guid": result.get("metadata_id"),
            "name": result.get("metadata_name"),
            "subtype": header.get("type"),
            "owner_org": org_index.get(owner_org_id, str(owner_org_id)),
            "published_to": published,
            "is_published": bool(published),
        })
    return rows


# Publish failures name the variable and object by GUID and the Org by numeric
# id, which is unreadable without resolution. These patterns turn the three
# observed failure modes into actionable messages.
# The identifier groups are deliberately permissive rather than GUID-shaped: the
# publish API accepts object names as well as GUIDs, and the surrounding literal
# text is specific enough to disambiguate on its own.
_MISSING_VALUE_RE = re.compile(
    r"Variable\s+([^\s\]]+)\s+not defined for orgs\s+\[([\d,\s]+)\]"
    r"\s+in which object\s+([^\s\]]+)",
)
_NO_VARIABLE_RE = re.compile(
    r"No template variable node found in the dependency tree for object\s+([^\s\"'\\\]]+)",
)
# The identifier is the last thing in the message, so it runs straight into the
# enclosing JSON's escaping (\"]"}}}}). Stop at the first character that cannot
# appear in an org name rather than anchoring at end-of-string.
# Unpublish refuses to orphan dependents. The payload is an org-id -> [object guid]
# map embedded in the message, doubly JSON-escaped by the enclosing error envelope.
# Cohort publishing is an explicitly unsupported limitation, but the refusal
# identifies the offending column only by GUID.
_COHORT_RE = re.compile(r"Cohort Column as dependency\.\s*ColumnId:\s*([^\s\"'\\\]]+)")

_DEPENDENTS_PHRASE = "Following objects have dependents present:"
_DEP_PAIR_RE = re.compile(r'"?(\d+)"?\s*:\s*\[([^\]]*)\]')
_GUIDISH_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_BARE_ID_RE = re.compile(r'"([^"\s,\[\]]+)"')

_INVALID_ORG_RE = re.compile(r"Org not found corresponding to the org_identifier:\s*([^\s\"'\\\]}]+)")


def guids_in_body(body_text: str) -> set:
    """GUID-shaped tokens appearing anywhere in an error body.

    Used to resolve names for objects the caller never named. A 13152 failure
    reports the BLOCKING object (a shared Model, say), which is not in the
    request, so the caller's own identifier list cannot resolve it. Sweeping the
    body also picks up the incident id, which is harmless: it simply will not
    match anything.
    """
    return set(_GUIDISH_RE.findall(body_text or ""))


def _explain_dependents_present(
    body_text: str, org_index: Dict[int, str], object_index: Dict[str, str],
) -> Optional[str]:
    """Render a 13152 (unpublish blocked by dependents) into an ordered fix."""
    idx = body_text.find(_DEPENDENTS_PHRASE)
    if idx == -1:
        return None
    # Strip the envelope's escaping so the embedded map parses as plain text.
    tail = body_text[idx + len(_DEPENDENTS_PHRASE):].replace("\\", "")

    blocked: List[str] = []
    for org_raw, guid_blob in _DEP_PAIR_RE.findall(tail):
        org = org_index.get(int(org_raw), org_raw)
        ids = _GUIDISH_RE.findall(guid_blob) or _BARE_ID_RE.findall(guid_blob)
        named = ", ".join(f"'{object_index[i]}'" if i in object_index else i for i in ids)
        blocked.append(f"{named} in org '{org}'")
    if not blocked:
        return None

    return (
        f"Cannot unpublish: {'; '.join(blocked)} still has published dependents there. "
        f"Unpublishing would orphan them, so it was refused and nothing changed. "
        f"Retract the dependent objects first with --keep-dependencies, then retract "
        f"this one (which will cascade to its own dependencies)."
    )


def explain_publish_error(
    body_text: str,
    variable_index: Dict[str, str],
    org_index: Dict[int, str],
    object_index: Dict[str, str],
) -> Optional[str]:
    """Translate a publish failure body into an actionable message.

    The three observed failure modes (all HTTP 400, ``code 13151``) are:
    a variable with no value in a target Org, an object with no variable bound
    at all, and an unknown Org identifier. Names are resolved from the supplied
    indexes where possible and fall back to the raw GUID or id.

    Returns None when the body matches none of them, so the caller can surface
    the raw error rather than a misleading paraphrase.

    Pure — no I/O.
    """
    if not body_text:
        return None

    def _obj(guid: str) -> str:
        return f"'{object_index[guid]}'" if guid in object_index else guid

    match = _COHORT_RE.search(body_text)
    if match:
        col = match.group(1)
        named = f"'{object_index[col]}'" if col in object_index else col
        return (
            f"Cannot publish: cohort column {named} is defined on the Model in this "
            f"object's closure. Cohort publishing is not supported, and the block is "
            f"Model-wide: it stops the Model and every Answer or Liveboard built on it, "
            f"whether or not they actually use the column (verified live). Delete the "
            f"cohort column from the Model to publish. Tables below the Model are "
            f"unaffected and can still be published."
        )

    match = _MISSING_VALUE_RE.search(body_text)
    if match:
        var_guid, org_ids_raw, obj_guid = match.groups()
        var_name = variable_index.get(var_guid, var_guid)
        org_names = [org_index.get(int(o.strip()), o.strip())
                     for o in org_ids_raw.split(",") if o.strip()]
        orgs = ", ".join(f"'{o}'" for o in org_names)
        return (
            f"Variable '{var_name}' has no value for org(s) {orgs}, needed by object {_obj(obj_guid)}. "
            f"Assign one with: ts variables set {var_name} <value> "
            f"{' '.join('--org ' + o for o in org_names)}"
        )

    match = _NO_VARIABLE_RE.search(body_text)
    if match:
        obj_guid = match.group(1)
        return (
            f"Object {_obj(obj_guid)} is not parameterized, so it cannot be published. "
            f"Bind a variable to its db/schema/table fields with `ts metadata parameterize` first. "
            f"When every org reads the same table, still use a variable and give it the "
            f"same value in each org rather than passing --skip-validation."
        )

    dependents = _explain_dependents_present(body_text, org_index, object_index)
    if dependents:
        return dependents

    match = _INVALID_ORG_RE.search(body_text.strip())
    if match:
        known = ", ".join(sorted(org_index.values()))
        return f"Org '{match.group(1)}' does not exist. Known orgs: {known}"

    return None


def _org_index(client: ThoughtSpotClient) -> Dict[int, str]:
    """Map numeric Org id to Org name via POST /api/rest/2.0/orgs/search."""
    resp = client.post("/api/rest/2.0/orgs/search", json={})
    return {o["id"]: o["name"] for o in resp.json() if "id" in o}


def _name_index(client: ThoughtSpotClient, guids: List[str], obj_type: str) -> Dict[str, str]:
    """Map object GUID to display name, best-effort (used only for error messages).

    Tries the caller's type first, then the other publishable types, because a
    failure can name an object the caller never mentioned and of a different kind
    (a shared Model blocking a Liveboard unpublish, for instance). Stops as soon
    as every GUID is resolved.
    """
    names: Dict[str, str] = {}
    for candidate in dict.fromkeys([obj_type, *PUBLISHABLE_TYPES, "LOGICAL_COLUMN"]):
        remaining = [g for g in guids if g not in names]
        if not remaining:
            break
        try:
            resp = client.post("/api/rest/2.0/metadata/search",
                               json={"metadata": [{"identifier": g, "type": candidate}
                                                  for g in remaining],
                                     "include_headers": True})
            names.update({r.get("metadata_id"): r.get("metadata_name")
                          for r in resp.json() if r.get("metadata_id")})
        except Exception:
            # Never let a nicety break the real operation's error reporting.
            continue
    return names


def _variable_index(client: ThoughtSpotClient) -> Dict[str, str]:
    """Map variable GUID to variable name, best-effort (used only for error messages).

    Auto-paginates: a partial index would silently degrade a publish failure back
    to the raw GUID it is meant to resolve, which is the confusing case this
    whole function exists to remove.
    """
    index: Dict[str, str] = {}
    page_size = 200
    offset = 0
    try:
        while True:
            resp = client.post("/api/rest/2.0/template/variables/search",
                               json={"record_offset": offset, "record_size": page_size})
            page = resp.json()
            if not isinstance(page, list) or not page:
                break
            index.update({v["id"]: v["name"] for v in page if v.get("id")})
            if len(page) < page_size:
                break
            offset += page_size
    except Exception:
        # Never let a nicety break the real operation's error reporting; a
        # partial index still resolves more names than none.
        pass
    return index


def _post_with_explanation(client: ThoughtSpotClient, path: str, payload: dict,
                           guids: List[str], obj_type: str) -> None:
    """POST a publish/unpublish call, translating a 400 into an actionable message."""
    resp = client.post(path, json=payload, raise_for_status=False)
    if resp.ok:
        return
    body = getattr(resp, "text", "") or ""
    # Include GUIDs that appear only in the error body: the blocking object in a
    # 13152 is a dependency, never something the caller named.
    lookup = list(dict.fromkeys([*guids, *guids_in_body(body)]))
    explanation = explain_publish_error(
        body, _variable_index(client), _org_index(client), _name_index(client, lookup, obj_type),
    )
    if explanation:
        print(explanation, file=sys.stderr)
    else:
        print(f"HTTP {resp.status_code}: {' '.join(body.split())[:500]}", file=sys.stderr)
    raise typer.Exit(1)


@app.command("push")
def push(
    guids: List[str] = typer.Argument(..., help="One or more object GUIDs (or names) to publish"),
    org: List[str] = typer.Option(..., "--org", help="Target org name or numeric id (repeatable)"),
    type: str = typer.Option("LOGICAL_TABLE", "--type", "-t",
                             help="Object type: LOGICAL_TABLE (Tables and Models) | LIVEBOARD | ANSWER"),
    skip_validation: bool = typer.Option(
        False, "--skip-validation",
        help="DISCOURAGED. Disables every pre-publish validation, not just the "
             "variable-coverage check, and lets an unparameterized object publish so the "
             "target org reads the Primary Org's hardcoded database. Prefer a variable "
             "with the same value in each org."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Publish objects from the Primary Org to one or more target Orgs.

    Requires ADMINISTRATION with all-Orgs access, and must run from the Primary Org.
    Published objects are read-only in the target and visible only to that Org's
    admins until they share them onward.

    Every referenced variable must have a value in every target org; publish
    fails closed otherwise, and the error is translated into a `ts variables set`
    command you can run.

    Output: empty on success (HTTP 204). Exits 1 with an explanation on failure.

    Examples:

    \b
      ts publish push 4be2cc25-... --org ORG1
      ts publish push 4be2cc25-... d2c12c11-... --org ORG1 --org ORG2
      ts publish push my-liveboard-guid --type LIVEBOARD --org ORG3
    """
    payload = build_publish_payload(list(guids), type, list(org), skip_validation=skip_validation)
    if skip_validation:
        print("Warning: --skip-validation disables ALL pre-publish checks. An unparameterized "
              "object will publish and read the Primary Org's database in every target org.",
              file=sys.stderr)
    client = ThoughtSpotClient(resolve_profile(profile))
    _post_with_explanation(client, "/api/rest/2.0/security/metadata/publish",
                           payload, list(guids), type)


@app.command("unpush")
def unpush(
    guids: List[str] = typer.Argument(..., help="One or more object GUIDs (or names) to unpublish"),
    org: List[str] = typer.Option(..., "--org", help="Org name or numeric id to retract from (repeatable)"),
    type: str = typer.Option("LOGICAL_TABLE", "--type", "-t",
                             help="Object type: LOGICAL_TABLE | LIVEBOARD | ANSWER"),
    keep_dependencies: bool = typer.Option(
        False, "--keep-dependencies",
        help="Retract only the named objects, leaving dependencies (including the "
             "Connection) granted to the target orgs. Off by default: a rollback that "
             "leaves the Connection behind is not a rollback."),
    force: bool = typer.Option(False, "--force",
                               help="Unpublish even where it breaks dependent objects in the target orgs"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Unpublish objects from one or more target Orgs.

    By default this also retracts dependencies, which is what actually removes
    the Connection grant from the target orgs. Pass --keep-dependencies only if
    you deliberately want them to stay.

    Output: empty on success (HTTP 204). Exits 1 with an explanation on failure.

    Examples:

    \b
      ts publish unpush 4be2cc25-... --org ORG1
      ts publish unpush 4be2cc25-... --org ORG1 --org ORG2 --force
    """
    payload = build_unpublish_payload(list(guids), type, list(org),
                                      include_dependencies=not keep_dependencies, force=force)
    client = ThoughtSpotClient(resolve_profile(profile))
    _post_with_explanation(client, "/api/rest/2.0/security/metadata/unpublish",
                           payload, list(guids), type)


@app.command("status")
def status(
    guids: List[str] = typer.Argument(None, help="Object GUIDs to report on (omit for all of --type)"),
    type: str = typer.Option("LOGICAL_TABLE", "--type", "-t",
                             help="Object type: LOGICAL_TABLE | LIVEBOARD | ANSWER"),
    published_only: bool = typer.Option(False, "--published-only",
                                        help="Report only objects published to at least one other org"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Report which objects are published to which Orgs.

    Reads `metadata_header.orgIds` from the Primary Org, so no per-Org
    authentication is needed. `published_to` excludes the owning Org.

    Output (JSON array to stdout):
      [{"guid", "name", "subtype", "owner_org", "published_to": [...], "is_published"}]

    Examples:

    \b
      ts publish status
      ts publish status --published-only
      ts publish status 4be2cc25-... d2c12c11-...
      ts publish status --type LIVEBOARD --published-only
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    org_index = _org_index(client)

    meta_filter: Dict[str, Any] = {"type": type}
    payload: Dict[str, Any] = {"metadata": [meta_filter], "include_headers": True,
                               "record_offset": 0, "record_size": 500}
    if guids:
        payload["metadata"] = [{"type": type, "identifier": g} for g in guids]

    results: List[dict] = []
    while True:
        resp = client.post("/api/rest/2.0/metadata/search", json=payload)
        data = resp.json()
        page = data if isinstance(data, list) else data.get("metadata", [])
        if not page:
            break
        results.extend(page)
        if guids or len(page) < payload["record_size"]:
            break
        payload["record_offset"] += payload["record_size"]

    rows = publication_rows(results, org_index)
    if published_only:
        rows = [r for r in rows if r["is_published"]]
    print(json.dumps(rows))
