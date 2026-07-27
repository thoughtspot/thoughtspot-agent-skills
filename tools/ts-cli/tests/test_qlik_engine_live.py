"""Unit tests for ts_cli.qlik.live_engine — the live Qlik Engine JSON-RPC path.

No network: a FakeEngine feeds recorded Engine API responses so the IR-building
logic (master items, variables, sheets/charts, data-model tables) is asserted
end-to-end. Also asserts the missing-websocket-client remediation message.
"""
import sys

import pytest

from ts_cli.qlik import live_engine
from ts_cli.qlik.ir import QlikApp


# --- recorded Engine layouts, keyed by the session-object / object handle ---

_LAYOUTS = {
    "dimensionlist": {"qDimensionList": {"qItems": [
        {"qInfo": {"qId": "d1"}, "qMeta": {"title": "Region"}},
    ]}},
    "measurelist": {"qMeasureList": {"qItems": [
        {"qInfo": {"qId": "m1"}, "qMeta": {"title": "Total Sales"}},
        {"qInfo": {"qId": "m2"}, "qMeta": {"title": "Avg Order"}},
    ]}},
    "variablelist": {"qVariableList": {"qItems": [
        {"qName": "vThreshold", "qData": {"definition": "=100"}},
    ]}},
    "sheetlist": {"qAppObjectList": {"qItems": [
        {"qInfo": {"qId": "s1"},
         "qData": {"title": "Overview", "cells": [
             {"name": "c1", "type": "barchart"},
             {"name": "c2", "type": "kpi"},
         ]}},
    ]}},
    # chart objects (handle = "obj:<id>")
    "obj:c1": {"title": "Sales by Region",
               "qHyperCube": {"qDimensionInfo": [{"qFallbackTitle": "Region"}],
                              "qMeasureInfo": [{"qFallbackTitle": "Total Sales"}]}},
    "obj:c2": {"title": "KPI",
               "qHyperCube": {"qDimensionInfo": [],
                              "qMeasureInfo": [{"qFallbackTitle": "Avg Order"}]}},
}


class FakeEngine:
    """Stand-in for QlikEngine.call() over recorded responses (no websocket)."""

    def __init__(self, url, *, headers=None, timeout=30):
        self.url = url
        self.headers = headers
        self.closed = False

    def call(self, method, handle, *params):
        if method == "OpenDoc":
            return {"qReturn": {"qHandle": 1}}
        if method == "GetScript":
            return {"qScript": "LIB CONNECT TO [lib://Snowflake_Sales];\nSELECT * FROM S;"}
        if method == "CreateSessionObject":
            qtype = params[0]["qInfo"]["qType"]          # e.g. "measurelist"
            return {"qReturn": {"qHandle": qtype}}       # handle encodes list type
        if method == "GetObject":
            return {"qReturn": {"qHandle": "obj:" + params[0]}}
        if method == "GetLayout":
            return {"qLayout": _LAYOUTS[handle]}
        if method == "GetTablesAndKeys":
            return {"qtr": [
                {"qName": "Orders",
                 "qFields": [{"qName": "OrderID"}, {"qName": "Amount"}]},
                {"qName": "Region", "qFields": [{"qName": "Region"}]},
            ]}
        raise AssertionError(f"unexpected method {method}")

    def close(self):
        self.closed = True


@pytest.fixture()
def fake_engine(monkeypatch):
    monkeypatch.setattr(live_engine, "QlikEngine", FakeEngine)


class TestExtract:
    def test_extract_builds_full_ir(self, fake_engine):
        app = live_engine.extract("wss://tenant/app", "app-guid-123")
        assert isinstance(app, QlikApp)
        assert app.extraction_mode == "engine"
        assert app.load_script.startswith("LIB CONNECT TO")

        assert [d.label for d in app.dimensions] == ["Region"]
        assert sorted(m.label for m in app.measures) == ["Avg Order", "Total Sales"]
        assert [v.name for v in app.variables] == ["vThreshold"]

        assert [t.name for t in app.tables] == ["Orders", "Region"]
        orders = next(t for t in app.tables if t.name == "Orders")
        assert [c.name for c in orders.columns] == ["OrderID", "Amount"]

    def test_extract_reads_sheets_and_charts(self, fake_engine):
        app = live_engine.extract("wss://tenant/app", "app-guid-123")
        assert len(app.sheets) == 1
        sheet = app.sheets[0]
        assert sheet.title == "Overview"
        assert [c.viz_type for c in sheet.charts] == ["barchart", "kpi"]
        bar = sheet.charts[0]
        assert bar.title == "Sales by Region"
        assert bar.dimensions == ["Region"]
        assert bar.measures == ["Total Sales"]

    def test_engine_connection_closed(self, fake_engine):
        # extract() must close the engine in its finally block.
        created = {}
        real = FakeEngine

        def spy(url, *, headers=None, timeout=30):
            eng = real(url, headers=headers, timeout=timeout)
            created["eng"] = eng
            return eng

        import ts_cli.qlik.live_engine as le
        le.QlikEngine = spy  # type: ignore
        try:
            le.extract("wss://tenant/app", "g")
        finally:
            le.QlikEngine = real  # type: ignore
        assert created["eng"].closed is True


class TestFullUrl:
    def test_appends_guid_when_path_ends_with_app(self):
        assert live_engine.full_url("wss://h/app", "g1") == "wss://h/app/g1"

    def test_leaves_full_url_untouched(self):
        assert live_engine.full_url("wss://h/app/g1", "g1") == "wss://h/app/g1"


class TestMissingWebsocketClient:
    def test_missing_extra_gives_clear_remediation(self, monkeypatch):
        # Force `import websocket` to fail inside QlikEngine.__init__.
        monkeypatch.setitem(sys.modules, "websocket", None)
        with pytest.raises(RuntimeError) as exc:
            live_engine.extract("wss://h/app", "g1")
        msg = str(exc.value)
        assert "websocket-client" in msg
        assert "thoughtspot-cli[qlik]" in msg
