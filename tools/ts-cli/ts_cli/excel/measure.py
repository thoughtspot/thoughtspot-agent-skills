"""The intended-role pass over a row-level translation (``--role measure | attribute``).

A spreadsheet formula over ``[@Col]`` is a per-row value. When the user intends a MEASURE, the
translation must be built at the right grain, because a MEASURE is re-aggregated at whatever
grain a search asks for:

- **already aggregated** (``SUM(Table[a])``) — maps directly;
- **additive** (``a - b``, ``a * 12``) — the sum of each component, ``sum ( a ) - sum ( b )``;
  per-row values and the column sums agree once totalled;
- **a ratio** (``a / b``, an IFERROR-guarded ``safe_divide``) — a **ratio of totals**,
  ``safe_divide ( sum ( num ) , sum ( den ) )``; never the sum of per-row ratios, which is a
  different (and usually meaningless) number;
- **a numeric flag** (``IF(c, 1, 0)``) — stays row-level; the column's aggregation (SUM)
  totals it;
- **another row-level expression** (``MAX(0, a - b)``) — summed per row, ``sum ( … )``;
- **text** — cannot be a measure: kept row-level (an ATTRIBUTE) with a trap pointing at
  ``group_aggregate`` at a declared grain.

ATTRIBUTE keeps the row-level form.
"""
from __future__ import annotations

from typing import Optional

from ts_cli.excel import tsast as T

RATIO_TRAP = ("ratio of totals: a MEASURE is re-aggregated at the search's grain, so the "
              "translation divides the totals — safe_divide ( sum ( numerator ) , "
              "sum ( denominator ) ) — which matches Excel's per-row ratio only where one row "
              "is the reporting grain; the Excel aggregate equivalent is "
              "SUM(Table[num]) / SUM(Table[den]). Never the sum of per-row ratios")
ADDITIVE_NOTE = ("additive: the per-row Excel values and the sum of each column agree once "
                 "totalled")
ROWSUM_NOTE = ("{what}: summed per row, sum ( … ) — the total of the Excel column")
FLAG_NOTE = ("a numeric flag stays row-level; with role MEASURE the column's aggregation (SUM) "
             "totals it (a count of the rows where it holds)")
TEXT_TRAP = ("returns text, so it cannot be a MEASURE: kept row-level (an ATTRIBUTE, evaluated "
             "per row as in Excel). For a label computed on totals, write it over the "
             "aggregates at a declared grain — e.g. group_aggregate ( sum ( [T::x] ) , "
             "{ [T::Account] } , query_filters ( ) )")
ZERO_TOTAL_TRAP = ("a zero total: safe_divide returns 0 where Excel's per-row division showed "
                   "#DIV/0!")


class _Lifter:
    def __init__(self, tr):
        self.tr = tr

    def lift(self, node: dict) -> dict:
        kind = node.get("node")
        if not T.has_column(node):
            return node
        if kind in ("col", "ref"):
            return T.call("sum", node)
        if kind == "unop" and node["op"] == "-":
            return T.unop("-", self.lift(node["operand"]))
        if kind == "binop" and node["op"] in ("+", "-"):
            self.tr.note(ADDITIVE_NOTE)
            return T.binop(node["op"], self.lift(node["left"]), self.lift(node["right"]))
        if kind == "binop" and node["op"] == "*":
            return self._product(node)
        if kind == "binop" and node["op"] == "/":
            self.tr.trap(ZERO_TOTAL_TRAP)
            return self._ratio(node["left"], node["right"])
        if kind == "call" and node["fn"] == "safe_divide":
            return self._ratio(*node["args"])
        self.tr.note(ROWSUM_NOTE.format(what="a non-linear row expression"))
        return T.call("sum", node)

    def _product(self, node: dict) -> dict:
        left, right = node["left"], node["right"]
        if not T.has_column(left):
            return T.binop("*", left, self.lift(right))
        if not T.has_column(right):
            return T.binop("*", self.lift(left), right)
        self.tr.note(ROWSUM_NOTE.format(what="a product of two columns"))
        return T.call("sum", node)

    def _ratio(self, num: dict, den: dict) -> dict:
        self.tr.trap(RATIO_TRAP)
        return T.call("safe_divide", self.lift(num), self.lift(den))


def _is_flag(node: dict) -> bool:
    if node.get("node") != "ifelse":
        return False
    values = [v for _c, v in node["branches"]] + [node.get("else")]
    return all(v is not None and (T.number_value(v) is not None or T.is_lit(v, "null"))
               for v in values)


def apply_role(tr, node: dict, role: Optional[str]) -> tuple[dict, Optional[str]]:
    """(formula AST, role) for the intended ``role`` (``measure`` / ``attribute`` / None)."""
    if role is None:
        return node, None
    aggregated = T.is_aggregated(node)
    if role == "attribute":
        if aggregated:
            tr.note("the formula aggregates, so it is a MEASURE despite --role attribute")
            return node, "MEASURE"
        return node, "ATTRIBUTE"
    if aggregated:
        return node, "MEASURE"
    if tr.type_of(node) in ("text", "bool", "date"):
        tr.trap(TEXT_TRAP if tr.type_of(node) == "text" else
                TEXT_TRAP.replace("returns text", f"returns a {tr.type_of(node)}"))
        return node, "ATTRIBUTE"
    if _is_flag(node):
        tr.note(FLAG_NOTE)
        return node, "MEASURE"
    if not T.has_column(node):
        return node, "MEASURE"
    return _Lifter(tr).lift(node), "MEASURE"
