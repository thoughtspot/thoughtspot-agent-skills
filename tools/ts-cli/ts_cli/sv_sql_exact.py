"""Snowflake SQL -> ThoughtSpot: the constructs that are NOT renames.

Moved out of ``sv_sql.py`` (#572 review): each one either shifts an argument, picks a
native function by unit, or falls back to an exact ``sql_*_op`` pass-through where no
native form computes the same value (BL-340..343). Pure functions, no I/O.

``EXACT_FORM_EMITS`` declares, per source function handled by ``EXACT_FORM_CALLS``, every
ThoughtSpot function its handler can emit. ``check_mapping_code_sync.py`` reads it: the
handlers are function references, which its dict scan cannot see, so the declaration is
what puts them under the doc/code gate. A handler without a declaration fails that gate.
"""
from __future__ import annotations

from ts_cli.formula_common import (
    UntranslatableError,
    expr_is_aggregated,
    sql_passthrough_call,
    sql_substr_to_ts,
)
from ts_cli.sql_forms import sqlf_div0, sqlf_div0null, sqlf_rounded_cast, sqlf_scaled_floor_ceil


def is_aggregated(x: str, resolver) -> bool:
    """True if translated ``x`` is aggregated — by its text, or because it holds a
    metric reference the resolver handed out (``[formula_X]`` hides it)."""
    refs = getattr(resolver, "metric_refs", ()) or ()
    return expr_is_aggregated(x) or any(r in x for r in refs)


def row_level_args(name: str, args: list[str], resolver) -> None:
    """A row-level sql_*_op pass-through cannot wrap an aggregate."""
    if any(is_aggregated(a, resolver) for a in args):
        raise UntranslatableError(
            f"{name} over an aggregate has no exact ThoughtSpot form (its exact form is a "
            "row-level pass-through)")


def _arity(name: str, args: list[str], allowed: tuple[int, ...]) -> None:
    if len(args) not in allowed:
        want = " or ".join(str(n) for n in allowed)
        raise UntranslatableError(f"{name} expects {want} arguments, got {len(args)}")


def call_months_between(name: str, args: list[str], resolver) -> str:
    """MONTHS_BETWEEN(d1, d2) -> exact pass-through, source order kept (BL-342). Snowflake's
    value is fractional (31-day months, integral only on the same day or both month ends,
    6 places); diff_months counts boundaries crossed (Jan 20 -> Mar 15: 2, not 1.838710)."""
    _arity(name, args, (2,))
    row_level_args(name, args, resolver)
    return sql_passthrough_call("sql_double_op", name, args)


def call_to_char(name: str, args: list[str], resolver) -> str:
    """TO_CHAR / TO_VARCHAR(x[, fmt]) -> pass-through (BL-343). The format used to be
    dropped for one-argument to_string, rejected on a DATE and on Text (probe record §7); no
    ThoughtSpot function is documented as equivalent to a format model. The SQL is
    Snowflake's own, so it is exact with the format given; WITHOUT one, a date or timestamp
    renders by the session's DATE_OUTPUT_FORMAT / TIMESTAMP_OUTPUT_FORMAT, which is
    ThoughtSpot's connection session rather than the source's."""
    _arity(name, args, (1, 2))
    row_level_args(name, args, resolver)
    return sql_passthrough_call("sql_string_op", name, args)


def call_substr(name: str, args: list[str], resolver) -> str:
    """1-based SUBSTR -> zero-based substr, or an exact pass-through (BL-340)."""
    out = sql_substr_to_ts(name, args)
    if out.startswith("sql_"):
        row_level_args(name, args, resolver)
    return out


def call_div0(name: str, args: list[str], resolver) -> str:
    """DIV0 / DIV0NULL -> the NULL-guarded ``safe_divide`` forms (BL-357, ``sql_forms``).
    ``safe_divide`` alone is 0 for ``DIV0(NULL, 0)``, which Snowflake returns as NULL."""
    _arity(name, args, (2,))
    return (sqlf_div0 if name == "DIV0" else sqlf_div0null)(args[0], args[1])


