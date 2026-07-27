# tools/ts-cli/tests/test_twb_extractors.py
from __future__ import annotations
import xml.etree.ElementTree as ET
from ts_cli.tableau.twb import (
    count_native_sets,
    extract_blends,
    extract_table_calc_addressing,
    detect_orphan_calcs,
    _extract_columns,
    _extract_sql_views,
    _extract_tables,
    _build_column_table_map,
    _is_extract_wrapper,
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


SQLVIEW_XML = """
<workbook><datasources>
  <datasource caption='Orders CSQ'>
    <connection>
      <relation name='Custom SQL Query' type='text'>SELECT id, region, sales FROM db.sch.orders WHERE amt >> 0 AND flag == 1</relation>
      <metadata-records>
        <metadata-record class='column'><remote-name>id</remote-name><local-name>[id]</local-name><local-type>integer</local-type><parent-name>[Custom SQL Query]</parent-name></metadata-record>
        <metadata-record class='column'><remote-name>region</remote-name><local-name>[region]</local-name><local-type>string</local-type><parent-name>[Custom SQL Query]</parent-name></metadata-record>
        <metadata-record class='column'><remote-name>sales</remote-name><local-name>[sales]</local-name><local-type>real</local-type><parent-name>[Custom SQL Query]</parent-name></metadata-record>
      </metadata-records>
    </connection>
    <column name='[sales]' caption='Sales' datatype='real' role='measure'/>
    <column name='[region]' caption='Region' datatype='string' role='dimension'/>
    <column name='[calc_1]' caption='Calc'><calculation class='tableau' formula='[sales]*2'/></column>
  </datasource>
</datasources></workbook>
"""


def test_extract_sql_views_custom_sql_relation():
    root = ET.fromstring(SQLVIEW_XML)
    ds = root.find(".//datasource")
    views = _extract_sql_views(ds)
    assert len(views) == 1
    v = views[0]
    assert v["name"] == "Custom SQL Query"
    # XML-encoding artifacts decoded: >> -> >, == -> =
    assert v["sql_query"] == "SELECT id, region, sales FROM db.sch.orders WHERE amt > 0 AND flag = 1"
    cols = {c["sql_output_column"]: c for c in v["columns"]}
    assert set(cols) == {"id", "region", "sales"}
    # role enrichment from <column> elements
    assert cols["sales"]["column_type"] == "MEASURE"
    assert cols["region"]["column_type"] == "ATTRIBUTE"
    assert cols["region"]["name"] == "Region"
    # data types mapped from local-type
    assert cols["id"]["data_type"] == "INT64"
    assert cols["sales"]["data_type"] == "DOUBLE"


def test_extract_sql_views_none_when_no_text_relation():
    root = ET.fromstring("<workbook><datasources><datasource caption='X'>"
                         "<relation name='t' type='table' table='[db].[t]'/>"
                         "</datasource></datasources></workbook>")
    ds = root.find(".//datasource")
    assert _extract_sql_views(ds) == []


# ---------------------------------------------------------------------------
# Fix #4 — hyper Extract wrapper relations must not be emitted as tables
# ---------------------------------------------------------------------------

def test_is_extract_wrapper_detects_extract_schema():
    assert _is_extract_wrapper("[Extract].[Extract]") is True
    # the wrapper's own identifier commonly re-embeds the live table's full
    # dotted db path + a GUID — must still be recognized via the FIRST segment
    assert _is_extract_wrapper(
        "[Extract].[agg_booked_monthly (dev_trusted_gold.bar_media.agg_booked_monthly)_8E5C5306]"
    ) is True


def test_is_extract_wrapper_false_for_live_source():
    assert _is_extract_wrapper("[dev_trusted_gold].[bar_media].[agg_booked_monthly]") is False
    assert _is_extract_wrapper("[Orders$]") is False
    assert _is_extract_wrapper("") is False


EXTRACT_WRAPPER_XML = """
<datasource caption='SetCtrl'>
  <connection class='federated'>
    <relation name='Orders' table='[Orders$]' type='table'/>
  </connection>
  <extract enabled='true'>
    <connection class='hyper'>
      <relation name='Extract' table='[Extract].[Extract]' type='table'/>
    </connection>
  </extract>
</datasource>
"""


def test_extract_tables_skips_extract_wrapper_relation():
    ds = ET.fromstring(EXTRACT_WRAPPER_XML)
    tables = _extract_tables(ds)
    assert [t["name"] for t in tables] == ["Orders"]


HASH_SUFFIXED_EXTRACT_XML = """
<datasource caption='Ads'>
  <connection class='federated'>
    <relation name='agg_booked_monthly' table='[dev_trusted_gold].[bar_media].[agg_booked_monthly]' type='table'/>
  </connection>
  <object-graph>
    <objects>
      <object caption='agg_booked_monthly' id='agg_booked_monthly (x)_HASH'>
        <properties context='extract'>
          <relation name='agg_booked_monthly (dev_trusted_gold.bar_media.agg_booked_monthly)_8E5C5306'
                    table='[Extract].[agg_booked_monthly (dev_trusted_gold.bar_media.agg_booked_monthly)_8E5C5306]'
                    type='table'/>
        </properties>
      </object>
    </objects>
  </object-graph>
</datasource>
"""


def test_extract_tables_skips_hash_suffixed_extract_wrapper():
    # Reproduces the Ads Commercial Dashboard shape: the hash-suffixed Extract
    # relation's own bracket segment embeds the live table's dotted db path,
    # which is exactly what broke the naive "_strip_brackets().split('.')[-1]"
    # alias_of derivation this fix sidesteps by excluding the relation outright.
    ds = ET.fromstring(HASH_SUFFIXED_EXTRACT_XML)
    tables = _extract_tables(ds)
    assert [t["name"] for t in tables] == ["agg_booked_monthly"]


def test_extract_tables_keeps_self_join_alias():
    # A genuine self-join alias (d_partner1 -> alias_of d_partner) must survive
    # the Extract-wrapper filter — it is a distinct, real join role, not a
    # hyper-cache duplicate.
    xml = """
    <datasource caption='Ads'>
      <connection class='federated'>
        <relation name='d_partner' table='[db].[s].[d_partner]' type='table'/>
        <relation name='d_partner1' table='[db].[s].[d_partner]' type='table'/>
      </connection>
    </datasource>
    """
    ds = ET.fromstring(xml)
    tables = _extract_tables(ds)
    by_name = {t["name"]: t for t in tables}
    assert set(by_name) == {"d_partner", "d_partner1"}
    assert by_name["d_partner1"]["alias_of"] == "d_partner"


# ---------------------------------------------------------------------------
# col_table_map / _extract_columns must not own columns by the Extract-wrapper
# relation's internal name — that relation is excluded by _extract_tables, so
# a column stamped to it dangles (column_id points at a table the model never
# emits) and is dropped ("XREF: column_id not found"). Reproduces
# "Demo WB 3 with SQL join.twbx": a federated Custom-SQL + hyper-Extract
# datasource writes its column metadata TWICE — once under the live
# <connection>, once (mirrored, GUID-named) under <extract>/<connection> — and
# since both sit under the same <datasource> element, a naive
# ``.//metadata-record`` walk picks up both and the extract's (document-order-
# later) copy silently wins.
# ---------------------------------------------------------------------------

TWO_RELATION_EXTRACT_XML = """
<datasource caption='Orders'>
  <connection class='federated'>
    <relation name='Orders' table='[public].[Orders]' type='table'/>
    <metadata-records>
      <metadata-record class='column'>
        <remote-name>region</remote-name>
        <local-name>[Region]</local-name>
        <parent-name>[Orders]</parent-name>
        <local-type>string</local-type>
      </metadata-record>
      <metadata-record class='column'>
        <remote-name>amount</remote-name>
        <local-name>[Amount]</local-name>
        <parent-name>[Orders]</parent-name>
        <local-type>real</local-type>
      </metadata-record>
    </metadata-records>
  </connection>
  <column name='[Region]' caption='Region' datatype='string' role='dimension'/>
  <column name='[Amount]' caption='Amount' datatype='real' role='measure'/>
  <extract enabled='true'>
    <connection class='hyper' schema='Extract' tablename='Extract'>
      <relation type='collection'>
        <relation name='Orders_9BBB0000000000000000000000000'
                  table='[Extract].[Orders_9BBB0000000000000000000000000]' type='table'/>
      </relation>
      <metadata-records>
        <metadata-record class='column'>
          <remote-name>region</remote-name>
          <local-name>[Region]</local-name>
          <parent-name>[Orders_9BBB0000000000000000000000000]</parent-name>
          <local-type>string</local-type>
        </metadata-record>
        <metadata-record class='column'>
          <remote-name>amount1</remote-name>
          <local-name>[Amount]</local-name>
          <parent-name>[Orders_9BBB0000000000000000000000000]</parent-name>
          <local-type>real</local-type>
        </metadata-record>
      </metadata-records>
    </connection>
  </extract>
</datasource>
"""


def test_build_column_table_map_remaps_extract_wrapper_owned_columns_to_live_source():
    ds = ET.fromstring(TWO_RELATION_EXTRACT_XML)
    tables = _extract_tables(ds)
    assert [t["name"] for t in tables] == ["Orders"]  # wrapper excluded, as before

    col_map = _build_column_table_map(ds, tables)
    assert col_map["Region"] == "Orders"
    assert col_map["Amount"] == "Orders"
    # Never the wrapper's own (excluded) internal relation name.
    assert "Orders_9BBB0000000000000000000000000" not in col_map.values()


def test_extract_columns_table_field_uses_live_source_not_extract_wrapper():
    ds = ET.fromstring(TWO_RELATION_EXTRACT_XML)
    tables = _extract_tables(ds)
    columns = _extract_columns(ds, tables)
    by_name = {c["name"]: c for c in columns}
    assert by_name["Region"]["table"] == "Orders"
    assert by_name["Amount"]["table"] == "Orders"


def test_extract_columns_db_column_name_unaffected_by_extract_wrapper_disambiguation():
    # The extract's own metadata-record can carry an internally-disambiguated
    # remote-name (Tableau appends a numeric suffix — 'amount1' here, 'Sales
    # Person1' in the live repro — when the hyper extract joins two sources
    # with a colliding column name). That must never leak into db_column_name;
    # the live connection's remote-name is the real warehouse identity.
    ds = ET.fromstring(TWO_RELATION_EXTRACT_XML)
    tables = _extract_tables(ds)
    columns = _extract_columns(ds, tables)
    by_name = {c["name"]: c for c in columns}
    assert by_name["Amount"]["db_column_name"] == "amount"


DOTTED_RELATION_NAME_XML = """
<datasource caption='Orders'>
  <connection class='federated'>
    <relation name='dim_sales_team_clean_updated.csv1'
              table='[dim_sales_team_clean_updated#csv]' type='table'/>
    <metadata-records>
      <metadata-record class='column'>
        <remote-name>Manager Name</remote-name>
        <local-name>[Manager Name]</local-name>
        <parent-name>[dim_sales_team_clean_updated.csv1]</parent-name>
        <local-type>string</local-type>
      </metadata-record>
    </metadata-records>
  </connection>
  <column name='[Manager Name]' caption='Manager Name' datatype='string' role='dimension'/>
</datasource>
"""


def test_build_column_table_map_preserves_literal_dot_in_relation_name():
    # A file-backed relation's own `name` can legitimately embed a literal '.'
    # (e.g. a CSV extract Tableau names 'dim_sales_team_clean_updated.csv1') —
    # metadata-record `parent-name` referencing it must resolve to the whole
    # relation name, not get truncated at the last '.' to 'csv1' (a table
    # `_extract_tables` never emits, which reproduces the same dangling-
    # column_id XREF as the wrapper-name bug above).
    ds = ET.fromstring(DOTTED_RELATION_NAME_XML)
    tables = _extract_tables(ds)
    assert [t["name"] for t in tables] == ["dim_sales_team_clean_updated.csv1"]

    col_map = _build_column_table_map(ds, tables)
    assert col_map["Manager Name"] == "dim_sales_team_clean_updated.csv1"

    columns = _extract_columns(ds, tables)
    assert columns[0]["table"] == "dim_sales_team_clean_updated.csv1"


# ---------------------------------------------------------------------------
# Fix #2 — Tableau disambiguation suffix must not leak into db_column_name
# ---------------------------------------------------------------------------

COLLISION_COLUMNS_XML = """
<datasource caption='Ads'>
  <connection class='federated'>
    <relation name='agg_booked_monthly' table='[db].[s].[agg_booked_monthly]' type='table'/>
    <relation name='v_lineitem_budgetline' table='[db].[s].[v_lineitem_budgetline]' type='table'/>
    <metadata-records>
      <metadata-record class='column'>
        <remote-name>LineItemId</remote-name>
        <local-name>[LineItemId (agg_booked_monthly)]</local-name>
        <parent-name>[agg_booked_monthly]</parent-name>
        <local-type>integer</local-type>
      </metadata-record>
      <metadata-record class='column'>
        <remote-name>LineItemId</remote-name>
        <local-name>[LineItemId (v_lineitem_budgetline)]</local-name>
        <parent-name>[v_lineitem_budgetline]</parent-name>
        <local-type>integer</local-type>
      </metadata-record>
    </metadata-records>
  </connection>
  <column name='[LineItemId (agg_booked_monthly)]' caption='LineItemId (agg booked monthly)' datatype='integer' role='dimension'/>
  <column name='[LineItemId (v_lineitem_budgetline)]' caption='LineItemId (v lineitem budgetline)' datatype='integer' role='dimension'/>
</datasource>
"""


def test_extract_columns_strips_disambiguation_suffix_from_db_column_name():
    ds = ET.fromstring(COLLISION_COLUMNS_XML)
    tables = _extract_tables(ds)
    columns = _extract_columns(ds, tables)
    by_caption = {c["name"]: c for c in columns}

    agg_col = by_caption["LineItemId (agg booked monthly)"]
    budget_col = by_caption["LineItemId (v lineitem budgetline)"]

    # db_column_name is the real physical column — no " (table_name)" suffix —
    # even though the collision leaves it on the display `name` (Tableau's own
    # disambiguation, harmless as a display string).
    assert agg_col["db_column_name"] == "LineItemId"
    assert budget_col["db_column_name"] == "LineItemId"

    # stamped to its owning table (from the metadata-record's parent-name) so
    # column_id can be TABLE::col-qualified — required once db_column_name is
    # no longer unique on its own, else the two would collide into one
    # column_id ("columns should have unique column_id values").
    assert agg_col["table"] == "agg_booked_monthly"
    assert budget_col["table"] == "v_lineitem_budgetline"


def test_extract_columns_falls_back_to_internal_name_without_metadata_record():
    ds = ET.fromstring(
        "<datasource caption='Simple'>"
        "<column name='[Sales]' caption='Sales' datatype='real' role='measure'/>"
        "</datasource>"
    )
    columns = _extract_columns(ds, [])
    assert columns[0]["db_column_name"] == "Sales"
    assert "table" not in columns[0]


def test_build_column_table_map_unaffected_by_shared_helper_refactor():
    ds = ET.fromstring(COLLISION_COLUMNS_XML)
    tables = _extract_tables(ds)
    col_map = _build_column_table_map(ds, tables)
    assert col_map["LineItemId (agg_booked_monthly)"] == "agg_booked_monthly"
    assert col_map["LineItemId (v_lineitem_budgetline)"] == "v_lineitem_budgetline"


# ---------------------------------------------------------------------------
# count_native_sets (BL-131) — native Tableau Sets, not auto-converted by
# build-model (Phase-2a/2b/2c set->cohort is an agent-guided step).
# ---------------------------------------------------------------------------

# A static union set (real Set — live-reproduced shape from
# TableauSetControlUseCases.twbx's "Customer Group 1").
STATIC_SET_XML = """
<workbook><datasources>
  <datasource caption='Orders'>
    <group name='[Customer Group 1]'>
      <groupfilter function='union'>
        <groupfilter function='member' level='[Customer Name]' member='&quot;Aaron Bergman&quot;'/>
        <groupfilter function='member' level='[Customer Name]' member='&quot;Aaron Hawkins&quot;'/>
      </groupfilter>
    </group>
  </datasource>
</datasources></workbook>
"""

# A Top-N ranked set (also a real Set — BL-009 Phase 2b) — must count too.
TOPN_SET_XML = """
<workbook><datasources>
  <datasource caption='Orders'>
    <group name='[State Top N]'>
      <groupfilter count='5' end='top' function='end' units='records'>
        <groupfilter direction='DESC' expression='SUM([Sales])' function='order'/>
        <groupfilter function='level-members' level='[State]'/>
      </groupfilter>
    </group>
  </datasource>
</datasources></workbook>
"""

# Tableau's internal combined-field mechanism for multi-field dashboard
# Actions/Tooltips — a <group> element, but NOT a user-created Set (live-
# reproduced shape from Ads Commercial Dashboard's "Action (...)" groups).
# Must be excluded from the count.
CROSSJOIN_GROUP_XML = """
<workbook><datasources>
  <datasource caption='Orders'>
    <group name='[Action (Region,Category)]'>
      <groupfilter function='crossjoin'>
        <groupfilter function='level-members' level='[Region]'/>
        <groupfilter function='level-members' level='[Category]'/>
      </groupfilter>
    </group>
  </datasource>
</datasources></workbook>
"""

# Tableau's Pivot construct — a <group> with no <groupfilter> child at all
# (plain <field> children instead). Not a Set either.
PIVOT_GROUP_XML = """
<workbook><datasources>
  <datasource caption='Orders'>
    <group name='Pivot Field Values'>
      <field name='[2000-01]'/>
      <field name='[2001-02]'/>
    </group>
  </datasource>
</datasources></workbook>
"""


def test_count_native_sets_static_union():
    root = ET.fromstring(STATIC_SET_XML)
    assert count_native_sets(root) == 1


def test_count_native_sets_topn_counts_as_a_set():
    root = ET.fromstring(TOPN_SET_XML)
    assert count_native_sets(root) == 1


def test_count_native_sets_excludes_crossjoin_action_tooltip_groups():
    root = ET.fromstring(CROSSJOIN_GROUP_XML)
    assert count_native_sets(root) == 0


def test_count_native_sets_excludes_pivot_groups_with_no_groupfilter():
    root = ET.fromstring(PIVOT_GROUP_XML)
    assert count_native_sets(root) == 0


def test_count_native_sets_zero_when_no_groups():
    root = ET.fromstring("<workbook><datasources><datasource caption='Orders'>"
                         "<relation name='t' type='table' table='[db].[t]'/>"
                         "</datasource></datasources></workbook>")
    assert count_native_sets(root) == 0


def test_count_native_sets_mixed_workbook_counts_only_real_sets():
    root = ET.fromstring("""
    <workbook><datasources>
      <datasource caption='Orders'>
        <group name='[Customer Group 1]'>
          <groupfilter function='union'>
            <groupfilter function='member' level='[Customer Name]' member='&quot;X&quot;'/>
          </groupfilter>
        </group>
        <group name='[Action (Region)]'>
          <groupfilter function='crossjoin'>
            <groupfilter function='level-members' level='[Region]'/>
          </groupfilter>
        </group>
        <group name='Pivot Field Values'>
          <field name='[a]'/>
        </group>
      </datasource>
    </datasources></workbook>
    """)
    assert count_native_sets(root) == 1
