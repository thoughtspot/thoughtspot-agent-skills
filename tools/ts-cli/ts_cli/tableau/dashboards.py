"""Dashboard/visual extraction from a Tableau workbook (open item #20).

Turns each `<dashboard>` into the `build_from_spec` dashboard shape (visuals with
mark + fields tagged by shelf/role/measure + date bucket tokens + a grid tile), so
`ts tableau parse` → `ts tableau build-liveboard` runs with no hand-assembled spec.
This is the codification of the previously agent-driven Tableau liveboard step (the
FedEx-harness `build_fedex_liveboard_*.py` method). Pure functions, no I/O.
"""
from __future__ import annotations

import re
from typing import Optional
import xml.etree.ElementTree as ET

from ts_cli.tableau.liveboard import leaf_name, role_for_shelf

# Tableau derivation → aggregate? (drives measure detection) and → date bucket keyword.
_AGG = {"Sum", "Avg", "Average", "Count", "Cnt", "CntD", "Min", "Max", "Median",
        "Stdev", "Stdevp", "Var", "Varp", "Attr"}
_TRUNC = {"Month-Trunc": "monthly", "Year-Trunc": "yearly", "Quarter-Trunc": "quarterly",
          "Week-Trunc": "weekly", "Day-Trunc": "daily", "Hour-Trunc": "hourly"}


def _instances(ws: ET.Element) -> dict:
    return {c.get("name"): c for c in ws.findall(".//datasource-dependencies/column-instance")}


def _shelf_refs(text: Optional[str]) -> list[str]:
    """Pull the `[inst]` keys out of a shelf's `([ds].[inst] * [ds].[inst] ...)` text."""
    return re.findall(r"\]\.(\[[^\]]+\])", text or "")


def _resolve(inst_key: str, ci: dict, captions: dict) -> Optional[dict]:
    c = ci.get(inst_key)
    if c is None:
        return None
    raw = c.get("column")                         # e.g. [Tailgating Events (copy)_NNN] or [sales]
    name = captions.get(raw) or leaf_name(raw)    # resolve calc-id → display caption
    if not name:
        return None
    deriv = c.get("derivation") or "None"
    bucket = _TRUNC.get(deriv)
    # measure iff aggregated, or a quantitative field that isn't a date bucket
    measure = (deriv in _AGG) or (c.get("type") == "quantitative" and not bucket)
    return {"name": name, "measure": measure, "bucket": bucket}


def _topn_sets(root: ET.Element) -> dict:
    """Top/bottom-N Tableau sets → {set_name: count}.

    A ranked set is a `<group ui-builder="filter-group">` whose nested `<groupfilter
    function="end">` carries `end="top"|"bottom"` and a record `count` — e.g.
    `[Driver Name Set 2]` = top 5 drivers by SUM(events). We keep the count; ThoughtSpot's
    `top N` search keyword reproduces the limit, ranked by the query's measure.
    """
    sets: dict[str, int] = {}
    for g in root.iter("group"):
        name = g.get("name")
        end = g.find(".//groupfilter[@function='end']")
        if not name or end is None:
            continue
        count = end.get("count")
        if end.get("end") in ("top", "bottom") and count and count.isdigit():
            sets[name] = int(count)
    return sets


def _visual_top_n(ws: ET.Element, topn_sets: dict) -> Optional[int]:
    """The top-N count if this worksheet filters on a ranked set, else None.

    A worksheet references a set either directly (`[ds].[Driver Name Set 2]`) or via the
    in/out membership form (`[ds].[io:Driver Name Set:nk]`); both resolve to the same set.
    """
    for f in ws.findall(".//filter"):
        col = f.get("column") or ""
        m = re.search(r"\]\.(\[[^\]]+\])$", col)   # trailing [Set Name] of [ds].[Set Name]
        if not m:
            continue
        key = m.group(1)
        io = re.match(r"\[io:(.+):[a-z]+\]$", key)  # unwrap [io:Driver Name Set:nk] → [Driver Name Set]
        if io:
            key = f"[{io.group(1)}]"
        if key in topn_sets:
            return topn_sets[key]
    return None


def _enc_ref(enc: ET.Element) -> Optional[str]:
    """The `[inst]` key an encoding points at, e.g. color/text → `[none:NORMALIZEDDAYS:ok]`."""
    m = re.search(r"\]\.(\[[^\]]+\])", enc.get("column") or "")
    return m.group(1) if m else None


