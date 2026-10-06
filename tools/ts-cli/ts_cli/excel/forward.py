"""``Translator``: Excel / Sheets AST → ThoughtSpot AST, at row level.

Operators, literals and references are handled here; function calls dispatch to
``functions.HANDLERS`` (and ``SHEETS_HANDLERS`` for Google Sheets). A construct with no rule
raises ``NeedsReview`` — never a guess. Every column reference goes through the one recording
resolver of ``formula_translate.context.ColumnContext``.

The intended role (MEASURE: additive sums, ratio of totals) is a separate pass
(``measure.apply_role``) over this row-level result.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Optional

from ts_cli.excel import nodes as X
from ts_cli.excel import tsast as T
from ts_cli.excel.map_index import cite

TRANSLATED = "TRANSLATED"
APPROXIMATED = "APPROXIMATED"
NEEDS_REVIEW = "NEEDS_REVIEW"

BLANK_TRAP = ("E10: a blank cell is 0 / \"\" to Excel; a NULL in ThoughtSpot propagates through "
              "arithmetic and concat and makes a comparison unknown (the IF takes its else "
              "branch) — wrap nullable columns in ifnull ( x , 0 ) or ifnull ( x , '' ) where "
              "the sheet relied on blanks")
DIV_TRAP = ("a zero divisor: Excel shows #DIV/0!; ThoughtSpot's plain / returns NULL "
            "(probe record §7)")
TYPE_UNKNOWN_NOTE = ("concat needs Text arguments, so {name} (type unknown) was wrapped in "
                     "to_string; if it is a text column remove to_string — ThoughtSpot rejects "
                     "to_string on Text (probe record §7). Pass data_type in --columns to decide")


class NeedsReview(Exception):
    """The construct has no rule; the message is the user-facing reason."""


class Translator:
    def __init__(self, ctx, dialect: str = "excel"):
        self.ctx = ctx
        self.dialect = dialect
        self.notes: list[str] = []
        self.traps: list[str] = []
        self.status = TRANSLATED
        self.agg_depth = 0
        self.division_mode: Optional[str] = None   # None | "safe" (IFERROR …, 0)
        self.divisions = 0
        self.elementwise = False                   # inside Sheets ARRAYFORMULA

    # -- reporting -----------------------------------------------------------------
    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def trap(self, text: str, downgrade: bool = False) -> None:
        if text not in self.traps:
            self.traps.append(text)
        if downgrade and self.status == TRANSLATED:
            self.status = APPROXIMATED

    def review(self, reason: str) -> None:
        raise NeedsReview(reason)

    def no_rule(self, name: str) -> None:
        self.review(f"{name}: the translator has no rule for it — {cite(name, self.dialect)}. "
                    "Read that row for the ThoughtSpot form or workaround (hand-composed, "
                    "not translator output)")

    @contextmanager
    def aggregate(self):
        self.agg_depth += 1
        try:
            yield
        finally:
            self.agg_depth -= 1

    # -- types -----------------------------------------------------------------------
    def column_type(self, node: dict) -> Optional[str]:
        spec = self.ctx.spec_for_target(T.to_text(node))
        return T.type_of_data_type(spec.data_type) if spec else None

    def type_of(self, node: dict) -> Optional[str]:
        return T.type_of(node, self.column_type)

    # -- dispatch ----------------------------------------------------------------------
    def expr(self, node) -> dict:
        handler = _NODE_HANDLERS.get(type(node))
        if handler is None:
            self.review(f"unsupported construct {type(node).__name__}")
        return handler(self, node)

    def ref(self, node: X.Ref) -> dict:
        if node.kind == "a1":
            return self._a1(node)
        if node.kind == "name":
            self.note(f"`{node.raw}` is a defined name, read as a column; if it is a single "
                      "input cell, a runtime parameter is the ThoughtSpot form")
        if node.grain == "column" and not self.agg_depth and not self.elementwise:
            self.note(f"`{node.raw}` outside an aggregate is Excel's implicit intersection — "
                      "read as the row's value")
        return T.ref_node(self.ctx.resolve(node.column, table_hint=node.table))

    def _a1(self, node: X.Ref) -> dict:
        if node.grain == "block":
            self.review(f"range {node.raw} spans several columns — no single-column reading "
                        "(Excel map E5)")
        target = self.ctx.resolve(node.column)
        ref = next((r for r in self.ctx.references if r.source == node.column), None)
        if ref is not None and ref.placeholder:
            self.note(f"NEEDS_REVIEW: A1 reference `{node.raw}` is a placeholder {target} — "
                      f"column {node.column} has no name; map it with --columns "
                      f"'{{\"{node.column}\": \"TABLE.COLUMN\"}}'")
        if node.sheet:
            self.note(f"`{node.raw}` reads sheet '{node.sheet}' — usually another table, "
                      "joined in the Model")
        if node.absolute:
            self.note(f"`{node.raw}` is a fixed cell — usually an input; a runtime parameter "
                      "is the ThoughtSpot form")
        if node.grain == "column" and not self.agg_depth and not self.elementwise:
            self.note(f"range `{node.raw}` outside an aggregate read as the row's value")
        return T.ref_node(target)

    def call(self, node: X.Call) -> dict:
        from ts_cli.excel.functions import HANDLERS, SHEETS_HANDLERS

        handler = None
        if self.dialect == "google_sheets":
            handler = SHEETS_HANDLERS.get(node.name)
        handler = handler or HANDLERS.get(node.name)
        if handler is None:
            self.no_rule(node.name)
        return handler(self, node)

    # -- operators ---------------------------------------------------------------------
    def binary(self, node: X.Binary) -> dict:
        if node.op == "&":
            return self.concat(_flatten_concat(node))
        left, right = self.expr(node.left), self.expr(node.right)
        if node.op == "^":
            return T.call("pow", left, right)
        if node.op in ("+", "-"):
            return self._additive(node.op, left, right)
        if node.op == "/":
            return self.divide(left, right)
        if node.op in ("=", "<>", "<", "<=", ">", ">="):
            if T.has_column(left) or T.has_column(right):
                self.trap(BLANK_TRAP)
            return T.binop("!=" if node.op == "<>" else node.op, left, right)
        return T.binop(node.op, left, right)

    def divide(self, left: dict, right: dict) -> dict:
        self.divisions += 1
        if self.division_mode == "safe":
            return T.call("safe_divide", left, right)
        if self.division_mode is None:
            self.trap(DIV_TRAP)
        return T.binop("/", left, right)

    def _additive(self, op: str, left: dict, right: dict) -> dict:
        lt, rt = self.type_of(left), self.type_of(right)
        if op == "-" and lt == "date" and rt == "date":
            return T.call("diff_days", left, right)
        if lt == "date" and rt == "number":
            amount = right if op == "+" else T.unop("-", right)
            return T.call("add_days", left, amount)
        if op == "+" and rt == "date" and lt == "number":
            return T.call("add_days", right, left)
        if "date" in (lt, rt):
            self.review("date arithmetic with an operand that is not a number of days has no "
                        "ThoughtSpot form (Excel map E9)")
        return T.binop(op, left, right)

    def concat(self, operands: list) -> dict:
        """Excel ``&`` / CONCAT: one N-argument ``concat`` of Text arguments (probe §7)."""
        parts = [p for p in operands if not (isinstance(p, X.Str) and p.value == "")]
        if not parts:
            return T.lit_string("")
        texts = [self.as_text(self.expr(p)) for p in parts]
        if any(T.has_column(t) for t in texts):
            self.trap(BLANK_TRAP)
        return texts[0] if len(texts) == 1 else T.call("concat", *texts)

    def as_text(self, node: dict) -> dict:
        t = self.type_of(node)
        if t == "text":
            return node
        if t == "date":
            self.trap("a date joined with & is its serial number in Excel; ThoughtSpot's "
                      "to_string gives the date text — use TEXT() semantics deliberately",
                      downgrade=True)
        elif t is None:
            self.note(TYPE_UNKNOWN_NOTE.format(name=T.to_text(node)))
        elif t == "number" and node.get("node") != "lit":
            self.trap("to_string of a DOUBLE may render a decimal ('12.0') where Excel shows "
                      "12 — exact for an integer column")
        return T.call("to_string", node)


def _flatten_concat(node) -> list:
    if isinstance(node, X.Binary) and node.op == "&":
        return _flatten_concat(node.left) + _flatten_concat(node.right)
    return [node]


def _num(tr: Translator, n: X.Num) -> dict:
    return T.lit_number(n.text)


def _str(tr: Translator, n: X.Str) -> dict:
    return T.lit_string(n.value)


def _bool(tr: Translator, n: X.Bool) -> dict:
    return T.lit_bool(n.value)


def _err(tr: Translator, n: X.Err) -> dict:
    tr.review(f"the error literal {n.text} has no ThoughtSpot value (Excel map E8)")


def _missing(tr: Translator, n: X.Missing) -> dict:
    tr.review("an omitted argument has no ThoughtSpot form here")


def _unary(tr: Translator, n: X.Unary) -> dict:
    inner = tr.expr(n.operand)
    return inner if n.op == "+" else T.unop("-", inner)


def _percent(tr: Translator, n: X.Percent) -> dict:
    return T.binop("/", tr.expr(n.operand), T.lit_number("100"))


def _array(tr: Translator, n: X.Array) -> dict:
    tr.review("an array constant has no row-level reading (Excel map E6); only the *IFS "
              "OR-idiom and holiday lists use one")


_NODE_HANDLERS = {
    X.Num: _num, X.Str: _str, X.Bool: _bool, X.Err: _err, X.Missing: _missing,
    X.Ref: Translator.ref, X.Unary: _unary, X.Percent: _percent,
    X.Binary: Translator.binary, X.Call: Translator.call, X.Array: _array,
}
