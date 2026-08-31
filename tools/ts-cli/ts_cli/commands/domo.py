"""ts domo — Domo → ThoughtSpot offline file transforms.

All I/O lives here; the ts_cli.domo package is pure (dicts in/out).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(help="Domo → ThoughtSpot conversion from a captured offline bundle.")

_MODE_HELP = "Extraction mode. Only 'offline' is implemented."


def _echo_parse_notes(app_ir) -> None:
    """Print parser notes to stderr.

    `parse_app` swallows an unreadable dataset file into `app.notes`, and neither build
    command ever printed them — so corrupting one dataset file gave exit 0, no warning,
    and cards silently bound to the other table's columns.
    """
    notes = list(getattr(app_ir, "notes", []) or [])
    if not notes:
        return
    typer.echo(f"  {len(notes)} parser note(s) — read these before trusting the output:",
               err=True)
    for n in notes:
        msg = getattr(n, "message", None) or str(n)
        area = getattr(n, "area", "") or ""
        sev = (getattr(n, "severity", "") or "note").upper()
        typer.echo(f"    - [{sev}] {area}: {msg}".replace(": :", ":"), err=True)


def _check_mode(mode: str) -> str:
    """Reject any mode other than offline.

    `parse_app` ignores `mode` but stored it, and the report prints it as
    **Source mode**, so `--mode domo-cloud` produced a customer-facing document
    claiming a live extraction that never happened. A live path is not wired up at
    all (see the skill's references/open-items.md #3, #4), so the value is refused
    rather than recorded.
    """
    if (mode or "").strip().lower() != "offline":
        typer.echo(
            f"Unsupported --mode {mode!r}. Only 'offline' is implemented: a Domo card's "
            "analyzer query is not reachable from any Domo API, so there is no live "
            "conversion path (see the ts-convert-from-domo skill, references/"
            "open-items.md #3/#4). Capture a bundle and pass the directory.",
            err=True)
        raise typer.Exit(2)
    return "offline"


@app.command("signin")
def signin_cmd(
    profile: Optional[str] = typer.Option(None, "--profile", "-p",
        help="Domo profile name (see /ts-profile-domo). Omit if only one is configured."),
) -> None:
    """Verify a Domo profile's developer token by making two authenticated calls.

    Never prints the token. Reports what the token can actually reach, which is the
    thing worth knowing: the internal endpoints are undocumented and scope-dependent.
    """
    from ts_cli.domo.client import DomoError, client_from_profile

    client = client_from_profile(profile)
    result: dict = {"instance": client.base, "reachable": {}}
    for label, call in (("datasets", client.list_datasets), ("pages", client.list_pages)):
        try:
            result["reachable"][label] = len(call())
        except DomoError as e:
            result["reachable"][label] = f"FAILED: {e}"
    ok = any(isinstance(v, int) for v in result["reachable"].values())
    result["ok"] = ok
    print(json.dumps(result, indent=2))
    if not ok:
        raise typer.Exit(1)


@app.command("parse")
def parse_cmd(
    input_dir: str = typer.Argument(..., help="Directory of exported Domo JSON"),
    output_file: str = typer.Option(..., "--output", "-o", help="Output inventory JSON path"),
    mode: str = typer.Option("offline", "--mode", help=_MODE_HELP),
) -> None:
    from ts_cli.domo.parsing import build_inventory, parse_app

    app_ir = parse_app(input_dir, mode=_check_mode(mode))
    _echo_parse_notes(app_ir)
    inv = build_inventory(app_ir)
    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inv, indent=2))
    typer.echo(f"Parsed {inv['counts']} → {output_file}", err=True)
    print(json.dumps(inv["counts"], indent=2))


@app.command("build-model")
def build_model_cmd(
    input_dir: str = typer.Argument(..., help="Directory of exported Domo JSON"),
    connection_name: str = typer.Option(..., "--connection", "-c", help="TS connection name"),
    database: str = typer.Option(..., "--database", help="Warehouse database"),
    schema: str = typer.Option(..., "--schema", help="Warehouse schema"),
    model_name: Optional[str] = typer.Option(None, "--model-name", "-m"),
    output_dir: str = typer.Option("out", "--output-dir", "-o"),
    mode: str = typer.Option("offline", "--mode", help=_MODE_HELP),
    etl: Optional[str] = typer.Option(None, "--etl",
        help="Domo Magic ETL export JSON — drives model joins from the dataflow's join graph"),
) -> None:
    from ts_cli.domo.build_model import build_model_artifacts
    from ts_cli.domo.parsing import parse_app
    from ts_cli.tml_common import dump_tml_yaml

    app_ir = parse_app(input_dir, mode=_check_mode(mode))
    _echo_parse_notes(app_ir)
    explicit_joins = None
    if etl:
        from ts_cli.domo.magic_etl import parse_etl
        etl_path = Path(etl)
        if not etl_path.is_file():
            typer.echo(f"Magic ETL export not found: {etl}", err=True)
            raise typer.Exit(2)
        parsed = parse_etl(json.loads(etl_path.read_text()))
        explicit_joins = parsed["joins"]
        for note in parsed.get("notes", []):
            typer.echo(f"  ETL note: {note}", err=True)
        typer.echo(f"Using {len(explicit_joins)} join(s) from Magic ETL {etl}", err=True)
    arts = build_model_artifacts(
        app_ir, connection_name=connection_name, db=database, schema=schema,
        model_name=model_name, explicit_joins=explicit_joins)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for fn, doc in arts["tables"].items():
        (out / fn).write_text(dump_tml_yaml(doc))
    (out / arts["model"]["filename"]).write_text(dump_tml_yaml(arts["model"]["tml"]))
    (out / "mapping.json").write_text(json.dumps(arts["mapping"], indent=2))
    for w in arts["mapping"].get("join_warnings", []):
        typer.echo(f"  NEEDS REVIEW: {w}", err=True)
    typer.echo(f"Model artifacts → {output_dir}", err=True)
    print(json.dumps({"counts": arts["counts"], "model": arts["model"]["filename"]}, indent=2))


@app.command("report")
def report_cmd(
    output_dir: str = typer.Option("out", "--output-dir", "-o",
        help="Dir holding mapping.json (+ liveboard_mapping.json) from build-model/build-liveboard"),
    output_file: Optional[str] = typer.Option(None, "--output",
        help="Report path (default: <output-dir>/migration_report.md)"),
) -> None:
    """Render a Markdown migration report from the build mappings."""
    from ts_cli.domo.report import render_report

    out = Path(output_dir)
    mapping_path = out / "mapping.json"
    if not mapping_path.is_file():
        typer.echo(
            f"No mapping.json in {output_dir}. Run `ts domo build-model` first "
            "(and `ts domo build-liveboard` to include the cards).", err=True)
        raise typer.Exit(2)
    mapping = json.loads(mapping_path.read_text())
    lb_path = out / "liveboard_mapping.json"
    lb = json.loads(lb_path.read_text()) if lb_path.exists() else None
    md = render_report(mapping, lb)
    dest = Path(output_file) if output_file else (out / "migration_report.md")
    dest.write_text(md)
    typer.echo(f"Migration report → {dest}", err=True)
    print(str(dest))


@app.command("build-liveboard")
def build_liveboard_cmd(
    input_dir: str = typer.Argument(..., help="Directory of exported Domo JSON"),
    model_name: str = typer.Option(..., "--model-name", "-m", help="TS Model name to bind to"),
    model_fqn: Optional[str] = typer.Option(None, "--model-fqn", help="TS Model GUID (optional)"),
    report_name: Optional[str] = typer.Option(None, "--report-name"),
    output_dir: str = typer.Option("out", "--output-dir", "-o"),
    mode: str = typer.Option("offline", "--mode", help=_MODE_HELP),
) -> None:
    from ts_cli.domo.answers import build_liveboard_artifacts
    from ts_cli.domo.naming import bundle_digest, index_from_dict
    from ts_cli.domo.parsing import parse_app
    from ts_cli.tml_common import dump_tml_yaml

    app_ir = parse_app(input_dir, mode=_check_mode(mode))
    _echo_parse_notes(app_ir)

    # Bind against the namespace `build-model` resolved, rather than re-deriving it.
    # Re-deriving is deterministic but cannot detect that the bundle changed between
    # the two commands, which is how an Answer ends up bound to another layout's Model.
    index = None
    mapping_path = Path(output_dir) / "mapping.json"
    if mapping_path.is_file():
        prior = json.loads(mapping_path.read_text())
        digest = bundle_digest(app_ir)
        if prior.get("bundle_digest") and prior["bundle_digest"] != digest:
            typer.echo(
                f"mapping.json in {output_dir} was built from a different bundle "
                f"({prior['bundle_digest']} != {digest}). Re-run `ts domo build-model` "
                "against this bundle — binding Answers to a stale Model would produce "
                "wrong numbers, not an error.", err=True)
            raise typer.Exit(2)
        if prior.get("name_index"):
            index = index_from_dict(prior["name_index"])
    if index is None:
        typer.echo(
            "  NOTE: no resolved name index found — re-deriving it from the bundle. "
            "Run `ts domo build-model` into the same --output-dir first so both stages "
            "provably share one namespace.", err=True)

    arts = build_liveboard_artifacts(
        app_ir, model_name=model_name, model_fqn=model_fqn, report_name=report_name,
        index=index)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / arts["liveboard"]["filename"]).write_text(dump_tml_yaml(arts["liveboard"]["tml"]))
    (out / "liveboard_mapping.json").write_text(json.dumps(arts["mapping"], indent=2))
    typer.echo(f"Liveboard → {output_dir}", err=True)
    print(json.dumps({"counts": arts["counts"], "liveboard": arts["liveboard"]["filename"]}, indent=2))
