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


# Keywords that can never continue a NOT operand: boolean connectors plus
# the CASE-structure keywords (a NOT inside a CASE condition ends at THEN).
_NOT_OPERAND_STOP_KWS = frozenset({"AND", "OR", "THEN", "WHEN", "ELSE", "END"})


# Arithmetic/comparison operators that can precede a postfix construct's
# left operand. 'and'/'or' are deliberately excluded — a boolean connector
# two positions back (e.g. `a = 1 AND b IN (...)`) must still pop `b`, not
# be treated as a compound operand.
_COMPOUND_GUARD_OPS = {"+", "-", "*", "/", "=", "!=", "<", ">", "<=", ">="}


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
        # collapse) — resolve it to null_if_zero here, never leak raw bytes.
        return f"null_if_zero ( {unit[len(_NULLIF0):]} )"
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
    if kind == "kw" and text in ("IN", "BETWEEN", "LIKE"):
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
        out = f"if ( {cond} , {val} , {out} )"
    return out


def _construct_cast(cur, resolver) -> str:
    from ts_cli.databricks.mv_sql import UntranslatableError, _expr_units
    cur.expect_op("(")
    inner_units = _expr_units(cur, resolver, frozenset({"AS"}))
    kind, text = cur.advance()
    if text != "AS":
        raise UntranslatableError("CAST without AS")
    tk, _ttext = cur.advance()  # the target type ident — dropped (implicit in TS)
    if tk != "ident":
        raise UntranslatableError("CAST with a non-identifier target type")
    nk, nt = cur.peek()
    if nk == "op" and nt == "(":  # DECIMAL(10,2)-style precision — skip it
        cur.advance()
        depth = 1
        while depth:
            k2, t2 = cur.advance()
            if k2 == "op" and t2 == "(":
                depth += 1
            elif k2 == "op" and t2 == ")":
                depth -= 1
    cur.expect_op(")")
    if len(inner_units) == 1:
        return inner_units[0]
    return f"( {' '.join(inner_units)} )"


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


def _construct_in(cur, resolver, units: list[str]) -> None:
    from ts_cli.databricks.mv_sql import _expr
    operand = _pop_operand(units, "IN")
    cur.expect_op("(")
    values: list[str] = []
    while True:
        values.append(_expr(cur, resolver))
        kind, text = cur.peek()
        if kind == "op" and text == ",":
            cur.advance()
            continue
        cur.expect_op(")")
        break
    ors = " or ".join(f"{operand} = {v}" for v in values)
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
