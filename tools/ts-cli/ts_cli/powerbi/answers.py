"""Power BI report (PBIR pages/visuals) -> a build_from_spec spec.

Ported from the standalone converter (generate_tml.build_answers_and_liveboards). Pure
functions, no I/O. This module only RESOLVES the PBI side (visual type -> ts_chart, PBIR
field roles -> canonical roles, month columns -> date buckets, inline Sum(col) -> the agg
measure); the actual Answer + tabbed-Liveboard TML is emitted by the shared
ts_cli/tableau/liveboard.build_from_spec (which was itself ported from this converter's
_answer_tml), so both conversion skills share one emitter. build_from_spec reads a
per-visual ``ts_chart`` (added there) so the PBI type mapping wins over Tableau-mark inference.
"""
from __future__ import annotations

import re

# Power BI visualType -> ThoughtSpot chart type. PBI "columnChart"/"barChart" ARE the
# stacked variants; the clustered forms have their own names.
_CHART_MAP = {
    "columnchart": "STACKED_COLUMN", "clusteredcolumnchart": "COLUMN",
    "stackedcolumnchart": "STACKED_COLUMN", "hundredpercentstackedcolumnchart": "STACKED_COLUMN",
    "barchart": "STACKED_BAR", "clusteredbarchart": "BAR",
    "stackedbarchart": "STACKED_BAR", "hundredpercentstackedbarchart": "STACKED_BAR",
    "linechart": "LINE", "areachart": "AREA", "stackedareachart": "AREA",
    "lineclusteredcolumncombochart": "LINE_COLUMN", "linestackedcolumncombochart": "LINE_STACKED_COLUMN",
    "piechart": "PIE", "donutchart": "PIE", "scatterchart": "SCATTER",
    "tableex": "GRID_TABLE", "table": "GRID_TABLE", "pivottable": "PIVOT_TABLE", "matrix": "PIVOT_TABLE",
    "card": "KPI", "multirowcard": "KPI", "cardvisual": "KPI", "kpi": "KPI", "gauge": "KPI",
    "map": "GEO_BUBBLE", "filledmapvisual": "GEO_AREA", "shapemap": "GEO_AREA",
    "treemap": "TREEMAP", "funnel": "FUNNEL", "waterfallchart": "WATERFALL",
}
_NON_VISUAL = {"slicer", "advancedslicervisual", "textbox", "actionbutton", "image",
               "shape", "basicshape", "actionbuttonvisual"}
_MONTH_PARTS = {"month", "month name", "monthname", "month of year"}
_SIMPLE_AGG = re.compile(r"(?i)^\s*(SUM|AVERAGE|AVG|MIN|MAX|COUNT|COUNTA|DISTINCTCOUNT)\s*\(\s*(.+?)\s*\)\s*$")


def chart_type_for(visual_type):
    """Power BI visualType -> (ts_chart, status, note). None ts_chart => skip (slicer/text)."""
    vt = (visual_type or "").strip().lower()
    if vt in _NON_VISUAL:
        return None, "Skipped", f"{visual_type} is not a chart (slicer/text/button)"
    if vt in ("", "unknown", "unparsed"):
        return "GRID_TABLE", "NEEDS REVIEW", "visual type unknown; defaulted to GRID_TABLE"
    if vt in _CHART_MAP:
        ct = _CHART_MAP[vt]
        if ct in ("GEO_BUBBLE", "GEO_AREA"):
            return ct, "Approximated", "needs a geo-recognized column; verify"
        if vt == "gauge":
            return ct, "Approximated", "gauge approximated as KPI"
        return ct, "Migrated", ""
    return "GRID_TABLE", "Approximated", f"no direct mapping for '{visual_type}'; defaulted to GRID_TABLE"


def _leaf(field_name):
    """A parsed PBIR field ref ('Sum of Sales', 'Sales.Amount', 'Amount') -> a best-effort
    leaf name for matching against model column display names."""
    if not field_name:
        return ""
    s = str(field_name).strip()
    s = re.sub(r"^(sum|average|avg|min|max|count|count of|sum of|average of)\s+", "", s, flags=re.I)
    if "." in s:
        s = s.split(".")[-1]
    return s.strip().strip("[]")


def _date_bucket_map(inv):
    """Map a date-table month-name column -> ("[Date].MONTHLY", "Date"): the monthly search
    token plus the RAW base date column. A PBI date hierarchy sorts a text "Month" by an
    underlying date; a varchar Month sorts alphabetically in ThoughtSpot, so the faithful
    equivalent is the base date column bucketed monthly.

    The second element is the RAW date column, NOT the resolved output name "Month(Date)":
    the shared build_from_spec._output_name applies the bucket label itself (raw "Date" +
    "[Date].MONTHLY" -> output column "Month(Date)"). Passing the pre-resolved "Month(Date)"
    here makes the emitter wrap it a second time -> "Month(Month(Date))", which the engine
    rejects (live-verified on ps-internal)."""
    out = {}
    for t in inv.get("tables", []):
        date_col, month_cols = None, []
        for c in t.get("columns", []):
            if c.get("calculated"):
                continue
            if (c.get("dataType") or "").lower() in ("datetime", "date") and date_col is None:
                date_col = c["name"]
            if c["name"].strip().lower() in _MONTH_PARTS:
                month_cols.append(c["name"])
        if date_col:
            for mc in month_cols:
                out[mc] = (f"[{date_col}].MONTHLY", date_col)
    return out


