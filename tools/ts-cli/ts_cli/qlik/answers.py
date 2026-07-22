"""Build a ThoughtSpot Answer + tabbed Liveboard from the Qlik IR.

Ported from the vendored q2t transform's liveboard emitter. One Liveboard is
produced with one TAB per Qlik sheet; each chart becomes an embedded Answer
(``visualizations[].answer``) whose search query is assembled from the chart's
dimensions + measures. A Qlik viz type with no ThoughtSpot equivalent defaults
to a table and is flagged NEEDS REVIEW rather than silently mis-mapped.

Pure functions — return dicts, never write files (the ``ts qlik
build-liveboard`` command does the I/O). No dependency on a shared
``build_from_spec`` (none exists on this branch — the Tableau converter has no
liveboard builder), so the spec is constructed and emitted here directly.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .ir import Chart, QlikApp

# Qlik viz object type -> ThoughtSpot chart type.
_CHART_MAP = {
    "barchart": "COLUMN", "bar": "BAR",
    "linechart": "LINE", "line": "LINE",
    "combochart": "LINE_COLUMN",
    "piechart": "PIE", "pie": "PIE",
    "kpi": "KPI",
    "gauge": "KPI",
    "scatterplot": "SCATTER",
    "table": "GRID_TABLE", "pivot-table": "PIVOT_TABLE", "sn-table": "GRID_TABLE",
    "treemap": "TREEMAP",
    "map": "GEO_AREA",
    "histogram": "COLUMN",
}

_STATUS_REVIEW = "NEEDS REVIEW"


def build_liveboard_artifacts(
    app: QlikApp,
    *,
    model_name: str,
    model_fqn: Optional[str] = None,
    report_name: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble a tabbed Liveboard TML (one tab per sheet) from a QlikApp.

    Returns::

        {
          "liveboard": {"filename": str, "tml": liveboard_tml_dict},
          "mapping":   {...},    # per-chart status + NEEDS REVIEW reasons
          "counts":    {...},
        }
    """
    report_name = report_name or model_name or app.app_name
    viz_list: list[dict] = []
    tab_layout: list[dict] = []
    chart_map: list[dict] = []
    review = 0
    counter = 0

    for sheet in app.sheets:
        tab_viz_ids: list[str] = []
        for chart in sheet.charts:
            counter += 1
            vid = f"Viz_{counter}"
            viz, entry = _viz(vid, chart, model_name, model_fqn, sheet.title or sheet.id)
            viz_list.append(viz)
            tab_viz_ids.append(vid)
            chart_map.append(entry)
            if entry["status"] == _STATUS_REVIEW:
                review += 1
        tab_layout.append({"name": sheet.title or sheet.id, "visualization_ids": tab_viz_ids})

    lb: dict[str, Any] = {"name": report_name, "visualizations": viz_list}
    if tab_layout:
        lb["layout"] = {"tabs": tab_layout}

    warnings = [
        "Liveboard vizzes are generated from chart dimensions/measures as "
        "natural-language search queries. Review each viz — Qlik set analysis, "
        "alternate dimensions, and complex expressions are not translated."
    ]

    counts = {
        "sheets": len(app.sheets),
        "tabs": len(tab_layout),
        "charts": counter,
        "visualizations": len(viz_list),
        "charts_needs_review": review,
    }
    mapping = {
        "report": report_name,
        "model": model_name,
        "model_fqn": model_fqn,
        "charts": chart_map,
        "warnings": warnings,
        "counts": counts,
    }
    return {
        "liveboard": {"filename": f"liveboard.{_slug(report_name)}.tml", "tml": {"liveboard": lb}},
        "mapping": mapping,
        "counts": counts,
    }


def _viz(
    vid: str,
    chart: Chart,
    model_name: str,
    model_fqn: Optional[str],
    sheet_title: str,
) -> tuple[dict, dict]:
    chart_type = _CHART_MAP.get((chart.viz_type or "").lower())
    status = "OK"
    reason = ""
    if chart_type is None:
        chart_type = "GRID_TABLE"
        status = _STATUS_REVIEW
        reason = (f"Qlik viz type '{chart.viz_type}' has no ThoughtSpot equivalent; "
                  "defaulted to a table.")

    tokens = [f"[{d}]" for d in chart.dimensions] + [f"[{m}]" for m in chart.measures]
    search_query = " ".join(tokens)
    if not tokens:
        status = _STATUS_REVIEW
        reason = (reason + " " if reason else "") + (
            "No dimensions/measures recovered for this chart; the search query is "
            "empty — rebuild the viz by hand."
        )

    table_ref: dict[str, Any] = {"name": model_name}
    if model_fqn:
        table_ref["fqn"] = model_fqn

    answer: dict[str, Any] = {
        "name": chart.title or chart.id,
        "tables": [table_ref],
        "search_query": search_query or "[]",
        "chart": {"type": chart_type},
        "display_mode": "TABLE_MODE" if chart_type == "GRID_TABLE" else "CHART_MODE",
    }
    viz = {"id": vid, "answer": answer}
    entry = {
        "id": vid,
        "sheet": sheet_title,
        "title": chart.title or chart.id,
        "qlik_viz_type": chart.viz_type,
        "ts_chart_type": chart_type,
        "search_query": search_query or "[]",
        "status": status,
        "reason": reason.strip(),
    }
    return viz, entry


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "obj"
