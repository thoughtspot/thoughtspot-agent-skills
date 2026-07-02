"""Tableau formula pre-transforms — run before the main translation pipeline.

Pure functions, no I/O. Each transform rewrites a raw Tableau formula string
into a form the main pipeline can classify and translate.
"""
from __future__ import annotations

import re

from ts_cli.tableau.parsing import _extract_function_args


# ---------------------------------------------------------------------------
# Pre-0. Strip Tableau // line comments (BL-056)
# ---------------------------------------------------------------------------

def strip_comments(formula: str) -> str:
    """Strip Tableau // line comments, preserving // inside string literals."""
    result: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(formula):
        c = formula[i]
        if c == "'" and not in_double:
            in_single = not in_single
            result.append(c)
            i += 1
        elif c == '"' and not in_single:
            in_double = not in_double
            result.append(c)
            i += 1
        elif (c == '/' and i + 1 < len(formula) and formula[i + 1] == '/'
              and not in_single and not in_double):
            newline = formula.find('\n', i)
            if newline == -1:
                break
            i = newline
        else:
            result.append(c)
            i += 1
    return ''.join(result).strip()


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
