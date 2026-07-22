"""ts powerbi — Power BI (.pbip) -> ThoughtSpot conversion commands.

I/O + typer live here; the conversion logic is pure functions in ts_cli/powerbi/*.
Conventions (.claude/rules/ts-cli.md): structured JSON to stdout, diagnostics to stderr,
auth via --profile, connection by display name (never GUID).
"""
from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer(help="Power BI (.pbip) -> ThoughtSpot conversion commands.")


@app.command("parse")
def parse_cmd(
    pbip_dir: str = typer.Argument(..., help="Path to the .pbip project folder"),
    output_file: str = typer.Option(..., "--output", "-o", help="Output parsed JSON path"),
) -> None:
    """Parse a .pbip (TMDL semantic model + PBIR report) into structured JSON.

    Emits tables/columns/measures/relationships (from TMDL) and pages/visuals (from
    PBIR) — the inventory that ``build-model`` / ``build-liveboard`` consume. Anything
    the parser cannot confidently read is listed under ``warnings`` rather than guessed.
    """
    from ts_cli.powerbi.parsing import parse_inventory

    if not Path(pbip_dir).is_dir():
        typer.echo(f"Not a directory: {pbip_dir}", err=True)
        raise SystemExit(1)

    inv = parse_inventory(pbip_dir)
    Path(output_file).write_text(json.dumps(inv, indent=2), encoding="utf-8")

    # counts to stdout (JSON, pipeable); warnings to stderr (diagnostics)
    typer.echo(json.dumps(inv["counts"]))
    for w in inv.get("warnings", []):
        typer.echo(f"warning: {w}", err=True)


