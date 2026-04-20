"""ts tml — export and import ThoughtSpot Markup Language objects."""
from __future__ import annotations

import json
import re
import sys
from typing import List, Optional

import typer
import yaml

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="TML export and import commands.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")

# Non-printable characters that cause YAML parse errors in ThoughtSpot edoc output.
# Keeps: tab (09), LF (0A), CR (0D), printable ASCII (20-7E), NEL (85),
# non-breaking space (A0), and BMP chars up to FFFD.
_NONPRINTABLE_RE = re.compile(r'[^\x09\x0A\x0D\x20-\x7E\x85\xA0-\uFFFD]')

# Top-level keys that identify TML object types in a parsed edoc.
_TML_TYPE_KEYS = frozenset({
    "model", "table", "answer", "liveboard", "worksheet",
    "view", "pinboard", "sql_view",
})


def strip_nonprintable(text: str) -> str:
    """Remove non-printable characters from a TML edoc string before parsing."""
    return _NONPRINTABLE_RE.sub("", text)


def detect_tml_type(parsed: dict) -> str:
    """Return the TML object type from the top-level key (excluding 'guid').

    ThoughtSpot TML has exactly one top-level key that names the object type
    (e.g. 'model', 'table', 'answer'). The optional 'guid' key at document
    root is excluded from the search.

    Returns 'unknown' if no recognised type key is found.
    """
    # Prefer known type keys first for determinism
    for key in _TML_TYPE_KEYS:
        if key in parsed:
            return key
    # Fallback: first non-guid key
    for key in parsed:
        if key != "guid":
            return key
    return "unknown"


def parse_edoc(edoc: str, format: str = "YAML") -> dict:
    """Parse a TML edoc string into a Python dict.

    Strips non-printable characters before parsing. Supports YAML (default)
    and JSON formats matching the --format flag on ts tml export.

    Raises:
        yaml.YAMLError: if YAML parsing fails.
        json.JSONDecodeError: if JSON parsing fails.
    """
    cleaned = strip_nonprintable(edoc)
    if format.upper() == "JSON":
        return json.loads(cleaned)
    return yaml.safe_load(cleaned)


@app.command("export")
def export_tml(
    guids: List[str] = typer.Argument(..., help="One or more GUIDs to export"),
    profile: Optional[str] = _profile_option,
    fqn: bool = typer.Option(False, "--fqn", help="Include fully-qualified names in output"),
    associated: bool = typer.Option(False, "--associated",
                                    help="Export associated objects (e.g. tables for a model)"),
    format: str = typer.Option("YAML", "--format", "-f",
                               help="Output format: YAML or JSON"),
    parse: bool = typer.Option(False, "--parse",
                               help=(
                                   "Parse each edoc string into a structured JSON object. "
                                   "Output changes from [{edoc: '...', info: {...}}] to "
                                   "[{type: '...', guid: '...', tml: {...}, info: {...}}]. "
                                   "Handles non-printable character stripping automatically."
                               )),
) -> None:
    """Export TML for one or more objects.

    Output: JSON from POST /api/rest/2.0/metadata/tml/export.
    The response contains an array of objects with 'edoc' (the TML string)
    and metadata about each exported object.

    With --parse, each edoc is parsed from YAML (or JSON) into a structured
    object. Non-printable characters are stripped automatically. This
    eliminates the boilerplate parse loop that every skill otherwise needs.

    Examples:

    \b
      ts tml export abc-123
      ts tml export abc-123 --fqn --associated
      ts tml export abc-123 --fqn --associated --parse
      ts tml export abc-123 def-456 --format JSON
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post(
        "/api/rest/2.0/metadata/tml/export",
        json={
            "metadata": [{"identifier": g} for g in guids],
            "export_fqn": fqn,
            "export_associated": associated,
            "formattype": format,
        },
    )
    data = resp.json()

    if not parse:
        print(json.dumps(data))
        return

    result = []
    for item in data:
        edoc = item.get("edoc", "")
        info = item.get("info", {})
        obj_name = info.get("name", "unknown")
        try:
            parsed_tml = parse_edoc(edoc, format)
        except Exception as exc:
            raise SystemExit(
                f"--parse: failed to parse edoc for '{obj_name}': {exc}"
            ) from exc
        result.append({
            "type": detect_tml_type(parsed_tml),
            "guid": parsed_tml.get("guid", ""),
            "tml": parsed_tml,
            "info": info,
        })

    print(json.dumps(result))


@app.command("import")
def import_tml(
    profile: Optional[str] = _profile_option,
    policy: str = typer.Option(
        "PARTIAL", "--policy",
        help="Import policy: PARTIAL (best-effort) or ALL_OR_NONE (atomic).",
    ),
    create_new: bool = typer.Option(
        True, "--create-new/--no-create-new",
        help="Create new objects if they don't exist.",
    ),
) -> None:
    """Import TML objects. Reads a JSON array of TML strings from stdin.

    Each element in the array should be a TML string (YAML or JSON).
    Use PARTIAL policy for tables (tolerates partial failures) and
    ALL_OR_NONE for models (either the whole model works or nothing is created).

    Output: JSON from POST /api/rest/2.0/metadata/tml/import containing
    per-object status and GUIDs of created/updated objects.

    Examples:

    \b
      # Import tables (partial — some may succeed even if others fail)
      echo '["table:\\n  name: ..."]' | ts tml import --policy PARTIAL

      # Import a model (atomic — all or nothing)
      echo '["model:\\n  name: ..."]' | ts tml import --policy ALL_OR_NONE
    """
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON on stdin: {e}")

    if isinstance(payload, str):
        tmls = [payload]
    elif isinstance(payload, list):
        tmls = payload
    else:
        raise SystemExit("stdin must be a JSON string or array of TML strings.")

    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post(
        "/api/rest/2.0/metadata/tml/import",
        json={
            "metadata_tmls": tmls,
            "import_policy": policy,
            "create_new": create_new,
        },
    )
    data = resp.json()

    # ThoughtSpot often returns an empty object list despite a successful import.
    # For each OK response with no GUID, search by name and back-fill the GUID.
    items = data if isinstance(data, list) else [data]
    for item in items:
        response_block = item.get("response", {})
        status = response_block.get("status", {})
        if status.get("status_code") != "OK":
            continue
        obj_list = response_block.get("object", [])
        if obj_list and obj_list[0].get("header", {}).get("id_guid"):
            continue  # GUID already present
        # Try to recover the GUID from the TML name field
        idx = item.get("request_index", 0)
        if idx < len(tmls):
            m = re.search(r"^\s*name:\s*(.+)$", tmls[idx], re.MULTILINE)
            if m:
                obj_name = m.group(1).strip().strip("\"'")
                search_resp = client.post(
                    "/api/rest/2.0/metadata/search",
                    json={
                        "metadata": [{"type": "LOGICAL_TABLE", "name_pattern": obj_name}],
                        "record_size": 10,
                        "record_offset": 0,
                        "include_headers": True,
                    },
                )
                results = search_resp.json()
                if isinstance(results, list):
                    for r in results:
                        if r.get("metadata_name") == obj_name:
                            # Back-fill into the response structure
                            if not obj_list:
                                response_block["object"] = [{"header": {}}]
                            response_block["object"][0].setdefault("header", {})["id_guid"] = r["metadata_id"]
                            break

    print(json.dumps(data))
