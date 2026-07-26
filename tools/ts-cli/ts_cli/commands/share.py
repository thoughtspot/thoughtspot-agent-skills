"""ts share — object-level and column-level grants over security/metadata/share.

Sharing is a lower-level capability than publication: it is needed whether or not
anything was published, and the same endpoint carries column-level security. So it is
its own command group rather than a step inside `ts publish`.

Endpoint shape verified live on 2026-07-26 (see
docs/superpowers/specs/2026-07-26-ts-security-sharing-design.md §2), with two findings
that contradict the published examples:

- `message` is TOP-LEVEL, beside `notify_on_share` -- NOT inside `notification`. The
  nested form fails with `Variable "$message" of required type "String!" was not
  provided`, so nothing works until this is right. The request schema agrees: message
  and notify_on_share are top-level properties, and message is required.
- `LOGICAL_COLUMN` IS accepted and takes effect, despite being absent from the docs'
  "Supported metadata objects" prose list (it is in the metadata_type enum).

The pipeline mirrors `ts publish` and the `ts alias` source conventions:

    ts share export | ts share resolve | ts share apply     (+ ts share status)

Pure planning logic lives in `ts_cli/share_plan.py`; this module is the I/O wrapper.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.share_plan import GRANTABLE_TYPES, permission_rows

app = typer.Typer(help="Share objects and columns with groups (object and column security).")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")

# LOGICAL_COLUMN is shareable even though the docs' supported-types prose omits it
# (verified live). It is never named in a manifest -- a column grant is a column_name on
# a LOGICAL_TABLE row -- but the payload builder must accept it.
SHAREABLE_TYPES = GRANTABLE_TYPES + ("LOGICAL_COLUMN",)

_DEFAULT_MESSAGE = "Access granted by ts share."


def build_share_payload(
    identifiers: List[str],
    metadata_type: str,
    permissions: List[Dict[str, Any]],
    *,
    message: str,
    notify_on_share: bool = False,
) -> Dict[str, Any]:
    """Build the request body for POST /api/rest/2.0/security/metadata/share.

    ``message`` goes at the TOP LEVEL, beside ``notify_on_share``. Every published
    example nests it inside a ``notification`` object; that form is rejected with
    `Variable "$message" of required type "String!" was not provided`. The endpoint's
    own request schema lists both as top-level and marks ``message`` required.

    ``notify_on_share`` defaults to False, against the API's own default of True.
    Sharing tenant data across Orgs is a bulk administrative operation, and emailing
    every member of every group on every run is not what an operator wants; opting in
    is the safer default.

    Pure -- no I/O -- so it is unit-testable without a live instance.
    """
    if metadata_type not in SHAREABLE_TYPES:
        raise ValueError(
            f"'{metadata_type}' cannot be shared by this command. Expected one of: "
            f"{', '.join(SHAREABLE_TYPES)}.")
    deduped = list(dict.fromkeys(identifiers or []))
    if not deduped:
        raise ValueError("Specify at least one object to share")
    if not permissions:
        raise ValueError("Specify at least one principal to share with")
    if not (message or "").strip():
        raise ValueError("A non-empty message is required by the share API")
    return {
        "metadata_type": metadata_type,
        "metadata_identifiers": deduped,
        "permissions": list(permissions),
        "message": message,
        "notify_on_share": notify_on_share,
    }


# ---------------------------------------------------------------------------
# Shared I/O helpers
# ---------------------------------------------------------------------------

def _client_for_org(profile: Optional[str], org: Optional[str] = None) -> ThoughtSpotClient:
    """A client scoped to one Org.

    Groups are per-Org, so a grant naming a group only resolves inside that Org's
    context. Each Org gets its own client (and its own cached token) rather than the
    process switching TS_ORG between calls.
    """
    return ThoughtSpotClient(resolve_profile(profile), org=org)


def _read_json_envelope(input_file: Optional[str]) -> Dict[str, Any]:
    """Read a JSON envelope from --input, or stdin when not given."""
    if input_file:
        return json.loads(Path(input_file).read_text())
    if sys.stdin.isatty():
        raise typer.BadParameter("Provide --input <file> or pipe the previous stage's output in")
    return json.loads(sys.stdin.read())


def _search(client: ThoughtSpotClient, body: Dict[str, Any]) -> List[dict]:
    """POST metadata/search and return the result list, whichever envelope came back."""
    resp = client.post("/api/rest/2.0/metadata/search", json=body)
    data = resp.json()
    return data if isinstance(data, list) else (data.get("metadata") or [])


def _descriptor(hit: Dict[str, Any], fallback_name: str) -> Dict[str, Any]:
    """A metadata/search hit as {guid, name, type, subtype}."""
    header = hit.get("metadata_header") or {}
    return {
        "guid": hit.get("metadata_id") or header.get("id") or "",
        "name": hit.get("metadata_name") or header.get("name") or fallback_name,
        "type": hit.get("metadata_type") or "LOGICAL_TABLE",
        "subtype": header.get("type") or "",
    }


def _try_search(client: ThoughtSpotClient, metadata: Dict[str, Any],
                record_size: int) -> List[dict]:
    """One metadata/search attempt, swallowing the failure so the next can run.

    Resolution walks several candidate types; a 400 on one of them is expected, not
    an error worth surfacing.
    """
    try:
        return _search(client, {"metadata": [metadata], "include_headers": True,
                                "record_size": record_size})
    except Exception:
        return []


def _resolve_object(client: ThoughtSpotClient, identifier: str) -> Dict[str, Any]:
    """Resolve a GUID or name to {guid, name, type, subtype}, failing loudly.

    A GUID resolves untyped and identifies at most one object. A NAME needs its type
    supplied, so each grantable type is tried in turn, and an exact-name match is
    REQUIRED -- an ambiguous name is refused rather than resolved to the first hit.
    That matters more here than in most lookups: silently picking one of two
    same-named tables would grant a tenant access to the wrong data.
    """
    by_guid = _try_search(client, {"identifier": identifier}, 1)
    if by_guid:
        return _descriptor(by_guid[0], identifier)

    for obj_type in GRANTABLE_TYPES:
        # A small page, then an exact-name filter: enough to detect ambiguity without
        # turning a bounded lookup into a listing.
        hits = _try_search(client, {"identifier": identifier, "type": obj_type}, 10)
        exact = [h for h in hits if h.get("metadata_name") == identifier]
        if len(exact) > 1:
            raise typer.BadParameter(
                f"'{identifier}' matches {len(exact)} {obj_type} objects "
                f"({', '.join(h.get('metadata_id', '?') for h in exact)}). Pass the GUID "
                f"of the one you mean -- guessing which object to share would be unsafe.")
        if exact:
            return _descriptor(exact[0], identifier)

    raise typer.BadParameter(
        f"Could not resolve '{identifier}'. Expected a GUID, or the exact name of one of: "
        f"{', '.join(GRANTABLE_TYPES)}.")


def _table_columns(client: ThoughtSpotClient, table_guid: str) -> List[Dict[str, str]]:
    """[{guid, name}] for a LOGICAL_TABLE's columns, via include_details.

    Column GUIDs are what LOGICAL_COLUMN sharing needs, and they are not in the
    Table TML -- metadata/search with include_details is the one place they surface.
    """
    hits = _search(client, {"metadata": [{"identifier": table_guid, "type": "LOGICAL_TABLE"}],
                            "include_details": True, "include_headers": True,
                            "include_hidden_objects": True})
    if not hits:
        return []
    columns = (hits[0].get("metadata_detail") or {}).get("columns") or []
    resolved: List[Dict[str, str]] = []
    for column in columns:
        header = column.get("header") or {}
        if header.get("id") and header.get("name"):
            resolved.append({"guid": header["id"], "name": header["name"]})
    return resolved


def _fetch_permissions(client: ThoughtSpotClient, targets: List[Dict[str, str]],
                       groups: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Read current grants for a set of objects, normalised to flat rows.

    ``permission_type: DEFINED`` asks for access that came from SHARING rather than from
    group privileges -- which is what a before/after check on `ts share` should compare.
    """
    if not targets:
        return []
    body: Dict[str, Any] = {
        "metadata": [{"identifier": t["guid"], "type": t["type"]} for t in targets],
        "record_offset": 0, "record_size": -1,
        "permission_type": "DEFINED",
    }
    if groups:
        body["principals"] = [{"type": "USER_GROUP", "identifier": g} for g in groups]
    resp = client.post("/api/rest/2.0/security/metadata/fetch-permissions", json=body,
                       raise_for_status=False)
    if not resp.ok:
        print(f"Warning: could not read permissions "
              f"(HTTP {resp.status_code}): {' '.join((resp.text or '').split())[:300]}",
              file=sys.stderr)
        return []
    return permission_rows(resp.json())


