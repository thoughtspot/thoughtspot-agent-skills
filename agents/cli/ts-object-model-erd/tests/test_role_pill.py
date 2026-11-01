"""The side panel names each table's role (roles.py, audit v2 roadmap PR 4.1), with a
tooltip saying what it means — checked in headless Chrome."""
import os

import pytest

from . import browser

pytestmark = pytest.mark.skipif(browser.CHROME is None, reason="Google Chrome not installed")


def _col(t, n, kind):
    return {"name": f"{t} {n}", "column_id": f"{t}::{n}", "properties": {"column_type": kind}}


MODEL = {"guid": "g", "model": {
    "name": "Header detail",
    "model_tables": [
        {"name": "LINES", "joins": [{"with": "HEADER", "cardinality": "MANY_TO_ONE"}]},
        {"name": "HEADER", "joins": [{"with": "CUSTOMER", "cardinality": "MANY_TO_ONE"}]},
        {"name": "CUSTOMER"},
    ],
    "columns": [_col("LINES", "QTY", "MEASURE"), _col("HEADER", "FREIGHT", "MEASURE"),
                _col("HEADER", "STATUS", "ATTRIBUTE"), _col("CUSTOMER", "NAME", "ATTRIBUTE")],
}}


def test_pill_names_the_role_with_a_tooltip(tmp_path):
    import build_erd
    import yaml
    tml = tmp_path / "tml"
    tml.mkdir()
    (tml / "Header_detail.model.tml").write_text(yaml.safe_dump(MODEL), encoding="utf-8")
    page = str(tmp_path / "erd.html")
    build_erd.build([str(tml)], page, log=lambda *_: None)
    got = browser.probe(page, """
      var out = {};
      ["LINES", "HEADER", "CUSTOMER"].forEach(function(id){
        showTable(id);
        var pill = document.querySelector("#inspector .pill");
        out[id] = [pill.textContent, pill.getAttribute("title") || "", pill.className];
      });
      return out;""", tmp_path)
    assert "LINES" in got, got
    assert got["LINES"][0] == "Fact" and "fact" in got["LINES"][2]
    assert got["HEADER"][0] == "Dimension holding measures"
    assert "cardinality" in got["HEADER"][1] and "dim" in got["HEADER"][2]
    assert got["CUSTOMER"][0] == "Dimension (outrigger)" and "snowflaked" in got["CUSTOMER"][1]
