#!/usr/bin/env python3
"""
check_tml.py — validate ThoughtSpot TML structural correctness.

Checks all rules from agents/shared/schemas/thoughtspot-table-tml.md and
agents/shared/schemas/thoughtspot-model-tml.md.

Auto-detects Table TML (top-level 'table:' key) vs Model TML (top-level 'model:' key).

Usage:
    python tools/validate/check_tml.py --from-md agents/shared/worked-examples/snowflake/ts-from-snowflake.md
    python tools/validate/check_tml.py --file /tmp/my_table.tml.yaml
    python tools/validate/check_tml.py --stdin < model.yaml
    python tools/validate/check_tml.py --root . --staged
    python tools/validate/check_tml.py --root .  # full repo scan
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Valid value sets
# ---------------------------------------------------------------------------

TS_DATA_TYPES = {
    "INT64", "INTEGER", "BIGINT", "DOUBLE", "FLOAT",
    "VARCHAR", "CHAR", "STRING",
    "BOOL", "BOOLEAN",
    "DATE", "DATE_TIME", "DATETIME", "TIMESTAMP",
}

SQL_ONLY_TYPES = {
    "INT", "SMALLINT", "TINYINT", "NUMERIC", "DECIMAL",
    "REAL", "NUMBER", "TEXT", "NVARCHAR", "NCHAR",
    "TIME",
}

VALID_COLUMN_TYPES = {"ATTRIBUTE", "MEASURE"}
VALID_AGGREGATIONS = {
    "SUM", "COUNT", "AVERAGE", "MAX", "MIN",
    "COUNT_DISTINCT", "NONE", "STD_DEVIATION", "VARIANCE",
}


# ---------------------------------------------------------------------------
# Table TML validator
# ---------------------------------------------------------------------------

def validate_table_tml(data: dict) -> list[str]:
    """
    Validate a parsed Table TML dict.
    Returns a list of error strings; empty = valid.
    """
    if not isinstance(data, dict):
        return ["Top-level TML value must be a mapping"]

    errors: list[str] = []

    # Rule: guid must be at document root, not inside table:
    inner = data.get("table", {})
    if isinstance(inner, dict) and "guid" in inner:
        errors.append(
            "'guid' is nested inside 'table:' — it must be at the document root. "
            "Move it to the top level (or omit on first import)."
        )

    if not inner:
        errors.append("Missing top-level 'table:' key")
        return errors

    if not isinstance(inner, dict):
        errors.append("'table:' value must be a mapping")
        return errors

    # Required fields
    for field in ("name", "db", "schema", "db_table"):
        if not inner.get(field):
            errors.append(f"table.{field} is required")

    # connection block
    conn = inner.get("connection")
    if conn is None:
        errors.append("table.connection is required")
    elif not isinstance(conn, dict):
        errors.append("table.connection must be a mapping")
    else:
        if "fqn" in conn:
            errors.append(
                "table.connection has 'fqn:' — use 'name:' only. "
                "The fqn field causes authentication failures on some ThoughtSpot instances."
            )
        if not conn.get("name"):
            errors.append(
                "table.connection.name is required "
                "(the display name of the connection, e.g. 'My Snowflake')"
            )

    # columns
    columns = inner.get("columns") or []
    if not columns:
        errors.append("table.columns must have at least one entry")

    for i, col in enumerate(columns):
        if not isinstance(col, dict):
            errors.append(f"table.columns[{i}] must be a mapping")
            continue
        col_name = col.get("name", f"columns[{i}]")

        # db_column_name must always be present
        if "db_column_name" not in col:
            errors.append(
                f"Column '{col_name}' missing 'db_column_name' — "
                "required on every column even when it equals 'name'. "
                "Some ThoughtSpot instances reject imports without it."
            )

        # column_type must be under properties:
        if "column_type" in col:
            errors.append(
                f"Column '{col_name}' has 'column_type' at the column root — "
                "it must be nested under 'properties:'"
            )

        props = col.get("properties", {})
        if isinstance(props, dict):
            col_type = props.get("column_type")
            if not col_type:
                errors.append(
                    f"Column '{col_name}' missing properties.column_type "
                    "(must be ATTRIBUTE or MEASURE)"
                )
            elif not isinstance(col_type, str):
                errors.append(
                    f"Column '{col_name}' properties.column_type must be a string, "
                    f"got {type(col_type).__name__}"
                )
            elif col_type not in VALID_COLUMN_TYPES:
                errors.append(
                    f"Column '{col_name}' properties.column_type='{col_type}' "
                    f"is invalid — must be one of {sorted(VALID_COLUMN_TYPES)}"
                )

        db_props = col.get("db_column_properties", {})
        if isinstance(db_props, dict):
            dt = db_props.get("data_type")
            if dt and isinstance(dt, str) and dt.upper() in SQL_ONLY_TYPES:
                errors.append(
                    f"Column '{col_name}' db_column_properties.data_type='{dt}' "
                    "is a SQL type. Use the ThoughtSpot type instead "
                    "(e.g. INT64 not INTEGER, VARCHAR not TEXT, BOOL not TINYINT)."
                )

    # joins_with: empty list is an error
    joins_with = inner.get("joins_with")
    if joins_with is not None and joins_with == []:
        errors.append(
            "table.joins_with is an empty list — omit the key entirely for tables "
            "with no joins. An empty list may cause import errors on some versions."
        )

    return errors


# ---------------------------------------------------------------------------
# Model TML validator
# ---------------------------------------------------------------------------

def validate_model_tml(data: dict) -> list[str]:
    """
    Validate a parsed Model TML dict.
    Returns a list of error strings; empty = valid.
    """
    if not isinstance(data, dict):
        return ["Top-level TML value must be a mapping"]

    errors: list[str] = []

    # Rule: guid at document root, not inside model:
    inner = data.get("model", {})
    if isinstance(inner, dict) and "guid" in inner:
        errors.append(
            "'guid' is nested inside 'model:' — it must be at the document root. "
            "Move it to the top level (or omit on first import)."
        )

    if not inner:
        errors.append("Missing top-level 'model:' key")
        return errors

    if not isinstance(inner, dict):
        errors.append("'model:' value must be a mapping")
        return errors

    if not inner.get("name"):
        errors.append("model.name is required")

    # model_tables — collect alias set for column_id prefix validation.
    # column_id prefixes match: alias > id > name (in that priority order per ThoughtSpot docs)
    model_tables = inner.get("model_tables", [])
    table_aliases: set[str] = set()
    for i, entry in enumerate(model_tables):
        if not isinstance(entry, dict):
            continue
        t_name = entry.get("name", f"model_tables[{i}]")
        # 'alias' > 'id' > 'name' — all three are valid column_id prefixes
        alias = entry.get("alias") or t_name
        entry_id = entry.get("id")
        if alias in table_aliases and not entry_id:
            errors.append(
                f"model_tables has duplicate alias '{alias}' — "
                "use 'alias:' to distinguish the same physical table used multiple times"
            )
        table_aliases.add(alias)
        if entry_id:
            table_aliases.add(entry_id)

    columns = inner.get("columns") or []
    formulas = inner.get("formulas") or []

    # Build formula id set
    formula_ids: set[str] = set()
    for f in formulas:
        if not isinstance(f, dict):
            continue
        fid = f.get("id")
        if fid:
            formula_ids.add(fid)

        # Rule: aggregation must NOT appear in formulas[] entries
        if "aggregation" in f:
            errors.append(
                f"Formula '{f.get('name', fid)}' has 'aggregation:' in formulas[] — "
                "aggregation belongs in the corresponding columns[] entry, never in formulas[]"
            )

    formula_ids_referenced: set[str] = set()
    column_ids_seen: set[str] = set()
    col_display_names: list[str] = []

    for i, col in enumerate(columns):
        if not isinstance(col, dict):
            errors.append(f"model.columns[{i}] must be a mapping")
            continue
        col_display = col.get("name", f"columns[{i}]")
        col_display_names.append(col_display)

        # column_type must NOT appear at column root
        if "column_type" in col:
            errors.append(
                f"Column '{col_display}' has 'column_type' at the column root — "
                "it must be under 'properties.column_type'"
            )

        props = col.get("properties", {})
        if not isinstance(props, dict) or not props.get("column_type"):
            errors.append(
                f"Column '{col_display}' missing properties.column_type "
                "(must be ATTRIBUTE or MEASURE)"
            )

        # column_id: check for duplicates and table prefix validity
        col_id = col.get("column_id")
        if col_id:
            if col_id in column_ids_seen:
                errors.append(
                    f"Duplicate column_id '{col_id}' — each column must have a unique id"
                )
            column_ids_seen.add(col_id)

            if "::" in col_id and table_aliases:
                tbl_prefix = col_id.split("::")[0]
                if tbl_prefix not in table_aliases:
                    errors.append(
                        f"Column '{col_display}' column_id='{col_id}' — "
                        f"table prefix '{tbl_prefix}' does not match any "
                        "model_tables name or alias"
                    )

        # formula_id: must match a formulas[] id
        formula_id = col.get("formula_id")
        if formula_id:
            formula_ids_referenced.add(formula_id)
            if formula_ids and formula_id not in formula_ids:
                errors.append(
                    f"Column '{col_display}' formula_id='{formula_id}' "
                    "does not match any formulas[].id in this model"
                )

    # Every formula must be surfaced in at least one column
    unreferenced = formula_ids - formula_ids_referenced
    for fid in sorted(unreferenced):
        errors.append(
            f"Formula id '{fid}' is defined in formulas[] but has no "
            "matching 'formula_id:' in any columns[] entry — "
            "the formula will not be visible in the model"
        )

    # Duplicate column display names
    seen_names: set[str] = set()
    for name in col_display_names:
        if name in seen_names:
            errors.append(
                f"Duplicate column display name '{name}' in model.columns[] — "
                "ThoughtSpot requires unique display names"
            )
        seen_names.add(name)

    return errors


# ---------------------------------------------------------------------------
# Auto-detect and dispatch
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r'\{[A-Za-z_][A-Za-z0-9_]*\}')


def _is_template_block(data: dict) -> bool:
    """
    Return True if this YAML block looks like a schema-reference template or a
    documentation snippet rather than a real TML object. Checks:
    - Any template placeholder {identifier} anywhere in the dict
    - Inner dict has a 'name' field that is itself a dict (schema ref pattern)
    - Table TML snippet: has 'table:' but missing both 'connection' and 'columns'
      (documentation excerpts showing only selected fields — not complete TML)
    """
    raw = str(data)
    # Any template placeholder = skip (schema refs and worked-example templates use these)
    if _TEMPLATE_RE.search(raw):
        return True
    # Inner object name is a dict (YAML schema reference pattern: name: {type: string})
    inner = data.get("table") or data.get("model") or {}
    if isinstance(inner, dict) and isinstance(inner.get("name"), dict):
        return True
    # Partial table TML snippet: real Table TML always has connection: and columns:
    # If both are absent the block is a documentation excerpt, not importable TML
    if "table" in data and isinstance(data["table"], dict):
        tbl = data["table"]
        if "connection" not in tbl and "columns" not in tbl:
            return True
        # Documentation pattern: columns: with no value (YAML null) = "columns go here" comment
        if "columns" in tbl and tbl.get("columns") is None:
            return True
    return False


def validate_tml(data: dict) -> tuple[str, list[str]]:
    """
    Auto-detect TML type and validate.
    Returns (tml_type, errors) where tml_type is 'table', 'model', or 'unknown'.
    """
    if not isinstance(data, dict):
        return "unknown", ["Top-level value must be a YAML mapping"]

    if _is_template_block(data):
        return "template", []  # schema reference / worked-example template — skip

    if "table" in data:
        return "table", validate_table_tml(data)
    if "model" in data:
        return "model", validate_model_tml(data)
    if "worksheet" in data:
        # Worksheets are exported TML but not directly importable as table/model.
        # No validation implemented; skip silently.
        return "worksheet", []
    return "unknown", []


# ---------------------------------------------------------------------------
# Shared YAML-block extractor
# ---------------------------------------------------------------------------

_FENCE_START = re.compile(r"^```ya?ml\s*$", re.IGNORECASE)
_FENCE_END = re.compile(r"^```\s*$")


def _extract_yaml_blocks(file_path: Path) -> list[tuple[int, str]]:
    blocks = []
    lines = file_path.read_text(encoding="utf-8").splitlines()
    in_block = False
    block_start = 0
    block_lines: list[str] = []

    for i, line in enumerate(lines, 1):
        if not in_block:
            if _FENCE_START.match(line):
                in_block = True
                block_start = i + 1
                block_lines = []
        else:
            if _FENCE_END.match(line):
                in_block = False
                blocks.append((block_start, "\n".join(block_lines)))
                block_lines = []
            else:
                block_lines.append(line)

    return blocks


def _get_staged_files(repo_root: Path, suffix: str) -> list[Path]:
    import subprocess
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return [
        repo_root / f
        for f in result.stdout.splitlines()
        if f.endswith(suffix) and (repo_root / f).exists()
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate ThoughtSpot Table or Model TML structure."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--file", help="Path to a .yaml/.tml file to validate")
    group.add_argument("--stdin", action="store_true", help="Read YAML from stdin")
    group.add_argument(
        "--from-md",
        help="Extract and validate all TML YAML blocks from a .md file",
    )
    parser.add_argument("--root", default=".", help="Repo root (default: current dir)")
    parser.add_argument(
        "--staged", action="store_true", help="Only check staged files"
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()

    # ── Single-file modes ────────────────────────────────────────────────────
    if args.stdin:
        raw = sys.stdin.read()
        data = yaml.safe_load(raw)
        tml_type, errors = validate_tml(data or {})
        if tml_type == "unknown":
            print("SKIP  <stdin>  (not Table or Model TML)")
            return 0
        if errors:
            for e in errors:
                print(f"FAIL  <stdin> ({tml_type} TML)  →  {e}")
            print(f"\n{len(errors)} error(s).")
            return 1
        print(f"PASS  <stdin> ({tml_type} TML)")
        return 0

    if args.file:
        path = Path(args.file)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        tml_type, errors = validate_tml(data or {})
        rel = path.name
        if tml_type == "unknown":
            print(f"SKIP  {rel}  (not Table or Model TML)")
            return 0
        if errors:
            for e in errors:
                print(f"FAIL  {rel} ({tml_type} TML)  →  {e}")
            print(f"\n{len(errors)} error(s).")
            return 1
        print(f"PASS  {rel} ({tml_type} TML)")
        return 0

    if args.from_md:
        path = Path(args.from_md)
        if not path.is_absolute():
            path = repo_root / path
        blocks = _extract_yaml_blocks(path)
        total_errors = 0
        for start_line, content in blocks:
            try:
                data = yaml.safe_load(content)
            except yaml.YAMLError:
                continue
            if not isinstance(data, dict):
                continue
            tml_type, errors = validate_tml(data)
            if tml_type == "unknown":
                continue
            rel = path.name
            if errors:
                for e in errors:
                    print(f"FAIL  {rel}:{start_line} ({tml_type} TML)  →  {e}")
                total_errors += len(errors)
            else:
                print(f"PASS  {rel}:{start_line} ({tml_type} TML)")
        print()
        if total_errors:
            print(f"{total_errors} TML error(s) found.")
            return 1
        print("All TML blocks valid (or no TML blocks found).")
        return 0

    # ── Repo-scan mode ───────────────────────────────────────────────────────
    skip_dirs = {".git", "__pycache__", ".venv", "venv", "dist", "build", "validate"}

    if args.staged:
        md_files = _get_staged_files(repo_root, ".md")
    else:
        md_files = [
            f for f in sorted(repo_root.glob("agents/**/*.md"))
            if not any(p in f.parts for p in skip_dirs)
        ]

    total_errors = 0
    checked = 0

    for md_file in md_files:
        blocks = _extract_yaml_blocks(md_file)
        for start_line, content in blocks:
            try:
                data = yaml.safe_load(content)
            except yaml.YAMLError:
                continue
            if not isinstance(data, dict):
                continue
            tml_type, errors = validate_tml(data)
            if tml_type in ("unknown", "template", "worksheet"):
                continue
            checked += 1
            rel = md_file.relative_to(repo_root)
            if errors:
                for e in errors:
                    print(f"FAIL  {rel}:{start_line} ({tml_type} TML)  →  {e}")
                total_errors += len(errors)

    print()
    if not checked:
        print("No TML blocks found.")
        return 0

    if total_errors:
        print(f"{total_errors} TML error(s) found in {checked} block(s).")
        return 1

    print(f"All {checked} TML block(s) valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
