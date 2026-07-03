"""ts snowflake — deterministic helpers shared by the Snowflake conversion skills.

BL-063 codification quick wins (2026-07-03 audit, codification review rows 3 & 4):
`diff` and `lint-ddl` extract inline Python that both ts-convert-to-snowflake-sv and
ts-convert-from-snowflake-sv previously copy-pasted into their SKILL.md files. Pure
logic lives in `ts_cli.snowflake_ops` (no I/O); this module is the CLI/file-I/O shell.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from ts_cli.snowflake_ops import compute_change_set, lint_sv_ddl

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
