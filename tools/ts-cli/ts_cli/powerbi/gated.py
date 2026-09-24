"""Power BI gated-count and gated-ratio measures -> ThoughtSpot formulas.

`translate_dax` refuses anything containing CALCULATE, USERELATIONSHIP or VAR/RETURN,
which is right for filter-context work in general and wrong for two shapes that carry
most on-time / in-tolerance / hit-rate reporting. Both are fully described by the DAX
itself, so recognising them turns a measure a human had to retype into one the converter
migrates:

    CALCULATE(DISTINCTCOUNT(T[key]), NOT ISBLANK(T[gate]))
        -> unique count (if ([T::gate] != null) then [T::key] else null)

    VAR a = CALCULATE(DISTINCTCOUNT(T[key]), NOT ISBLANK(T[g1]), T[stage] IN {"x","y"})
    VAR b = CALCULATE(DISTINCTCOUNT(T[key]), NOT ISBLANK(T[g2]))
    RETURN a/b
        -> (unique count (if ([T::g1] != null and ([T::stage] = 'x' or [T::stage] = 'y'))
            then [T::key] else null)) / (unique count (if ([T::g2] != null)
            then [T::key] else null))

Measured on a real 27-measure report: 17 recognised here, and the 8 that stay NEEDS
REVIEW are dynamic-text captions with no ThoughtSpot tile equivalent. Nothing is guessed
— a filter argument this module does not understand makes it refuse the whole shape.

The emitted aggregation is `unique count`, with the space. BL-171 records `unique_count`
as a name the formula parser rejects; the spaced form is the one that binds, live-verified.
"""

from __future__ import annotations

import re

from ts_cli.powerbi.functions import _split_args

_REF = r"(?:'([^']+)'|(\w+))\s*\[([^\]]+)\]"


def _body(src, fname):
    """The argument text of the first fname(...) call, or None."""
    m = re.search(rf"\b{fname}\s*\(", src, re.I)
    if not m:
        return None
    i, depth = m.end(), 1
    while i < len(src) and depth:
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
        i += 1
    return src[m.end():i - 1] if depth == 0 else None


def _ref(text):
    m = re.search(_REF, text or "")
    return (m.group(1) or m.group(2), m.group(3)) if m else (None, None)


def _parse_filter(arg):
    """One CALCULATE filter argument -> a typed tuple, or None if not understood."""
    s = arg.strip()
    if re.match(r"^\s*USERELATIONSHIP\s*\(", s, re.I):
        return ("userelationship", None, None, None)
    if re.match(r"^\s*NOT\s+ISBLANK\s*\(", s, re.I) or re.match(r"^\s*NOT\s*\(\s*ISBLANK", s, re.I):
        table, col = _ref(s)
        return ("notnull", table, col, None) if col else None
    m = re.match(rf"^\s*{_REF}\s+IN\s*\{{(.+)\}}\s*$", s, re.I | re.S)
    if m:
        vals = re.findall(r'"([^"]*)"', m.group(4))
        return ("in", m.group(1) or m.group(2), m.group(3), vals) if vals else None
    m = re.match(rf'^\s*{_REF}\s*=\s*"([^"]*)"\s*$', s, re.S)
    if m:
        return ("in", m.group(1) or m.group(2), m.group(3), [m.group(4)])
    return None


def parse_calculate(src):
    """CALCULATE(DISTINCTCOUNT(T[key]), <filters>) -> dict, or None if not that shape."""
    body = _body(src, "CALCULATE")
    if body is None:
        return None
    args = _split_args(body)
    if not args:
        return None
    # CALCULATE(CALCULATE(DISTINCTCOUNT(..), <gate>), USERELATIONSHIP(..)) is common and
    # puts the gate on the INNER call. Recursing and merging is the difference between
    # keeping that filter and silently widening the counted population.
    if re.match(r"^\s*CALCULATE\s*\(", args[0], re.I):
        inner = parse_calculate(args[0])
        if inner is None:
            return None
        table, key = inner["table"], inner["key"]
        gates, cats, rel = list(inner["gates"]), list(inner["categories"]), inner["userelationship"]
    else:
        dc = _body(args[0], "DISTINCTCOUNT")
        if dc is None:
            return None
        table, key = _ref(dc)
        if not key:
            return None
        gates, cats, rel = [], [], False
    for arg in args[1:]:
        parsed = _parse_filter(arg)
        if parsed is None:
            return None          # a filter we cannot read: refuse the whole shape
        kind, tbl, col, vals = parsed
        if kind == "userelationship":
            rel = True
        elif kind == "notnull":
            gates.append((tbl or table, col))
        elif kind == "in":
            cats.append((tbl or table, col, vals))
    return {"table": table, "key": key, "gates": gates, "categories": cats,
            "userelationship": rel}


