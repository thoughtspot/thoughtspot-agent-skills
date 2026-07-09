"""Metric View dimension/measure SQL expression classification.

Pure functions: expression text in, classification dict out. No I/O, no
network calls — trivially unit-testable. stdlib only (Genie-vendorable —
see package docstring).

Classification rules: agents/shared/mappings/ts-databricks/ts-from-databricks-rules.md
(Dimension / Measure classification sections). Classification only;
translation to TS formula text is PR 3's job.
"""
from __future__ import annotations

import re

_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_sql_comments(expr: str) -> str:
    """Strip -- line and /* */ block comments before classification.

    Naive w.r.t. comment markers inside string literals — acceptable per the
    rules file (classification only; the raw expr is preserved separately).
    """
    return _BLOCK_COMMENT_RE.sub(" ", _LINE_COMMENT_RE.sub("", expr)).strip()


_IDENT = r"(?:`[^`]+`|[A-Za-z_][\w$]*)"
_DOT_PATH = rf"{_IDENT}(?:\.{_IDENT})*"
_DIRECT_RE = re.compile(rf"^{_DOT_PATH}$")
_LOD_RE = re.compile(
    r"^([A-Za-z_]\w*)\s*\((.*)\)\s+OVER\s*\(\s*PARTITION\s+BY\s+(.+)\)\s*$",
    re.IGNORECASE | re.DOTALL)
_OVER_RE = re.compile(r"\bOVER\s*\(", re.IGNORECASE)
_SUBQUERY_RE = re.compile(r"\(\s*SELECT\b", re.IGNORECASE)
_COUNT_STAR_RE = re.compile(r"^COUNT\s*\(\s*\*\s*\)$", re.IGNORECASE)
_FILTER_WHERE_RE = re.compile(r"\bFILTER\s*\(\s*WHERE\b", re.IGNORECASE)
_SIMPLE_AGG_RE = re.compile(
    rf"^([A-Za-z_]\w*)\s*\(\s*(DISTINCT\s+)?({_DOT_PATH})\s*\)$",
    re.IGNORECASE)
_MEASURE_REF_RE = re.compile(r"\bMEASURE\s*\(\s*(`[^`]+`|[A-Za-z_]\w*)\s*\)",
                             re.IGNORECASE)
_ANY_VALUE_RE = re.compile(r"\bANY_VALUE\s*\(\s*(`[^`]+`|[A-Za-z_]\w*)\s*\)",
                           re.IGNORECASE)
_WINDOW_EXTRAS_RE = re.compile(r"\b(ORDER\s+BY|ROWS|RANGE|GROUPS)\b", re.IGNORECASE)


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    """Split on `sep` at paren depth 0 (partition lists may contain calls)."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def extract_cross_refs(expr: str) -> tuple[list[str], list[str]]:
    """Return (MEASURE() names, ANY_VALUE() names) in source order."""
    e = strip_sql_comments(expr)
    refs = [m.group(1).strip("`") for m in _MEASURE_REF_RE.finditer(e)]
    lod = [m.group(1).strip("`") for m in _ANY_VALUE_RE.finditer(e)]
    return refs, lod


def classify_dimension_expr(expr: str) -> dict:
    """Classify a dimension expr: direct | computed | lod_window | unsupported."""
    e = strip_sql_comments(expr)
    if _SUBQUERY_RE.search(e):
        return {"kind": "unsupported", "reason": "subquery in dimension expr"}
    m = _LOD_RE.match(e)
    if m:
        inner_expr = m.group(2).strip()
        partition_tail = m.group(3)
        # Reject shapes _LOD_RE over-matches: running/frame windows
        # (ORDER BY / ROWS / RANGE / GROUPS in the OVER clause), argless
        # ranking functions, and expressions spanning multiple windows.
        if (not inner_expr or _OVER_RE.search(inner_expr)
                or _WINDOW_EXTRAS_RE.search(partition_tail)):
            return {"kind": "unsupported",
                    "reason": "window function without the recognized "
                              "AGG(...) OVER (PARTITION BY ...) LOD shape"}
        return {"kind": "lod_window",
                "inner_agg": m.group(1).upper(),
                "inner_expr": inner_expr,
                "partition_by": _split_top_level(partition_tail)}
    if _OVER_RE.search(e):
        return {"kind": "unsupported",
                "reason": "window function without the recognized "
                          "AGG(...) OVER (PARTITION BY ...) LOD shape"}
    if _DIRECT_RE.match(e):
        return {"kind": "direct"}
    return {"kind": "computed"}


def classify_measure_expr(expr: str) -> dict:
    """Classify a measure expr per the rules-file decision tree.

    expr_kind: simple | count_distinct | count_star | conditional |
    complex_cross_measure | complex | unsupported. cross_refs/lod_refs are
    always recorded (PR 3's dependency DAG reads them on every kind).
    """
    e = strip_sql_comments(expr)
    refs, lod = extract_cross_refs(e)
    out = {"expr_kind": None, "agg_function": None, "physical_ref": None,
           "distinct": False, "cross_refs": refs, "lod_refs": lod}
    if _SUBQUERY_RE.search(e):
        out["expr_kind"] = "unsupported"
        out["reason"] = "subquery in measure expr"
        return out
    if _COUNT_STAR_RE.match(e):
        out["expr_kind"] = "count_star"
        return out
    if _FILTER_WHERE_RE.search(e):
        out["expr_kind"] = "conditional"
        return out
    if refs or lod:
        out["expr_kind"] = "complex_cross_measure"
        return out
    m = _SIMPLE_AGG_RE.match(e)
    if m:
        agg = m.group(1).upper()
        distinct = bool(m.group(2))
        col = m.group(3)
        if agg == "COUNT" and distinct:
            out["expr_kind"] = "count_distinct"
        else:
            out["expr_kind"] = "simple"
            out["agg_function"] = agg
            out["distinct"] = distinct
        out["physical_ref"] = col
        return out
    out["expr_kind"] = "complex"
    return out
