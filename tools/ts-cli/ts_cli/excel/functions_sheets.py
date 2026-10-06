"""Google Sheets delta handlers (the Sheets map). Every other Sheets name takes its Excel
handler (Sheets map E1)."""
from __future__ import annotations

import re

from ts_cli.excel import nodes as X
from ts_cli.excel import tsast as T
from ts_cli.excel.functions_logic import _error_sources, _with_mode
from ts_cli.excel.functions_text import _concat
from ts_cli.excel.helpers import is_range, need, template
from ts_cli.excel.map_index import cite

_REDUCERS = {"SUM", "SUMIF", "SUMIFS", "COUNT", "COUNTA", "COUNTIF", "COUNTIFS", "AVERAGE",
             "AVERAGEIF", "AVERAGEIFS", "MAX", "MIN", "AND", "OR", "COUNTUNIQUE", "TEXTJOIN",
             "JOIN", "MEDIAN"}


def _binary(op: str):
    def handler(tr, n):
        need(tr, n, 2, 2)
        return tr.expr(X.Binary(op, n.args[0], n.args[1]))
    return handler


def _uminus(tr, n):
    need(tr, n, 1, 1)
    return T.unop("-", tr.expr(n.args[0]))


def _uplus(tr, n):
    need(tr, n, 1, 1)
    return tr.expr(n.args[0])


def _unary_percent(tr, n):
    need(tr, n, 1, 1)
    return T.binop("/", tr.expr(n.args[0]), T.lit_number("100"))


def _pow(tr, n):
    need(tr, n, 2, 2)
    return T.call("pow", tr.expr(n.args[0]), tr.expr(n.args[1]))


def _query(tr, n):
    tr.review(f"QUERY is structural — {cite('QUERY', 'google_sheets')}: its select / where / "
              "group by / order by become the Answer's columns, filters, attributes and sort, "
              "not a formula; its string matching is case-sensitive where ThoughtSpot's is not")


def _arrayformula(tr, n):
    need(tr, n, 1, 1)
    inner = n.args[0]
    reducers = {x.name for x in X.walk(inner) if isinstance(x, X.Call)} & _REDUCERS
    if reducers:
        tr.review(f"ARRAYFORMULA around {', '.join(sorted(reducers))} is not element-wise: "
                  "a per-row COUNTIF / SUMIF is a fixed-grain group_aggregate and AND / OR "
                  f"collapse to one value — {cite('ARRAYFORMULA', 'google_sheets')}")
    tr.note("ARRAYFORMULA is a no-op around an element-wise expression: a Model formula is "
            "already evaluated per row (Sheets map E6)")
    saved, tr.elementwise = tr.elementwise, True
    try:
        return tr.expr(inner)
    finally:
        tr.elementwise = saved


def _iferror(tr, n):
    need(tr, n, 1, 2)
    if len(n.args) == 2:
        from ts_cli.excel.functions_logic import _iferror as excel_iferror
        return excel_iferror(tr, n)
    value = n.args[0]
    divisions, others = _error_sources(value)
    if divisions and not others:
        tr.note("one-argument IFERROR is blank by default: a division becomes plain / , which "
                "returns NULL on a zero divisor (probe record §7) — never safe_divide (0)")
        return _with_mode(tr, value, "plain")
    if others:
        tr.review(f"one-argument IFERROR around {', '.join(sorted(others))}: no map rule — "
                  f"{cite('IFERROR', 'google_sheets')}")
    tr.note("one-argument IFERROR around a conversion: a failed to_double / to_date is "
            "already NULL, the blank Sheets returns (Sheets map IFERROR row)")
    return tr.expr(value)


def _countunique(tr, n):
    if len(n.args) != 1 or not is_range(n.args[0]):
        tr.review("COUNTUNIQUE over several ranges counts distinct values across them — no "
                  "single-column form (Sheets map COUNTUNIQUE row)")
    with tr.aggregate():
        return T.call("unique count", tr.expr(n.args[0]))


def _regex(kind: str):
    def handler(tr, n):
        tr.note(f"{n.name} passes through as a Snowflake regex (RE2 → POSIX dialect differences: "
                "no look-arounds or lazy quantifiers)")
        if kind == "match":
            need(tr, n, 2, 2)
            return T.call("sql_bool_op", template("REGEXP_INSTR({0}, {1}) > 0"),
                          tr.expr(n.args[0]), tr.expr(n.args[1]))
        if kind == "replace":
            need(tr, n, 3, 3)
            return T.call("sql_string_op", template("REGEXP_REPLACE({0}, {1}, {2})"),
                          *[tr.expr(a) for a in n.args])
        need(tr, n, 2, 2)
        sql = _extract_template(tr, n.args[1])
        return T.call("sql_string_op", template(sql), tr.expr(n.args[0]), tr.expr(n.args[1]))
    return handler


def _extract_template(tr, pattern) -> str:
    if not isinstance(pattern, X.Str):
        tr.review("REGEXEXTRACT with a non-literal pattern: its capture groups decide the "
                  "result, so the pattern must be known")
    groups = len(re.findall(r"(?<!\\)\((?!\?)", pattern.value))
    if groups == 0:
        return "REGEXP_SUBSTR({0}, {1})"
    if groups == 1:
        return "REGEXP_SUBSTR({0}, {1}, 1, 1, 'e', 1)"
    tr.review("REGEXEXTRACT with several capture groups spills one column per group — one "
              "formula per group (Sheets map REGEXEXTRACT row)")


SHEETS_HANDLERS = {
    "ADD": _binary("+"), "MINUS": _binary("-"), "MULTIPLY": _binary("*"),
    "DIVIDE": _binary("/"), "EQ": _binary("="), "NE": _binary("<>"), "GT": _binary(">"),
    "GTE": _binary(">="), "LT": _binary("<"), "LTE": _binary("<="),
    "UMINUS": _uminus, "UPLUS": _uplus, "UNARY_PERCENT": _unary_percent, "POW": _pow,
    "CONCAT": _concat, "QUERY": _query, "ARRAYFORMULA": _arrayformula, "IFERROR": _iferror,
    "COUNTUNIQUE": _countunique, "REGEXMATCH": _regex("match"),
    "REGEXEXTRACT": _regex("extract"), "REGEXREPLACE": _regex("replace"),
}
