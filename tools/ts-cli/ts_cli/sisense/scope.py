"""Filter scope for Sisense widget measures: conditions, measured values, ignored filters.

Pure functions, no I/O. Shared by ``functions.translate_jaql`` (measured values inside a
JAQL formula) and ``answers`` (widget filters and ``metadata.ignore``). Every expression this
module builds is already in ThoughtSpot's final literal form, so callers splice it in AFTER
``ts_finalize_formula`` has run on the surrounding text.

Three Sisense behaviours meet here, each verified against a live Sisense cube and a
ThoughtSpot import:

* **Measured value** ``(count([id]), [Status])`` with a member filter on ``[Status]``: the
  value's own filter REPLACES any dashboard or widget filter on ``[Status]`` (a HIRED
  measured value keeps its count under a ``Status = APPLIED`` widget filter). ThoughtSpot:
  ``group_aggregate ( unique_count_if ( [Status] = 'HIRED' , [id] ) , <groups> ,
  query_filters ( ) - { [Status] } )``. A plain ``*_if`` would be narrowed by the filter.
* **Widget ignores dashboard filters** (``metadata.ignore.ids`` / ``.dimensions``): each
  aggregate becomes ``group_aggregate ( agg , <groups> , query_filters ( ) - { [col] } )``;
  ``ignore.all`` becomes ``group_aggregate ( agg , <groups> , { } )``.
* **Tile filter on a column that also has a Liveboard filter**: in ThoughtSpot a Liveboard
  filter on a column REPLACES the tile's own filter on that column (Sisense applies both),
  so the tile filter is folded into the measures as a condition instead of the search.

``<groups>`` is ``{ }`` for a single-value widget (indicator) and ``query_groups ( )``
otherwise, so a grouped chart keeps its rows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ts_cli.formula_text import ts_string_literal

# A ThoughtSpot aggregate call in translated text. ``unique count`` precedes ``count`` and
# the ``*_if`` forms precede their bases so the longest name wins at each position.
_AGG_NAMES = ("unique_count_if", "unique count", "count_if", "sum_if", "average_if",
              "min_if", "max_if", "sum", "count", "average", "min", "max", "stddev",
              "variance", "median")
_AGG_CALL = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(n) for n in _AGG_NAMES)
                       + r")\s*\(")
_GA_CALL = re.compile(r"(?<![A-Za-z0-9_])group_aggregate\s*\(")
# plain aggregate -> its conditional form; None = no catalogued *_if, use if/then/else null
_COND_FORM = {"sum": "sum_if", "count": "count_if", "unique count": "unique_count_if"}

GROUPS_SINGLE = "{ }"
GROUPS_QUERY = "query_groups ( )"


@dataclass
class Scope:
    """How a widget's measures must be scoped (see module docstring).

    ``conds`` maps a model column ref (``[Col]``) to a condition folded into every
    aggregate (tile filters shadowed by a Liveboard filter). ``ignore_cols`` are the column
    refs whose query filters the measures drop; ``ignore_all`` drops every query filter.
    """
    groups: str = GROUPS_QUERY
    conds: dict = field(default_factory=dict)
    ignore_cols: list = field(default_factory=list)
    ignore_all: bool = False

    def trivial(self) -> bool:
        return not (self.conds or self.ignore_cols or self.ignore_all)


# --------------------------------------------------------------------------- #
# Literals and conditions
# --------------------------------------------------------------------------- #
def _literal(v, numeric: bool = False) -> str:
    """A filter member -> ThoughtSpot literal. Numbers are bare; so is a numeric string
    on a numeric column (JAQL sends members as strings, ``"1"`` for a numeric flag, and
    ``[flag] = '1'`` does not compile against a number column)."""
    if numeric and isinstance(v, str):
        try:
            float(v)
            return v.strip()
        except ValueError:
            pass
    if isinstance(v, bool):
        return ts_string_literal(str(v).lower())
    if isinstance(v, (int, float)):
        return repr(v)
    return ts_string_literal(str(v))


_RANGE_OPS = (("equals", "="), ("from", ">="), ("fromNotEqual", ">"),
              ("to", "<="), ("toNotEqual", "<"))


def _member_values(r: dict) -> tuple:
    """-> ('members' | 'exclude' | None, raw member list)."""
    if "members" in r:
        return "members", list(r.get("members") or [])
    if "exclude" in r:
        return "exclude", list((r.get("exclude") or {}).get("members") or [])
    return None, []


def _member_condition(col_ref: str, kind: str, vals: list) -> str | None:
    if not vals:
        return None
    if kind == "members":
        return f"{col_ref} = {vals[0]}" if len(vals) == 1 else \
            f"{col_ref} in {{ {' , '.join(vals)} }}"
    return f"{col_ref} != {vals[0]}" if len(vals) == 1 else \
        f"not ( {col_ref} in {{ {' , '.join(vals)} }} )"


def _no_form(col_ref: str, r: dict, what: str) -> tuple:
    """An ``all`` (or empty) filter restricts nothing; anything else has no form."""
    if r.get("all") or not r:
        return None, ""
    return None, f"filter on {col_ref} ({', '.join(sorted(r))}) has no {what} form"


def filter_condition(col_ref: str, raw: dict, datatype: str = "") -> tuple:
    """Sisense JAQL filter dict on ``col_ref`` -> (condition | None, error | "").

    members -> ``= v`` / ``in { … }``; exclude -> ``!= v`` / ``not ( … in { … } )``;
    from/to/fromNotEqual/toNotEqual/equals -> comparisons joined by ``and``. An ``all``
    filter (or an empty member list) restricts nothing -> (None, ""). Any other shape
    (relative date, top-N, ranking, nested condition) -> (None, error). ``datatype`` is
    the JAQL item's own (``numeric`` / ``text`` / ``datetime``); a member list on a
    datetime column is refused, since its literal form depends on the warehouse.
    """
    r = raw or {}
    dtype = (datatype or "").lower()
    kind, members = _member_values(r)
    if kind and dtype == "datetime":
        return None, f"member filter on date column {col_ref} has no condition form"
    if kind:
        vals = [_literal(v, dtype == "numeric") for v in members]
        return _member_condition(col_ref, kind, vals), ""
    parts = [f"{col_ref} {op} {_literal(r[k], dtype == 'numeric')}"
             for k, op in _RANGE_OPS if r.get(k) is not None]
    if parts:
        return " and ".join(parts), ""
    return _no_form(col_ref, r, "condition")


def _search_literal(v):
    """A search-token literal, or None when the value holds a quote (no escape exists)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return repr(v)
    s = str(v)
    return None if "'" in s else f"'{s}'"


