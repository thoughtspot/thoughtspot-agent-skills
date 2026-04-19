#!/usr/bin/env python3
"""
check_sv_yaml.py — validate Snowflake Semantic View YAML structure.

Checks all rules from agents/shared/schemas/snowflake-schema.md:
  - required top-level fields (name, tables)
  - name is a valid Snowflake identifier
  - forbidden fields absent (relationship_type, join_type, default_aggregation, sample_values)
  - 'metrics' keyword used (not 'measures')
  - metrics entries have NO data_type (causes Cortex error 392700)
  - dimensions/time_dimensions have valid data_type
  - all field names globally unique across entire semantic view
  - primary_key is a dict with 'columns:' list
  - every right_table in relationships has a primary_key
  - relationship left_table/right_table references match table names
  - expr table alias prefixes match a tables[].name entry

Usage:
    python tools/validate/check_sv_yaml.py --from-md agents/shared/worked-examples/snowflake/ts-to-snowflake.md
    python tools/validate/check_sv_yaml.py --file /tmp/my_view.yaml
    python tools/validate/check_sv_yaml.py --stdin < my_view.yaml
    python tools/validate/check_sv_yaml.py --root . --staged
    python tools/validate/check_sv_yaml.py --root .  # full repo scan
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
# Constants
# ---------------------------------------------------------------------------

VALID_DATA_TYPES = {"TEXT", "NUMBER", "DATE", "TIMESTAMP", "BOOLEAN"}
FORBIDDEN_FIELDS = {"relationship_type", "join_type", "default_aggregation", "sample_values"}
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# SQL function/keyword prefixes that appear before '.' in expr — not table refs
_SQL_FUNCTIONS = {
    "SUM", "COUNT", "AVG", "MIN", "MAX", "COALESCE", "NULLIF", "NVL",
    "IFF", "CASE", "CAST", "ROUND", "FLOOR", "CEIL", "TRUNC", "ABS",
    "DATEDIFF", "DATEADD", "DATE_TRUNC", "YEAR", "MONTH", "DAY",
    "CONCAT", "UPPER", "LOWER", "TRIM", "LENGTH", "SUBSTR", "REPLACE",
    "TO_DATE", "TO_NUMBER", "TO_VARCHAR", "TRY_CAST",
}

# Extract all word.word patterns from an SQL expression
_ALIAS_PREFIX_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.")


# ---------------------------------------------------------------------------
# Core validator
# ---------------------------------------------------------------------------

def validate_sv_yaml(data: dict) -> list[str]:
    """
    Validate a parsed Snowflake Semantic View YAML dict.

    Returns a list of error strings. Empty list means the YAML is valid.
    """
    if not isinstance(data, dict):
        return ["Top-level YAML value must be a mapping (got list or scalar)"]

    errors: list[str] = []

    # ── Top-level name ───────────────────────────────────────────────────────
    name = data.get("name")
    if not name:
        errors.append("Missing required top-level 'name' field")
    elif not isinstance(name, str):
        errors.append(f"'name' must be a string, got {type(name).__name__}")
    elif not IDENTIFIER_RE.match(name):
        errors.append(
            f"View name '{name}' is not a valid Snowflake identifier "
            "(must match ^[A-Za-z_][A-Za-z0-9_]*$)"
        )

    # ── tables ───────────────────────────────────────────────────────────────
    tables = data.get("tables")
    if not tables:
        errors.append("'tables' is required and must be a non-empty list")
        return errors  # cannot continue without tables

    if not isinstance(tables, list):
        errors.append("'tables' must be a list")
        return errors

    table_names: set[str] = set()
    all_field_names: list[tuple[str, str, str]] = []  # (field_name, table_name, section)
    right_tables: set[str] = set()

    for i, table in enumerate(tables):
        if not isinstance(table, dict):
            errors.append(f"tables[{i}] must be a mapping")
            continue

        t_name = table.get("name")
        if not t_name:
            errors.append(f"tables[{i}] missing 'name'")
            t_name = f"<tables[{i}]>"
        elif not IDENTIFIER_RE.match(str(t_name)):
            errors.append(
                f"Table name '{t_name}' at tables[{i}] is not a valid Snowflake identifier"
            )

        if t_name in table_names:
            errors.append(f"Duplicate table name '{t_name}'")
        table_names.add(t_name)

        # Forbidden fields anywhere in the table dict
        for key in FORBIDDEN_FIELDS:
            if key in table:
                errors.append(
                    f"Table '{t_name}' contains forbidden field '{key}' "
                    "(not part of the Semantic View schema)"
                )

        # 'measures' keyword forbidden — must be 'metrics'
        if "measures" in table:
            errors.append(
                f"Table '{t_name}' uses keyword 'measures' — "
                "the correct key is 'metrics'"
            )

        # base_table required fields
        bt = table.get("base_table")
        if not bt:
            errors.append(f"Table '{t_name}' missing 'base_table'")
        elif isinstance(bt, dict):
            for field in ("database", "schema", "table"):
                if not bt.get(field):
                    errors.append(f"Table '{t_name}' base_table missing required field '{field}'")

        # primary_key structure
        pk = table.get("primary_key")
        if pk is not None:
            if not isinstance(pk, dict):
                errors.append(
                    f"Table '{t_name}' primary_key must be a mapping with a 'columns:' list, "
                    f"got {type(pk).__name__}"
                )
            elif not isinstance(pk.get("columns"), list):
                errors.append(
                    f"Table '{t_name}' primary_key must have 'columns:' as a list "
                    "(e.g. 'columns:\\n    - PRODUCT_ID')"
                )

        # dimensions, time_dimensions, metrics
        for section in ("dimensions", "time_dimensions", "metrics"):
            for j, field in enumerate(table.get(section, [])):
                if not isinstance(field, dict):
                    errors.append(f"Table '{t_name}' {section}[{j}] must be a mapping")
                    continue

                f_name = field.get("name")
                if not f_name:
                    errors.append(f"Table '{t_name}' {section}[{j}] missing 'name'")
                    f_name = f"<{section}[{j}]>"
                elif not IDENTIFIER_RE.match(str(f_name)):
                    errors.append(
                        f"Field name '{f_name}' in table '{t_name}' {section}[{j}] "
                        "is not a valid Snowflake identifier"
                    )

                all_field_names.append((str(f_name), t_name, section))

                # metrics must NOT have data_type
                if section == "metrics" and "data_type" in field:
                    errors.append(
                        f"Metric '{f_name}' in table '{t_name}' has 'data_type' — "
                        "omit data_type from metrics entirely "
                        "(Cortex Analyst rejects it with error 392700)"
                    )

                # dimensions and time_dimensions must have a valid data_type
                if section in ("dimensions", "time_dimensions"):
                    dt = field.get("data_type")
                    if not dt:
                        errors.append(
                            f"{section[:-1].title()} '{f_name}' in table '{t_name}' "
                            "missing 'data_type'"
                        )
                    elif dt not in VALID_DATA_TYPES:
                        errors.append(
                            f"{section[:-1].title()} '{f_name}' in table '{t_name}' "
                            f"has invalid data_type '{dt}' — "
                            f"must be one of {sorted(VALID_DATA_TYPES)}"
                        )

                # expr table-alias prefix check (heuristic)
                expr = str(field.get("expr", ""))
                if expr and table_names:
                    _check_expr_table_refs(
                        expr, table_names, f_name, t_name, section, errors
                    )

    # ── Global field-name uniqueness ─────────────────────────────────────────
    seen: dict[str, tuple[str, str]] = {}
    for f_name, t_name, section in all_field_names:
        if f_name in seen:
            prev_table, prev_section = seen[f_name]
            errors.append(
                f"Duplicate field name '{f_name}': appears in "
                f"'{prev_table}.{prev_section}' and '{t_name}.{section}' — "
                "names must be globally unique across the entire semantic view"
            )
        else:
            seen[f_name] = (t_name, section)

    # ── Relationships ────────────────────────────────────────────────────────
    relationships = data.get("relationships", [])
    if not isinstance(relationships, list):
        errors.append("'relationships' must be a list")
    else:
        for i, rel in enumerate(relationships):
            if not isinstance(rel, dict):
                errors.append(f"relationships[{i}] must be a mapping")
                continue

            rel_name = rel.get("name", f"relationships[{i}]")

            for side in ("left_table", "right_table"):
                ref = rel.get(side)
                if not ref:
                    errors.append(f"Relationship '{rel_name}' missing '{side}'")
                elif ref not in table_names:
                    errors.append(
                        f"Relationship '{rel_name}' {side}='{ref}' "
                        "does not match any name in tables[]"
                    )

            rt = rel.get("right_table")
            if rt:
                right_tables.add(rt)

            rel_cols = rel.get("relationship_columns", [])
            if not rel_cols:
                errors.append(
                    f"Relationship '{rel_name}' has no 'relationship_columns' entries"
                )

            for key in FORBIDDEN_FIELDS:
                if key in rel:
                    errors.append(
                        f"Relationship '{rel_name}' contains forbidden field '{key}'"
                    )

    # ── Every right_table must have primary_key ──────────────────────────────
    for table in tables:
        if not isinstance(table, dict):
            continue
        t_name = table.get("name", "")
        if t_name in right_tables and "primary_key" not in table:
            errors.append(
                f"Table '{t_name}' is a right_table in a relationship "
                "but has no 'primary_key' defined"
            )

    return errors


def _check_expr_table_refs(
    expr: str,
    table_names: set[str],
    field_name: str,
    table_name: str,
    section: str,
    errors: list[str],
) -> None:
    """
    Heuristic check: alias prefixes in `expr` (e.g. 'fact_sales' in 'fact_sales.AMOUNT')
    should match a name in tables[]. SQL function names are excluded.
    Only flag if ALL extracted prefixes are unknown (avoids false positives on
    partially-matched expressions like SUM(fact_sales.AMOUNT)).
    """
    prefixes = {
        m.group(1).upper()
        for m in _ALIAS_PREFIX_RE.finditer(expr)
        if m.group(1).upper() not in _SQL_FUNCTIONS
    }
    unknown = [p for p in prefixes if p not in {n.upper() for n in table_names}]
    if unknown and len(unknown) == len(prefixes):
        # All extracted prefixes are unknown — likely a real error
        errors.append(
            f"Field '{field_name}' in table '{table_name}' ({section}) "
            f"expr '{expr}' — alias prefix(es) {unknown} not found in tables[]. "
            "Check table name spelling."
        )


# ---------------------------------------------------------------------------
# Shared YAML-block extractor (mirrors check_yaml.py)
# ---------------------------------------------------------------------------

_FENCE_START = re.compile(r"^```ya?ml\s*$", re.IGNORECASE)
_FENCE_END = re.compile(r"^```\s*$")


def _extract_yaml_blocks(file_path: Path) -> list[tuple[int, str]]:
    """Return (start_line, content) pairs for each ```yaml block in the file."""
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
        description="Validate Snowflake Semantic View YAML structure."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--file", help="Path to a .yaml file to validate")
    group.add_argument("--stdin", action="store_true", help="Read YAML from stdin")
    group.add_argument(
        "--from-md",
        help="Extract and validate the first YAML block from a .md file",
    )
    parser.add_argument(
        "--root", default=".", help="Repo root (default: current dir)"
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Only check files staged in git",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()

    # ── Single-file modes ────────────────────────────────────────────────────
    if args.stdin:
        raw = sys.stdin.read()
        data = yaml.safe_load(raw)
        errors = validate_sv_yaml(data or {})
        if errors:
            for e in errors:
                print(f"FAIL  <stdin>  →  {e}")
            print(f"\n{len(errors)} error(s).")
            return 1
        print("PASS  <stdin>")
        return 0

    if args.file:
        path = Path(args.file)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        errors = validate_sv_yaml(data or {})
        rel = path.name
        if errors:
            for e in errors:
                print(f"FAIL  {rel}  →  {e}")
            print(f"\n{len(errors)} error(s).")
            return 1
        print(f"PASS  {rel}")
        return 0

    if args.from_md:
        path = Path(args.from_md)
        if not path.is_absolute():
            path = repo_root / path
        blocks = _extract_yaml_blocks(path)
        if not blocks:
            print(f"SKIP  {path.name}  (no YAML blocks found)")
            return 0
        total_errors = 0
        for start_line, content in blocks:
            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                continue  # skip non-mapping blocks (e.g. pure list examples)
            # Only validate blocks that look like Semantic View YAML
            if "tables" not in data and "name" not in data:
                continue
            errors = validate_sv_yaml(data)
            rel = path.name
            if errors:
                for e in errors:
                    print(f"FAIL  {rel}:{start_line}  →  {e}")
                total_errors += len(errors)
            else:
                print(f"PASS  {rel}:{start_line}")
        print()
        if total_errors:
            print(f"{total_errors} error(s) found.")
            return 1
        print("All Semantic View YAML blocks valid.")
        return 0

    # ── Repo-scan mode ───────────────────────────────────────────────────────
    skip_dirs = {".git", "__pycache__", ".venv", "venv", "dist", "build", "validate"}


    if args.staged:
        md_files = _get_staged_files(repo_root, ".md")
        yaml_files = _get_staged_files(repo_root, ".yaml") + _get_staged_files(repo_root, ".yml")
    else:
        md_files = [
            f for f in repo_root.glob("agents/shared/**/*.md")
            if not any(p in f.parts for p in skip_dirs)
        ]
        yaml_files = []

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
            if "tables" not in data:
                continue  # not a SV YAML block
            # Skip schema-reference/template blocks where name is a placeholder
            sv_name = data.get("name")
            if sv_name in ("string", None) or (
                isinstance(sv_name, str) and ("{" in sv_name or sv_name == "string")
            ):
                continue
            errors = validate_sv_yaml(data)
            rel = md_file.relative_to(repo_root)
            checked += 1
            if errors:
                for e in errors:
                    print(f"FAIL  {rel}:{start_line}  →  {e}")
                total_errors += len(errors)

    for yf in yaml_files:
        try:
            data = yaml.safe_load(yf.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict) or "tables" not in data:
            continue
        errors = validate_sv_yaml(data)
        rel = yf.relative_to(repo_root)
        checked += 1
        if errors:
            for e in errors:
                print(f"FAIL  {rel}  →  {e}")
            total_errors += len(errors)

    print()
    if not checked:
        print("No Semantic View YAML blocks found.")
        return 0

    if total_errors:
        print(f"{total_errors} Semantic View YAML error(s) found.")
        return 1

    print("All Semantic View YAML blocks valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
