"""Databricks Metric View YAML -> structured dict (`ts databricks parse-mv`).

Pure functions: YAML text in, JSON-ready dict out. No I/O, no network calls —
trivially unit-testable. stdlib + PyYAML only (Genie-vendorable — see
package docstring).

Schema reference: agents/shared/schemas/databricks-metric-view.md.
Classification rules: agents/shared/mappings/ts-databricks/ts-from-databricks-rules.md.
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


def _split_fqn(s: str) -> list[str]:
    """Split a dotted identifier on '.', respecting backtick-quoted segments."""
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


_IDENT_SEGMENT_RE = re.compile(r"^[A-Za-z_][\w$]*$")


def classify_source(raw: str) -> dict | None:
    """Classify a `source:` value into one of the documented source forms.

    Returns {"kind": "sql_query", ...} or {"kind": "table_fqn", ...}, or None
    when the value matches neither (caller records an unsupported[] entry).
    An FQN cannot be distinguished from an MV-on-MV source offline, so every
    table_fqn carries needs_live_check: True — the SKILL step runs the live
    information_schema.tables check and fails loud on METRIC_VIEW.
    """
    stripped = raw.strip()
    if not stripped:
        return None
    low = stripped.lower()
    if low.startswith(("(select", "(with")) or low.startswith(("select ", "with ")):
        return {"kind": "sql_query", "raw": stripped,
                "parenthesized": stripped.startswith("(")}
    parts = _split_fqn(stripped)
    for part in parts:
        # A backtick-quoted segment (now unquoted by _split_fqn) may hold any
        # non-empty text; a bare segment must be a plain identifier.
        bare = part if "`" not in stripped else None
        if not part:
            return None
        if bare is not None and not _IDENT_SEGMENT_RE.match(part):
            return None
    return {"kind": "table_fqn", "raw": stripped,
            "parts": parts if len(parts) == 3 else None,
            "needs_live_check": True}


# ---------------------------------------------------------------------------
# Window spec (measures[].window) — all five range values live-verified
# 2026-07-08/09; see docs/audit/2026-07-08-dbx-window-claim-matrix.md and
# databricks-metric-view.md "Window with Offset".
# ---------------------------------------------------------------------------

_RANGE_FIXED = {"current", "cumulative", "all"}
_RANGE_RE = re.compile(
    r"^(trailing|leading)\s+(\d+)\s+([a-z]+)(?:\s+(inclusive|exclusive))?$")
_OFFSET_RE = re.compile(r"^(-\d+)\s+([a-z]+)$")
_WINDOW_KEYS = {"order", "range", "semiadditive", "offset"}
_SEMIADDITIVE_VALUES = {"last", "first"}


def parse_range(raw) -> dict | None:
    """Parse a window `range:` value into {type, n, unit, anchor}.

    Fixed types (current|cumulative|all) reject the inclusive/exclusive
    modifier; trailing/leading default to exclusive when it is omitted
    (live-verified C2, 2026-07-08).
    """
    s = str(raw).strip().lower()
    if s in _RANGE_FIXED:
        return {"type": s, "n": None, "unit": None, "anchor": None}
    m = _RANGE_RE.match(s)
    if not m:
        return None
    return {"type": m.group(1), "n": int(m.group(2)), "unit": m.group(3),
            "anchor": m.group(4) or "exclusive"}


def parse_offset(raw) -> dict | None:
    """Parse a window `offset:` value ('-N unit') into {n, unit}."""
    m = _OFFSET_RE.match(str(raw).strip().lower())
    if not m:
        return None
    return {"n": int(m.group(1)), "unit": m.group(2)}


def parse_window(window_val, measure_name: str) -> tuple[dict | None, list[str]]:
    """Parse a measure's `window:` block. Returns (window_dict, problems).

    On any problem returns (None, [messages]) — the caller records each
    message as an unsupported[] entry (fail loud, never a silent drop).
    density_check_required implements BL-098 item 1: trailing/leading frames
    are date-interval on Databricks but translate to row-positional
    moving_sum on ThoughtSpot — the numbers diverge on gapped data (E1).
    """
    problems: list[str] = []
    if (not isinstance(window_val, list) or len(window_val) != 1
            or not isinstance(window_val[0], dict)):
        return None, [f"measure '{measure_name}': window must be a "
                      f"single-entry list of mappings"]
    w = window_val[0]
    unknown = sorted(set(w) - _WINDOW_KEYS)
    if unknown:
        problems.append(f"measure '{measure_name}': unknown window key(s): "
                        f"{', '.join(unknown)}")
    order = w.get("order")
    if not order:
        problems.append(f"measure '{measure_name}': window missing required 'order'")
    raw_range = w.get("range")
    rng = parse_range(raw_range) if raw_range is not None else None
    if rng is None:
        problems.append(f"measure '{measure_name}': unrecognized window "
                        f"range: {raw_range!r}")
    semi = w.get("semiadditive")
    if semi not in _SEMIADDITIVE_VALUES:
        problems.append(f"measure '{measure_name}': window requires "
                        f"semiadditive last|first, got {semi!r}")
    raw_offset = w.get("offset")
    offset = None
    if raw_offset is not None:
        offset = parse_offset(raw_offset)
        if offset is None:
            problems.append(f"measure '{measure_name}': unrecognized window "
                            f"offset: {raw_offset!r}")
    if problems:
        return None, problems
    return {
        "order": order,
        "range": rng,
        "raw_range": str(raw_range).strip(),
        "semiadditive": semi,
        "offset": offset,
        "raw_offset": None if raw_offset is None else str(raw_offset).strip(),
        "density_check_required": rng["type"] in ("trailing", "leading"),
    }, []


# ---------------------------------------------------------------------------
# Expression classification — mirrors the decision trees in
# ts-from-databricks-rules.md (Dimension / Measure classification sections).
# Classification only; translation to TS formula text is PR 3's job.
# ---------------------------------------------------------------------------

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
