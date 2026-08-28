#!/usr/bin/env python3
"""check_mapping_code_sync.py — the mapping docs and the translator code must agree.

A formula mapping doc (``agents/shared/mappings/<platform>/*.md``) and its Python
translator (``ts_cli/<platform>/`` or ``ts_cli/sv_*.py``) are **two hand-maintained
copies of one ruleset**, and nothing compared them until this validator. Each side
had its own gate and both passed while disagreeing:

* ``check_formula_catalog.py`` reads ``mapping_dir.rglob("*.md")`` — **markdown only**.
  It never opens a ``.py``, so a translator emitting a non-existent ThoughtSpot
  function is invisible to it.
* ``check_mirror_sync.py`` compares ``synced-from`` **version markers**, not content.
* Only two platforms ever grew an in-process cross-check by hand
  (``test_qlik_functions.py::TestMapIntegrity``, and the domo equivalent added in
  PR #440). Every other converter had none.

The cost of that gap is on the record. ``sv_sql.py`` emitted the six BL-171
string functions — ``upper``/``lower``/``trim``/``ltrim``/``rtrim``/``replace``,
live-disproved on se-thoughtspot, rejected at import with error_code 14516 — for
**three CLI versions after the mapping rows had already been corrected**
(``agents/SYNC-DEBT.md`` records the v1.19.2 → v1.19.5 lag). The doc was right, the
code was wrong, and the doc-only gate could not see it. PR #440 then shipped the
same class in a new converter.

Why the doc cannot simply be generated from the code, or vice versa: the doc is
**executable in its own right**. The CoCo Snowsight runtime has no shell and no
``ts`` CLI, so there the *model* performs the translation by reading these tables
(``agents/coco-snowsight/ts-convert-from-snowflake-sv/SKILL.md`` marks it MANDATORY
under I7). The Python serves the CLI runtime. Two consumers, two representations,
one ruleset — so the only durable answer is to assert they agree.

Requirements
------------

**A — no translator may emit a disproved ThoughtSpot function name.** (gate)
Any string in an emitted-name position whose value the catalog marks
**non-existent** (a ``~~`name`~~`` row in
``agents/shared/schemas/thoughtspot-formula-patterns.md``) fails. This is BL-170 /
BL-171 generalised from the two hand-written tests to every converter.

**B — a source construct the code translates should appear in the platform's doc.**
(soft) Catches the code-ahead-of-doc direction: ``sv_sql.py:307`` maps
``LOCATE -> strpos`` and no Snowflake mapping doc mentions ``LOCATE``, so the CoCo
runtime — which has only the doc — cannot translate it.

A third requirement was drafted and **cut**: "an emitted name absent from the
catalog entirely is *unverified*, report it". Measured against the real tree it
produced **190 findings and no unique true positives** — a translator is full of
dicts that are not function maps (``{"STRING": "string"}`` type maps, ``{"kind":
"lit"}`` AST builders, status enums), so every lowercase dict value read as a
candidate function name: ``string``, ``double``, ``condition``, ``lit``, ``binop``,
``true``, ``raw``. The one real case it found (``sv_sql.py``'s ``ZEROIFNULL``,
absent from the catalog) is already reported by requirement B, which keys on the
*source* name instead. A check at that signal-to-noise ratio trains its reader to
ignore the output — the same failure mode as a gate that manufactures divergences.
Distinguishing a function map from a type map needs a per-module declaration, which
is the hand-maintained registry this validator exists to make unnecessary.

**Emitted-name position** is the load-bearing definition. A translator's dicts do
NOT share one shape: ``_RENAME`` is ``{platform: ts}``, ``_PASS_THROUGH_HINT`` is
``{platform: "sql_string_op"}``, ``_ARG_SWAP`` is ``{platform: (ts, arity)}``,
``_DATEDIFF_UNIT`` is ``{unit: ts}`` — its keys are date units, not functions — and
several maps are bare ``frozenset``s with no values at all. So a name is treated as
emitted only when it is a **dict value, or a string inside a tuple that is a dict
value**. That deliberately excludes docstrings and comments: ``sv_sql.py:245-248``
carries a comment naming all six BL-171 functions precisely to explain that they are
absent, and a scan that read prose would fail on the very comment documenting the
fix. (``check_converter_parity`` shipped with exactly that bug — a comment satisfying
a requirement — so it is not hypothetical.)

Scope is **discovered, never listed**: platforms and their code locations come from
``check_formula_catalog.parse_catalog`` and ``check_converter_parity``'s discovery,
imported rather than reimplemented. A platform whose docs cannot be located is a hard
failure telling the author to add an override — a new converter must not be silently
skipped, which is how the pre-BL-110 validators reported PASS.

Exit codes:
  0 — no disproved name is emitted (warnings may still print)
  1 — a disproved emitted name, or an unresolvable platform

Run manually:
    python3 tools/validate/check_mapping_code_sync.py --root .
    python3 tools/validate/check_mapping_code_sync.py --root . --warnings
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

from check_converter_parity import _routed_re, discover_platforms, resolve_code_files
from check_formula_catalog import parse_catalog

CATALOG_REL = "agents/shared/schemas/thoughtspot-formula-patterns.md"
MAPPINGS_REL = "agents/shared/mappings"

# Platforms whose mapping-doc directory is not `<platform>` or `ts-<platform>`.
# Everything else resolves by that convention, so this stays near-empty by design.
PLATFORM_DOC_OVERRIDES: dict[str, tuple[str, ...] | None] = {
    # Both warehouse converters file their docs by warehouse, not by artifact:
    # `snowflake-sv` -> ts-snowflake/, `databricks-mv` -> ts-databricks/.
    "snowflake-sv": ("ts-snowflake",),
    "databricks-mv": ("ts-databricks",),
    # Looker is mapping-only and ships no translator, so there is no code side to
    # compare. `resolve_code_files` already returns no files for it; this entry
    # records that the absence is intentional rather than an unresolved platform.
    "looker": None,
}

# A ThoughtSpot function name: lowercase, may contain `_` or a space
# (`unique count` is one function — an underscore there is rejected by the parser).
_TS_NAME_RE = re.compile(r"^[a-z][a-z0-9_ ]{1,40}$")

# Emitted values that are pass-through wrappers or internal dispatch targets, not
# ThoughtSpot function names. `sql_*_op` is a real TS construct but takes the source
# function as a string argument, so it is never itself a catalog entry.
_NOT_A_FUNCTION_RE = re.compile(r"^(sql_\w+_op|_\w+)$")


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """`id()` of every string Constant that is a docstring.

    Docstrings are `ast.Expr` statements, so they would otherwise read as ordinary
    string literals. They must not count as emitted names — see the module docstring
    on why a prose mention must never satisfy or trip a requirement.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef)):
            continue
        body = getattr(node, "body", None) or []
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.add(id(body[0].value))
    return out


