"""ThoughtSpot formula → Excel formula (``ts formula translate --from thoughtspot --to excel``).

The ThoughtSpot text is parsed with the repo's one ThoughtSpot parser
(``databricks.mv_emit_expr.parse_formula``) and emitted against an Excel Table (default
``Table1``): a row-level reference is ``[@Col]``, a reference inside an aggregate is
``Table1[Col]``. Function rules are in ``to_excel_calls``. A construct with no Excel equivalent
(window functions, ``rank``, ``sql_*_op`` pass-throughs, a query-dependent grain) is
NEEDS_REVIEW with the reason — never an approximation passed off as a translation.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional

from ts_cli.formula_common import UntranslatableError

TRANSLATED = "TRANSLATED"
APPROXIMATED = "APPROXIMATED"
NEEDS_REVIEW = "NEEDS_REVIEW"

# Excel precedence, loosest first (for parenthesisation only).
P_CMP, P_CONCAT, P_ADD, P_MUL, P_POW, P_NEG, P_PRIMARY = 1, 2, 3, 4, 5, 6, 8
_TS_PREC = {"=": P_CMP, "!=": P_CMP, "<": P_CMP, "<=": P_CMP, ">": P_CMP, ">=": P_CMP,
            "+": P_ADD, "-": P_ADD, "*": P_MUL, "/": P_MUL}

BLANK_TRAP = ("Excel treats a blank cell as 0 (or \"\") in arithmetic and comparisons, while a "
              "ThoughtSpot NULL propagates — the two agree only where the column has no NULLs")
CASE_NOTE = ("= and SEARCH are case-insensitive in Excel, like ThoughtSpot's =, contains and "
             "strpos (probe record §4) — no case change")
_NEEDS_BRACKETS = re.compile(r"[^A-Za-z0-9_.]")
_ESCAPE = re.compile(r"([\[\]#'])")


class ExcelReview(Exception):
    pass


@dataclass
class ExcelOut:
    formula: Optional[str]
    status: str
    notes: list = field(default_factory=list)
    traps: list = field(default_factory=list)
    references: list = field(default_factory=list)


class Emitter:
    def __init__(self, table: str = "Table1", column_types: Optional[dict] = None):
        self.table = table
        self.column_types = column_types or {}  # "[T::c]" -> "date" | "datetime" | …
        self.agg = 0
        self.notes: list[str] = []
        self.traps: list[str] = []
        self.status = TRANSLATED
        self.refs: dict[str, str] = {}

    # -- reporting -------------------------------------------------------------------
    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def trap(self, text: str, downgrade: bool = False) -> None:
        if text not in self.traps:
            self.traps.append(text)
        if downgrade and self.status == TRANSLATED:
            self.status = APPROXIMATED

    def review(self, reason: str) -> None:
        raise ExcelReview(reason)

    @contextmanager
    def aggregate(self):
        self.agg += 1
        try:
            yield
        finally:
            self.agg -= 1

    # -- emission: each returns (text, precedence) -------------------------------------
    def emit(self, node: dict) -> tuple[str, int]:
        kind = node.get("node")
        handler = getattr(self, f"_e_{kind}", None)
        if handler is None:
            self.review(f"no Excel form for {kind!r}")
        return handler(node)

    def text(self, node: dict, minimum: int = 0) -> str:
        out, prec = self.emit(node)
        return f"({out})" if prec < minimum else out

    def _e_col(self, node: dict) -> tuple[str, int]:
        return self.column(node["column"], f"[{node['table']}::{node['column']}]"), P_PRIMARY

    def _e_ref(self, node: dict) -> tuple[str, int]:
        name = node["name"]
        if name.startswith("formula_"):
            name = name[len("formula_"):]
            self.note(f"[formula_{name}] is another formula: in Excel it is a calculated column "
                      f"of {self.table} named {name!r}")
        else:
            self.note(f"[{name}] (a parameter or display-name reference) is read as a column of "
                      f"{self.table}; a runtime parameter is a single input cell in Excel")
        return self.column(name, f"[{node['name']}]"), P_PRIMARY

    def column(self, name: str, source: str) -> str:
        esc = _ESCAPE.sub(r"'\1", name)
        if self.agg:
            target = f"{self.table}[{esc}]"
        elif _NEEDS_BRACKETS.search(name):
            target = f"[@[{esc}]]"
        else:
            target = f"[@{esc}]"
        self.refs.setdefault(source, target)
        return target

    def _e_lit(self, node: dict) -> tuple[str, int]:
        kind, value = node["kind"], node["value"]
        if kind == "string":
            inner = value[1:-1].replace("''", "'")
            return '"' + inner.replace('"', '""') + '"', P_PRIMARY
        if kind == "bool":
            return value.upper(), P_PRIMARY
        if kind == "null":
            self.trap("null became \"\" (a blank text): Excel has no NULL; a numeric column "
                      "would show the blank where ThoughtSpot has NULL", downgrade=True)
            return '""', P_PRIMARY
        return value, P_PRIMARY

    def _e_unop(self, node: dict) -> tuple[str, int]:
        if node["op"] == "not":
            return f"NOT({self.text(node['operand'])})", P_PRIMARY
        return f"-{self.text(node['operand'], P_NEG)}", P_NEG

    def _e_binop(self, node: dict) -> tuple[str, int]:
        op = node["op"]
        if op in ("and", "or"):
            return self.logical(op, node), P_PRIMARY
        prec = _TS_PREC[op]
        left = self.text(node["left"], prec)
        right = self.text(node["right"], prec + 1)
        if prec == P_CMP:
            left = self.typed_literal(node["left"], left, node["right"])
            right = self.typed_literal(node["right"], right, node["left"])
        if op == "/":
            self.trap("a zero divisor: ThoughtSpot's / returns NULL, Excel shows #DIV/0! "
                      "(safe_divide is the guarded form)")
        if prec == P_CMP and _has_string(node):
            self.note(CASE_NOTE)
        return f"{left}{'<>' if op == '!=' else op}{right}", prec

    def logical(self, op: str, node: dict) -> str:
        parts = _flatten(node, op)
        if self.agg:  # AND / OR collapse an array to one value: use * and + element-wise
            joined = ("*" if op == "and" else "+").join(f"({self.text(p)})" for p in parts)
            return joined if op == "and" else f"(({joined})>0)"
        return f"{op.upper()}(" + ",".join(self.text(p) for p in parts) + ")"

    def _e_ifelse(self, node: dict) -> tuple[str, int]:
        other = node.get("else")
        out = self.text(other) if other is not None else None
        for cond, value in reversed(node["branches"]):
            args = [self.text(cond), self.text(value)] + ([out] if out is not None else [])
            out = "IF(" + ",".join(args) + ")"
        if other is None:
            self.note("if without else: Excel's IF returns FALSE when the test fails")
        return out, P_PRIMARY

    def _e_call(self, node: dict) -> tuple[str, int]:
        from ts_cli.excel.to_excel_calls import CALLS, NO_EXCEL

        fn = node["fn"]
        if fn in CALLS:
            return CALLS[fn](self, node["args"])
        reason = NO_EXCEL.get(fn) or next(
            (why for prefix, why in NO_EXCEL.items() if prefix.endswith("_") and
             fn.startswith(prefix)), None)
        self.review(f"{fn}: {reason}" if reason else
                    f"{fn}: no Excel rule — rewrite by hand from the Excel map's reverse "
                    "direction section")

    def _e_lodset(self, node: dict) -> tuple[str, int]:
        self.review("a { … } list outside in / group_aggregate has no Excel form")


    def column_type(self, node: dict) -> Optional[str]:
        if node.get("node") == "col":
            return self.column_types.get(f"[{node['table']}::{node['column']}]")
        if node.get("node") == "ref":
            return self.column_types.get(f"[{node['name']}]")
        return None

    def typed_literal(self, lit: dict, text: str, other: dict) -> str:
        """A string literal set against a column: a 'yyyy-mm-dd[ hh:mm[:ss]]' value is a date
        or datetime to ThoughtSpot, a numeric string a number — Excel would compare text, so
        it becomes DATEVALUE(…)[+TIMEVALUE(…)] / VALUE(…). Exact when the column is known to
        be a date (or a number); otherwise APPROXIMATED with a note."""
        if not (lit.get("node") == "lit" and lit["kind"] == "string"):
            return text
        value = lit["value"][1:-1]
        m = _ISO_DATETIME.fullmatch(value)
        if m:
            out = f'DATEVALUE("{m.group(1)}")' + (f'+TIMEVALUE("{m.group(2)}")' if m.group(2) else "")
            self._typed_note(other, ("date", "datetime"), out)
            return out
        if _NUMERIC.fullmatch(value) and other.get("node") in ("col", "ref"):
            self._typed_note(other, ("number",), f'VALUE("{value}")')
            return f'VALUE("{value}")'
        return text

    def _typed_note(self, other: dict, wanted: tuple, out: str) -> None:
        if self.column_type(other) not in wanted:
            self.trap(f"column type unknown: {out} assumes {to_ts_text(other)} is a "
                      f"{' / '.join(wanted)}; if it is text, compare with the string as written "
                      "(pass --columns with data_type to decide)", downgrade=True)


_ISO_DATETIME = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?))?")
_NUMERIC = re.compile(r"-?\d+(?:\.\d+)?")


def to_ts_text(node: dict) -> str:
    from ts_cli.excel.tsast import to_text
    return to_text(node)


def _flatten(node: dict, op: str) -> list:
    if node.get("node") == "binop" and node["op"] == op:
        return _flatten(node["left"], op) + _flatten(node["right"], op)
    return [node]


def _has_string(node: dict) -> bool:
    from ts_cli.excel.tsast import walk
    return any(n.get("node") == "lit" and n["kind"] == "string" for n in walk(node))


def to_excel(ts_formula: str, table: str = "Table1", specs: Optional[list] = None) -> ExcelOut:
    """Translate one ThoughtSpot formula into an Excel formula (leading ``=``). ``specs``
    (``formula_translate.context.ColumnSpec`` list, from ``--columns``) give column types."""
    from ts_cli.excel.helpers import from_text
    from ts_cli.excel.tsast import has_column, type_of_data_type

    types = {s.target: type_of_data_type(s.data_type) for s in (specs or []) if s.data_type}
    em = Emitter(table, types)
    try:
        node = from_text(ts_formula)
        text = em.text(node)
    except UntranslatableError as exc:
        return ExcelOut(None, NEEDS_REVIEW, [f"cannot parse the ThoughtSpot formula: {exc}"])
    except ExcelReview as exc:
        return ExcelOut(None, NEEDS_REVIEW, em.notes + [str(exc)], em.traps)
    if has_column(node):
        em.trap(BLANK_TRAP)
    refs = [{"source": s, "target": t} for s, t in em.refs.items()]
    return ExcelOut("=" + text, em.status, em.notes, em.traps, refs)