def call_floor_ceil(name: str, args: list[str], resolver) -> str:
    """FLOOR / CEIL / CEILING(x[, scale]) (BL-361). Not snapped: Snowflake's own FLOOR of a
    DOUBLE is plain double arithmetic (``FLOOR(0.29::DOUBLE, 2)`` = 0.28, live 2026-10-07),
    which ``floor ( x * 100 ) * 0.01`` reproduces; a NUMBER scales exactly either way."""
    _arity(name, args, (1, 2))
    fn = "floor" if name == "FLOOR" else "ceil"
    if len(args) == 1:
        return f"{fn} ( {args[0]} )"
    return sqlf_scaled_floor_ceil(fn, args[0], args[1], snap=False)


def call_to_number(name: str, args: list[str], resolver) -> str:
    """TO_NUMBER / TO_DECIMAL / TO_NUMERIC(x[, fmt][, p, s]) (BL-359). Snowflake's default
    scale is 0 and the conversion ROUNDS (``TO_NUMBER('2.5')`` = 3, ``TO_NUMBER(2.567)`` = 3,
    ``TO_DECIMAL(2.567, 10, 2)`` = 2.57, live 2026-10-07); it was ``to_double``, which keeps
    every digit. Scale 0 -> ``to_integer`` (rounds the same way, probe record §7); a positive
    scale -> ``sqlf_rounded_cast``; a format model -> an exact pass-through."""
    _arity(name, args, (1, 2, 3, 4))
    if len(args) == 1:
        return f"to_integer ( {args[0]} )"
    tail = [a.strip() for a in args[1:]]
    if len(tail) == 2 and all(a.isdigit() for a in tail):
        if int(tail[1]) == 0:
            return f"to_integer ( {args[0]} )"
        return sqlf_rounded_cast(args[0], int(tail[1]), f"{name}({{0}}, {tail[0]}, {tail[1]})",
                                 is_aggregated(args[0], resolver))
    row_level_args(name, args, resolver)
    return sql_passthrough_call("sql_double_op", name, args)


EXACT_FORM_CALLS = {"TO_CHAR": call_to_char, "TO_VARCHAR": call_to_char,
                    "SUBSTR": call_substr, "SUBSTRING": call_substr,
                    "MONTHS_BETWEEN": call_months_between,
                    "DIV0": call_div0, "DIV0NULL": call_div0,
                    "FLOOR": call_floor_ceil, "CEIL": call_floor_ceil,
                    "CEILING": call_floor_ceil, "TO_NUMBER": call_to_number,
                    "TO_DECIMAL": call_to_number, "TO_NUMERIC": call_to_number}
EXACT_FORM_EMITS = {"TO_CHAR": ("sql_string_op",), "TO_VARCHAR": ("sql_string_op",),
                    "SUBSTR": ("substr", "strlen", "sql_string_op"),
                    "SUBSTRING": ("substr", "strlen", "sql_string_op"),
                    "MONTHS_BETWEEN": ("sql_double_op",),
                    "DIV0": ("isnull", "safe_divide"),
                    "DIV0NULL": ("isnull", "safe_divide", "ifnull"),
                    "FLOOR": ("floor",), "CEIL": ("ceil",), "CEILING": ("ceil",),
                    "TO_NUMBER": ("to_integer", "round", "sql_double_op"),
                    "TO_DECIMAL": ("to_integer", "round", "sql_double_op"),
                    "TO_NUMERIC": ("to_integer", "round", "sql_double_op")}


