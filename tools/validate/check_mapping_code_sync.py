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

**C — the Excel / Google Sheets translator agrees with its function maps.** (gate)
``ts_cli/excel/`` has no ``ts-convert-*`` skill, so discovery never finds it; it is checked
here directly, more strictly than the converters, because its rule table is data
(``ts_cli/excel/rules.py``, read with ``ast``). For every rule: the map
(``docs/function-maps/ts-excel-function-mapping.md`` or the Sheets delta map) rows the function;
every ThoughtSpot name the rule emits appears in that row's text (``CRITERIA_EMITS`` in the
criteria-string table) and is a catalogued function (the formula reference's table, or the
vendored ``EXTRAS`` in ``formula_translate/catalog.py``), never a disproved one; and each map's
*Translator coverage* list names exactly the rule table's keys for that map. Requirement A
also runs over ``ts_cli/excel/*.py``.

The declared ``emits`` are only half of it (PR #570 review L1): a handler could emit a name it
never declared. So C also **runs every handler** — ``translate_excel`` over synthetic calls of
arity 0–4 drawn from a small argument pool (a row reference, a range, numbers, strings) — and
fails when an emitted function is outside that rule's ``emits`` plus ``SHARED_EMITS`` (the
names the shared machinery adds whatever the rule: ``to_string`` in ``&``, ``isnull`` / ``not``
in blank tests), or is disproved or uncatalogued. And a disproved name written as a call
(``"nullif ("``) in any string literal of ``ts_cli/excel/`` fails, whatever path builds it.

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


# ---------------------------------------------------------------------------
# C — the Excel / Sheets translator (no ts-convert-* skill, so not discovered)
# ---------------------------------------------------------------------------

EXCEL_CODE_REL = "tools/ts-cli/ts_cli/excel"
EXCEL_RULES_REL = "tools/ts-cli/ts_cli/excel/rules.py"
VENDORED_CATALOG_REL = "tools/ts-cli/ts_cli/formula_translate/catalog.py"
EXCEL_MAPS = {"excel": "docs/function-maps/ts-excel-function-mapping.md",
              "sheets": "docs/function-maps/ts-sheets-function-mapping.md"}
COVERAGE_START = "<!-- translator-coverage:start -->"
COVERAGE_END = "<!-- translator-coverage:end -->"


def literal_assignments(source: str) -> dict:
    """Top-level ``NAME = <literal>`` assignments of a module, evaluated with ``ast``."""
    out = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return out


def map_rows(text: str) -> dict[str, str]:
    """``NAME`` -> that function row's full line, for every ``| `NAME(…)` |`` row."""
    rows = {}
    for line in text.splitlines():
        m = re.match(r"^\| `([A-Z][A-Z0-9_.]*)\(", line)
        if m:
            rows[m.group(1)] = line
    return rows


def coverage_list(text: str):
    """Backticked names between the coverage markers, or None when the markers are absent."""
    if COVERAGE_START not in text or COVERAGE_END not in text:
        return None
    block = text.split(COVERAGE_START, 1)[1].split(COVERAGE_END, 1)[0]
    return set(re.findall(r"`([A-Z][A-Z0-9_.]*)`", block))


def _mentions(text: str, name: str) -> bool:
    return re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text) is not None


def excel_rule_errors(rules_src: str, maps: dict[str, str], valid: set[str],
                      nonexistent: set[str], extras: set[str]) -> list[str]:
    """Requirement C over a rules module's source and the two maps' texts."""
    data = literal_assignments(rules_src)
    errors: list[str] = []
    tables = {"FUNCTION_RULES": data.get("FUNCTION_RULES", {}),
              "SHEETS_RULES": data.get("SHEETS_RULES", {})}
    known = valid | extras
    for table, rules in tables.items():
        for name, rule in rules.items():
            key = rule.get("map", "excel")
            text = maps.get(key, "")
            row = map_rows(text).get(rule.get("row", name))
            if row is None:
                errors.append(f"{table}[{name!r}]: the {key} map has no `{name}(` row — the "
                              "translator implements a function its map does not row")
                continue
            for emitted in rule.get("emits", ()):
                errors.extend(_emitted_errors(table, name, emitted, row, key, known, nonexistent))
    criteria = text_between(maps.get("excel", ""), "### Criteria strings", "\n## ")
    for emitted in data.get("CRITERIA_EMITS", ()):
        if not _mentions(criteria, emitted):
            errors.append(f"CRITERIA_EMITS: `{emitted}` does not appear in the Excel map's "
                          "criteria-string table")
    for key, keys in (("excel", set(tables["FUNCTION_RULES"])), ("sheets", set(tables["SHEETS_RULES"]))):
        listed = coverage_list(maps.get(key, ""))
        if listed is None:
            errors.append(f"the {key} map has no translator-coverage list ({COVERAGE_START} … "
                          f"{COVERAGE_END}) naming the rows the translator backs")
        elif listed != keys:
            errors.append(f"the {key} map's translator-coverage list disagrees with rules.py: "
                          f"listed but not translated {sorted(listed - keys)}, translated but "
                          f"not listed {sorted(keys - listed)}")
    return errors


def _emitted_errors(table, name, emitted, row, key, known, nonexistent) -> list[str]:
    out = []
    if emitted in nonexistent:
        out.append(f"{table}[{name!r}] emits `{emitted}`, which the catalog marks as NOT a "
                   "ThoughtSpot function")
    elif emitted not in known and not emitted.startswith("sql_"):
        out.append(f"{table}[{name!r}] emits `{emitted}`, which is not in the formula catalog")
    if not _mentions(row, emitted):
        out.append(f"{table}[{name!r}] emits `{emitted}`, but the {key} map's `{name}` row never "
                   "mentions it — the code does something its row does not say")
    return out


def text_between(text: str, start: str, end: str) -> str:
    if start not in text:
        return ""
    rest = text.split(start, 1)[1]
    return rest.split(end, 1)[0] if end in rest else rest


_ARG_POOL = ("[@a]", "T[b]", "2", "0", '"M"', '""')
_WIDE_POOL = ("T[b]", '"x"', "[@a]>1", "[@a]")
# Nested shapes the idiom rules key on: IFERROR(a/b, 0), ISNUMBER(SEARCH(…)), IF(b=0,0,a/b).
_NESTED_POOL = ("[@a]/[@b]", 'SEARCH("x",[@a])', "VALUE([@a])", "[@b]=0", "0", "[@a]")
_CALL_NAME = re.compile(r"(?<![\w])([a-z_][a-z0-9_]*(?: count)?)\s*\(")
_QUOTED = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"\\]|\\.)*\"")


def _synthetic_calls(name: str):
    """(formula, its arguments) for the call shapes the gate runs."""
    from itertools import product
    shapes = [(_ARG_POOL, a) for a in range(0, 4)] + [(_WIDE_POOL, 4)] + \
        [(_NESTED_POOL, a) for a in range(1, 4)]
    for pool, arity in shapes:
        for args in product(pool, repeat=arity):
            yield f"={name}({','.join(args)})", args


def emitted_by_handlers(root: Path) -> dict:
    """{(table, rule): set of function names its handler actually emitted}, by running it."""
    code_root = str(root / "tools" / "ts-cli")
    sys.path.insert(0, code_root)
    try:
        from ts_cli.excel import rules
        from ts_cli.excel.translate import translate_excel
        from ts_cli.formula_translate.context import ColumnContext
    finally:
        sys.path.remove(code_root)
    def names(src: str, dialect: str) -> set:
        expr = translate_excel(src, ColumnContext(), dialect=dialect).expr
        return set(_CALL_NAME.findall(_QUOTED.sub("''", expr))) if expr else set()

    out: dict = {}
    for table, dialect, rule_table in (("FUNCTION_RULES", "excel", rules.FUNCTION_RULES),
                                       ("SHEETS_RULES", "google_sheets", rules.SHEETS_RULES)):
        own = {a: names("=" + a, dialect) for a in set(_ARG_POOL + _WIDE_POOL + _NESTED_POOL)}
        for name in rule_table:
            seen: set = set()
            for src, args in _synthetic_calls(name):
                # what the arguments emit on their own is not this handler's emission
                seen.update(names(src, dialect) - set().union(*(own[a] for a in args)))
            out[(table, name)] = seen - {"if", "and", "or", "not", "in"} | (
                {"not"} & seen)
    return out


def emission_errors(emitted: dict, rules_src: str, valid: set[str], nonexistent: set[str],
                    extras: set[str]) -> list[str]:
    data = literal_assignments(rules_src)
    shared = set(data.get("SHARED_EMITS", ()))
    errors = []
    for (table, name), names in sorted(emitted.items()):
        declared = set(data.get(table, {}).get(name, {}).get("emits", ())) | shared
        for fn in sorted(names):
            if fn in nonexistent:
                errors.append(f"{table}[{name!r}]'s handler emitted `{fn}`, which the catalog "
                              "marks as NOT a ThoughtSpot function")
            elif fn not in valid | extras and not fn.startswith("sql_"):
                errors.append(f"{table}[{name!r}]'s handler emitted `{fn}`, which is not in "
                              "the formula catalog")
            elif fn not in declared:
                errors.append(f"{table}[{name!r}]'s handler emitted `{fn}`, which its rule does "
                              "not declare in `emits` (so its map row is never checked for it)")
    return errors


def disproved_literal_errors(code_files: list, nonexistent: set[str], root: Path) -> list[str]:
    """A disproved name written as a call inside any string literal (not a docstring)."""
    errors = []
    pattern = re.compile(r"(?<![\w`])(" + "|".join(sorted(map(re.escape, nonexistent))) +
                         r")\s*\(") if nonexistent else None
    for path in code_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in skip and pattern and pattern.search(node.value):
                errors.append(f"{path.relative_to(root)}:{node.lineno}: a string literal "
                              f"builds `{pattern.search(node.value).group(1)} (`, which the "
                              "catalog marks as NOT a ThoughtSpot function")
    return errors


def check_excel(root: Path, valid: set[str], nonexistent: set[str]) -> tuple[list, list]:
    code_dir = root / EXCEL_CODE_REL
    if not code_dir.is_dir():
        return [], []
    maps = {k: (root / v).read_text(encoding="utf-8") if (root / v).exists() else ""
            for k, v in EXCEL_MAPS.items()}
    extras = set(literal_assignments(
        (root / VENDORED_CATALOG_REL).read_text(encoding="utf-8")).get("EXTRAS", {}))
    rules_src = (root / EXCEL_RULES_REL).read_text(encoding="utf-8")
    code_files = sorted(code_dir.glob("*.py"))
    errors = excel_rule_errors(rules_src, maps, valid, nonexistent, extras)
    errors += disproved_literal_errors(code_files, nonexistent, root)
    try:
        emitted = emitted_by_handlers(root)
    except Exception as exc:  # the gate must not pass because the code failed to import
        errors.append(f"could not run the Excel handlers to check what they emit: "
                      f"{type(exc).__name__}: {exc}")
        emitted = {}
    errors += emission_errors(emitted, rules_src, valid, nonexistent, extras)
    e, w = check_platform("excel", code_files, "\n".join(maps.values()),
                          valid, nonexistent, root)
    return errors + e, w


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
    if not platforms and not (root / EXCEL_CODE_REL).is_dir():
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

    e, w = check_excel(root, valid, nonexistent)
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
    print(f"PASS  mapping/code sync: {len(platforms)} platform(s) + the Excel/Sheets "
          f"translator checked, no translator emits a disproved ThoughtSpot function, and "
          f"every Excel/Sheets rule agrees with its map row{suffix}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
