"""Logical and information handlers (Excel map, Logical / Information), and IFERROR by cause
(E8): a division becomes ``safe_divide`` (fallback 0, or ``""`` — APPROXIMATED), the map row's
``if ( b = 0 ) then v else a / b`` for one division with another fallback, ``ifnull`` around a
conversion; any other error cause is NEEDS_REVIEW."""
from __future__ import annotations

from typing import Optional

from ts_cli.excel import nodes as X
from ts_cli.excel import tsast as T
from ts_cli.excel.functions_text import find_call, search_call
from ts_cli.excel.helpers import fold, is_range, need

NULL_DIVISOR_TRAP = ("a blank (NULL) divisor: Excel reads it as 0 and returns the IFERROR "
                     "fallback; safe_divide returns NULL — wrap the divisor in ifnull ( … , 0 ) "
                     "if the column can be blank (E8)")
BLANK_FALLBACK_TRAP = ("IFERROR fallback \"\" (blank) in a numeric formula: ThoughtSpot has no "
                       "blank number, so safe_divide returns 0 where Excel showed a blank; "
                       "write IFERROR(…, 0) in the sheet for exact parity, or use "
                       "if ( b = 0 ) then null else a / b for a NULL")
MULTI_DIVISION_TRAP = ("IFERROR covers {n} divisions: Excel returns the fallback for the WHOLE "
                       "expression when any divisor is 0; safe_divide makes only the failing "
                       "ratio 0, so the rest still computes")

# Excel functions that cannot themselves raise an error for the inputs a sheet passes them —
# an IFERROR whose only error source is a division may contain these.
_ERROR_FREE = {"SUM", "ABS", "ROUND", "ROUNDUP", "ROUNDDOWN", "MAX", "MIN", "IF", "AND", "OR",
               "NOT", "INT", "TODAY", "YEAR", "MONTH", "DAY", "IFERROR"}
_CONVERSIONS = {"VALUE", "DATEVALUE"}


def _safe_divide_idiom(n):
    """``IF(b=0, 0, a/b)`` → (a, b): the Excel map IFERROR row's divide form with fallback 0,
    which is exactly ``safe_divide`` (it compiles to ``CASE WHEN b = 0 THEN 0 ELSE a / …``)."""
    if len(n.args) != 3:
        return None
    cond, then_node, else_node = n.args
    if not (isinstance(cond, X.Binary) and cond.op == "=" and isinstance(cond.right, X.Num)
            and float(cond.right.text) == 0):
        return None
    if not (isinstance(then_node, X.Num) and float(then_node.text) == 0):
        return None
    if isinstance(else_node, X.Binary) and else_node.op == "/" and else_node.right == cond.left:
        return else_node.left, else_node.right
    return None


def _if(tr, n):
    need(tr, n, 2, 3)
    idiom = _safe_divide_idiom(n)
    if idiom is not None:
        tr.trap(NULL_DIVISOR_TRAP.replace("the IFERROR fallback", "0"))
        saved, tr.division_mode = tr.division_mode, "plain"
        try:
            return T.call("safe_divide", tr.expr(idiom[0]), tr.expr(idiom[1]))
        finally:
            tr.division_mode = saved
    cond = tr.as_condition(tr.expr(n.args[0]))
    then_node = n.args[1]
    else_node = n.args[2] if len(n.args) == 3 else None
    if isinstance(then_node, X.Missing):
        tr.review("IF with an omitted value_if_true returns 0 in Excel; no rule")
    then_v = tr.expr(then_node)
    if else_node is None or isinstance(else_node, X.Missing):
        tr.trap("IF without value_if_false returns FALSE in Excel; ThoughtSpot needs a "
                "type-matched else — emitted else null", downgrade=True)
        return T.ifelse(cond, then_v, T.lit_null())
    return T.ifelse(cond, *_branches(tr, then_v, tr.expr(else_node)))


def _branches(tr, a: dict, b: dict) -> tuple:
    """A ``""`` branch beside a numeric one becomes ``null`` (a type-matched blank)."""
    ta, tb = tr.type_of(a), tr.type_of(b)
    for blank_first in (True, False):
        blank, other, t_other = (a, b, tb) if blank_first else (b, a, ta)
        if T.is_lit(blank, "string", "''") and t_other is None:
            note = (f"an IF branch returns \"\" beside {T.to_text(other)} (type unknown): if "
                    "that is a number, ThoughtSpot rejects the mixed branches — use null instead "
                    "(pass data_type in --columns to decide)")
            tr.note(note)
            tr.need_type(other, "blank IF branch", note)
        if T.is_lit(blank, "string", "''") and t_other == "number":
            tr.trap("an IF branch returning \"\" beside a number: ThoughtSpot branches must "
                    "share a type, so the blank became null", downgrade=True)
            blank = T.lit_null()
            return (blank, other) if blank_first else (other, blank)
    return a, b


def _ifs(tr, n):
    if len(n.args) < 2 or len(n.args) % 2:
        tr.review("IFS needs condition / value pairs")
    pairs = [(n.args[i], n.args[i + 1]) for i in range(0, len(n.args), 2)]
    other: Optional[dict] = None
    if isinstance(pairs[-1][0], X.Bool) and pairs[-1][0].value:
        other = tr.expr(pairs.pop()[1])
    else:
        tr.trap("IFS with no TRUE default: Excel returns #N/A when no test holds; ThoughtSpot "
                "returns NULL (else null)")
        other = T.lit_null()
    for cond, val in reversed(pairs):
        other = T.ifelse(tr.as_condition(tr.expr(cond)), tr.expr(val), other)
    return other


