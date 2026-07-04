# tools/ts-cli/tests/test_twb_extractors.py
from __future__ import annotations
import xml.etree.ElementTree as ET
from ts_cli.tableau.twb import (
    extract_blends,
    extract_table_calc_addressing,
    detect_orphan_calcs,
)

BLEND_XML = """
<workbook>
  <datasource name='federated.a' caption='Orders'/>
  <datasource name='federated.b' caption='Targets'/>
  <datasource-relationships>
    <datasource-dependencies datasource='federated.a'>
      <column-instance name='[none:Category:nk]' column='[Category]'/>
    </datasource-dependencies>
    <datasource-dependencies datasource='federated.b'>
      <column-instance name='[none:Cat:nk]' column='[Cat]'/>
    </datasource-dependencies>
    <datasource-relationship source='federated.a' target='federated.b'>
      <column-mapping>
        <map key='[federated.a].[none:Category:nk]' value='[federated.b].[none:Cat:nk]'/>
      </column-mapping>
    </datasource-relationship>
  </datasource-relationships>
</workbook>
"""

def test_extract_blends_keys_by_caption_and_resolves_columns():
    root = ET.fromstring(BLEND_XML)
    graph = extract_blends(root)
    assert list(graph.keys()) == ["Orders"]
    edge = graph["Orders"][0]
    assert edge["target_ds"] == "Targets"
    assert edge["column_mappings"] == [{"source_col": "Category", "target_col": "Cat"}]

def test_extract_blends_absent_returns_empty():
    root = ET.fromstring("<workbook></workbook>")
    assert extract_blends(root) == {}


TC_XML = """
<workbook>
  <datasource>
    <column name='[Calculation_1]'>
      <calculation class='tableau'>
        <table-calc ordering-type='Rows' type='PctTotal'>
          <address><value>2</value></address>
        </table-calc>
      </calculation>
    </column>
  </datasource>
  <worksheet name='Sheet 1'>
    <column-instance column='[Calculation_1]'>
      <table-calc ordering-type='Columns'/>
    </column-instance>
  </worksheet>
</workbook>
"""

def test_extract_table_calc_addressing_column_and_ws():
    root = ET.fromstring(TC_XML)
    addr = extract_table_calc_addressing(root)
    col = addr["column_level"]["[Calculation_1]"]
    assert col["ordering_type"] == "Rows"
    assert col["quick_calc_type"] == "PctTotal"
    assert col["address_offset"] == 2
    assert addr["ws_overrides"]["Sheet 1"]["[Calculation_1]"]["ordering_type"] == "Columns"

def test_extract_table_calc_addressing_none():
    root = ET.fromstring("<workbook><worksheet name='S'/></workbook>")
    addr = extract_table_calc_addressing(root)
    assert addr == {"column_level": {}, "ws_overrides": {"S": {}}}


def test_detect_orphan_calcs_direct_and_transitive():
    ds = {
        "tables": [{"name": "ORDERS", "db_table": "db.s.ORDERS"}],
        "calc_map": {"Calculation_9": "Ghost Sum", "[Calculation_9]": "Ghost Sum"},
        "calculated_fields": [
            {"caption": "Ghost Sum", "formula": "SUM([MISSING::Amount])"},   # direct orphan
            {"caption": "Depends", "formula": "[Calculation_9] * 2"},         # transitive orphan
            {"caption": "Fine", "formula": "SUM([ORDERS::Amount])"},          # ok
        ],
    }
    assert detect_orphan_calcs(ds) == ["Depends", "Ghost Sum"]

def test_detect_orphan_calcs_none():
    ds = {"tables": [{"name": "ORDERS"}], "calc_map": {},
          "calculated_fields": [{"caption": "Fine", "formula": "SUM([ORDERS::A])"}]}
    assert detect_orphan_calcs(ds) == []
