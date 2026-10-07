"""Tableau function-name and date-function mapping.

Pure functions, no I/O. Maps Tableau scalar/aggregate function names to
their ThoughtSpot equivalents and converts Tableau date functions
(DATETRUNC, DATEDIFF, DATEADD, DATEPART, DATENAME) to ThoughtSpot syntax,
including unit-name remapping and argument reordering where the two
platforms disagree on argument order.
"""
from __future__ import annotations

import re
from typing import Any

from ts_cli.formula_common import (
    WEEKDAY_FIRST_DAY_INDEX,
    sql_digits_to_ts_increment,
    ts_round_from_sql_digits,
    ts_weekday_number,
)
from ts_cli.tableau.literals import literal_value
from ts_cli.tableau.parsing import _extract_function_args


# ---------------------------------------------------------------------------
# 6. Function mapping
# ---------------------------------------------------------------------------

_FUNCTION_MAP: list[tuple[re.Pattern, str | callable]] = []


def _build_function_map() -> list[tuple[re.Pattern, Any]]:
    """Build regex → replacement pairs for Tableau → ThoughtSpot functions."""
    mappings: list[tuple[str, str | Any]] = [
        # Null handling
        (r"\bZN\s*\(", "_ZN_HANDLER"),
        (r"\bIFNULL\s*\(", "ifnull ( "),
        (r"\bISNULL\s*\(", "isnull ( "),

        # Aggregates
        (r"\bCOUNTD\s*\(", "unique count ( "),
        (r"\bAVG\s*\(", "average ( "),
        (r"\bATTR\s*\(", "("),  # ATTR just strips to the inner ref
        (r"\bSTDEV\s*\(", "stddev ( "),
        (r"\bMEDIAN\s*\(", "median ( "),
        (r"\bSUM\s*\(", "sum ( "),
        (r"\bMIN\s*\(", "min ( "),
        (r"\bMAX\s*\(", "max ( "),
        (r"\bCOUNT\s*\(", "count ( "),

        # String
        (r"\bCONTAINS\s*\(", "contains ( "),
        (r"\bLEN\s*\(", "strlen ( "),
        # TRIM/LTRIM/RTRIM and REPLACE are handled specially — see
        # _ARG_HANDLERS. None of `trim`, `ltrim`, `rtrim` or `replace` is a
        # real ThoughtSpot formula function (live-verified 2026-07-29 +
        # 2026-07-30 on se-thoughtspot, error_code 14516 — BL-170/BL-171);
        # each must go through the sql_string_op pass-through form instead.

        # LEFT/RIGHT/MID are handled specially
        (r"\bLEFT\s*\(", "_LEFT_HANDLER"),
        (r"\bRIGHT\s*\(", "_RIGHT_HANDLER"),
        (r"\bMID\s*\(", "_MID_HANDLER"),

        (r"\bFIND\s*\(", "strpos ( "),
        (r"\bUPPER\s*\(", "_UPPER_HANDLER"),
        (r"\bLOWER\s*\(", "_LOWER_HANDLER"),
        (r"\bSTARTSWITH\s*\(", "_STARTSWITH_HANDLER"),
        (r"\bENDSWITH\s*\(", "_ENDSWITH_HANDLER"),

        # Math
        (r"\bABS\s*\(", "abs ( "),
        # ROUND is handled in _ARG_HANDLERS (BL-331): Tableau's 2nd arg is a
        # digit count, ThoughtSpot round()'s is an increment — a bare rename
        # turned ROUND(x, 2) into round(x, 2), which rounds to the nearest 2.
        (r"\bCEILING\s*\(", "ceil ( "),
        (r"\bFLOOR\s*\(", "floor ( "),
        (r"\bLOG\s*\(", "log10 ( "),
        (r"\bLN\s*\(", "ln ( "),
        (r"\bPOWER\s*\(", "pow ( "),
        (r"\bSQRT\s*\(", "sqrt ( "),
        (r"\bEXP\s*\(", "exp ( "),
        (r"\bSQUARE\s*\(", "_SQUARE_HANDLER"),
        # BL-364: the warehouse's own PI(), a full double — the 15-digit literal lost
        # precision, and a literal-over-literal division of it was fixed-point (BL-365).
        (r"\bPI\s*\(\s*\)", 'sql_double_op ( "PI()" )'),

        # Row-offset table calc — SIZE() is the one member of that family
        # (see tableau/validate.py's _TABLE_CALC_NO_EQUIVALENT for the rest)
        # with a context-free translation: unpartitioned row count, no
        # sort/partition attribute needed. Tier 7 of the Row-Offset Table
        # Calculations decision tree in tableau-formula-translation.md.
        (r"\bSIZE\s*\(\s*\)", 'sql_int_aggregate_op ( "COUNT(*) OVER ()" )'),

        # Type conversion
        (r"\bFLOAT\s*\(", "to_double ( "),
        (r"\bSTR\s*\(", "to_string ( "),

        # Date
        (r"\bTODAY\s*\(\s*\)", "today ( )"),
        (r"\bNOW\s*\(\s*\)", "now ( )"),
        (r"\bYEAR\s*\(", "year ( "),
        (r"\bMONTH\s*\(", "month_number ( "),
        (r"\bDAY\s*\(", "day ( "),
        (r"\bDATE\s*\(", "date ( "),
    ]

    compiled = []
    for pattern, replacement in mappings:
        compiled.append((re.compile(pattern, re.IGNORECASE), replacement))
    return compiled


