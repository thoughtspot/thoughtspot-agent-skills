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
