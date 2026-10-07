"""Databricks SQL calls with an exact ThoughtSpot form that is not a rename (BL-359..362).

Split out of ``mv_sql.py`` (file-size gate). Each handler takes ``(name, args)`` — the
already-translated argument texts — and is listed by name in ``mv_sql._EXACT_FORM_CALLS``,
whose ``EXACT_FORM_EMITS`` declares what each can emit (``check_mapping_code_sync.py``
requirement D). Semantics are Databricks' own, probed on the M2 SQL warehouse 2026-10-07
(``docs/reviews/2026-10-07-fidelity-m2-databricks.md``, "After fixes"). Pure functions,
stdlib only; vendored into the Genie notebook, so every top-level name is ``mvc_``-prefixed.
"""
from __future__ import annotations

from ts_cli.formula_common import (
    UntranslatableError,
    expr_is_aggregated,
    sql_passthrough_call,
)
from ts_cli.sql_forms import sqlf_mod, sqlf_plain_division, sqlf_scaled_floor_ceil


def _mvc_arity(name: str, args: list[str], allowed: tuple[int, ...]) -> None:
    if len(args) not in allowed:
        want = " or ".join(str(n) for n in allowed)
        raise UntranslatableError(f"{name} expects {want} arguments, got {len(args)}")


def _mvc_row_level(name: str, args: list[str]) -> None:
    if any(expr_is_aggregated(a) for a in args):
        raise UntranslatableError(
            f"{name} over an aggregate has no exact ThoughtSpot form (its exact form is a "
            "row-level pass-through)")


def mvc_floor_ceil(name: str, args: list[str], resolver=None) -> str:
    """``FLOOR(x[, s])`` / ``CEIL(x[, s])`` / ``CEILING`` — the scale form scaled by a power of
    ten, nudged for a DOUBLE (``sql_forms.sqlf_scaled_floor_ceil``, BL-361)."""
    _mvc_arity(name, args, (1, 2))
    fn = "floor" if name == "FLOOR" else "ceil"
    if len(args) == 1:
        return f"{fn} ( {args[0]} )"
    return sqlf_scaled_floor_ceil(fn, args[0], args[1], snap=True)


def mvc_mod(name: str, args: list[str], resolver=None) -> str:
    """``MOD(x, y)`` — the same form as ``x % y`` (``sql_forms.sqlf_mod``)."""
    _mvc_arity(name, args, (2,))
    return sqlf_mod(args[0], args[1], resolver)


def mvc_try_divide(name: str, args: list[str], resolver=None) -> str:
    """``try_divide(x, y)``: NULL on a zero divisor — ThoughtSpot's own ``/`` (BL-362)."""
    _mvc_arity(name, args, (2,))
    return sqlf_plain_division(args[0], args[1])


def mvc_nvl2(name: str, args: list[str], resolver=None) -> str:
    """``nvl2(a, b, c)``: ``b`` when ``a`` is not NULL, else ``c``."""
    _mvc_arity(name, args, (3,))
    return f"( if ( {args[0]} != null ) then {args[1]} else {args[2]} )"


#: trunc(date, fmt) units with a native ThoughtSpot form. WEEK is a pass-through: Databricks
#: truncates to Monday, ThoughtSpot's start_of_week follows the Model's calendar (BL-334).
_MVC_TRUNC = {"YEAR": "start_of_year", "YYYY": "start_of_year", "YY": "start_of_year",
              "QUARTER": "start_of_quarter",
              "MONTH": "start_of_month", "MM": "start_of_month", "MON": "start_of_month"}


def mvc_trunc(name: str, args: list[str], resolver=None) -> str:
    """``trunc(date, fmt)`` -> ``start_of_*`` (a DATE in both), or a pass-through for WEEK."""
    _mvc_arity(name, args, (2,))
    fmt = args[1].strip()
    if not (fmt.startswith("'") and fmt.endswith("'")):
        raise UntranslatableError("TRUNC with a non-literal format has no exact form")
    unit = fmt[1:-1].upper()
    if unit in _MVC_TRUNC:
        return f"{_MVC_TRUNC[unit]} ( {args[0]} )"
    if unit == "WEEK":
        _mvc_row_level(name, args)
        return sql_passthrough_call("sql_date_op", "trunc", args)
    raise UntranslatableError(f"TRUNC format {fmt} is not mapped (YEAR|QUARTER|MONTH|WEEK)")


def mvc_last_day(name: str, args: list[str], resolver=None) -> str:
    """``last_day(d)`` -> the day before the next month's first (a DATE, as in Databricks)."""
    _mvc_arity(name, args, (1,))
    return f"add_days ( add_months ( start_of_month ( {args[0]} ) , 1 ) , -1 )"


def mvc_passthrough(op: str):
    """A row-level pass-through of the call itself: the warehouse runs its own function."""
    def handler(name: str, args: list[str], resolver=None) -> str:
        _mvc_row_level(name, args)
        return sql_passthrough_call(op, name.lower(), args)
    return handler


#: bround (HALF_EVEN rounding), instr (case-sensitive, 1-based, 0 when absent), concat_ws
#: (skips NULL arguments, unlike concat) and to_date over a column have no native form.
mvc_bround = mvc_passthrough("sql_double_op")
mvc_instr = mvc_passthrough("sql_int_op")
mvc_concat_ws = mvc_passthrough("sql_string_op")
mvc_to_date_expr = mvc_passthrough("sql_date_op")
