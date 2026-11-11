"""Tableau formula pre-transforms — run before the main translation pipeline.

Pure functions, no I/O. Each transform rewrites a raw Tableau formula string
into a form the main pipeline can classify and translate.
"""
from __future__ import annotations

import re

from ts_cli.formula_translate.refs import comment_pattern, strip_comment_matches
from ts_cli.tableau.literals import mask_refs, unmask_refs
from ts_cli.tableau.parsing import _extract_function_args


# ---------------------------------------------------------------------------
# Pre-0. Strip Tableau comments: // line comments (BL-056) and /* */ blocks
# ---------------------------------------------------------------------------
#
# help.tableau.com (Operators): "A comment starts at the two forward slashes (//) and goes
# to the end of the line" and "Multi-line comments can be added by typing /* to start the
# comment and */ to end it". One left-to-right scan: a [field] reference, a string literal
# or a comment, whichever starts first. A reference may hold a quote or `//` ([Bob's Sales],
# [http://site]), a literal may hold `//` or `/*`, and only what is outside both is a
# comment. The character toggle this replaced read the apostrophe in [Bob's Sales] as an
# open literal, and the `//` in [http://site] as a comment (BL-460 review).
# The shared scanner (formula_translate.refs.comment_pattern) with Tableau's literal
# grammar: a quote is doubled inside a literal, and there is no backslash escape.
_COMMENT_SCAN = comment_pattern(
    ("//",), block=True, refs=True,
    literal=r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")


def strip_comments(formula: str) -> str:
    """Strip Tableau comments (``//`` to the end of the line, ``/* … */`` blocks) outside
    string literals and ``[field]`` references."""
    return strip_comment_matches(_COMMENT_SCAN, formula, line="").strip()


# ---------------------------------------------------------------------------
# Pre-0c. One spelling per Tableau function (BL-460 review)
# ---------------------------------------------------------------------------
#
# Tableau function names are case-insensitive, so `log2(` and `LOG2(` are one call. Every
# mapping here matches case-insensitively and emits lower case, and the survivor catch in
# validate.py reads a lower-case name as converter output. A source written in lower case
# leaked through it: `log2(` (a ThoughtSpot name, though LOG2 is unmapped until a live
# check) and `group_concat(` passed while `LOG2(` was skipped. Upper-casing every call name
# in the source first gives one spelling: whatever comes out in lower case, the converter
# wrote. Operators keep their case; [field] references are masked, and string literals are
# already placeholders when this runs.
_SOURCE_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)(\s*\()")
# Tableau's operators and control words: never a function name. The one copy;
# validate.py's survivor catch reads it too.
CONTROL_WORDS = frozenset(
    {"if", "then", "else", "elseif", "and", "or", "not", "in", "is", "case", "when", "end"})


def upper_call_names(expr: str) -> str:
    """Upper-case every function name called in a Tableau source ``expr`` (not operators,
    not inside ``[field]`` references). Run on the literal-masked source."""
    masked, refs = mask_refs(expr)

    def _upper(m: re.Match) -> str:
        name = m.group(1)
        return m.group(0) if name.lower() in CONTROL_WORDS else name.upper() + m.group(2)

    return unmask_refs(_SOURCE_CALL.sub(_upper, masked), refs)


# ---------------------------------------------------------------------------
# Pre-1. Custom SQL Query alias resolution (BL-057)
# ---------------------------------------------------------------------------

def rewrite_csq_aliases(
    expr: str,
    csq_to_table: dict[str, str],
) -> str:
    """Rewrite [COL (Custom SQL Query N)] → [TABLE::COL].

    csq_to_table: {"Custom SQL Query8": "FORECAST", ...}
    """
    if not csq_to_table:
        return expr

    _CSQ_REF = re.compile(
        r"\[([^\]]+?)\s+\((Custom SQL Query\s*\d+)\)\]",
        re.IGNORECASE,
    )

    def _replace(m: re.Match) -> str:
        col = m.group(1).strip()
        csq = m.group(2).strip()
        csq_norm = re.sub(r"\s+", " ", csq)
        table = csq_to_table.get(csq_norm)
        if table:
            return f"[{table}::{col}]"
        return m.group(0)

    return _CSQ_REF.sub(_replace, expr)


def build_csq_column_map(
    csq_columns: dict[str, set[str]],
    model_tables: dict[str, set[str]],
    threshold: float = 0.8,
) -> tuple[dict[str, str], dict[str, tuple[str, float]]]:
    """Match Custom SQL Query aliases to model tables by column overlap.

    Returns (definitive_map, ambiguous_map).
    definitive_map: {csq_name: table_name} for matches >= threshold.
    ambiguous_map: {csq_name: (best_table, score)} for matches >= 0.5 but < threshold.
    """
    definitive: dict[str, str] = {}
    ambiguous: dict[str, tuple[str, float]] = {}

    for csq_name, csq_cols in csq_columns.items():
        if not csq_cols:
            continue
        best_match = None
        best_score = 0.0
        for table_name, table_cols in model_tables.items():
            overlap = csq_cols & table_cols
            score = len(overlap) / len(csq_cols)
            if score > best_score:
                best_match = table_name
                best_score = score
        if best_match and best_score >= threshold:
            definitive[csq_name] = best_match
        elif best_match and best_score >= 0.5:
            ambiguous[csq_name] = (best_match, best_score)

    return definitive, ambiguous


# ---------------------------------------------------------------------------
# Pre-2. No-keyword LOD: {AGG([col])} → group_aggregate (BL-052)
# ---------------------------------------------------------------------------

_NO_KEYWORD_LOD_AGG_MAP = {
    "COUNTD": "unique count",
    "COUNT": "count",
    "SUM": "sum",
    "AVG": "average",
    "MAX": "max",
    "MIN": "min",
    "MEDIAN": "median",
    "ATTR": "max",
}

def convert_no_keyword_lod(expr: str) -> str:
    """Convert {AGG([col])} (no FIXED/INCLUDE/EXCLUDE) → group_aggregate.

    Only matches braces with no keyword before the aggregate — the keyword forms
    are handled by convert_lod().
    """
    _PATTERN = re.compile(
        r"\{\s*(COUNTD|COUNT|SUM|AVG|MAX|MIN|MEDIAN|ATTR)\s*\((.+?)\)\s*\}",
        re.IGNORECASE,
    )

    def _replace(m: re.Match) -> str:
        agg = m.group(1).upper()
        inner = m.group(2).strip()
        ts_agg = _NO_KEYWORD_LOD_AGG_MAP.get(agg, agg.lower())
        return f"group_aggregate ( {ts_agg} ( {inner} ) , {{}} , query_filters () )"

    return _PATTERN.sub(_replace, expr)


# ---------------------------------------------------------------------------
# Pre-3. Scalar MAX(a,b) / MIN(a,b) detection (BL-055)
# ---------------------------------------------------------------------------

def convert_scalar_max_min(expr: str) -> str:
    """Convert two-arg MAX(a, b) → greatest(a, b). Same for MIN → least."""
    result = expr
    result = _convert_scalar_fn(result, "MAX", "greatest")
    result = _convert_scalar_fn(result, "MIN", "least")
    return result


def _convert_scalar_fn(expr: str, fn: str, ts_fn: str) -> str:
    _PAT = re.compile(rf"\b{fn}\s*\(", re.IGNORECASE)

    result = expr
    search_start = 0
    safety = 0
    while safety < 50:
        m = _PAT.search(result, search_start)
        if not m:
            break
        safety += 1

        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            search_start = m.end()
            continue
        args, end_pos = extracted

        if len(args) == 2:
            a = args[0].strip()
            b = args[1].strip()
            replacement = f"{ts_fn} ( {a} , {b} )"
            result = result[:m.start()] + replacement + result[end_pos:]
            # Rescan from the replacement start: args may contain nested calls
            search_start = m.start()
        else:
            # Aggregate (1-arg) or 3+ args: skip past this match only, keep
            # scanning — its args may still contain a scalar MAX/MIN
            search_start = m.end()

    return result


# ---------------------------------------------------------------------------
# Pre-4. Date arithmetic: DATE()+N → add_days (BL-054)
# ---------------------------------------------------------------------------

def rewrite_date_arithmetic(expr: str, date_columns: set[str] | None = None) -> str:
    """Rewrite date +/- integer patterns to add_days().

    Only rewrites when one side is clearly a date:
    - DATE([col]) + N / DATE([col]) - N (always — DATE() call is explicit)
    - [date_col] + N / [date_col] - N (only if col is in date_columns set)
    """
    date_columns = date_columns or set()
    date_columns_upper = {c.upper() for c in date_columns}

    # Pattern 1: DATE(...) +/- N — always a date
    _DATE_CALL = re.compile(
        r"(date\s*\([^)]+\))\s*([+-])\s*(\d+)",
        re.IGNORECASE,
    )

    def _replace_date_call(m: re.Match) -> str:
        date_expr = m.group(1).strip()
        operator = m.group(2)
        n = m.group(3)
        if operator == "-":
            return f"add_days ( {date_expr} , -{n} )"
        return f"add_days ( {date_expr} , {n} )"

    result = _DATE_CALL.sub(_replace_date_call, expr)

    # Pattern 2: [col] +/- N where col is a known date column
    if date_columns_upper:
        _COL_ARITH = re.compile(
            r"\[([^\]]+)\]\s*([+-])\s*(\d+)",
        )

        def _replace_col(m: re.Match) -> str:
            col = m.group(1).strip()
            col_name = col.split("::")[-1] if "::" in col else col
            if col_name.upper() in date_columns_upper:
                operator = m.group(2)
                n = m.group(3)
                if operator == "-":
                    return f"add_days ( [{col}] , -{n} )"
                return f"add_days ( [{col}] , {n} )"
            return m.group(0)

        result = _COL_ARITH.sub(_replace_col, result)

    return result