def _ws_fields(ws: ET.Element, ci: dict, captions: dict) -> tuple[list, dict]:
    """(fields, bucket_tokens) for a worksheet, in shelf order.

    Primary fields come from cols/rows/color and the Measure Values construct. `text`/`label`
    encodings are used only as a **fallback** when nothing else resolved — a value-only KPI
    (e.g. Normalised Days) carries its single value on `text`, but reading text unconditionally
    would also drag in decorative label calcs (sheet-name titles, `''` spacers) onto every KPI.
    """
    fields: list[dict] = []
    bucket_tokens: dict[str, str] = {}
    seen: set[str] = set()

    def add(inst_key: str, shelf: str) -> None:
        f = _resolve(inst_key, ci, captions)
        if not f or f["name"] in seen:
            return
        seen.add(f["name"])
        fields.append({"name": f["name"], "measure": f["measure"],
                       "role": role_for_shelf(shelf, f["measure"])})
        if f["bucket"]:
            bucket_tokens[f["name"]] = f"[{f['name']}].{f['bucket']}"

    cols_el, rows_el = ws.find(".//table/cols"), ws.find(".//table/rows")
    cols_text = (cols_el.text if cols_el is not None else "") or ""
    rows_text = (rows_el.text if rows_el is not None else "") or ""
    for k in _shelf_refs(cols_text):
        add(k, "cols")
    for k in _shelf_refs(rows_text):
        add(k, "rows")
    for enc in ws.findall(".//encodings/color"):
        if _enc_ref(enc):
            add(_enc_ref(enc), "color")
    # Measure Values: the shelf holds [Multiple Values]/[:Measure Names] pseudo-fields, so the
    # real measures are the worksheet's column-instances (e.g. Behaviours & Events).
    both = cols_text + rows_text
    if "[Multiple Values]" in both or "[:Measure Names]" in both:
        for inst_key in ci:
            add(inst_key, "measure-values")
    if not fields:                                  # value-only KPI fallback (text/label)
        for enc in ws.findall(".//encodings/text") + ws.findall(".//encodings/label"):
            if _enc_ref(enc):
                add(_enc_ref(enc), enc.tag)
    return fields, bucket_tokens


def worksheet_visual(name: str, ws: ET.Element, captions: dict,
                     topn_sets: Optional[dict] = None) -> Optional[dict]:
    """One worksheet → a build_from_spec visual (mark + fields + bucket_tokens + top_n)."""
    mark_el = ws.find(".//mark")
    mark = (mark_el.get("class") if mark_el is not None else "") or "Automatic"
    fields, bucket_tokens = _ws_fields(ws, _instances(ws), captions)
    if not fields:
        return None
    v = {"title": name, "mark": mark.lower(), "fields": fields,
         "bucket_tokens": bucket_tokens}
    top_n = _visual_top_n(ws, topn_sets or {})
    if top_n:
        v["top_n"] = top_n
    return v


def _zone_tile(z: ET.Element) -> Optional[dict]:
    """Tableau 0–100,000 zone coords → a 12-col × ~20-row ThoughtSpot grid tile."""
    try:
        x, y, w, h = (int(z.get("x")), int(z.get("y")), int(z.get("w")), int(z.get("h")))
    except (TypeError, ValueError):
        return None
    return {
        "x": max(0, min(11, round(x / 100000 * 12))),
        "y": max(0, round(y / 100000 * 20)),
        "width": max(2, min(12, round(w / 100000 * 12))),
        "height": max(3, round(h / 100000 * 20)),
    }


def extract_dashboards(root: ET.Element) -> list[dict]:
    """All `<dashboard>` elements → build_from_spec `dashboards[]`.

    Each viz zone (a zone carrying a worksheet `name`) becomes a visual; zones are
    deduped by worksheet name; layout/filter/legend/param/text zones are skipped
    (they have no `name`). Tiles come from the zone's grid coordinates.
    """
    ws_by_name = {w.get("name"): w for w in root.findall(".//worksheets/worksheet")}
    captions = {col.get("name"): col.get("caption")
                for col in root.findall(".//column") if col.get("caption")}
    topn_sets = _topn_sets(root)
    dashboards: list[dict] = []
    for d in root.findall(".//dashboards/dashboard"):
        visuals: list[dict] = []
        seen: set[str] = set()
        for z in d.findall(".//zone"):
            wsname = z.get("name")
            if not wsname or wsname in seen or wsname not in ws_by_name:
                continue
            seen.add(wsname)
            v = worksheet_visual(wsname, ws_by_name[wsname], captions, topn_sets)
            if v:
                tile = _zone_tile(z)
                if tile:
                    v["tile"] = tile
                visuals.append(v)
        dashboards.append({"name": d.get("name") or "Dashboard", "visuals": visuals})
    return dashboards
