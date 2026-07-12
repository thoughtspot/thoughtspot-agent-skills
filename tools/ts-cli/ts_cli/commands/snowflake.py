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
