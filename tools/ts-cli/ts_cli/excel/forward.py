"""``Translator``: Excel / Sheets AST → ThoughtSpot AST, at row level.

Operators, literals and references are handled here; function calls dispatch to
``functions.HANDLERS`` (and ``SHEETS_HANDLERS`` for Google Sheets). A construct with no rule
raises ``NeedsReview`` — never a guess. Every column reference goes through the one recording
resolver of ``formula_translate.context.ColumnContext``.

The intended role (MEASURE: additive sums, ratio of totals) is a separate pass
(``measure.apply_role``) over this row-level result.
"""
from __future__ import annotations

import re
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
TYPE_UNKNOWN_NOTE = ("column types unknown: {name} was left bare inside concat; if it is "
                     "numeric (or a date / boolean) wrap it in to_string — concat accepts only "
                     "Text, and to_string rejects Text (probe record §7). Pass data_type in "
                     "--columns, or --model, to decide")


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
        # (target, reason, note) for each column whose unknown type changed the output —
        # formula_translate.prompts turns these into the result's needs_types[]
        self.type_needs: list[tuple[str, str, str]] = []

    # -- reporting -----------------------------------------------------------------
    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def trap(self, text: str, downgrade: bool = False) -> None:
        if text not in self.traps:
            self.traps.append(text)
        if downgrade and self.status == TRANSLATED:
            self.status = APPROXIMATED

    def need_type(self, node: dict, reason: str, note: str) -> None:
        """Record that ``node`` (a column reference of unknown type) decided the output."""
        if node.get("node") in ("col", "ref"):
            self.type_needs.append((T.to_text(node), reason, note))

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

    def column_fine_type(self, node: dict) -> Optional[str]:
        """A reference's type with int and double kept apart (``typecheck``)."""
        from ts_cli.excel.typecheck import type_of_data_type

        spec = self.ctx.spec_for_target(T.to_text(node))
        return type_of_data_type(spec.data_type) if spec else None

    def fine_type(self, node: dict) -> Optional[str]:
        """``int`` / ``double`` / ``number`` / ``text`` / ``date`` / … of an emitted node."""
        from ts_cli.excel.typecheck import infer

        return infer(node, self.column_fine_type)

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
        out = handler(self, node)
        if out.get("node") == "call" and out["fn"] in _NUMERIC_ARGS:
            # Excel coerces TRUE to 1 inside MAX(…), ROUND(…); ThoughtSpot does not
            out["args"] = [self.as_number(a) for a in out["args"]]
        return out

    # -- operators ---------------------------------------------------------------------
    def binary(self, node: X.Binary) -> dict:
        if node.op == "&":
            return self.concat(_flatten_concat(node))
        left, right = self.expr(node.left), self.expr(node.right)
        if node.op in ("=", "<>", "<", "<=", ">", ">="):
            return self.compare(node.op, left, right)
        left, right = self.as_number(left), self.as_number(right)
        if node.op == "^":
            return T.call("pow", left, right)
        if node.op in ("+", "-"):
            return self._additive(node.op, left, right)
        if node.op == "/":
            return self.divide(left, right)
        return T.binop(node.op, left, right)

    def as_number(self, node: dict) -> dict:
        """Excel coerces TRUE to 1 in arithmetic; ThoughtSpot rejects a boolean operand
        (``true + 1`` fails import — probe record §7), so coerce it explicitly."""
        if self.type_of(node) == "bool":
            return T.ifelse(node, T.lit_number("1"), T.lit_number("0"))
        return node

    def as_condition(self, node: dict) -> dict:
        """Excel reads a number as a condition (0 is FALSE); ThoughtSpot needs a boolean."""
        t = self.type_of(node)
        if t == "number":
            return T.binop("!=", node, T.lit_number("0"))
        if t is None and node.get("node") in ("col", "ref"):
            note = (f"column type unknown: {T.to_text(node)} is used as a condition as-is; if "
                    f"it is numeric, write {T.to_text(node)} != 0 (Excel reads 0 as FALSE) — "
                    "pass data_type in --columns (or --model) to decide")
            self.trap(note, downgrade=True)
            self.need_type(node, "condition", note)
        return node

    def compare(self, op: str, left: dict, right: dict) -> dict:
        if T.has_column(left) or T.has_column(right):
            self.trap(BLANK_TRAP)
        for value, other in ((left, right), (right, left)):
            if T.is_lit(value, "string", "''") and op in ("=", "<>"):
                return self._blank_test(op, other)
        return T.binop("!=" if op == "<>" else op, left, right)

    def _blank_test(self, op: str, x: dict) -> dict:
        """``x = ""`` is TRUE for a blank cell in Excel: ``isnull ( x )`` (number / date — a
        numeric column compared with '' is rejected at import), ``isnull ( x ) or x = ''``
        (text or unknown type)."""
        t = self.type_of(x)
        if t in ("number", "date", "datetime", "bool"):
            test = T.call("isnull", x)
        else:
            test = T.binop("or", T.call("isnull", x), T.binop("=", x, T.lit_string("")))
            if t is None:
                note = (f"column type unknown: the blank test on {T.to_text(x)} includes "
                        f"{T.to_text(x)} = '', which ThoughtSpot rejects for a numeric or "
                        "date column — there it is isnull alone; pass data_type in --columns "
                        "(or --model) to decide")
                self.trap(note, downgrade=True)
                self.need_type(x, "blank test", note)
        return test if op == "=" else T.unop("not", test)

    def divide(self, left: dict, right: dict) -> dict:
        self.divisions += 1
        if self.division_mode == "safe":
            return T.call("safe_divide", left, right)
        if self.division_mode is None:
            self.trap(DIV_TRAP)
        return T.binop("/", left, right)

    def _temporal(self, op: str, left: dict, right: dict, lt, rt):
        """Date / datetime arithmetic, or None when neither side is temporal."""
        if op == "-" and lt in T.TEMPORAL and rt in T.TEMPORAL:
            if "datetime" in (lt, rt):
                # Excel's difference is in days WITH the time fraction; diff_days drops the
                # hours. diff_time ( end , start ) is seconds (live 2026-10-06: one day =
                # 86400, end first), so / 86400 is the Excel serial difference.
                return T.binop("/", T.call("diff_time", left, right), T.lit_number("86400"))
            return T.call("diff_days", left, right)
        if lt in T.TEMPORAL and rt == "number":
            amount = self._whole_days(right)
            return T.call("add_days", left, amount if op == "+" else T.unop("-", amount))
        if op == "+" and rt in T.TEMPORAL and lt == "number":
            return T.call("add_days", right, self._whole_days(left))
        return None

    def _additive(self, op: str, left: dict, right: dict) -> dict:
        lt, rt = self.type_of(left), self.type_of(right)
        temporal = self._temporal(op, left, right, lt, rt)
        if temporal is not None:
            return temporal
        if lt in T.TEMPORAL or rt in T.TEMPORAL:
            self.review("date arithmetic with an operand whose type is not known to be a date "
                        "or a number of days has no ThoughtSpot form (Excel map E9) — pass "
                        "data_type in --columns (or --model) for its columns")
        unknown = [T.to_text(x) for x, t in ((left, lt), (right, rt))
                   if t is None and x.get("node") in ("col", "ref")]
        if unknown:
            note = (f"column type unknown ({', '.join(unknown)}): if these are dates, "
                    "ThoughtSpot has no date arithmetic — a date difference is diff_days "
                    "( end , start ) and date + n is add_days ( d , n ); pass data_type in "
                    "--columns (or --model) to decide")
            self.trap(note, downgrade=True)
            for x, t in ((left, lt), (right, rt)):
                if t is None:
                    self.need_type(x, "date arithmetic", note)
        return T.binop(op, left, right)

    def _whole_days(self, amount: dict) -> dict:
        """add_days takes whole days; Excel's date + 0.5 (or + 1/24) adds a time of day."""
        value = T.number_value(amount)
        if value is not None and value != value.to_integral_value():
            self.review("adding a fraction of a day to a date or datetime (+0.5, +1/24) has no "
                        "add_days form — add_days takes whole days; for hours use add_minutes "
                        "( d , n * 60 ) or add_seconds on a DATETIME")
        if value is None and any(n.get("node") == "binop" and n["op"] == "/"
                                            for n in T.walk(amount)):
            self.review("a computed number of days (e.g. 1/24) added to a date may be "
                        "fractional — add_days takes whole days")
        return amount

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
        if t is None:
            # Left bare: to_string rejects a Text argument at import, so wrapping a column
            # that turns out to be text would break the formula (PR #570 review H4).
            note = TYPE_UNKNOWN_NOTE.format(name=T.to_text(node))
            self.trap(note, downgrade=True)
            self.need_type(node, "text join", note)
            return node
        if t == "bool":
            self.note("to_string of a boolean gives 'true' / 'false'; Excel's & shows TRUE / "
                      "FALSE")
        if t in T.TEMPORAL:
            self.trap("a date joined with & is its serial number in Excel; ThoughtSpot's "
                      "to_string gives the date text — use TEXT() semantics deliberately",
                      downgrade=True)
        elif t == "number" and node.get("node") != "lit":
            self.trap("to_string of a DOUBLE may render a decimal ('12.0') where Excel shows "
                      "12 — exact for an integer column")
        return T.call("to_string", node)


