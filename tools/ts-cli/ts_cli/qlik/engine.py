"""Engine-artifacts extraction — ingest the JSON dumped by the headless-engine
extractor (qvf-engine-extract/) into the Qlik IR.

Split out of ``parsing.py`` (module-per-concern, to stay under the file-size
gate — same pattern the databricks package uses). The sidecar Node/Docker tool
dumps an ``output/`` folder::

    script.qvs         raw load script
    data-model.json    getTablesAndKeys() -> { qtr: [tables], qk: [keys] }
    master-items.json  { measures: [...], dimensions: [...] }
    sheets.json        [{ id, title, children: [...] }]
    manifest.json      { app, counts, ... }

Because these come straight from the Qlik engine the IR is SOURCE-grade
(extraction_mode="engine") — the faithful path, no byte-scraping. Tolerant of
missing files/keys so a partial export still yields a usable IR with notes.
Pure — the only I/O is reading the artifact files.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from .ir import (
    Chart, Column, MasterDimension, MasterMeasure, QlikApp, Sheet, Table,
)
from .layout import _first_field_def, _fmt, _measure_def, _qid, _qtype
from .parsing import _parse_connections_from_script


def extract_engine_artifacts(artifacts_dir: str) -> QlikApp:
    d = artifacts_dir
    manifest = _read_json(os.path.join(d, "manifest.json")) or {}
    app_name = manifest.get("app") or os.path.basename(os.path.normpath(d)) or "app"
    if app_name.lower().endswith(".qvf"):
        app_name = app_name[:-4]

    app = QlikApp(app_name=app_name, source_file=d, extraction_mode="engine")

    if not os.path.isdir(d):
        app.note("manual", "general",
                 f"Artifacts directory '{d}' not found; nothing to extract.")
        return app

    script = _read_text(os.path.join(d, "script.qvs"))
    if script:
        app.load_script = script
        _parse_connections_from_script(script, app)
    else:
        app.note("warning", "script", "No script.qvs in artifacts.")

    _ingest_data_model(_read_json(os.path.join(d, "data-model.json")), app)
    _ingest_master_items(_read_json(os.path.join(d, "master-items.json")), app)
    _ingest_sheets(_read_json(os.path.join(d, "sheets.json")), app)
    return app


def _ingest_data_model(dm: Optional[dict], app: QlikApp) -> None:
    if not dm:
        app.note("warning", "table", "No data-model.json; tables not loaded.")
        return
    conn = app.connections[0].name if app.connections else None
    for t in dm.get("qtr", []) or []:
        name = t.get("qName")
        if not name:
            continue
        cols = [Column(name=f.get("qName")) for f in (t.get("qFields") or []) if f.get("qName")]
        app.tables.append(Table(name=name, columns=cols, source_connection=conn))
    for k in dm.get("qk", []) or []:
        fields = k.get("qKeyFields") or []
        tables = k.get("qTables") or []
        if fields and len(tables) >= 2:
            app.note("info", "join",
                     f"Association on {', '.join(fields)}: {' <-> '.join(tables)}")


def _ingest_master_items(mi: Optional[dict], app: QlikApp) -> None:
    if not mi:
        app.note("warning", "measure", "No master-items.json; measures/dimensions not loaded.")
        return
    for m in mi.get("measures", []) or []:
        app.measures.append(_measure_from_master(m))
    for dmn in mi.get("dimensions", []) or []:
        app.dimensions.append(_dimension_from_master(dmn))


def _measure_from_master(m: dict) -> MasterMeasure:
    props = m.get("props", {}) or {}
    qm = props.get("qMeasure", {}) or {}
    meta = props.get("qMetaDef", {}) or {}
    return MasterMeasure(
        id=m.get("id") or _qid(props),
        label=qm.get("qLabel") or meta.get("title") or m.get("id", ""),
        expression=qm.get("qDef", ""),
        number_format=_fmt(qm.get("qNumFormat")),
    )


def _dimension_from_master(dmn: dict) -> MasterDimension:
    props = dmn.get("props", {}) or {}
    qd = props.get("qDim", {}) or {}
    meta = props.get("qMetaDef", {}) or {}
    defs = qd.get("qFieldDefs", []) or []
    labels = qd.get("qFieldLabels", []) or []
    return MasterDimension(
        id=dmn.get("id") or _qid(props),
        label=meta.get("title") or (labels or defs or [""])[0],
        fields=defs,
        expression=defs[0] if defs and defs[0].startswith("=") else None,
    )


def _ingest_sheets(sheets: Optional[list], app: QlikApp) -> None:
    if not sheets:
        app.note("warning", "chart", "No sheets.json; sheets/charts not loaded.")
        return
    for s in sheets:
        sheet = Sheet(id=s.get("id", ""), title=s.get("title") or s.get("id", "Sheet"))
        for child in s.get("children", []) or []:
            chart = _chart_from_child(child)
            if chart is not None:
                sheet.charts.append(chart)
        app.sheets.append(sheet)


def _chart_from_child(child: dict) -> Optional[Chart]:
    props = child.get("props", {}) or {}
    vtype = child.get("type") or _qtype(props) or "UNKNOWN"
    if vtype in ("", "sheet"):
        return None
    hc = props.get("qHyperCubeDef", {}) or {}
    dims = [_first_field_def(x) for x in hc.get("qDimensions", []) or []]
    meas = [_measure_def(x) for x in hc.get("qMeasures", []) or []]
    return Chart(
        id=child.get("id", ""),
        title=_chart_title(props, child),
        viz_type=vtype,
        dimensions=[x for x in dims if x],
        measures=[x for x in meas if x],
    )


def _chart_title(props: dict, child: dict) -> str:
    meta = props.get("qMetaDef", {}) or {}
    return props.get("title") or meta.get("title", "") or child.get("id", "")


def _read_json(path: str) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _read_text(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None
