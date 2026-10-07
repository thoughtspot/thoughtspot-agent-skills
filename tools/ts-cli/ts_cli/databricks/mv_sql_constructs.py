"""CASE/CAST/NOT/IS/IN/BETWEEN keyword-construct handlers for mv_sql.

Split out of mv_sql.py to keep both files under the file-size warn line
(BL-063 PR3) — pure function move, no behavior change. Pure functions: SQL
cursor + column resolver in, TS formula text out. No I/O, no network calls.
stdlib only (Genie-vendorable — see package docstring).

Circular-import seam: this module is a callee of mv_sql._keyword_construct,
but its own handlers need mv_sql's expression-parsing primitives
(_expr/_expr_units/_string_literal/_ident_unit/_keyword_unit/
_collapse_nullif_markers/_NULLIF0/UntranslatableError) back. To keep both
modules independently importable regardless of which loads first, every
cross-reference to mv_sql is a late import inside the function that needs
it — this module has no top-level dependency on mv_sql.
"""
from __future__ import annotations

from ts_cli.formula_common import CAST_MAP_LOAD_BEARING, CAST_TYPES_WIDENING
from ts_cli.sql_forms import SQLF_DIV_MARK, sqlf_rounded_cast, sqlf_trunc_toward_zero


# Keywords that can never continue a NOT operand: boolean connectors plus
# the CASE-structure keywords (a NOT inside a CASE condition ends at THEN).
_NOT_OPERAND_STOP_KWS = frozenset({"AND", "OR", "THEN", "WHEN", "ELSE", "END"})


# Arithmetic/comparison operators that can precede a postfix construct's
# left operand. 'and'/'or' are deliberately excluded — a boolean connector
# two positions back (e.g. `a = 1 AND b IN (...)`) must still pop `b`, not
# be treated as a compound operand.
_COMPOUND_GUARD_OPS = {"+", "-", "*", "/", "%", "||", SQLF_DIV_MARK,
                       "=", "!=", "<", ">", "<=", ">="}


def _pop_operand(units: list[str], construct: str) -> str:
    from ts_cli.databricks.mv_sql import UntranslatableError, _NULLIF0
    if not units:
        raise UntranslatableError(f"'{construct}' without a left operand")
    if len(units) >= 2 and units[-2] in _COMPOUND_GUARD_OPS:
        raise UntranslatableError(
            f"compound left operand of {construct} — parenthesize it "
            f"(e.g. (a * b) {construct} …)")
    unit = units.pop()
    if unit.startswith(_NULLIF0):
        # NULLIF marker popped mid-expression (before the end-of-expr
        # collapse) — resolve it to the CASE form here (no null_if_zero in ThoughtSpot, BL-344),
        # never leak raw bytes.
        return f"( if ( {unit[len(_NULLIF0):]} = 0 ) then null else {unit[len(_NULLIF0):]} )"
    return unit


def _terminates_operand(nk: str | None, nt: str | None) -> bool:
    """True when the next token ends a bare-column operand."""
    if nk is None:
        return True
    if nk == "kw" and nt in _NOT_OPERAND_STOP_KWS:
        return True
    return nk == "op" and nt in (")", ",")


def _construct_not(cur, resolver, units: list[str]) -> None:
    from ts_cli.databricks.mv_sql import UntranslatableError, _expr
    kind, text = cur.peek()
    if kind == "kw" and text == "IN":
        # BL-316 item 3 — `x NOT IN (a, b)` -> ( x != a and x != b )
        cur.advance()
        operand = _pop_operand(units, "NOT IN")
        values = _in_values(cur, resolver)
        if "null" in values:
            raise UntranslatableError(
                "NOT IN with a NULL in the list is never true in SQL; the != chain "
                "would not reproduce that — rewrite without the NULL")
        ands = " and ".join(f"{operand} != {v}" for v in values)
        units.append(f"( {ands} )")
        return
    if kind == "kw" and text in ("LIKE", "ILIKE", "RLIKE"):
        from ts_cli.databricks.mv_sql import _construct_like
        cur.advance()
        _construct_like(text, cur, units, negate=True)  # BL-362
        return
    if kind == "kw" and text == "BETWEEN":
        raise UntranslatableError(
            f"NOT {text} has no documented ThoughtSpot mapping")
    if kind == "ident":
        nk, nt = cur.peek(1)
        if _terminates_operand(nk, nt):  # NOT <boolean column>
            cur.advance()
            units.append(f"{resolver(text)} = false")
            return
        if not (nk == "op" and nt == "("):
            # NOT <col> <comparison/IS/IN/…> — the comparison binds tighter
            # than NOT in SQL, so wrap the whole comparison, not just the col.
            inner = _expr(cur, resolver, _NOT_OPERAND_STOP_KWS)
            units.append(f"not ( {inner} )")
            return
    # NOT <group/call/…>: translate exactly one operand
    operand_units = _one_operand(cur, resolver)
    units.append(f"not ( {' '.join(operand_units)} )")


