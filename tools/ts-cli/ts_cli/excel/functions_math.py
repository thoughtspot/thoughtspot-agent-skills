"""Math handlers beyond rounding (Excel map, Math and trigonometry): logarithms,
trigonometry, the hyperbolic family, angle conversion and factorial.

Live facts these rest on (probe record §7, se-thoughtspot, 2026-10-07):
- ThoughtSpot's ``sin`` / ``cos`` / ``tan`` take **radians** and ``asin`` / ``acos`` / ``atan``
  return radians: ``sin ( 30 )`` compiles to ``SIN(30)`` and returns −0.988, ``asin ( 0.5 )``
  returns 0.5236. Excel's trigonometry is in radians too, so the call is the same — the map's
  former E16 rule (multiply by 180 / π) was wrong and gave a wrong answer for every input.
- The hyperbolic functions and ``DEGREES`` / ``RADIANS`` are Snowflake pass-throughs
  (``SINH``, ``ATANH``, ``DEGREES``, … returned Python's ``math`` values to the last digit).
  The ``exp`` / ``ln`` compositions in the map are exact algebra but not exact arithmetic:
  ``( exp ( x ) - exp ( - x ) ) / 2`` cancels for a small ``x`` and ``exp ( 2 * x )``
  overflows for a large one, and ``x * 180 / 3.14159…`` over literals is fixed-point decimal
  arithmetic in the warehouse (BL-351).
- ``FACTORIAL(FLOOR(x))`` as ``sql_double_op`` returns 25! as 1.5511210043330986E+25; as
  ``sql_int_op`` it would overflow INT64 from 21!.

The reciprocal family (BL-372): ``COT`` / ``SEC`` / ``CSC`` are ``1 /`` the native function, the
form every other translator emits for ``COT`` (BL-364); ``COTH`` / ``SECH`` / ``CSCH`` are ``1 /``
the Snowflake hyperbolic pass-through, for the precision reason above; ``ACOT`` is the map's
``π / 2 − atan ( x )``; ``ACOTH`` is ``ATANH(1 / x)`` in Snowflake, the argument cast to a
double so an integer column is not divided at scale 6 (BL-365). ThoughtSpot's ``/`` is
NULL-safe, so at a zero divisor (``COT(0)``, ``CSC(0)``, ``COTH(0)``, ``CSCH(0)``) the result is
NULL where Excel returns ``#DIV/0!`` (BL-370): a literal zero is NEEDS_REVIEW, a column carries
a non-downgrading trap (BL-370's posture; for ``COT`` the engine's own BL-370 trap fires).
"""
from __future__ import annotations

from ts_cli.excel import nodes as X
from ts_cli.excel import tsast as T
from ts_cli.excel.helpers import need, template

FACT_TRAP = ("FACT of a column: Snowflake FACTORIAL accepts 0 to 33 and FAILS THE WHOLE QUERY "
             "for a negative number or one above 33, where Excel returns #NUM! in one cell "
             "(negative) or computes up to 170!")


DOMAIN_TRAP = ("{name} of a value outside {what}: Excel returns #NUM! (or #DIV/0!) in that "
               "cell; the warehouse returns NaN, the text 'Infinity', NULL or fails the query "
               "(fidelity M1 coverage run)")


def _domain(tr, name: str, node: dict, ok, what: str) -> None:
    """A literal outside the function's domain is NEEDS_REVIEW (Excel's error has no value);
    a non-literal gets a downgrading trap."""
    value = T.number_value(node)
    if value is None:
        tr.trap(DOMAIN_TRAP.format(name=name, what=what), downgrade=True)
    elif not ok(value):
        tr.review(f"{name} of {value}: outside {what}, an error in Excel")


def _log(tr, n):
    """``LOG(x, [base])``: Excel's default base is 10."""
    need(tr, n, 1, 2)
    x = tr.num(n.args[0])
    _domain(tr, "LOG", x, lambda v: v > 0, "x > 0")
    if len(n.args) == 1 or isinstance(n.args[1], X.Missing):
        return T.call("log10", x)
    base = tr.num(n.args[1])
    _domain(tr, "LOG", base, lambda v: v > 0 and v != 1, "a base > 0 and not 1")
    value = T.number_value(base)
    if value == 10:
        return T.call("log10", x)
    if value == 2:
        return T.call("log2", x)
    return T.binop("/", T.call("ln", x), T.call("ln", base))


# name -> (accepts, the domain in words) for the functions with a restricted domain
_DOMAINS = {"ASIN": (lambda v: -1 <= v <= 1, "-1 to 1"), "ACOS": (lambda v: -1 <= v <= 1, "-1 to 1"),
            "ACOSH": (lambda v: v >= 1, "x >= 1"), "ATANH": (lambda v: -1 < v < 1, "-1 < x < 1")}


def _native(fn: str):
    """Excel and ThoughtSpot trigonometry are both in radians (probe record §7)."""
    def handler(tr, n):
        need(tr, n, 1, 1)
        x = tr.num(n.args[0])
        if n.name in _DOMAINS:
            _domain(tr, n.name, x, *_DOMAINS[n.name])
        return T.call(fn, x)
    return handler


