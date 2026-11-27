"""BL-638: a dimension comparing a row to a whole-table LOD dimension.

`is_latest: period = latest_period`, where `latest_period` is `MAX(period) OVER ()`,
would translate to `[formula_Period] = [formula_Latest Period]` over a
`group_aggregate ( … , { } , { } )`. That imports, but ThoughtSpot's SQL for the flag
is wrong: grouped on, the flag's CTE has no GROUP BY and the join fans out; filtered
on, first_value/last_value are partitioned by the period (live, 2026-11-26). So the
flag is emitted as a scalar subquery in a pass-through instead, which matched the
Metric View in every shape tried:

    sql_bool_op ( "{0} = (SELECT MAX(<expr>) FROM <source fqn> WHERE <MV filter>)" , [formula_Period] )
"""
from __future__ import annotations

import re

from ts_cli.databricks.mv_expr import mask_string_literals, split_dot_path
from ts_cli.sql_forms import strip_sql_comments
from ts_cli.databricks.mv_sql import UntranslatableError

_CMP_OPS = ("<=", ">=", "<>", "!=", "=", "<", ">")
_SEG = r"(?:`[^`]+`|[A-Za-z_][\w$]*)"
_NAME_RE = re.compile(rf"{_SEG}(?:\.{_SEG})*")
_FIRST_SEG_RE = re.compile(_SEG)
# An operator that binds looser than a comparison, or is a predicate of its own: on
# the non-latest side it would regroup the comparison inside the template.
_LOOSE_KW_RE = re.compile(r"\b(AND|OR|NOT|IS|IN|BETWEEN|LIKE|RLIKE|ILIKE)\b", re.IGNORECASE)
_SQL_AGGS = {"MAX", "MIN"}

PASSTHROUGH_NOTE = (
    "compares a row to the whole-table '{lod}' through a scalar subquery "
    "(sql_bool_op), because ThoughtSpot's SQL for a row-vs-group_aggregate flag is "
    "wrong (BL-638). The subquery names the source table and repeats the MV filter as "
    "text: edit it per environment, and lineage does not see it.")


def whole_table_lods(parsed: dict) -> dict[str, dict]:
    """casefolded name -> parsed dimension, for every `AGG(expr) OVER ()` dimension."""
    return {str(d["name"]).casefold(): d for d in parsed["dimensions"]
            if d["kind"] == "lod_window" and not d["partition_by"]}


def clean_sql(sql: str) -> str:
    """Comments stripped, and newlines outside string literals made spaces, so the
    text can sit on one line inside a sql_bool_op template."""
    sql = strip_sql_comments(sql)
    masked = mask_string_literals(sql)
    return "".join(" " if m in "\r\n" else c for c, m in zip(sql, masked)).strip()


def _strip_parens(s: str) -> str:
    """`(x)` -> `x` while the outer parentheses wrap the whole text."""
    while s.startswith("(") and s.endswith(")"):
        masked, depth = mask_string_literals(s), 0
        for i, ch in enumerate(masked):
            depth += {"(": 1, ")": -1}.get(ch, 0)
            if depth == 0 and i < len(s) - 1:
                return s
        s = s[1:-1].strip()
    return s


def _bare_names(sql: str) -> list[tuple[int, int, str]]:
    """(start, end, name) of every identifier path outside string literals that is
    not a function call."""
    masked = mask_string_literals(sql)
    out = []
    for m in _NAME_RE.finditer(masked):
        rest = masked[m.end():].lstrip()
        if rest.startswith("("):
            continue
        if m.start() and (masked[m.start() - 1].isalnum() or masked[m.start() - 1] in "_$"):
            continue
        out.append((m.start(), m.end(), sql[m.start():m.end()]))
    return out


def _unquote(seg: str) -> str:
    return seg[1:-1] if seg.startswith("`") else seg


def names_in(expr: str) -> list[str]:
    """Every unqualified (single-segment) name in an expression, unquoted."""
    return [_unquote(name) for _, _, name in _bare_names(clean_sql(expr))
            if len(split_dot_path(name)) == 1]


def references(expr: str, lods: dict[str, dict]) -> list[str]:
    """Names of the whole-table LOD dimensions an expression references unqualified."""
    found = []
    for _, _, name in _bare_names(clean_sql(expr)):
        segs = split_dot_path(name)
        if len(segs) == 1 and _unquote(segs[0]).casefold() in lods:
            found.append(_unquote(segs[0]).casefold())
    return found


