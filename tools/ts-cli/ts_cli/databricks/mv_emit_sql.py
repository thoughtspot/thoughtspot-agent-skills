"""dict-AST -> Databricks-SQL string (reverse direction). Pure: stdlib only.

Authoritative mapping source:
  agents/shared/mappings/ts-databricks/ts-databricks-formula-translation.md
"""
from __future__ import annotations
from typing import Callable

from ts_cli.databricks.mv_emit_expr import UntranslatableError

# TS aggregate fn -> Databricks aggregate fn
AGG_MAP = {
    "sum": "SUM", "average": "AVG", "avg": "AVG", "count": "COUNT",
    "min": "MIN", "max": "MAX", "stddev": "STDDEV", "variance": "VARIANCE",
    "median": "MEDIAN",
}
# unique count -> COUNT(DISTINCT ...) handled specially (two-word fn tokenised as one ident "unique count")
# TS scalar fn -> Databricks scalar fn (direct rename, same arg order)
SCALAR_FN_MAP = {
    "concat": "CONCAT", "greatest": "GREATEST", "least": "LEAST",
    "upper": "UPPER", "lower": "LOWER", "abs": "ABS", "round": "ROUND",
    "length": "LENGTH", "trim": "TRIM", "strlen": "LENGTH",
}
# TS sql_*_op pass-through wrappers -> unwrap, emit inner as raw SQL string literal arg
PASSTHROUGH_FN = {"sql_int_op", "sql_bool_op", "sql_str_op", "sql_string_op",
                  "sql_number_op", "sql_date_op", "sql_datetime_op"}
# TS conditional-aggregate fns -> (dbx agg, is_distinct)
COND_AGG = {
    "sum_if": ("SUM", False), "count_if": ("COUNT", False),
    "unique_count_if": ("COUNT", True), "average_if": ("AVG", False),
    "min_if": ("MIN", False), "max_if": ("MAX", False),
    "stddev_if": ("STDDEV", False), "variance_if": ("VARIANCE", False),
}
_OP_SQL = {"=": "=", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">=",
           "+": "+", "-": "-", "*": "*", "/": "/", "and": "AND", "or": "OR"}
# operator precedence, low -> high (used to decide when a child expression
# needs re-parenthesizing so the emitted SQL preserves the AST's semantics)
_PREC = {"or": 1, "and": 2,
         "=": 3, "!=": 3, "<": 3, "<=": 3, ">": 3, ">=": 3,
         "+": 4, "-": 4, "*": 5, "/": 5}
_UNARY_PREC = 6
_ATOMIC_PREC = 7  # col/ref/lit/call/ifelse: self-delimiting, never wrapped


def emit_sql(node: dict, resolver: Callable[[dict], str]) -> str:
    kind = node["node"]
    if kind == "col":
        return resolver(node)
    if kind == "ref":
        raise UntranslatableError(f"unresolved reference [{node['name']}]")
    if kind == "lit":
        return _emit_lit(node)
    if kind == "unop":
        return _emit_unop(node, resolver)
    if kind == "binop":
        return _emit_binop(node, resolver)
    if kind == "ifelse":
        return _emit_case(node, resolver)
    if kind == "call":
        return _emit_call(node, resolver)
    raise UntranslatableError(f"cannot emit node {kind!r}")


def _precedence(node: dict) -> int:
    kind = node["node"]
    if kind == "binop":
        return _PREC[node["op"]]
    if kind == "unop":
        return _UNARY_PREC
    return _ATOMIC_PREC  # col, ref, lit, call, ifelse are atomic


def _emit_unop(node: dict, resolver) -> str:
    inner = emit_sql(node["operand"], resolver)
    if node["operand"]["node"] == "binop":
        inner = f"({inner})"
    if node["op"] == "not":
        return f"NOT {inner}"
    # Nested unary minus (double negation, e.g. `-(-[T::x])` or `- -[T::x]`)
    # would otherwise concatenate to `--source.x`, which Databricks SQL parses
    # as a line comment and silently corrupts the expression. Separate with a
    # space so it reads as `- -source.x` instead.
    if inner.startswith("-"):
        return f"- {inner}"
    return f"-{inner}"


def _emit_lit(node: dict) -> str:
    if node["kind"] == "null":
        return "NULL"
    if node["kind"] == "bool":
        return node["value"].upper()
    if node["kind"] == "raw":
        return node["value"]
    return node["value"]  # string keeps single quotes; number verbatim


