"""Unit tests for ts_cli.qlik.parsing — offline/engine-artifacts extraction + inventory.

Pure-function tests, no live connection. Uses the vendored .qvf fixtures when
the offline parser can read them, and small in-memory artifact dirs otherwise.
"""
import json
from pathlib import Path

import pytest

from ts_cli.qlik import parsing
from ts_cli.qlik.ir import QlikApp

# Sample .qvf fixtures live alongside the tests.
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "qlik"
SQLITE_QVF = _FIXTURES / "SqliteApp.qvf"
RETAIL_QVF = _FIXTURES / "RetailDemo.qvf"

pytestmark = pytest.mark.skipif(
    not SQLITE_QVF.exists(), reason="qlik fixtures not present"
)


class TestOfflineSqlite:
    def test_sqlite_app_counts(self):
        app = parsing.parse_app(str(SQLITE_QVF), mode="offline")
        assert app.extraction_mode == "sqlite"
        assert app.app_name == "Sales Analytics"
        inv = parsing.build_inventory(app)
        c = inv["counts"]
        assert c["connections"] == 1
        assert c["tables"] == 1
        assert c["columns"] == 2
        assert c["measures"] == 2
        assert c["dimensions"] == 1
        assert c["variables"] == 1
        assert c["sheets"] == 1
        assert c["charts"] == 2

    def test_measure_expressions_recovered(self):
        app = parsing.parse_app(str(SQLITE_QVF), mode="offline")
        exprs = {m.label: m.expression for m in app.measures}
        assert exprs["Total Sales"] == "Sum(Sales)"
        assert exprs["Avg Order"] == "Avg(OrderValue)"

    def test_connection_recovered_from_script(self):
        app = parsing.parse_app(str(SQLITE_QVF), mode="offline")
        assert [c.name for c in app.connections] == ["Snowflake_Sales"]


class TestOfflineByteScan:
    def test_retail_demo_bytescan(self):
        app = parsing.parse_app(str(RETAIL_QVF), mode="offline")
        assert app.extraction_mode == "offline"
        inv = parsing.build_inventory(app)
        assert inv["counts"]["tables"] == 2
        assert inv["counts"]["columns"] == 5
        assert inv["counts"]["measures"] == 1
        assert inv["counts"]["sheets"] == 1

    def test_bytescan_emits_best_effort_warning(self):
        app = parsing.parse_app(str(RETAIL_QVF), mode="offline")
        warns = [n for n in app.notes if n.severity in ("warning", "manual")]
        assert any("best-effort" in n.message for n in warns)


class TestInventoryShape:
    def test_inventory_has_all_expected_keys(self):
        app = parsing.parse_app(str(SQLITE_QVF), mode="offline")
        inv = parsing.build_inventory(app)
        for key in ("tables", "columns", "measures", "dimensions", "sheets",
                    "charts", "connections", "counts", "warnings"):
            assert key in inv, f"inventory missing '{key}'"

    def test_charts_flattened_with_sheet(self):
        app = parsing.parse_app(str(SQLITE_QVF), mode="offline")
        inv = parsing.build_inventory(app)
        assert all("sheet" in ch and "viz_type" in ch for ch in inv["charts"])


class TestModeValidation:
    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError):
            parsing.parse_app(str(SQLITE_QVF), mode="bogus")


class TestGracefulDegradation:
    def test_opaque_file_does_not_crash(self, tmp_path):
        """A non-.qvf, non-SQLite file must degrade to warnings, never crash."""
        junk = tmp_path / "notaqvf.qvf"
        junk.write_bytes(b"\x00\x01\x02not a qlik file\xff\xfe")
        app = parsing.parse_app(str(junk), mode="offline")
        assert isinstance(app, QlikApp)
        assert app.extraction_mode == "offline"
        # No tables/sheets recovered, but manual notes must flag the gaps.
        assert any(n.severity == "manual" for n in app.notes)
        inv = parsing.build_inventory(app)
        assert inv["counts"]["tables"] == 0


class TestEngineArtifacts:
    def _write_artifacts(self, d: Path):
        (d / "manifest.json").write_text(json.dumps({"app": "EngineApp.qvf"}))
        (d / "script.qvs").write_text("LIB CONNECT TO [lib://Snowflake_X];\nSELECT * FROM T;")
        (d / "data-model.json").write_text(json.dumps({
            "qtr": [{"qName": "Orders", "qFields": [{"qName": "OrderID"}, {"qName": "Amount"}]}],
            "qk": [],
        }))
        (d / "master-items.json").write_text(json.dumps({
            "measures": [{"id": "m1", "props": {"qMeasure": {"qLabel": "Revenue",
                                                             "qDef": "Sum(Amount)"}}}],
            "dimensions": [],
        }))
        (d / "sheets.json").write_text(json.dumps([
            {"id": "s1", "title": "Main", "children": [
                {"id": "c1", "type": "barchart",
                 "props": {"title": "Rev by Order",
                           "qHyperCubeDef": {"qDimensions": [], "qMeasures": []}}}
            ]}
        ]))

    def test_engine_artifacts_dir(self, tmp_path):
        self._write_artifacts(tmp_path)
        app = parsing.parse_app(str(tmp_path), mode="engine-artifacts")
        assert app.extraction_mode == "engine"
        assert app.app_name == "EngineApp"
        inv = parsing.build_inventory(app)
        assert inv["counts"]["tables"] == 1
        assert inv["counts"]["measures"] == 1
        assert inv["counts"]["sheets"] == 1
        assert inv["counts"]["charts"] == 1

    def test_missing_artifacts_dir_degrades(self, tmp_path):
        missing = tmp_path / "nope"
        app = parsing.parse_app(str(missing), mode="engine-artifacts")
        assert isinstance(app, QlikApp)
        assert any(n.severity == "manual" for n in app.notes)
