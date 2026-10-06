"""A type checker over an emitted ThoughtSpot AST — the safety net behind the Excel rules.

ThoughtSpot type-checks a formula at import (*Function X expects 1st argument to be Numeric*,
error_code 14516). A translation that would fail that check must never come back TRANSLATED:
fidelity M1 found 36 of them (BL-352..355). This module infers each node's type and checks every
function argument, operator operand and ``if`` branch against a signature table, so a provable
type error becomes NEEDS_REVIEW with the reason, and an argument whose column type is unknown is
reported for the ``needs_types`` prompt instead of being guessed.

Types: ``text``, ``int``, ``double``, ``number`` (numeric, integer-ness unknown — a DECIMAL
column), ``date``, ``datetime``, ``bool``, ``null``; ``None`` is unknown.

**ThoughtSpot's "Numeric" is an integer.** Probed with VALIDATE_ONLY on se-thoughtspot,
2026-10-07 (probe record §7): a DOUBLE column, or a decimal literal, is rejected wherever the
error message asks for *Numeric* — ``substr`` start and length, ``left`` / ``right`` count,
``add_days`` / ``add_months`` amount, both ``mod`` arguments, and ``to_double`` itself
(*expects Boolean or Numeric or Text*). ``abs``, ``ceil``, ``floor``, ``round``, ``pow``,
``sqrt``, ``ln``, ``exp``, ``log10``, ``safe_divide``, ``greatest`` / ``least``, arithmetic and
the aggregates accept a DOUBLE. ``to_string`` takes one argument only for a boolean or number:
on a DATE or DATE_TIME the one-argument form is rejected (*expects 2 arguments*).
"""
from __future__ import annotations

from typing import Callable, Optional

from ts_cli.excel import tsast as T

NUMERIC = ("int", "double", "number")
TEMPORAL = ("date", "datetime")

_INT_TYPES = {"INT32", "INT64", "INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT"}
_DOUBLE_TYPES = {"DOUBLE", "FLOAT", "REAL"}


def type_of_data_type(data_type: Optional[str]) -> Optional[str]:
    """A ThoughtSpot ``data_type`` → this module's type (int and double kept apart)."""
    dt = (data_type or "").upper()
    if dt in _INT_TYPES:
        return "int"
    if dt in _DOUBLE_TYPES:
        return "double"
    coarse = T.type_of_data_type(data_type)
    return "number" if coarse == "number" else coarse


# ---------------------------------------------------------------------------
# Parameter kinds: which argument types a slot accepts
# ---------------------------------------------------------------------------
# kind -> (accepted types, the wording ThoughtSpot would use)
KINDS: dict[str, tuple[tuple, str]] = {
    "text": (("text",), "Text"),
    "int": (("int",), "an integer (ThoughtSpot's Numeric; a DOUBLE is rejected)"),
    "num": (NUMERIC, "a number"),
    "date": (TEMPORAL, "a Date or DateTime"),
    "bool": (("bool",), "a Boolean"),
    # to_string ( x ): one argument only for Boolean or a number (probe record §7)
    "to_string": (("bool",) + NUMERIC, "a Boolean or a number (a Date needs to_string's "
                                       "2-argument form; Text is rejected)"),
    # to_double ( x ): Boolean, integer or Text — a DOUBLE is rejected (probe record §7)
    "to_double": (("bool", "int", "text"), "a Boolean, an integer or Text (a DOUBLE is "
                                           "rejected — it is a number already)"),
    "to_integer": (("bool", "text") + NUMERIC, "a Boolean, a number or Text"),
}
# "number" (integer-ness unknown) in an int slot cannot be decided: not an error.
_UNDECIDED = {("int", "number"), ("to_double", "number")}
# Slots where an unknown column type is asked about (needs_types). Elsewhere the bare output is
# right for the common type (a number in arithmetic, text in a text function), so asking about
# every column would be noise — the same rule ``prompts.build_needs_types`` applies to date
# arithmetic. Here the common Excel case is the failing one: every Excel number is a DOUBLE.
ASK_KINDS = frozenset({"int", "to_double", "to_string"})

_DATE_PARTS = ("year", "month_number", "day", "day_number_of_week", "quarter_number",
               "day_number_of_year", "day_number_of_quarter", "month_number_of_quarter",
               "week_number_of_year", "week_number_of_month", "week_number_of_quarter",
               "hour_of_day")
_DATE_STARTS = ("start_of_month", "start_of_year", "start_of_quarter", "start_of_week")
_DIFFS = ("diff_days", "diff_weeks", "diff_months", "diff_quarters", "diff_years",
          "diff_time", "diff_hours", "diff_minutes")