_FUNCTION_MAP = _build_function_map()


def map_functions(expr: str) -> str:
    """Apply function name mappings from Tableau to ThoughtSpot."""
    result = expr

    for pattern, replacement in _FUNCTION_MAP:
        if isinstance(replacement, str) and not replacement.startswith("_"):
            result = pattern.sub(replacement, result)

    # ZN(x) → ifnull ( x , 0 )
    result = _convert_zn(result)

    for fn, render in _ARG_HANDLERS:
        result = _apply_arg_handler(result, fn, render)

    return result


def _apply_arg_handler(expr: str, fn: str, render) -> str:
    """Rewrite fn(args...) calls using render([stripped_args]) → replacement or None to skip."""
    pat = re.compile(rf"\b{fn}\s*\(", re.IGNORECASE)
    result = expr
    search_start = 0
    safety = 0
    while safety < 50:
        m = pat.search(result, search_start)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            search_start = m.end()
            continue
        args, end_pos = extracted
        # Translate same-function calls nested inside the args first — the
        # cursor skips past the replacement so they would never be revisited,
        # and rescanning is unsafe because the UPPER/LOWER templates quote
        # their own function name.
        replacement = render([_apply_arg_handler(a.strip(), fn, render) for a in args])
        if replacement is None:
            search_start = m.end()
            continue
        result = result[:m.start()] + replacement + result[end_pos:]
        search_start = m.start() + len(replacement)
    return result


def _round_handler(a: list[str]) -> str:
    """Tableau ROUND(x[, d]) -> ThoughtSpot round(x[, 10^-d]) (BL-331).

    Only a literal digit count converts. Anything else — a field-driven d, a
    third argument — is re-emitted as upper-case ``ROUND(...)``, which
    validate.py's survivor pattern rejects, so the formula is skipped with a
    reason instead of importing as round-to-nearest-d.
    """
    if len(a) == 1 and a[0]:
        return ts_round_from_sql_digits(a[0])
    if len(a) == 2 and sql_digits_to_ts_increment(a[1]) is not None:
        return ts_round_from_sql_digits(a[0], a[1])
    return f"ROUND({', '.join(a)})"


