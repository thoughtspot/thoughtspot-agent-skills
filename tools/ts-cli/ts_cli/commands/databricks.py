"""ts databricks — Databricks Metric View conversion commands.

Offline file transforms only (the `ts snowflake` precedent): the input YAML
is fetched by the skill via the external `databricks` CLI (DESCRIBE TABLE
EXTENDED) before these commands run. No Databricks HTTP client lives in
ts-cli. Pure logic lives in ts_cli/databricks/ (stdlib + PyYAML only).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(help="Databricks Metric View conversion commands (offline file transforms).")

_HTML_TAG_RE = re.compile(r"<[^>]+>")


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


@app.command("build-model")
def build_model_cmd(
    parsed_path: str = typer.Option(
        ..., "--parsed", "-p", help="parse-mv output JSON"),
    translated_path: str = typer.Option(
        ..., "--translated", "-t", help="translate-formulas output JSON"),
    tables_path: str = typer.Option(
        ..., "--tables", help="tables.json (v2 objects or plain strings)"),
    connection: str = typer.Option(
        ..., "--connection", "-c",
        help="ThoughtSpot connection display name (table TML only)"),
    model_name: str = typer.Option(
        ..., "--model-name", "-n", help="Model TML name"),
    output_dir: str = typer.Option(
        ..., "--output-dir", "-o",
        help="Directory for the generated .model.tml / .table.tml files"),
    mv_fqn: Optional[str] = typer.Option(
        None, "--mv-fqn", help="Source MV FQN for the model description"),
    spotter_enabled: Optional[bool] = typer.Option(
        None, "--spotter-enabled/--no-spotter-enabled",
        help="Stamp spotter_config; omit for no spotter_config block"),
    existing_guid: Optional[str] = typer.Option(
        None, "--existing-guid",
        help="Stamp guid: at the document root (update-in-place)"),
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Import the model TML after a clean lint"),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="With --profile: assemble+lint but skip the import"),
) -> None:
    """Assemble ThoughtSpot Model (+ Table) TML from parse-mv/translate-formulas JSON.

    Validates TML invariants + lints before any import; with --profile imports
    the model via `ts tml import --policy PARTIAL`. Summary JSON on stdout,
    diagnostics on stderr. Exit 1 on findings or import failure.
    """
    from ts_cli.databricks.mv_build_model import build_model_tml_dbx
    from ts_cli.databricks.mv_tml import validate_tml_invariants
    from ts_cli.tml_common import dump_tml_yaml
    from ts_cli.tml_lint import lint_tml

    parsed = _load_json(parsed_path, "parsed")
    translated_doc = _load_json(translated_path, "translated")
    tables = _load_json(tables_path, "tables")

    try:
        model_doc, build_info = build_model_tml_dbx(
            model_name=model_name, parsed=parsed, translated_doc=translated_doc,
            tables=tables, mv_fqn=mv_fqn, spotter_enabled=spotter_enabled,
            existing_guid=existing_guid)
    except ValueError as exc:
        typer.echo(f"cannot build model TML: {exc}", err=True)
        raise SystemExit(1)

    skipped = translated_doc.get("skipped") or []
    _echo_translate_diagnostics(build_info, skipped)

    # Zero-column guard runs before any file is written or imported (Task 5
    # review carry-over) — _build_table_docs exits 1 internally on violation.
    table_docs = _build_table_docs(tables, connection)

    invariant_findings: list[str] = []
    lint_findings: list[str] = []
    for doc in [model_doc] + table_docs:
        invariant_findings.extend(validate_tml_invariants(doc))
        lint_findings.extend(lint_tml(doc))

    model_file, table_files = _write_tml_files(
        output_dir, model_name, model_doc, table_docs, dump_tml_yaml)
    tables_entries = _table_alias_entries(tables)

    if invariant_findings or lint_findings:
        summary = _build_summary(
            model_name=model_name, model_file=model_file,
            table_files=table_files, connection=connection,
            tables_entries=tables_entries, build_info=build_info,
            skipped=skipped, spotter_enabled=spotter_enabled,
            existing_guid=existing_guid, invariant_findings=invariant_findings,
            lint_findings=lint_findings, import_status="not_requested",
            model_guid=None)
        typer.echo(json.dumps(summary))
        raise SystemExit(1)

    import_status, model_guid, import_error = _run_import(
        profile, dry_run, model_doc)

    summary = _build_summary(
        model_name=model_name, model_file=model_file,
        table_files=table_files, connection=connection,
        tables_entries=tables_entries, build_info=build_info,
        skipped=skipped, spotter_enabled=spotter_enabled,
        existing_guid=existing_guid, invariant_findings=invariant_findings,
        lint_findings=lint_findings, import_status=import_status,
        model_guid=model_guid, import_error=import_error)
    typer.echo(json.dumps(summary))
    if import_status == "failed":
        raise SystemExit(1)


def _echo_translate_diagnostics(build_info: dict, skipped: list[dict]) -> None:
    """WARNING per sparse_data_risk annotation, SKIPPED per skipped entry (stderr)."""
    for wm in build_info["window_measures"]:
        for ann in wm.get("annotations") or []:
            if ann["kind"] == "sparse_data_risk":
                typer.echo(f"WARNING: {wm['name']}: {ann['detail']}", err=True)
    for skip in skipped:
        typer.echo(f"SKIPPED {skip['role']} '{skip['name']}': {skip['reason']}",
                   err=True)


def _build_table_docs(tables: dict, connection: str) -> list[dict]:
    """Build Table TML for every `create: true` alias.

    Exits 1 (stderr) on a builder ValueError, or when a table's columns[]
    is empty after Databricks-type omissions — both before any file is
    written or imported.
    """
    from ts_cli.databricks.mv_tml import build_table_tml

    table_docs: list[dict] = []
    for alias, info in tables.items():
        if not (isinstance(info, dict) and info.get("create")):
            continue
        try:
            table_doc, notes = build_table_tml(info, connection)
        except ValueError as exc:
            typer.echo(f"cannot build table TML for '{alias}': {exc}", err=True)
            raise SystemExit(1)
        for note in notes:
            typer.echo(f"WARNING: {note}", err=True)
        if not table_doc["table"]["columns"]:
            omitted = ", ".join(c["name"] for c in info["columns"])
            typer.echo(
                f"ERROR: table '{info['name']}' has zero columns after omitting "
                f"{omitted} (unsupported Databricks type(s)) — nothing to import",
                err=True)
            raise SystemExit(1)
        table_docs.append(table_doc)
    return table_docs


def _write_tml_files(output_dir: str, model_name: str, model_doc: dict,
                     table_docs: list[dict], dump_tml_yaml) -> tuple[str, list[str]]:
    """Write the model TML + every table TML to --output-dir. Returns (model_file, table_files)."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_file = out_dir / f"{model_name}.model.tml"
    model_file.write_text(dump_tml_yaml(model_doc))
    table_files = []
    for doc in table_docs:
        t_file = out_dir / f"{doc['table']['name']}.table.tml"
        t_file.write_text(dump_tml_yaml(doc))
        table_files.append(str(t_file))
    return str(model_file), table_files