def _double_op(sql: str):
    def handler(tr, n):
        need(tr, n, 1, 1)
        x = tr.num(n.args[0])
        if n.name in _DOMAINS:
            _domain(tr, n.name, x, *_DOMAINS[n.name])
        return T.call("sql_double_op", template(sql), x)
    return handler


def _atan2(tr, n):
    """``ATAN2(x, y)`` is SQL ``ATAN2(y, x)``: the operands swap."""
    need(tr, n, 2, 2)
    x, y = tr.num(n.args[0]), tr.num(n.args[1])
    tr.trap("ATAN2(0, 0): Excel returns #DIV/0!, Snowflake ATAN2 returns 0")
    return T.call("sql_double_op", template("ATAN2({0}, {1})"), y, x)


def _pi(tr, n):
    """``PI()`` as the warehouse's double ``PI()``, never a literal: a decimal literal under
    ``/`` is fixed-point at scale 6 (``-1 / 3.141592653589793`` lost seven digits, and
    ``x * 180 / 3.14…`` is read as ``x * ( 180 / 3.14… )`` — live 2026-10-07, probe record §7)."""
    need(tr, n, 0, 0)
    return T.call("sql_double_op", template("PI()"))


def _fact(tr, n):
    """``FACT(x)``: Excel truncates ``x``; FLOOR inside the template does the same for x ≥ 0."""
    need(tr, n, 1, 1)
    x = tr.num(n.args[0])
    value = T.number_value(x)
    if value is not None:
        if value < 0:
            tr.review("FACT of a negative number is #NUM! in Excel")
        if value >= 34:
            tr.review("FACT above 33: Snowflake FACTORIAL fails the query, Excel computes "
                      "up to 170!")
    else:
        tr.trap(FACT_TRAP, downgrade=True)
    return T.call("sql_double_op", template("FACTORIAL(FLOOR({0}))"), x)


RECIPROCAL_ZERO_TRAP = ("{name}(0): Excel returns #DIV/0!; the translation divides by "
                        "{inner} ( 0 ) = 0 and ThoughtSpot's division is NULL-safe, so the "
                        "result is NULL there — BL-370")


def _reciprocal(inner: str, sql: str = "", zero: bool = False):
    """``1 / inner ( x )`` — native ``inner``, or ``1 / sql_double_op ( sql , x )`` when ``sql``
    is given. ``zero``: the divisor is 0 at ``x = 0`` (cot, csc, coth, csch)."""
    def handler(tr, n):
        need(tr, n, 1, 1)
        x = tr.num(n.args[0])
        if zero:
            if T.number_value(x) == 0:
                tr.review(f"{n.name}(0) is #DIV/0! in Excel; ThoughtSpot's NULL-safe division "
                          "would return NULL (BL-370)")
            if n.name != "COT":  # COT: the engine's own BL-370 trap (formula_translate.traps)
                tr.trap(RECIPROCAL_ZERO_TRAP.format(name=n.name, inner=inner.lower()))
        divisor = T.call("sql_double_op", template(sql), x) if sql else T.call(inner.lower(), x)
        return T.binop("/", T.lit_number("1"), divisor)
    return handler


def _acot(tr, n):
    """``ACOT(x)`` = π/2 − atan(x): Excel's principal range (0, π) for every sign of x."""
    need(tr, n, 1, 1)
    x = tr.num(n.args[0])
    half_pi = T.binop("/", T.call("sql_double_op", template("PI()")), T.lit_number("2"))
    return T.binop("-", half_pi, T.call("atan", x))


def _acoth(tr, n):
    """``ACOTH(x)`` = atanh(1 / x), domain |x| > 1; the cast keeps an integer x off scale 6."""
    need(tr, n, 1, 1)
    x = tr.num(n.args[0])
    _domain(tr, "ACOTH", x, lambda v: abs(v) > 1, "|x| > 1")
    return T.call("sql_double_op", template("ATANH(1 / TO_DOUBLE({0}))"), x)


MATH_HANDLERS = {
    "LOG": _log, "PI": _pi, "FACT": _fact, "ATAN2": _atan2,
    "SIN": _native("sin"), "COS": _native("cos"), "TAN": _native("tan"),
    "ASIN": _native("asin"), "ACOS": _native("acos"), "ATAN": _native("atan"),
    "SINH": _double_op("SINH({0})"), "COSH": _double_op("COSH({0})"),
    "TANH": _double_op("TANH({0})"), "ASINH": _double_op("ASINH({0})"),
    "ACOSH": _double_op("ACOSH({0})"), "ATANH": _double_op("ATANH({0})"),
    "DEGREES": _double_op("DEGREES({0})"), "RADIANS": _double_op("RADIANS({0})"),
    "COT": _reciprocal("TAN", zero=True), "SEC": _reciprocal("COS"),
    "CSC": _reciprocal("SIN", zero=True),
    "COTH": _reciprocal("TANH", "TANH({0})", zero=True),
    "SECH": _reciprocal("COSH", "COSH({0})"),
    "CSCH": _reciprocal("SINH", "SINH({0})", zero=True),
    "ACOT": _acot, "ACOTH": _acoth,
}