_ARG_HANDLERS: list[tuple[str, Any]] = [
    ("LEFT", lambda a: f"substr ( {a[0]} , 0 , {a[1]} )" if len(a) == 2 else None),
    ("RIGHT", lambda a: f"substr ( {a[0]} , strlen ( {a[0]} ) - {a[1]} , {a[1]} )" if len(a) == 2 else None),
    ("MID", lambda a: f"substr ( {a[0]} , {a[1]} - 1 , {a[2]} )" if len(a) == 3 else None),
    ("UPPER", lambda a: f'sql_string_op ( "UPPER({{0}})" , {a[0]} )' if len(a) == 1 else None),
    ("LOWER", lambda a: f'sql_string_op ( "LOWER({{0}})" , {a[0]} )' if len(a) == 1 else None),
    # BL-171 — `trim`/`ltrim`/`rtrim` do NOT exist in ThoughtSpot (live-verified
    # 2026-07-29 + 2026-07-30, se-thoughtspot; rejected with error_code 14516,
    # the same signature UPPER/LOWER produce). Same pass-through treatment;
    # forms per tableau-formula-translation.md's TRIM/LTRIM/RTRIM rows.
    ("TRIM", lambda a: f'sql_string_op ( "TRIM({{0}})" , {a[0]} )' if len(a) == 1 else None),
    ("LTRIM", lambda a: f'sql_string_op ( "LTRIM({{0}})" , {a[0]} )' if len(a) == 1 else None),
    ("RTRIM", lambda a: f'sql_string_op ( "RTRIM({{0}})" , {a[0]} )' if len(a) == 1 else None),
    ("STARTSWITH", lambda a: f"( strpos ( {a[0]} , {a[1]} ) = 1 )" if len(a) == 2 else None),
    ("ENDSWITH", lambda a: (
        f"( substr ( {a[0]} , strlen ( {a[0]} ) - strlen ( {a[1]} ) , strlen ( {a[1]} ) ) = {a[1]} )"
        if len(a) == 2 else None)),
    # BL-331 — ROUND(x, d): d decimal places -> ThoughtSpot increment 10^-d.
    ("ROUND", _round_handler),
    ("SQUARE", lambda a: f"pow ( {a[0]} , 2 )" if len(a) == 1 else None),
    ("SIGN", lambda a: (
        f"( if ( {a[0]} > 0 ) then 1 else if ( {a[0]} < 0 ) then -1 else 0 )"
        if len(a) == 1 else None)),
    # BL-364: ThoughtSpot trigonometry is in RADIANS (live 2026-10-07, probe record §7:
    # `sin ( 30 )` compiles to SIN(30) = -0.988), as Tableau's is, so it maps 1:1. The
    # former `* 180 / 3.14159…` conversion assumed degrees and was wrong for every input.
    ("SIN", lambda a: f"sin ( {a[0]} )" if len(a) == 1 else None),
    ("COS", lambda a: f"cos ( {a[0]} )" if len(a) == 1 else None),
    ("TAN", lambda a: f"tan ( {a[0]} )" if len(a) == 1 else None),
    # Exact: the warehouse PI() (a double), and the product bracketed before the
    # division (BL-365 — `x * 180 / π` is read as `x * ( 180 / π )`).
    ("RADIANS", lambda a: (f'( ( {a[0]} * sql_double_op ( "PI()" ) ) / 180 )'
                           if len(a) == 1 else None)),
    ("DEGREES", lambda a: (f'( ( {a[0]} * 180 ) / sql_double_op ( "PI()" ) )'
                           if len(a) == 1 else None)),
    # ATAN2 has no native ThoughtSpot function; pass it to the warehouse, the same
    # warehouse treatment PI gets above. Argument order is Tableau's (y, x)
    # and SQL ATAN2 takes (y, x) too, so no swap. Audit finding 13.27 -- it was in
    # no mapped, unmapped or pass-through table, so it passed through untranslated
    # against this file's own fail-loud policy. That the trig block handled the
    # radian/degree mismatch but stopped short of ATAN2 is the tell that the census
    # was function-list-driven rather than page-driven.
    ("ATAN2", lambda a: (f'sql_double_op ( "ATAN2({{0}}, {{1}})" , {a[0]} , {a[1]} )'
                         if len(a) == 2 else None)),
    # Tableau DIV(a, b) is INTEGER division. floor() is native; the divisor guard is
    # mandatory in this repo (raw `/` pushed to the warehouse errors the whole query
    # on a zero divisor, where Tableau returns NULL) -- so it goes through
    # safe_divide, which returns 0 rather than NULL on a zero divisor. Flag if
    # downstream logic distinguishes the two (finding 13.27).
    ("DIV", lambda a: (f"floor ( safe_divide ( {a[0]} , {a[1]} ) )"
                       if len(a) == 2 else None)),

    # Inverse trig + COT (BL-072 sub-item). Radians in and out on both sides (BL-364);
    # COT(x) = 1 / tan(x).
    ("ACOS", lambda a: f"acos ( {a[0]} )" if len(a) == 1 else None),
    ("ASIN", lambda a: f"asin ( {a[0]} )" if len(a) == 1 else None),
    ("ATAN", lambda a: f"atan ( {a[0]} )" if len(a) == 1 else None),
    ("COT", lambda a: f"( 1 / tan ( {a[0]} ) )" if len(a) == 1 else None),

    ("DATEPARSE", lambda a: f"to_date ( {a[1]} , {a[0]} )" if len(a) == 2 else None),

    # Pass-through rescues (tableau-formula-translation.md "Functions with no
    # native ThoughtSpot equivalent — pass-through", lines ~989-995) — no
    # native ThoughtSpot function exists for regex/nth-occurrence matching, so
    # these translate to the documented sql_*_op templates verbatim.
    ("REGEXP_EXTRACT", lambda a: (
        f'sql_string_op ( "REGEXP_SUBSTR({{0}}, {{1}})" , {a[0]} , {a[1]} )'
        if len(a) == 2 else None)),
    ("REGEXP_MATCH", lambda a: (
        f'sql_bool_op ( "REGEXP_LIKE ({{0}}, {{1}})" , {a[0]} , {a[1]} )'
        if len(a) == 2 else None)),
    ("REGEXP_REPLACE", lambda a: (
        f'sql_string_op ( "REGEXP_REPLACE({{0}},{{1}},{{2}})" , {a[0]} , {a[1]} , {a[2]} )'
        if len(a) == 3 else None)),
    ("FINDNTH", lambda a: (
        f'sql_int_op ( "REGEXP_INSTR({{0}},{{1}},1,{{2}})" , {a[0]} , {a[1]} , {a[2]} )'
        if len(a) == 3 else None)),
    # REPLACE: bare `replace(...)` is not a real ThoughtSpot formula function
    # (live-confirmed invalid) — re-mapped to the sql_string_op pass-through
    # form. No documented template existed for REPLACE prior to this fix; this
    # is the form added to tableau-formula-translation.md alongside this change.
    ("REPLACE", lambda a: (
        f'sql_string_op ( "REPLACE({{0}}, {{1}}, {{2}})" , {a[0]} , {a[1]} , {a[2]} )'
        if len(a) == 3 else None)),

    # User-identity → RLS system variables (BL-071 subset). Only the
    # unambiguous, documented mappings — FULLNAME/ISFULLNAME/USERDOMAIN/
    # USERATTRIBUTE(INCLUDES) stay in _UNMAPPED_FUNCTIONS (validate.py),
    # see tableau-formula-translation.md for the disposition of each.
    ("USERNAME", lambda a: (
        "ts_username" if len(a) == 0 or (len(a) == 1 and not a[0].strip()) else None)),
    ("ISUSERNAME", lambda a: f"( ts_username = {a[0]} )" if len(a) == 1 else None),
    ("ISMEMBEROF", lambda a: f"( ts_groups = {a[0]} )" if len(a) == 1 else None),

    # ISOWEEKDAY(date): "1-7, start of week is always Monday" (help.tableau.com
    # date functions) — exactly ThoughtSpot's fixed day_number_of_week (BL-334).
    ("ISOWEEKDAY", lambda a: (
        ts_weekday_number(a[0].strip(), first_day="monday", base=1)
        if len(a) == 1 else None)),
]


