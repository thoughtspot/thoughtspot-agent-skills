"""ts snowflake — deterministic helpers shared by the Snowflake conversion skills.

BL-063 codification quick wins (2026-07-03 audit, codification review rows 3 & 4):
`diff` and `lint-ddl` extract inline Python that both ts-convert-to-snowflake-sv and
ts-convert-from-snowflake-sv previously copy-pasted into their SKILL.md files. Pure
logic lives in `ts_cli.snowflake_ops` (no I/O); this module is the CLI/file-I/O shell.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

import typer

from ts_cli.snowflake_ops import (
    compute_change_set,
    json_safe_value,
    lint_sv_ddl,
    parse_var_assignment,
    substitute_sql_vars,
)

app = typer.Typer(help="Snowflake Semantic View conversion helper commands.")


def _read_json_file(path_str: str, flag: str) -> dict:
    p = Path(path_str)
    if not p.is_file():
        raise SystemExit(f"{flag} path does not exist or is not a file: {path_str}")
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON in {flag} file '{path_str}': {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"{flag} file '{path_str}' must contain a JSON object.")
    return data


@app.command("diff")
def diff_cmd(
    current: str = typer.Option(
        ..., "--current",
        help="Path to a JSON file describing the CURRENT column map.",
    ),
    new: str = typer.Option(
        ..., "--new",
        help="Path to a JSON file describing the NEW column map.",
    ),
    ignore_empty_new_description: bool = typer.Option(
        False, "--ignore-empty-new-description",
        help=(
            "Only flag a description change when the NEW description is non-empty "
            "(from-side behaviour: a blank new description means 'no opinion', not "
            "'clear the field'). Default: flag any difference, including a new "
            "description going blank (to-side behaviour)."
        ),
    ),
) -> None:
    """Diff two Semantic-View-adjacent column maps and print a change set.

    Both `--current` and `--new` are JSON files shaped:

    \b
      {
        "COLUMN_NAME": {
          "expr": "SQL or ThoughtSpot formula text",
          "description": "optional",
          "synonyms": ["optional", "list"]
        },
        ...
      }

    `expr` is compared with a stash-then-normalise algorithm that survives
    whitespace/case differences while preserving double-quoted SQL identifiers and
    ThoughtSpot `[bracket]`/`{brace}` references verbatim — so it works whether the
    two sides are SQL expressions or already-translated ThoughtSpot formula text.
    Any translation from SQL to ThoughtSpot formula (or vice versa) must happen
    BEFORE the column maps are written to these files — this command only compares
    whatever expression text it is given, it does not translate.

    `description`/`synonyms` are optional per column entry. `modified_synonyms` is
    only computed for a column when BOTH sides supply a "synonyms" key — a column
    map that never tracks synonyms naturally produces an empty `modified_synonyms`
    list.

    Output: the change_set JSON to stdout —
    `{new_columns, removed_columns, modified_expressions, modified_descriptions,
    modified_synonyms}`. Diagnostic counts go to stderr.

    Examples:

    \b
      ts snowflake diff --current existing_sv_cols.json --new generated_sv_cols.json
      ts snowflake diff --current model_cols.json --new sv_cols_translated.json \\
        --ignore-empty-new-description
    """
    current_data = _read_json_file(current, "--current")
    new_data = _read_json_file(new, "--new")

    change_set = compute_change_set(
        current_data, new_data, ignore_empty_new_description=ignore_empty_new_description,
    )

    print(
        f"  new_columns:           {len(change_set['new_columns'])}\n"
        f"  removed_columns:       {len(change_set['removed_columns'])}\n"
        f"  modified_expressions:  {len(change_set['modified_expressions'])}\n"
        f"  modified_descriptions: {len(change_set['modified_descriptions'])}\n"
        f"  modified_synonyms:     {len(change_set['modified_synonyms'])}",
        file=sys.stderr,
    )
    print(json.dumps(change_set))


@app.command("lint-ddl")
def lint_ddl_cmd(
    file: Optional[str] = typer.Argument(
        None,
        help="Path to a .sql file containing the CREATE SEMANTIC VIEW DDL. Reads stdin if omitted.",
    ),
) -> None:
    """Lint a `CREATE SEMANTIC VIEW` DDL string for the deterministic subset of the
    ts-convert-to-snowflake-sv Step 11 checklist — the structural checks with no
    semantic judgment involved (identifier validity, duplicate aliases, undeclared
    table references, metric-alias ordering, leftover untranslatable placeholders,
    a likely-unescaped quote in a comment= value). Everything else on that checklist
    (aggregation shape, LOD/window base-metric-alias correctness, CA-extension-JSON
    category placement, reserved-word quoting, etc.) still needs manual review — see
    the skill's Step 11 for the full list.

    No ThoughtSpot or Snowflake connection needed; pure local structural check.

    Output: a JSON array of findings to stdout —
    `[{"severity": "error"|"warning", "check": "<slug>", "message": str, "detail": str}, ...]`.
    A human-readable summary goes to stderr.

    Exit code is 1 if any `error`-severity finding is present, else 0 — so it
    composes with `&&` to gate on a clean lint before creating the view.

    Examples:

    \b
      ts snowflake lint-ddl generated_sv.sql
      cat generated_sv.sql | ts snowflake lint-ddl
      ts snowflake lint-ddl generated_sv.sql && echo "clean, proceeding"
    """
    if file is not None:
        p = Path(file)
        if not p.is_file():
            raise SystemExit(f"FILE path does not exist or is not a file: {file}")
        ddl_text = p.read_text()
    else:
        ddl_text = sys.stdin.read()

    findings = lint_sv_ddl(ddl_text)
    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]

    if findings:
        print(f"  {len(errors)} error(s), {len(warnings)} warning(s):", file=sys.stderr)
        for f in findings:
            print(f"  [{f['severity'].upper()}] {f['check']}: {f['message']}", file=sys.stderr)
    else:
        print("  clean — no findings", file=sys.stderr)

    print(json.dumps(findings))
    raise SystemExit(1 if errors else 0)


# ---------------------------------------------------------------------------
# ts snowflake exec — run a .sql template (or inline query) against a profile
# (BL-079). SQL lives in references/*.sql files instead of markdown fences the
# LLM retypes each run; `--var` fills `{placeholder}` tokens deterministically.
# ---------------------------------------------------------------------------


def _exec_python(profile: dict, sql: str, warehouse: Optional[str],
                 role: Optional[str]) -> list[dict]:
    """Execute a (possibly multi-statement) SQL script via snowflake.connector,
    reusing load.py's canonical connector so the connect logic never drifts.

    Returns one result-set dict per statement: {"rows": [ {col: val}, ... ]}.
    Statements run in file order and stop at the first error (so a dependent UDF
    is not created after the function it references failed)."""
    # Imported here (not at module top) so `ts snowflake diff`/`lint-ddl` do not
    # pay for the load module — and to keep the "reuse the load connector" wiring
    # explicit at the one call site that needs it.
    from ts_cli.commands.load import _connect_python

    conn = _connect_python(profile, warehouse, role)
    results: list[dict] = []
    try:
        for cur in conn.execute_string(sql):
            if cur.description:
                cols = [c[0] for c in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            else:
                rows = []
            results.append({"rows": rows})
    finally:
        conn.close()
    return results


def _exec_cli(cli_connection: str, sql: str) -> list[dict]:
    """Execute a SQL script via `snow sql -f` (method: cli profiles). The file
    path avoids shell-quoting issues with `$$`-delimited UDF bodies. Returns the
    result set snow emits as JSON, wrapped as a single-element results list."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as f:
        f.write(sql)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ["snow", "sql", "-c", cli_connection, "--format", "json", "-f", tmp_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise SystemExit(
                "snow sql failed:\n"
                + (result.stderr.strip() or result.stdout.strip()
                   or "(no error detail — try `snow sql --debug`)")
            )
        out = result.stdout.strip()
        if not out:
            return [{"rows": []}]
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            # snow emitted non-JSON status text (e.g. DDL confirmations) — pass
            # it through as a diagnostic rather than pretending it was rows.
            print(out, file=sys.stderr)
            return [{"rows": []}]
        rows = parsed if isinstance(parsed, list) else [parsed]
        return [{"rows": rows}]
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _resolve_exec_sql(file: Optional[str], query: Optional[str]) -> str:
    """Resolve the SQL text from exactly one of --file / --query / stdin, or exit
    with a clear message on ambiguity/emptiness."""
    if file is not None and query is not None:
        raise SystemExit("Pass only one of --file / --query.")
    if file is not None:
        p = Path(file)
        if not p.is_file():
            raise SystemExit(f"--file path does not exist or is not a file: {file}")
        sql = p.read_text(encoding="utf-8")
    elif query is not None:
        sql = query
    else:
        sql = sys.stdin.read()
    if not sql.strip():
        raise SystemExit("No SQL provided (empty --file / --query / stdin).")
    return sql


def _resolve_exec_vars(var: Optional[List[str]]) -> dict[str, str]:
    """Parse repeatable `--var name=value` into a dict, exiting on a malformed one."""
    variables: dict[str, str] = {}
    for assignment in (var or []):
        try:
            k, v = parse_var_assignment(assignment)
        except ValueError as e:
            raise SystemExit(str(e))
        variables[k] = v
    return variables


@app.command("exec")
def exec_cmd(
    file: Optional[str] = typer.Option(
        None, "--file", "-f",
        help="Path to a .sql file to execute. Reads stdin if neither --file nor --query is given.",
    ),
    query: Optional[str] = typer.Option(
        None, "--query", "-q",
        help="Inline SQL to execute (mutually exclusive with --file).",
    ),
    sf_profile: str = typer.Option(
        ..., "--sf-profile",
        help="Snowflake profile name from ~/.claude/snowflake-profiles.json.",
    ),
    var: Optional[List[str]] = typer.Option(
        None, "--var",
        help="Placeholder substitution as name=value (repeatable). Fills {name} tokens in the SQL.",
    ),
    warehouse: Optional[str] = typer.Option(
        None, "--warehouse", "-w", help="Warehouse (default: profile default_warehouse).",
    ),
    role: Optional[str] = typer.Option(
        None, "--role", "-r", help="Role (default: profile default_role).",
    ),
) -> None:
    """Execute a .sql template (or inline query) against a Snowflake profile.

    SQL is read from `--file`, `--query`, or stdin (exactly one). `{name}`
    placeholders are filled from `--var name=value` (repeatable) before
    execution; any placeholder left without a value aborts the run rather than
    shipping a literal `{target_schema}` to Snowflake. Statements run in order
    and stop at the first error.

    Works with both profile methods: `python` reuses the shared snowflake.connector
    connector (so credentials never drift from `ts load`), `cli` shells to
    `snow sql -f`.

    Output: JSON to stdout — `{"profile", "method", "statement_count", "results":
    [{"rows": [...]}, ...], "rows": <last result set's rows>}`. The top-level
    `rows` is a convenience for single-query verifies. Diagnostics go to stderr.

    Examples:

    \b
      ts snowflake exec -f references/business-day-udfs.sql --sf-profile PROD \\
        --var target_db=ANALYTICS --var target_schema=PUBLIC
      ts snowflake exec -q "SELECT ANALYTICS.PUBLIC.get_business_days_clamped(
        '2026-01-05'::TIMESTAMP, '2026-01-09'::TIMESTAMP, FALSE)" --sf-profile PROD
    """
    sql = _resolve_exec_sql(file, query)
    variables = _resolve_exec_vars(var)

    try:
        sql = substitute_sql_vars(sql, variables)
    except ValueError as e:
        raise SystemExit(str(e))

    # load.py owns profile resolution — reuse it rather than re-reading the JSON.
    from ts_cli.commands.load import load_snowflake_profile

    profile = load_snowflake_profile(sf_profile)
    method = profile.get("method", "python")

    if method == "cli":
        cli_conn = profile.get("cli_connection")
        if not cli_conn:
            raise SystemExit(
                f"Profile '{sf_profile}' has method: cli but no 'cli_connection' field."
            )
        print(f"  Executing against {sf_profile} (method: cli)...", file=sys.stderr)
        results = _exec_cli(cli_conn, sql)
    else:
        wh = warehouse or profile.get("default_warehouse")
        rl = role or profile.get("default_role")
        print(f"  Executing against {sf_profile} (method: python)...", file=sys.stderr)
        results = _exec_python(profile, sql, wh, rl)

    output = {
        "profile": sf_profile,
        "method": method,
        "statement_count": len(results),
        "results": results,
        "rows": results[-1]["rows"] if results else [],
    }
    # default=json_safe_value coerces Decimal/datetime/bytes the connector returns
    # for NUMBER/temporal/BINARY columns (native JSON types never reach it).
    print(json.dumps(output, indent=2, default=json_safe_value))


@app.command("parse-sv")
def parse_sv_cmd(
    ddl_file: str = typer.Argument(
        ..., help="Path to a Semantic View DDL file, or '-' to read stdin"),
    output_file: str = typer.Option(
        ..., "--output", "-o", help="Output parsed JSON path"),
) -> None:
    """Parse Snowflake Semantic View DDL into structured JSON.

    Codifies ts-convert-from-snowflake-sv SKILL.md Step 4: view identity,
    tables (aliases, PKs, range constraints, subqueries), relationships
    (equi/range/asof), dimensions, metrics (semi-additive, window, USING),
    facts, custom instructions, verified queries, extension JSON.
    Exits 1 when unsupported[] is non-empty (list on stderr; JSON still
    written). Emits BL-100 prerequisite warnings for sample_values/is_enum.
    """
    from ts_cli.sv_parse import parse_sv_ddl

    if ddl_file == "-":
        ddl_text = sys.stdin.read()
    else:
        path = Path(ddl_file)
        if not path.exists():
            typer.echo(f"File not found: {ddl_file}", err=True)
            raise SystemExit(1)
        ddl_text = path.read_text()

    parsed = parse_sv_ddl(ddl_text)

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

    dim_count = len(parsed["dimensions"])
    met_count = len(parsed["metrics"])
    fact_count = len(parsed["facts"])
    rel_count = len(parsed["relationships"])
    typer.echo(
        f"Parsed SV '{parsed['name']}': {dim_count} dimension(s), "
        f"{met_count} metric(s), {fact_count} fact(s), "
        f"{rel_count} relationship(s) -> {output_file}", err=True)


@app.command("translate-formulas")
def translate_formulas_cmd(
    input_file: str = typer.Option(
        ..., "--input", "-i", help="Parsed SV JSON from parse-sv"),
    output_file: str = typer.Option(
        ..., "--output", "-o", help="Output translated JSON path"),
) -> None:
    """Translate Snowflake SQL formulas from parsed SV to ThoughtSpot syntax.

    Takes the JSON output of `ts snowflake parse-sv` and translates all
    dimension, fact, and metric expressions from Snowflake SQL to
    ThoughtSpot formula syntax. Codifies ts-convert-from-snowflake-sv
    SKILL.md Step 9 (formula translation).
    """
    from ts_cli.sv_translate import translate_sv_formulas

    path = Path(input_file)
    if not path.exists():
        typer.echo(f"File not found: {input_file}", err=True)
        raise SystemExit(1)
    parsed = json.loads(path.read_text())

    result = translate_sv_formulas(parsed)

    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))

    stats = result["stats"]
    typer.echo(
        f"Translated {stats['translated']}/{stats['total']} formulas "
        f"({stats['skipped']} skipped) -> {output_file}", err=True)
    if result["skipped"]:
        typer.echo("Skipped:", err=True)
        for s in result["skipped"]:
            typer.echo(f"  - {s['name']} ({s['block']}): {s['reason']}",
                       err=True)
    print(json.dumps(stats, indent=2))


