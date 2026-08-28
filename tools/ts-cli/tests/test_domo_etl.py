"""Tests for Domo Magic ETL parsing + ETL-driven model joins."""
import json
from pathlib import Path

from ts_cli.domo.build_model import build_model_artifacts
from ts_cli.domo.ir import Dataset, DomoApp, DomoColumn
from ts_cli.domo.magic_etl import parse_etl

ETL = Path(__file__).parent / "fixtures" / "domo" / "magic_etl_olist.json"


def test_parse_etl_tables_and_joins():
    r = parse_etl(json.loads(ETL.read_text()))
    assert r["output"] == "Olist Master Dataset"
    names = {t["name"] for t in r["tables"]}
    assert "Olist Orders Dataset" in names and "Olist Sellers Dataset" in names
    assert len(r["tables"]) == 8
    assert len(r["joins"]) == 7
    # keys + type captured, every join flagged for review
    j0 = r["joins"][0]
    assert j0["type"] == "LEFT_OUTER"
    assert j0["keys"] == [{"left": "customer_id", "right": "customer_id"}]
    assert all(j["review"] for j in r["joins"])
    # Alter Columns renames attach to the translation table
    tx = next(t for t in r["tables"] if t["name"] == "Product Category Name Translation")
    assert any(rn["to"] == "product_category_name_english" for rn in tx["renames"])


def test_build_model_uses_explicit_etl_joins():
    app = DomoApp(app_name="Olist", datasets=[
        Dataset(id="d1", name="Olist Orders Dataset", rows=100000, columns=[
            DomoColumn("order_id", "STRING"), DomoColumn("customer_id", "STRING"),
            DomoColumn("price", "DOUBLE")]),
        Dataset(id="d2", name="Olist Customer Dataset", rows=3000, columns=[
            DomoColumn("customer_id", "STRING"), DomoColumn("city", "STRING")]),
    ])
    joins = [{"left_table": "Olist Orders Dataset", "right_table": "Olist Customer Dataset",
              "type": "LEFT_OUTER", "keys": [{"left": "customer_id", "right": "customer_id"}]}]
    arts = build_model_artifacts(app, connection_name="C", db="DB", schema="S",
                                 model_name="Olist Model", explicit_joins=joins)
    # mapping records the ETL-sourced join
    assert arts["mapping"]["joins"][0]["source"] == "magic_etl"
    assert arts["mapping"]["joins"][0]["status"] == "NEEDS REVIEW"
    # the join lives on the source (Orders) side only, with a cardinality
    mts = {mt["name"]: mt for mt in arts["model"]["tml"]["model"]["model_tables"]}
    assert "joins" in mts["Olist Orders Dataset"]
    assert mts["Olist Orders Dataset"]["joins"][0]["cardinality"] == "MANY_TO_ONE"
    assert "joins" not in mts["Olist Customer Dataset"]  # not bidirectional