def _emit_binop(node: dict, resolver) -> str:
    op = node["op"]
    # null comparison -> IS [NOT] NULL
    if op in ("=", "!=") and node["right"].get("node") == "lit" and node["right"]["kind"] == "null":
        left = emit_sql(node["left"], resolver)
        return f"{left} IS NULL" if op == "=" else f"{left} IS NOT NULL"
    parent_prec = _PREC[op]
    left = _emit_child(node["left"], resolver, parent_prec, is_right=False)
    right = _emit_child(node["right"], resolver, parent_prec, is_right=True, parent_op=op)
    return f"{left} {_OP_SQL[op]} {right}"


def _emit_child(node: dict, resolver, parent_prec: int, is_right: bool, parent_op: str = "") -> str:
    sql = emit_sql(node, resolver)
    child_prec = _precedence(node)
    needs_wrap = child_prec < parent_prec
    if is_right and not needs_wrap:
        # left-associative, non-commutative parent ops (- and /) must
        # re-parenthesize an equal-precedence right child: a - (b - c) != a - b - c
        needs_wrap = child_prec == parent_prec and parent_op in ("-", "/")
    return f"({sql})" if needs_wrap else sql


def _emit_case(node: dict, resolver) -> str:
    parts = ["CASE"]
    for cond, val in node["branches"]:
        parts.append(f"WHEN {emit_sql(cond, resolver)} THEN {emit_sql(val, resolver)}")
    if node["else"] is not None:
        parts.append(f"ELSE {emit_sql(node['else'], resolver)}")
    parts.append("END")
    return " ".join(parts)


def _emit_call(node: dict, resolver) -> str:
    fn = node["fn"]
    args = node["args"]
    if fn == "unique count":
        return f"COUNT(DISTINCT {emit_sql(args[0], resolver)})"
    if fn == "count" and _is_count_star(args):
        return "COUNT(*)"
    if fn in AGG_MAP:
        return f"{AGG_MAP[fn]}({emit_sql(args[0], resolver)})"
    if fn in COND_AGG:
        return _emit_cond_agg(fn, args, resolver)
    if fn in PASSTHROUGH_FN:
        return _emit_passthrough(fn, args)
    if fn in SCALAR_FN_MAP:
        inner = ", ".join(emit_sql(a, resolver) for a in args)
        return f"{SCALAR_FN_MAP[fn]}({inner})"
    handler = _SIMPLE_FN.get(fn)
    if handler is not None:
        return handler(args, resolver)
    raise UntranslatableError(f"no Databricks translation for function {fn!r}")


def _is_count_star(args: list) -> bool:
    return len(args) == 1 and args[0].get("node") == "lit" and args[0]["value"] == "1"


def _emit_cond_agg(fn: str, args: list, resolver) -> str:
    agg, distinct = COND_AGG[fn]
    cond, measure = args[0], args[1]
    inner = emit_sql(measure, resolver)
    body = f"DISTINCT {inner}" if distinct else inner
    return f"{agg}({body}) FILTER (WHERE {emit_sql(cond, resolver)})"


def _emit_passthrough(fn: str, args: list) -> str:
    if len(args) != 1:
        raise UntranslatableError(
            f"{fn} pass-through expects exactly one argument, got {len(args)}")
    raw = args[0]
    if raw.get("node") != "lit" or raw["kind"] != "string":
        raise UntranslatableError(f"{fn} pass-through expects a string literal")
    return raw["value"][1:-1].replace("''", "'")  # unwrap the SQL string


def _emit_safe_divide(args: list, resolver) -> str:
    numerator = emit_sql(args[0], resolver)
    # numerator sits left of the implicit `/` -> wrap if it's a binop
    # (precedence <= 5, i.e. any binop); the denominator is inside
    # NULLIF(x, 0), a function-arg context that needs no extra wrapping.
    if args[0]["node"] == "binop":
        numerator = f"({numerator})"
    return f"COALESCE({numerator} / NULLIF({emit_sql(args[1], resolver)}, 0), 0)"


def _emit_if_null(args: list, resolver) -> str:
    return f"COALESCE({emit_sql(args[0], resolver)}, {emit_sql(args[1], resolver)})"


def _emit_zero_if_null(args: list, resolver) -> str:
    return f"COALESCE({emit_sql(args[0], resolver)}, 0)"


def _emit_null_if_zero(args: list, resolver) -> str:
    return f"NULLIF({emit_sql(args[0], resolver)}, 0)"


def _emit_isnull(args: list, resolver) -> str:
    return f"{emit_sql(args[0], resolver)} IS NULL"


def _emit_if_fn(args: list, resolver) -> str:
    # if(cond, then, else) function form
    return _emit_case({"node": "ifelse", "branches": [[args[0], args[1]]],
                       "else": args[2] if len(args) > 2 else None}, resolver)


def _emit_in(args: list, resolver) -> str:
    head = emit_sql(args[0], resolver)
    vals = ", ".join(emit_sql(a, resolver) for a in args[1:])
    return f"{head} IN ({vals})"