def _one_operand(cur, resolver) -> list[str]:
    """Translate a single operand (group, call, literal, or column)."""
    from ts_cli.databricks.mv_sql import (
        UntranslatableError, _collapse_nullif_markers, _expr, _ident_unit,
        _keyword_unit, _string_literal)
    kind, text = cur.peek()
    if kind is None:
        raise UntranslatableError("expected an operand")
    units: list[str] = []
    cur.advance()
    if kind == "string":
        units.append(_string_literal(text))
    elif kind == "number":
        units.append(text)
    elif kind == "op" and text == "(":
        inner = _expr(cur, resolver)
        cur.expect_op(")")
        units.append(f"( {inner} )")
    elif kind == "ident":
        _ident_unit(text, cur, resolver, units)  # cursor already past the ident
    elif kind == "kw":
        _keyword_unit(text, cur, resolver, units)
    else:
        raise UntranslatableError(f"unexpected operand {text!r}")
    _collapse_nullif_markers(units)  # never let a raw marker escape
    return units


def _construct_case(cur, resolver) -> str:
    from ts_cli.databricks.mv_sql import UntranslatableError, _expr
    branches: list[tuple[str, str]] = []
    else_val = "null"
    stop = frozenset({"WHEN", "THEN", "ELSE", "END"})
    while True:
        kind, text = cur.advance() if cur.peek()[0] is not None else (None, None)
        if kind is None:
            raise UntranslatableError("CASE without END")
        if text == "WHEN":
            cond = _expr(cur, resolver, stop)
            k2, t2 = cur.advance()
            if t2 != "THEN":
                raise UntranslatableError("CASE WHEN without THEN")
            val = _expr(cur, resolver, stop)
            branches.append((cond, val))
        elif text == "ELSE":
            else_val = _expr(cur, resolver, stop)
        elif text == "END":
            break
        else:
            raise UntranslatableError(f"unexpected {text!r} inside CASE")
    if not branches:
        raise UntranslatableError("CASE with no WHEN branch")
    out = else_val
    for cond, val in reversed(branches):
        out = f"if ( {cond} ) then {val} else {out}"
    return out


def _construct_cast(cur, resolver) -> str:
    from ts_cli.databricks.mv_sql import UntranslatableError, _expr_units
    cur.expect_op("(")
    inner_units = _expr_units(cur, resolver, frozenset({"AS"}))
    kind, text = cur.advance()
    if text != "AS":
        raise UntranslatableError("CAST without AS")
    tk, ttext = cur.advance()
    if tk != "ident":
        raise UntranslatableError("CAST with a non-identifier target type")
    # The target type used to be discarded here as "implicit in TS". It is not:
    # CAST(4.7 AS INT) must truncate and CAST(ts AS DATE) must drop the time, so
    # dropping it emitted a formula returning different numbers than the source,
    # silently (audit 4.1). The Snowflake engine already mapped it; the map now
    # lives in formula_common and both emit through it.
    type_name = ttext.upper()
    params = _cast_params(cur)
    cur.expect_op(")")
    inner = inner_units[0] if len(inner_units) == 1 else f"( {' '.join(inner_units)} )"
    special = _cast_64bit_or_decimal(type_name, params, inner)
    if special is not None:
        return special
    fn = CAST_MAP_LOAD_BEARING.get(type_name)
    if fn is not None:
        # Narrowing cast: the target changes the value, so it must be emitted.
        return f"{fn} ( {inner} )"
    if type_name in CAST_TYPES_WIDENING:
        # Widening/no-op: ThoughtSpot's arithmetic already promotes (live-verified),
        # and emitting a conversion here yields an unresolvable function.
        return inner
    raise UntranslatableError(
        f"CAST target type '{type_name}' not recognised — add it to "
        "CAST_MAP_LOAD_BEARING or CAST_TYPES_WIDENING in ts_cli/formula_common.py")


