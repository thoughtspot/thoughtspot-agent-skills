"""One handler per rule in ``rules.FUNCTION_RULES`` / ``SHEETS_RULES``: Excel call → TS AST.

Each handler follows its map row (cited in the rule table, checked by
``check_mapping_code_sync``). Shared transforms come from ``formula_common`` — the ROUND digit
→ increment conversion and weekday numbering — never re-implemented here (BL-217).
"""
from __future__ import annotations

from ts_cli.excel import nodes as X
from ts_cli.excel import tsast as T
from ts_cli.excel.criteria import criteria_condition
from ts_cli.excel.forward import Translator
from ts_cli.excel.helpers import fold, from_text, is_range, literal_int, need, template
from ts_cli.excel.functions_text import TEXT_HANDLERS
from ts_cli.excel.functions_date import DATE_HANDLERS
from ts_cli.excel.functions_logic import LOGIC_HANDLERS
from ts_cli.excel.functions_math import MATH_HANDLERS
from ts_cli.excel.functions_format import FORMAT_HANDLERS
from ts_cli.excel.functions_sheets import SHEETS_HANDLERS  # noqa: F401  (re-exported)
from ts_cli.formula_common import (
    UntranslatableError, sql_digits_to_ts_increment, ts_round_from_sql_digits,
)


# ---------------------------------------------------------------------------
# Reducers: one range argument aggregates (E5); several cells are row-wise (E7)
# ---------------------------------------------------------------------------

def _reduce(tr: Translator, node: X.Call, agg: str, rowwise=None) -> dict:
    if not node.args:
        tr.review(f"{node.name}() with no arguments")
    if len(node.args) == 1 and is_range(node.args[0]):
        with tr.aggregate():
            return T.call(agg, tr.expr(node.args[0]))
    if any(is_range(a) for a in node.args):
        tr.review(f"{node.name} mixes a range with other arguments — no single-column reading "
                  "(Excel map E5/E7)")
    if rowwise is None:
        tr.review(f"{node.name} over cells of one row has no row-wise ThoughtSpot form")
    return rowwise([tr.expr(a) for a in node.args])


def _fold(op: str):
    return lambda args: fold(op, args)


def _average_rowwise(args: list) -> dict:
    total = _fold("+")(args)
    return total if len(args) == 1 else T.binop("/", total, T.lit_number(str(len(args))))


def _sum(tr, n):
    if len(n.args) > 1:
        tr.trap("SUM over cells of one row is row-wise addition; Excel treats a blank as 0, "
                "+ propagates NULL — wrap nullable columns in ifnull ( x , 0 ) (E7, E10)")
    return _reduce(tr, n, "sum", _fold("+"))


def _max(tr, n):
    return _reduce(tr, n, "max", lambda a: a[0] if len(a) == 1 else T.call("greatest", *a))


def _min(tr, n):
    return _reduce(tr, n, "min", lambda a: a[0] if len(a) == 1 else T.call("least", *a))


def _simple_agg(fn: str):
    return lambda tr, n: _reduce(tr, n, fn)


# ---------------------------------------------------------------------------
# Conditional aggregates (criteria per Excel map E11)
# ---------------------------------------------------------------------------

def _range_col(tr: Translator, node) -> dict:
    if not (isinstance(node, X.Ref) and node.grain == "column"):
        tr.review("a criteria range must be one column (a range or Table[Col] — E5)")
    with tr.aggregate():
        return tr.expr(node)


def _conditions(tr: Translator, pairs: list) -> dict:
    conds = [criteria_condition(tr, _range_col(tr, r), c) for r, c in pairs]
    return _fold("and")(conds)


def _pairs(tr: Translator, args: list) -> list:
    if len(args) % 2:
        tr.review("criteria arguments must come in range / criteria pairs")
    return [(args[i], args[i + 1]) for i in range(0, len(args), 2)]


def _ifs_agg(fn: str, first_is_value: bool = True):
    """SUMIFS / AVERAGEIFS / MAXIFS / MINIFS (value range first)."""
    def handler(tr, n):
        if len(n.args) < 3:
            tr.review(f"{n.name} needs a value range and at least one criteria pair")
        value = _range_col(tr, n.args[0])
        if fn in ("max_if", "min_if"):
            tr.trap(f"{n.name}: Excel returns 0 when no row matches, {fn} returns NULL — wrap "
                    "in ifnull ( … , 0 ) to match (E10)")
        return T.call(fn, _conditions(tr, _pairs(tr, n.args[1:])), value)
    return handler


def _if_agg(fn: str):
    """SUMIF / AVERAGEIF: (range, criteria, [value_range])."""
    def handler(tr, n):
        need(tr, n, 2, 3)
        rng = _range_col(tr, n.args[0])
        value = _range_col(tr, n.args[2]) if len(n.args) == 3 else rng
        return T.call(fn, criteria_condition(tr, rng, n.args[1]), value)
    return handler


