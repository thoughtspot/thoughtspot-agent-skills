# tools/ts-cli/tests/test_tableau_sets_extract.py
"""extract_sets (BL-067 part 1) — Set -> classified-spec extraction from TWB XML.

One fixture per documented set type (step-5-tml-generation.md "Tableau Sets ->
ThoughtSpot column sets (Phase 2a/2b/2c)"). Real-shape XML snippets are lifted
from TableauSetControlUseCases.twbx where possible (see test_twb_extractors.py's
STATIC_SET_XML/TOPN_SET_XML for the same live-reproduced-shape convention).
"""
from __future__ import annotations
import xml.etree.ElementTree as ET

from ts_cli.tableau.twb import extract_sets


def _ds(inner: str) -> ET.Element:
    return ET.fromstring(f"<datasource caption='Orders'>{inner}</datasource>")


# ---------------------------------------------------------------------------
# static (Phase 2a)
# ---------------------------------------------------------------------------

def test_static_set_union_of_members():
    ds = _ds("""
      <column name='[Customer Name]' caption='Customer Name' datatype='string'/>
      <group caption='Customer Group 1' name='[Customer Group 1]'>
        <groupfilter function='union'>
          <groupfilter function='member' level='[Customer Name]' member='&quot;Aaron Bergman&quot;'/>
          <groupfilter function='member' level='[Customer Name]' member='&quot;Aaron Hawkins&quot;'/>
        </groupfilter>
      </group>
    """)
    sets = extract_sets(ds)
    assert len(sets) == 1
    s = sets[0]
    assert s["name"] == "Customer Group 1"
    assert s["set_type"] == "static"
    assert s["anchor_name"] == "Customer Name"
    assert s["anchor_ref"] == "Customer Name"
    assert s["anchor_is_calc"] is False
    assert s["anchor_datatype"] == "string"
    assert s["members"] == ["Aaron Bergman", "Aaron Hawkins"]


