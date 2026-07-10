"""ts databricks — Databricks Metric View conversion commands.

Offline file transforms only (the `ts snowflake` precedent): the input YAML
is fetched by the skill via the external `databricks` CLI (DESCRIBE TABLE
EXTENDED) before these commands run. No Databricks HTTP client lives in
ts-cli. Pure logic lives in ts_cli/databricks/ (stdlib + PyYAML only).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

app = typer.Typer(help="Databricks Metric View conversion commands (offline file transforms).")


@app.command("parse-mv")
def parse_mv_cmd(
    yaml_file: str = typer.Argument(
        ..., help="Path to a Metric View YAML file, or '-' to read stdin"),
    output_file: str = typer.Option(
        ..., "--output", "-o", help="Output parsed JSON path"),
) -> None:
    """Parse Databricks Metric View YAML into structured JSON.

    Codifies ts-convert-from-databricks-mv SKILL.md Step 5: version routing
    (0.1/1.1 -> one shape), source-form classification, fields:/dimensions:
    alias, dimension/measure classification, joins walk, window spec (all
    five range values), materialization: pass-through, global filter:.
    Exits 1 when unsupported[] is non-empty (list on stderr; JSON still
    written). Emits a BL-098 density-check WARNING on stderr for every
    trailing/leading window measure.
    """
    from ts_cli.databricks.mv_parse import parse_metric_view

    if yaml_file == "-":
        yaml_text = sys.stdin.read()
    else:
        path = Path(yaml_file)
        if not path.exists():
            typer.echo(f"File not found: {yaml_file}", err=True)
            raise SystemExit(1)
        yaml_text = path.read_text()

    parsed = parse_metric_view(yaml_text)

    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(parsed, indent=2))

    for warning in parsed["warnings"]:
        typer.echo(f"WARNING: {warning}", err=True)
    if parsed["unsupported"]:
        typer.echo(
            f"UNSUPPORTED constructs ({len(parsed['unsupported'])}) — "
            f"parse incomplete:", err=True)
        for entry in parsed["unsupported"]:
            typer.echo(f"  - {json.dumps(entry)}", err=True)
        raise SystemExit(1)
    typer.echo(
        f"Parsed MV v{parsed['version']}: {len(parsed['dimensions'])} "
        f"dimension(s), {len(parsed['measures'])} measure(s), "
        f"{len(parsed['joins'])} top-level join(s) -> {output_file}", err=True)


@app.command("translate-formulas")
def translate_formulas_cmd(
    input_file: str = typer.Option(
        ..., "--input", "-i", help="parsed.json from ts databricks parse-mv"),
    output_file: str = typer.Option(
        ..., "--output", "-o", help="Output translated formulas JSON path"),
    tables_file: str = typer.Option(
        ..., "--tables", "-t",
        help="JSON object mapping MV alias paths to ThoughtSpot table "
             "names ('source' key required)"),
) -> None:
    """Translate parsed Metric View expressions to ThoughtSpot formulas.

    Codifies ts-convert-from-databricks-mv SKILL.md Step 6: dot-path
    resolution, the ts-databricks-formula-translation.md function map,
    conditional aggregates, LOD windows, the full window decision tree
    (post-PR-1 corrected forms), and cross-measure inlining in dependency
    order. Every dimension/measure lands in translated[] or skipped[] with
    a reason — exit 0 with skips (a reported outcome), exit 1 only on
    unreadable/invalid input. Emits a BL-098 sparse-data-risk WARNING on
    stderr for every trailing/leading window translation.
    """
    from ts_cli.databricks.mv_translate import translate_metric_view

    parsed = _load_json(input_file, "parsed input")
    tables = _load_json(tables_file, "tables map")
    try:
        result = translate_metric_view(parsed, tables)
    except ValueError as exc:
        typer.echo(f"Invalid --tables map: {exc}", err=True)
        raise SystemExit(1)

    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))

    for entry in result["translated"]:
        for ann in entry["annotations"]:
            if ann["kind"] == "sparse_data_risk":
                typer.echo(f"WARNING: {entry['name']}: {ann['detail']}", err=True)
    for skip in result["skipped"]:
        typer.echo(f"SKIPPED {skip['role']} '{skip['name']}': {skip['reason']}",
                   err=True)
    stats = result["stats"]
    typer.echo(
        f"Translated {stats['translated']}/{stats['total']} "
        f"({stats['skipped']} skipped) -> {output_file}", err=True)


def _load_json(path_str: str, label: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        typer.echo(f"{label} file not found: {path_str}", err=True)
        raise SystemExit(1)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo(f"cannot read {label} {path_str}: {exc}", err=True)
        raise SystemExit(1)
    if not isinstance(data, dict):
        typer.echo(f"{label} must be a JSON object: {path_str}", err=True)
        raise SystemExit(1)
    return data