# DATEDIFF(unit, start, end) -> diff_<unit> ( end , start ). Snowflake counts unit
# BOUNDARIES crossed, and so does each native function here — read from its compiled
# SQL and checked by value (formula fidelity M0, se-thoughtspot 2026-10-06; the rows
# of ts-snowflake-formula-translation.md quote it). YEAR was diff_days / 365 (BL-341).
# Two units are NOT native — each is an exact pass-through, because the converter
# has no channel to show a trap (#572 review):
#   WEEK — diff_weeks fixes a Monday week start; Snowflake's DATEDIFF(week) follows
#          WEEK_START.
#   HOUR — diff_hours compiles to DATEDIFF('HOUR', DATE '1970-01-01', x) differences,
#          which on a TIMESTAMP_TZ count hours in UTC while Snowflake counts them in
#          the value's own offset: at +05:30, 10:59 -> 11:01 is 1 in Snowflake and 0
#          in ThoughtSpot (M0 sf-ts-005, 4 of 10 rows wrong, 2026-10-06). TIMESTAMP_NTZ
#          and DATE matched (sf-ts-001, sf-date-014), and diff_minutes matched on the
#          same TIMESTAMP_TZ rows (sf-ts-006) — every real offset is whole minutes.
DATEDIFF_UNIT = {"DAY": "diff_days", "MONTH": "diff_months", "QUARTER": "diff_quarters",
                 "YEAR": "diff_years", "MINUTE": "diff_minutes", "SECOND": "diff_time"}
DATEDIFF_PASSTHROUGH_UNITS = frozenset({"WEEK", "HOUR"})
# Snowflake's documented date/time part aliases (docs: "Supported date and time parts").
DATE_PART_ALIASES = {a: u for u, al in {
    "DAY": "D DD DAYS DAYOFMONTH", "WEEK": "W WK WEEKOFYEAR WOY WY",
    "MONTH": "MM MON MONS MONTHS", "QUARTER": "Q QTR QTRS QUARTERS",
    "YEAR": "Y YY YYY YYYY YR YEARS YRS", "HOUR": "H HH HH24 HR HOURS HRS",
    "MINUTE": "M MI MIN MINUTES MINS", "SECOND": "S SEC SECONDS SECS",
}.items() for a in al.split()}


def datediff_to_ts(unit: str, args: list[str], resolver) -> str:
    """``DATEDIFF(unit, start, end)`` with ``args = [start, end]``."""
    unit = DATE_PART_ALIASES.get(unit, unit)
    if unit in DATEDIFF_PASSTHROUGH_UNITS:
        row_level_args("DATEDIFF", args, resolver)
        return (f'sql_int_op ( "DATEDIFF({unit.lower()}, {{0}}, {{1}})" , '
                f"{args[0]} , {args[1]} )")
    fn = DATEDIFF_UNIT.get(unit)
    if fn is None:
        raise UntranslatableError(
            f"DATEDIFF unit '{unit}' not mapped "
            f"(DAY|WEEK|MONTH|QUARTER|YEAR|HOUR|MINUTE|SECOND)")
    return f"{fn} ( {args[1]} , {args[0]} )"


# --- CAST to NUMBER / DECIMAL (BL-359) ------------------------------------------------

def cast_params(cur) -> list[str]:
    """The ``(p, s)`` after a CAST target type, as raw token texts (empty when absent)."""
    nk, nt = cur.peek()
    if not (nk == "op" and nt == "("):
        return []
    cur.advance()
    params: list[str] = []
    depth = 1
    while depth:
        k2, t2 = cur.advance()
        if k2 == "op":
            depth += {"(": 1, ")": -1}.get(t2, 0)
        elif k2 == "number" and depth == 1:
            params.append(t2)
    return params


CAST_NUMBER = frozenset({"NUMBER", "DECIMAL", "NUMERIC"})


def cast_number(type_name: str, params: list[str], inner: str, resolver) -> str:
    """``CAST(x AS NUMBER[(p[, s])])``: Snowflake's default scale is 0, and the cast ROUNDS
    half away from zero (``CAST(2.5 AS NUMBER)`` = 3, ``CAST(2.567 AS NUMBER(10,2))`` = 2.57,
    live 2026-10-07). It was ``to_double``, which keeps every digit — a silent wrong
    number (BL-359). Scale 0 -> ``to_integer``, which compiles to Snowflake's own INT cast
    (``NUMBER(38,0)``, rounding the same way); a positive scale -> ``sqlf_rounded_cast``."""
    s = int(params[1]) if len(params) > 1 else 0
    if s == 0:
        return f"to_integer ( {inner} )"
    p = params[0]
    return sqlf_rounded_cast(inner, s, f"CAST({{0}} AS {type_name}({p},{s}))",
                             is_aggregated(inner, resolver))
