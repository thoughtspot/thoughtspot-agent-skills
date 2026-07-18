"""Unit tests for dashboard/visual extraction (ts tableau parse #20)."""
import xml.etree.ElementTree as ET

from ts_cli.tableau.dashboards import extract_dashboards, worksheet_visual

# Minimal TWB: one dashboard with two viz zones + a legend zone; a calc column with a
# caption to exercise calc-id → display-name resolution and a month-trunc date bucket.
_TWB = """<workbook>
  <datasources>
    <datasource>
      <column caption="Speeding Events" name="[Calculation_99]" />
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name="Top 5 Speeding Drivers">
      <table>
        <rows>[ds].[sum:Calculation_99:qk]</rows>
        <cols>[ds].[none:Driver Name:nk]</cols>
      </table>
      <datasource-dependencies>
        <column-instance name="[sum:Calculation_99:qk]" column="[Calculation_99]" derivation="Sum" type="quantitative" />
        <column-instance name="[none:Driver Name:nk]" column="[Driver Name]" derivation="None" type="nominal" />
      </datasource-dependencies>
    </worksheet>
    <worksheet name="Sales Trend">
      <table>
        <cols>[ds].[tmn:Order Date:qk]</cols>
        <rows>[ds].[sum:Sales:qk]</rows>
      </table>
      <datasource-dependencies>
        <column-instance name="[tmn:Order Date:qk]" column="[Order Date]" derivation="Month-Trunc" type="quantitative" />
        <column-instance name="[sum:Sales:qk]" column="[Sales]" derivation="Sum" type="quantitative" />
      </datasource-dependencies>
    </worksheet>
  </worksheets>
  <dashboards>
    <dashboard name="My Dash">
      <zones>
        <zone name="Top 5 Speeding Drivers" x="0" y="0" w="50000" h="50000" />
        <zone name="Sales Trend" x="50000" y="0" w="50000" h="50000" />
        <zone type-v2="color" />
        <zone name="Top 5 Speeding Drivers" x="0" y="60000" w="50000" h="20000" />
      </zones>
    </dashboard>
  </dashboards>
</workbook>"""


def _dash():
    return extract_dashboards(ET.fromstring(_TWB))


def test_one_dashboard_two_deduped_visuals():
    d = _dash()
    assert len(d) == 1 and d[0]["name"] == "My Dash"
    titles = [v["title"] for v in d[0]["visuals"]]
    assert titles == ["Top 5 Speeding Drivers", "Sales Trend"]  # legend skipped, dupe deduped


def test_calc_id_resolves_to_caption_and_measure():
    v = [x for x in _dash()[0]["visuals"] if x["title"] == "Top 5 Speeding Drivers"][0]
    fields = {f["name"]: f for f in v["fields"]}
    assert "Speeding Events" in fields               # [Calculation_99] → caption
    assert fields["Speeding Events"]["measure"] is True       # Sum/quantitative
    assert fields["Driver Name"]["measure"] is False          # nominal → dimension
    assert fields["Driver Name"]["role"] == "Category"        # cols shelf


def test_date_bucket_token():
    v = [x for x in _dash()[0]["visuals"] if x["title"] == "Sales Trend"][0]
    assert v["bucket_tokens"].get("Order Date") == "[Order Date].monthly"
    od = [f for f in v["fields"] if f["name"] == "Order Date"][0]
    assert od["measure"] is False    # date bucket is a dimension, not a measure


def test_tile_from_zone_coords():
    v = _dash()[0]["visuals"][0]
    assert v["tile"] == {"x": 0, "y": 0, "width": 6, "height": 10}   # 50000/100000*12≈6, *20=10


def test_worksheet_with_no_fields_returns_none():
    ws = ET.fromstring('<worksheet name="empty"><table/></worksheet>')
    assert worksheet_visual("empty", ws, {}) is None