def parse_ratio(src):
    """VAR a = CALCULATE(..) VAR b = CALCULATE(..) RETURN a/b -> (num, den) or None."""
    variables = dict(re.findall(r"\bVAR\s+(\w+)\s*=\s*(.*?)(?=\bVAR\b|\bRETURN\b)",
                                src, re.I | re.S))
    ret = re.search(r"\bRETURN\b(.*)$", src, re.I | re.S)
    if not variables or not ret:
        return None
    div = re.match(r"^\s*(\w+)\s*/\s*(\w+)\s*$", ret.group(1).strip())
    if not div:
        return None
    num_src, den_src = variables.get(div.group(1)), variables.get(div.group(2))
    if not (num_src and den_src):
        return None
    num, den = parse_calculate(num_src), parse_calculate(den_src)
    return (num, den) if num and den else None


def _count_expr(spec, table):
    conds = [f"[{table}::{col}] != null" for _, col in spec["gates"]]
    for _, col, vals in spec["categories"]:
        ors = " or ".join(f"[{table}::{col}] = '{v}'" for v in vals)
        conds.append(f"({ors})" if len(vals) > 1 else ors)
    if not conds:
        return f"unique count ([{table}::{spec['key']}])"
    return (f"unique count (if ({' and '.join(conds)}) "
            f"then [{table}::{spec['key']}] else null)")


def translate(dax, home_table=None):
    """(expr, status, note), or (None, None, None) when the DAX is not one of these shapes.

    USERELATIONSHIP yields Approximated rather than Migrated. The measure is correct for
    the grain, and wrong for a page slicing on the role-playing date, because a model
    cannot rewire which date the filter context applies to. Saying so is more use than a
    silent Migrated.
    """
    src = (dax or "").strip()
    if not src:
        return None, None, None

    pair = parse_ratio(src)
    if pair:
        num, den = pair
        if num["key"] != den["key"]:
            return None, None, None
        table = home_table or num["table"]
        expr = f"({_count_expr(num, table)}) / ({_count_expr(den, table)})"
        note = "gated ratio over a distinct count, recognised from the DAX"
        if num["userelationship"] or den["userelationship"]:
            return expr, "Approximated", note + _REL_NOTE
        return expr, "Migrated", note

    spec = parse_calculate(src)
    if spec:
        table = home_table or spec["table"]
        note = "gated distinct count, recognised from the DAX"
        if spec["userelationship"]:
            return _count_expr(spec, table), "Approximated", note + _REL_NOTE
        return _count_expr(spec, table), "Migrated", note

    return None, None, None


_REL_NOTE = ("; the source uses USERELATIONSHIP, so a page slicing on the role-playing "
             "date needs a union fact keyed by measure, not this measure")


def describe(dax):
    """The shape's parameters, for KPI discovery. None when it is not one of these."""
    pair = parse_ratio(dax or "")
    if pair:
        num, den = pair
        cat = num["categories"][0] if num["categories"] else (None, None, None)
        return {"shape": "ratio", "key": num["key"], "table": num["table"],
                "numerator_gate": num["gates"][0][1] if num["gates"] else None,
                "denominator_gate": den["gates"][0][1] if den["gates"] else None,
                "stage_col": cat[1], "on_time_values": cat[2],
                "userelationship": num["userelationship"] or den["userelationship"]}
    spec = parse_calculate(dax or "")
    if spec:
        return {"shape": "count", "key": spec["key"], "table": spec["table"],
                "numerator_gate": spec["gates"][0][1] if spec["gates"] else None,
                "denominator_gate": None,
                "stage_col": spec["categories"][0][1] if spec["categories"] else None,
                "on_time_values": spec["categories"][0][2] if spec["categories"] else None,
                "userelationship": spec["userelationship"]}
    return None
