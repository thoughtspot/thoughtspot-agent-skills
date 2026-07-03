#!/usr/bin/env python3
"""
check_no_v1_endpoints.py — fail if any Python code calls a v1 (`/tspublic/v1/...`)
ThoughtSpot REST endpoint, OR a v2 endpoint that has since been deprecated.

The repo completed its v1→v2 migration on 2026-06-16 (see `.claude/rules/ts-cli.md`,
"No v1 endpoints"). v1 paths are removed on newer ThoughtSpot Cloud builds (404), so any
new one is a latent bug. This validator guards the invariant.

2026-07-03 audit finding 13.1 added a second, narrower denylist: DEPRECATED_V2_ENDPOINTS.
Some v2 endpoints get superseded by a newer v2 shape without a full v1→v2-style repo
migration event — e.g. the batch `POST /template/variables/update-values` was replaced
by the per-identifier `POST /template/variables/{identifier}/update-values` (26.4.0.cl,
`putVariableValues` replacing `updateVariableValues`). The bare batch path is exactly
the shape of bug the v1 marker used to catch, so it reuses the same AST infrastructure
rather than spinning up a sibling validator.

Why AST (not grep): legitimate marker mentions live in **docstrings** (explaining what
was migrated away) and in **test assertions** (`assert "/tspublic/v1/" not in url`).
A raw grep flags all of those. This walker:

  - skips test files (path contains a `tests` segment, or filename starts with `test_`)
  - skips string constants that are docstrings (module / class / function)
  - flags every other string literal containing a banned marker — i.e. a real endpoint
    path baked into code
  - f-string variants (e.g. `f"/api/rest/2.0/template/variables/{identifier}/update-values"`)
    are safe by construction: an f-string's constant text is split into separate
    ast.Constant fragments around each `{...}` expression, so the bare denylisted
    substring never appears contiguously in any single fragment

Exit codes:
  0 — no v1 endpoint and no deprecated-v2 endpoint usage in non-test, non-docstring code
  1 — at least one banned endpoint string literal found

Run manually:
    python3 tools/validate/check_no_v1_endpoints.py --root .
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

V1_MARKER = "/tspublic/v1/"

# v2 endpoints that were current when written but have since been superseded by a
# newer v2 shape (2026-07 audit finding 13.1). Denylisting the bare/deprecated form
# stops it from being reintroduced once every call site has migrated to the
# replacement. Each entry needs a one-line reason in this comment block:
#
#   /api/rest/2.0/template/variables/update-values
#     — batch form, deprecated 26.4.0.cl. Replacement: the per-identifier form
#       /api/rest/2.0/template/variables/{identifier}/update-values (`putVariableValues`).
#       Anchored on the exact bare path so it does NOT match the current per-identifier
#       form or an f-string variant like
#       f"/api/rest/2.0/template/variables/{quote(variable)}/update-values" — those
#       have a `{...}` expression between "variables/" and "update-values", so the bare
#       "variables/update-values" substring never appears contiguously in either one.
DEPRECATED_V2_ENDPOINTS = (
    "/api/rest/2.0/template/variables/update-values",
)

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
    v1 marker or a deprecated-v2 endpoint. Empty list = clean."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if V1_MARKER not in source and not any(ep in source for ep in DEPRECATED_V2_ENDPOINTS):
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
        if id(node) in docstring_ids:
            continue
        if V1_MARKER in node.value or any(ep in node.value for ep in DEPRECATED_V2_ENDPOINTS):
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
            kind = "v1 endpoint" if V1_MARKER in snippet else "deprecated v2 endpoint"
            failures.append(f"  ✗ {rel}:{lineno}: {kind} in code → {snippet!r}")

    if failures:
        print(f"\n{len(failures)} banned endpoint usage(s) found:\n")
        print("\n".join(failures))
        print()
        print("The repo is v1-free (.claude/rules/ts-cli.md) and avoids deprecated v2")
        print("endpoints (DEPRECATED_V2_ENDPOINTS in this file, 2026-07 audit 13.1).")
        print("Migrate to the current equivalent: confirm the spec via")
        print("get-rest-api-reference, then use the per-identifier / current v2 path.")
        print("Docstrings and test assertions are exempt.")
        return 1

    print(f"No v1 or deprecated-v2 endpoint usage in {scanned} Python file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
