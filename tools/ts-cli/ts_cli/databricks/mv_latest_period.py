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
from ts_cli.databricks.mv_sql import UntranslatableError

_CMP_OPS = ("<=", ">=", "<>", "!=", "=", "<", ">")
_NAME_RE = re.compile(r"`[^`]+`|[A-Za-z_][\w$]*(?:\.(?:`[^`]+`|[A-Za-z_][\w$]*))*")
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


def references(expr: str, lods: dict[str, dict]) -> list[str]:
    """Names of the whole-table LOD dimensions an expression references unqualified."""
    found = []
    for _, _, name in _bare_names(expr):
        segs = split_dot_path(name)
        if len(segs) == 1 and _unquote(segs[0]).casefold() in lods:
            found.append(_unquote(segs[0]).casefold())
    return found


def _split_comparison(expr: str) -> tuple[str, str, str]:
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
    return expr[:pos].strip(), op, expr[pos + len(op):].strip()


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
            out.append(segs[1])
            last = end
            continue
        raise UntranslatableError(
            f"{what} names '{name}', not a source column: the subquery reads the "
            f"source table only")
    out.append(sql[last:])
    return "".join(out).strip()


def translate_latest_period_flag(dim: dict, parsed: dict, lods: dict[str, dict],
                                 operand_ts) -> str:
    """The sql_bool_op formula for `dim`, or UntranslatableError (the skip reason
    says why). operand_ts translates the non-LOD side to a ThoughtSpot expression."""
    why = (f"dimension '{dim['name']}' compares to a whole-table OVER () dimension; "
           f"the group_aggregate comparison gives wrong numbers in ThoughtSpot (BL-638) "
           f"and it")
    try:
        left, op, right = _split_comparison(dim["expr"])
    except UntranslatableError:
        raise UntranslatableError(
            f"{why} is not a single comparison `<expr> <op> <latest dimension>`, the "
            f"one shape emitted as a subquery") from None
    side = [s for s in (left, right)
            if len(split_dot_path(s)) == 1 and _unquote(s).casefold() in lods]
    other = right if side and side[0] == left else left
    if len(side) != 1 or references(other, lods):
        raise UntranslatableError(
            f"{why} does not compare one plain expression to one latest dimension")
    lod = lods[_unquote(side[0]).casefold()]
    if lod["inner_agg"] not in _SQL_AGGS:
        raise UntranslatableError(
            f"{why} uses {lod['inner_agg']}, and only MAX/MIN latest dimensions are "
            f"emitted as a subquery")
    src = parsed.get("source") or {}
    if src.get("kind") != "table_fqn":
        raise UntranslatableError(f"{why} needs a table source to query")
    try:
        sql = (f"SELECT {lod['inner_agg']}({_source_sql(lod['inner_expr'], 'the latest dimension')})"
               f" FROM {src['raw']}")
        if parsed.get("filter"):
            sql += f" WHERE {_source_sql(parsed['filter'], 'the MV filter')}"
    except UntranslatableError as exc:
        raise UntranslatableError(f"{why} cannot be a subquery: {exc}") from None
    if any(c in sql for c in '"{}'):
        raise UntranslatableError(f"{why} has a double quote or brace in its SQL")
    lhs, rhs = ("{0}", f"({sql})") if side[0] == right else (f"({sql})", "{0}")
    return f'sql_bool_op ( "{lhs} {op} {rhs}" , {operand_ts(other)} )'
