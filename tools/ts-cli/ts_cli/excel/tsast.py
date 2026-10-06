"""ThoughtSpot formula AST: constructors, the canonical-spacing printer, type inference.

The node shape is ``ts_cli.databricks.mv_emit_expr.parse_formula``'s dict-AST, so the reverse
direction (and the tests' normaliser) parse ThoughtSpot text with that ONE parser instead of a
second one (BL-217):

- ``{"node": "binop", "op", "left", "right"}`` — ``or and = != < <= > >= + - * /``
- ``{"node": "unop", "op": "not" | "-", "operand"}``
- ``{"node": "call", "fn", "args"}`` — ``fn`` lower case; ``unique count`` keeps its space;
  ``in`` / ``between`` are calls whose first argument is the tested value
- ``{"node": "lit", "kind": "string" | "number" | "null" | "bool", "value"}`` — a string's
  ``value`` keeps its single quotes
- ``{"node": "col", "table", "column"}`` (``[T::c]``) and ``{"node": "ref", "name"}`` (``[x]``)
- ``{"node": "ifelse", "branches": [[cond, value]], "else"}``
- ``{"node": "lodset", "cols"}`` — ``{ a , b }``

``to_text`` prints the canonical spacing the formula reference uses (``concat ( [a] , 'b' )``,
``if ( c ) then a else b``) and adds parentheses only where precedence needs them.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

_PREC = {"or": 1, "and": 2, "=": 4, "!=": 4, "<": 4, "<=": 4, ">": 4, ">=": 4,
         "+": 5, "-": 5, "*": 6, "/": 6}
_PRIMARY = 9


def lit_string(value: str) -> dict:
    return {"node": "lit", "kind": "string", "value": "'" + value.replace("'", "''") + "'"}


def lit_number(text: str) -> dict:
    return {"node": "lit", "kind": "number", "value": canonical_number(text)}


def lit_null() -> dict:
    return {"node": "lit", "kind": "null", "value": "null"}


def lit_bool(value: bool) -> dict:
    return {"node": "lit", "kind": "bool", "value": "true" if value else "false"}


def call(fn: str, *args: dict) -> dict:
    return {"node": "call", "fn": fn, "args": list(args)}


def binop(op: str, left: dict, right: dict) -> dict:
    return {"node": "binop", "op": op, "left": left, "right": right}


def unop(op: str, operand: dict) -> dict:
    return {"node": "unop", "op": op, "operand": operand}


def ifelse(cond: dict, then: dict, other: Optional[dict]) -> dict:
    """``if ( cond ) then … else …``; an ``ifelse`` in ``other`` chains as ``else if``."""
    return {"node": "ifelse", "branches": [[cond, then]], "else": other}


def ref_node(text: str) -> dict:
    """A resolved reference's text (``[T::c]`` / ``[x]``) as a node."""
    inner = text.strip()[1:-1]
    if "::" in inner:
        t, c = inner.split("::", 1)
        return {"node": "col", "table": t.strip(), "column": c.strip()}
    return {"node": "ref", "name": inner.strip()}


def canonical_number(text: str) -> str:
    """``.5`` → ``0.5``, ``1E3`` → ``1000``; an integer stays an integer."""
    try:
        d = Decimal(text)
    except InvalidOperation:
        return text
    if d == d.to_integral_value() and "e" not in text.lower() and "." not in text:
        return str(int(d))
    out = format(d.normalize(), "f")
    return out if out not in ("-0",) else "0"


def is_lit(node: dict, kind: Optional[str] = None, value: Optional[str] = None) -> bool:
    if node.get("node") != "lit":
        return False
    if kind and node["kind"] != kind:
        return False
    return value is None or node["value"] == value


def number_value(node: dict) -> Optional[Decimal]:
    if is_lit(node, "number"):
        try:
            return Decimal(node["value"])
        except InvalidOperation:
            return None
    if node.get("node") == "unop" and node["op"] == "-":
        v = number_value(node["operand"])
        return -v if v is not None else None
    return None


def children(node: dict) -> list[dict]:
    kind = node.get("node")
    if kind == "binop":
        return [node["left"], node["right"]]
    if kind == "unop":
        return [node["operand"]]
    if kind == "call":
        return list(node["args"])
    if kind == "ifelse":
        out = [x for b in node["branches"] for x in b]
        return out + ([node["else"]] if node.get("else") is not None else [])
    if kind == "lodset":
        return list(node["cols"])
    return []


def walk(node: dict):
    yield node
    for c in children(node):
        yield from walk(c)


def has_column(node: dict) -> bool:
    return any(n.get("node") in ("col", "ref") for n in walk(node))


AGGREGATES = frozenset({
    "sum", "average", "count", "min", "max", "median", "stddev", "variance", "unique count",
    "sum_if", "count_if", "average_if", "min_if", "max_if", "unique_count_if", "stddev_if",
    "variance_if", "group_aggregate",
})


def is_aggregated(node: dict) -> bool:
    return any(n.get("node") == "call" and (n["fn"] in AGGREGATES or n["fn"].startswith(
        ("group_", "cumulative_", "moving_"))) for n in walk(node))


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------

def _prec(node: dict) -> int:
    kind = node.get("node")
    if kind == "binop":
        return _PREC[node["op"]]
    if kind == "ifelse":
        return 0
    if kind == "unop":
        return _PRIMARY if node["op"] == "not" else 7
    if kind == "call" and node["fn"] in ("in", "between"):
        return 4
    return _PRIMARY