def _countif(tr, n):
    need(tr, n, 2, 2)
    rng = _range_col(tr, n.args[0])
    cond = criteria_condition(tr, rng, n.args[1])
    counted = rng
    if isinstance(n.args[1], X.Str) and n.args[1].value in ("", "="):
        counted = T.ref_node(tr.ctx.key_reference())
        tr.note("a blank criterion counts a non-null key column, not the range itself "
                "(count_if counts non-null values of its 2nd argument)")
    return T.call("count_if", cond, counted)


def _countifs(tr, n):
    if len(n.args) < 2:
        tr.review("COUNTIFS needs at least one criteria pair")
    cond = _conditions(tr, _pairs(tr, n.args))
    key = T.ref_node(tr.ctx.key_reference())
    tr.note("COUNTIFS counts rows, so it counts a non-null key column; name the table's key "
            "with --key-column if this is a placeholder")
    return T.call("count_if", cond, key)


# ---------------------------------------------------------------------------
# Rounding (E12 — the increment conversion lives in formula_common)
# ---------------------------------------------------------------------------

def _round(tr, n):
    need(tr, n, 2, 2)
    x = tr.num(n.args[0])
    digits = tr.expr(n.args[1])
    try:
        text = ts_round_from_sql_digits(T.to_text(x), T.to_text(digits),
                                        aggregated=T.is_aggregated(x))
    except UntranslatableError as exc:
        tr.review(str(exc))
    if text.startswith("sql_double_op"):
        tr.note("ROUND with a non-literal digit count: passed through to the warehouse")
        return T.call("sql_double_op", template("ROUND({0}, {1})"), x, digits)
    return from_text(text)


def _quarter_idiom(node):
    """``ROUNDUP(MONTH(d)/3, 0)`` → the date argument, else None."""
    x, d = node.args
    if literal_int(d) != 0 or not (isinstance(x, X.Binary) and x.op == "/"):
        return None
    if isinstance(x.left, X.Call) and x.left.name == "MONTH" and literal_int(x.right) == 3:
        return x.left.args[0] if len(x.left.args) == 1 else None
    return None


SNAP = "0.000000001"
SNAP_NOTE = ("a DOUBLE scaled for rounding is snapped to 1e-9 first — round ( x * F , "
             "0.000000001 ) — because binary representation error would otherwise push an "
             "exact step over the edge (1.1 * 100 is 110.00000000000001, so ceil gave 1.11 "
             "where Excel, which works to 15 significant digits, gives 1.1). A value with a "
             "genuine difference beyond the 9th decimal of the scaled number is snapped too")


def _snap(tr, x: dict, scaled: dict) -> dict:
    """``round ( scaled , 1e-9 )`` when ``x`` may be a DOUBLE (a DOUBLE or an unknown column
    type); exact literals and integer or DECIMAL columns are left alone. Live 2026-10-07:
    the snapped forms return Excel's 1.1, 0.29 and CEILING's 1.1 where the raw ones gave 1.11,
    0.28 and 1.2 (probe record §7)."""
    if not T.has_column(x) or tr.fine_type(x) not in ("double", None):
        return scaled
    tr.note(SNAP_NOTE)
    return T.call("round", scaled, T.lit_number(SNAP))


def _scaled(tr, x: dict, digits: int, inner_fn: str) -> dict:
    """``fn ( x * F ) * I`` (digits > 0, ``I`` = 1 / ``F``), ``fn ( x )`` (0),
    ``fn ( x / F ) * F`` (< 0), the scaled value snapped for a DOUBLE (``_snap``).

    Multiplying by the increment, not dividing by the factor (BL-348): ``ceil ( … ) / F``
    divides two integers, and Snowflake keeps a division's result at scale 6, so more than
    6 digits came back cut to 6 (live, se-thoughtspot 2026-10-07: ``/ to_double ( F )`` and
    ``to_double ( ceil ( … ) ) / F`` are cut the same way; ``* 0.00000000001`` keeps 11)."""
    if abs(digits) > 15:
        tr.review(f"rounding to {digits} digits: beyond a double's 15 significant digits, and "
                  "the 10^n factor overflows ceil / floor's INT64 result")
    if digits == 0:
        return T.call(inner_fn, _snap(tr, x, x))
    factor = T.lit_number(sql_digits_to_ts_increment(str(-abs(digits))))
    if digits > 0:
        increment = T.lit_number(sql_digits_to_ts_increment(str(digits)))
        scaled = _snap(tr, x, T.binop("*", x, factor))
        return T.binop("*", T.call(inner_fn, scaled), increment)
    return T.binop("*", T.call(inner_fn, _snap(tr, x, T.binop("/", x, factor))), factor)