def _convert_zn(expr: str) -> str:
    """Convert ZN(x) → ifnull(x, 0)."""
    _ZN = re.compile(r"\bZN\s*\(", re.IGNORECASE)

    result = expr
    safety = 0
    while safety < 50:
        m = _ZN.search(result)
        if not m:
            break
        safety += 1

        start = m.end()
        depth = 1
        pos = start
        while pos < len(result) and depth > 0:
            if result[pos] == "(":
                depth += 1
            elif result[pos] == ")":
                depth -= 1
            pos += 1

        if depth != 0:
            break

        inner = result[start:pos - 1].strip()
        replacement = f"ifnull ( {inner} , 0 )"
        result = result[:m.start()] + replacement + result[pos:]

    return result


# ---------------------------------------------------------------------------
# 7. Date function mapping
# ---------------------------------------------------------------------------

_DATETRUNC_UNIT_MAP = {
    "month": "start_of_month",
    "quarter": "start_of_quarter",
    "week": "start_of_week",
    "year": "start_of_year",
    "day": "date",
}

_DATEPART_UNIT_MAP = {
    "month": "month_number",
    "year": "year",
    "day": "day",
    "quarter": "quarter_number",
    "dayofyear": "day_number_of_year",
    # "weekday" is NOT a rename (BL-334) — see _datepart_weekday below.
    "hour": "hour_of_day",
    "week": "week_number_of_year",
}

