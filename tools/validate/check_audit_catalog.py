#!/usr/bin/env python3
"""
check_audit_catalog.py — the `ts audit` rule catalog is well-formed.

`ts audit`'s checks are data: YAML rules under `tools/ts-cli/ts_cli/audit/catalog/`,
read by a small rule engine. Data fails silently where code fails loudly — a mistyped
operator, scope or category id would simply never match, and the rule would report
nothing on every Model forever. This gate makes those mistakes fail the commit:
unknown keys, unknown scopes/modes/operators/data requirements/categories/profiles,
duplicate ids, a profile override of a key that defines what a rule means, band levels
not ordered worst first, and an active rule without a `fires` and a `silent` example.

The checks themselves live in `ts_cli/audit/catalog_validate.py` (one implementation,
shared with the ts-cli tests). This script only loads it from `--root` and reports.

It imports the catalog modules (catalog_model, catalog_validate, catalog_expr) and,
to learn the derived-field names rules may use, the engine's field registry
(engine/fields.py, which needs only audit/rules.py) — WITHOUT executing the `ts_cli`
package __init__, which pulls in typer, requests and the whole CLI. So it runs under
any python3 with PyYAML, including the EOL system interpreter.

Usage:
    python3 tools/validate/check_audit_catalog.py --root .

Prints `PASS  audit catalog: N rule(s), M categories`, or `FAIL` plus one line per
problem (`<file>: <id>: <message>`) and exits 1.
"""
from __future__ import annotations

import argparse
import importlib
import sys
import types
from pathlib import Path

AUDIT_REL = Path("tools/ts-cli/ts_cli/audit")


def _load_validator(root: Path) -> types.ModuleType:
    """Import ts_cli.audit.catalog_validate from `root` without the package __init__s.

    Stand-in package modules carry only `__path__`, so submodule imports resolve to
    files under `root` and nothing else of ts_cli executes. Safe only in a fresh
    process — never call this where the real ts_cli is (or will be) imported.
    """
    audit_dir = (root / AUDIT_REL).resolve()
    for name, path in (("ts_cli", audit_dir.parent), ("ts_cli.audit", audit_dir)):
        stub = types.ModuleType(name)
        stub.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = stub
    return importlib.import_module("ts_cli.audit.catalog_validate")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root)

    if not (root / AUDIT_REL / "catalog_validate.py").is_file():
        print(f"FAIL  audit catalog: {AUDIT_REL}/catalog_validate.py not found under {root}")
        return 1
    validator = _load_validator(root)
    cat, problems = validator.check_catalog(root / AUDIT_REL / "catalog")
    if problems:
        print(f"FAIL  audit catalog: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"PASS  audit catalog: {len(cat.rules)} rule(s), {len(cat.categories)} categories")
    return 0


if __name__ == "__main__":
    sys.exit(main())