# ---------------------------------------------------------------------------
# Share-call execution and error translation (used by `ts share apply`)
# ---------------------------------------------------------------------------

# The failure an implementation hits first, and the one whose message points nowhere
# useful. Worth translating even though this CLI never builds the nested form: a
# hand-rolled payload or a future refactor would land here.
_NESTED_MESSAGE_RE = re.compile(
    r'Variable\s+\\?"\$message\\?"\s+of required type', re.IGNORECASE)
_MISSING_PRINCIPAL_RE = re.compile(
    r"Principal object does not exist corresponding to the identifier\s+"
    r"([^\s\"'\\,}\]]+)")


def explain_share_error(body_text: str) -> Optional[str]:
    """Translate a share failure body into an actionable message.

    Returns None when the body matches nothing known, so the caller surfaces the raw
    error rather than a misleading paraphrase.

    Pure -- no I/O.
    """
    if not body_text:
        return None

    if _NESTED_MESSAGE_RE.search(body_text):
        return (
            "The share payload put `message` in the wrong place. It belongs at the top "
            "level, beside `notify_on_share` -- not inside a `notification` object, "
            "despite every published example showing it nested.")

    match = _MISSING_PRINCIPAL_RE.search(body_text)
    if match:
        return (
            f"Group or user '{match.group(1)}' does not exist in the Org this call ran "
            f"in. Groups are per-Org: a group in the Primary Org is a different principal "
            f"from a same-named group in a tenant Org. Check the spelling, confirm the "
            f"Org, and re-run `ts share resolve` without --skip-group-check to catch this "
            f"at plan time.")

    return None


