"""Function rules for ThoughtSpot → Excel (``to_excel``). Each returns ``(text, precedence)``.

The reverse of the Excel map rows the forward translator implements, so a round trip is
stable: ``safe_divide ( a , b )`` → ``IF(b=0,0,a/b)`` (exact, unlike IFERROR, which also
swallows other errors) and back; ``round ( x , 0.01 )`` → ``ROUND(x,2)`` via
``formula_common.ts_increment_to_sql_digits``; ``contains`` → ``ISNUMBER(SEARCH())``;
``day_number_of_week`` → ``WEEKDAY(d,2)``.
"""
from __future__ import annotations

from decimal import Decimal

from ts_cli.excel.to_excel import (
    P_ADD, P_CONCAT, P_MUL, P_PRIMARY, Emitter,
)
from ts_cli.formula_common import ts_increment_to_sql_digits

# ThoughtSpot functions with no Excel formula equivalent, with the reason (prefix_ = family).
NO_EXCEL = {
    "cumulative_": "a window function — Excel has no row order; a running total is "
                   "SUM($B$2:B2) filled down over a sorted sheet, by hand",
    "moving_": "a window function — Excel has no row order or partition; rebuild with OFFSET "
               "over a sorted sheet, by hand",
    "rank": "rank depends on the search's grouping; Excel RANK.EQ ranks a fixed range",
    "rank_percentile": "rank depends on the search's grouping",
    "sql_": "a warehouse SQL pass-through — rewrite the SQL as Excel functions by hand",
    "first_value": "a semi-additive window over a date axis — no Excel form",
    "last_value": "a semi-additive window over a date axis — no Excel form",
    "query_groups": "the grain follows the search — no fixed Excel form",
    "unique_count_if": "a conditional distinct count — COUNTA(UNIQUE(FILTER(…))) by hand",
    "ts_var": "a formula variable — resolved per user at query time",
    "isnotnull": "not a ThoughtSpot function (rejected at import, probe record §7, BL-339) — "
                 "the formula is invalid; write not ( isnull ( x ) )",
    "nullif": "not a ThoughtSpot function (rejected at import, probe record §7, BL-339) — the "
              "formula is invalid; write if ( a = b ) then null else a",
}
_AGG = {"sum": "SUM", "average": "AVERAGE", "min": "MIN", "max": "MAX", "median": "MEDIAN",
        "stddev": "STDEV.S", "variance": "VAR.S", "count": "COUNTA"}
_IFS = {"sum_if": "SUMIFS", "average_if": "AVERAGEIFS", "max_if": "MAXIFS",
        "min_if": "MINIFS", "count_if": "COUNTIFS"}
_GROUP_SHORT = {"group_sum": "sum", "group_average": "average", "group_count": "count",
                "group_max": "max", "group_min": "min"}
_SIMPLE = {"abs": "ABS", "sqrt": "SQRT", "exp": "EXP", "ln": "LN", "log10": "LOG10",
           "year": "YEAR", "month_number": "MONTH", "day": "DAY", "left": "LEFT",
           "right": "RIGHT", "strlen": "LEN", "pow": "POWER", "to_double": "VALUE",
           "add_months": "EDATE", "floor": "INT"}


def wildcard_escape(text: str) -> str:
    """Excel's SEARCH and *IFS criteria read ``* ? ~`` as wildcards; ``~`` escapes them."""
    return text.replace("~", "~~").replace("*", "~*").replace("?", "~?")


def _string_inner(node: dict) -> str:
    return node["value"][1:-1].replace("''", "'")


