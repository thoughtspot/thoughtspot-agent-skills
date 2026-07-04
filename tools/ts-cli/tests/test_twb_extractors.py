# tools/ts-cli/tests/test_twb_extractors.py
from __future__ import annotations
import xml.etree.ElementTree as ET
from ts_cli.tableau.twb import extract_blends

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