def _emit_between(args: list, resolver) -> str:
    return f"{emit_sql(args[0], resolver)} BETWEEN {emit_sql(args[1], resolver)} AND {emit_sql(args[2], resolver)}"


# fns with a single fixed-shape translation, dispatched by name (keeps
# _emit_call's cyclomatic complexity under the repo's module-health CAP)
_SIMPLE_FN: dict = {
    "safe_divide": _emit_safe_divide,
    "if_null": _emit_if_null,
    "ifnull": _emit_if_null,
    "zero_if_null": _emit_zero_if_null,
    "null_if_zero": _emit_null_if_zero,
    "isnull": _emit_isnull,
    "if": _emit_if_fn,
    "in": _emit_in,
    "between": _emit_between,
}


# --- Raw-measure aggregation wrapper (Task 18 Finding 1 fix) ---------------
# A formula-backed MEASURE whose translated SQL contains no aggregate at all
# (e.g. safe_divide over two RAW physical-column refs) is what
# `ts spotql classify-columns` calls a "raw_measure": ThoughtSpot itself
# treats it as an unaggregated per-row expression and applies the column's
# declared aggregation (SUM by default) at query time. Databricks has no such
# implicit behavior -- CREATE VIEW rejects the un-aggregated expression with
# MISSING_AGGREGATION. mv_emit.emit_measure calls these two helpers to match
# ThoughtSpot's own semantics; kept here (not in mv_emit.py) because this
# module already owns AGG_MAP/the aggregate-keyword knowledge.
_AGG_PRESENCE_TOKENS = (
    "SUM(", "COUNT(", "AVG(", "MIN(", "MAX(", "STDDEV(", "VARIANCE(",
    "MEDIAN(", "MEASURE(", "ANY_VALUE(",
)


def is_aggregate_present(sql: str) -> bool:
    """True if an aggregate function call or window `OVER` clause appears
    ANYWHERE in `sql` -- presence-based, not "the outermost AST node is an
    aggregate call". A cross-measure ref like
    `COALESCE(MEASURE(quantity) / NULLIF(ANY_VALUE(category_quantity), 0), 0)`
    already aggregates via its resolved MEASURE()/ANY_VALUE() refs even
    though its own outermost call is `safe_divide`/`COALESCE`, neither of
    which is itself an aggregate function -- this distinguishes that case
    (already aggregated, leave as-is) from a bare `safe_divide` over two
    RAW physical-column refs (no aggregate anywhere, must be wrapped).
    """
    if not sql:
        return False
    if " OVER " in sql or "OVER(" in sql:
        return True
    return any(token in sql for token in _AGG_PRESENCE_TOKENS)


# aggregation property -> Databricks aggregate keyword, for wrapping a
# no-aggregate formula-measure expr. Mirrors mv_emit.py's own
# `_PROP_AGG_TO_DBX` (kept as a separate copy here, not imported, to avoid a
# mv_emit_sql.py -> mv_emit.py dependency; both derive from this module's own
# AGG_MAP, the shared source of truth).
_WRAP_AGG_TO_DBX = {
    "SUM": AGG_MAP["sum"], "COUNT": AGG_MAP["count"], "AVERAGE": AGG_MAP["average"],
    "AVG": AGG_MAP["avg"], "MIN": AGG_MAP["min"], "MAX": AGG_MAP["max"],
    "STD_DEVIATION": AGG_MAP["stddev"], "STDDEV": AGG_MAP["stddev"],
    "VARIANCE": AGG_MAP["variance"],
}


def wrap_in_aggregation(sql: str, aggregation: str | None) -> str:
    """Wrap `sql` in the Databricks aggregate keyword for `aggregation`
    (ThoughtSpot's `properties.aggregation`, default SUM) -- the same AGG
    semantics `mv_emit._physical_measure_expr` applies to a physical column's
    dot-path, generalized here to any already-translated SQL string.
    """
    agg = (aggregation or "SUM").upper()
    if agg == "COUNT_DISTINCT":
        return f"COUNT(DISTINCT {sql})"
    dbx_agg = _WRAP_AGG_TO_DBX.get(agg)
    if dbx_agg is None:
        raise UntranslatableError(f"unknown aggregation {aggregation!r} on formula measure")
    return f"{dbx_agg}({sql})"


def wrap_measure_if_needed(sql: str, aggregation: str | None) -> str:
    """Convenience combinator over the two helpers above: wrap `sql` in
    `aggregation` only when it has no aggregate present already; otherwise
    return it unchanged. Lets mv_emit.emit_measure's formula branch stay a
    single call while `is_aggregate_present`/`wrap_in_aggregation` remain
    independently unit-testable.
    """
    return sql if is_aggregate_present(sql) else wrap_in_aggregation(sql, aggregation)