_DATEDIFF_UNIT_MAP = {
    "day": "diff_days",
    "month": "diff_months",
    "year": "diff_years",
}

_DATEADD_UNIT_MAP = {
    "day": "add_days",
    "month": "add_months",
    "year": "add_years",
}


def _resolve_unit(arg: str, registry: dict | None) -> str:
    """Resolve a date-function's unit argument to its lowercased text.

    `arg` is normally a quoted literal ('month', 'day', ...). When the
    pipeline has masked literals into placeholders (see literals.py), `arg`
    is the placeholder token instead — resolve it via `registry` first. Falls
    back to the old direct quote-strip when there's no registry (e.g. these
    functions are still unit-tested by calling them directly with real quotes).
    """
    arg = arg.strip()
    if registry:
        lit = literal_value(arg, registry)
        if lit is not None:
            return lit.lower()
    return arg.strip("'\"").lower()


def map_date_functions(expr: str, registry: dict | None = None,
                       week_start: str | None = None,
                       notes: dict | None = None) -> str:
    """Convert Tableau date functions to ThoughtSpot equivalents.

    `registry` is the literal-masking registry from literals.mask_literals
    (see translate_single) — needed to resolve a masked unit argument
    ('month', 'day', ...) back to its text for the unit-name lookups below.
    `week_start` is the datasource's Week start (lower-case day name) when the
    TWB records one; `notes` collects assumption counters (WEEK_START_ASSUMED).
    """
    result = expr

    # DATETRUNC('unit', date) → start_of_unit ( date )
    result = _convert_datetrunc(result, registry, week_start, notes)

    # DATEDIFF('unit', start, end) → diff_unit ( end , start )  [reversed args]
    result = _convert_datediff(result, registry, notes)

    # DATEADD('unit', n, date) → add_unit ( date , n )  [reordered]
    result = _convert_dateadd(result, registry)

    # DATEPART('unit', date) → unit_func ( date )
    result = _convert_datepart(result, registry, week_start, notes)

    # DATENAME('month', date) → month ( date )
    result = _convert_datename(result, registry)

    return result


# Tableau DATETRUNC('week', d, [start_of_week]) and DATEPART('week', d,
# [start_of_week]) honour the week start; ThoughtSpot start_of_week and
# week_number_of_year are Monday-based. When the converter KNOWS the source week
# starts elsewhere (a literal argument, else the datasource's Week start) the plain
# Monday form is a known wrong answer: it is still emitted, but counted under
# `WEEK_START_MISMATCH:<day>` so the record is flagged for review (BL-334). An
# unknown start stays an advisory (formula_week.week_start_note).
WEEK_START_MISMATCH = "week_start_mismatch"


def _note_week_mismatch(args: list[str], registry: dict | None,
                        week_start: str | None, notes: dict | None) -> None:
    start = None
    if len(args) >= 3:
        start = _resolve_unit(args[2], registry)
    elif week_start:
        start = week_start.lower()
    if notes is not None and start in WEEKDAY_FIRST_DAY_INDEX and start != "monday":
        key = f"{WEEK_START_MISMATCH}:{start}"
        notes[key] = notes.get(key, 0) + 1


