"""Power BI gated distinct-count measures -> ThoughtSpot ``unique_count_if``.

``translate_dax``'s review gate refuses anything containing CALCULATE, USERELATIONSHIP or
VAR/RETURN. That is right for filter-context work in general, and leaves two shapes on the
floor that are mechanical and fully described by the DAX:

    CALCULATE(DISTINCTCOUNT(T[key]), NOT ISBLANK(T[gate]))
        -> unique_count_if ( [T::gate] != null , [T::key] )

    VAR a = CALCULATE(DISTINCTCOUNT(T[key]), NOT ISBLANK(T[g1]), T[status] IN {"x","y"})
    VAR b = CALCULATE(DISTINCTCOUNT(T[key]), NOT ISBLANK(T[g2]))
    RETURN a/b
        -> unique_count_if ( … , [T::key] ) / unique_count_if ( … , [T::key] )

**Always Approximated, never Migrated.** A CALCULATE column filter *replaces* any existing
filter on that column; ``unique_count_if`` *ANDs* its condition with the query filters.
Synthetic illustration, for ``CALCULATE(DISTINCTCOUNT(T[k]), T[s] = "b")`` on a visual
grouped by ``T[s]``, where N is the number of distinct keys with ``s = "b"``:

    T[s] | emitted unique_count_if | Power BI CALCULATE
    a    | 0                       | N
    b    | N                       | N
    c    | 0                       | N

The emitted form is row-local; a live probe on ps-internal (2026-10-08) observed that side.
The Power BI column follows from CALCULATE's semantics and was not measured. The same
difference arises whenever the query itself filters the filtered column, whether by
grouping, a slicer, a page filter or a Liveboard filter: under a filter ``s = "c"``,
Power BI still returns N and ``unique_count_if`` returns 0. The two agree only when nothing
in the query filters that column, so the label has to say Approximated. The same probe
confirmed ``unique_count_if`` compiles and returns what the older
``unique count ( if … else null )`` form returns.

A second difference: DAX ``DISTINCTCOUNT`` counts a blank key as one value, while
``unique_count_if`` (SQL ``count(DISTINCT …)``) ignores NULL, so a key column with blanks
can come out one lower (BL-540 covers the plain ``DISTINCTCOUNT`` row). The note says so.

Acceptance is whole-expression or nothing. The measure must be *entirely* the CALCULATE,
or entirely a ``RETURN a/b`` over two of them; every CALCULATE argument must be consumed
by a recognised filter; and every column must belong to the home table. Anything else
returns no formula and keeps its NEEDS REVIEW, because a partial read of a filter silently
widens the counted population, which is worse than refusing the shape.
"""

from __future__ import annotations

import re

from ts_cli.formula_common import unique_count_formula
from ts_cli.formula_text import ts_finalize_formula, ts_string_literal
from ts_cli.powerbi.functions import (DAX_STRING, DISTINCTCOUNT_NOTE, _match_paren, _split_args,
                                      dax_col_refs, dax_string_value, plain_int64)

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
_EQ = re.compile(r"\s*=(?!=)\s*")                 # `=`, never `==`, `>=`, `<=`
_IN = re.compile(r"\s*IN\s*\{", re.I)
_WS = re.compile(r"\s*")


def _whole_call(src: str, fname: str) -> str | None:
    """The argument text when ``src`` is *entirely* one ``fname(...)`` call, else None.

    The first version searched for the call anywhere and discarded the rest, so
    ``DIVIDE(CALCULATE(...), DISTINCTCOUNT(...))`` silently became its own numerator.
    """
    s = src.strip()
    m = re.match(rf"^{fname}\s*\(", s, re.I)
    if not m:
        return None
    close = _match_paren(s, m.end() - 1)         # skips quoted text and [columns]
    return s[m.end():close] if close == len(s) - 1 else None


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
        i = _WS.match(s, i).end()                 # match, not slice: linear in the set size
        lit = _literal_at(s, i)
        if lit is None:
            return None
        vals.append(lit[:2])
        i = _WS.match(s, lit[2]).end()
        if s[i:i + 1] == ",":
            i += 1
        elif s[i:i + 1] == "}" and not s[i + 1:].strip():
            return vals
        else:
            return None


def _blank_equal(kind: str, value: str) -> bool:
    """DAX treats BLANK() = 0 and BLANK() = "" as TRUE, so a CALCULATE filter ``= 0`` or
    ``= ""`` also keeps blank rows, which ThoughtSpot's ``=`` drops (inferred from DAX
    semantics, not measured). Such a filter is refused rather than undercounted. DAX ``IN``
    compares strictly (BLANK does not match 0, per the CONTAINSROW reference), so this
    rationale does not hold for a value set; it is refused there too because refusing is
    safe and the shapes stay one rule."""
    return value == "" if kind == "str" else float(value) == 0


def _ts_values(vals) -> list[str] | None:
    """ThoughtSpot literal text for a value set, or None when it cannot be written
    exactly. DAX compares a mixed set as text (``IN {"a", 1}`` matches ``"1"``), so once
    any member is a string every member is emitted as one; an all-number set stays numeric.
    A number in a mixed set is accepted only as a plain 64-bit integer (``plain_int64``),
    because DAX converts it to text in its own canonical form: ``1.50`` compares as
    ``"1.5"``, ``1.0`` as ``"1"`` and ``01`` as ``"1"``, so emitting the digits as written
    would drop rows DAX counts."""
    if not any(k == "str" for k, _ in vals):
        return [v for _, v in vals]
    if any(k == "num" and not plain_int64(v) for k, v in vals):
        return None
    return [ts_string_literal(v) for _, v in vals]


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
    ts_vals = _compared_values(s, end)
    return ("in", tbl, col, ts_vals) if ts_vals else None


