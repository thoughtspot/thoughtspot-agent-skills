"""Tile placement and note tiles for ``build-liveboard --target-model`` (pure, no I/O).

The Sisense columnar layout becomes the 12-column Liveboard grid: each layout column keeps its
share of the width, rows fill their column, and every tile stays inside the grid. Rich-text
widgets and tab-set titles become section-header note tiles.
"""
from __future__ import annotations

import html as _html
import re

_MIN_HEIGHT = {"KPI": 2, "GRID_TABLE": 6, "PIVOT_TABLE": 6}

_PX_PER_ROW = 55

_NOTE_BG = "rgb(0, 132, 169)"


def _strip_html(s: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)
    return _html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def note_tile(text: str) -> dict:
    """A section-header note tile (format copied from an exported Liveboard)."""
    safe = _html.escape(text)
    return {"html_parsed_string": (
        '<h2 class="theme-module__editor-h2" style="text-align: center;"><b><strong class="theme-module__editor-text-bold" '
        f'style="color: rgb(255, 255, 255); white-space: pre-wrap;">{safe}</strong></b></h2>'
        f'<div class="pinboard-note-tile-module__noteTileBg editor-module__bgNode" style="background-color: {_NOTE_BG};"></div>')}


def _tile_height(ct, px):
    return max(_MIN_HEIGHT.get(ct, 5), round((px or 0) / _PX_PER_ROW))


def _layout_rows(inv: dict, placed: dict) -> list:
    """Dashboard layout -> [(col_index, col_pct, [(oid, width_pct, height_px)])] keeping placed oids."""
    out = []
    for row in (inv.get("dashboard") or {}).get("layout") or []:
        items = [(it["oid"], it["width_pct"], it["height_px"]) for it in row["items"] if it["oid"] in placed]
        if items:
            out.append((row["col"], row["items"][0]["col_pct"], items))
    return out


def _row_widths(items: list, span: int, x: int) -> list:
    """Subcell widths filling ``span`` columns from ``x``, each at least 1 and inside the grid."""
    span = max(1, min(span, 12 - x))
    total = sum(w for _, w, _ in items) or 100
    widths = [max(1, round(span * w / total)) for _, w, _ in items]
    widths[-1] = max(1, span - sum(widths[:-1]))     # rows always fill their column
    return widths


def _place(inv: dict, placed: dict) -> list:
    """placed: oid -> {'kind','ct'}; -> [(oid, x, y, w, h)] on a 12-column grid. Widgets the
    layout does not mention are appended full-width at the end, in widget order."""
    tiles, y_of, x_of = [], {}, {}
    col_x = 0
    for ci, col_pct, items in _layout_rows(inv, placed):
        if ci not in x_of:
            x_of[ci] = col_x
            col_x += round(12 * col_pct / 100)
            y_of[ci] = 0
        x = x_of[ci] if x_of[ci] < 12 else 0
        widths = _row_widths(items, round(12 * col_pct / 100) or 12, x)
        h = max(1 if placed[oid]["kind"] == "note" else _tile_height(placed[oid]["ct"], px) for oid, _, px in items)
        for (oid, _, _), w in zip(items, widths):
            tiles.append((oid, x, y_of[ci], w, h if placed[oid]["kind"] != "note" else 1))
            x += w
        y_of[ci] += h
    seen = {t[0] for t in tiles}
    y = max(y_of.values(), default=0)
    for oid, p in placed.items():
        if oid not in seen:
            h = 1 if p["kind"] == "note" else _tile_height(p["ct"], 0) + 2
            tiles.append((oid, 0, y, 12, h))
            y += h
    return tiles


def _note_text(w: dict, inv: dict) -> str:
    text = w.get("title") if w.get("wtype") == "WidgetsTabber" else _strip_html((w.get("richtext") or {}).get("html"))
    return text or (inv.get("dashboard") or {}).get("title") or ""
