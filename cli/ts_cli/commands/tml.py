"""ts tml — export and import ThoughtSpot Markup Language objects."""
from __future__ import annotations

import json
import sys
from typing import List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="TML export and import commands.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")


@app.command("export")
def export_tml(
    guids: List[str] = typer.Argument(..., help="One or more GUIDs to export"),
    profile: Optional[str] = _profile_option,
    fqn: bool = typer.Option(False, "--fqn", help="Include fully-qualified names in output"),
    associated: bool = typer.Option(False, "--associated",
                                    help="Export associated objects (e.g. tables for a model)"),
    format: str = typer.Option("YAML", "--format", "-f",
                               help="Output format: YAML or JSON"),
) -> None:
    """Export TML for one or more objects.

    Output: JSON from POST /api/rest/2.0/metadata/tml/export.
    The response contains an array of objects with 'edoc' (the TML string)
    and metadata about each exported object.

    Examples:

    \b
      ts tml export abc-123
      ts tml export abc-123 --fqn --associated
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
    print(json.dumps(resp.json()))


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
    print(json.dumps(resp.json()))