@app.command("build-model")
def build_model_cmd(
    parsed_path: str = typer.Option(
        ..., "--parsed", "-p", help="parse-sv output JSON"),
    translated_path: str = typer.Option(
        ..., "--translated", "-t", help="translate-formulas output JSON"),
    tables_path: str = typer.Option(
        ..., "--tables", help="JSON object mapping SV alias -> TS table name/info"),
    model_name: str = typer.Option(
        ..., "--model-name", "-n", help="Model TML name"),
    output_dir: str = typer.Option(
        ..., "--output-dir", "-o",
        help="Directory for the generated .model.tml file"),
    sv_fqn: Optional[str] = typer.Option(
        None, "--sv-fqn", help="Source SV FQN for the model description"),
    spotter_enabled: Optional[bool] = typer.Option(
        None, "--spotter-enabled/--no-spotter-enabled",
        help="Stamp spotter_config; omit for no spotter_config block"),
    existing_guid: Optional[str] = typer.Option(
        None, "--existing-guid",
        help="Stamp guid: at the document root (update-in-place; skips phase 1)"),
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Import the model TML after a clean lint"),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="With --profile: assemble+lint but skip the import"),
) -> None:
    """Assemble ThoughtSpot Model TML from parse-sv/translate-formulas JSON.

    Validates TML invariants + lints before any import. With --profile,
    imports the model via a two-pass flow: phase 1 imports structure only
    (no formulas), captures the GUID, then phase 2 imports the full model
    with formulas using the captured GUID. If --existing-guid is provided,
    skips phase 1 (update-in-place). Summary JSON on stdout, diagnostics
    on stderr. Exit 1 on findings or import failure.
    """
    from ts_cli.sv_build_model import build_model_tml_sv, strip_formulas
    from ts_cli.tml_common import dump_tml_yaml
    from ts_cli.tml_lint import lint_tml

    parsed = _read_json_file(parsed_path, "--parsed")
    translated_doc = _read_json_file(translated_path, "--translated")
    tables = _read_json_file(tables_path, "--tables")

    try:
        model_doc, build_info = build_model_tml_sv(
            model_name=model_name, parsed=parsed, translated_doc=translated_doc,
            tables=tables, sv_fqn=sv_fqn, spotter_enabled=spotter_enabled,
            existing_guid=existing_guid)
    except ValueError as exc:
        typer.echo(f"cannot build model TML: {exc}", err=True)
        raise SystemExit(1)

    skipped = translated_doc.get("skipped") or []
    for skip in skipped:
        typer.echo(f"SKIPPED {skip.get('block', '?')} '{skip['name']}': "
                   f"{skip['reason']}", err=True)

    lint_findings: list[str] = lint_tml(model_doc)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_file = out_dir / f"{model_name}.model.tml"
    model_file.write_text(dump_tml_yaml(model_doc))

    if lint_findings:
        for f in lint_findings:
            typer.echo(f"LINT: {f}", err=True)
        summary = _build_model_summary(
            model_name=model_name, model_file=str(model_file),
            build_info=build_info, skipped=skipped,
            spotter_enabled=spotter_enabled, existing_guid=existing_guid,
            lint_findings=lint_findings, import_status="not_imported",
            model_guid=None)
        print(json.dumps(summary))
        raise SystemExit(1)

    import_status, model_guid, import_error = _run_sv_import(
        profile, dry_run, model_doc, build_info, existing_guid)

    summary = _build_model_summary(
        model_name=model_name, model_file=str(model_file),
        build_info=build_info, skipped=skipped,
        spotter_enabled=spotter_enabled, existing_guid=existing_guid,
        lint_findings=lint_findings, import_status=import_status,
        model_guid=model_guid, import_error=import_error)
    print(json.dumps(summary))
    if import_status == "failed":
        raise SystemExit(1)