def _compared_values(s: str, end: int) -> list[str] | None:
    """ThoughtSpot literals for the ``= <literal>`` or ``IN {…}`` that follows the column
    ending at ``end`` and runs to the end of ``s``, else None: nothing else may follow, a
    BLANK-equal value refuses, and so does a mixed set that cannot be written exactly."""
    m = _IN.match(s, end)
    if m:
        vals = _value_set(s, m.end())
    else:
        m = _EQ.match(s, end)
        lit = _literal_at(s, m.end()) if m else None
        vals = [lit[:2]] if lit and not s[lit[2]:].strip() else None
    if not vals or any(_blank_equal(k, v) for k, v in vals):
        return None
    return _ts_values(vals)


def _filtered_cols(spec) -> set[tuple[str, str]]:
    """The columns a spec filters, casefolded: DAX names are case-insensitive, so
    ``Fact[s]`` and ``Fact[S]`` are one column and an inner filter on it still wins."""
    pairs = [(t, c) for t, c in spec["gates"]] + [(t, c) for t, c, _ in spec["cats"]]
    return {(t.casefold(), c.casefold()) for t, c in pairs}


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


# Each VAR definition runs up to the next VAR or the RETURN. parse_ratio anchors each one
# where the last ended (``match``, not ``finditer``: a leading ``\s*`` under finditer
# rescans a whitespace run from every start, which is quadratic), so nothing between
# definitions is skipped.
_VAR_DEF = re.compile(r"\s*\bVAR\s+(\w+)\s*=\s*(.*?)(?=\bVAR\b|\bRETURN\b)", re.I | re.S)
_COMMENT = re.compile(r"//|--|/\*")


def _has_comment(src: str) -> bool:
    """True when ``src`` holds a DAX comment outside a string literal. A comment can carry
    a whole commented-out VAR, so the measure is refused rather than read around it."""
    return bool(_COMMENT.search(DAX_STRING.sub('""', src)))


def parse_ratio(src: str):
    """``VAR a = … VAR b = … RETURN a/b`` -> (num, den), else None. The RETURN must be
    exactly one var divided by another: ``DIVIDE(a,b)``, ``1 - a/b`` and ``a/b*2`` are all
    refused, because each means something the emitted formula would not say."""
    s = src.strip()
    ret = re.search(r"\bRETURN\b(.*)$", s, re.I | re.S)
    if not re.match(r"^VAR\b", s, re.I) or not ret:
        return None
    variables, pos = {}, 0
    while pos < ret.start():
        m = _VAR_DEF.match(s, pos)
        if m is None or m.end() > ret.start() or m.group(1).lower() in variables:
            return None                    # text between definitions, or a VAR redefined
        variables[m.group(1).lower()] = m.group(2)
        pos = m.end()
    if not variables:
        return None
    div = re.fullmatch(r"\s*(\w+)\s*/\s*(\w+)\s*", ret.group(1))
    if not div:
        return None
    num, den = (parse_calculate(variables.get(div.group(i).lower(), "")) for i in (1, 2))
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
    if not conds:                     # USERELATIONSHIP only: a plain DISTINCTCOUNT (BL-540)
        return unique_count_formula(key, null_is_a_value=True)
    return f"unique_count_if ( {' and '.join(conds)} , {key} )"


_REL_NOTE = ("; the source uses USERELATIONSHIP, so a page slicing on the role-playing "
             "date needs a union fact keyed by measure, not this measure")
_NOTE = ("gated distinct count recognised from the DAX; CALCULATE REPLACES an existing "
         "filter on the filtered column while unique_count_if ANDs with it, so the two "
         "differ whenever the query filters that column, by grouping, a slicer, a page or "
         "a Liveboard filter (the emitted side live-probed, the Power BI side inferred); and "
         "DISTINCTCOUNT counts a blank key as one value while unique_count_if ignores NULL, "
         "so a key column with blanks can come out one lower")


def _note(specs, rel: bool) -> str:
    """The note for the emitted terms: the gated caveats for a ``unique_count_if`` term,
    the shared DISTINCTCOUNT caveat for an ungated one (USERELATIONSHIP only)."""
    gated = [bool(sp["gates"] or sp["cats"]) for sp in specs]
    parts = ([_NOTE] if any(gated) else []) + ([DISTINCTCOUNT_NOTE] if not all(gated) else [])
    return "; ".join(parts) + (_REL_NOTE if rel else "")


def translate(dax: str, home_table: str | None = None):
    """``(expr, "Approximated", note)``, or ``(None, None, None)`` when not these shapes."""
    src = (dax or "").strip()
    if not src or _has_comment(src):
        return None, None, None
    try:
        return _translate(src, home_table)
    except RecursionError:          # ~1,000 nested CALCULATEs: refuse, never abort the build
        return None, None, None


def _translate(src: str, home_table: str | None):
    """``translate`` past its comment check; ``parse_calculate`` recurses per nesting."""
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
        return (ts_finalize_formula(f"{a} / {b}"), "Approximated", _note((num, den), rel))

    spec = parse_calculate(src)
    if spec:
        home = home_table or spec["table"]
        expr = _count_expr(spec, home)
        if not expr:
            return None, None, None
        return (ts_finalize_formula(expr), "Approximated",
                _note((spec,), spec["userelationship"]))

    return None, None, None
