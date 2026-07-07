#!/usr/bin/env python3
"""
check_pagination_convention.py — fail if a `record_size` literal in ts-cli is
hard-capped without a pagination loop.

ts-cli.md's output conventions promise: "Pagination — Auto-paginate internally; caller
always gets the full result set." 2026-07 audit finding 14.2 found three commands that
violated it — `ts variables search` (hard-capped at 50, `variables.py:37-41`),
`ts metadata search` (single-page unless `--all`, same truncation class as the ts-audit
2.4.0 false-orphan bug), and `ts users`/`ts groups` (default `--limit 20`) — all fixed
in ts-cli v0.28.0 (PR #173). This validator makes the fix permanent.

Rule: a `"record_size": <int literal>` (or `record_size=<int literal>`) dict/keyword
entry is fine when the literal is `-1` (ThoughtSpot's "return everything" sentinel —
see `_build_dependents_payload` in commands/metadata.py). Any OTHER literal is only
fine when the innermost enclosing function also contains a pagination loop — a `while`
statement, or a mutation of a variable literally named `record_offset` — anywhere in
that function's own body. A literal `record_size` fed by a *parameterized* page-size
variable (e.g. `"record_size": page_size` next to a `while True: ... offset += page_size`
loop, the pattern every `search` command in this CLI now uses) never triggers this
check at all, because the AST value is a Name, not a Constant — only a hard literal is
suspect.

Why AST, function-scoped (not a flat regex): the offending shape is "this call always
asks for the same N records with no loop around it" — a per-function property. A flat
regex can't tell a hard-capped call from a paginated one; it would have to also verify
absence of a nearby `while`, which is exactly what AST scoping gives for free. Scoping
to the *innermost* enclosing function (nested defs are analyzed separately, not folded
into the outer function's while-loop) avoids two failure modes: a literal in a small
helper wrongly cleared by an unrelated while loop elsewhere in a big outer function, and
a real bug hidden because SOME function in the file happens to loop.

ALLOWLIST: legitimate bounded, non-paginated probes — a single-record existence check,
or a small-N name lookup immediately followed by an in-memory exact-match filter (never
returns unfiltered "search results" to a caller, so silent truncation past N is not the
same failure class the audit found in the user-facing `search` commands). Each entry
needs a one-line justification comment; see below.

Exit codes:
  0 — no un-paginated literal record_size found outside the allowlist
  1 — at least one found

Run manually:
    python3 tools/validate/check_pagination_convention.py --root .
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Directory scanned — the pagination convention is a ts-cli output contract
# (ts-cli.md), not a repo-wide rule, so this deliberately doesn't scan agents/.
SCAN_ROOT = "tools/ts-cli/ts_cli"

# ThoughtSpot's "return everything, no pagination" sentinel — never suspect.
UNLIMITED_SENTINEL = -1

# (relative_path, qualified_function_name) -> justification.
# Add an entry here only for a literal record_size that is a bounded, exact-match
# lookup — never a "return search results to the caller" path (those must paginate).
ALLOWLIST: dict[tuple[str, str], str] = {
    ("ts_cli/commands/metadata.py", "get_object"):
        "record_size=1 GUID lookup — a GUID identifies at most one object, "
        "so there is nothing to paginate over.",
    ("ts_cli/commands/tables.py", "_find_guid_by_name"):
        "record_size=10 exact-name lookup used only to seed a local "
        "`r.get('metadata_name') == name` filter — a small buffer against "
        "near-duplicate names, not a result set returned to the caller.",
    ("ts_cli/commands/tml.py", "import_tml"):
        "record_size=10 GUID backfill: searches by the exact name just imported "
        "to recover a GUID the import response omitted, then filters for an exact "
        "match — bounded lookup, not a listing.",
    ("ts_cli/report/resolver.py", "resolve_source"):
        "record_size=1 (GUID) and record_size=10 (exact-name) lookups in the same "
        "source-resolution function; the name-lookup branch already raises "
        "SourceAmbiguousError when more than one exact match comes back, so a "
        "caller is never silently handed a truncated page.",
    ("ts_cli/commands/dependency_apply.py", "_current_modified"):
        "record_size=1 GUID drift-check lookup (BL-083 apply-change) — reads a single "
        "object's metadata_header.modified by GUID; a GUID identifies at most one "
        "object and the result is never returned as a listing.",
}


def _iter_own_body(node: ast.AST):
    """Yield every descendant of node's own statements, without descending into
    nested function/async-function/lambda bodies — those are scanned separately as
    their own scope so a literal isn't cleared by an unrelated loop elsewhere."""
    body = getattr(node, "body", None)
    if body is None:
        return
    pending = list(body)
    while pending:
        n = pending.pop()
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        pending.extend(ast.iter_child_nodes(n))


