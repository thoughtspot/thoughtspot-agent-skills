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


def _catalog():
    from ts_cli.audit.catalog_model import load_catalog
    return load_catalog()


def _parse_angles(angles: Optional[str]) -> Optional[list]:
    """`--angles A,d` -> ["A", "D"], each a category id of the rule catalog, each once;
    a name the catalog does not know, or a selection naming nothing (`","`), is a usage
    error — not silently nothing, nor silently everything."""
    if angles is None:
        return None
    letters = list(dict.fromkeys(a.strip().upper() for a in angles.split(",") if a.strip()))
    if not letters:
        raise typer.BadParameter("no category given (use e.g. A,D, or omit --angles "
                                 "for all)", param_hint="--angles")
    known = list(_catalog().categories)
    unknown = [a for a in letters if a not in known]
    if unknown:
        raise typer.BadParameter(f"unknown categor{'y' if len(unknown) == 1 else 'ies'} "
                                 f"{', '.join(unknown)} (known: {', '.join(known)})",
                                 param_hint="--angles")
    return letters


def _assessment(name: Optional[str]) -> str:
    """The catalog profile `--assessment` names (None: the default); exits on an
    unknown one."""
    from ts_cli.audit.engine.run import resolve_profile as resolve_assessment
    try:
        return resolve_assessment(_catalog(), name)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _uncaptured(selection: list, profile: str, captured: set) -> Optional[str]:
    """Why a replay of `selection` under `profile` cannot run on data `captured`, or
    None. What the selected rules read (`requires ∪ uses`) must all have been fetched."""
    from ts_cli.audit import data_needs
    from ts_cli.audit.engine.run import selected_rules
    missing = sorted(data_needs(selection, [profile]) - captured)
    if not missing:
        return None
    catalog = _catalog()
    known = [a for a in selection if a in catalog.categories]
    readers = [r for r in selected_rules(catalog, known, profile)
               if set(missing) & (set(r.requires) | set(r.uses))]
    cats = list(dict.fromkeys(c for r in readers for c in r.categories if c in known))
    return (f"Angle(s) {', '.join(cats)} read data not captured in this snapshot: "
            f"{', '.join(missing)} (rules {', '.join(r.id for r in readers)}). "
            "Re-capture with those angles, or drop them from --angles.")


def _replay(snapshot_in: Path, angle_list: Optional[list],
            assessment_name: Optional[str]) -> dict:
    """Audit a captured snapshot: no profile, no client, no network.

    The captured assessment is used unless ``--assessment`` is given explicitly. The
    selection must read only data the snapshot captured (its manifest's `needs`, or —
    for a snapshot written before needs were recorded — what its angles fetched), which
    the audit JSON records as `corpus.fetched_needs`.
    """
    from ts_cli.audit import run_audit
    from ts_cli.audit.snapshot import SnapshotError, read_snapshot_needs

    try:
        ctx, captured, needs = read_snapshot_needs(snapshot_in)
    except SnapshotError as exc:
        raise SystemExit(f"Cannot replay snapshot: {exc}") from exc
    selection = angle_list or captured
    profile = _assessment(assessment_name if assessment_name is not None else ctx.assessment)
    why = _uncaptured(selection, profile, needs)
    if why:
        raise SystemExit(f"{why} (snapshot: {snapshot_in})")
    if assessment_name is not None and profile != _assessment(ctx.assessment):
        typer.echo(f"Note: --assessment {profile} overrides the "
                   f"snapshot's captured assessment ({ctx.assessment}).", err=True)
    return run_audit(None, ctx.model_guids, selection, assessment_name, ctx=ctx,
                     fetched_needs=needs)


def _capture(client, models: list, angle_list: Optional[list], assessment_name: Optional[str],
             snapshot_out: Path) -> dict:
    """Fetch the audit data, write it to ``snapshot_out``, then audit it as normal."""
    from ts_cli.audit import data_needs, run_audit
    from ts_cli.audit.context import ALWAYS_FETCHED
    from ts_cli.audit.context import build_context
    from ts_cli.audit.snapshot import SnapshotError, write_snapshot

    angles = angle_list or list(_catalog().categories)
    # Every profile's needs (a replay may pass a different --assessment); the manifest
    # records them so a replay can refuse what is missing.
    needs = data_needs(angles)
    ctx = build_context(client, models, needs)
    ctx.assessment = _assessment(assessment_name)
    try:
        write_snapshot(ctx, snapshot_out, angles, needs=needs)
    except SnapshotError as exc:
        raise SystemExit(f"Cannot write snapshot: {exc}") from exc
    typer.echo(f"Snapshot written to {snapshot_out}", err=True)
    return run_audit(client, models, angles, assessment_name, ctx=ctx,
                     fetched_needs=set(needs) | ALWAYS_FETCHED)


@app.command("run")
def run(
    models: Optional[List[str]] = typer.Option(
        None, "--models", "-m",
        help="One or more model GUIDs to audit (required unless --snapshot-in)"),
    profile: Optional[str] = _profile_option,
    angles: Optional[str] = typer.Option(
        None, "--angles", "-a",
        help="Comma-separated categories of the rule catalog: A,D,H,P,S (default: all)"),
    assessment_name: Optional[str] = typer.Option(
        None, "--assessment",
        help="Assessment profile of the rule catalog the rules measure against: spotter "
             "(descriptions >= 95%, synonyms >= 80%, AI context required) or general "
             "(>= 50%, >= 25%, AI context recommended). Default: general; with "
             "--snapshot-in, the assessment the snapshot was captured with"),
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
    """Run the audit rule catalog against one or more ThoughtSpot models."""
    from ts_cli.audit import run_audit

    if assessment_name is not None:
        _assessment(assessment_name)
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
