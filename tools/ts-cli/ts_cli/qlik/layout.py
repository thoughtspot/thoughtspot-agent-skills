"""Qlik layout-JSON → IR parsing (SQLite-backed .qvf path).

Split out of ``parsing.py`` to stay under the file-size gate (same
module-per-concern pattern the tableau/databricks packages use). Holds the
pure functions that turn a decoded Qlik ``Layout`` JSON object — master
measures/dimensions/variables and the sheet/chart tree — into IR objects, plus
the small ``q*`` accessors shared with the engine-artifacts path.

Pure — no I/O. Consumed by ``parsing._extract_sqlite`` and ``engine``.
"""

from __future__ import annotations

from typing import Optional

from .ir import (
    Chart, MasterDimension, MasterMeasure, QlikApp, Sheet, Variable,
)

# ---------------------------------------------------------------------------
# small accessors (shared with engine-artifacts extraction)
# ---------------------------------------------------------------------------


def _items(layout: dict, key: str) -> list[dict]:
    return (layout.get(key, {}) or {}).get("qItems", []) or []


def _qid(item: dict) -> str:
    return (item.get("qInfo", {}) or {}).get("qId", "")


def _qtype(props: dict) -> str:
    return (props.get("qInfo", {}) or {}).get("qType", "")


def _fmt(numfmt: Optional[dict]) -> Optional[str]:
    return numfmt.get("qFmt") if isinstance(numfmt, dict) else None


def _first_field_def(dim: dict) -> str:
    qdef = dim.get("qDef", {}) or {}
    labels = qdef.get("qFieldLabels", []) or []
    defs = qdef.get("qFieldDefs", []) or []
    return (labels or defs or [""])[0]


def _measure_def(m: dict) -> str:
    qdef = m.get("qDef", {}) or {}
    return qdef.get("qLabel") or qdef.get("qDef", "")


# ---------------------------------------------------------------------------
# Layout JSON -> IR
# ---------------------------------------------------------------------------


def _parse_layout(layout: dict, app: QlikApp) -> None:
    meta = layout.get("qMeta", {}) or {}
    if meta.get("title"):
        app.app_name = meta["title"]

    _ingest_layout_measures(layout, meta, app)
    _ingest_layout_dimensions(layout, app)
    _ingest_layout_variables(layout, app)
    _ingest_layout_sheets(layout, app)

    if not app.tables and app.dimensions:
        app.note("info", "table",
                 "No data-model tables in layout; tables are typically defined by "
                 "the load script. Provide a connection/tables at load time.")


def _ingest_layout_measures(layout: dict, meta: dict, app: QlikApp) -> None:
    for item in _items(layout, "qMeasureList"):
        qm = (item.get("qData", {}) or {}).get("qMeasure", {}) or {}
        app.measures.append(MasterMeasure(
            id=_qid(item),
            label=qm.get("qLabel") or meta.get("title", "") or _qid(item),
            expression=qm.get("qDef", ""),
            number_format=_fmt(qm.get("qNumFormat")),
        ))


def _ingest_layout_dimensions(layout: dict, app: QlikApp) -> None:
    for item in _items(layout, "qDimensionList"):
        qd = (item.get("qData", {}) or {}).get("qDim", {}) or {}
        defs = qd.get("qFieldDefs", []) or []
        labels = qd.get("qFieldLabels", []) or []
        app.dimensions.append(MasterDimension(
            id=_qid(item),
            label=(labels or defs or [""])[0],
            fields=defs,
            expression=defs[0] if defs and defs[0].startswith("=") else None,
        ))


def _ingest_layout_variables(layout: dict, app: QlikApp) -> None:
    for item in _items(layout, "qVariableList"):
        app.variables.append(Variable(
            name=item.get("qName", ""),
            definition=item.get("qDefinition", ""),
        ))


def _ingest_layout_sheets(layout: dict, app: QlikApp) -> None:
    sheets = [it for it in _items(layout, "qAppObjectList")
              if (it.get("qInfo", {}) or {}).get("qType") == "sheet"]
    sheets.sort(key=lambda s: (s.get("qData", {}) or {}).get("rank", 0))
    for it in sheets:
        app.sheets.append(_parse_sheet(it))


def _parse_sheet(item: dict) -> Sheet:
    data = item.get("qData", {}) or {}
    meta = item.get("qMeta", {}) or {}
    sheet = Sheet(id=_qid(item), title=meta.get("title", "Sheet"))
    for cell in data.get("cells", []) or []:
        chart = _chart_from_cell(cell)
        if chart is not None:
            sheet.charts.append(chart)
    return sheet


def _chart_from_cell(cell: dict) -> Optional[Chart]:
    vtype = cell.get("type", "UNKNOWN")
    if vtype in ("", "unknown"):
        return None
    props = cell.get("props", {}) or {}
    hc = props.get("qHyperCubeDef", {}) or {}
    dims = [_first_field_def(d) for d in hc.get("qDimensions", []) or []]
    meas = [_measure_def(m) for m in hc.get("qMeasures", []) or []]
    return Chart(
        id=cell.get("name", "obj"),
        title=props.get("title", "") or cell.get("name", ""),
        viz_type=vtype,
        dimensions=[d for d in dims if d],
        measures=[m for m in meas if m],
        raw={"col": cell.get("col"), "row": cell.get("row"),
             "colspan": cell.get("colspan"), "rowspan": cell.get("rowspan")},
    )