def _run_sv_import(
    profile: Optional[str], dry_run: bool, model_doc: dict,
    build_info: dict, existing_guid: Optional[str],
) -> tuple[str, Optional[str], Optional[str]]:
    """Two-pass import for SV models.

    Phase 1: structure only (no formulas) → captures GUID.
    Phase 2: full model with formulas + captured GUID.
    Skips phase 1 when --existing-guid is provided or the model has no formulas.
    """
    if not profile:
        return "not_requested", None, None
    if dry_run:
        return "dry_run", None, None

    from ts_cli.sv_build_model import strip_formulas

    has_formulas = bool(build_info["formula_count"])
    guid = existing_guid

    if has_formulas and not guid:
        phase1_doc = strip_formulas(model_doc)
        status, guid, error = _import_one(profile, phase1_doc, phase=1)
        if status == "failed":
            return status, None, error
        if not guid:
            return "failed", None, "phase 1 import returned no GUID"
        typer.echo(f"Phase 1 imported (structure): guid={guid}", err=True)

    if has_formulas and guid:
        import copy
        phase2_doc = copy.deepcopy(model_doc)
        phase2_doc.pop("guid", None)
        phase2_doc = {"guid": guid, **phase2_doc}
        status, final_guid, error = _import_one(
            profile, phase2_doc, phase=2, no_create_new=True)
        if status == "failed":
            return status, guid, error
        return "imported", guid, None

    status, guid, error = _import_one(profile, model_doc, phase=0)
    return status, guid, error


