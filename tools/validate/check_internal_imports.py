#!/usr/bin/env python3
"""
check_internal_imports.py — fail if a `from ts_cli.X import Y` statement anywhere in
`tools/ts-cli/ts_cli/` imports a name `Y` that does not actually exist in `ts_cli.X`.

2026-07-29 audit finding 4.2 (angle 17's first catch, 17.1): `ts migrate rollback`
(`ts_cli/commands/migrate.py:496`) has a **function-local** import —

    from ts_cli.migrate.apply_plan import STEP_LIFT_CONTENT, STEP_LIFT_SCAFFOLDING

— of two constants the apply-rewrite (PR #367) deleted from `apply_plan.py`. Because the
import is inside a function body, it never executes at module load, so `ts` starts fine,
pytest collection is clean, and CI is green — the ImportError only fires the first time
someone actually runs `ts migrate rollback`. No test exercises the rollback path, so
nothing else in the suite would have caught it either. This validator closes that gap
with a purely static check: it never imports `ts_cli` at runtime (which would hide the
same class of bug behind whichever import happens to execute first), it walks the AST of
every module and the AST of every module it imports from, and asserts the imported name
is actually bound there.

How a name is "found" in the target module:
  - defined at module top level (`def`/`class`/assignment/`import`/`from ... import ...`),
    including inside `if`/`try`/`with`/`for`/`while` blocks (they execute at import time —
    only function/class BODIES introduce a new scope this walker doesn't need to enter), OR
  - re-exported: the target module itself does `from somewhere import that_name` — the
    binding walk above already covers this, since a `from`-import binds a name in the
    importing module's own namespace exactly like an assignment would, OR
  - a **submodule** of the target *package* — `from ts_cli.migrate import discover` is
    valid whenever `ts_cli/migrate/discover.py` exists, even if `migrate/__init__.py`
    never explicitly imports it (Python's import system attributes a successfully-imported
    submodule onto its parent package automatically). Checked by resolving `discover` as
    a file/subpackage under the target module's directory.

What this does NOT check (deliberately, to keep false positives near zero):
  - Relative imports (`from . import x`, `from .foo import bar`) — the audit finding and
    the routing task both scope this to imports whose module string starts with `ts_cli`;
    relative imports are a different (and, empirically, currently correct) surface.
  - Star imports (`from ts_cli.x import *`) — no star imports exist in the package today;
    if one is ever added, this walker treats that module's namespace as "unknown" and
    stops checking names against it rather than risk a false failure.
  - `import ts_cli.x.y` (bare `Import`, not `ImportFrom`) — out of scope per the finding.
  - Modules with a PEP 562 `__getattr__` — `ts_cli/model_builder.py` deliberately defers
    `build_blend_plan` to a module-level `__getattr__` to break a genuine circular import
    with `ts_cli/tableau/build_model.py` (see that file's "Re-exports" comment). A static
    walker can't evaluate what `__getattr__` returns, so a module defining one is treated
    like a star import: skip per-name checks against it rather than false-flag the
    deliberate lazy re-export.

Exit codes:
  0 — every `from ts_cli...` import in tools/ts-cli/ts_cli/ resolves to a real name
  1 — at least one import references a name that isn't defined, re-exported, or a
      submodule of its target — OR a target module itself doesn't exist on disk

Run manually:
    python3 tools/validate/check_internal_imports.py --root .
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PACKAGE_NAME = "ts_cli"
# tools/ts-cli/ts_cli — the package root; module dotted paths resolve relative to this.
SCAN_ROOT = Path("tools/ts-cli/ts_cli")

# --------------------------------------------------------------------------------------
# Temporary allowlist for a KNOWN, already-diagnosed breakage with a fix in flight.
# Every entry needs a dated justification comment and must be removed the moment the
# referenced fix merges — this is scaffolding for landing the gate now, not a permanent
# exemption. Format: (repo-relative path, import lineno, target module, imported name).
# --------------------------------------------------------------------------------------
ALLOWLIST: set[tuple[str, int, str, str]] = {
    # ts_cli/commands/migrate.py:496 imports STEP_LIFT_CONTENT, STEP_LIFT_SCAFFOLDING from
    # ts_cli.migrate.apply_plan — the apply-rewrite (PR #367) deleted those constants,
    # which is exactly the breakage audit finding 17.1 documents. A separate PR is
    # reworking rollback_migration against the new ledger schema.
    # known break, fix in flight (audit 17.1) — remove when merged. Added 2026-07-29.
    ("tools/ts-cli/ts_cli/commands/migrate.py", 496, "ts_cli.migrate.apply_plan", "STEP_LIFT_CONTENT"),
    ("tools/ts-cli/ts_cli/commands/migrate.py", 496, "ts_cli.migrate.apply_plan", "STEP_LIFT_SCAFFOLDING"),
}


@dataclass
class Finding:
    path: Path
    lineno: int
    module: str
    name: Optional[str]  # None for a "module itself doesn't exist" finding
    reason: str  # "module-not-found" | "name-not-found"


def _module_relpath(module: str) -> str:
    """"ts_cli" -> "" ; "ts_cli.migrate.apply_plan" -> "migrate/apply_plan"."""
    assert module == PACKAGE_NAME or module.startswith(PACKAGE_NAME + ".")
    rest = module[len(PACKAGE_NAME):].lstrip(".")
    return rest.replace(".", "/")


def resolve_module_file(pkg_root: Path, module: str) -> Optional[Path]:
    """Static file resolution for a `ts_cli...` dotted module path — never imports it."""
    rel = _module_relpath(module)
    if rel == "":
        candidate = pkg_root / "__init__.py"
        return candidate if candidate.is_file() else None
    as_module = pkg_root / f"{rel}.py"
    if as_module.is_file():
        return as_module
    as_package = pkg_root / rel / "__init__.py"
    if as_package.is_file():
        return as_package
    return None


def submodule_exists(pkg_root: Path, module: str, name: str) -> bool:
    """True if `name` is itself a submodule/subpackage living under `module`'s directory
    — valid for `from ts_cli.pkg import name` regardless of whether pkg/__init__.py
    explicitly re-exports it (Python binds a successfully-imported submodule onto its
    parent package automatically)."""
    rel = _module_relpath(module)
    base = pkg_root / rel if rel else pkg_root
    if not base.is_dir():
        return False  # module is a plain .py file, not a package — no submodule concept
    return (base / f"{name}.py").is_file() or (base / name / "__init__.py").is_file()


def _assign_target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        out: set[str] = set()
        for elt in target.elts:
            out |= _assign_target_names(elt)
        return out
    if isinstance(target, ast.Starred):
        return _assign_target_names(target.value)
    return set()


def _container_bodies(node: ast.stmt) -> list[list[ast.stmt]]:
    """Sub-bodies of a control-flow statement that execute at the SAME (module) scope
    as the statement itself — as opposed to FunctionDef/ClassDef, which open a new scope
    this walker must not enter."""
    bodies = [node.body]
    orelse = getattr(node, "orelse", None)
    if orelse:
        bodies.append(orelse)
    if isinstance(node, ast.Try):
        for handler in node.handlers:
            bodies.append(handler.body)
        if node.finalbody:
            bodies.append(node.finalbody)
    return bodies


def collect_bound_names(body: list[ast.stmt]) -> Optional[set[str]]:
    """Names bound at module scope by this statement list. Returns None if a star
    import is present anywhere — the namespace can't be determined precisely, so the
    caller should skip per-name checks against this module rather than risk a false
    failure."""
    names: set[str] = set()
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names |= _assign_target_names(target)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            names |= _assign_target_names(node.target)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    return None
                names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for sub_body in _container_bodies(node):
                sub_names = collect_bound_names(sub_body)
                if sub_names is None:
                    return None
                names |= sub_names
        # Everything else (Expr/docstrings, bare calls, Global/Nonlocal, Delete, ...)
        # binds nothing at module scope worth tracking here.
    return names


def _has_module_dunder_getattr(body: list[ast.stmt]) -> bool:
    """True if a module-level PEP 562 `__getattr__` is defined anywhere at module scope
    (including inside if/try/with/for/while — mirrors collect_bound_names' scope rules).
    A module using this pattern can resolve arbitrary names dynamically at first access,
    so its namespace can't be verified statically (see module docstring)."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__getattr__":
            return True
        if isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for sub_body in _container_bodies(node):
                if _has_module_dunder_getattr(sub_body):
                    return True
    return False


def _module_namespace(
    pkg_root: Path, module: str, cache: dict[str, Optional[set[str]]]
) -> tuple[bool, Optional[set[str]]]:
    """Returns (exists, namespace). namespace is None if the module exists but its
    bound-name set couldn't be determined precisely (star import, or a PEP 562
    `__getattr__`) — callers should treat that as "don't flag names against this
    module", not as "module is empty"."""
    if module in cache:
        return True, cache[module]
    target_file = resolve_module_file(pkg_root, module)
    if target_file is None:
        return False, None
    try:
        source = target_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(target_file))
    except (OSError, SyntaxError):
        cache[module] = None
        return True, None
    namespace = collect_bound_names(tree.body)
    if namespace is not None and _has_module_dunder_getattr(tree.body):
        namespace = None
    cache[module] = namespace
    return True, namespace


