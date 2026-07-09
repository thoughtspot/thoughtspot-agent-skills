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


def _scan_string_literal(s: str, i: int) -> int:
    """Given s[i] == "'", return the index just past the literal's closing
    quote ('' is the escape; an unterminated literal runs to end-of-string)."""
    j = i + 1
    n = len(s)
    while j < n:
        if s[j] == "'":
            if j + 1 < n and s[j + 1] == "'":
                j += 2
                continue
            return j + 1
        j += 1
    return n


def strip_sql_comments(expr: str) -> str:
    """Strip -- line and /* */ block comments in a single quote-aware pass.

    String-literal contents are copied verbatim (comment markers inside
    literals are data, not comments); a `--` inside a `/* */` block is part
    of that block. Block comments are replaced with one space, line comments
    with nothing (both as before)."""
    out: list[str] = []
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch == "'":
            end = _scan_string_literal(expr, i)
            out.append(expr[i:end])
            i = end
        elif expr.startswith("--", i):
            while i < n and expr[i] != "\n":
                i += 1
        elif expr.startswith("/*", i):
            close = expr.find("*/", i + 2)
            out.append(" ")
            i = n if close == -1 else close + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out).strip()


def mask_string_literals(s: str) -> str:
    """Length-preserving mask: literal contents -> spaces, quotes kept.

    Keyword/shape regexes run against the mask; captured spans are sliced
    from the original (same length, so spans line up)."""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "'":
            end = _scan_string_literal(s, i)
            out.append("'" + " " * (end - i - 2) + "'" if end - i >= 2 else s[i:end])
            i = end
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def split_dot_path(s: str) -> list[str]:
    """Split a dotted identifier on '.', respecting backtick-quoted segments.

    Segments are returned WITHOUT their backticks. A quoted segment that
    itself contains a '.' cannot be normalized to a plain dot-path — callers
    must reject it (classify_measure_expr does, as unsupported).
    """
    parts: list[str] = []
    buf: list[str] = []
    in_backtick = False
    for ch in s:
        if ch == "`":
            in_backtick = not in_backtick
        elif ch == "." and not in_backtick:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


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
    """Split on `sep` at paren depth 0, outside string literals."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "'":
            end = _scan_string_literal(s, i)
            buf.append(s[i:end])
            i = end
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def extract_cross_refs(expr: str) -> tuple[list[str], list[str]]:
    """Return (MEASURE() names, ANY_VALUE() names) in source order."""
    e = strip_sql_comments(expr)
    masked = mask_string_literals(e)
    refs = [e[m.start(1):m.end(1)].strip("`")
            for m in _MEASURE_REF_RE.finditer(masked)]
    lod = [e[m.start(1):m.end(1)].strip("`")
           for m in _ANY_VALUE_RE.finditer(masked)]
    return refs, lod


def classify_dimension_expr(expr: str) -> dict:
    """Classify a dimension expr: direct | computed | lod_window | unsupported."""
    e = strip_sql_comments(expr)
    masked = mask_string_literals(e)
    if _SUBQUERY_RE.search(masked):
        return {"kind": "unsupported", "reason": "subquery in dimension expr"}
    m = _LOD_RE.match(masked)
    if m:
        inner_expr = e[m.start(2):m.end(2)].strip()
        partition_tail = e[m.start(3):m.end(3)]
        masked_inner = masked[m.start(2):m.end(2)]
        masked_tail = masked[m.start(3):m.end(3)]
        # Reject shapes _LOD_RE over-matches: running/frame windows
        # (ORDER BY / ROWS / RANGE / GROUPS in the OVER clause), argless
        # ranking functions, expressions spanning multiple windows, and
        # ordered-set aggregates (ORDER BY inside the AGG(...) argument
        # list itself, e.g. ARRAY_AGG(x ORDER BY y) OVER (...)) — these
        # have no group_aggregate analogue on ThoughtSpot.
        if (not inner_expr or _OVER_RE.search(masked_inner)
                or _WINDOW_EXTRAS_RE.search(masked_inner)
                or _WINDOW_EXTRAS_RE.search(masked_tail)):
            return {"kind": "unsupported",
                    "reason": "window function without the recognized "
                              "AGG(...) OVER (PARTITION BY ...) LOD shape"}
        return {"kind": "lod_window",
                "inner_agg": m.group(1).upper(),
                "inner_expr": inner_expr,
                "partition_by": _split_top_level(partition_tail)}
    if _OVER_RE.search(masked):
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
    masked = mask_string_literals(e)
    refs, lod = extract_cross_refs(e)
    out = {"expr_kind": None, "agg_function": None, "physical_ref": None,
           "distinct": False, "cross_refs": refs, "lod_refs": lod}
    if _SUBQUERY_RE.search(masked):
        out["expr_kind"] = "unsupported"
        out["reason"] = "subquery in measure expr"
        return out
    if _COUNT_STAR_RE.match(masked):
        out["expr_kind"] = "count_star"
        return out
    if _FILTER_WHERE_RE.search(masked):
        out["expr_kind"] = "conditional"
        return out
    if refs or lod:
        out["expr_kind"] = "complex_cross_measure"
        return out
    m = _SIMPLE_AGG_RE.match(masked)
    if m:
        agg = m.group(1).upper()
        distinct = bool(m.group(2))
        col = e[m.start(3):m.end(3)]
        if agg == "COUNT" and distinct:
            out["expr_kind"] = "count_distinct"
        else:
            out["expr_kind"] = "simple"
            out["agg_function"] = agg
            out["distinct"] = distinct
        segments = split_dot_path(col)
        if any("." in seg for seg in segments):
            out["expr_kind"] = "unsupported"
            out["reason"] = ("dot inside a backtick-quoted identifier — "
                             "cannot normalize to a plain dot-path")
            return out
        out["physical_ref"] = ".".join(segments)
        return out
    out["expr_kind"] = "complex"
    return out
