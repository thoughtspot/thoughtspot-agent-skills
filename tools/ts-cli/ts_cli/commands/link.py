"""ts link — register a semantic-layer object in ThoughtSpot without converting it.

`ts link build` creates a Table over a semantic object (Snowflake Semantic View,
Databricks Metric View, Honeydew, Cube, Kyvos, …) and a thin Model that references only
that Table: no joins, no formulas. The platform owns the metric logic and generates the
SQL; ThoughtSpot carries the column roles, aggregations and search metadata.

Pure TML construction lives in `ts_cli/link_build.py`. This module does the I/O:

1. build Table + Model TML from a normalized spec (`--spec`);
2. import the Table (`metadata/tml/import`, create_new), capture its GUID;
3. import the Model with `model_tables[0].fqn` set to that GUID;
4. write Spotter instructions via `POST /api/rest/2.0/ai/instructions/set`
   (`setNLInstructions`, Beta 10.15.0.cl+). TML `model_instructions` is NOT used:
   live-verified 2026-09-28 that a TML import reports OK but persists nothing, and an
   export does not return instructions the API set (BL-030);
5. re-export the Model and report any column whose column_type/aggregation ThoughtSpot
   changed on import — coercions are silent and the import still says OK.

Always creates NEW objects. Re-run detection and keep/discard of ThoughtSpot-side edits
is parked (BL-318).

Conventions (.claude/rules/ts-cli.md): JSON to stdout, diagnostics to stderr, auth via
--profile, Org via TS_ORG.
"""
from __future__ import annotations

import json as _json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import typer
import yaml

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.link_build import (
    AGGREGATION_MODES, LinkSpecError, build_link_tml, diff_column_roles,
)

app = typer.Typer(help="Register a semantic-layer object as a ThoughtSpot Table + thin Model (no conversion).")

_IMPORT_PATH = "/api/rest/2.0/metadata/tml/import"
_EXPORT_PATH = "/api/rest/2.0/metadata/tml/export"
_INSTRUCTIONS_SET_PATH = "/api/rest/2.0/ai/instructions/set"


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _dump(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=1000)


def _json_body(resp: Any) -> Any:
    """Response JSON, or the raw text when the body is not JSON — never raises."""
    try:
        return resp.json()
    except ValueError:
        return {"raw": (resp.text or "")[:500]}


# ThoughtSpotClient.request raises SystemExit on a non-2xx response and on an exhausted
# connection retry, even with raise_for_status=False. Once the Table exists, every later
# step must convert that into a reported failure, never an exit that loses table_guid.
_POST_CREATE_ERRORS = (Exception, SystemExit)


def _import_one(client: ThoughtSpotClient, tml_text: str) -> str:
    """Import one TML document as a new object; return its GUID or raise RuntimeError."""
    from ts_cli.tml_common import extract_imported_guid, format_import_failures, tml_import_failures

    resp = client.post(_IMPORT_PATH, json={
        "metadata_tmls": [tml_text], "import_policy": "ALL_OR_NONE", "create_new": True,
    }, raise_for_status=False)
    data = _json_body(resp)
    if not resp.ok:
        raise RuntimeError(f"import returned HTTP {resp.status_code}: {_json.dumps(data)[:500]}")
    failures = tml_import_failures(data)
    if failures:
        raise RuntimeError("\n".join(format_import_failures(failures)))
    guid = extract_imported_guid(data if isinstance(data, list) else [data])
    if not guid:
        raise RuntimeError(f"import reported OK but returned no GUID: {_json.dumps(data)[:500]}")
    return guid


_EXISTING_TABLE_RE = re.compile(r"table in the TML file already exists\.\s*Existing Table GUID:\s*([0-9a-f-]{36})", re.I)


def _existing_table_guid(message: str) -> Optional[str]:
    """GUID from ThoughtSpot's 'table … already exists. Existing Table GUID: …' refusal."""
    m = _EXISTING_TABLE_RE.search(message)
    return m.group(1) if m else None


def _export_model(client: ThoughtSpotClient, guid: str) -> dict:
    resp = client.post(_EXPORT_PATH, json={
        "metadata": [{"identifier": guid}], "export_fqn": True, "edoc_format": "YAML",
    }, raise_for_status=False)
    if not resp.ok:
        raise RuntimeError(f"export returned HTTP {resp.status_code}")
    items = _json_body(resp)
    edoc = items[0].get("edoc") if isinstance(items, list) and items else None
    return yaml.safe_load(edoc) if edoc else {}


def _set_instructions(client: ThoughtSpotClient, model_guid: str, instructions: list) -> dict:
    """Write GLOBAL Spotter instructions. Never raises: a missing privilege must not undo
    an otherwise-successful link, so the outcome is reported instead."""
    try:
        resp = client.post(_INSTRUCTIONS_SET_PATH, json={
            "data_source_identifier": model_guid,
            "nl_instructions_info": [{"instructions": instructions, "scope": "GLOBAL"}],
        }, raise_for_status=False)
        body: Any = _json_body(resp) if resp.content else {}
    except _POST_CREATE_ERRORS as exc:  # noqa: BLE001 — reported, not swallowed
        return {"set": False, "error": str(exc) or type(exc).__name__}
    ok = resp.status_code == 200 and isinstance(body, dict) and body.get("success") is True
    return {"set": ok} if ok else {"set": False, "http_status": resp.status_code, "error": body}


