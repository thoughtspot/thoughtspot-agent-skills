"""Match warehouse query-history GROUP BY shapes to signatures (pure, no I/O)."""
from __future__ import annotations

import re

_GROUP_BY = re.compile(r"group\s+by\s+(.+?)(?:\border\b|\bhaving\b|\blimit\b|;|$)",
                       re.I | re.S)


def extract_group_by(sql: str) -> list:
    """Pull the column list out of a SQL statement's GROUP BY clause.

    Returns physical `TABLE.COL` tokens (upper-cased, quotes stripped) in
    declaration order. Non-identifier tokens (expressions, ordinals, etc.)
    are dropped rather than guessed at — a partial match is safer than a
    wrong one for weighting signatures.
    """
    m = _GROUP_BY.search(sql or "")
    if not m:
        return []
    cols = []
    for part in m.group(1).split(","):
        token = part.strip().strip('"`').upper()
        if re.fullmatch(r"[A-Z0-9_.\"]+", token):
            cols.append(token.replace('"', ""))
    return cols


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
        display = {colmap.get(c) for c in extract_group_by(row.get("query_text", ""))}
        display.discard(None)
        if not display:
            continue
        for s in signatures:
            key = f"{s['source_guid']}::{s.get('viz_name') or ''}"
            sig_dims = set(s["dimensions"]) | ({s["date_column"]}
                                               if s.get("date_column") else set())
            if display == sig_dims or display == set(s["dimensions"]):
                weights[key] = weights.get(key, 0.0) + 1.0
    return weights