# fn -> (fixed parameter kinds, variadic kind or None, return type or rule). Only the
# parameters listed are checked; an optional trailing argument (a calendar name, a fiscal
# flag) is left alone. A function not in the table is inferred unknown — its arguments are
# still checked recursively.
SIGNATURES: dict[str, tuple[list, Optional[str], object]] = {
    "concat": ([], "text", "text"),
    "to_string": (["to_string"], None, "text"),
    "to_double": (["to_double"], None, "double"),
    "to_integer": (["to_integer"], None, "int"),
    "to_date": ([None, "text"], None, "date"),
    "substr": (["text", "int", "int"], None, "text"),
    "left": (["text", "int"], None, "text"),
    "right": (["text", "int"], None, "text"),
    "strlen": (["text"], None, "int"),
    "strpos": (["text", "text"], None, "int"),
    "contains": (["text", "text"], None, "bool"),
    "abs": (["num"], None, "arg0"),
    "ceil": (["num"], None, "int"),
    "floor": (["num"], None, "int"),
    "round": (["num", "num"], None, "number"),
    "sqrt": (["num"], None, "double"),
    "ln": (["num"], None, "double"),
    "exp": (["num"], None, "double"),
    "log10": (["num"], None, "double"),
    "log2": (["num"], None, "double"),
    # radians in and out (probe record §7, 2026-10-07)
    **{fn: (["num"], None, "double") for fn in ("sin", "cos", "tan", "asin", "acos", "atan")},
    "pow": (["num", "num"], None, "double"),
    "mod": (["int", "int"], None, "int"),
    "safe_divide": (["num", "num"], None, "double"),
    "greatest": ([], "num", "numeric"),
    "least": ([], "num", "numeric"),
    "sum": (["num"], None, "arg0"),
    "average": (["num"], None, "double"),
    "stddev": (["num"], None, "double"),
    "variance": (["num"], None, "double"),
    "median": (["num"], None, "double"),
    "count": ([None], None, "int"),
    "unique count": ([None], None, "int"),
    "sum_if": (["bool", "num"], None, "arg1"),
    "average_if": (["bool", "num"], None, "double"),
    "count_if": (["bool", None], None, "int"),
    "max_if": (["bool", None], None, "arg1"),
    "min_if": (["bool", None], None, "arg1"),
    "month": (["date"], None, "text"),
    "day_of_week": (["date"], None, "text"),
    "year_name": (["date"], None, "text"),
    "is_weekend": (["date"], None, "bool"),
    "today": ([], None, "date"),
    "now": ([], None, "datetime"),
    "date": (["date"], None, "date"),
    "add_days": (["date", "int"], None, "arg0"),
    "add_weeks": (["date", "int"], None, "arg0"),
    "add_months": (["date", "int"], None, "arg0"),
    "add_years": (["date", "int"], None, "arg0"),
    "isnull": ([None], None, "bool"),
    "ifnull": ([None, None], None, "same"),
    "sql_string_op": ([None], None, "text"),
    "sql_int_op": ([None], None, "int"),
    "sql_double_op": ([None], None, "double"),
    "sql_bool_op": ([None], None, "bool"),
    "sql_date_op": ([None], None, "date"),
    "sql_date_time_op": ([None], None, "datetime"),
    **{fn: (["date"], None, "int") for fn in _DATE_PARTS},
    **{fn: (["date"], None, "date") for fn in _DATE_STARTS},
    **{fn: (["date", "date"], None, "int") for fn in _DIFFS},
}

_COMPARE = ("=", "!=", "<", "<=", ">", ">=")


def _family(t: Optional[str]) -> Optional[str]:
    if t in NUMERIC:
        return "number"
    if t in TEMPORAL:
        return "date"
    return t


