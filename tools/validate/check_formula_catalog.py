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