def _switch(tr, n):
    if len(n.args) < 3:
        tr.review("SWITCH needs an expression and at least one value / result pair")
    subject = tr.expr(n.args[0])
    rest = list(n.args[1:])
    other = tr.expr(rest.pop()) if len(rest) % 2 else T.lit_null()
    for i in range(len(rest) - 2, -1, -2):
        other = T.ifelse(T.binop("=", subject, tr.expr(rest[i])), tr.expr(rest[i + 1]), other)
    return other


def _logical(op: str):
    def handler(tr, n):
        if not n.args:
            tr.review(f"{n.name}() with no arguments")
        if any(is_range(a) for a in n.args):
            tr.review(f"{n.name} over a range is an aggregate test (Excel map {n.name} row: "
                      "count_if over a key) — not covered")
        return fold(op, [tr.as_condition(tr.expr(a)) for a in n.args])
    return handler


def _not(tr, n):
    need(tr, n, 1, 1)
    return T.unop("not", tr.as_condition(tr.expr(n.args[0])))


def _const(value: bool):
    def handler(tr, n):
        need(tr, n, 0, 0)
        return T.lit_bool(value)
    return handler


def _isblank(tr, n):
    need(tr, n, 1, 1)
    tr.note("ISBLANK → isnull: a sheet that stores empty cells as '' needs "
            "isnull ( x ) or x = '' (Excel map ISBLANK row)")
    return T.call("isnull", tr.expr(n.args[0]))


def _isnumber(tr, n):
    need(tr, n, 1, 1)
    arg = n.args[0]
    if isinstance(arg, X.Call) and arg.name == "SEARCH":
        pos = search_call(tr, arg)
        return T.call("contains", pos["args"][0], pos["args"][1])
    if isinstance(arg, X.Call) and arg.name == "FIND":
        return T.binop(">", find_call(tr, arg), T.lit_number("0"))
    if isinstance(arg, X.Call) and arg.name == "VALUE" and len(arg.args) == 1:
        # not ( isnull ( … ) ): ThoughtSpot has no isnotnull (probe record §7, BL-339)
        return T.unop("not", T.call("isnull", T.call("to_double", tr.expr(arg.args[0]))))
    value = tr.expr(arg)
    t = tr.type_of(value)
    if t == "number" and value.get("node") in ("col", "ref"):
        # a blank cell is not a number to Excel
        return T.unop("not", T.call("isnull", value))
    if t is None:
        tr.review("ISNUMBER on a value of unknown type: a type test resolves from the column's "
                  "type (Excel map E15) — pass data_type in --columns")
    return T.lit_bool(t == "number")


# ---------------------------------------------------------------------------
# IFERROR
# ---------------------------------------------------------------------------

def _error_sources(node) -> tuple[int, set]:
    """(number of divisions, names of calls that are neither error-free nor conversions)."""
    divisions, others = 0, set()
    for x in X.walk(node):
        if isinstance(x, X.Binary) and x.op == "/":
            divisions += 1
        elif isinstance(x, X.Call) and x.name not in _ERROR_FREE | _CONVERSIONS:
            others.add(x.name)
    return divisions, others


def _fallback_kind(node) -> str:
    if node is None:
        return "none"
    if isinstance(node, X.Missing) or (isinstance(node, X.Num) and float(node.text) == 0):
        return "zero"
    if isinstance(node, X.Str) and node.value == "":
        return "blank"
    return "value"


def _with_mode(tr, node, mode):
    saved, tr.division_mode = tr.division_mode, mode
    try:
        return tr.expr(node)
    finally:
        tr.division_mode = saved


def iferror_divisions(tr, value, fallback, divisions: int) -> dict:
    kind = _fallback_kind(fallback)
    if kind in ("zero", "blank"):
        out = _with_mode(tr, value, "safe")
        tr.trap(NULL_DIVISOR_TRAP)
        if kind == "blank":
            tr.trap(BLANK_FALLBACK_TRAP, downgrade=True)
        if divisions > 1:
            tr.trap(MULTI_DIVISION_TRAP.format(n=divisions), downgrade=True)
        return out
    if divisions == 1 and isinstance(value, X.Binary) and value.op == "/":
        num, den = _with_mode(tr, value.left, "plain"), _with_mode(tr, value.right, "plain")
        fb = tr.expr(fallback)
        tr.trap(NULL_DIVISOR_TRAP)
        return T.ifelse(T.binop("=", den, T.lit_number("0")), fb, T.binop("/", num, den))
    tr.review("IFERROR with a non-zero fallback around more than one division (or a division "
              "inside a larger expression) has no map rule — Excel map IFERROR row")


def _iferror(tr, n):
    need(tr, n, 2, 2)
    value, fallback = n.args
    divisions, others = _error_sources(value)
    if others:
        tr.review(f"IFERROR around {', '.join(sorted(others))}: the error cause is not a "
                  "division or a conversion, and no map rule covers it (Excel map IFERROR row, E8)")
    if divisions:
        return iferror_divisions(tr, value, fallback, divisions)
    if any(isinstance(x, X.Call) and x.name in _CONVERSIONS for x in X.walk(value)):
        return T.call("ifnull", tr.expr(value), tr.expr(fallback))
    tr.review("IFERROR around an expression with no division or conversion: no error cause the "
              "map translates (E8)")


LOGIC_HANDLERS = {
    "IF": _if, "IFS": _ifs, "SWITCH": _switch, "AND": _logical("and"), "OR": _logical("or"),
    "NOT": _not, "TRUE": _const(True), "FALSE": _const(False), "IFERROR": _iferror,
    "ISBLANK": _isblank, "ISNUMBER": _isnumber,
}
