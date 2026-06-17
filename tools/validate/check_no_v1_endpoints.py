#!/usr/bin/env python3
"""
check_no_v1_endpoints.py — fail if any Python code calls a v1 (`/tspublic/v1/...`)
ThoughtSpot REST endpoint.

The repo completed its v1→v2 migration on 2026-06-16 (see `.claude/rules/ts-cli.md`,
"No v1 endpoints"). v1 paths are removed on newer ThoughtSpot Cloud builds (404), so any
new one is a latent bug. This validator guards the invariant.

Why AST (not grep): legitimate `/tspublic/v1/` mentions live in **docstrings** (explaining
what was migrated away) and in **test assertions** (`assert "/tspublic/v1/" not in url`).
A raw grep flags all of those. This walker:

  - skips test files (path contains a `tests` segment, or filename starts with `test_`)
  - skips string constants that are docstrings (module / class / function)
  - flags every other string literal containing `/tspublic/v1/` — i.e. a real endpoint
    path baked into code

Exit codes:
  0 — no v1 endpoint usage in non-test, non-docstring code
  1 — at least one v1 endpoint string literal found

Run manually:
    python3 tools/validate/check_no_v1_endpoints.py --root .
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

V1_MARKER = "/tspublic/v1/"

# Directories scanned for Python source. Anything else (node_modules, build dirs) is
# irrelevant — the CLI and the Databricks client are where API calls live.
SCAN_DIRS = ("tools", "agents", "scripts")

# The validators under tools/validate/ are meta-tooling: they reference the marker
# string to *detect* v1 usage, they never call the API. Exclude them.
EXCLUDE_DIRS = ("tools/validate",)


def _is_excluded(rel: Path) -> bool:
    rel_str = rel.as_posix()
    return any(rel_str.startswith(d + "/") for d in EXCLUDE_DIRS)


def _is_test_file(path: Path) -> bool:
    return path.name.startswith("test_") or "tests" in path.parts


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    """Return id() of every string-Constant node that is a docstring (the first
    Expr statement of a module / class / function body)."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            if isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, snippet) for each non-docstring string literal containing the
    v1 marker. Empty list = clean."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if V1_MARKER not in source:
        return []  # fast path — nothing to parse
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []  # not our job to police syntax; other validators do

    docstring_ids = _docstring_constant_ids(tree)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if V1_MARKER not in node.value:
            continue
        if id(node) in docstring_ids:
            continue
        hits.append((node.lineno, node.value.strip()[:80]))
    return hits


def iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        base = root / d
        if base.is_dir():
            files.extend(sorted(base.rglob("*.py")))
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    failures: list[str] = []
    scanned = 0
    for path in iter_python_files(root):
        rel = path.relative_to(root)
        if _is_test_file(path) or _is_excluded(rel):
            continue
        scanned += 1
        for lineno, snippet in scan_file(path):
            rel = path.relative_to(root)
            failures.append(f"  ✗ {rel}:{lineno}: v1 endpoint in code → {snippet!r}")

    if failures:
        print(f"\n{len(failures)} v1 endpoint usage(s) found:\n")
        print("\n".join(failures))
        print()
        print("The repo is v1-free (.claude/rules/ts-cli.md). Migrate to the v2 equivalent:")
        print("  confirm the v2 spec via get-rest-api-reference, then use POST")
        print("  /api/rest/2.0/... instead. Docstrings and test assertions are exempt.")
        return 1

    print(f"No v1 endpoint usage in {scanned} Python file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