def _clean_error_message(msg: str) -> str:
    """Strip HTML tags, collapse whitespace, and cap at ~1000 chars."""
    cleaned = _HTML_TAG_RE.sub(" ", msg or "")
    cleaned = " ".join(cleaned.split())
    return cleaned[:1000]


def _extract_status_error(import_result: list) -> Optional[str]:
    """If the parsed import response carries an in-band ERROR status, return
    a cleaned error message. Returns None for OK status, an unrecognized
    shape, or an empty response list.

    Live finding, BL-063 PR4 (2026-07-10, se-thoughtspot): `ts tml import`
    can return returncode 0 with a response body carrying
    `status.status_code == "ERROR"` and a rich (HTML-laden) `error_message`
    — that error was previously swallowed, surfacing only as
    `import_status: "failed"`, `import_error: ""`.
    """
    if not import_result or not isinstance(import_result, list):
        return None
    first = import_result[0]
    if not isinstance(first, dict):
        return None
    status = (first.get("response") or {}).get("status") or {}
    if status.get("status_code") != "ERROR":
        return None
    return _clean_error_message(status.get("error_message", ""))


def _run_import(
    profile: Optional[str], dry_run: bool, model_doc: dict,
) -> tuple[str, Optional[str], Optional[str]]:
    """Run `ts tml import` for the model TML only. Returns (status, guid, error).

    stdin is always provided (BL-097: `ts tml import` hangs waiting on an open
    non-TTY stdin when no input is passed). No retry loop — a single import
    attempt.

    Error surfacing (BL-063 PR4 live e2e fix, 2026-07-10): every `failed`
    outcome now carries a non-empty `import_error` —
      (a) an in-band ERROR status (see _extract_status_error) wins first,
          even when the subprocess itself exited 0;
      (b) rc != 0 with stdout that didn't parse as JSON falls back to the
          existing stderr tail;
      (c) rc == 0 with an OK-shaped response but no extractable GUID (should
          be rare now that extract_imported_guid handles the flat response
          shape) gets a synthesized message naming the problem, with a
          response-tail excerpt for diagnosis.
    """
    if not profile:
        return "not_requested", None, None
    if dry_run:
        return "dry_run", None, None

    import shlex
    import subprocess

    from ts_cli.tml_common import extract_imported_guid

    model_tml_str = json.dumps(model_doc)
    completed = subprocess.run(
        ["bash", "-c",
         f"source ~/.zshenv && ts tml import --policy PARTIAL --profile {shlex.quote(profile)}"],
        input=json.dumps([model_tml_str]), capture_output=True, text=True)
    stderr_tail = (completed.stderr or "")[-500:]

    try:
        import_result = json.loads(completed.stdout)
    except Exception:
        import_result = None

    if import_result is not None:
        status_error = _extract_status_error(import_result)
        if status_error is not None:
            return "failed", None, status_error

    if completed.returncode != 0:
        return "failed", None, stderr_tail

    if import_result is None:
        tail = (completed.stdout or "")[-500:]
        return "failed", None, f"import response unparseable — response tail: {tail}"

    model_guid = extract_imported_guid(import_result)
    if model_guid is None:
        tail = (completed.stdout or "")[-500:]
        return "failed", None, (
            f"import response OK but no GUID found — response tail: {tail}"
        )
    return "imported", model_guid, None