def _has_pagination_loop(own_nodes: list[ast.AST]) -> bool:
    for n in own_nodes:
        if isinstance(n, ast.While):
            return True
        # `record_offset` variable mutation — the heuristic's second signal.
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "record_offset":
                    return True
        if isinstance(n, ast.AugAssign):
            if isinstance(n.target, ast.Name) and n.target.id == "record_offset":
                return True
    return False


def _record_size_literals(own_nodes: list[ast.AST]) -> list[tuple[int, int]]:
    """Return (lineno, value) for every literal (non -1) record_size found directly
    in own_nodes — both `{"record_size": N}` dict entries and `record_size=N`
    keyword arguments."""
    hits: list[tuple[int, int]] = []
    for n in own_nodes:
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if (isinstance(k, ast.Constant) and k.value == "record_size"
                        and isinstance(v, ast.Constant) and isinstance(v.value, int)
                        and not isinstance(v.value, bool)
                        and v.value != UNLIMITED_SENTINEL):
                    hits.append((getattr(v, "lineno", getattr(n, "lineno", 0)), v.value))
        elif isinstance(n, ast.Call):
            for kw in n.keywords:
                if (kw.arg == "record_size" and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, int)
                        and not isinstance(kw.value.value, bool)
                        and kw.value.value != UNLIMITED_SENTINEL):
                    hits.append((getattr(kw.value, "lineno", getattr(n, "lineno", 0)),
                                 kw.value.value))
    return hits


def scan_file(path: Path) -> list[tuple[int, int, str]]:
    """Return (lineno, value, qualname) for each un-paginated literal record_size
    found in this file. Empty list = clean."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if "record_size" not in source:
        return []  # fast path
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []  # not our job to police syntax

    findings: list[tuple[int, int, str]] = []

    def _check_scope(node: ast.AST, qualname: str) -> None:
        own_nodes = list(_iter_own_body(node))
        literals = _record_size_literals(own_nodes)
        if literals and not _has_pagination_loop(own_nodes):
            for lineno, value in literals:
                findings.append((lineno, value, qualname))

    def _visit(node: ast.AST, func_stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = ".".join(func_stack + [child.name])
                _check_scope(child, qualname)
                _visit(child, func_stack + [child.name])
            else:
                _visit(child, func_stack)

    _check_scope(tree, "<module>")
    _visit(tree, [])

    return findings


def iter_python_files(root: Path) -> list[Path]:
    base = root / SCAN_ROOT
    if not base.is_dir():
        return []
    return sorted(base.rglob("*.py"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    failures: list[str] = []
    scanned = 0
    for path in iter_python_files(root):
        rel = path.relative_to(root)
        scanned += 1
        for lineno, value, qualname in scan_file(path):
            # ALLOWLIST is keyed relative to tools/ts-cli/ (i.e. "ts_cli/...").
            key = (str(rel.relative_to("tools/ts-cli")), qualname)
            if key in ALLOWLIST:
                continue
            failures.append(
                f"  ✗ {rel}:{lineno}  {qualname}()  record_size={value} literal with "
                f"no pagination loop in scope"
            )

    if failures:
        print(f"\n{len(failures)} un-paginated record_size literal(s) found:\n")
        print("\n".join(failures))
        print()
        print("ts-cli.md: 'Pagination — Auto-paginate internally; caller always gets")
        print("the full result set.' Either add a while-loop pagination pattern (see")
        print("`ts metadata search` / `ts users search`), or if this is a bounded")
        print("exact-match lookup (never a listing returned to the caller), add it to")
        print("ALLOWLIST in this file with a one-line justification.")
        return 1

    print(f"No un-paginated record_size literals in {scanned} ts-cli file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