def _strings_in(value: ast.expr) -> list[ast.Constant]:
    """String constants in a dict-value position: the value, or inside a tuple/list."""
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return [value]
    if isinstance(value, (ast.Tuple, ast.List)):
        return [e for e in value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def extract_maps(path: Path) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Return (emitted_names, source_keys) as (name, lineno) pairs.

    `emitted_names` are strings in a dict-value position — what the translator can
    write into a formula. `source_keys` are upper-case dict keys whose value looks
    like a TS function name — the platform-side construct being translated.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return [], []

    skip = _docstring_nodes(tree)
    emitted: list[tuple[str, int]] = []
    keys: list[tuple[str, int]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            strings = [c for c in _strings_in(value) if id(c) not in skip]
            named = [c.value for c in strings
                     if _TS_NAME_RE.match(c.value)
                     and not _NOT_A_FUNCTION_RE.match(c.value)]
            for const in strings:
                if id(const) not in skip:
                    emitted.append((const.value, const.lineno))
            # Only treat the key as a source construct when the value actually
            # looks like a translation target; that is what separates
            # `{"LOCATE": ("strpos", 2)}` from `{"YEAR": "year"}`-shaped unit maps
            # only loosely, so C is a warning rather than a gate.
            if (named and isinstance(key, ast.Constant)
                    and isinstance(key.value, str) and key.value.isupper()):
                keys.append((key.value, key.lineno))
    return emitted, keys


def resolve_doc_files(root: Path, platform: str) -> tuple[list[Path], bool]:
    """Return (mapping .md files, resolved) for a platform."""
    mappings = root / MAPPINGS_REL
    if platform in PLATFORM_DOC_OVERRIDES:
        dirs = PLATFORM_DOC_OVERRIDES[platform]
        if dirs is None:
            return [], True
        out: list[Path] = []
        for name in dirs:
            out.extend(sorted((mappings / name).rglob("*.md")))
        return out, bool(out)

    for candidate in (platform, f"ts-{platform}"):
        d = mappings / candidate
        if d.is_dir():
            return sorted(d.rglob("*.md")), True
    return [], False


def check_platform(platform: str, code_files: list[Path], doc_text: str,
                   valid: set[str], nonexistent: set[str],
                   root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    # A disproved name is legitimate as an INTERMEDIATE MARKER when the package also
    # routes it to a `sql_*_op` pass-through: `qlik/functions.py:135` maps
    # `"upper": "upper"` and `PASSTHROUGH_MAP:43` rewrites it to
    # `("sql_string_op", "UPPER({0})", 1)`, so nothing bare is ever emitted. The
    # first cut of this validator flagged all six Qlik and three PowerBI markers —
    # `check_converter_parity`'s docstring warns about precisely this, and the
    # routing test is imported from it rather than restated so the two gates cannot
    # disagree about what "routed" means.
    package_source = "\n".join(
        p.read_text(encoding="utf-8") for p in code_files if p.is_file()
    )

    for path in code_files:
        rel = path.relative_to(root)
        emitted, keys = extract_maps(path)

        for name, lineno in emitted:
            if name in nonexistent and _routed_re(name).search(package_source):
                continue
            if name in nonexistent:
                errors.append(
                    f"{rel}:{lineno}: emits `{name}`, which the catalog marks as NOT a "
                    f"ThoughtSpot function (BL-170/BL-171, live-disproved — an import "
                    f"rejects it with error_code 14516). The mapping doc may already be "
                    f"correct; this is the code side. Route it through a `sql_*_op` "
                    f"pass-through (see qlik/functions.py PASSTHROUGH_MAP)."
                )

        for name, lineno in keys:
            if doc_text and name.lower() not in doc_text.lower():
                warnings.append(
                    f"{rel}:{lineno}: translates `{name}`, which no {platform} mapping "
                    f"doc mentions. The CoCo runtime reads only the doc, so it cannot "
                    f"translate this construct. Add a row."
                )

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--warnings", action="store_true",
                        help="Print soft findings (requirements B and C)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    catalog = root / CATALOG_REL
    if not catalog.exists():
        print(f"ERROR: catalog not found: {catalog}", file=sys.stderr)
        return 1
    valid, nonexistent = parse_catalog(catalog.read_text(encoding="utf-8"))

    platforms = discover_platforms(root)
    if not platforms:
        print(f"No ts-convert-* skills found under {root}/agents/cli/. Nothing to check.")
        return 0

    errors: list[str] = []
    warnings: list[str] = []

    for platform in platforms:
        code_files, code_ok = resolve_code_files(root, platform)
        if not code_ok:
            errors.append(
                f"{platform}: cannot locate its CLI code — see PLATFORM_CODE_OVERRIDES "
                f"in check_converter_parity.py. (Failing loudly is deliberate: a new "
                f"converter must not be silently skipped.)"
            )
            continue
        if not code_files:
            continue  # mapping-only converter, documented as having no translator

        doc_files, doc_ok = resolve_doc_files(root, platform)
        if not doc_ok:
            errors.append(
                f"{platform}: emits formulas from {code_files[0].parent.name}/ but no "
                f"mapping docs were found under {MAPPINGS_REL}/{platform}/ or "
                f"{MAPPINGS_REL}/ts-{platform}/. Add the directory, or an entry to "
                f"PLATFORM_DOC_OVERRIDES in this file (None if it genuinely has none)."
            )
            continue

        doc_text = "\n".join(p.read_text(encoding="utf-8") for p in doc_files)
        e, w = check_platform(platform, code_files, doc_text, valid, nonexistent, root)
        errors.extend(e)
        warnings.extend(w)

    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    if args.warnings:
        for w in warnings:
            print(f"WARN:  {w}", file=sys.stderr)

    if errors:
        print(f"\nFAIL  mapping/code sync: {len(errors)} disproved-name or "
              f"unresolvable-platform error(s).", file=sys.stderr)
        return 1

    suffix = (f" ({len(warnings)} soft finding(s); re-run with --warnings)"
              if warnings and not args.warnings else "")
    print(f"PASS  mapping/code sync: {len(platforms)} platform(s) checked, "
          f"no translator emits a disproved ThoughtSpot function{suffix}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
