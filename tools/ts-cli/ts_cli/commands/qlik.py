"""ts qlik — Qlik Sense -> ThoughtSpot converter.

Mirrors the ``ts tableau`` converter's conventions: structured JSON to stdout,
progress/diagnostics to stderr, pure conversion logic in the ``ts_cli.qlik``
subpackage (this module does I/O only).

Subcommands:
  parse           .qvf / engine-artifacts dir -> structured inventory JSON
  build-model     -> Table TML(s) + Model TML + mapping.json
  build-liveboard -> Answer + tabbed Liveboard TML (one tab per Qlik sheet)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from ts_cli.qlik import answers, build_model, parsing
from ts_cli.qlik.ir import QlikApp
from ts_cli.tml_common import dump_tml_yaml

app = typer.Typer(help="Qlik Sense -> ThoughtSpot converter.")

_ALL_MODES = ("offline", "engine-artifacts", "qlik-cloud", "engine")
_OFFLINE_MODES = ("offline", "engine-artifacts")

_mode_option = typer.Option(
    "offline", "--mode",
    help="offline (default; <source> is a .qvf file) | engine-artifacts "
         "(<source> is a directory of engine-extracted JSON) | qlik-cloud "
         "(--tenant/--app-id/--api-key) | engine (--engine/--app-id/--header).",
)
_tenant_option = typer.Option(
    None, "--tenant", help="Qlik Cloud tenant URL, e.g. https://acme.us.qlikcloud.com (qlik-cloud mode).",
)
_app_id_option = typer.Option(
    None, "--app-id", help="Qlik app GUID (qlik-cloud/engine modes); qlik-cloud also accepts an app name.",
)
_api_key_option = typer.Option(
    None, "--api-key", envvar="QLIK_API_KEY",
    help="Qlik Cloud API key (default from env QLIK_API_KEY); never printed (qlik-cloud mode).",
)
_engine_option = typer.Option(
    None, "--engine", help="Qlik Engine websocket URL, e.g. wss://host/app (engine mode).",
)
_header_option = typer.Option(
    None, "--header", help="Extra websocket header 'k=v' (engine mode); repeatable.",
)


def _parse_headers(headers: Optional[list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in headers or []:
        if "=" not in h:
            typer.echo(f"Invalid --header '{h}' (expected k=v)", err=True)
            raise SystemExit(2)
        k, v = h.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _load_offline(source: Optional[str], mode: str) -> QlikApp:
    if not source:
        typer.echo(f"--mode {mode} requires a <source> path", err=True)
        raise SystemExit(2)
    if not Path(source).exists():
        typer.echo(f"Source not found: {source}", err=True)
        raise SystemExit(1)
    return parsing.parse_app(source, mode=mode)


def _load_cloud(tenant: Optional[str], app_id: Optional[str],
                api_key: Optional[str]) -> QlikApp:
    if not tenant or not app_id:
        typer.echo("qlik-cloud mode requires --tenant and --app-id", err=True)
        raise SystemExit(2)
    from ts_cli.qlik import cloud
    try:
        return cloud.extract(tenant, app_id, api_key)
    except RuntimeError as e:  # missing websocket-client extra
        typer.echo(str(e), err=True)
        raise SystemExit(1)


def _load_live_engine(engine: Optional[str], app_id: Optional[str],
                      headers: Optional[list[str]]) -> QlikApp:
    if not engine or not app_id:
        typer.echo("engine mode requires --engine and --app-id", err=True)
        raise SystemExit(2)
    from ts_cli.qlik import live_engine
    try:
        return live_engine.extract(engine, app_id, headers=_parse_headers(headers))
    except RuntimeError as e:  # missing websocket-client extra
        typer.echo(str(e), err=True)
        raise SystemExit(1)


def _apply_overrides(app_obj: QlikApp, overrides: Optional[str]) -> QlikApp:
    if not overrides:
        return app_obj
    ov_path = Path(overrides)
    if not ov_path.exists():
        typer.echo(f"Overrides file not found: {overrides}", err=True)
        raise SystemExit(1)
    patch = json.loads(ov_path.read_text())
    merged = app_obj.to_dict()
    merged.update(patch)
    typer.echo(f"Applied overrides ({len(patch)} top-level key(s))", err=True)
    return QlikApp.from_dict(merged)


def _load_app(source: Optional[str], mode: str, overrides: Optional[str], *,
              tenant: Optional[str] = None, app_id: Optional[str] = None,
              api_key: Optional[str] = None, engine: Optional[str] = None,
              headers: Optional[list[str]] = None) -> QlikApp:
    """Extract an IR from the requested source mode, then apply an optional
    --overrides patch.

    Modes: ``offline`` / ``engine-artifacts`` read the positional ``<source>``;
    ``qlik-cloud`` / ``engine`` pull live from Qlik (no positional source).
    ``--overrides`` is a JSON file whose top-level keys (app_name, connections,
    tables, measures, dimensions, variables, sheets, ...) REPLACE the extracted
    values — the hand-edit-the-IR path (dump via `parse`, fix, feed back).
    """
    if mode not in _ALL_MODES:
        typer.echo(f"Unknown --mode '{mode}' (expected {'|'.join(_ALL_MODES)})", err=True)
        raise SystemExit(2)

    if mode in _OFFLINE_MODES:
        app_obj = _load_offline(source, mode)
    elif mode == "qlik-cloud":
        app_obj = _load_cloud(tenant, app_id, api_key)
    else:  # engine
        app_obj = _load_live_engine(engine, app_id, headers)

    return _apply_overrides(app_obj, overrides)


def _emit_warnings(app_obj: QlikApp) -> None:
    for n in app_obj.notes:
        if n.severity in ("warning", "manual"):
            typer.echo(f"  [{n.severity}] {n.area}: {n.message}", err=True)


@app.command("parse")
def parse_cmd(
    source: Optional[str] = typer.Argument(None, help="Path to a .qvf file (offline) or an artifacts directory (engine-artifacts); omit for qlik-cloud/engine modes"),
    output_file: str = typer.Option(..., "--output", "-o", help="Output inventory JSON path"),
    mode: str = _mode_option,
    tenant: Optional[str] = _tenant_option,
    app_id: Optional[str] = _app_id_option,
    api_key: Optional[str] = _api_key_option,
    engine: Optional[str] = _engine_option,
    header: Optional[list[str]] = _header_option,
) -> None:
    """Parse a Qlik app into a structured inventory JSON.

    Emits {app_name, extraction_mode, connections, tables, columns, measures,
    dimensions, variables, sheets, charts, counts, warnings} to the output
    file. Prints the `counts` object to stdout; warnings go to stderr.
    """
    app_obj = _load_app(source, mode, overrides=None, tenant=tenant,
                        app_id=app_id, api_key=api_key, engine=engine,
                        headers=header)
    inventory = parsing.build_inventory(app_obj)

    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inventory, indent=2))

    typer.echo(f"Parsed {source} (mode={app_obj.extraction_mode}) -> {output_file}", err=True)
    _emit_warnings(app_obj)
    print(json.dumps(inventory["counts"]))


@app.command("build-model")
def build_model_cmd(
    source: Optional[str] = typer.Argument(None, help="Path to a .qvf file (offline) or an artifacts directory (engine-artifacts); omit for qlik-cloud/engine modes"),
    connection_name: str = typer.Option(..., "--connection", "-c", help="ThoughtSpot connection display NAME (never a GUID)"),
    db: str = typer.Option(..., "--db", help="Warehouse database for the table TML(s)"),
    schema: str = typer.Option(..., "--schema", help="Warehouse schema for the table TML(s)"),
    output_dir: str = typer.Option(..., "--output", "-o", help="Directory for output TML + mapping.json"),
    model_name: Optional[str] = typer.Option(None, "--model-name", help="Model name (default: Qlik app name)"),
    overrides: Optional[str] = typer.Option(None, "--overrides", help="JSON file whose top-level keys replace parsed IR values (hand-edited IR)"),
    types: Optional[str] = typer.Option(None, "--types", help="JSON {TABLE:{COLUMN:ts_type}} of real warehouse types to avoid type guessing"),
    mode: str = _mode_option,
    tenant: Optional[str] = _tenant_option,
    app_id: Optional[str] = _app_id_option,
    api_key: Optional[str] = _api_key_option,
    engine: Optional[str] = _engine_option,
    header: Optional[list[str]] = _header_option,
) -> None:
    """Build import-ready Table TML(s) + Model TML from a Qlik app.

    Translates Qlik master-measure expressions to ThoughtSpot formulas
    ([formula_<name>] id-refs), honours the TML invariants (db_column_name on
    every column, connection name-only, formula_id linkage), and writes a
    mapping.json. Anything not faithfully translatable is flagged NEEDS REVIEW
    in mapping.json — never silently downgraded. Prints a counts summary JSON
    to stdout.
    """
    type_overrides = None
    if types:
        t_path = Path(types)
        if not t_path.exists():
            typer.echo(f"Types file not found: {types}", err=True)
            raise SystemExit(1)
        type_overrides = json.loads(t_path.read_text())

    app_obj = _load_app(source, mode, overrides, tenant=tenant, app_id=app_id,
                        api_key=api_key, engine=engine, headers=header)
    _emit_warnings(app_obj)

    result = build_model.build_model_artifacts(
        app_obj,
        connection_name=connection_name,
        db=db,
        schema=schema,
        model_name=model_name,
        type_overrides=type_overrides,
    )

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for fname, doc in result["tables"].items():
        (out / fname).write_text(dump_tml_yaml(doc))
        typer.echo(f"  Wrote table: {out / fname}", err=True)

    model_fname = result["model"]["filename"]
    (out / model_fname).write_text(dump_tml_yaml(result["model"]["tml"]))
    typer.echo(f"  Wrote model: {out / model_fname}", err=True)

    (out / "mapping.json").write_text(json.dumps(result["mapping"], indent=2))
    typer.echo(f"  Wrote mapping: {out / 'mapping.json'}", err=True)

    nr = result["counts"]["needs_review_total"]
    if nr:
        typer.echo(f"  {nr} item(s) flagged NEEDS REVIEW — see mapping.json", err=True)

    print(json.dumps(result["counts"]))


@app.command("build-liveboard")
def build_liveboard_cmd(
    source: Optional[str] = typer.Argument(None, help="Path to a .qvf file (offline) or an artifacts directory (engine-artifacts); omit for qlik-cloud/engine modes"),
    output_dir: str = typer.Option(..., "--output", "-o", help="Directory for output Liveboard TML + mapping.json"),
    model_name: str = typer.Option(..., "--model-name", help="Name of the ThoughtSpot model the Answers query"),
    model_fqn: Optional[str] = typer.Option(None, "--model-fqn", help="GUID of the model (added as fqn on the Answer table refs)"),
    report_name: Optional[str] = typer.Option(None, "--report-name", help="Liveboard name (default: model name / Qlik app name)"),
    overrides: Optional[str] = typer.Option(None, "--overrides", help="JSON file whose top-level keys replace parsed IR values (hand-edited IR)"),
    mode: str = _mode_option,
    tenant: Optional[str] = _tenant_option,
    app_id: Optional[str] = _app_id_option,
    api_key: Optional[str] = _api_key_option,
    engine: Optional[str] = _engine_option,
    header: Optional[list[str]] = _header_option,
) -> None:
    """Build an Answer + tabbed Liveboard from a Qlik app's sheets/charts.

    One tab per Qlik sheet; each chart becomes an embedded Answer whose search
    query is assembled from its dimensions + measures. A Qlik viz type with no
    ThoughtSpot equivalent defaults to a table and is flagged NEEDS REVIEW in
    mapping.json. Prints a counts summary JSON to stdout.
    """
    app_obj = _load_app(source, mode, overrides, tenant=tenant, app_id=app_id,
                        api_key=api_key, engine=engine, headers=header)
    _emit_warnings(app_obj)

    result = answers.build_liveboard_artifacts(
        app_obj,
        model_name=model_name,
        model_fqn=model_fqn,
        report_name=report_name,
    )

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    lb_fname = result["liveboard"]["filename"]
    (out / lb_fname).write_text(dump_tml_yaml(result["liveboard"]["tml"]))
    typer.echo(f"  Wrote liveboard: {out / lb_fname}", err=True)

    (out / "liveboard_mapping.json").write_text(json.dumps(result["mapping"], indent=2))
    typer.echo(f"  Wrote mapping: {out / 'liveboard_mapping.json'}", err=True)

    nr = result["counts"]["charts_needs_review"]
    if nr:
        typer.echo(f"  {nr} chart(s) flagged NEEDS REVIEW — see liveboard_mapping.json", err=True)

    print(json.dumps(result["counts"]))
