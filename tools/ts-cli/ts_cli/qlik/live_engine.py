"""Qlik Engine JSON-RPC extractor — the live, reliable extraction path.

Connects to a running Qlik engine over WebSocket and reads the full app
layout — sheets, charts, master dimensions/measures, variables, the data
model tables, and the load script — via documented Engine API methods. This
is the live counterpart to the offline ``.qvf`` byte-scan (``parsing.py``) and
the ``engine-artifacts`` directory ingest (``engine.py``): instead of guessing
at bytes or reading pre-dumped JSON, it asks a running engine directly.

Requires the app to be reachable by a running engine (Qlik Sense Desktop,
Enterprise on Windows/Kubernetes, or Qlik Cloud) and the ``websocket-client``
package (the ``[qlik]`` optional extra). ``websocket`` is imported lazily
inside ``QlikEngine.__init__`` so this module — and the whole ``ts_cli.qlik``
package — imports fine without the extra installed; only actually opening an
engine connection needs it.

This is one of the qlik package's two I/O modules (the other is ``cloud.py``),
mirroring ``ts_cli/tableau/client.py``. Everything else in the package is pure.

Engine API methods used (see the Qlik Engine API reference):
  OpenDoc / GetScript / GetLayout / GetTablesAndKeys / CreateSessionObject /
  GetObject.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .ir import (
    Chart, MasterDimension, MasterMeasure, QlikApp, Sheet, Table, Variable,
    Column,
)

_MISSING_WS_MSG = (
    "websocket-client is required for --mode engine / qlik-cloud.\n"
    "Install it with the qlik extra:\n"
    "  pip install 'thoughtspot-cli[qlik]'\n"
    "If ts was installed as an isolated uv tool, inject it into that env:\n"
    "  uv tool install thoughtspot-cli --with websocket-client"
)


class QlikEngine:
    """Minimal JSON-RPC client over the Qlik Engine WebSocket protocol."""

    def __init__(self, url: str, *, headers: Optional[dict[str, str]] = None,
                 timeout: int = 30):
        try:
            import websocket  # type: ignore  # lazy: optional [qlik] extra
        except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
            raise RuntimeError(_MISSING_WS_MSG) from exc
        self.url = url
        self._ws = websocket.create_connection(
            url, header=[f"{k}: {v}" for k, v in (headers or {}).items()],
            timeout=timeout)
        self._id = 0

    def call(self, method: str, handle: int, *params: Any) -> Any:
        self._id += 1
        self._ws.send(json.dumps({
            "jsonrpc": "2.0", "id": self._id, "handle": handle,
            "method": method, "params": list(params),
        }))
        while True:
            msg = json.loads(self._ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"{method} failed: {msg['error']}")
                return msg.get("result", {})

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:  # pragma: no cover - best-effort close
            pass


def full_url(engine_url: str, app_id: str) -> str:
    """Qlik Cloud/Enterprise expect the app GUID in the ws path
    (wss://host/app/<guid>). If the URL ends with '/app' we append it."""
    if engine_url.rstrip("/").endswith("/app"):
        return engine_url.rstrip("/") + "/" + app_id
    return engine_url


def extract(engine_url: str, app_id: str, *,
            headers: Optional[dict[str, str]] = None) -> QlikApp:
    """Open an app on the engine and build the IR from its layout."""
    eng = QlikEngine(full_url(engine_url, app_id), headers=headers)
    try:
        doc = eng.call("OpenDoc", -1, app_id)
        h = doc["qReturn"]["qHandle"]

        app = QlikApp(app_name=app_id, source_file=engine_url,
                      extraction_mode="engine")

        try:
            app.load_script = eng.call("GetScript", h).get("qScript")
        except Exception as e:
            app.note("warning", "script", f"GetScript failed: {e}")

        _read_master_items(eng, h, app)
        _read_variables(eng, h, app)
        _read_sheets(eng, h, app)
        _read_tables(eng, h, app)
        return app
    finally:
        eng.close()


def _list_def(qtype: str) -> dict[str, Any]:
    """Session-object definition to enumerate master dimensions/measures."""
    def_key = "qDimensionListDef" if qtype == "dimension" else "qMeasureListDef"
    expr = "/qDim" if qtype == "dimension" else "/qMeasure"
    return {
        "qInfo": {"qType": f"{qtype}list"},
        def_key: {"qType": qtype,
                  "qData": {"title": "/qMetaDef/title", "expr": expr}},
    }


def _read_master_items(eng: QlikEngine, h: int, app: QlikApp) -> None:
    for qtype in ("dimension", "measure"):
        try:
            so = eng.call("CreateSessionObject", h, _list_def(qtype))
            layout = eng.call("GetLayout", so["qReturn"]["qHandle"])["qLayout"]
            items = (layout.get("qDimensionList")
                     or layout.get("qMeasureList") or {}).get("qItems", [])
            for it in items:
                info = it.get("qInfo", {})
                meta = it.get("qMeta", {})
                if qtype == "dimension":
                    app.dimensions.append(MasterDimension(
                        id=info.get("qId", ""), label=meta.get("title", "")))
                else:
                    app.measures.append(MasterMeasure(
                        id=info.get("qId", ""), label=meta.get("title", "")))
        except Exception as e:
            app.note("warning", qtype, f"Could not list {qtype}s: {e}")


def _read_variables(eng: QlikEngine, h: int, app: QlikApp) -> None:
    try:
        so = eng.call("CreateSessionObject", h, {
            "qInfo": {"qType": "variablelist"},
            "qVariableListDef": {"qType": "variable", "qShowReserved": False,
                                 "qShowConfig": False,
                                 "qData": {"definition": "/qDefinition"}},
        })
        layout = eng.call("GetLayout", so["qReturn"]["qHandle"])["qLayout"]
        for it in layout.get("qVariableList", {}).get("qItems", []):
            app.variables.append(Variable(
                name=it.get("qName", ""),
                definition=(it.get("qData", {}) or {}).get("definition", "")))
    except Exception as e:
        app.note("warning", "variable", f"Could not list variables: {e}")


def _read_sheets(eng: QlikEngine, h: int, app: QlikApp) -> None:
    try:
        so = eng.call("CreateSessionObject", h, {
            "qInfo": {"qType": "sheetlist"},
            "qAppObjectListDef": {"qType": "sheet",
                                  "qData": {"title": "/qMetaDef/title",
                                            "cells": "/cells"}},
        })
        layout = eng.call("GetLayout", so["qReturn"]["qHandle"])["qLayout"]
        for it in layout.get("qAppObjectList", {}).get("qItems", []):
            info = it.get("qInfo", {})
            data = it.get("qData", {}) or {}
            sheet = Sheet(id=info.get("qId", ""), title=data.get("title", "Sheet"))
            for cell in data.get("cells", []) or []:
                sheet.charts.append(_chart_from_cell(eng, h, cell, app))
            app.sheets.append(sheet)
    except Exception as e:
        app.note("warning", "chart", f"Could not list sheets: {e}")


def _chart_from_cell(eng: QlikEngine, h: int, cell: dict, app: QlikApp) -> Chart:
    obj_id = cell.get("name", "")
    chart = Chart(id=obj_id, viz_type=cell.get("type", "UNKNOWN"))
    try:
        obj = eng.call("GetObject", h, obj_id)
        layout = eng.call("GetLayout", obj["qReturn"]["qHandle"])["qLayout"]
        chart.title = (layout.get("title")
                       or layout.get("qMeta", {}).get("title") or "")
        hc = layout.get("qHyperCube", {})
        chart.dimensions = [d.get("qFallbackTitle", "")
                            for d in hc.get("qDimensionInfo", [])]
        chart.measures = [m.get("qFallbackTitle", "")
                          for m in hc.get("qMeasureInfo", [])]
    except Exception as e:
        app.note("warning", "chart", f"Could not read object {obj_id}: {e}")
    return chart


def _read_tables(eng: QlikEngine, h: int, app: QlikApp) -> None:
    try:
        tv = eng.call("GetTablesAndKeys", h, {"qcx": 1000, "qcy": 1000},
                      {"qcx": 0, "qcy": 0}, 0, True, False)
        for t in tv.get("qtr", []):
            tbl = Table(name=t.get("qName", ""))
            for fld in t.get("qFields", []):
                tbl.columns.append(Column(name=fld.get("qName", "")))
            app.tables.append(tbl)
    except Exception as e:
        app.note("warning", "table", f"Could not read data model tables: {e}")
