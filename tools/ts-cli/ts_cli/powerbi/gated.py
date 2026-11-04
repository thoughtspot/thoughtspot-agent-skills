"""Power BI gated distinct-count measures -> ThoughtSpot ``unique_count_if``.

``translate_dax``'s review gate refuses anything containing CALCULATE, USERELATIONSHIP or
VAR/RETURN. That is right for filter-context work in general, and leaves two shapes on the
floor that carry most on-time / in-tolerance / hit-rate reporting and are fully described
by the DAX:

    CALCULATE(DISTINCTCOUNT(T[key]), NOT ISBLANK(T[gate]))
        -> unique_count_if ( [T::gate] != null , [T::key] )

    VAR a = CALCULATE(DISTINCTCOUNT(T[key]), NOT ISBLANK(T[g1]), T[stage] IN {"x","y"})
    VAR b = CALCULATE(DISTINCTCOUNT(T[key]), NOT ISBLANK(T[g2]))
    RETURN a/b
        -> unique_count_if ( … , [T::key] ) / unique_count_if ( … , [T::key] )

**Always Approximated, never Migrated.** A CALCULATE column filter *replaces* any existing
filter on that column; ``unique_count_if`` *ANDs* its condition with the query filters.
Live probe (ps-internal, 2026-10-08), the emitted form grouped by the column it filters on:

    Early 0 | On Time 3812 | 1 week late 0 | Less than 1 week late 0 | …

Row-local. Power BI should show 3812 in *every* row, because CALCULATE drops the grouping
filter on that column (inferred from CALCULATE's semantics, not measured in Power BI). The numbers agree only when the board does not group by it, so the
label has to say Approximated. The same probe confirmed ``unique_count_if`` compiles and
returns exactly what the older ``unique count ( if … else null )`` form returns.

Acceptance is whole-expression or nothing. The measure must be *entirely* the CALCULATE,
or entirely a ``RETURN a/b`` over two of them; every CALCULATE argument must be consumed
by a recognised filter; and every column must belong to the home table. Anything else
returns no formula and keeps its NEEDS REVIEW, because a partial read of a filter silently
widens the counted population, which is worse than refusing the shape.
"""

from __future__ import annotations

import re

from ts_cli.formula_text import ts_finalize_formula, ts_string_literal
from ts_cli.powerbi.functions import DAX_STRING, _split_args, dax_col_refs, dax_string_value

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
_EQ = re.compile(r"\s*=(?!=)\s*")                 # `=`, never `==`, `>=`, `<=`
_IN = re.compile(r"\s*IN\s*\{", re.I)


def _whole_call(src: str, fname: str) -> str | None:
    """The argument text when ``src`` is *entirely* one ``fname(...)`` call, else None.

    The first version searched for the call anywhere and discarded the rest, so
    ``DIVIDE(CALCULATE(...), DISTINCTCOUNT(...))`` silently became its own numerator.
    """
    s = src.strip()
    m = re.match(rf"^{fname}\s*\(", s, re.I)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(s) and depth:
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
        i += 1
    return s[m.end():i - 1] if depth == 0 and i == len(s) else None


def _whole_ref(text: str) -> tuple[str, str] | None:
    """``(table, column)`` when ``text`` is *exactly* one qualified column, else None.

    Uses the repo's single DAX-qualifier reader, so ``'Bob''s Sales'[g]`` survives.
    Containing one column is not enough: ``IF(T[g] > 5, 1)`` contains one.
    """
    t = text.strip()
    refs = dax_col_refs(t)
    if len(refs) == 1 and refs[0][0] == 0 and refs[0][1] == len(t):
        return refs[0][2], refs[0][3]
    return None


def _leading_ref(s: str):
    """``(table, column, end)`` for a qualified column at the very start of ``s``."""
    refs = dax_col_refs(s)
    if refs and refs[0][0] == 0:
        return refs[0][2], refs[0][3], refs[0][1]
    return None


def _literal_at(s: str, i: int):
    """``(kind, value, end)`` for one DAX literal starting at ``i``, else None. Strings
    are decoded by the shared DAX decoder (``""`` is a quote; there are no backslash
    escapes, so ``"C:\\temp"`` is kept as written)."""
    m = DAX_STRING.match(s, i)
    if m:
        return "str", dax_string_value(m), m.end()
    m = _NUM.match(s, i)
    if m and not (m.end() < len(s) and (s[m.end()].isalnum() or s[m.end()] in "_.")):
        return "num", m.group(0), m.end()
    return None


