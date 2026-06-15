#!/usr/bin/env python3
"""
check_formula_catalog.py — cross-check mapping files against
thoughtspot-formula-patterns.md to catch invalid TS function references.

Parses the catalog for valid and non-existent (strikethrough) function names,
then scans each mapping file for TS function references that contradict the
catalog.

Usage:
    python tools/validate/check_formula_catalog.py --root /path/to/repo
    python tools/validate/check_formula_catalog.py --root /path/to/repo --all
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Matches a function name in the first column of a catalog table row.
# Two patterns:
#   1. Non-existent: | ~~`name`~~ | ...  (strikethrough)
#   2. Valid:        | `name`     | ...
_CATALOG_VALID_RE = re.compile(r"^\|\s*`([a-z_][a-z0-9_ ]*)`\s*\|")
_CATALOG_NONEXISTENT_RE = re.compile(r"^\|\s*~~`([a-z_][a-z0-9_ ]*)`~~\s*\|")


def parse_catalog(text: str) -> tuple[set[str], set[str]]:
    """Parse formula-patterns.md content. Returns (valid_functions, nonexistent_functions)."""
    valid: set[str] = set()
    nonexistent: set[str] = set()
    for line in text.splitlines():
        m = _CATALOG_NONEXISTENT_RE.match(line)
        if m:
            nonexistent.add(m.group(1))
            continue
        m = _CATALOG_VALID_RE.match(line)
        if m:
            name = m.group(1)
            if name not in ("Function",):
                valid.add(name)
    return valid, nonexistent


# Extracts TS function names from mapping file table cells.
_TS_FUNC_IN_CELL_RE = re.compile(r"`(?:~~)?([a-z_][a-z0-9_ ]*)\s*\(")

# Detects strikethrough wrapping on a function reference in a mapping file.
_STRIKETHROUGH_FUNC_RE = re.compile(r"~~`([a-z_][a-z0-9_ ]*)\s*\(")

# Detects sql_*_op template calls — skip function names inside the template string.
_SQL_OP_RE = re.compile(r'`sql_[a-z_]+_op\s*\(')

COMPLEX_PATTERN_PREFIXES = (
    "cumulative_", "moving_", "group_", "rank", "last_value", "first_value",
    "sql_string_op", "sql_int_op", "sql_double_op", "sql_bool_op",
    "sql_date_op", "sql_date_time_op",
    "sql_string_aggregate_op", "sql_int_aggregate_op",
    "sql_number_aggregate_op", "sql_date_time_aggregate_op",
)


def _is_complex_pattern(name: str) -> bool:
    return any(name.startswith(p) or name == p.rstrip("_") for p in COMPLEX_PATTERN_PREFIXES)


def scan_mapping(
    text: str,
    filename: str,
    valid: set[str],
    nonexistent: set[str],
) -> tuple[list[str], list[str]]:
    """Scan a mapping file for TS function references. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    for line_no, line in enumerate(text.splitlines(), 1):
        if _SQL_OP_RE.search(line):
            continue

        strikethrough_names = {m.group(1) for m in _STRIKETHROUGH_FUNC_RE.finditer(line)}

        for m in _TS_FUNC_IN_CELL_RE.finditer(line):
            name = m.group(1).strip()
            if not name or name in strikethrough_names:
                continue
            if _is_complex_pattern(name):
                continue
            if name in nonexistent:
                errors.append(
                    f"ERROR: {filename}:{line_no}: `{name}` is not a valid TS function "
                    f"(marked non-existent in formula-patterns.md)"
                )
            elif name not in valid:
                warnings.append(
                    f"WARNING: {filename}:{line_no}: `{name}` not found in "
                    f"formula-patterns.md catalog"
                )

    return errors, warnings