def _import_one(
    profile: str, doc: dict, *, phase: int,
    no_create_new: bool = False,
) -> tuple[str, Optional[str], Optional[str]]:
    """Run a single `ts tml import` invocation. Returns (status, guid, error)."""
    import shlex
    import subprocess

    from ts_cli.tml_common import extract_imported_guid

    model_tml_str = json.dumps(doc)
    cmd = (f"source ~/.zshenv && ts tml import --policy PARTIAL "
           f"--profile {shlex.quote(profile)}")
    if no_create_new:
        cmd += " --no-create-new"

    label = f"phase {phase}" if phase else "import"
    typer.echo(f"  Running {label}...", err=True)

    completed = subprocess.run(
        ["bash", "-c", cmd],
        input=json.dumps([model_tml_str]), capture_output=True, text=True)
    stderr_tail = (completed.stderr or "")[-500:]

    try:
        import_result = json.loads(completed.stdout)
    except Exception:
        import_result = None

    if completed.returncode != 0:
        return "failed", None, stderr_tail

    if import_result is None:
        tail = (completed.stdout or "")[-500:]
        return "failed", None, f"import response unparseable — response tail: {tail}"

    if isinstance(import_result, list):
        status = ((import_result[0].get("response") or {})
                  .get("status") or {})
        if status.get("status_code") == "ERROR":
            import re
            msg = status.get("error_message", "")
            cleaned = re.sub(r"<[^>]+>", " ", msg or "")
            cleaned = " ".join(cleaned.split())[:1000]
            return "failed", None, cleaned

    model_guid = extract_imported_guid(import_result)
    if model_guid is None:
        tail = (completed.stdout or "")[-500:]
        return "failed", None, (
            f"import OK but no GUID found — response tail: {tail}")
    return "imported", model_guid, None


def _build_model_summary(
    *, model_name: str, model_file: str, build_info: dict,
    skipped: list[dict], spotter_enabled: Optional[bool],
    existing_guid: Optional[str], lint_findings: list[str],
    import_status: str, model_guid: Optional[str],
    import_error: Optional[str] = None,
) -> dict:
    summary = {
        "model_name": model_name,
        "model_file": model_file,
        "columns": {"attributes": build_info["attributes"],
                     "measures": build_info["measures"]},
        "formula_count": build_info["formula_count"],
        "skipped": skipped,
        "name_renames": build_info["rename_map"],
        "spotter_enabled": spotter_enabled,
        "existing_guid": existing_guid,
        "lint_findings": lint_findings,
        "import_status": import_status,
        "model_guid": model_guid,
    }
    if import_error is not None:
        summary["import_error"] = import_error
    return summary
