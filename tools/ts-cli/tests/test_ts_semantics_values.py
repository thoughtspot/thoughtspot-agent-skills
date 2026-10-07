"""Translations checked BY VALUE against a Python model of ThoughtSpot's own reading (BL-364,
BL-365). There is no Tableau or Power BI oracle, so this model stands in for the cluster; each
rule in it is a live observation (se-thoughtspot 2026-10-07, probe record §7):

* trigonometry is in radians (`sin ( 30 )` = SIN(30) = -0.988);
* `/` takes the operand immediately before it: `a * b / c` is `a * ( b / c )`, `a / b / c` and
  `a / b * c` are left to right;
* a division of two integer literals is fixed-point at scale 6, rounded half up (`[n] * 4 / 3`
  = 3.999999 for n = 3);
* in a single-quoted literal a doubled quote is TWO quotes and `\\x` is `x`; in a double-quoted
  literal `\\x` is `x`.

Each case computes the source formula's value in Python by the source's own rules and compares
it with the model's value of the translation, on several rows. The model also reproduces the
pre-fix outputs' wrong values (`test_model_reproduces_the_live_wrong_answers`), which is what
makes it evidence rather than a restatement of the fix.
"""
from __future__ import annotations

import json
import math
from decimal import ROUND_HALF_UP, Decimal

import pytest

from ts_cli.formula_text import _ts_scan, ts_literal_token_text
from ts_cli.formula_translate.context import ColumnContext, parse_columns_json
from ts_cli.formula_translate.engine import translate


class _Fixed:
    """A number ThoughtSpot sends to Snowflake as an exact NUMBER (an integer literal)."""

    def __init__(self, v):
        self.v = Decimal(v)


def _num(x):
    return float(x.v) if isinstance(x, _Fixed) else x


class TSModel:
    """A tiny evaluator for the ThoughtSpot formula subset the cases emit."""

    def __init__(self, text: str, row: dict):
        self.toks = [t for t in _ts_scan(text) if t[0] not in ("ws", "comment")]
        self.i = 0
        self.row = row

    def peek(self):
        return self.toks[self.i][:2] if self.i < len(self.toks) else (None, None)

    def take(self, text=None):
        k, t = self.peek()
        if text is not None and t != text:
            raise AssertionError(f"expected {text!r}, got {t!r} at {self.i}")
        self.i += 1
        return k, t

    def value(self):
        v = self.cond()
        assert self.i == len(self.toks), self.toks[self.i:]
        return v

    def cond(self):
        if self.peek() == ("word", "if"):
            self.take()
            self.take("(")
            c = self.cond()
            self.take(")")
            self.take("then")
            a = self.cond()
            self.take("else")
            b = self.cond()
            return a if c else b
        left = self.add()
        k, t = self.peek()
        if t in ("=", "!="):
            self.take()
            right = self.add()
            eq = left is not None and right is not None and \
                str(_num(left)).lower() == str(_num(right)).lower()
            return eq if t == "=" else not eq
        return left

    def add(self):
        v = self.mul()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            r = self.mul()
            v = _num(v) + _num(r) if op == "+" else _num(v) - _num(r)
        return v

    def mul(self):  # `*` binds looser than `/`: a * b / c = a * ( b / c )
        v = self.div()
        while self.peek()[1] == "*":
            self.take()
            r = self.div()
            v = _Fixed(v.v * r.v) if isinstance(v, _Fixed) and isinstance(r, _Fixed) \
                else _num(v) * _num(r)
        return v

    def div(self):
        v = self.unary()
        while self.peek()[1] == "/":
            self.take()
            r = self.unary()
            if isinstance(v, _Fixed) and isinstance(r, _Fixed):
                v = _Fixed((v.v / r.v).quantize(Decimal("0.000001"), ROUND_HALF_UP))
            else:
                v = _num(v) / _num(r)
        return v

    def unary(self):
        if self.peek()[1] == "-":
            self.take()
            x = self.unary()
            return _Fixed(-x.v) if isinstance(x, _Fixed) else -x
        return self.primary()

    def primary(self):
        k, t = self.take()
        if t == "(":
            v = self.cond()
            self.take(")")
            return v
        if k == "num":
            return _Fixed(t) if "." not in t else float(t)
        if k in ("sq", "dq"):
            return ts_literal_token_text(t)
        if k == "ref":
            return self.row[t[1:-1].split("::")[-1]]
        if k == "word":
            self.take("(")
            args = []
            if self.peek()[1] != ")":
                args.append(self.cond())
                while self.peek()[1] == ",":
                    self.take()
                    args.append(self.cond())
            self.take(")")
            return self.call(t, args)
        raise AssertionError(f"unexpected token {t!r}")

    @staticmethod
    def call(fn, args):
        if fn in ("sin", "cos", "tan", "asin", "acos", "atan"):
            return getattr(math, fn)(_num(args[0]))
        if fn == "concat":
            return "".join(args)
        if fn.startswith("sql_") and args[0] == "PI()":
            return math.pi
        if fn == "sql_double_op" and args[0] == "ATAN2({0}, {1})":
            return math.atan2(_num(args[1]), _num(args[2]))
        raise AssertionError(f"model has no {fn}")