def _convert_datetrunc(expr: str, registry: dict | None = None,
                       week_start: str | None = None,
                       notes: dict | None = None) -> str:
    _PAT = re.compile(r"\bDATETRUNC\s*\(", re.IGNORECASE)
    result = expr
    search_start = 0
    safety = 0
    while safety < 20:
        m = _PAT.search(result, search_start)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            search_start = m.end()
            continue
        args, end_pos = extracted
        if len(args) >= 2:
            unit = _resolve_unit(args[0], registry)
            date_expr = args[1].strip()
            ts_func = _DATETRUNC_UNIT_MAP.get(unit)
            if ts_func is None:
                # Unknown unit — no ThoughtSpot start_of_* function exists.
                # Leave the original DATETRUNC(...) text in place rather than
                # fabricate a nonexistent function name; validate_output
                # flags any surviving DATETRUNC call as unmapped.
                search_start = end_pos
                continue
            if unit == "week":
                _note_week_mismatch(args, registry, week_start, notes)
            replacement = f"{ts_func} ( {date_expr} )"
            result = result[:m.start()] + replacement + result[end_pos:]
            search_start = m.start() + len(replacement)
        else:
            search_start = m.end()
    return result


#: Counted per DATEDIFF('week') converted to diff_days / 7 (BL-334): the record is
#: flagged from this counter, never from the output text, so an exact
#: DATEDIFF('day', a, b) / 7 source is not.
WEEK_DIFF_DAYS = "week_diff_days"


def _convert_datediff(expr: str, registry: dict | None = None,
                      notes: dict | None = None) -> str:
    _PAT = re.compile(r"\bDATEDIFF\s*\(", re.IGNORECASE)
    result = expr
    search_start = 0
    safety = 0
    while safety < 20:
        m = _PAT.search(result, search_start)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            search_start = m.end()
            continue
        args, end_pos = extracted
        if len(args) >= 3:
            unit = _resolve_unit(args[0], registry)
            start_date = args[1].strip()
            end_date = args[2].strip()
            ts_func = _DATEDIFF_UNIT_MAP.get(unit)
            if ts_func:
                # Note: arg order REVERSED — TS takes (end, start)
                replacement = f"{ts_func} ( {end_date} , {start_date} )"
            elif unit == "hour":
                replacement = f"diff_time ( {end_date} , {start_date} ) / 3600"
            elif unit == "minute":
                replacement = f"diff_time ( {end_date} , {start_date} ) / 60"
            elif unit == "week":
                replacement = f"diff_days ( {end_date} , {start_date} ) / 7"
                if notes is not None:
                    notes[WEEK_DIFF_DAYS] = notes.get(WEEK_DIFF_DAYS, 0) + 1
            else:
                # Unknown unit — no ThoughtSpot diff function exists. Leave
                # the original DATEDIFF(...) text in place rather than
                # fabricate a nonexistent function name; validate_output
                # flags any surviving DATEDIFF call as unmapped.
                search_start = end_pos
                continue
            result = result[:m.start()] + replacement + result[end_pos:]
            search_start = m.start() + len(replacement)
        else:
            search_start = m.end()
    return result


def _convert_dateadd(expr: str, registry: dict | None = None) -> str:
    _PAT = re.compile(r"\bDATEADD\s*\(", re.IGNORECASE)
    result = expr
    search_start = 0
    safety = 0
    while safety < 20:
        m = _PAT.search(result, search_start)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            search_start = m.end()
            continue
        args, end_pos = extracted
        if len(args) >= 3:
            unit = _resolve_unit(args[0], registry)
            n = args[1].strip()
            date_expr = args[2].strip()
            ts_func = _DATEADD_UNIT_MAP.get(unit)
            if ts_func is None:
                # Unknown unit — no ThoughtSpot add function exists. Leave
                # the original DATEADD(...) text in place rather than
                # fabricate a nonexistent function name; validate_output
                # flags any surviving DATEADD call as unmapped.
                search_start = end_pos
                continue
            # Note: arg order changes — TS takes (date, n)
            replacement = f"{ts_func} ( {date_expr} , {n} )"
            result = result[:m.start()] + replacement + result[end_pos:]
            search_start = m.start() + len(replacement)
        else:
            search_start = m.end()
    return result