def _round_dir(away: bool):
    def handler(tr, n):
        need(tr, n, 2, 2)
        if away:
            date = _quarter_idiom(n)
            if date is not None:
                tr.trap("ROUNDUP(MONTH(d)/3, 0) is the calendar quarter → quarter_number, which "
                        "follows the Model's calendar: a fiscal calendar shifts it")
                return T.call("quarter_number", tr.expr(date))
        digits = literal_int(n.args[1])
        if digits is None:
            tr.review(f"{n.name} with a non-literal digit count has no native form")
        x = tr.num(n.args[0])
        pos, neg = ("ceil", "floor") if away else ("floor", "ceil")
        cond = T.binop(">=", x, T.lit_number("0"))
        return T.ifelse(cond, _scaled(tr, x, digits, pos), _scaled(tr, x, digits, neg))
    return handler


def _mround(tr, n):
    need(tr, n, 2, 2)
    x, m = tr.num(n.args[0]), tr.num(n.args[1])
    v = T.number_value(m)
    tr.trap("MROUND: Excel returns #NUM! when the number and multiple differ in sign; "
            "round ( x , abs ( m ) ) returns a value")
    return T.call("round", x, m if v is not None and v > 0 else T.call("abs", m))


def _int(tr, n):
    need(tr, n, 1, 1)
    return T.call("floor", tr.num(n.args[0]))


def _multiple(tr, fn: str, x: dict, sig: dict) -> dict:
    """``fn ( x / s ) * s``, the quotient snapped for a DOUBLE (``_snap``)."""
    return T.binop("*", T.call(fn, _snap(tr, x, T.binop("/", x, sig))), sig)


def _zero_guard(sig: dict, form: dict) -> dict:
    """Excel ``CEILING`` / ``CEILING.MATH`` with a zero significance return 0; ``x / 0`` is
    NULL in ThoughtSpot (BL-347). A non-zero literal needs no guard."""
    value = T.number_value(sig)
    if value is not None:
        return T.lit_number("0") if value == 0 else form
    return T.ifelse(T.binop("=", sig, T.lit_number("0")), T.lit_number("0"), form)


def _ceiling_floor(fn: str):
    """``CEILING`` / ``FLOOR (x, s)`` → ``fn ( x / s ) * s``. The signed division gives
    Excel's rounding for every sign pair Excel accepts (a negative number with a negative
    significance rounds away from zero, with a positive one toward zero); a positive number
    with a negative significance is ``#NUM!`` in Excel and a number here. ``CEILING`` of a zero
    significance is 0 (guarded); ``FLOOR``'s is ``#DIV/0!``, and NULL here."""
    def handler(tr, n):
        need(tr, n, 1, 2)
        x = tr.num(n.args[0])
        if len(n.args) == 1:
            return T.call(fn, _snap(tr, x, x))
        sig = tr.num(n.args[1])
        form = _multiple(tr, fn, x, sig)
        return _zero_guard(sig, form) if fn == "ceil" else form
    return handler


def _math_family(primary: str, negative: str = "", modes: bool = False):
    """``CEILING.MATH`` / ``FLOOR.MATH(x, [s], [mode])`` and ``CEILING.PRECISE`` /
    ``FLOOR.PRECISE`` / ``ISO.CEILING(x, [s])`` (BL-346). Excel ignores the significance's
    sign: ``fn ( x / |s| ) * |s|``, ``fn`` = ``primary``. With a non-zero ``mode`` a negative
    number rounds the other way (``negative``): CEILING.MATH away from zero, FLOOR.MATH toward
    it. A zero significance returns 0 (BL-347). The default significance is 1."""
    def handler(tr, n):
        need(tr, n, 1, 3 if modes else 2)
        x = tr.num(n.args[0])
        given = len(n.args) > 1 and not isinstance(n.args[1], X.Missing)
        sig = tr.num(n.args[1]) if given else T.lit_number("1")
        value = T.number_value(sig)
        step = T.lit_number(str(abs(value))) if value is not None else T.call("abs", sig)
        mode = n.args[2] if len(n.args) == 3 and not isinstance(n.args[2], X.Missing) else None
        other = False
        if mode is not None:
            m = T.number_value(tr.num(mode))
            if m is None:
                tr.review(f"{n.name} with a non-literal mode has no rule: the mode decides the "
                          "rounding direction of negative numbers")
            other = m != 0

        def form(fn):
            return (T.call(fn, _snap(tr, x, x)) if T.is_lit(step, "number", "1")
                    else _multiple(tr, fn, x, step))
        out = form(primary)
        if other:
            out = T.ifelse(T.binop("<", x, T.lit_number("0")), form(negative), out)
        return _zero_guard(sig, out) if given else out
    return handler


