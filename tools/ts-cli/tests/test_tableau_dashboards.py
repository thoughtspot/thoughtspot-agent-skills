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


# ---------------------------------------------------------------------------
# Tableau pivot pseudo-fields must not become liveboard fields (SCAL-338494)
#
# `reconcile.py` drops them from Model/Table TML, so a liveboard that still
# named one would reference a column the Model does not have — and no gate
# sees it (`lint_cross_references` is Model-only, `lint_tml` is clean on the
# liveboard). The token stays a TRIGGER for the measure-values branch; it must
# never become a field.
# ---------------------------------------------------------------------------

_REAL_MEASURE = ("<column-instance name='[sum:Units:qk]' column='[Units Sold]' "
                 "derivation='Sum' type='quantitative'/>")
_MN_INST = ("<column-instance name='[:Measure Names]' column='[:Measure Names]' "
            "derivation='None' type='nominal'/>")
_MV_INST = ("<column-instance name='[Multiple Values]' column='[Multiple Values]' "
            "derivation='None' type='nominal'/>")


def _ws(rows="", cols="", instances=""):
    return ET.fromstring(
        f"""<worksheet name='Scorecard'><table><view>
              <datasource-dependencies datasource='federated.x'>
                {instances}{_REAL_MEASURE}
              </datasource-dependencies>
            </view><rows>{rows}</rows><cols>{cols}</cols></table>
            <mark class='Bar'/></worksheet>""")


def _field_names(ws):
    from ts_cli.tableau.dashboards import _instances, _ws_fields
    return [f["name"] for f in _ws_fields(ws, _instances(ws), {})[0]]


def test_shelf_ref_to_measure_names_is_not_emitted_as_a_field():
    # resolves fine — `_resolve` returns it — but must not reach the field list
    assert _field_names(_ws(rows="([federated.x].[:Measure Names])",
                            instances=_MN_INST)) == ["Units Sold"]


def test_measure_values_branch_does_not_emit_the_pseudo_field():
    # the branch iterates EVERY column-instance, including the pseudo-field's own
    assert _field_names(_ws(cols="([federated.x].[Multiple Values])",
                            instances=_MN_INST)) == ["Units Sold"]


def test_multiple_values_with_its_own_instance_is_not_emitted():
    assert _field_names(_ws(cols="([federated.x].[Multiple Values])",
                            instances=_MV_INST)) == ["Units Sold"]


def test_measure_values_trigger_still_fires_without_a_pseudo_column_instance():
    """The trigger reads the raw shelf TEXT, not the filtered field list. Filtering
    the pseudo-fields inside `add()` must not disable it — a shelf naming only the
    trigger still has to pull the worksheet's real measures through."""
    names = _field_names(_ws(cols="([federated.x].[Multiple Values])"))
    assert names == ["Units Sold"], "measure-values trigger was disabled by the filter"


def test_a_filter_only_pseudo_field_does_not_become_a_pivot_trigger():
    """`_PSEUDO_FIELDS` (never emit this column) and `_PIVOT_PSEUDO_FIELDS` (this
    worksheet is a Measure Values pivot) are separate on purpose. Adding a filter-only
    member must not make its token fire the measure-values branch, which pulls EVERY
    column-instance into the field list.

    The module is RELOADED after patching: `dashboards` binds the constant with
    `from … import …`, so rebinding it on `reconcile` alone would leave the already-bound
    name untouched and the test would pass whatever the trigger reads."""
    import importlib
    import ts_cli.tableau.reconcile as rec
    import ts_cli.tableau.dashboards as dash

    ws = _ws(cols="([federated.x].[Latitude (generated)])")
    original = rec._PSEUDO_FIELDS
    try:
        rec._PSEUDO_FIELDS = frozenset(original | {"Latitude (generated)"})
        importlib.reload(dash)
        fields, _ = dash._ws_fields(ws, dash._instances(ws), {})
        assert [f["name"] for f in fields] == [], "a filter-only member fired the pivot trigger"
    finally:
        rec._PSEUDO_FIELDS = original
        importlib.reload(dash)


def test_emitted_answer_tml_names_neither_pseudo_field():
    import json
    from ts_cli.tableau.liveboard import build_from_spec

    ws = _ws(rows="([federated.x].[:Measure Names])",
             cols="([federated.x].[Multiple Values])", instances=_MN_INST + _MV_INST)
    visual = worksheet_visual("Scorecard", ws, {})
    spec = {"report_name": "R", "model_name": "M", "model_fqn": "GUID",
            "measure_names": ["Units Sold"],
            "dashboards": [{"name": "D", "visuals": [
                dict(visual, tile={"x": 0, "y": 0, "width": 6, "height": 6})]}]}
    blob = json.dumps(build_from_spec(spec))
    assert ":Measure Names" not in blob
    assert "Multiple Values" not in blob
    assert "Units Sold" in blob