def _wrap(node: dict, minimum: int) -> str:
    text = to_text(node)
    return f"( {text} )" if _prec(node) < minimum else text


def _call_text(node: dict) -> str:
    fn, args = node["fn"], node["args"]
    if fn == "in":
        items = " , ".join(to_text(a) for a in args[1:])
        return f"{_wrap(args[0], 5)} in {{ {items} }}"
    if fn == "between":
        return f"{_wrap(args[0], 5)} between {_wrap(args[1], 5)} and {_wrap(args[2], 5)}"
    if not args:
        return f"{fn} ( )"
    return f"{fn} ( " + " , ".join(to_text(a) for a in args) + " )"


def _ifelse_text(node: dict) -> str:
    parts = []
    for i, (cond, val) in enumerate(node["branches"]):
        parts.append(("if" if i == 0 else "else if") + f" ( {to_text(cond)} ) then {_wrap(val, 1)}")
    out = " ".join(parts)
    if node.get("else") is not None:
        out += f" else {to_text(node['else'])}"
    return out


def to_text(node: dict) -> str:
    """Canonical ThoughtSpot formula text for ``node``."""
    kind = node.get("node")
    if kind == "binop":
        p = _PREC[node["op"]]
        left_min = p + 1 if p == 4 else p  # a comparison inside a comparison is bracketed
        return f"{_wrap(node['left'], left_min)} {node['op']} {_wrap(node['right'], p + 1)}"
    if kind == "unop":
        if node["op"] == "not":
            return f"not ( {to_text(node['operand'])} )"
        return f"- {_wrap(node['operand'], 8)}"
    if kind == "call":
        return _call_text(node)
    if kind == "ifelse":
        return _ifelse_text(node)
    if kind == "lit":
        return node["value"]
    if kind == "col":
        return f"[{node['table']}::{node['column']}]"
    if kind == "ref":
        return f"[{node['name']}]"
    if kind == "lodset":
        return "{ " + " , ".join(to_text(c) for c in node["cols"]) + " }"
    raise ValueError(f"cannot print node {node!r}")


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

_TEXT_TYPES = {"VARCHAR", "CHAR", "TEXT", "STRING"}
_DATE_TYPES = {"DATE"}
_DATETIME_TYPES = {"DATE_TIME", "DATETIME", "TIMESTAMP", "TIMESTAMP_NTZ", "TIMESTAMP_TZ",
                   "TIMESTAMP_LTZ", "TIME"}
# Types that are a point in time: "date" (whole days) or "datetime" (with a time of day).
TEMPORAL = ("date", "datetime")
_NUM_TYPES = {"INT32", "INT64", "INTEGER", "INT", "BIGINT", "DOUBLE", "FLOAT", "DECIMAL",
              "NUMBER", "NUMERIC", "REAL"}
_FN_TYPES = {
    "text": {"concat", "to_string", "left", "right", "substr", "month", "day_of_week",
             "sql_string_op", "year_name"},
    "datetime": {"now", "sql_date_time_op"},
    "date": {"today", "add_days", "add_months", "add_years", "add_weeks", "to_date",
             "start_of_month", "start_of_year", "start_of_quarter", "start_of_week", "date",
             "sql_date_op"},
    "bool": {"contains", "isnull", "in", "between", "sql_bool_op", "is_weekend"},
}


def type_of_data_type(data_type: Optional[str]) -> Optional[str]:
    dt = (data_type or "").upper()
    if dt in _TEXT_TYPES:
        return "text"
    if dt in _DATE_TYPES:
        return "date"
    if dt in _DATETIME_TYPES:
        return "datetime"
    if dt in _NUM_TYPES:
        return "number"
    if dt in ("BOOL", "BOOLEAN"):
        return "bool"
    return None


def _ifelse_type(node: dict, column_type) -> Optional[str]:
    types = {type_of(v, column_type) for _c, v in node["branches"]}
    if node.get("else") is not None and not is_lit(node["else"], "null"):
        types.add(type_of(node["else"], column_type))
    types.discard(None)
    return types.pop() if len(types) == 1 else None


def _call_type(node: dict, column_type) -> Optional[str]:
    if node["fn"] in ("add_days", "add_months", "add_years", "add_weeks") and node["args"]:
        first = type_of(node["args"][0], column_type)
        return first if first in TEMPORAL else "date"
    for t, fns in _FN_TYPES.items():
        if node["fn"] in fns:
            return t
    if node["fn"] in ("ifnull", "greatest", "least"):
        return type_of(node["args"][0], column_type)
    return "number"


_LIT_TYPES = {"string": "text", "number": "number", "bool": "bool"}


def type_of(node: dict, column_type) -> Optional[str]:
    """``"text" | "number" | "date" | "bool"`` or None (unknown). ``column_type(node)`` gives
    a reference's type from the column context."""
    kind = node.get("node")
    if kind == "lit":
        return _LIT_TYPES.get(node["kind"])
    if kind in ("col", "ref"):
        return column_type(node)
    if kind == "binop":
        return "bool" if _PREC[node["op"]] <= 4 else "number"
    if kind == "unop":
        return "bool" if node["op"] == "not" else "number"
    if kind == "ifelse":
        return _ifelse_type(node, column_type)
    if kind == "call":
        return _call_type(node, column_type)
    return None


def walk_any(value: Any):
    """Yield every dict node in a value that may be a list of nodes."""
    if isinstance(value, dict):
        yield from walk(value)
    elif isinstance(value, list):
        for v in value:
            yield from walk_any(v)