def _cast_params(cur) -> list[str]:
    """The ``(p, s)`` after a CAST target type, as raw token texts (empty when absent)."""
    nk, nt = cur.peek()
    if not (nk == "op" and nt == "("):
        return []
    cur.advance()
    params: list[str] = []
    depth = 1
    while depth:
        k2, t2 = cur.advance()
        if k2 == "op" and t2 == "(":
            depth += 1
        elif k2 == "op" and t2 == ")":
            depth -= 1
        elif k2 == "number" and depth == 1:
            params.append(t2)
    return params


#: Databricks' 64-bit integer types. ``to_integer`` compiles to ``CAST(x as int)``, which is
#: 32-bit on Databricks: ``CAST(1e12 AS BIGINT)`` came back 2147483647 (M2 ``dbx-round-009``).
_CAST_64BIT = frozenset({"BIGINT", "LONG"})
_CAST_DECIMAL = frozenset({"DECIMAL", "DEC", "NUMERIC"})


def _cast_64bit_or_decimal(type_name: str, params: list[str], inner: str):
    """The casts whose exact form is not in the shared CAST map, or None.

    * ``BIGINT`` / ``LONG`` (BL-359): row-level, the warehouse's own 64-bit cast
      (``sql_int_op``); over an aggregate, native truncation toward zero (``floor`` /
      ``ceil`` return INT64). Databricks' cast truncates toward zero.
    * ``DECIMAL(p, s)``: it ROUNDS half up to ``s`` places, and a bare ``DECIMAL`` is
      ``DECIMAL(10, 0)`` (``CAST(2.5 AS DECIMAL)`` = 3, live 2026-10-07) — so it is not the
      widening no-op the shared map lists it as. ``s = 0`` is an integral cast like BIGINT;
      ``s > 0`` is ``sql_forms.sqlf_rounded_cast``.
    """
    from ts_cli.databricks.mv_sql import UntranslatableError
    from ts_cli.formula_common import expr_is_aggregated
    if type_name in _CAST_DECIMAL:
        p = params[0] if params else "10"
        s = int(params[1]) if len(params) > 1 else 0
        if s > 0:
            return sqlf_rounded_cast(inner, s, f"CAST({{0}} AS DECIMAL({p},{s}))",
                                     expr_is_aggregated(inner))
        sql = f"CAST({{0}} AS DECIMAL({p},0))"
    elif type_name in _CAST_64BIT:
        sql = "CAST({0} AS BIGINT)"
    else:
        return None
    if expr_is_aggregated(inner):
        if type_name in _CAST_DECIMAL:
            raise UntranslatableError(
                f"CAST(… AS DECIMAL({params[0] if params else 10},0)) over an aggregate rounds "
                "half up — no exact native form")
        return sqlf_trunc_toward_zero(inner)
    return f'sql_int_op ( "{sql}" , {inner} )'


def _construct_is(cur, units: list[str]) -> None:
    from ts_cli.databricks.mv_sql import UntranslatableError
    operand = _pop_operand(units, "IS")
    kind, text = cur.advance()
    if text == "NULL":
        units.append(f"isnull ( {operand} )")
        return
    if text == "NOT":
        k2, t2 = cur.advance()
        if t2 == "NULL":
            units.append(f"not ( isnull ( {operand} ) )")
            return
    raise UntranslatableError("IS supports only IS NULL / IS NOT NULL")


def _in_values(cur, resolver) -> list[str]:
    """Parse the parenthesized value list after IN / NOT IN."""
    from ts_cli.databricks.mv_sql import _expr
    cur.expect_op("(")
    values: list[str] = []
    while True:
        values.append(_expr(cur, resolver))
        kind, text = cur.peek()
        if kind == "op" and text == ",":
            cur.advance()
            continue
        cur.expect_op(")")
        return values


def _construct_in(cur, resolver, units: list[str]) -> None:
    operand = _pop_operand(units, "IN")
    ors = " or ".join(f"{operand} = {v}" for v in _in_values(cur, resolver))
    units.append(f"( {ors} )")


def _construct_between(cur, resolver, units: list[str]) -> None:
    from ts_cli.databricks.mv_sql import UntranslatableError, _expr
    operand = _pop_operand(units, "BETWEEN")
    lo = _expr(cur, resolver, frozenset({"AND"}))
    kind, text = cur.advance()
    if text != "AND":
        raise UntranslatableError("BETWEEN without AND")
    hi = " ".join(_one_operand(cur, resolver))
    units.append(f"{operand} >= {lo} and {operand} <= {hi}")
