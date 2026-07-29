"""render_check — decide whether an imported Liveboard actually renders.

A Liveboard TML can import cleanly (valid structure, resolvable column names) yet
still fail at query time — most commonly with "No data source found for the query"
when a stored answer was hand-authored and its tiles are not bound the way the engine
expects. `ts tml import` returns success in that case; the break only shows when the
board is asked for data. This module classifies a `metadata/liveboard/data` response
so a skill can gate on "does it render", not merely "did it import".

Pure functions, no I/O — the command layer (`commands/tml.py verify-render`) does the
POSTs and feeds the responses here. Kept pure so the classification is unit-tested
without a live cluster.
"""
from __future__ import annotations

import json
from typing import Any, Optional


def extract_error(body: Any) -> Optional[str]:
    """Pull the human-readable message out of a ThoughtSpot v2 error body.

    The render error nests as ``error.message.debug.debug``, a JSON-encoded list whose
    first element carries ``Error Code: <CODE> Incident Id: <guid>\\nError Message: <msg>``.
    Return the ``Error Message:`` text when present (the actionable part), else the
    deepest string we can find, else a short repr. Never raises."""
    if not isinstance(body, dict):
        return str(body)[:300] if body else None
    err = body.get("error")
    if err is None:
        return None
    # Walk the documented nesting defensively — any level may be absent or a plain string.
    node: Any = err
    for key in ("message", "debug", "debug"):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            break
    text = node if isinstance(node, str) else json.dumps(err)[:300]
    # The debug string is often a JSON list like ["Error Code: ... Error Message: X", ""].
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and parsed:
            text = str(parsed[0])
    except (ValueError, TypeError):
        pass
    marker = "Error Message:"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return text.strip()[:300] or None


def classify_render(status_code: int, body: Any) -> dict:
    """One `liveboard/data` response (whole board or a single viz) -> render verdict.

    ``{"rendered": bool, "tiles": int, "error": str|None}``. A 200 with a ``contents``
    array renders; anything else is a failure carrying the extracted message."""
    if status_code == 200 and isinstance(body, dict):
        contents = body.get("contents")
        if isinstance(contents, list) and contents:
            return {"rendered": True, "tiles": len(contents), "error": None}
        if isinstance(contents, list):
            # 200 with an empty contents array: nothing rendered. Reporting ok:true with
            # tiles_rendered:0 would be a confusing gate pass, so treat it as a failure.
            return {"rendered": False, "tiles": 0, "error": "no visualization data returned"}
    return {"rendered": False, "tiles": 0, "error": extract_error(body)}


def render_summary(board_guid: str, board: dict, per_viz: Optional[list] = None) -> dict:
    """Assemble the command's stdout JSON contract.

    ``per_viz`` is a list of ``{"visual": name, ...classify_render()}`` probed only when
    the whole-board fetch failed, so the caller can name the offending tile(s) rather
    than report a bare board-level 500."""
    failing = [v for v in (per_viz or []) if not v.get("rendered")]
    return {
        "ok": bool(board.get("rendered")),
        "board": board_guid,
        "tiles_rendered": board.get("tiles", 0),
        "error": board.get("error"),
        "failing_tiles": [{"visual": v.get("visual"), "error": v.get("error")} for v in failing],
    }