def _xl_string(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _search_arg(em: Emitter, node: dict) -> str:
    """The find_text of SEARCH: a literal is wildcard-escaped (ThoughtSpot contains/strpos
    match it literally); a column cannot be escaped, so the trap says so."""
    if _is_lit(node, "string"):
        return _xl_string(wildcard_escape(_string_inner(node)))
    em.trap("SEARCH treats * ? ~ in the searched-for value as wildcards; ThoughtSpot matches "
            "them literally — equal unless the column holds those characters")
    return em.text(node)


def _fn(name: str, em: Emitter, args: list) -> tuple[str, int]:
    return f"{name}(" + ",".join(em.text(a) for a in args) + ")", P_PRIMARY


def _aggregate(name: str):
    def rule(em: Emitter, args: list):
        if len(args) != 1:
            em.review(f"{name} with {len(args)} arguments")
        with em.aggregate():
            inner = em.text(args[0])
        if args[0].get("node") not in ("col", "ref"):
            em.note("an expression inside an aggregate is an array calculation — Excel 365 "
                    "evaluates it natively (older Excel: SUMPRODUCT)")
        return f"{_AGG[name]}({inner})", P_PRIMARY
    return rule


def _unique_count(em: Emitter, args: list):
    with em.aggregate():
        inner = em.text(args[0])
    return f"COUNTA(UNIQUE({inner}))", P_PRIMARY


def _criteria(em: Emitter, cond: dict) -> list:
    """``col op literal`` conjunction → ``[range, criterion, …]``, or [] when not expressible."""
    from ts_cli.excel.to_excel import _flatten

    out: list = []
    for part in _flatten(cond, "and"):
        pair = _criterion(em, part)
        if pair is None:
            return []
        out.extend(pair)
    return out


def _is_call(node: dict, fn: str) -> bool:
    return node.get("node") == "call" and node["fn"] == fn


def _null_criterion(em: Emitter, part: dict):
    """``isnull ( c )`` → blank, ``not ( isnull ( c ) )`` → non-blank."""
    negated = part.get("node") == "unop" and part["op"] == "not"
    inner = part["operand"] if negated else part
    if _is_call(inner, "isnull") and _is_column(inner["args"][0]):
        return [em.text(inner["args"][0]), '"<>"' if negated else '""']
    return None


def _compare_criterion(em: Emitter, part: dict):
    if not (part.get("node") == "binop" and part["op"] in ("=", "!=", "<", "<=", ">", ">=")
            and _is_column(part["left"]) and part["right"].get("node") == "lit"):
        return None
    # An equality keeps its "=" so a value such as ">5" is not read as a comparison, and a
    # text value is wildcard-escaped so "a*" matches only "a*" (PR #570 review M3).
    op = {"!=": "<>"}.get(part["op"], part["op"])
    is_text = part["right"]["kind"] == "string"
    value = wildcard_escape(_string_inner(part["right"])) if is_text else part["right"]["value"]
    if op == "<>":
        em.trap("criterion \"<>x\" also matches blanks in Excel; ThoughtSpot's != skips NULLs",
                downgrade=True)
    return [em.text(part["left"]), _xl_string(op + value)]


def _criterion(em: Emitter, part: dict):
    if _is_call(part, "contains") and _is_column(part["args"][0]) \
            and _is_lit(part["args"][1], "string"):
        inner = wildcard_escape(_string_inner(part["args"][1]))
        return [em.text(part["args"][0]), _xl_string("*" + inner + "*")]
    return _null_criterion(em, part) or _compare_criterion(em, part)


def _is_column(node: dict) -> bool:
    return node.get("node") in ("col", "ref")


def _is_lit(node: dict, kind: str) -> bool:
    return node.get("node") == "lit" and node["kind"] == kind


def _conditional(fn: str):
    def rule(em: Emitter, args: list):
        cond, value = args
        with em.aggregate():
            crit = _criteria(em, cond)
            target = em.text(value)
        if not crit:
            em.review(f"{fn}: the condition is not a conjunction of column-vs-literal tests, so "
                      "it has no *IFS criteria form")
        if fn == "count_if":
            em.trap("COUNTIFS counts matching rows; count_if counts non-null values of its "
                    "second argument — equal when that column has no NULLs")
            return f"COUNTIFS({','.join(crit)})", P_PRIMARY
        if fn in ("max_if", "min_if"):
            em.trap(f"{_IFS[fn]} returns 0 when no row matches; {fn} returns NULL")
        return f"{_IFS[fn]}({target},{','.join(crit)})", P_PRIMARY
    return rule


def _group_aggregate(em: Emitter, args: list):
    if len(args) < 2 or args[0].get("node") != "call" or args[0]["fn"] not in _AGG \
            or args[1].get("node") != "lodset":
        em.review("group_aggregate: only an aggregate of a column at a fixed { … } grain has an "
                  "Excel form (SUMIFS per group)")
    if len(args) > 2 and not (args[2].get("node") == "call" and args[2]["fn"] == "query_filters"
                              and not args[2]["args"]):
        em.review("group_aggregate with explicit filters has no *IFS form here")
    return _per_group(em, args[0]["fn"], args[0]["args"][0], args[1]["cols"])


def _per_group(em: Emitter, agg: str, measure: dict, groups: list):
    ifs = {"sum": "SUMIFS", "average": "AVERAGEIFS", "max": "MAXIFS", "min": "MINIFS",
           "count": "COUNTIFS"}.get(agg)
    if ifs is None or not all(_is_column(g) for g in groups) or not _is_column(measure):
        em.review("group_aggregate: only sum / average / count / max / min of a column, grouped "
                  "by columns, has a per-group *IFS form")
    em.trap("a fixed-grain total per row, as SUMIFS over the whole table: Excel's *IFS ignores "
            "sheet filters, while group_aggregate with query_filters ( ) respects the search's "
            "filters", downgrade=True)
    pairs = []
    for g in groups:
        with em.aggregate():
            rng = em.text(g)
        pairs += [rng, em.text(g)]
    if ifs == "COUNTIFS":
        return f"COUNTIFS({','.join(pairs)})", P_PRIMARY
    with em.aggregate():
        target = em.text(measure)
    return f"{ifs}({target},{','.join(pairs)})", P_PRIMARY


def _group_short(em: Emitter, args: list, agg: str):
    return _per_group(em, agg, args[0], args[1:])


def _safe_divide(em: Emitter, args: list):
    a, b = em.text(args[0], P_MUL), em.text(args[1], P_MUL + 1)
    return f"IF({em.text(args[1])}=0,0,{a}/{b})", P_PRIMARY


def _round(em: Emitter, args: list):
    if len(args) == 1:
        return f"ROUND({em.text(args[0])},0)", P_PRIMARY
    inc = args[1]
    if inc.get("node") == "unop" and inc["op"] == "-" and _is_lit(inc["operand"], "number"):
        em.review("round with a negative increment: ThoughtSpot does not round to tens with it "
                  "(live 2026-10-06: round(1234.5678, -2) = 1234, not 1200 — Excel map E12), "
                  "so there is no faithful Excel form; check what the formula intends")
    if not _is_lit(inc, "number"):
        em.review("round with a non-literal increment has no Excel ROUND / MROUND form")
    try:
        digits = ts_increment_to_sql_digits(inc["value"])
    except ValueError as exc:
        em.review(str(exc))
    if digits is not None:
        return f"ROUND({em.text(args[0])},{digits})", P_PRIMARY
    # ThoughtSpot compiles round ( x , inc ) to inc * ROUND(x / inc); MROUND would return
    # #NUM! for a negative x, so write ThoughtSpot's own form.
    x = em.text(args[0], P_MUL)
    return f"ROUND({x}/{inc['value']},0)*{inc['value']}", P_MUL


def _concat(em: Emitter, args: list):
    parts = []
    for a in args:
        if a.get("node") == "call" and a["fn"] == "to_string":
            em.note("to_string inside concat is implicit in Excel's & (a date column joins as "
                    "its serial number — wrap it in TEXT(d,\"yyyy-mm-dd\"))")
            a = a["args"][0]
        parts.append(em.text(a, P_CONCAT + 1))
    return "&".join(parts), P_CONCAT


def _to_string(em: Emitter, args: list):
    return f'{em.text(args[0], P_CONCAT + 1)}&""', P_CONCAT


def _contains(em: Emitter, args: list):
    return f"ISNUMBER(SEARCH({_search_arg(em, args[1])},{em.text(args[0])}))", P_PRIMARY


def _strpos(em: Emitter, args: list):
    return f"IFERROR(SEARCH({_search_arg(em, args[1])},{em.text(args[0])}),0)", P_PRIMARY


def _substr(em: Emitter, args: list):
    start = args[1]
    if _is_lit(start, "number"):
        begin = str(Decimal(start["value"]) + 1)
    else:
        begin = f"{em.text(start, P_ADD)}+1"
    return f"MID({em.text(args[0])},{begin},{em.text(args[2])})", P_PRIMARY


def _greatest_least(name: str, cmp: str):
    def rule(em: Emitter, args: list):
        if not em.agg:
            return _fn(name, em, args)
        out = em.text(args[-1])
        for a in reversed(args[:-1]):  # MAX / MIN collapse an array: element-wise IF instead
            x = em.text(a)
            out = f"IF({x}{cmp}{out},{x},{out})"
        return out, P_PRIMARY
    return rule


def _diff_days(em: Emitter, args: list):
    return f"{em.text(args[0], P_ADD)}-{em.text(args[1], P_ADD + 1)}", P_ADD


def _diff_months(em: Emitter, args: list):
    e, s = em.text(args[0]), em.text(args[1])
    em.trap("diff_months counts month boundaries crossed (Jan 31 → Feb 1 = 1); Excel's "
            "DATEDIF(…,\"M\") counts complete months — this is the boundary count")
    return f"(YEAR({e})-YEAR({s}))*12+MONTH({e})-MONTH({s})", P_ADD


def _diff_years(em: Emitter, args: list):
    em.trap("diff_years counts year boundaries crossed, not complete years (DATEDIF \"Y\")")
    return f"YEAR({em.text(args[0])})-YEAR({em.text(args[1])})", P_ADD


def _weekday(em: Emitter, args: list):
    return f"WEEKDAY({em.text(args[0])},2)", P_PRIMARY


def _quarter(em: Emitter, args: list):
    em.trap("quarter_number follows the Model's calendar (fiscal if set); "
            "ROUNDUP(MONTH(d)/3,0) is the calendar quarter")
    return f"ROUNDUP(MONTH({em.text(args[0])})/3,0)", P_PRIMARY


def _start_of_month(em: Emitter, args: list):
    return f"EOMONTH({em.text(args[0])},-1)+1", P_ADD


def _add_days(em: Emitter, args: list):
    return f"{em.text(args[0], P_ADD)}+{em.text(args[1], P_ADD + 1)}", P_ADD


def _nullary(name: str):
    return lambda em, args: (f"{name}()", P_PRIMARY)


def _isnull(em: Emitter, args: list):
    return f"ISBLANK({em.text(args[0])})", P_PRIMARY


def _typed(em: Emitter, value: dict, column: dict) -> str:
    return em.typed_literal(value, em.text(value), column)


def _ifnull(em: Emitter, args: list):
    x = em.text(args[0])
    return f"IF(ISBLANK({x}),{_typed(em, args[1], args[0])},{x})", P_PRIMARY


def _in(em: Emitter, args: list):
    x = em.text(args[0])
    return "OR(" + ",".join(f"{x}={_typed(em, v, args[0])}" for v in args[1:]) + ")", P_PRIMARY


def _between(em: Emitter, args: list):
    x = em.text(args[0])
    return (f"AND({x}>={_typed(em, args[1], args[0])},{x}<={_typed(em, args[2], args[0])})",
            P_PRIMARY)


def _mod(em: Emitter, args: list):
    """ThoughtSpot mod compiles to Snowflake MOD — the result takes the DIVIDEND's sign
    (live 2026-10-06: mod(-3, 2) = -1, mod(3, -2) = 1, probe record §7). Excel MOD takes the
    divisor's sign (MOD(-3, 2) = 1), so the exact form is a - b * TRUNC(a / b)."""
    a, b = em.text(args[0], P_ADD), em.text(args[1], P_MUL)
    return f"{a}-{b}*TRUNC({em.text(args[0], P_MUL)}/{em.text(args[1], P_MUL + 1)})", P_ADD


def _simple(name: str):
    return lambda em, args: _fn(name, em, args)


CALLS = {
    **{k: _aggregate(k) for k in _AGG},
    **{k: _conditional(k) for k in _IFS},
    **{k: _simple(v) for k, v in _SIMPLE.items()},
    **{k: (lambda a: lambda em, args: _group_short(em, args, a))(v)
       for k, v in _GROUP_SHORT.items()},
    "unique count": _unique_count, "group_aggregate": _group_aggregate,
    "safe_divide": _safe_divide, "round": _round, "ceil": _simple("CEILING.MATH"),
    "log2": lambda em, args: (f"LOG({em.text(args[0])},2)", P_PRIMARY), "mod": _mod,
    "concat": _concat, "to_string": _to_string, "contains": _contains, "strpos": _strpos,
    "substr": _substr, "greatest": _greatest_least("MAX", ">="),
    "least": _greatest_least("MIN", "<="), "diff_days": _diff_days,
    "diff_months": _diff_months, "diff_years": _diff_years, "day_number_of_week": _weekday,
    "quarter_number": _quarter, "start_of_month": _start_of_month, "add_days": _add_days,
    "today": _nullary("TODAY"), "now": _nullary("NOW"), "isnull": _isnull,
    "ifnull": _ifnull, "in": _in, "between": _between,
    "to_integer": lambda em, args: (f"ROUND({em.text(args[0])},0)", P_PRIMARY),
}
