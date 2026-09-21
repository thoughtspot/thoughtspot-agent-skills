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

Row-local. Power BI would show 3812 in *every* row, because CALCULATE drops the grouping
filter on that column. The numbers agree only when the board does not group by it, so the
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
from ts_cli.powerbi.functions import _split_args, dax_col_refs

_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


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


def _sole_ref(text: str) -> tuple[str, str] | None:
    """The one qualified column in ``text``, or None if there are none or several.

    Uses the repo's single DAX-qualifier reader, so ``'Bob''s Sales'[g]`` survives.
    """
    refs = dax_col_refs(text)
    return (refs[0][2], refs[0][3]) if len(refs) == 1 else None


def _literal(token: str) -> str | None:
    """One IN-set member as ThoughtSpot formula text: a string literal or a number."""
    t = token.strip()
    if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
        return ts_string_literal(re.sub(r"\\(.)", r"\1", t[1:-1]))
    return t if _NUM.match(t) else None


def _parse_filter(arg: str):
    """One CALCULATE argument -> a typed tuple, or None when not fully recognised.

    Every branch matches the WHOLE argument. Anchoring only the start let
    ``NOT ISBLANK(T[g]) && T[qty] > 5`` keep the first predicate and drop the second.
    """
    s = arg.strip()
    if re.fullmatch(r"USERELATIONSHIP\s*\(.*\)", s, re.I | re.S):
        return ("userelationship", None, None, None)
    m = re.fullmatch(r"NOT\s*\(?\s*ISBLANK\s*\((.*)\)\s*\)?", s, re.I | re.S)
    if m:
        ref = _sole_ref(m.group(1))
        return ("notnull", ref[0], ref[1], None) if ref else None
    m = re.fullmatch(r"(.*?)\s+IN\s*\{(.*)\}", s, re.I | re.S)
    if m:
        ref = _sole_ref(m.group(1))
        if not ref:
            return None
        vals = [_literal(v) for v in _split_args(m.group(2))]
        return ("in", ref[0], ref[1], vals) if vals and all(vals) else None
    m = re.fullmatch(r"(.*?)\s*=\s*(.+)", s, re.S)
    if m:
        ref, val = _sole_ref(m.group(1)), _literal(m.group(2))
        return ("in", ref[0], ref[1], [val]) if ref and val else None
    return None


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
        if dc is None:
            return None
        ref = _sole_ref(dc)
        if not ref:
            return None
        table, key = ref
        gates, cats, rel = [], [], False
    for arg in args[1:]:
        parsed = _parse_filter(arg)
        if parsed is None:
            return None                        # unread filter: refuse the whole shape
        kind, tbl, col, vals = parsed
        if kind == "userelationship":
            rel = True
        elif kind == "notnull":
            gates.append((tbl, col))
        else:
            cats.append((tbl, col, vals))
    return {"table": table, "key": key, "gates": gates, "cats": cats,
            "userelationship": rel}


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