def _value_set(s: str, i: int):
    """The literals of ``{a, b, …}`` whose ``{`` ends just before ``i``, when the set
    closes exactly at the end of ``s``; else None. ``{"a" & "b"}`` and
    ``{"a"} && T[t] IN {"b"}`` are refused, not read up to the first quote."""
    vals = []
    while True:
        i = len(s) - len(s[i:].lstrip())
        lit = _literal_at(s, i)
        if lit is None:
            return None
        vals.append(lit[:2])
        i = len(s) - len(s[lit[2]:].lstrip())
        if s[i:i + 1] == ",":
            i += 1
        elif s[i:i + 1] == "}" and not s[i + 1:].strip():
            return vals
        else:
            return None


def _ts_values(vals) -> list[str]:
    """ThoughtSpot literal text for a value set. DAX compares a mixed set as text
    (``IN {"a", 1}`` matches ``"1"``), so once any member is a string every member is
    emitted as one; an all-number set stays numeric."""
    if any(k == "str" for k, _ in vals):
        return [ts_string_literal(v) for _, v in vals]
    return [v for _, v in vals]


def _not_isblank_ref(rest: str) -> tuple[str, str] | None:
    """The column of ``ISBLANK(T[c])`` or ``( ISBLANK(T[c]) )`` making up all of ``rest``
    (the text after a leading NOT), else None."""
    inner = _whole_call(rest, "ISBLANK")
    if inner is None:
        paren = _whole_call(rest, "")
        inner = _whole_call(paren, "ISBLANK") if paren is not None else None
    return _whole_ref(inner) if inner is not None else None


def _parse_filter(arg: str):
    """One CALCULATE argument -> a typed tuple, or None when not exactly a shape we read.

    Three shapes, each matched to the END of the argument with nothing before the column:
    ``T[c] = <literal>``, ``T[c] IN {<literal>, …}`` and ``NOT ISBLANK(T[c])`` (plus
    ``USERELATIONSHIP(T[a], U[b])``). Anything else, ``>=``, ``NOT T[c] = …``,
    ``LEFT(T[c], 1) = …``, ``T[c] + 1 = …``, ``&&``, ``||`` or a function call around
    the column, refuses: a partial read silently changes the counted population.
    """
    s = arg.strip()
    rel = _whole_call(s, "USERELATIONSHIP")
    if rel is not None:
        parts = _split_args(rel)
        ok = len(parts) == 2 and all(_whole_ref(p) for p in parts)
        return ("userelationship", None, None, None) if ok else None
    m = re.match(r"NOT\b\s*", s, re.I)
    if m:
        ref = _not_isblank_ref(s[m.end():])
        return ("notnull", ref[0], ref[1], None) if ref else None
    lead = _leading_ref(s)
    if lead is None:
        return None
    tbl, col, end = lead
    m = _IN.match(s, end)
    if m:
        vals = _value_set(s, m.end())
        return ("in", tbl, col, _ts_values(vals)) if vals else None
    m = _EQ.match(s, end)
    if m:
        lit = _literal_at(s, m.end())
        if lit and not s[lit[2]:].strip():
            return ("in", tbl, col, _ts_values([lit[:2]]))
    return None


def _filtered_cols(spec) -> set[tuple[str, str]]:
    return {(t, c) for t, c in spec["gates"]} | {(t, c) for t, c, _ in spec["cats"]}