@app.command("build-model")
def build_model_cmd(
    pbip_dir: str = typer.Argument(..., help="Path to the .pbip project folder"),
    connection: str = typer.Option(..., "--connection", "-c",
                                    help="ThoughtSpot connection display name the tables bind to"),
    db: str = typer.Option(..., "--db", help="Warehouse database"),
    schema: str = typer.Option(..., "--schema", help="Warehouse schema"),
    output_dir: str = typer.Option(..., "--output", "-o", help="Output dir for .tml + mapping.json"),
    model_name: str = typer.Option(None, "--model-name", help="Name for the generated Model"),
    join_type: str = typer.Option("LEFT_OUTER", "--join-type",
                                  help="Join type for relationships (LEFT_OUTER keeps fact rows)"),
    overrides: str = typer.Option(None, "--overrides",
                                  help="overrides.json (hand-authored ts_formula / connection / table_map / parameters)"),
    lower_db_table: bool = typer.Option(False, "--lower-db-table",
                                        help="Lowercase db_table (Databricks folds unquoted names)"),
) -> None:
    """Build Table + Model TML (and mapping.json) from a .pbip. Parses the project,
    translates DAX to formulas ([formula_<name>] id-refs, topo-sorted), emits joins with
    real cardinality, honours summarizeBy for AVG-vs-SUM, and enables Spotter. Serialized
    via the shared dump_tml_yaml; the connection block carries name only (never fqn)."""
    from ts_cli.tml_common import dump_tml_yaml
    from ts_cli.powerbi.parsing import parse_inventory
    from ts_cli.powerbi.build_model import assemble

    if not Path(pbip_dir).is_dir():
        typer.echo(f"Not a directory: {pbip_dir}", err=True)
        raise SystemExit(1)

    inv = parse_inventory(pbip_dir)
    ov = json.loads(Path(overrides).read_text(encoding="utf-8")) if overrides else {}
    files, mapping = assemble(inv, ov, connection, db, schema, join_type, lower_db_table, model_name)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for fname, tml in files:
        (out / fname).write_text(dump_tml_yaml(tml), encoding="utf-8")
    (out / "mapping.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    mr = mapping["measures"]

    def _n(rows, s):
        return sum(1 for r in rows if r.get("status") == s)
    typer.echo(json.dumps({
        "tables": _n(mapping["tables"], "Migrated"), "model": 1, "measures": len(mr),
        "migrated": _n(mr, "Migrated"), "approximated": _n(mr, "Approximated"),
        "needs_review": _n(mr, "NEEDS REVIEW")}))
    for w in mapping.get("warnings", []):
        typer.echo(f"warning: {w}", err=True)


def _model_names(inv, ov, connection, db, schema, model_name):
    """Build the model in-memory (assemble mutates inv's tables, not its pages) to derive the
    (column_names, measure_names) the report spec resolves visual fields against."""
    from ts_cli.powerbi.build_model import assemble
    files, _ = assemble(inv, ov, connection or "conn", db, schema, "LEFT_OUTER",
                        lower_db_table=False, model_name=model_name)
    model = next(tml for fn, tml in files if fn.endswith(".model.tml"))["model"]
    cols = model["columns"]
    return [c["name"] for c in cols], {c["name"] for c in cols
                                       if c.get("properties", {}).get("column_type") == "MEASURE"}


@app.command("build-liveboard")
def build_liveboard_cmd(
    pbip_dir: str = typer.Argument(..., help="Path to the .pbip project folder"),
    output_dir: str = typer.Option(..., "--output", "-o", help="Directory for the emitted .liveboard.tml"),
    model_name: str = typer.Option(..., "--model-name",
                                   help="Model name the answers bind to (must match `build-model`)"),
    model_fqn: str = typer.Option(None, "--model-fqn", help="Model GUID to bind to (optional; more robust)"),
    report_name: str = typer.Option(None, "--report-name", help="Liveboard name (default: derived from model)"),
    connection: str = typer.Option("", "--connection", "-c", help="Connection name (for the in-memory model build)"),
    db: str = typer.Option("db", "--db"),
    schema: str = typer.Option("schema", "--schema"),
    overrides: str = typer.Option(None, "--overrides", help="overrides.json (explicit answers / extra_visuals)"),
) -> None:
    """Emit Answer + tabbed-Liveboard TML from a .pbip's report pages, reusing the shared
    build_from_spec (role-aware axes: Category->x, Series->color, Rows/Columns->pivot,
    measures->y; chart-needs floor; override capture-and-replay). Report pages become tabs in
    PBI pageOrder; a Tooltip page is dropped, not a tab."""
    from ts_cli.tml_common import dump_tml_yaml
    from ts_cli.tableau import liveboard as lb
    from ts_cli.powerbi.parsing import parse_inventory
    from ts_cli.powerbi.answers import spec_from_parse
    from ts_cli.powerbi.tables import _slug

    if not Path(pbip_dir).is_dir():
        typer.echo(f"Not a directory: {pbip_dir}", err=True)
        raise SystemExit(1)

    inv = parse_inventory(pbip_dir)
    ov = json.loads(Path(overrides).read_text(encoding="utf-8")) if overrides else {}
    column_names, measure_names = _model_names(inv, ov, connection, db, schema, model_name)

    spec = spec_from_parse(inv, model_name, model_fqn, column_names, measure_names, ov)
    if report_name:
        spec["report_name"] = report_name
    result = lb.build_from_spec(spec)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    lb_tml = result.get("liveboard")
    if lb_tml:
        (out / f"{_slug(spec['report_name'])}.liveboard.tml").write_text(dump_tml_yaml(lb_tml), encoding="utf-8")

    vr = result["visual_rows"]

    def _c(rows, s):
        return sum(1 for r in rows if r.get("status") == s)
    typer.echo(json.dumps({
        "report_name": spec["report_name"], "answers": len(result["answers"]),
        "tabs": sum(1 for p in result["page_rows"] if p.get("status") == "Migrated"),
        "visuals_migrated": _c(vr, "Migrated"), "approximated": _c(vr, "Approximated"),
        "needs_review": _c(vr, "NEEDS REVIEW"), "liveboard": bool(lb_tml)}))