_CELL = re.compile(r"(\$?)([A-Za-z]{1,3})(\$?)(\d+)")
A1_WINDOW_HINT = ("a position-dependent formula needs an order column the Model has: a running "
                  "total is cumulative_sum ( x , [order] ), the previous row is "
                  "moving_sum ( x , 1 , -1 , [order] ) (Excel map E6)")


def check_a1(tree) -> None:
    """Refuse A1 shapes that depend on a cell's POSITION, not just its column (PR #570 review
    H1): a formula over a Model column is evaluated per row, so a row number is meaningless —
    except the one shared row of a fill-down formula (``=A2*B2``)."""
    rows = set()
    for node in X.walk(tree):
        if not (isinstance(node, X.Ref) and node.kind == "a1") or node.grain == "block":
            continue  # a multi-column block is refused (or reported structural) when translated
        if node.sheet:
            raise NeedsReview(f"`{node.raw}` reads another sheet ('{node.sheet}'), which is not "
                              "this table — model it as a joined table and reference its column")
        cells = _CELL.findall(node.raw.split("!")[-1])
        if len(cells) == 2:
            anchored = {c[2] for c in cells}
            if len(anchored) == 2:
                raise NeedsReview(f"`{node.raw}` is an expanding range (one end anchored) — "
                                  + A1_WINDOW_HINT)
            raise NeedsReview(f"`{node.raw}` is a bounded range, not a column: write the whole "
                              "column (A:A) or a Table column (Table[Col]) for a column "
                              "aggregate, or filter with sum_if for a subset")
        if len(cells) == 1:
            if cells[0][2]:
                raise NeedsReview(f"`{node.raw}` is a fixed cell (an anchored row) — an input, "
                                  "not a row value: use a runtime parameter")
            rows.add(cells[0][3])
    if len(rows) > 1:
        raise NeedsReview(f"the formula reads rows {', '.join(sorted(rows, key=int))} — a "
                          "reference to another row is " + A1_WINDOW_HINT)


# ThoughtSpot functions whose arguments are all numbers (a boolean there is coerced).
_NUMERIC_ARGS = frozenset({"greatest", "least", "abs", "round", "floor", "ceil", "pow", "sqrt",
                           "ln", "exp", "log10", "sum", "average", "max", "min", "median",
                           "stddev", "variance"})


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
    return inner if n.op == "+" else T.unop("-", tr.as_number(inner))


def _percent(tr: Translator, n: X.Percent) -> dict:
    return T.binop("/", tr.as_number(tr.expr(n.operand)), T.lit_number("100"))


def _array(tr: Translator, n: X.Array) -> dict:
    tr.review("an array constant has no row-level reading (Excel map E6); only the *IFS "
              "OR-idiom and holiday lists use one")


_NODE_HANDLERS = {
    X.Num: _num, X.Str: _str, X.Bool: _bool, X.Err: _err, X.Missing: _missing,
    X.Ref: Translator.ref, X.Unary: _unary, X.Percent: _percent,
    X.Binary: Translator.binary, X.Call: Translator.call, X.Array: _array,
}