def test_static_set_null_member_included():
    ds = _ds("""
      <column name='[Category]' caption='Category' datatype='string'/>
      <group caption='01. Category Set' name='[Category Set]'>
        <groupfilter function='union'>
          <groupfilter function='member' level='[Category]' member='&quot;Furniture&quot;'/>
          <groupfilter function='member' level='[Category]' member='%null%'/>
        </groupfilter>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["set_type"] == "static"
    assert s["members"] == ["Furniture", "%null%"]


def test_static_set_anchored_on_calc_formula_column():
    """A set anchored on [Calculation_NNN] resolves the anchor to the calc's
    display name (caption), not the raw internal id (step-5-tml-generation.md:
    'Never emit the raw Calculation_NNN id as anchor_column_id')."""
    ds = _ds("""
      <column name='[Calculation_1368249874240847883]' caption='Year' datatype='integer'>
        <calculation class='tableau' formula='YEAR([Order Date])'/>
      </column>
      <group caption='Year Set' name='[Year Set]'>
        <groupfilter function='member' level='[Calculation_1368249874240847883]' member='2018'/>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["set_type"] == "static"
    assert s["anchor_ref"] == "Calculation_1368249874240847883"
    assert s["anchor_name"] == "Year"
    assert s["anchor_is_calc"] is True
    assert s["anchor_datatype"] == "integer"
    assert s["members"] == ["2018"]


# ---------------------------------------------------------------------------
# except of a member list (translatable via NE)
# ---------------------------------------------------------------------------

def test_except_member_list_excludes_null_and_regular_member():
    ds = _ds("""
      <column name='[Category]' caption='Category' datatype='string'/>
      <group caption='Category Set' name='[Category Set]'>
        <groupfilter function='except'>
          <groupfilter function='level-members' level='[Category]'/>
          <groupfilter function='union'>
            <groupfilter function='member' level='[Category]' member='&quot;Furniture&quot;'/>
            <groupfilter function='member' level='[Category]' member='%null%'/>
          </groupfilter>
        </groupfilter>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["set_type"] == "except_members"
    assert s["anchor_name"] == "Category"
    assert s["members"] == ["Furniture", "%null%"]


# ---------------------------------------------------------------------------
# Top-N / Bottom-N (Phase 2b)
# ---------------------------------------------------------------------------

def test_topn_literal_count():
    ds = _ds("""
      <column name='[State]' caption='State' datatype='string'/>
      <group caption='State Top N' name='[State Top N]'>
        <groupfilter count='5' end='top' function='end' units='records'>
          <groupfilter direction='DESC' expression='SUM([Sales])' function='order'/>
          <groupfilter function='level-members' level='[State]'/>
        </groupfilter>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["set_type"] == "topn"
    assert s["anchor_name"] == "State"
    assert s["topn_direction"] == "top"
    assert s["topn_count_literal"] == 5
    assert "topn_count_param" not in s
    assert s["order_expr"] == "SUM([Sales])"


def test_topn_parameter_driven_count():
    ds = _ds("""
      <column name='[State]' caption='State' datatype='string'/>
      <group caption='State Top N' name='[State Top N]'>
        <groupfilter count='[Parameters].[topN]' end='top' function='end' units='records'>
          <groupfilter direction='DESC' expression='SUM([gallons])' function='order'/>
          <groupfilter function='level-members' level='[State]'/>
        </groupfilter>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["set_type"] == "topn"
    assert s["topn_count_param"] == "[Parameters].[topN]"
    assert "topn_count_literal" not in s
    assert s["order_expr"] == "SUM([gallons])"


def test_bottom_n_direction():
    ds = _ds("""
      <column name='[State]' caption='State' datatype='string'/>
      <group caption='State Bottom N' name='[State Bottom N]'>
        <groupfilter count='5' end='bottom' function='end' units='records'>
          <groupfilter direction='ASC' expression='SUM([Sales])' function='order'/>
          <groupfilter function='level-members' level='[State]'/>
        </groupfilter>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["topn_direction"] == "bottom"


# ---------------------------------------------------------------------------
# all-except-Top-N (Phase 2c — inverted rank)
# ---------------------------------------------------------------------------

def test_except_topn_whole_domain_minus_topn():
    ds = _ds("""
      <column name='[State]' caption='State' datatype='string'/>
      <group caption='State NotTopN' name='[State NotTopN]'>
        <groupfilter function='except'>
          <groupfilter function='level-members' level='[State]'/>
          <groupfilter count='10' end='top' function='end' units='records'>
            <groupfilter direction='DESC' expression='SUM([Sales])' function='order'/>
            <groupfilter function='level-members' level='[State]'/>
          </groupfilter>
        </groupfilter>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["set_type"] == "except_topn"
    assert s["topn_direction"] == "top"
    assert s["topn_count_literal"] == 10
    assert s["order_expr"] == "SUM([Sales])"


# ---------------------------------------------------------------------------
# intersect of two member lists (Phase 2c)
# ---------------------------------------------------------------------------

def test_intersect_member_lists_computes_common_members():
    ds = _ds("""
      <column name='[State]' caption='State' datatype='string'/>
      <group caption='Region Intersect' name='[Region Intersect]'>
        <groupfilter function='intersect'>
          <groupfilter function='union'>
            <groupfilter function='member' level='[State]' member='&quot;New York&quot;'/>
            <groupfilter function='member' level='[State]' member='&quot;Ohio&quot;'/>
            <groupfilter function='member' level='[State]' member='&quot;Texas&quot;'/>
          </groupfilter>
          <groupfilter function='union'>
            <groupfilter function='member' level='[State]' member='&quot;Ohio&quot;'/>
            <groupfilter function='member' level='[State]' member='&quot;Texas&quot;'/>
            <groupfilter function='member' level='[State]' member='&quot;Nevada&quot;'/>
          </groupfilter>
        </groupfilter>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["set_type"] == "intersect_members"
    assert s["members"] == ["Ohio", "Texas"]
    assert s["side_member_counts"] == [3, 3]


def test_intersect_member_lists_empty_intersection():
    ds = _ds("""
      <column name='[State]' caption='State' datatype='string'/>
      <group caption='No Overlap' name='[No Overlap]'>
        <groupfilter function='intersect'>
          <groupfilter function='union'>
            <groupfilter function='member' level='[State]' member='&quot;New York&quot;'/>
          </groupfilter>
          <groupfilter function='union'>
            <groupfilter function='member' level='[State]' member='&quot;Ohio&quot;'/>
          </groupfilter>
        </groupfilter>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["set_type"] == "intersect_members"
    assert s["members"] == []


# ---------------------------------------------------------------------------
# condition-based (Phase 2c)
# ---------------------------------------------------------------------------

def test_condition_based_set():
    ds = _ds("""
      <column name='[Customer Name]' caption='Customer Name' datatype='string'/>
      <group caption='HighRevCustomers' name='[HighRevCustomers]'>
        <groupfilter function='filter' level='[Customer Name]' expression='SUM([Sales]) &gt; 10000'/>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["set_type"] == "condition"
    assert s["anchor_name"] == "Customer Name"
    assert s["condition_expr"] == "SUM([Sales]) > 10000"


# ---------------------------------------------------------------------------
# Set Control (dynamic, no fixed members — untranslatable, drop the scaffolding)
# ---------------------------------------------------------------------------

def test_set_control_level_members_only():
    ds = _ds("""
      <column name='[Calculation_1368249874239139850]' caption='01. Month' datatype='date'>
        <calculation class='tableau' formula=\"DATE(DATETRUNC('month', [Order Date]))\"/>
      </column>
      <group caption='01. Month Set' name='[01. Month Set]'>
        <groupfilter function='level-members' level='[Calculation_1368249874239139850]' ui-enumeration='all'/>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["set_type"] == "set_control"
    assert s["anchor_name"] == "01. Month"
    assert s["anchor_is_calc"] is True


# ---------------------------------------------------------------------------
# mixed computed set operations (Phase 2c — member-list combined with a
# computed side; distinct from the simpler except_topn "whole domain" case)
# ---------------------------------------------------------------------------

def test_mixed_intersect_of_member_list_and_topn():
    ds = _ds("""
      <column name='[State]' caption='State' datatype='string'/>
      <group caption='East Top Revenue' name='[East Top Revenue]'>
        <groupfilter function='intersect'>
          <groupfilter function='union'>
            <groupfilter function='member' level='[State]' member='&quot;New York&quot;'/>
            <groupfilter function='member' level='[State]' member='&quot;California&quot;'/>
          </groupfilter>
          <groupfilter count='10' end='top' function='end' units='records'>
            <groupfilter direction='DESC' expression='SUM([Revenue])' function='order'/>
            <groupfilter function='level-members' level='[State]'/>
          </groupfilter>
        </groupfilter>
      </group>
    """)
    s = extract_sets(ds)[0]
    assert s["set_type"] == "mixed"
    assert s["mixed_op"] == "intersect"
    sides = s["sides"]
    assert len(sides) == 2
    assert sides[0]["kind"] == "members"
    assert sides[0]["members"] == ["New York", "California"]
    assert sides[1]["kind"] == "topn"
    assert sides[1]["topn_count_literal"] == 10
    assert sides[1]["order_expr"] == "SUM([Revenue])"


# ---------------------------------------------------------------------------
# Non-set <group> shapes are excluded entirely (same rule as count_native_sets)
# ---------------------------------------------------------------------------

def test_crossjoin_action_tooltip_group_excluded():
    ds = _ds("""
      <group caption='Action (Region,Category)' name='[Action (Region,Category)]'>
        <groupfilter function='crossjoin'>
          <groupfilter function='level-members' level='[Region]'/>
          <groupfilter function='level-members' level='[Category]'/>
        </groupfilter>
      </group>
    """)
    assert extract_sets(ds) == []


def test_pivot_group_with_no_groupfilter_excluded():
    ds = _ds("""
      <group name='Pivot Field Values'>
        <field name='[2000-01]'/>
      </group>
    """)
    assert extract_sets(ds) == []


def test_no_groups_returns_empty_list():
    ds = _ds("<relation name='t' type='table' table='[db].[t]'/>")
    assert extract_sets(ds) == []