def search_filter_tokens(col_ref: str, raw: dict) -> tuple:
    """A widget filter as search-query tokens -> (tokens | None, error | "").

    members -> ``[c] = 'a' 'b'``; exclude -> one ``[c] != 'a'`` per member; ranges ->
    one comparison per bound. Values holding a quote are refused: search tokens have no
    escape, so the caller routes them to a conditional measure instead."""
    r = raw or {}
    kind, members = _member_values(r)
    if kind:
        vals = [_search_literal(v) for v in members]
        if None in vals:
            return None, f"a member of {col_ref} holds a quote"
        if kind == "members":
            return (f"{col_ref} = {' '.join(vals)}" if vals else ""), ""
        return " ".join(f"{col_ref} != {v}" for v in vals), ""
    parts = [(op, _search_literal(r[k])) for k, op in _RANGE_OPS if r.get(k) is not None]
    if any(v is None for _, v in parts):
        return None, f"a bound of {col_ref} holds a quote"
    if parts:
        return " ".join(f"{col_ref} {op} {v}" for op, v in parts), ""
    tok, err = _no_form(col_ref, r, "search")
    return ("" if not err else None), err


def and_conds(conds) -> str | None:
    """Join conditions with ``and`` (each parenthesised when there is more than one)."""
    cs = [c for c in conds if c]
    if not cs:
        return None
    if len(cs) == 1:
        return cs[0]
    return " and ".join(f"( {c} )" for c in cs)


# --------------------------------------------------------------------------- #
# Aggregate-call rewriting
# --------------------------------------------------------------------------- #
def _close_paren(s: str, open_idx: int) -> int:
    """Index of the ')' matching '(' at ``open_idx``, skipping quoted literals; -1 if none."""
    depth, quote = 0, None
    for i in range(open_idx, len(s)):
        ch = s[i]
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def map_agg_calls(expr: str, fn) -> str:
    """Apply ``fn(name, arg_text) -> replacement`` to every top-level aggregate call.

    A ``group_aggregate ( … )`` call is left untouched (it is already scoped)."""
    out, i = [], 0
    while i < len(expr):
        m_agg = _AGG_CALL.search(expr, i)
        m_ga = _GA_CALL.search(expr, i)
        if m_ga and (not m_agg or m_ga.start() <= m_agg.start()):
            end = _close_paren(expr, expr.index("(", m_ga.start()))
            if end == -1:
                return expr
            out.append(expr[i:end + 1])
            i = end + 1
            continue
        if not m_agg:
            out.append(expr[i:])
            break
        open_idx = expr.index("(", m_agg.start())
        end = _close_paren(expr, open_idx)
        if end == -1:
            return expr
        out.append(expr[i:m_agg.start()])
        out.append(fn(m_agg.group(1), expr[open_idx + 1:end].strip()))
        i = end + 1
    return "".join(out)


