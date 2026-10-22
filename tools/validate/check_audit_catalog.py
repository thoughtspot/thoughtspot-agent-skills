#!/usr/bin/env python3
"""
check_audit_catalog.py — the `ts audit` rule catalog is well-formed.

`ts audit`'s checks are data: YAML rules under `tools/ts-cli/ts_cli/audit/catalog/`,
read by a small rule engine. Data fails silently where code fails loudly — a mistyped
operator, scope or category id would simply never match, and the rule would report
nothing on every Model forever. This gate makes those mistakes fail the commit:
unknown keys, unknown scopes/modes/operators/data requirements/categories/profiles,
conditional data a rule reads (its scope, derived fields or code, as their registries
declare) that its `requires`/`uses` do not declare — it would silently not be fetched —
and a registered field, code rule or scope whose code reads conditional data its
registration omits, or reaches code the scan cannot follow (a static scan of the
compiled code, function-local imports included — context.py is read as source, never
imported; what it covers and its evasions are in catalog_reads.py),
code-rule names that nothing registers, duplicate ids, a profile override of a key that
defines what a rule means, band levels not ordered worst first, and an active rule
without a `fires` and a `silent` example. It also fails when the generated rule tables in
`agents/cli/ts-audit/references/check-catalog.md` are stale (`ts_cli.audit.generate`,
the same check as `python -m ts_cli.audit.generate --check`) — checked whenever the
repo has the ts-audit skill directory, so a missing doc fails too.

The checks themselves live in `ts_cli/audit/catalog_validate.py` (one implementation,
shared with the ts-cli tests). This script only loads it from `--root` and reports.

It imports the catalog modules (catalog_model, catalog_validate, catalog_expr,
catalog_code, catalog_forms, catalog_uses, catalog_reads) and, to learn the names rules may use, two engine registries:
derived fields (engine/fields.py and the engine/fields_data.py and
engine/fields_human.py it imports, which need only audit/rules.py and engine/memo.py) and code rules
(engine/code_rules.py and the engine/code_rules_human.py it imports, which need
findings.py; see its docstring for what else they may import) — WITHOUT executing the `ts_cli` package __init__, which pulls in typer,
requests and the whole CLI. So it runs under any python3 with PyYAML, including the
EOL system interpreter.

With `--base <ref>` it also holds rule ids to their history (catalog_history.py): an
id present at `<ref>` that is gone now fails (retire it instead), and so does an id
retired at `<ref>` under every profile that is active again under any (a retired id is
never reused — `status` is overridable per profile, so the effective status per
profile is compared). `<ref>`'s catalog is read with `git show`, so it runs offline.
CI passes `--base origin/main`. Pre-commit passes `--merge-base-with origin/main`: the
merge base of HEAD with the local `origin/main` (no fetch), so an id that exists only
on the branch may still be dropped or renamed; without a local `origin/main` the
history check is skipped with a printed notice. A base with no catalog yet passes
with a note; one git cannot read fails.

Usage:
    python3 tools/validate/check_audit_catalog.py --root .
        [--base origin/main | --merge-base-with origin/main]

Prints `PASS  audit catalog: N rule(s), M categories`, or `FAIL` plus one line per
problem (`<file>: <id>: <message>`) and exits 1.
"""
from __future__ import annotations

import argparse
import importlib
import subprocess
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


SKILL_REL = Path("agents/cli/ts-audit")
RULES_REL = AUDIT_REL / "catalog" / "rules"


class _GitError(Exception):
    pass


def _git(root: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if res.returncode != 0:
        lines = (res.stderr or res.stdout).strip().splitlines()
        raise _GitError(lines[-1] if lines else f"git {args[0]} exited {res.returncode}")
    return res.stdout


def _merge_base(root: Path, ref: str):
    """`git merge-base HEAD <ref>`, or None when `ref` does not exist locally (no
    fetch is ever made: pre-commit runs offline)."""
    probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet",
                            f"{ref}^{{commit}}"], capture_output=True, text=True)
    if probe.returncode != 0:
        return None
    return _git(root, "merge-base", "HEAD", ref).strip()


def _yaml(text: str):
    import yaml
    return yaml.safe_load(text)


def _base_rules(root: Path, ref: str):
    """`ref`'s rule files as `{"rules/<name>": [entries]}`; None when it has none."""
    import yaml
    _git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    names = [n for n in _git(root, "ls-tree", "--name-only", ref, f"{RULES_REL}/").split()
             if n.endswith(".yaml")]
    if not names:
        return None
    return {f"rules/{Path(n).name}": yaml.safe_load(_git(root, "show", f"{ref}:{n}")) or []
            for n in names}


def _history(root: Path, ref: str) -> tuple:
    """(problems, note) for rule ids against `ref`."""
    history = importlib.import_module("ts_cli.audit.catalog_history")
    model = importlib.import_module("ts_cli.audit.catalog_model")
    try:
        base = _base_rules(root, ref)
    except _GitError as exc:
        return [f"--base {ref}: cannot read it with git ({exc})"], ""
    if base is None:
        return [], f"no rule catalog at {ref} — nothing to compare"
    head_raw = model.load_raw(root / AUDIT_REL / "catalog")
    try:
        base["profiles.yaml"] = _yaml(_git(root, "show",
                                          f"{ref}:{AUDIT_REL}/catalog/profiles.yaml")) or []
    except _GitError:
        base["profiles.yaml"] = []
    head = history.rule_entries(head_raw)
    old = history.rule_entries(base)
    problems = history.history_problems(old, head, ref,
                                        history.profile_ids(head_raw, base))
    return problems, f"rule ids vs {ref}: {len(old)} at base, none removed or reused"


def _doc_problems(root: Path) -> list:
    """Stale generated tables in check-catalog.md. Skipped only where the repo has no
    ts-audit skill directory at all (a catalog-only copy, as the gate's tests make)."""
    if not (root / SKILL_REL).is_dir():
        return []
    generate = importlib.import_module("ts_cli.audit.generate")
    return generate.check(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--base", default=None,
                        help="git ref whose rule ids must survive (removed -> retired)")
    parser.add_argument("--merge-base-with", default=None, metavar="REF",
                        help="like --base, against `git merge-base HEAD REF`; skipped "
                             "with a notice when REF does not exist locally")
    args = parser.parse_args()
    root = Path(args.root)
    skipped = ""
    if args.merge_base_with and not args.base:
        try:
            args.base = _merge_base(root, args.merge_base_with)
        except _GitError as exc:
            print(f"FAIL  audit catalog: --merge-base-with {args.merge_base_with}: {exc}")
            return 1
        if args.base is None:
            skipped = (f"NOTE  audit catalog: rule-id history not checked — "
                       f"{args.merge_base_with} does not exist locally")

    if not (root / AUDIT_REL / "catalog_validate.py").is_file():
        print(f"FAIL  audit catalog: {AUDIT_REL}/catalog_validate.py not found under {root}")
        return 1
    validator = _load_validator(root)
    cat, problems = validator.check_catalog(root / AUDIT_REL / "catalog")
    if not problems:
        problems = _doc_problems(root)
    note = ""
    if args.base and cat is not None:  # a catalog the loader could read
        history, note = _history(root, args.base)
        problems = problems + history
    if problems:
        print(f"FAIL  audit catalog: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"PASS  audit catalog: {len(cat.rules)} rule(s), {len(cat.categories)} categories")
    if note:
        print(f"PASS  audit catalog: {note}")
    if skipped:
        print(skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
