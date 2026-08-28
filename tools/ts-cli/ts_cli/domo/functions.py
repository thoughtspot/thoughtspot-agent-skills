"""Domo Beast Mode → ThoughtSpot formula translation.

Kept in sync with agents/shared/mappings/domo/beastmode-thoughtspot-formula-translation.md.
Strategy (family convention): deterministically translate the common subset; flag
everything else NEEDS REVIEW with the original preserved — never a wrong-but-valid
substitute. `translate()` returns (ts_formula, review_required, reason).
"""
from __future__ import annotations

import re
from typing import Optional

from ts_cli.formula_common import wrap_passthrough_calls

# --- BL-171 pass-throughs -------------------------------------------------
# Functions with NO ThoughtSpot equivalent. FUNCTION_MAP points the Domo name at
# a marker; `wrap_passthrough_calls` turns the marker into a `sql_string_op`
# pass-through that the warehouse evaluates. Same mechanism as ts_cli/qlik.
_PT_UPPER = "__pt_upper"
_PT_LOWER = "__pt_lower"
_PT_TRIM = "__pt_trim"
_PT_LTRIM = "__pt_ltrim"
_PT_RTRIM = "__pt_rtrim"
_PT_REPLACE = "__pt_replace"

PASSTHROUGH_MAP: dict[str, tuple[str, str, int]] = {
    _PT_UPPER: ("sql_string_op", "UPPER({0})", 1),
    _PT_LOWER: ("sql_string_op", "LOWER({0})", 1),
    _PT_TRIM: ("sql_string_op", "TRIM({0})", 1),
    _PT_LTRIM: ("sql_string_op", "LTRIM({0})", 1),
    _PT_RTRIM: ("sql_string_op", "RTRIM({0})", 1),
    _PT_REPLACE: ("sql_string_op", "REPLACE({0}, {1}, {2})", 3),
}

# Domo Beast Mode function/aggregation name -> ThoughtSpot function.
# None = no ThoughtSpot equivalent -> flag NEEDS REVIEW.
FUNCTION_MAP: dict[str, str | None] = {
    # --- aggregations ---
    "sum": "sum", "avg": "average", "average": "average", "min": "min", "max": "max",
    "count": "count", "stddev": "stddev", "stdev": "stddev",
    "variance": "variance", "var": "variance",
    "median": None, "percentile": None,
    # --- math ---
    "abs": "abs", "round": "round", "floor": "floor", "ceil": "ceil", "ceiling": "ceil",
    "power": "pow", "pow": "pow", "sqrt": "sqrt", "exp": "exp", "ln": "ln", "log": "log",
    "mod": "mod", "sign": "sign",
    # --- string ---
    # NOTE: `upper`/`lower`/`trim`/`ltrim`/`rtrim`/`replace` map onto PASSTHROUGH
    # MARKERS, not ThoughtSpot names — those six functions do not exist in
    # ThoughtSpot (BL-170/BL-171, live-disproved on se-thoughtspot 2026-06-13 and
    # 2026-07-29/30; a bare call is rejected at import with error_code 14516).
    # `_remap_functions` rewrites each marker into a `sql_string_op` pass-through,
    # so a marker never reaches an emitted formula (asserted by
    # tests/test_domo_functions.py::TestMapIntegrity).
    "concat": "concat",
    "upper": _PT_UPPER, "lower": _PT_LOWER, "trim": _PT_TRIM,
    "ltrim": _PT_LTRIM, "rtrim": _PT_RTRIM, "replace": _PT_REPLACE,
    "length": "strlen", "len": "strlen",
    # ThoughtSpot's substring function is `substr` — `substring` does not exist.
    "substring": "substr", "substr": "substr",
    "left": "left", "right": "right", "instr": "strpos",
    # --- date ---
    "year": "year", "month": "month", "day": "day", "hour": "hour", "minute": "minute",
    "quarter": "quarter", "week": "week", "now": "now", "current_date": "today",
    "datediff": "diff_days", "date_diff": "diff_days",
    # --- type ---
    "to_number": "to_double", "to_double": "to_double", "to_char": "to_string",
    "to_string": "to_string", "to_date": "to_date",
    # --- structural / unsupported -> NEEDS REVIEW (manual rewrite; see the
    #     mapping doc for the recommended ThoughtSpot form) ---
    "ifnull": None, "coalesce": None, "nullif": None, "cast": None,
    "rank": None, "row_number": None, "lag": None, "lead": None, "running_total": None,
}

# ThoughtSpot function names we emit ourselves — must not be flagged as "unknown"
# when the token pass re-scans the translated string.
_KNOWN_TS = ({v for v in FUNCTION_MAP.values() if v} - set(PASSTHROUGH_MAP)) | {
    # `unique count` (a space) is emitted by step 2; `unique_count` is NOT a
    # ThoughtSpot function and must stay flagged if a Beast Mode spells it that way.
    "unique", "if", "isnull", "to_string", "to_double",
    "diff_hours", "diff_minutes", "add_days", "add_months",
    "sql_string_op", "sql_date_op", "sql_number_op",
}

# Constructs the token-based translator cannot faithfully rewrite -> flag NEEDS REVIEW.
_UNSUPPORTED_RE = re.compile(
    r"\bcase\b|\bover\s*\(|\bpartition\s+by\b", re.IGNORECASE)

_MARKER_ORIGIN = {marker: name.upper()
                  for name, marker in FUNCTION_MAP.items()
                  if marker in PASSTHROUGH_MAP}

