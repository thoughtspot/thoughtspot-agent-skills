"""Metric View window-spec parsing (measures[].window).

Pure functions: window block in, parsed dict out. No I/O, no network calls —
trivially unit-testable. stdlib only (Genie-vendorable — see package
docstring).

All five range values live-verified 2026-07-08/09; see
docs/audit/2026-07-08-dbx-window-claim-matrix.md and
agents/shared/schemas/databricks-metric-view.md "Window with Offset".
density_check_required implements BL-098 item 1 (date-interval vs
row-positional frame divergence on gapped data).
"""
from __future__ import annotations

import re

_RANGE_FIXED = {"current", "cumulative", "all"}
_RANGE_RE = re.compile(
    r"^(trailing|leading)\s+(\d+)\s+([a-z]+)(?:\s+(inclusive|exclusive))?$")
_OFFSET_RE = re.compile(r"^(-\d+)\s+([a-z]+)$")
_WINDOW_KEYS = {"order", "range", "semiadditive", "offset"}
_SEMIADDITIVE_VALUES = {"last", "first"}
_VALID_UNITS = {"day", "week", "month", "quarter", "year"}


def parse_range(raw) -> dict | None:
    """Parse a window `range:` value into {type, n, unit, anchor}.

    Fixed types (current|cumulative|all) reject the inclusive/exclusive
    modifier; trailing/leading default to exclusive when it is omitted
    (live-verified C2, 2026-07-08). n == 0 and units outside _VALID_UNITS
    are rejected — a zero-length or unrecognized-unit window has no
    meaningful ThoughtSpot translation.
    """
    s = str(raw).strip().lower()
    if s in _RANGE_FIXED:
        return {"type": s, "n": None, "unit": None, "anchor": None}
    m = _RANGE_RE.match(s)
    if not m:
        return None
    n = int(m.group(2))
    if n == 0 or m.group(3) not in _VALID_UNITS:
        return None
    return {"type": m.group(1), "n": n, "unit": m.group(3),
            "anchor": m.group(4) or "exclusive"}


def parse_offset(raw) -> dict | None:
    """Parse a window `offset:` value ('-N unit') into {n, unit}.

    n == 0 and units outside _VALID_UNITS are rejected (see parse_range).
    """
    m = _OFFSET_RE.match(str(raw).strip().lower())
    if not m:
        return None
    n = int(m.group(1))
    if n == 0 or m.group(2) not in _VALID_UNITS:
        return None
    return {"n": n, "unit": m.group(2)}


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
    unknown = sorted(str(k) for k in set(w) - _WINDOW_KEYS)
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
