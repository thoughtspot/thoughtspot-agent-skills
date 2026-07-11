"""Match warehouse query-history GROUP BY shapes to signatures (pure, no I/O)."""
from __future__ import annotations

import re

_GROUP_BY = re.compile(r"group\s+by\s+(.+?)(?:\border\b|\bhaving\b|\blimit\b|;|$)",
                       re.I | re.S)


def extract_group_by(sql: str) -> tuple:
    """Pull the column list out of a SQL statement's GROUP BY clause.

    Returns `(columns, had_dropped)`:
      - `columns`: physical `TABLE.COL` tokens (upper-cased, quotes stripped) in
        declaration order — only bare identifiers survive.
      - `had_dropped`: True if any GROUP BY term was NOT a bare identifier
        (a function call like `date_trunc(...)`, a CASE expression, an ordinal,
        etc.) and was therefore dropped. This flag is load-bearing for matching:
        a dropped term almost always means the query grouped by a date bucket
        (`date_trunc('MONTH', d)`) we can't name, so the identifiers we *did*
        extract are only the non-date dimensions. `match_history` uses it to
        avoid crediting a date-bucketed query to a coarser, dateless signature.
    """
    m = _GROUP_BY.search(sql or "")
    if not m:
        return [], False
    cols = []
    had_dropped = False
    for part in m.group(1).split(","):
        token = part.strip().strip('"`').upper()
        if re.fullmatch(r"[A-Z0-9_.\"]+", token):
            cols.append(token.replace('"', ""))
        elif token:
            had_dropped = True
    return cols, had_dropped


def _signature_matches(display: set, had_dropped: bool, sig: dict) -> bool:
    """Does a history row's parsed GROUP BY shape match this signature's grain?

    `display` is the set of Model display names for the identifiers we could
    parse out of the query's GROUP BY. Two regimes:

      - `had_dropped` False (we parsed the whole clause): exact set-equality —
        the parsed dims equal either the signature's dims+date, or its dims
        alone. Unchanged legacy behaviour.
      - `had_dropped` True (an unparseable term, ~always a date bucket, was
        dropped): the query is date-grained, so only credit signatures that
        HAVE a date_column, and only when the parsed identifiers equal that
        signature's NON-date dimensions. A dateless signature must NOT be
        credited — that was the over-matching bug (date-bucketed queries, the
        common case, inflating the coarser grain).
    """
    dims = set(sig["dimensions"])
    if had_dropped:
        return bool(sig.get("date_column")) and display == dims
    sig_dims = dims | ({sig["date_column"]} if sig.get("date_column") else set())
    return display == sig_dims or display == dims


def match_history(rows: list, signatures: list, colmap: dict) -> dict:
    """Weight each signature by base occurrence (1.0) + matching history rows.

    `rows` are `{"query_text": str}` dicts from warehouse query history.
    `colmap` maps physical `TABLE.COL` (upper) -> the Model's display name,
    so a history row's GROUP BY shape can be compared against a signature's
    `dimensions` (+ `date_column`, both display names).

    Keyed `"{source_guid}::{viz_name or ''}"` — matches the key `recommend`'s
    `_apply_weights` reads from `history`'s `weights.json` output.
    """
    weights = {}
    for s in signatures:
        key = f"{s['source_guid']}::{s.get('viz_name') or ''}"
        weights[key] = weights.get(key, 0.0) + 1.0  # base weight
    for row in rows:
        cols, had_dropped = extract_group_by(row.get("query_text", ""))
        display = {colmap.get(c) for c in cols}
        display.discard(None)
        if not display:
            continue
        for s in signatures:
            if _signature_matches(display, had_dropped, s):
                key = f"{s['source_guid']}::{s.get('viz_name') or ''}"
                weights[key] = weights.get(key, 0.0) + 1.0
    return weights