_BACKTICK = re.compile(r"`([^`]+)`")
# COUNT(DISTINCT [col]) -> unique_count([col])  (runs after backtick->bracket)
_COUNT_DISTINCT = re.compile(
    r"\bcount\s*\(\s*distinct\s+(\[[^\]]+\])\s*\)", re.IGNORECASE)
_FUNC_TOKEN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

# `[Bracketed Identifier]` and quoted literals — masked out before the structural
# check so their contents can never look like SQL keywords.
_IDENTIFIER_OR_LITERAL = re.compile(r"\[[^\]]*\]|'[^']*'|\"[^\"]*\"")


def _strip_identifiers(expr: str) -> str:
    """Blank out bracketed identifiers and string literals."""
    return _IDENTIFIER_OR_LITERAL.sub(" ", expr)


# Domo functions whose ThoughtSpot counterpart takes a fixed argument count. A rename
# alone is not enough: Domo's `DATEDIFF('month', a, b)` carries a grain argument that
# `diff_days` has no parameter for, so the rename produced a 3-arg call to a 2-arg
# function — invalid, and graded Approximated.
_ARITY: dict[str, tuple[int, str]] = {
    "diff_days": (2, "Domo DATEDIFF carries a grain argument (e.g. 'month') that "
                     "ThoughtSpot's diff_days has no parameter for — rewrite using the "
                     "matching diff_* function or a date-part expression"),
}


def _arities_of(call: str, expr: str) -> list[int]:
    """Top-level argument counts for EVERY `call(` in `expr`.

    One `find()` was not enough: a valid 2-arg call ahead of an invalid one hid it,
    so `diff_days([a],[b]) + diff_days('month',[a],[b])` shipped unflagged.
    """
    out: list[int] = []
    low = expr.lower()
    needle = call + "("
    start = 0
    while True:
        i = low.find(needle, start)
        if i < 0:
            return out
        depth, args, seen = 0, 1, False
        j = i + len(call)
        for ch in expr[j:]:
            j += 1
            if ch == "(":
                depth += 1
                seen = True
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "," and depth == 1:
                args += 1
        if seen:
            out.append(args)
        start = i + len(needle)


def translate(expr: str) -> tuple[str, bool, str]:
    """Translate a Domo Beast Mode expression into a ThoughtSpot formula."""
    if not expr or not expr.strip():
        return "", True, "empty formula"

    reasons: list[str] = []
    review = False

    # 1. column refs: `Col Name` -> [Col Name]. This runs FIRST so the structural
    #    check below can ignore identifiers: a column named "Case Volume" or
    #    "Cases Closed" must not be mistaken for SQL `CASE` (common in CRM/support
    #    data, and flagging it emitted the formula verbatim-with-backticks, which
    #    broke the whole model import).
    out = _BACKTICK.sub(lambda m: f"[{m.group(1)}]", expr)

    # 2. structural constructs the token translator can't faithfully rewrite
    #    (any CASE form, window/OVER) -> emit verbatim, flag for manual rewrite.
    if _UNSUPPORTED_RE.search(_strip_identifiers(out)):
        return out, True, ("contains CASE / window construct — ThoughtSpot has no CASE "
                            "syntax; manual rewrite required")
    # 3. COUNT(DISTINCT [x]) -> unique count([x])
    #    ThoughtSpot's distinct-count formula function is `unique count` (a space,
    #    NOT an underscore); `unique_count`/`count_distinct` are rejected by the
    #    formula parser.
    out = _COUNT_DISTINCT.sub(lambda m: f"unique count({m.group(1)})", out)

    # 4. function-name remap (Domo -> ThoughtSpot); flag unknown / unsupported
    def _repl(m: re.Match) -> str:
        nonlocal review
        fn = m.group(1)
        low = fn.lower()
        if low == "distinct":  # leftover from a non-count DISTINCT
            return m.group(0)
        if low in FUNCTION_MAP:
            mapped = FUNCTION_MAP[low]
            if mapped is None:
                review = True
                reasons.append(f"function '{fn}' has no ThoughtSpot equivalent")
                return m.group(0)
            return f"{mapped}("
        if low in _KNOWN_TS:  # already a TS function we emitted (e.g. unique_count)
            return f"{low}("
        review = True
        reasons.append(f"unrecognized function '{fn}'")
        return m.group(0)

    out = _FUNC_TOKEN.sub(_repl, out)

    # 5. BL-171: markers -> sql_string_op pass-throughs. An unresolved marker
    #    (wrong arity, unbalanced parens) is flagged rather than emitted — a bare
    #    upper/trim/replace call is rejected at import with error_code 14516.
    for call, (expected, advice) in _ARITY.items():
        wrong = sorted({n for n in _arities_of(call, out) if n != expected})
        if wrong:
            review = True
            counts = ", ".join(str(n) for n in wrong)
            reasons.append(f"'{call}' called with {counts} argument(s), expected "
                           f"{expected} — {advice}")

    out, unresolved = wrap_passthrough_calls(out, PASSTHROUGH_MAP)
    if unresolved:
        review = True
        for marker in sorted(unresolved):
            reasons.append(
                f"'{_MARKER_ORIGIN.get(marker, marker)}' has no ThoughtSpot "
                "equivalent and could not be rewritten as a SQL pass-through")

    reason = "; ".join(dict.fromkeys(reasons)) if review else ""
    return out, review, reason