def _conditional_call(name: str, arg: str, cond: str | None) -> str:
    """``name(arg)`` restricted to rows where ``cond`` holds."""
    if not cond:
        return f"{name} ( {arg} )"
    if name.endswith("_if"):                       # already conditional: AND the conditions
        inner_cond, _, value = _split_first_arg(arg)
        return f"{name} ( ( {inner_cond} ) and ( {cond} ) , {value} )"
    form = _COND_FORM.get(name)
    if form:
        return f"{form} ( {cond} , {arg} )"
    return f"{name} ( if ( {cond} ) then {arg} else null )"


def _split_first_arg(arg: str) -> tuple:
    """'c , v' -> ('c', ',', 'v') at the first top-level comma."""
    depth, quote = 0, None
    for i, ch in enumerate(arg):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            return arg[:i].strip(), ",", arg[i + 1:].strip()
    return arg, "", ""


def filters_arg(drop_cols, ignore_all: bool) -> str:
    """The third ``group_aggregate`` argument: ``{ }`` or ``query_filters ( ) - { … }``."""
    if ignore_all:
        return "{ }"
    cols = sorted(set(drop_cols))
    return "query_filters ( ) - { " + " , ".join(cols) + " }"


def scope_expression(expr: str, scope: Scope, extra_cond: str | None = None,
                     drop_cols=(), skip_cond_cols=()) -> str:
    """Apply a widget scope to every top-level aggregate in translated ``expr``.

    Each aggregate is restricted by the scope's conditions (minus ``skip_cond_cols``, the
    columns a measured value owns) and ``extra_cond``; when the scope drops filters, or
    ``drop_cols`` is given, the aggregate is wrapped in ``group_aggregate``."""
    cond = and_conds([c for col, c in sorted(scope.conds.items()) if col not in skip_cond_cols]
                     + [extra_cond])
    drop = list(scope.ignore_cols) + list(drop_cols)
    wrap = scope.ignore_all or bool(drop)

    def one(name, arg):
        call = _conditional_call(name, arg, cond)
        if not wrap:
            return call
        return f"group_aggregate ( {call} , {scope.groups} , {filters_arg(drop, scope.ignore_all)} )"

    return map_agg_calls(expr, one)


# --------------------------------------------------------------------------- #
# Measured values in JAQL source
# --------------------------------------------------------------------------- #
_PLACEHOLDER = re.compile(r"^\[[^\[\]]+\]$")


def _jaql_close(s: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(s)):
        if s[i] in "([":
            depth += 1
        elif s[i] in ")]":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_args(s: str) -> list:
    args, depth, buf = [], 0, []
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    args.append("".join(buf).strip())
    return args


def extract_measured_values(source: str) -> tuple:
    """Replace each measured value ``(expr, [k1], [k2]…)`` in JAQL ``source`` by a sentinel.

    A measured value is a GROUPING parenthesis (not a function call: no identifier right
    before it) holding two or more top-level arguments of which all but the first are bare
    ``[placeholder]`` tokens. Returns ``(source_with_sentinels, [(sentinel_key, expr,
    [k1, …]), …])``; sentinels are ``[__mv0]``, ``[__mv1]``, …"""
    found, out, i, n = [], [], 0, 0
    while i < len(source):
        ch = source[i]
        if ch == "(" and not re.search(r"[A-Za-z0-9_]\s*$", source[:i]):
            close = _jaql_close(source, i)
            if close != -1:
                args = _split_args(source[i + 1:close])
                if len(args) >= 2 and all(_PLACEHOLDER.match(a) for a in args[1:]):
                    key = f"__mv{n}"
                    n += 1
                    found.append((key, args[0], [a[1:-1].strip() for a in args[1:]]))
                    out.append(f"[{key}]")
                    i = close + 1
                    continue
        out.append(ch)
        i += 1
    return "".join(out), found