def parse_calculate(src: str):
    """``CALCULATE(DISTINCTCOUNT(T[key]), <filters>)`` -> dict, else None."""
    body = _whole_call(src, "CALCULATE")
    if body is None:
        return None
    args = _split_args(body)
    if not args:
        return None
    inner = parse_calculate(args[0])          # CALCULATE(CALCULATE(..), USERELATIONSHIP(..))
    if inner is not None:
        table, key = inner["table"], inner["key"]
        gates, cats, rel = list(inner["gates"]), list(inner["cats"]), inner["userelationship"]
    else:
        dc = _whole_call(args[0], "DISTINCTCOUNT")
        ref = _whole_ref(dc) if dc is not None else None
        if not ref:
            return None
        table, key = ref
        gates, cats, rel = [], [], False
    outer = {"gates": [], "cats": []}
    for arg in args[1:]:
        parsed = _parse_filter(arg)
        if parsed is None:
            return None                        # unread filter: refuse the whole shape
        kind, tbl, col, vals = parsed
        if kind == "userelationship":
            rel = True
        elif kind == "notnull":
            outer["gates"].append((tbl, col))
        else:
            outer["cats"].append((tbl, col, vals))
    if inner is not None and _filtered_cols(inner) & _filtered_cols(outer):
        # The inner CALCULATE's filter OVERRIDES the outer one on the same column, so
        # ANDing them (0 rows for "a" and "b") is wrong; there is no single condition.
        return None
    return {"table": table, "key": key, "gates": gates + outer["gates"],
            "cats": cats + outer["cats"], "userelationship": rel}


def parse_ratio(src: str):
    """``VAR a = … VAR b = … RETURN a/b`` -> (num, den), else None. The RETURN must be
    exactly one var divided by another: ``DIVIDE(a,b)``, ``1 - a/b`` and ``a/b*2`` are all
    refused, because each means something the emitted formula would not say."""
    s = src.strip()
    if not re.match(r"^VAR\b", s, re.I):
        return None
    variables = dict(re.findall(r"\bVAR\s+(\w+)\s*=\s*(.*?)(?=\bVAR\b|\bRETURN\b)",
                                s, re.I | re.S))
    ret = re.search(r"\bRETURN\b(.*)$", s, re.I | re.S)
    if not variables or not ret:
        return None
    div = re.fullmatch(r"\s*(\w+)\s*/\s*(\w+)\s*", ret.group(1))
    if not div:
        return None
    num, den = (parse_calculate(variables.get(div.group(i), "")) for i in (1, 2))
    return (num, den) if num and den else None


def _count_expr(spec, home: str) -> str | None:
    """``unique_count_if`` over the spec, or None when any column is off the home table.

    Qualifying every column with one table turned a filter on ``Dim[g]`` into
    ``[Fact::g]``, which reads as a different column that may well exist.
    """
    tables = {spec["table"]} | {t for t, _ in spec["gates"]} | {t for t, _, _ in spec["cats"]}
    if tables != {home}:
        return None
    conds = [f"[{home}::{c}] != null" for _, c in spec["gates"]]
    for _, col, vals in spec["cats"]:
        ors = " or ".join(f"[{home}::{col}] = {v}" for v in vals)
        conds.append(f"( {ors} )" if len(vals) > 1 else ors)
    key = f"[{home}::{spec['key']}]"
    if not conds:
        return f"unique count ( {key} )"
    return f"unique_count_if ( {' and '.join(conds)} , {key} )"


_REL_NOTE = ("; the source uses USERELATIONSHIP, so a page slicing on the role-playing "
             "date needs a union fact keyed by measure, not this measure")
_NOTE = ("gated distinct count recognised from the DAX; CALCULATE REPLACES an existing "
         "filter on the filtered column while unique_count_if ANDs with it, so the two "
         "differ on a visual grouped by that column (live-probed)")


def translate(dax: str, home_table: str | None = None):
    """``(expr, "Approximated", note)``, or ``(None, None, None)`` when not these shapes."""
    src = (dax or "").strip()
    if not src:
        return None, None, None

    pair = parse_ratio(src)
    if pair:
        num, den = pair
        home = home_table or num["table"]
        if num["key"] != den["key"]:
            return None, None, None
        a, b = _count_expr(num, home), _count_expr(den, home)
        if not (a and b):
            return None, None, None
        rel = num["userelationship"] or den["userelationship"]
        return (ts_finalize_formula(f"{a} / {b}"), "Approximated",
                _NOTE + (_REL_NOTE if rel else ""))

    spec = parse_calculate(src)
    if spec:
        home = home_table or spec["table"]
        expr = _count_expr(spec, home)
        if not expr:
            return None, None, None
        return (ts_finalize_formula(expr), "Approximated",
                _NOTE + (_REL_NOTE if spec["userelationship"] else ""))

    return None, None, None
