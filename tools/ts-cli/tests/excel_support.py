"""Test support for the Excel translator: a ThoughtSpot-AST normaliser and a small Excel
evaluator (Excel → TS → Excel is checked by evaluating both Excel formulas on sample rows).

Not product code: it lives with the tests and supports only what the tests need.
"""
from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal

from ts_cli.excel import nodes as X
from ts_cli.excel.helpers import from_text
from ts_cli.excel.parser import parse


# ---------------------------------------------------------------------------
# ThoughtSpot normaliser
# ---------------------------------------------------------------------------

def _norm(node):
    if isinstance(node, list):
        return [_norm(n) for n in node]
    if not isinstance(node, dict):
        return node
    kind = node.get("node")
    if kind == "col":
        return {"node": "ref", "name": node["column"]}
    if kind == "lit" and node["kind"] == "number":
        return {"node": "lit", "kind": "number", "value": str(Decimal(node["value"]).normalize())}
    if kind == "unop" and node["op"] == "-":
        inner = _norm(node["operand"])
        if inner.get("node") == "lit" and inner["kind"] == "number":
            return {"node": "lit", "kind": "number",
                    "value": str((-Decimal(inner["value"])).normalize())}
        return {"node": "unop", "op": "-", "operand": inner}
    out = {k: _norm(v) for k, v in node.items()}
    if kind == "call" and node["fn"] == "concat":
        args = []
        for a in out["args"]:
            args.extend(a["args"] if a.get("node") == "call" and a["fn"] == "concat" else [a])
        out["args"] = args
    return out


def normalise(ts_text: str) -> dict:
    """A ThoughtSpot formula as a comparable AST: reference spelling (``[T::c]`` = ``[c]``),
    redundant parentheses, whitespace, number spelling and nested ``concat`` normalised."""
    return _norm(from_text(ts_text))


# ---------------------------------------------------------------------------
# Excel evaluator (row context; a column reference yields the whole column)
# ---------------------------------------------------------------------------

class ExcelError(Exception):
    pass


def _num(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dt.date):
        return float((v - dt.date(1899, 12, 30)).days)
    raise ExcelError("#VALUE!")


def _text(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else repr(v)
    return str(v)


def _eq(a, b):
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()
    if isinstance(a, str) or isinstance(b, str):
        return False
    return _num(a) == _num(b)


def _cmp(op, a, b):
    if op in ("=", "<>"):
        r = _eq(a, b)
        return r if op == "=" else not r
    if isinstance(a, str) and isinstance(b, str):
        a, b = a.lower(), b.lower()
    else:
        a, b = _num(a), _num(b)
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def _roundup(x, d):
    f = 10 ** d
    return math.ceil(x * f - 1e-12) / f if x >= 0 else math.floor(x * f + 1e-12) / f


class Evaluator:
    def __init__(self, row: dict, table: list, today: dt.date):
        self.row, self.table, self.today = row, table, today

    def ev(self, node):
        method = getattr(self, "_" + type(node).__name__)
        return method(node)

    def _Num(self, n):
        return float(n.text)

    def _Str(self, n):
        return n.value

    def _Bool(self, n):
        return n.value

    def _Ref(self, n):
        if n.grain == "column":
            return [r[n.column] for r in self.table]
        return self.row[n.column]

    def _Unary(self, n):
        v = _num(self.ev(n.operand))
        return -v if n.op == "-" else v

    def _Binary(self, n):
        a, b = self.ev(n.left), self.ev(n.right)
        if isinstance(a, list) or isinstance(b, list):
            return self._elementwise(n.op, a, b)
        return self._scalar(n.op, a, b)

    def _elementwise(self, op, a, b):
        size = len(a) if isinstance(a, list) else len(b)
        a = a if isinstance(a, list) else [a] * size
        b = b if isinstance(b, list) else [b] * size
        out = []
        for x, y in zip(a, b):
            try:
                out.append(self._scalar(op, x, y))
            except ExcelError as exc:
                out.append(exc)
        return out

    def _scalar(self, op, a, b):
        if op == "&":
            return _text(a) + _text(b)
        if op in ("=", "<>", "<", "<=", ">", ">="):
            return _cmp(op, a, b)
        a, b = _num(a), _num(b)
        if op == "/":
            if b == 0:
                raise ExcelError("#DIV/0!")
            return a / b
        ops = {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "^": lambda: a ** b}
        return ops[op]()

    def _Call(self, n):
        fn = getattr(self, "f_" + n.name.replace(".", "_"), None)
        if fn is None:
            raise NotImplementedError(n.name)
        return fn(n.args)

    # functions -------------------------------------------------------------------
    def f_IF(self, args):
        cond = self.ev(args[0])
        if isinstance(cond, list):
            then = self.ev(args[1])
            other = self.ev(args[2]) if len(args) > 2 else False
            return [(then[i] if isinstance(then, list) else then) if c and not isinstance(
                c, ExcelError) else (other[i] if isinstance(other, list) else other)
                for i, c in enumerate(cond)]
        if _num(cond):
            return self.ev(args[1])
        return self.ev(args[2]) if len(args) > 2 else False

    def f_IFERROR(self, args):
        try:
            return self.ev(args[0])
        except ExcelError:
            return self.ev(args[1])

    def f_AND(self, args):
        return all(_num(self.ev(a)) for a in args)

    def f_OR(self, args):
        return any(_num(self.ev(a)) for a in args)

    def f_NOT(self, args):
        return not _num(self.ev(args[0]))

    def f_SEARCH(self, args):
        find, within = _text(self.ev(args[0])).lower(), _text(self.ev(args[1])).lower()
        pos = within.find(find)
        if pos < 0:
            raise ExcelError("#VALUE!")
        return float(pos + 1)

    def f_ISNUMBER(self, args):
        try:
            v = self.ev(args[0])
        except ExcelError:
            return False
        return isinstance(v, float) and not isinstance(v, bool)

    def _values(self, args):
        out = []
        for a in args:
            v = self.ev(a)
            for x in (v if isinstance(v, list) else [v]):
                if isinstance(x, ExcelError):
                    raise x
                out.append(x)
        return out

    def f_SUM(self, args):
        return float(sum(_num(v) for v in self._values(args)))

    def f_MAX(self, args):
        return max(_num(v) for v in self._values(args))

    def f_MIN(self, args):
        return min(_num(v) for v in self._values(args))

    def f_ROUNDUP(self, args):
        return _roundup(_num(self.ev(args[0])), int(_num(self.ev(args[1]))))

    def f_ROUND(self, args):
        d = int(_num(self.ev(args[1])))
        x = _num(self.ev(args[0]))
        return float(Decimal(str(x)).quantize(Decimal(1).scaleb(-d), rounding="ROUND_HALF_UP"))

    def f_TODAY(self, args):
        return self.today

    def _date(self, a):
        v = self.ev(a)
        if not isinstance(v, dt.date):
            raise ExcelError("#VALUE!")
        return v

    def f_MONTH(self, args):
        return float(self._date(args[0]).month)

    def f_YEAR(self, args):
        return float(self._date(args[0]).year)

    def f_DAY(self, args):
        return float(self._date(args[0]).day)


def evaluate(formula: str, row: dict, table: list, today: dt.date):
    """Value of an Excel formula on ``row`` (``"#ERR"`` for an error value)."""
    try:
        v = Evaluator(row, table, today).ev(parse(formula))
    except ExcelError:
        return "#ERR"
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, 9)
    return v