@app.command("build")
def build(
    spec: Path = typer.Option(..., "--spec", exists=True, dir_okay=False,
                              help="Link spec JSON (connection/db/schema/db_table + columns[])."),
    aggregation: str = typer.Option(
        ..., "--aggregation",
        help="'aggregate' — every measure AGGREGATE (Snowflake SV, Databricks MV). "
             "'standard' — each measure's own SUM/COUNT_DISTINCT/… from the spec's "
             "'aggregation' or its 'expr' (Honeydew-style)."),
    model_name: str = typer.Option(..., "--model-name", help="Display name of the Model to create."),
    table_name: Optional[str] = typer.Option(
        None, "--table-name", help="ThoughtSpot Table name (default: the spec's db_table)."),
    naming: str = typer.Option(
        "humanize", "--naming",
        help="Model column names: 'humanize' (revenue_gbp → Revenue GBP) or 'raw'. "
             "A column's 'display_name' always wins."),
    default_aggregation: Optional[str] = typer.Option(
        None, "--default-aggregation",
        help="standard mode only (ignored otherwise): aggregation for measures with neither 'aggregation' nor an "
             "inferable 'expr'. Without it such measures fail the build."),
    spotter: bool = typer.Option(True, "--spotter/--no-spotter", help="Enable Spotter on the Model."),
    output_dir: Path = typer.Option(Path("."), "--output-dir", help="Where table.tml / model.tml are written."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Build and write TML only; import nothing."),
    profile: Optional[str] = typer.Option(
        None, "--profile", "-p", envvar="TS_PROFILE",
        help="Profile name (default: first profile or TS_PROFILE env var)"),
) -> None:
    """Create a Table over a semantic object and a formula-free Model on top of it.

    Output: JSON summary — counts, skipped columns, GUIDs, instructions outcome, and any
    column ThoughtSpot coerced on import.

    Examples:

    \b
      ts link build --spec spec.json --aggregation aggregate --model-name "Sales" --dry-run
      TS_ORG=1111689045 ts link build --spec spec.json --aggregation aggregate \\
          --model-name "Semantic SQL - Sales" --profile my-profile
      ts link build --spec hd.json --aggregation standard --model-name "Sales (Honeydew)"
    """
    if aggregation not in AGGREGATION_MODES:
        _err(f"--aggregation must be one of: {', '.join(AGGREGATION_MODES)}")
        raise typer.Exit(2)
    try:
        spec_doc = _json.loads(spec.read_text())
    except _json.JSONDecodeError as exc:
        _err(f"--spec is not valid JSON: {exc}")
        raise typer.Exit(2)
    try:
        table_doc, model_doc, report = build_link_tml(
            spec_doc, aggregation_mode=aggregation, model_name=model_name,
            table_name=table_name, naming=naming,
            default_aggregation=default_aggregation, spotter_enabled=spotter,
        )
    except LinkSpecError as exc:
        _err(str(exc))
        raise typer.Exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "table.tml").write_text(_dump(table_doc))
    (output_dir / "model.tml").write_text(_dump(model_doc))
    for s in report["skipped"]:
        _err(f"skipped {s['name']} ({s['data_type']}): {s['reason']}")
    for w in report["warnings"]:
        _err(f"warning: {w}")

    if dry_run:
        report["dry_run"] = True
        print(_json.dumps(report, indent=2))
        return

    client = ThoughtSpotClient(resolve_profile(profile))
    try:
        table_guid = _import_one(client, _dump(table_doc))
    except _POST_CREATE_ERRORS as exc:
        existing = _existing_table_guid(str(exc) or "")
        if existing:
            # ThoughtSpot matches a Table on connection/db/schema/db_table, not on name, so
            # a second link to the same object is refused (live-verified 2026-09-28).
            # Updating it would overwrite ThoughtSpot-side edits — parked (BL-318).
            report["existing_table_guid"] = existing
            _err(f"This semantic object is already registered as Table {existing}. "
                 f"`ts link build` only creates new objects; re-linking is not supported yet (BL-318).")
        else:
            report["error"] = f"table import failed: {type(exc).__name__}: {exc}"
            _err(f"Table import failed:\n{exc}")
        print(_json.dumps(report, indent=2))
        raise typer.Exit(1)
    report["table_guid"] = table_guid
    _err(f"Table created: {table_guid}")

    model_doc["model"]["model_tables"][0]["fqn"] = table_guid
    (output_dir / "model.tml").write_text(_dump(model_doc))
    try:
        model_guid = _import_one(client, _dump(model_doc))
    except _POST_CREATE_ERRORS as exc:
        report["error"] = f"model import failed: {type(exc).__name__}: {exc}"
        _err(f"Model import failed (Table {table_guid} was created and remains — delete it "
             f"with `ts metadata delete {table_guid}` before retrying):\n{exc}")
        print(_json.dumps(report, indent=2))
        raise typer.Exit(1)
    report["model_guid"] = model_guid
    _err(f"Model created: {model_guid}")

    if report["instructions"]:
        report["instructions_result"] = _set_instructions(client, model_guid, report["instructions"])

    try:
        report["coerced"] = diff_column_roles(model_doc, _export_model(client, model_guid))
    except _POST_CREATE_ERRORS as exc:  # noqa: BLE001 — verification is advisory
        report["coerced"] = None
        report["verify_error"] = str(exc)
    if report.get("coerced"):
        _err(f"WARNING: ThoughtSpot changed {len(report['coerced'])} column role(s) on import — see 'coerced'")

    print(_json.dumps(report, indent=2))
