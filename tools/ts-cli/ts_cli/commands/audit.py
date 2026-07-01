from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Audit ThoughtSpot models for best practices.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")


@app.command("run")
def run(
    models: List[str] = typer.Option(..., "--models", "-m",
                                     help="One or more model GUIDs to audit"),
    profile: Optional[str] = _profile_option,
    angles: Optional[str] = typer.Option(None, "--angles", "-a",
                                          help="Comma-separated angle filter: A,D,H,P,S (default: all)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
                                           help="Write JSON report to file instead of stdout"),
) -> None:
    """Run audit checks against one or more ThoughtSpot models."""
    from ts_cli.audit import run_audit

    angle_list = [a.strip().upper() for a in angles.split(",")] if angles else None
    client = ThoughtSpotClient(resolve_profile(profile))
    result = run_audit(client, models, angle_list)
    json_str = json.dumps(result, indent=2)

    if output:
        output.write_text(json_str)
        typer.echo(f"Report written to {output}", err=True)
    else:
        print(json_str)

    summary = result.get("summary", {})
    total = sum(summary.get("by_severity", {}).values())
    typer.echo(f"Audit complete: {total} finding(s) across "
               f"{summary.get('checks_run', 0)} checks", err=True)
