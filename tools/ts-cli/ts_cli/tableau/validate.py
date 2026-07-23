"""Pre-import and output validation for translated Tableau formulas.

Pure functions, no I/O. Flags forbidden syntax patterns and structural
issues (unbalanced brackets, orphaned if/then/else, unresolved refs) before
a formula is sent to ThoughtSpot import.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# 15. Validation
# ---------------------------------------------------------------------------

_FORBIDDEN_PATTERNS = [
    (re.compile(r"(?<!\[)\bEND\b(?!\])", re.IGNORECASE), "bare 'END' keyword"),
    (re.compile(r"(?<!\[)\bCASE\b(?!\])", re.IGNORECASE), "bare 'CASE' keyword"),
    (re.compile(r"(?<!\[)\bWHEN\b(?!\])", re.IGNORECASE), "bare 'WHEN' keyword"),
    (re.compile(r"\bunique_count\b"), "'unique_count' (should be 'unique count')"),
    (re.compile(r"\bdate_trunc\b", re.IGNORECASE), "'date_trunc' (should be 'start_of_*')"),
    (re.compile(r"\bELSEIF\b", re.IGNORECASE), "'ELSEIF' (should be 'else if')"),
    (re.compile(r"\bNOT\s+IN\s*\(", re.IGNORECASE), "'NOT IN (...)' (unsupported in ThoughtSpot — rewrite as negated conditions)"),
]

# Tableau functions with no ThoughtSpot equivalent (or not yet implemented).
# Formulas containing them are skipped with a reason instead of failing at
# TML import, where the retry loop silently drops them.
_UNMAPPED_FUNCTIONS = [
    "SPLIT", "PROPER", "ASCII", "CHAR",
    # REGEXP_EXTRACT_NTH has no documented pass-through template (unlike its
    # siblings REGEXP_MATCH/REGEXP_EXTRACT/REGEXP_REPLACE/FINDNTH, wired in
    # functions.py::_ARG_HANDLERS as of ts-cli v0.81.0 — see
    # tableau-formula-translation.md lines ~989-996) — still rejected here.
    "REGEXP_EXTRACT_NTH",
    "MAKEDATE", "MAKETIME", "MAKEDATETIME", "ISDATE",
    "USERNAME", "FULLNAME", "ISUSERNAME", "ISFULLNAME", "USERDOMAIN",
    "ACOS", "ASIN", "ATAN", "COT",  # inverse trig + COT — translations tracked in BL-072 (needs live degree/radian check)
    "DATEPART", "DATENAME", "DATETRUNC", "DATEADD", "DATEDIFF",  # survivors = unknown unit
    # Spatial — full 13-function Tableau set (help.tableau.com Spatial Functions,
    # verified 2026-07-03). No ThoughtSpot spatial data type or constructors exist.
    # See "Geospatial Policy" in tableau-formula-translation.md.
    "MAKEPOINT", "MAKELINE", "DISTANCE", "BUFFER", "AREA",
    "INTERSECTS", "LENGTH", "SHAPETYPE", "OUTLINE",
    "DIFFERENCE", "INTERSECTION", "SYMDIFFERENCE", "VALIDATE",
    # Embedded-RLS user-attribute family — sibling of USERNAME/FULLNAME/etc above.
    # ABAC ts_var() referencing a formula variable is a plausible native translation
    # (same JWT user-attribute mechanism as the ISMEMBEROF→ts_groups reclassification
    # of 2026-06-28) but needs live verification before wiring in. Tracked in BL-071.
    "USERATTRIBUTE", "USERATTRIBUTEINCLUDES",
]
_UNMAPPED_RE = [
    (re.compile(rf"\b{fn}\s*\(", re.IGNORECASE), fn) for fn in _UNMAPPED_FUNCTIONS
]

# Tableau table-calculation / window functions live-confirmed (error 14516,
# "Search did not find '<FUNC> ( ... )'") to have NO valid ThoughtSpot formula
# syntax. Per tableau-formula-translation.md ("Row-Offset Table Calculations",
# "Window / Moving Functions", "Untranslatable Patterns"), each of these
# either has no ThoughtSpot equivalent at all (PREVIOUS_VALUE — recursive, no
# SQL form) or needs a sort/partition attribute Tableau encodes as worksheet
# "Compute Using" addressing metadata — NOT present in the formula text
# itself. `translate_formulas()` has no wiring today from that worksheet
# context into this translator, so rather than emit the raw (invalid) Tableau
# syntax into a Model formula, these are rejected at translate time and the
# formula is skipped with a table-calc-specific reason (same "skip, don't
# fabricate" convention as `_UNMAPPED_FUNCTIONS` above).
#
# `SIZE()` is deliberately NOT in this list: it is the one row-offset
# function with a context-free translation (unpartitioned COUNT(*) OVER ()),
# converted earlier in the pipeline by `map_functions()` — see
# `ts_cli/tableau/functions.py`.
_TABLE_CALC_NO_EQUIVALENT = ["LOOKUP", "INDEX", "FIRST", "LAST", "PREVIOUS_VALUE"]
_TABLE_CALC_RE = [
    (re.compile(rf"\b{fn}\s*\(", re.IGNORECASE), fn) for fn in _TABLE_CALC_NO_EQUIVALENT
]
_WINDOW_TABLECALC_RE = re.compile(r"\b(WINDOW_[A-Z]+)\s*\(", re.IGNORECASE)


def validate_output(expr: str) -> list[str]:
    """Check for forbidden patterns in a translated expression.

    Returns a list of validation error strings. Empty = clean.
    """
    errors: list[str] = []
    for pattern, desc in _FORBIDDEN_PATTERNS:
        if pattern.search(expr):
            errors.append(f"Contains {desc}")
    for pattern, fn in _UNMAPPED_RE:
        if pattern.search(expr):
            errors.append(f"unmapped Tableau function: {fn}")
    for pattern, fn in _TABLE_CALC_RE:
        if pattern.search(expr):
            errors.append(f"Tableau table calc has no ThoughtSpot formula equivalent: {fn}")
    window_fns = {m.group(1).upper() for m in _WINDOW_TABLECALC_RE.finditer(expr)}
    for fn in sorted(window_fns):
        errors.append(f"Tableau table calc has no ThoughtSpot formula equivalent: {fn}")
    return errors


def _check_if_then_else_structure(expr: str, expr_stripped: str) -> list[str]:
    """if/then/else structural checks (BL-046 #5, BL-060) against a single
    formula expression. ``expr_stripped`` has ``[col refs]`` and ``'strings'``
    already removed (by the caller) to avoid false matches inside those.

    Extracted out of ``validate_pre_import`` to keep that function's
    cyclomatic complexity from creeping past the module-health ratchet as
    more if/then/else checks are added over time (each is an independent,
    unrelated check — not a deepening of one code path).
    """
    warnings: list[str] = []
    lower_s = expr_stripped.lower()

    # Use negative lookbehind to exclude *_if functions (sum_if, count_if, etc.)
    if_count = len(re.findall(r'(?<![a-zA-Z_])\bif\b', lower_s))
    then_count = len(re.findall(r'(?<![a-zA-Z_])\bthen\b', lower_s))
    else_count = len(re.findall(r'(?<![a-zA-Z_])\belse\b', lower_s))

    if if_count > 0:
        if then_count < if_count:
            warnings.append(f"if without matching then ({if_count} if, {then_count} then)")
        if else_count < if_count:
            warnings.append(f"if/then without else ({if_count} if, {else_count} else)")
    if else_count > if_count:
        warnings.append(f"Orphaned else clause ({else_count} else, {if_count} if)")

    # Bare else) — missing default value in aggregate context
    if re.search(r'\belse\s*\)', expr, re.IGNORECASE):
        warnings.append(
            "Bare 'else)' — missing default value after else "
            "(likely needs 'else 0)' or 'else null)')"
        )

    # Nested-if-in-comparison (BL-060) — a comparison operator binding
    # directly before 'if' (e.g. "sum(X) < if(Y) then Z else W") is valid
    # Tableau syntax but fails ThoughtSpot import: the comparison binds
    # before the if/then/else, so ThoughtSpot needs explicit parens around
    # the conditional.
    if re.search(r'[<>=!]=?\s*if\b', expr_stripped, re.IGNORECASE):
        warnings.append(
            "Comparison operator directly followed by 'if' — wrap the conditional in parentheses: "
            "(if ... then ... else ...)")

    return warnings


def validate_pre_import(
    translated: list[dict],
    column_names: set[str] | None = None,
    formula_names: set[str] | None = None,
) -> list[dict]:
    """Pre-import structural validation to catch issues before ThoughtSpot import.

    Checks each translated formula for common patterns that cause import failures.
    Returns a list of {name, warnings: [str]} for formulas with issues.
    """
    column_names = column_names or set()
    formula_names = formula_names or set()
    col_upper = {c.upper() for c in column_names}
    formula_upper = {f.upper() for f in formula_names}
    all_names_upper = col_upper | formula_upper

    issues: list[dict] = []

    for entry in translated:
        name = entry.get("name", "")
        expr = entry.get("expr", "")
        warnings: list[str] = []

        # Check for unbalanced parentheses
        depth = 0
        for c in expr:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            if depth < 0:
                break
        if depth != 0:
            warnings.append(f"Unbalanced parentheses (depth={depth})")

        # Check for unbalanced brackets
        b_depth = 0
        for c in expr:
            if c == "[":
                b_depth += 1
            elif c == "]":
                b_depth -= 1
        if b_depth != 0:
            warnings.append(f"Unbalanced brackets (depth={b_depth})")

        # if/then/else structural validation (BL-046 #5, BL-060)
        # Strip [col refs] and 'strings' to avoid false matches
        expr_stripped = re.sub(r'\[[^\]]*\]', '', expr)
        expr_stripped = re.sub(r"'[^']*'", '', expr_stripped)
        warnings.extend(_check_if_then_else_structure(expr, expr_stripped))

        # Check for unresolved Custom SQL Query references
        if "Custom SQL Query" in expr:
            warnings.append("Unresolved Custom SQL Query alias")

        # Check for nested group_aggregate (ThoughtSpot limitation)
        ga_positions = [m.start() for m in re.finditer(r'\bgroup_aggregate\s*\(', expr)]
        if len(ga_positions) >= 2:
            warnings.append(
                "Nested group_aggregate — ThoughtSpot does not support "
                "group_aggregate inside another group_aggregate. "
                "Decompose into separate formulas."
            )

        # Check for bare Tableau aggregate keywords
        if re.search(r"\bCOUNTD\b", expr):
            warnings.append("Unrewritten COUNTD (should be 'unique count')")

        # IN with parentheses instead of curly braces
        if re.search(r'\bin\s*\(', expr, re.IGNORECASE):
            if not re.search(r'\bnot\s+in\s*\(', expr, re.IGNORECASE):
                warnings.append("IN uses parentheses — ThoughtSpot requires curly braces: in {a, b, c}")

        # Non-existent ThoughtSpot functions
        if re.search(r'\badd_quarters\s*\(', expr, re.IGNORECASE):
            warnings.append("add_quarters() does not exist — use add_months(expr, N*3)")
        # NOTE: add_years / add_weeks ARE valid ThoughtSpot functions (see
        # thoughtspot-formula-patterns.md and tableau-formula-translation.md) — do
        # not flag them. Only add_quarters is unsupported.

        # Bare date literal not wrapped in to_date()
        bare_date = re.search(r"'(\d{4}-\d{2}-\d{2})'", expr)
        if bare_date:
            before = expr[:bare_date.start()]
            if not before.rstrip().lower().endswith("to_date("):
                warnings.append(
                    f"Bare date literal '{bare_date.group(1)}' — "
                    "wrap in to_date('YYYY-MM-DD', 'yyyy-MM-dd')"
                )

        # max(boolean_expr)=false pattern — ThoughtSpot can't aggregate a boolean
        if re.search(r'\bmax\s*\([^)]*=[^)]*\)\s*=\s*false', expr, re.IGNORECASE):
            warnings.append(
                "max([col]='value')=false pattern — rewrite as "
                "count_if([col] != 'value') = 0 or similar"
            )

        # Name clash with existing column
        if name.upper() in col_upper:
            warnings.append(f"Formula name '{name}' clashes with column name")

        if warnings:
            issues.append({"name": name, "warnings": warnings})

    return issues