def _apply_step(client: ThoughtSpotClient, step: Dict[str, Any],
                message: str, notify: bool) -> None:
    """POST one share call, translating a failure into something actionable."""
    payload = build_share_payload(step["metadata_identifiers"], step["metadata_type"],
                                  step["permissions"], message=message,
                                  notify_on_share=notify)
    resp = client.post("/api/rest/2.0/security/metadata/share", json=payload,
                       raise_for_status=False)
    audience = ", ".join(f"{p['principal']['identifier']}={p['share_mode']}"
                         for p in step["permissions"])
    where = step["org_name"] or "current org"
    if resp.ok:
        print(f"[{where}] {step['metadata_type']}: {', '.join(step['labels'])} "
              f"-> {audience}", file=sys.stderr)
        return

    body = getattr(resp, "text", "") or ""
    explanation = explain_share_error(body)
    if not explanation:
        explanation = f"HTTP {resp.status_code} {' '.join(body.split())[:400]}"
    print(f"Failed in org '{where}' on {', '.join(step['labels'])}: {explanation}",
          file=sys.stderr)
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# ts share status
# ---------------------------------------------------------------------------

def _status_targets(client: ThoughtSpotClient, guids: List[str],
                    with_columns: bool) -> List[Dict[str, str]]:
    """The objects (and optionally their columns) to read permissions for."""
    targets: List[Dict[str, str]] = []
    for identifier in dict.fromkeys(guids):
        resolved = _resolve_object(client, identifier)
        targets.append({"guid": resolved["guid"], "type": resolved["type"]})
        if with_columns and resolved["type"] == "LOGICAL_TABLE":
            targets += [{"guid": c["guid"], "type": "LOGICAL_COLUMN"}
                        for c in _table_columns(client, resolved["guid"])]
    return targets


@app.command("status")
def status_cmd(
    guids: List[str] = typer.Argument(..., help="Object GUIDs or names to report on"),
    org: List[str] = typer.Option([], "--org",
                                  help="Report grants in this Org (repeatable). Omit for "
                                       "the current Org."),
    group: List[str] = typer.Option([], "--group",
                                    help="Restrict to these groups (repeatable)"),
    columns: bool = typer.Option(False, "--columns",
                                 help="Also report column-level grants on each table"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Report who can see each object -- and, with --columns, each of its columns.

    The read-back half of the pipeline, and the way to check an apply landed.
    ``shared_permission`` is what SHARING granted; ``permission`` is effective access,
    which shows MODIFY for an admin group whether or not anything was shared with it.
    Compare ``shared_permission`` when verifying `ts share apply`.

    Output (JSON to stdout):
      [{"org", "guid", "name", "type", "principal_type", "principal_id",
        "principal_name", "permission", "shared_permission"}]

    Examples:

    \b
      ts share status <table-guid> -p prod
      ts share status <table-guid> --org ORG1 --org ORG2 --columns -p prod
      ts share status T2_PUBLISH --org ORG1 --group Analyst -p prod
    """
    targets = _status_targets(_client_for_org(profile), list(guids), columns)

    rows: List[Dict[str, Any]] = []
    for org_name in list(dict.fromkeys(org)) or [""]:
        client = _client_for_org(profile, org_name or None)
        for row in _fetch_permissions(client, targets, list(group) or None):
            rows.append({"org": org_name, **row})

    print(json.dumps(rows))