def scan_file(
    path: Path, pkg_root: Path, cache: dict[str, Optional[set[str]]]
) -> list[Finding]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []  # not this validator's job to police syntax

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level != 0:
            continue  # relative import — out of scope (see module docstring)
        module = node.module
        if not module or not (module == PACKAGE_NAME or module.startswith(PACKAGE_NAME + ".")):
            continue

        exists, namespace = _module_namespace(pkg_root, module, cache)
        if not exists:
            findings.append(Finding(path, node.lineno, module, None, "module-not-found"))
            continue

        for alias in node.names:
            name = alias.name
            if name == "*":
                continue
            if namespace is None:
                continue  # star import or __getattr__ elsewhere in the module — can't
                          # verify statically; assume it's fine rather than false-flag
            if name in namespace:
                continue
            if submodule_exists(pkg_root, module, name):
                continue
            findings.append(Finding(path, node.lineno, module, name, "name-not-found"))

    return findings


def iter_python_files(pkg_root: Path) -> list[Path]:
    return sorted(pkg_root.rglob("*.py"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    pkg_root = root / SCAN_ROOT

    if not pkg_root.is_dir():
        print(f"Scan root {pkg_root} does not exist — nothing to check.")
        return 0

    cache: dict[str, Optional[set[str]]] = {}
    all_findings: list[Finding] = []
    scanned = 0
    for path in iter_python_files(pkg_root):
        scanned += 1
        all_findings.extend(scan_file(path, pkg_root, cache))

    failures: list[Finding] = []
    allowlisted = 0
    for f in all_findings:
        rel = f.path.relative_to(root).as_posix()
        key = (rel, f.lineno, f.module, f.name)
        if key in ALLOWLIST:
            allowlisted += 1
            continue
        failures.append(f)

    if failures:
        print(f"\n{len(failures)} broken internal import(s) found:\n")
        for f in failures:
            rel = f.path.relative_to(root).as_posix()
            if f.reason == "module-not-found":
                print(f"  ✗ {rel}:{f.lineno}: target module {f.module!r} does not exist")
            else:
                print(
                    f"  ✗ {rel}:{f.lineno}: 'from {f.module} import {f.name}' — "
                    f"{f.name!r} is not defined, re-exported, or a submodule of {f.module!r}"
                )
        print()
        print("Every `from ts_cli.X import Y` must resolve statically — Y must be defined")
        print("or re-exported at X's module top level, or be a real submodule of X.")
        print("This is the class of bug behind audit finding 17.1 (a function-local import")
        print("of constants a refactor deleted, invisible to import-time checks and tests).")
        return 1

    suffix = f" ({allowlisted} allowlisted)" if allowlisted else ""
    print(f"No broken internal imports in {scanned} file(s) under {SCAN_ROOT}{suffix}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