def _trunc(tr, n):
    """``TRUNC(x, [digits])`` is ``ROUNDDOWN`` with digits defaulting to 0 (toward zero)."""
    need(tr, n, 1, 2)
    digits = n.args[1] if len(n.args) == 2 and not isinstance(n.args[1], X.Missing) \
        else X.Num("0")
    return _round_dir(False)(tr, X.Call(n.name, [n.args[0], digits]))


def _even_odd(odd: bool):
    """``EVEN`` / ``ODD``: away from zero to the next even / odd integer (map rows)."""
    def handler(tr, n):
        need(tr, n, 1, 1)
        x = tr.num(n.args[0])
        two, one, zero = T.lit_number("2"), T.lit_number("1"), T.lit_number("0")
        if not odd:
            pos = T.binop("*", T.call("ceil", T.binop("/", x, two)), two)
            neg = T.binop("*", T.call("floor", T.binop("/", x, two)), two)
        else:
            pos = T.binop("-", T.binop("*", T.call("ceil", T.binop(
                "/", T.binop("+", x, one), two)), two), one)
            neg = T.binop("+", T.binop("*", T.call("floor", T.binop(
                "/", T.binop("-", x, one), two)), two), one)
        return T.ifelse(T.binop(">=", x, zero), pos, neg)
    return handler


def _quotient(tr, n):
    """``QUOTIENT(x, y)``: the quotient truncated toward zero. A zero divisor is ``#DIV/0!``
    in Excel; ThoughtSpot's ``/`` returns NULL (probe record §7)."""
    need(tr, n, 2, 2)
    x, y = tr.num(n.args[0]), tr.num(n.args[1])
    q = T.binop("/", x, y)
    tr.note("QUOTIENT with a zero divisor: Excel shows #DIV/0!, ThoughtSpot's / returns NULL")
    return T.ifelse(T.binop(">=", q, T.lit_number("0")), T.call("floor", q), T.call("ceil", q))


def _mod(tr, n):
    need(tr, n, 2, 2)
    x, y = tr.num(n.args[0]), tr.num(n.args[1])
    return T.binop("-", x, T.binop("*", y, T.call("floor", T.binop("/", x, y))))


def _sign(tr, n):
    need(tr, n, 1, 1)
    x = tr.num(n.args[0])
    zero = T.lit_number("0")
    return T.ifelse(T.binop(">", x, zero), T.lit_number("1"),
                    T.ifelse(T.binop("<", x, zero), T.unop("-", T.lit_number("1")), zero))


def _unary_fn(fn: str):
    def handler(tr, n):
        need(tr, n, 1, 1)
        return T.call(fn, tr.num(n.args[0]))
    return handler


def _power(tr, n):
    need(tr, n, 2, 2)
    return T.call("pow", tr.num(n.args[0]), tr.num(n.args[1]))


HANDLERS = {
    "ABS": _unary_fn("abs"), "SQRT": _unary_fn("sqrt"), "EXP": _unary_fn("exp"),
    "LN": _unary_fn("ln"), "LOG10": _unary_fn("log10"), "INT": _int,
    "CEILING": _ceiling_floor("ceil"), "FLOOR": _ceiling_floor("floor"), "MOD": _mod,
    "CEILING.MATH": _math_family("ceil", "floor", modes=True),
    "FLOOR.MATH": _math_family("floor", "ceil", modes=True),
    "CEILING.PRECISE": _math_family("ceil"), "ISO.CEILING": _math_family("ceil"),
    "FLOOR.PRECISE": _math_family("floor"), "TRUNC": _trunc,
    "EVEN": _even_odd(False), "ODD": _even_odd(True), "QUOTIENT": _quotient,
    "MROUND": _mround, "POWER": _power, "ROUND": _round,
    "ROUNDUP": _round_dir(True), "ROUNDDOWN": _round_dir(False), "SIGN": _sign,
    "SUM": _sum, "SUMIF": _if_agg("sum_if"), "SUMIFS": _ifs_agg("sum_if"),
    "AVERAGE": lambda tr, n: _reduce(tr, n, "average", _average_rowwise),
    "AVERAGEIF": _if_agg("average_if"), "AVERAGEIFS": _ifs_agg("average_if"),
    "COUNT": _simple_agg("count"), "COUNTA": _simple_agg("count"),
    "COUNTIF": _countif, "COUNTIFS": _countifs,
    "MAX": _max, "MIN": _min, "MAXIFS": _ifs_agg("max_if"), "MINIFS": _ifs_agg("min_if"),
    "MEDIAN": _simple_agg("median"), "STDEV.S": _simple_agg("stddev"),
    "VAR.S": _simple_agg("variance"),
    **TEXT_HANDLERS, **DATE_HANDLERS, **LOGIC_HANDLERS, **MATH_HANDLERS,
    **FORMAT_HANDLERS,
}