# Tableau DATEPART('weekday', date, [start_of_week]) returns an INTEGER 1-7,
# 1 = start_of_week; "If it is omitted, the start of week is determined by the
# data source" (help.tableau.com .../functions_functions_date.htm). The old
# mapping to day_of_week returned the day NAME — a string compared to numbers.
# ThoughtSpot day_number_of_week is fixed 1 = Monday ... 7 = Sunday (live-probed
# 2026-10-06), so the numbering is rebuilt via formula_common.ts_weekday_number.
# Origin, in order: a literal start_of_week argument; else the datasource's
# Week start (`week_start`, read by twb.parse_twb from <date-options
# start-of-week=...>, written only when the author changed it); else SUNDAY —
# the en-US default ("Sunday is the first day of the week in the US, while
# Monday is the first day in the EU", help.tableau.com Date Properties). That
# last case is an assumption the TWB cannot confirm (the locale fallback is the
# author's machine), so it is counted in `notes` under WEEK_START_ASSUMED and
# surfaced to the conversion report as a validation warning (BL-334).
_TABLEAU_DEFAULT_WEEK_START = "sunday"
WEEK_START_ASSUMED = "weekday_week_start_assumed"


def _datepart_weekday(args: list[str], registry: dict | None,
                      week_start: str | None = None,
                      notes: dict | None = None) -> str | None:
    date_expr = args[1].strip()
    if len(args) >= 3:
        start = _resolve_unit(args[2], registry)
        if start not in WEEKDAY_FIRST_DAY_INDEX:
            return None  # a field/parameter start day — leave it flagged
    elif week_start and week_start.lower() in WEEKDAY_FIRST_DAY_INDEX:
        start = week_start.lower()
    else:
        start = _TABLEAU_DEFAULT_WEEK_START
        if notes is not None:
            notes[WEEK_START_ASSUMED] = notes.get(WEEK_START_ASSUMED, 0) + 1
    return ts_weekday_number(date_expr, first_day=start, base=1)


def _datepart_replacement(unit: str, args: list[str], registry: dict | None,
                          week_start: str | None,
                          notes: dict | None) -> str | None:
    """ThoughtSpot form of DATEPART(unit, date, ...), or None if unmappable."""
    date_expr = args[1].strip()
    if unit == "iso-weekday":  # always Monday = 1 — a clean rename
        return ts_weekday_number(date_expr, first_day="monday", base=1)
    if unit == "weekday":
        return _datepart_weekday(args, registry, week_start, notes)
    if unit == "week":
        _note_week_mismatch(args, registry, week_start, notes)
    ts_func = _DATEPART_UNIT_MAP.get(unit)
    return f"{ts_func} ( {date_expr} )" if ts_func else None


def _convert_datepart(expr: str, registry: dict | None = None,
                      week_start: str | None = None,
                      notes: dict | None = None) -> str:
    _PAT = re.compile(r"\bDATEPART\s*\(", re.IGNORECASE)
    result = expr
    search_start = 0
    safety = 0
    while safety < 20:
        m = _PAT.search(result, search_start)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            search_start = m.end()
            continue
        args, end_pos = extracted
        if len(args) >= 2:
            unit = _resolve_unit(args[0], registry)
            replacement = _datepart_replacement(unit, args, registry,
                                                week_start, notes)
            if replacement is None:
                # Unknown unit — no ThoughtSpot extractor exists. Leave the
                # original DATEPART(...) text in place rather than fabricate
                # a nonexistent function name; validate_output flags any
                # surviving DATEPART call as an unmapped function.
                search_start = end_pos
                continue
            result = result[:m.start()] + replacement + result[end_pos:]
            search_start = m.start() + len(replacement)
        else:
            search_start = m.end()
    return result


def _convert_datename(expr: str, registry: dict | None = None) -> str:
    _PAT = re.compile(r"\bDATENAME\s*\(", re.IGNORECASE)
    result = expr
    search_start = 0
    safety = 0
    while safety < 20:
        m = _PAT.search(result, search_start)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            search_start = m.end()
            continue
        args, end_pos = extracted
        if len(args) >= 2:
            unit = _resolve_unit(args[0], registry)
            date_expr = args[1].strip()
            if unit == "month":
                replacement = f"month ( {date_expr} )"
            else:
                # Unknown unit — no ThoughtSpot extractor exists. Leave the
                # original DATENAME(...) text in place rather than fabricate
                # a nonexistent function name; validate_output flags any
                # surviving DATENAME call as an unmapped function.
                search_start = end_pos
                continue
            result = result[:m.start()] + replacement + result[end_pos:]
            search_start = m.start() + len(replacement)
        else:
            search_start = m.end()
    return result