def _num_result(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if a == "int" and b == "int":
        return "int"
    return "double" if "double" in (a, b) else "number"


def unify(types: list) -> Optional[str]:
    """One type for ``if`` branches / ``ifnull`` arguments, or None when they differ or are
    unknown. ``null`` joins anything; int and double join as double."""
    ts = [t for t in types if t != "null"]
    if not ts or None in ts:
        return None
    if all(t in NUMERIC for t in ts):
        return "int" if all(t == "int" for t in ts) else ("double" if "double" in ts
                                                          else "number")
    fams = {_family(t) for t in ts}
    if len(fams) == 1:
        return ts[0] if len(set(ts)) == 1 else fams.pop()
    return None


class Checker:
    """``check(node)`` → ``(errors, unknown)``: ``errors`` are provable type errors (text),
    ``unknown`` is ``[(column node, what the slot needs)]`` for columns of unknown type in a
    typed slot."""

    def __init__(self, column_type: Callable[[dict], Optional[str]]):
        self.column_type = column_type
        self.errors: list[str] = []
        self.unknown: list[tuple[dict, str]] = []

    # -- reporting -------------------------------------------------------------------
    def _error(self, text: str) -> None:
        if text not in self.errors:
            self.errors.append(text)

    def _want(self, node: dict, t: Optional[str], kind: str, where: str) -> None:
        accepted, wording = KINDS[kind]
        if t is None:
            if kind in ASK_KINDS and node.get("node") in ("col", "ref"):
                self.unknown.append((node, f"{where} needs {wording}"))
            return
        if t in accepted or (kind, t) in _UNDECIDED or t == "null":
            return
        self._error(f"{where} expects {wording}; `{T.to_text(node)}` is {_article(t)}")

    # -- inference + checks ------------------------------------------------------------
    def infer(self, node: dict) -> Optional[str]:
        kind = node.get("node")
        if kind == "lit":
            k = node["kind"]
            if k == "number":
                return "double" if any(c in node["value"] for c in ".eE") else "int"
            return {"string": "text", "bool": "bool", "null": "null"}.get(k)
        if kind in ("col", "ref"):
            return self.column_type(node)
        if kind == "unop":
            t = self.infer(node["operand"])
            if node["op"] == "not":
                self._want(node["operand"], t, "bool", "not")
                return "bool"
            self._want(node["operand"], t, "num", "unary -")
            return t if t in NUMERIC else ("number" if t is None else None)
        if kind == "binop":
            return self._binop(node)
        if kind == "ifelse":
            return self._ifelse(node)
        if kind == "call":
            return self._call(node)
        for c in T.children(node):
            self.infer(c)
        return None

    def _binop(self, node: dict) -> Optional[str]:
        op = node["op"]
        lt, rt = self.infer(node["left"]), self.infer(node["right"])
        if op in ("and", "or"):
            self._want(node["left"], lt, "bool", op)
            self._want(node["right"], rt, "bool", op)
            return "bool"
        if op in _COMPARE:
            fl, fr = _family(lt), _family(rt)
            if None not in (fl, fr) and "null" not in (fl, fr) and fl != fr:
                self._error(f"`{T.to_text(node)}` compares {_article(lt)} with "
                            f"{_article(rt)}; ThoughtSpot rejects a comparison across types")
            return "bool"
        self._want(node["left"], lt, "num", f"operator {op}")
        self._want(node["right"], rt, "num", f"operator {op}")
        if op == "/":
            return "double"
        return _num_result(lt, rt)

    def _ifelse(self, node: dict) -> Optional[str]:
        values = []
        for cond, value in node["branches"]:
            self._want(cond, self.infer(cond), "bool", "an if condition")
            values.append((value, self.infer(value)))
        if node.get("else") is not None:
            values.append((node["else"], self.infer(node["else"])))
        known = [(v, t) for v, t in values if t not in (None, "null")]
        fams = {_family(t) for _v, t in known}
        if len(fams) > 1:
            shown = ", ".join(f"`{T.to_text(v)}` ({t})" for v, t in known)
            self._error(f"the if branches have different types ({shown}); ThoughtSpot needs "
                        "one type for every branch")
            return None
        return unify([t for _v, t in values])

    def _call(self, node: dict) -> Optional[str]:
        fn, args = node["fn"], node["args"]
        types = [self.infer(a) for a in args]
        sig = SIGNATURES.get(fn)
        if sig is None:
            return None
        fixed, variadic, ret = sig
        for i, (a, t) in enumerate(zip(args, types)):
            kind = fixed[i] if i < len(fixed) else variadic
            if kind is not None and a.get("kind") != "template":
                self._want(a, t, kind, f"{fn} argument {i + 1}")
        if ret == "same":
            self._same(fn, args, types)
        return _returns(ret, types)

    def _same(self, fn: str, args: list, types: list) -> None:
        if len(types) != 2 or None in types or "null" in types:
            return
        if _family(types[0]) != _family(types[1]):
            self._error(f"{fn} needs both arguments of one type; "
                        f"`{T.to_text(args[1])}` is {_article(types[1])}, "
                        f"`{T.to_text(args[0])}` is {_article(types[0])}")


def _returns(ret, types: list) -> Optional[str]:
    if ret == "arg0":
        return types[0] if types else None
    if ret == "arg1":
        return types[1] if len(types) > 1 else None
    if ret in ("same", "numeric"):
        return unify(types)
    return ret


def _article(t: Optional[str]) -> str:
    return {"int": "an integer", "double": "a DOUBLE", "number": "a number", "text": "Text",
            "date": "a Date", "datetime": "a DateTime", "bool": "a Boolean",
            "null": "null"}.get(t, str(t))


def check(node: dict, column_type: Callable[[dict], Optional[str]]):
    """``(errors, unknown)`` for ``node`` — see ``Checker``."""
    c = Checker(column_type)
    c.infer(node)
    return c.errors, c.unknown


def infer(node: dict, column_type: Callable[[dict], Optional[str]]) -> Optional[str]:
    """The type of ``node`` alone (errors discarded)."""
    return Checker(column_type).infer(node)