def _table_alias_entries(tables: dict) -> list[dict]:
    """Per-alias summary rows for the `tables` field of the build-model summary."""
    entries = []
    for alias, info in tables.items():
        if isinstance(info, dict):
            entries.append({
                "alias": alias, "name": info.get("name"),
                "fqn": info.get("fqn"),
                "table_tml_written": bool(info.get("create")),
            })
        else:
            entries.append({
                "alias": alias, "name": info, "fqn": None,
                "table_tml_written": False,
            })
    return entries


def _build_summary(
    *, model_name: str, model_file: str, table_files: list[str], connection: str,
    tables_entries: list[dict], build_info: dict, skipped: list[dict],
    spotter_enabled: Optional[bool], existing_guid: Optional[str],
    invariant_findings: list[str], lint_findings: list[str],
    import_status: str, model_guid: Optional[str],
    import_error: Optional[str] = None,
) -> dict:
    """Assemble the build-model summary JSON — the sole stdout contract."""
    summary = {
        "model_name": model_name,
        "model_file": model_file,
        "table_files": table_files,
        "connection": connection,
        "tables": tables_entries,
        "columns": {"attributes": build_info["attributes"],
                    "measures": build_info["measures"]},
        "formula_count": build_info["formula_count"],
        "window_measures": build_info["window_measures"],
        "skipped": skipped,
        "name_renames": build_info["rename_map"],
        "filter_applied": build_info["filter_applied"],
        "spotter_enabled": spotter_enabled,
        "existing_guid": existing_guid,
        "invariant_findings": invariant_findings,
        "lint_findings": lint_findings,
        "import_status": import_status,
        "model_guid": model_guid,
    }
    if import_error is not None:
        summary["import_error"] = import_error
    return summary


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