def agg_measures_map(inv):
    """(agg_word, column_lower) -> measure name, for a Power BI inline aggregation (Sum(col))
    that binds to the equivalent named measure ("Sum of BadHires") not the bare calc column."""
    out = {}
    for t in inv.get("tables", []):
        for me in t.get("measures", []):
            mm = _SIMPLE_AGG.match(me.get("expression", ""))
            if not mm:
                continue
            aggw = mm.group(1).lower().replace("avg", "average")
            col = re.sub(r".*[\[.]", "", mm.group(2)).strip(" []")
            if col:
                out[(aggw, col.lower())] = me["name"]
    return out


def _resolve_fields(vis, norm, bucket_map, agg_measures):
    """Resolve a visual's PBIR fields to model columns by leaf-name match, keeping each
    field's role. Returns (fields, bucket_tokens, missing) where fields are the build_from_spec
    ``{name, role}`` dicts and bucket_tokens maps a bucketed output name -> its search token."""
    fields, seen, bucket_tokens, missing = [], set(), {}, []

    def _place(col, role):
        if col not in seen:
            seen.add(col)
            fields.append({"name": col, "role": role})

    for f in vis.get("fields", []):
        role = f.get("role") or ""
        if f.get("kind") == "aggregation":       # inline Sum(col) -> the equivalent measure
            mname = agg_measures.get(((f.get("agg") or "sum"), (f.get("field") or "").lower()))
            if mname and mname.lower() in norm:
                _place(norm[mname.lower()], role)
            else:
                missing.append(f"{f.get('agg') or 'agg'}({f.get('field')})")
            continue
        leaf = _leaf(f.get("field"))
        if not leaf:
            continue
        match = norm.get(leaf.lower())
        if match and match in bucket_map:        # date-month part -> monthly date bucket
            # Place the RAW date column keyed with its monthly token; the shared emitter
            # resolves the output name once (raw "Date" -> "Month(Date)"). Placing the
            # pre-resolved name here would double-bucket to "Month(Month(Date))".
            tok, raw = bucket_map[match]
            _place(raw, role)
            bucket_tokens[raw] = tok
        elif match:
            _place(match, role)
        else:
            missing.append(leaf)
    return fields, bucket_tokens, missing


def _spec_visual(vis, vi, page_name, norm, bucket_map, agg_measures, ov_visuals):
    """One PBI visual -> a build_from_spec visual dict, or None to skip (a non-visual, e.g.
    slicer/textbox). An explicit override (search+columns) is passed through verbatim."""
    title = f"{page_name} - {vis.get('type', 'visual')} {vi + 1}"
    ov = ov_visuals.get((page_name, title)) or ov_visuals.get((page_name, vis.get("id")))
    if ov and ov.get("search") and ov.get("columns"):
        return {"title": vis.get("title") or ov.get("name") or title, "override": ov}
    ct, status, note = chart_type_for(vis.get("type"))
    if ov and ov.get("ts_chart"):
        ct, status, note = ov["ts_chart"], ov.get("status", "Migrated"), ov.get("note", "")
    if ct is None:
        return None                               # slicer / text / button -> not a tab tile
    fields, bucket_tokens, _ = _resolve_fields(vis, norm, bucket_map, agg_measures)
    # mark must be non-empty (build_from_spec treats "" as a non-visual and skips before the
    # ts_chart passthrough); "automatic" is benign — ts_chart still wins in _resolve_ct.
    # ts_chart_status/note carry chart_type_for's verdict so _resolve_ct reports the true
    # status (e.g. gauge->KPI Approximated, unknown->GRID_TABLE NEEDS REVIEW), not a blanket
    # "Migrated" — preserving the "flags, never downgrades" signal.
    sv = {"title": vis.get("title") or title, "mark": "automatic", "ts_chart": ct,
          "ts_chart_status": status, "ts_chart_note": note, "fields": fields}
    if bucket_tokens:
        sv["bucket_tokens"] = bucket_tokens
    return sv


def spec_from_parse(inv, model_name, model_fqn, column_names, measure_names, overrides):
    """Parsed PBI inventory -> a build_from_spec spec (report_name / model / measure_names /
    dashboards[] / extra_visuals). Pages become dashboards (tabs); a PBI Tooltip page is
    flagged tooltip so the shared emitter drops it, not a tab."""
    overrides = overrides or {}
    ov_visuals = {(v.get("page"), v.get("visual")): v for v in (overrides.get("visuals") or [])}
    norm = {n.lower(): n for n in column_names}
    bucket_map = _date_bucket_map(inv)
    agg_measures = agg_measures_map(inv)
    report_name = (overrides.get("project_name")
                   or re.sub(r"\s*\(PBI\)\s*$|\s+Model\s*$", "", model_name).strip() or model_name)

    dashboards = []
    for page in inv.get("pages", []):
        page_name = page.get("name") or page.get("id")
        if page.get("tooltip"):
            dashboards.append({"name": page_name, "tooltip": True, "visuals": []})
            continue
        visuals = []
        for vi, vis in enumerate(page.get("visuals", [])):
            sv = _spec_visual(vis, vi, page_name, norm, bucket_map, agg_measures, ov_visuals)
            if sv is not None:
                visuals.append(sv)
        dashboards.append({"name": page_name, "tooltip": False, "visuals": visuals})

    return {
        "report_name": report_name,
        "model_name": model_name,
        "model_fqn": model_fqn,
        "measure_names": sorted(measure_names),
        "dashboards": dashboards,
        "extra_visuals": overrides.get("extra_visuals") or [],
    }
