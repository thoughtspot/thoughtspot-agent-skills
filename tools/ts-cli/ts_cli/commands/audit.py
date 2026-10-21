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


def _parse_angles(angles: Optional[str]) -> Optional[list]:
    return [a.strip().upper() for a in angles.split(",")] if angles else None


def _replay(snapshot_in: Path, angle_list: Optional[list], assessment_name: str) -> dict:
    """Audit a captured snapshot: no profile, no client, no network."""
    from ts_cli.audit import run_audit
    from ts_cli.audit.snapshot import SnapshotError, read_snapshot

    try:
        ctx, captured = read_snapshot(snapshot_in)
    except SnapshotError as exc:
        raise SystemExit(f"Cannot replay snapshot: {exc}") from exc
    missing = [a for a in (angle_list or []) if a not in captured]
    if missing:
        raise SystemExit(
            f"Angle(s) {', '.join(missing)} not captured in snapshot {snapshot_in} "
            f"(captured: {', '.join(captured) or 'none'}) — the data they read was not "
            "fetched. Re-capture with those angles, or drop them from --angles.")
    return run_audit(None, ctx.model_guids, angle_list or captured, assessment_name, ctx=ctx)


def _capture(client, models: list, angle_list: Optional[list], assessment_name: str,
             snapshot_out: Path) -> dict:
    """Fetch the audit data, write it to ``snapshot_out``, then audit it as normal."""
    from ts_cli.audit import ANGLE_MODULES, assessment, run_audit
    from ts_cli.audit.context import build_context
    from ts_cli.audit.snapshot import SnapshotError, write_snapshot

    angles = angle_list or list(ANGLE_MODULES.keys())
    ctx = build_context(client, models, angles)
    ctx.assessment = assessment.normalise(assessment_name)
    try:
        write_snapshot(ctx, snapshot_out, angles)
    except SnapshotError as exc:
        raise SystemExit(f"Cannot write snapshot: {exc}") from exc
    typer.echo(f"Snapshot written to {snapshot_out}", err=True)
    return run_audit(client, models, angles, assessment_name, ctx=ctx)


@app.command("run")
def run(
    models: Optional[List[str]] = typer.Option(
        None, "--models", "-m",
        help="One or more model GUIDs to audit (required unless --snapshot-in)"),
    profile: Optional[str] = _profile_option,
    angles: Optional[str] = typer.Option(None, "--angles", "-a",
                                          help="Comma-separated angle filter: A,D,H,P,S (default: all)"),
    assessment_name: str = typer.Option(
        "general", "--assessment",
        help="Bar the AI-readiness checks measure against: spotter (descriptions >= 95%, "
             "synonyms >= 80%, AI context required) or general (>= 50%, >= 25%, "
             "AI context recommended). Default: general"),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
                                           help="Write JSON report to file instead of stdout"),
    snapshot_out: Optional[Path] = typer.Option(
        None, "--snapshot-out",
        help="Also write the fetched audit data to this directory, for later replay"),
    snapshot_in: Optional[Path] = typer.Option(
        None, "--snapshot-in",
        help="Audit a directory written by --snapshot-out instead of fetching: needs no "
             "profile, ignores --models, and --angles defaults to the captured angles"),
) -> None:
    """Run audit checks against one or more ThoughtSpot models."""
    from ts_cli.audit import assessment, run_audit

    try:
        assessment.normalise(assessment_name)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if snapshot_in and snapshot_out:
        raise typer.BadParameter("--snapshot-in and --snapshot-out cannot be used together",
                                 param_hint="--snapshot-in / --snapshot-out")
    if not snapshot_in and not models:
        raise typer.BadParameter("required unless --snapshot-in is given",
                                 param_hint="--models")

    angle_list = _parse_angles(angles)
    if snapshot_in:
        if models:
            typer.echo("Note: --models is ignored with --snapshot-in; "
                       "the snapshot's models are audited.", err=True)
        result = _replay(snapshot_in, angle_list, assessment_name)
    else:
        client = ThoughtSpotClient(resolve_profile(profile))
        if snapshot_out:
            result = _capture(client, models, angle_list, assessment_name, snapshot_out)
        else:
            result = run_audit(client, models, angle_list, assessment_name)
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