def _split_comparison(expr: str) -> tuple[str, str, str]:
    expr = _strip_parens(clean_sql(expr))
    masked = mask_string_literals(expr)
    depth, hits, i = 0, [], 0
    while i < len(masked):
        ch = masked[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            op = next((o for o in _CMP_OPS if masked.startswith(o, i)), None)
            if op:
                hits.append((i, op))
                i += len(op)
                continue
        i += 1
    if len(hits) != 1:
        raise UntranslatableError("not a single comparison")
    pos, op = hits[0]
    return _strip_parens(expr[:pos].strip()), op, _strip_parens(expr[pos + len(op):].strip())


def _source_sql(sql: str, what: str) -> str:
    """`sql` with the root alias dropped (`source.X` -> `X`), so it reads the source
    table directly. Refused when it names a joined table."""
    out, last = [], 0
    for start, end, name in _bare_names(sql):
        segs = split_dot_path(name)
        if len(segs) == 1:
            continue
        if len(segs) == 2 and _unquote(segs[0]).casefold() == "source":
            out.append(sql[last:start])
            first = _FIRST_SEG_RE.match(name)
            out.append(name[first.end() + 1:])  # the column as written, backticks kept
            last = end
            continue
        raise UntranslatableError(
            f"{what} names '{name}', not a source column: the subquery reads the "
            f"source table only")
    out.append(sql[last:])
    return "".join(out).strip()


def _sides(dim: dict, lods: dict[str, dict], why: str) -> tuple[str, str, str, bool]:
    """(op, the other operand, the latest dimension's casefolded name, whether the
    latest dimension is on the right)."""
    try:
        left, op, right = _split_comparison(dim["expr"])
    except UntranslatableError:
        raise UntranslatableError(
            f"{why} is not a single comparison `<expr> <op> <latest dimension>`, the "
            f"one shape emitted as a subquery") from None
    side = [s for s in (left, right)
            if len(split_dot_path(s)) == 1 and _unquote(s).casefold() in lods]
    on_right = bool(side) and side[0] == right
    other = left if on_right else right
    if len(side) != 1 or references(other, lods) or _LOOSE_KW_RE.search(
            mask_string_literals(other)):
        raise UntranslatableError(
            f"{why} does not compare one plain expression to one latest dimension")
    return op, other, _unquote(side[0]).casefold(), on_right


def _subquery(lod: dict, parsed: dict, why: str) -> str:
    if lod["inner_agg"] not in _SQL_AGGS:
        raise UntranslatableError(
            f"{why} uses {lod['inner_agg']}, and only MAX/MIN latest dimensions are "
            f"emitted as a subquery")
    src = parsed.get("source") or {}
    if src.get("kind") != "table_fqn" or len(split_dot_path(src.get("raw") or "")) != 3:
        raise UntranslatableError(
            f"{why} needs a three-part catalog.schema.table source: the subquery runs "
            f"on ThoughtSpot's connection, where a shorter name resolves elsewhere")
    try:
        inner = _source_sql(clean_sql(lod["inner_expr"]), "the latest dimension")
        sql = f"SELECT {lod['inner_agg']}({inner}) FROM {src['raw']}"
        if parsed.get("filter"):
            sql += f" WHERE {_source_sql(clean_sql(parsed['filter']), 'the MV filter')}"
    except UntranslatableError as exc:
        raise UntranslatableError(f"{why} cannot be a subquery: {exc}") from None
    if any(c in sql for c in '"{}\\'):
        # as formula_common / sql_forms refuse: ThoughtSpot strips a backslash in a
        # sql_*_op template (live, docs/reviews/2026-10-06-formula-semantics-probes.md)
        raise UntranslatableError(
            f"{why} has a double quote, brace or backslash in its SQL, which a "
            f"sql_bool_op template cannot carry")
    return sql


def translate_latest_period_flag(dim: dict, parsed: dict, lods: dict[str, dict],
                                 operand_ts) -> str:
    """The sql_bool_op formula for `dim`, or UntranslatableError (the skip reason
    says why). operand_ts translates the non-LOD side to a ThoughtSpot expression."""
    why = (f"dimension '{dim['name']}' compares to a whole-table OVER () dimension; "
           f"the group_aggregate comparison gives wrong numbers in ThoughtSpot (BL-638) "
           f"and it")
    op, other, name, on_right = _sides(dim, lods, why)
    sql = _subquery(lods[name], parsed, why)
    lhs, rhs = ("{0}", f"({sql})") if on_right else (f"({sql})", "{0}")
    return f'sql_bool_op ( "{lhs} {op} {rhs}" , {operand_ts(other)} )'
