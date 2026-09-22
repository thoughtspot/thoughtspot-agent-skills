#!/usr/bin/env python3
"""
check_python_redefinitions.py — no module-level name is bound twice in one file.

Background. This repo runs no Python linter: `grep -niE 'ruff|flake8|pyflakes|
pylint|mypy'` over `.github/workflows/` and `scripts/` returns nothing, and there
is no linter config anywhere. `radon` is installed in CI but only measures
complexity, and `vulture` is a dev dependency that is never invoked. So a
redefinition is invisible to every gate, and Python itself keeps the LAST binding
silently.

That matters beyond tidiness because of how it arrives. Two branches each adding
`def check_a6(...)` to `ts_cli/audit/checks_ai.py` — one above `check_a2`, one
above `check_a5` — land in different hunks, so git merges them with no conflict.
Both append `check_a6` to `ALL_CHECKS`, an identical edit that also merges
silently. The merged module defines the name twice, `ALL_CHECKS` holds one
function, `len(ALL_CHECKS) == 6` looks correct, the full suite passes, and one of
the audit's five-angle checks has become dead code that never runs. Constructed
and confirmed, 2026-09-22, during the BL-274/BL-279 collision sweep.

Scope: **direct children of the module body only**. A name rebound inside `try`,
`if` or a function is out of scope and deliberately so — the `try: import tomllib
/ except ImportError: import tomli as tomllib` fallback in `check_version_sync.py`
is correct code, and flagging it would make the gate unmergeable on its first run.
Conservative by construction: no false positives, at the cost of missing a
duplicate nested inside a conditional.

Counts imports as well as `def`/`class`. All four violations this gate found on
its first run were imports — a name listed twice in one `from ... import (...)`
list, a doubled `import sys`, and two re-imports of a module-level name — which a
`def`-only scan misses entirely.

`ruff check --select F811` is the off-the-shelf equivalent and catches strictly
more (it understands conditional branches). This exists instead because the repo
has no linter and adding one is a larger decision than this gate; if ruff is ever
adopted, delete this file and select F811.

Escape hatch: `# noqa: F811` on the redefining line, matching ruff's code so the
comment stays meaningful if the two ever swap.

Exit codes:
  0 — no duplicate module-level bindings
  1 — at least one
  2 — the check could not run; NOT a pass

Run manually:
    python3 tools/validate/check_python_redefinitions.py --root .
    python3 tools/validate/check_python_redefinitions.py --root . --staged
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

from _git import staged_files, tracked_relpaths

NOQA = "noqa: F811"


def module_level_bindings(tree: ast.Module) -> list[tuple[str, int]]:
    """Every name bound by a DIRECT child of the module body, with its line.

    Only direct children: see the scope note in the module docstring. A binding
    inside `try`/`if`/a function body is intentionally invisible here.
    """
    out: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append((node.name, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # `import a.b` binds `a`; `import a.b as c` binds `c`.
                name = alias.asname or alias.name.split(".")[0]
                out.append((name, alias.lineno if hasattr(alias, "lineno") else node.lineno))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue  # a star import binds unknowable names; not our business
                out.append((alias.asname or alias.name,
                            alias.lineno if hasattr(alias, "lineno") else node.lineno))
    return out


def duplicates_in(source: str) -> list[tuple[str, int, int]]:
    """(name, first_line, duplicate_line) for each rebinding, `# noqa: F811` aside."""
    tree = ast.parse(source)
    lines = source.splitlines()
    first: dict[str, int] = {}
    out: list[tuple[str, int, int]] = []
    for name, lineno in module_level_bindings(tree):
        if name not in first:
            first[name] = lineno
            continue
        text = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        if NOQA in text:
            continue
        out.append((name, first[name], lineno))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Check for duplicate module-level bindings.")
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--staged", action="store_true",
                        help="Only staged .py files (pre-commit); default is all tracked.")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    try:
        if args.staged:
            # staged_files() yields absolute paths; make them repo-relative so the
            # message reads the same whichever mode produced it.
            rels = [
                str(p.relative_to(root)) if p.is_absolute() else str(p)
                for p in staged_files(root)
                if str(p).endswith(".py")
            ]
        else:
            rels = [p for p in tracked_relpaths(root) if p.endswith(".py")]
    except Exception as exc:  # git absent, not a repo, index contention
        # Never green because it could not run — see the Exit codes block.
        print(f"ERROR: could not enumerate Python files: {exc}", file=sys.stderr)
        return 2

    problems: list[str] = []
    checked = 0
    for rel in sorted(rels):
        path = root / rel
        if not path.exists():
            continue  # staged deletion
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"ERROR: could not read {rel}: {exc}", file=sys.stderr)
            return 2
        try:
            dupes = duplicates_in(source)
        except SyntaxError as exc:
            # A file that does not parse is a real problem, not something to skip
            # past: skipping would let a broken module hide a duplicate inside it.
            print(f"ERROR: {rel} does not parse: {exc}", file=sys.stderr)
            return 2
        checked += 1
        for name, first_line, dup_line in dupes:
            problems.append(f"  ✗ {rel}:{dup_line}  `{name}` already bound at line {first_line}")

    if problems:
        print("Module-level name bound more than once:")
        print("\n".join(problems))
        print()
        print("Python keeps the LAST binding and says nothing. Two branches adding")
        print("the same name in different hunks merge without a conflict, so this")
        print("is how a merged function silently stops running.")
        print("Delete the redundant binding, or add `# noqa: F811` if the rebinding")
        print("is deliberate.")
        return 1

    print(f"PASS  python redefinitions: {checked} module(s), no duplicate module-level bindings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
