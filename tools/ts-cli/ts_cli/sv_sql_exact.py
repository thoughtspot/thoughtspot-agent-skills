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


EXACT_FORM_CALLS = {"TO_CHAR": call_to_char, "TO_VARCHAR": call_to_char,
                    "SUBSTR": call_substr, "SUBSTRING": call_substr,
                    "MONTHS_BETWEEN": call_months_between}
EXACT_FORM_EMITS = {"TO_CHAR": ("sql_string_op",), "TO_VARCHAR": ("sql_string_op",),
                    "SUBSTR": ("substr", "strlen", "sql_string_op"),
                    "SUBSTRING": ("substr", "strlen", "sql_string_op"),
                    "MONTHS_BETWEEN": ("sql_double_op",)}


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
