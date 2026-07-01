from __future__ import annotations

import json
import sys
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


@app.command("report")
def report(
    input_file: Optional[Path] = typer.Argument(
        None, help="Path to audit JSON file (omit to read from stdin)"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write HTML report to file instead of stdout"),
) -> None:
    """Render audit JSON as a self-contained HTML report."""
    from ts_cli.audit.report import render_report

    if input_file:
        if not input_file.exists():
            typer.echo(f"File not found: {input_file}", err=True)
            raise typer.Exit(1)
        raw = input_file.read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            typer.echo("No input file provided and stdin is a terminal. "
                       "Pipe audit JSON or pass a file path.", err=True)
            raise typer.Exit(1)
        raw = sys.stdin.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        typer.echo(f"Invalid JSON: {e}", err=True)
        raise typer.Exit(1)

    if "findings" not in data or "summary" not in data:
        typer.echo("Input JSON must contain 'findings' and 'summary' keys.", err=True)
        raise typer.Exit(1)

    html = render_report(data)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html, encoding="utf-8")
        size_kb = len(html.encode("utf-8")) / 1024
        typer.echo(f"Report written to {output} ({size_kb:.0f} KB)", err=True)
    else:
        print(html)
