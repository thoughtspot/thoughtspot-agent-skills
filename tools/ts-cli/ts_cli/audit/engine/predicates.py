"""`where` / `match` expressions.

    {field: <path>, <op>: <operand>, ...}    every listed operator must hold (AND)
    {all: [expr, ...]}  {any: [expr, ...]}  {not: expr}
    {count: <scope>, where: expr, gt: n}    how many `scope` items under this item
                                            pass `where`, compared like a field

Operator semantics are documented (and their operands validated) in
`ts_cli/audit/catalog_expr.py`; this module implements exactly that table.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict

from ts_cli.audit.engine import fields, scopes

_NUMERIC = (int, float)


def _is_number(v: Any) -> bool:
    return isinstance(v, _NUMERIC) and not isinstance(v, bool)


def equals(a: Any, b: Any) -> bool:
    """Scalar equality where a boolean never equals a number (True != 1)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    return a == b


def _blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, tuple, dict, set)):
        return len(v) == 0
    return False


def _length(v: Any):
    if v is None:
        return 0
    return len(v) if isinstance(v, (str, list, tuple, dict, set)) else None


def _compare(cmp: Callable[[Any, Any], bool]) -> Callable[[Any, Any], bool]:
    return lambda v, n: _is_number(v) and cmp(v, n)


def _compare_len(cmp: Callable[[Any, Any], bool]) -> Callable[[Any, Any], bool]:
    def check(v: Any, n: Any) -> bool:
        length = _length(v)
        return length is not None and cmp(length, n)
    return check


def _contains(v: Any, operand: Any) -> bool:
    if isinstance(v, str):
        return isinstance(operand, str) and operand in v
    if isinstance(v, (list, tuple, set)):
        return any(equals(x, operand) for x in v)
    return False


def _regex(v: Any, pattern: str) -> bool:
    return isinstance(v, str) and re.search(pattern, v) is not None


LEAF: Dict[str, Callable[[Any, Any], bool]] = {
    "eq": equals,
    "in": lambda v, options: any(equals(v, o) for o in options),
    "regex": _regex,
    "not_regex": lambda v, p: not _regex(v, p),
    "exists": lambda v, want: (v is not None) is want,
    "nonblank": lambda v, want: (not _blank(v)) is want,
    "truthy": lambda v, want: bool(v) is want,
    "gt": _compare(lambda a, b: a > b),
    "gte": _compare(lambda a, b: a >= b),
    "lt": _compare(lambda a, b: a < b),
    "lte": _compare(lambda a, b: a <= b),
    "len_gt": _compare_len(lambda a, b: a > b),
    "len_lt": _compare_len(lambda a, b: a < b),
    "contains": _contains,
}
_STRUCTURE = {"field", "count", "where"}


def evaluate(expr: dict, item: dict, ctx) -> bool:
    """Whether `item` satisfies `expr`."""
    if "all" in expr:
        return all(evaluate(e, item, ctx) for e in expr["all"])
    if "any" in expr:
        return any(evaluate(e, item, ctx) for e in expr["any"])
    if "not" in expr:
        return not evaluate(expr["not"], item, ctx)
    unknown = [k for k in expr if k not in LEAF and k not in _STRUCTURE]
    if unknown:
        raise ValueError(f"unknown operator(s) {unknown} in {expr!r}")
    value = _count(expr, item, ctx) if "count" in expr else fields.get(item, expr["field"], ctx)
    return all(LEAF[op](value, operand) for op, operand in expr.items() if op in LEAF)


def _count(expr: dict, item: dict, ctx) -> int:
    where = expr.get("where")
    return sum(1 for child in scopes.iterate(ctx, expr["count"], parent=item)
               if where is None or evaluate(where, child, ctx))


def passes(expr: Any, item: dict, ctx) -> bool:
    """`evaluate`, treating an absent expression as always true."""
    return True if not expr else evaluate(expr, item, ctx)