def ts_value(text: str, row: dict):
    return _num(TSModel(text, row).value())


ROWS = [{"X": 0.5, "Y": 3.0, "N": 3, "S": "O'Brien"},
        {"X": -1.25, "Y": 7.0, "N": 1000000, "S": "it's"},
        {"X": 2.0, "Y": 0.1, "N": 7, "S": "x"}]

_COLS = json.dumps([{"source": c, "table": "T", "column": c.upper(), "data_type": t,
                     "column_type": k}
                    for c, t, k in [("x", "DOUBLE", "MEASURE"), ("y", "DOUBLE", "MEASURE"),
                                    ("n", "INT64", "MEASURE"), ("s", "VARCHAR", "ATTRIBUTE")]])


def _tr(src, dialect):
    r = translate(src, dialect, ColumnContext(parse_columns_json(_COLS), level=1))
    assert r["formula"] is not None, r["notes"]
    return r["formula"]


def _close(a, b):
    if isinstance(b, (bool, str)) or isinstance(a, (bool, str)):
        return a == b
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)


# (Tableau source, Power BI source, the source's value in Python)
CASES = [
    ("SIN([x])", None, lambda r: math.sin(r["X"])),  # Power BI declines trigonometry
    ("COS([x])", None, lambda r: math.cos(r["X"])),
    ("TAN([x])", None, lambda r: math.tan(r["X"])),
    ("ASIN([x] / 4)", None, lambda r: math.asin(r["X"] / 4)),
    ("ACOS([x] / 4)", None, lambda r: math.acos(r["X"] / 4)),
    ("ATAN([x])", None, lambda r: math.atan(r["X"])),
    ("COT([x])", None, lambda r: 1 / math.tan(r["X"])),
    ("ATAN2([y], [x])", None, lambda r: math.atan2(r["Y"], r["X"])),
    ("DEGREES([x])", None, lambda r: math.degrees(r["X"])),
    ("RADIANS([y])", None, lambda r: math.radians(r["Y"])),
    ("PI() * [x]", None, lambda r: math.pi * r["X"]),
    ("[n] * 4 / 3", "[n] * 4 / 3", lambda r: r["N"] * 4 / 3),
    ("[n] * 100 / 7", "[n] * 100 / 7", lambda r: r["N"] * 100 / 7),
    ("[x] * [y] / 3", "[x] * [y] / 3", lambda r: r["X"] * r["Y"] / 3),
    ("[n] / 3 * 7", "[n] / 3 * 7", lambda r: r["N"] / 3 * 7),
    ("[n] - 3 + 7", "[n] - 3 + 7", lambda r: r["N"] - 3 + 7),
    ("IF [s] = 'O''Brien' THEN 1 ELSE 0 END", 'IF([s] = "O\'Brien", 1, 0)',
     lambda r: 1 if r["S"].lower() == "o'brien" else 0),
    ("IF [s] = \"it's\" THEN 1 ELSE 0 END", 'IF([s] = "it\'s", 1, 0)',
     lambda r: 1 if r["S"].lower() == "it's" else 0),
    ("[s] + 'a''b''c'", None, lambda r: r["S"] + "a'b'c"),
    ("[s] + \"it's here\"", None, lambda r: r["S"] + "it's here"),
]


@pytest.mark.parametrize("src,_dax,want", CASES, ids=[c[0] for c in CASES])
def test_tableau_by_value(src, _dax, want):
    out = _tr(src, "tableau")
    for row in ROWS:
        assert _close(ts_value(out, row), want(row)), (out, row)


@pytest.mark.parametrize("_src,dax,want", [c for c in CASES if c[1]],
                         ids=[c[1] for c in CASES if c[1]])
def test_powerbi_by_value(_src, dax, want):
    out = _tr(dax, "dax")
    for row in ROWS:
        assert _close(ts_value(out, row), want(row)), (out, row)


@pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
@pytest.mark.parametrize("src,want", [
    ("SIN(x)", lambda r: math.sin(r["X"])), ("ASIN(x / 4)", lambda r: math.asin(r["X"] / 4)),
    ("ATAN2(y, x)", lambda r: math.atan2(r["Y"], r["X"])),
    ("DEGREES(x)", lambda r: math.degrees(r["X"])), ("RADIANS(y)", lambda r: math.radians(r["Y"])),
    ("COT(x)", lambda r: 1 / math.tan(r["X"])), ("n * 4 / 3", lambda r: r["N"] * 4 / 3),
])
def test_sql_by_value(dialect, src, want):
    out = _tr(src, dialect)
    for row in ROWS:
        assert _close(ts_value(out, row), want(row)), (out, row)


def test_model_reproduces_the_live_wrong_answers():
    """The pre-fix outputs, through the model, give the wrong values seen live."""
    row = {"N": 3, "X": 30.0, "S": "it's"}
    assert ts_value("[T::N] * 4 / 3", row) == pytest.approx(3.999999, abs=1e-12)
    # the old Tableau SIN, sin ( x * 180 / 3.14159265358979 ), is not sin(x)
    assert not _close(ts_value("sin ( [T::X] * 180 / 3.14159265358979 )", row), math.sin(30.0))
    assert ts_value("'it''s'", row) == "it''s"
    assert ts_value("[T::S] = 'it''s'", row) is False
