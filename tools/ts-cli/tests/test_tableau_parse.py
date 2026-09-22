# tools/ts-cli/tests/test_tableau_parse.py
"""CLI test for `ts tableau parse` (Task 4 — Component 1; `blend_plan` — Task 8).

Composes the existing `parse_twb` (tables/columns/joins/calcs) with the three
pure extractors added in Tasks 1-3 (`extract_blends`,
`extract_table_calc_addressing`, `detect_orphan_calcs`) into one JSON output
file, so SKILL.md Step 3 can read structured JSON instead of hand-parsing the
TWB XML. Task 8 (Phase 3) adds `blend_plan`, built from `blends` +
`datasources` via `build_blend_plan`.
"""
from __future__ import annotations

import json


from ts_cli.cli import app

from runners import runner  # noqa: E402  (BL-139: one definition, see runners.py)

TWB = """<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='Orders'>
    <relation name='ORDERS' type='table' table='[db].[s].[ORDERS]'/>
    <column name='[Amount]' datatype='real' role='measure' caption='Amount'/>
    <column name='[Calculation_1]' caption='Ghost' datatype='real'>
      <calculation class='tableau' formula='SUM([MISSING::x])'/>
    </column>
  </datasource>
</workbook>
"""


def test_parse_writes_augmented_json(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(TWB)
    out = tmp_path / "parsed.json"

    result = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(out)])

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(out.read_text())
    assert {"datasources", "parameters", "param_map", "blends",
            "table_calc_addressing", "blend_plan"} <= set(data)

    ds = data["datasources"][0]
    assert ds["name"] == "Orders"
    assert ds["orphan_calcs"] == ["Ghost"]  # references MISSING:: table
    assert data["blends"] == {}
    assert data["table_calc_addressing"] == {
        "column_level": {}, "ws_overrides": {}, "warnings": []
    }
    # No blends in this fixture — blend_plan is the all-empty shape.
    assert data["blend_plan"] == {"components": [], "ds_table_map": {}, "joins": []}


# SCAL-338450 regressed at THIS layer, not in the extractor: a non-numeric
# <address><value> raised out of parse_cmd, so the command exited non-zero and
# wrote no output file, discarding an already-successful parse_twb. Asserting on
# the extractor alone would not catch a raise reintroduced before the write, nor
# a dropped warning emit. The worksheet <column-instance> path is the one that
# fires on real workbooks.
NON_NUMERIC_ADDRESS_TWB = """<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='Orders'>
    <relation name='ORDERS' type='table' table='[db].[s].[ORDERS]'/>
    <column name='[Amount]' datatype='real' role='measure' caption='Amount'/>
  </datasource>
  <worksheet name='Heat Map'>
    <column-instance column='[cost]'>
      <table-calc ordering-type='Rows' type='PctDiff'>
        <address><value>false</value></address>
      </table-calc>
    </column-instance>
  </worksheet>
</workbook>
"""


# SCAL-330635: `_extract_joins` returns (joins, warnings) and `parse_twb` puts the
# warnings on the datasource as `join_warnings`. Both halves are unit-tested, the
# wire between them was not — deleting that one assignment left every unit test
# green while the whole reporting chain went dead. These two drive the real
# command so the wiring is covered end to end; the pair is deliberate, since the
# skip test alone passes just as well when nothing is extracted at all.
def _join_twb(operator: str) -> str:
    return f"""<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='Orders'>
    <relation join='inner' type='join'>
      <relation name='ORDERS' type='table' table='[db].[s].[ORDERS]'/>
      <relation name='RETURNS' type='table' table='[db].[s].[RETURNS]'/>
      <clause type='join'>
        <expression op='{operator}'>
          <expression op='[ORDERS].[OrderId]'/>
          <expression op='[RETURNS].[OrderId]'/>
        </expression>
      </clause>
    </relation>
    <column name='[Amount]' datatype='real' role='measure' caption='Amount'/>
  </datasource>
</workbook>
"""


def test_parse_reports_a_skipped_join_in_its_output(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(_join_twb("&gt;="))
    out = tmp_path / "parsed.json"

    result = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(out)])

    assert result.exit_code == 0, result.stdout + result.stderr
    ds = json.loads(out.read_text())["datasources"][0]
    assert ds["joins"] == []
    assert len(ds["join_warnings"]) == 1
    assert "non-equi" in ds["join_warnings"][0]
    # Echoed, not just written to the JSON: a join count that silently excludes
    # the skipped ones is the shape that hid the datasource-skip losses.
    assert "WARNING" in result.stderr
    assert "non-equi" in result.stderr


def test_parse_emits_a_supported_join_with_no_warnings(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(_join_twb("="))
    out = tmp_path / "parsed.json"

    result = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(out)])

    assert result.exit_code == 0, result.stdout + result.stderr
    ds = json.loads(out.read_text())["datasources"][0]
    assert ds["join_warnings"] == []
    assert ds["joins"][0]["keys"] == [{"left": "OrderId", "right": "OrderId"}]
    assert "WARNING" not in result.stderr


def test_parse_survives_non_numeric_address(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(NON_NUMERIC_ADDRESS_TWB)
    out = tmp_path / "parsed.json"

    result = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(out)])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert out.exists(), "the shipped failure wrote no output file at all"
    assert "WARNING" in result.stderr
    assert "false" in result.stderr          # the offending token is named
    assert "Heat Map" in result.stderr       # and where it came from

    entry = json.loads(out.read_text())["table_calc_addressing"]
    assert entry["ws_overrides"]["Heat Map"]["[cost]"]["address_offset"] is None
    assert len(entry["warnings"]) == 1


def test_parse_creates_missing_output_parent_dir(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(TWB)
    out = tmp_path / "sub" / "deeper" / "parsed.json"
    assert not out.parent.exists()

    result = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(out)])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert out.exists()


def test_parse_missing_file_exits_nonzero(tmp_path):
    result = runner.invoke(
        app,
        ["tableau", "parse", str(tmp_path / "nope.twb"), "--output", str(tmp_path / "out.json")],
    )
    assert result.exit_code != 0


def test_parse_summary_line_written_to_stderr(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(TWB)
    out = tmp_path / "parsed.json"

    result = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(out)])

    assert result.exit_code == 0
    assert "Parsed 1 datasource(s)" in result.stderr
    assert result.stdout == ""


BLEND_TWB = """<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='Orders'>
    <relation name='ORDERS' type='table' table='[db].[s].[ORDERS]'/>
    <column name='[Cat]' datatype='string' caption='Cat'/>
  </datasource>
  <datasource name='federated.b' caption='Targets'>
    <relation name='TARGETS' type='table' table='[db].[s].[TARGETS]'/>
    <column name='[Cat]' datatype='string' caption='Cat'/>
  </datasource>
  <datasource-relationships>
    <datasource-dependencies datasource='federated.a'>
      <column-instance name='[ci_a]' column='[Cat]'/>
    </datasource-dependencies>
    <datasource-dependencies datasource='federated.b'>
      <column-instance name='[ci_b]' column='[Cat]'/>
    </datasource-dependencies>
    <datasource-relationship source='federated.a' target='federated.b'>
      <column-mapping><map key='[federated.a].[ci_a]' value='[federated.b].[ci_b]'/></column-mapping>
    </datasource-relationship>
  </datasource-relationships>
</workbook>
"""


def test_parse_includes_blend_plan(tmp_path):
    twb = tmp_path / "b.twb"; twb.write_text(BLEND_TWB)
    out = tmp_path / "parsed.json"
    result = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(out)])
    assert result.exit_code == 0, result.stdout + result.stderr
    plan = json.loads(out.read_text())["blend_plan"]
    assert plan["components"][0]["primary"] == "Orders"
    assert plan["joins"][0]["on"] == "[ORDERS::Cat] = [TARGETS::Cat]"


BLEND_ODD_CAPTION = """<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='{cap}'>
    <relation name='ORDERS' type='table' table='[db].[s].[ORDERS]'/>
    <column name='[Cat]' datatype='string' caption='Cat'/>
  </datasource>
  <datasource name='federated.b' caption='Targets'>
    <relation name='TARGETS' type='table' table='[db].[s].[TARGETS]'/>
    <column name='[Cat]' datatype='string' caption='Cat'/>
  </datasource>
  <datasource-relationships>
    <datasource-dependencies datasource='federated.a'>
      <column-instance name='[ci_a]' column='[Cat]'/>
    </datasource-dependencies>
    <datasource-dependencies datasource='federated.b'>
      <column-instance name='[ci_b]' column='[Cat]'/>
    </datasource-dependencies>
    <datasource-relationship source='federated.a' target='federated.b'>
      <column-mapping><map key='[federated.a].[ci_a]' value='[federated.b].[ci_b]'/></column-mapping>
    </datasource-relationship>
  </datasource-relationships>
</workbook>
"""


def test_blend_graph_uses_the_same_datasource_names_as_parse(tmp_path):
    """extract_blends kept its own copy of the naming rule, so an empty or
    padded caption keyed the graph on a name no datasource has — the edge was
    detected and then produced no join."""
    for cap, expected in [("", "federated.a"), ("Orders  ", "Orders")]:
        twb = tmp_path / "blend.twb"
        twb.write_text(BLEND_ODD_CAPTION.format(cap=cap))
        out = tmp_path / "parsed.json"

        result = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(out)])
        assert result.exit_code == 0, result.stdout + result.stderr

        data = json.loads(out.read_text())
        names = [d["name"] for d in data["datasources"]]
        assert expected in names
        assert list(data["blends"].keys()) == [expected]      # graph agrees with parse
        assert data["blend_plan"]["joins"], "blend detected but produced no join"


def test_classify_formulas_from_parsed_json(tmp_path):
    parsed = {
        "datasources": [{
            "name": "Orders",
            "calculated_fields": [
                {"caption": "Rev", "name": "Rev", "formula": "SUM([REVENUE])",
                 "role": "measure", "datatype": "real", "datasource": "Orders"}],
            "orphan_calcs": [],
        }],
        "parameters": [], "param_map": {},
    }
    pj = tmp_path / "parsed.json"; pj.write_text(json.dumps(parsed))
    out = tmp_path / "classification.json"
    result = runner.invoke(app, ["tableau", "classify-formulas", "--input", str(pj), "--output", str(out)])
    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(out.read_text())
    # Parsed-workbook input classifies per datasource (each is its own model).
    assert data["datasources"][0]["name"] == "Orders"
    assert data["datasources"][0]["formulas"][0]["tier"] == "native"
    assert data["tier_counts"]["native"] == 1


# ---------------------------------------------------------------------------
# Published-datasource files: .tds (root IS <datasource>) and .tdsx (zip).
# A published/sqlproxy datasource hides its physical tables + joins from the
# .twb; they live in the datasource's .tds. parse must accept it.
# ---------------------------------------------------------------------------

TDS = """<?xml version='1.0'?>
<datasource formatted-name='tentpole_prod' caption='Tentpole Prod'>
  <connection class='federated'>
    <relation join='inner' type='join'>
      <clause type='join'>
        <expression op='[PROMOTION_ID]'/>
        <expression op='[PROMOTION_ID (product)]'/>
      </clause>
      <relation name='promotion_master' type='table' table='[db].[s].[promotion_master]'/>
      <relation name='product_metrics' type='table' table='[db].[s].[product_metrics]'/>
    </relation>
  </connection>
  <column name='[CPG_SALES]' datatype='real' role='measure' caption='CPG Sales'/>
  <column name='[Calculation_1]' caption='Promo Sales' datatype='real'>
    <calculation class='tableau' formula='SUM([CPG_SALES])'/>
  </column>
</datasource>
"""


def _assert_tds_parsed(data):
    assert len(data["datasources"]) == 1, data["datasources"]
    ds = data["datasources"][0]
    assert ds["name"] == "Tentpole Prod"
    assert {t["name"] for t in ds["tables"]} == {"promotion_master", "product_metrics"}
    assert len(ds["joins"]) == 1
    assert "Promo Sales" in {c.get("caption", c.get("name")) for c in ds["calculated_fields"]}


def test_parse_tds_file(tmp_path):
    tds = tmp_path / "tentpole.tds"
    tds.write_text(TDS)
    out = tmp_path / "parsed.json"
    result = runner.invoke(app, ["tableau", "parse", str(tds), "--output", str(out)])
    assert result.exit_code == 0, result.stdout + result.stderr
    _assert_tds_parsed(json.loads(out.read_text()))


def test_parse_tdsx_file(tmp_path):
    import zipfile
    tdsx = tmp_path / "tentpole.tdsx"
    with zipfile.ZipFile(tdsx, "w") as z:
        z.writestr("tentpole.tds", TDS)
    out = tmp_path / "parsed.json"
    result = runner.invoke(app, ["tableau", "parse", str(tdsx), "--output", str(out)])
    assert result.exit_code == 0, result.stdout + result.stderr
    _assert_tds_parsed(json.loads(out.read_text()))


# SCAL-331323 — the fixture above carries BOTH `formatted-name` and `caption`,
# so it exercised a shape Tableau does not emit for a published datasource and
# the suite stayed green while every real .tds returned nothing. Real files
# carry `formatted-name` ALONE: the name lookup returned "", the empty-name
# guard in parse_twb discarded the datasource, and the command reported
# "Parsed 0 datasource(s)" with exit code 0.
TDS_NO_CAPTION = TDS.replace(
    "<datasource formatted-name='tentpole_prod' caption='Tentpole Prod'>",
    "<datasource formatted-name='tentpole_prod' inline='true' version='18.1'>",
)


def test_parse_tds_named_only_by_formatted_name(tmp_path):
    tds = tmp_path / "published.tds"
    tds.write_text(TDS_NO_CAPTION)
    out = tmp_path / "parsed.json"

    result = runner.invoke(app, ["tableau", "parse", str(tds), "--output", str(out)])

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(out.read_text())
    assert len(data["datasources"]) == 1, "the datasource was discarded for having no name"
    ds = data["datasources"][0]
    assert ds["name"] == "tentpole_prod"          # falls back to formatted-name
    assert {t["name"] for t in ds["tables"]} == {"promotion_master", "product_metrics"}
    assert len(ds["joins"]) == 1
    # every calc is labelled with the datasource it came from, not ""
    assert {c["datasource"] for c in ds["calculated_fields"]} == {"tentpole_prod"}


def test_parse_warns_when_a_datasource_is_discarded(tmp_path):
    """The silence is the bug's other half: a file whose datasource is thrown
    away must not report the same thing as a file that had none."""
    twb = tmp_path / "nameless.twb"
    twb.write_text("""<?xml version='1.0'?>
<workbook>
  <datasource>
    <relation name='ORDERS' type='table' table='[db].[s].[ORDERS]'/>
  </datasource>
</workbook>
""")
    out = tmp_path / "parsed.json"

    result = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(out)])

    assert result.exit_code == 0
    assert json.loads(out.read_text())["datasources"] == []
    assert "datasource skipped" in result.stderr
    assert "no usable name" in result.stderr


def test_parse_warns_when_a_named_datasource_has_nothing_migratable(tmp_path):
    """The name resolves, so the no-name guard never fires — this is the branch
    the first instrumentation missed. A .tds whose only relation is the
    [Extract] hyper cache is filtered by _is_extract_wrapper and leaves here."""
    tds = tmp_path / "extract_only.tds"
    tds.write_text("""<?xml version='1.0'?>
<datasource formatted-name='World Indicators' inline='true' version='18.1'>
  <connection class='federated'>
    <relation name='Extract' table='[Extract].[Extract]' type='table'/>
  </connection>
  <column caption='Population' datatype='real' name='[Population]' role='measure'/>
</datasource>
""")
    out = tmp_path / "parsed.json"

    result = runner.invoke(app, ["tableau", "parse", str(tds), "--output", str(out)])

    assert result.exit_code == 0
    assert json.loads(out.read_text())["datasources"] == []
    assert "no tables or SQL views" in result.stderr
    assert "World Indicators" in result.stderr     # names which one was lost


def test_skipped_datasources_are_individually_identifiable(tmp_path):
    """Two nameless datasources otherwise emit two identical warnings, which
    cannot be told apart or acted on — the same defect flagged for duplicate
    <column-instance> warnings in the previous PR."""
    twb = tmp_path / "two_nameless.twb"
    twb.write_text("""<?xml version='1.0'?>
<workbook>
  <datasource><relation name='ORDERS' type='table' table='[db].[s].[ORDERS]'/></datasource>
  <datasource><relation name='RETURNS' type='table' table='[db].[s].[RETURNS]'/></datasource>
</workbook>
""")
    out = tmp_path / "parsed.json"

    result = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(out)])

    assert result.exit_code == 0
    skipped = json.loads(out.read_text())["skipped_datasources"]
    assert len(skipped) == 2
    assert skipped[0]["detail"] != skipped[1]["detail"]
    assert "#1" in skipped[0]["detail"] and "#2" in skipped[1]["detail"]


def test_parse_does_not_report_duplicate_datasource_stubs(tmp_path):
    """Tableau writes one <datasource> stub per worksheet, so the duplicate
    branch fires far more often than datasources are kept. Reporting correct
    dedupe would bury the two skips that mean something."""
    twb = tmp_path / "dupes.twb"
    twb.write_text("""<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='Orders'>
    <relation name='ORDERS' type='table' table='[db].[s].[ORDERS]'/>
  </datasource>
  <datasource name='federated.a' caption='Orders'/>
  <datasource name='federated.a' caption='Orders'/>
</workbook>
""")
    out = tmp_path / "parsed.json"

    result = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(out)])

    assert result.exit_code == 0
    data = json.loads(out.read_text())
    assert len(data["datasources"]) == 1           # deduped, as intended
    assert data["skipped_datasources"] == []       # and reported as nothing
    assert "datasource skipped" not in result.stderr


def test_datasource_name_helper():
    import xml.etree.ElementTree as ET
    from ts_cli.tableau.twb import datasource_name
    # .twb shapes win in order; a .tds root has only formatted-name
    assert datasource_name(ET.fromstring("<datasource caption='C' name='N' formatted-name='F'/>")) == "C"
    assert datasource_name(ET.fromstring("<datasource name='N' formatted-name='F'/>")) == "N"
    assert datasource_name(ET.fromstring("<datasource formatted-name='F'/>")) == "F"
    assert datasource_name(ET.fromstring("<datasource/>")) == ""
    # an empty caption must fall through, not win — `.get(a, b)` would return ""
    assert datasource_name(ET.fromstring("<datasource caption='' formatted-name='F'/>")) == "F"
    # whitespace-only is absent too: truthy otherwise, it would shadow a real
    # name and reach the slug as "", giving a .model.tml with no filename stem
    assert datasource_name(ET.fromstring("<datasource caption='   ' name='federated.a'/>")) == "federated.a"
    assert datasource_name(ET.fromstring("<datasource caption=' ' name=' ' formatted-name=' '/>")) == ""
    assert datasource_name(ET.fromstring("<datasource caption='  Orders  '/>")) == "Orders"


def test_datasource_elements_helper():
    import xml.etree.ElementTree as ET
    from ts_cli.tableau.twb import datasource_elements
    wb = ET.fromstring("<workbook><datasource name='a'/><datasource name='b'/></workbook>")
    assert len(datasource_elements(wb)) == 2
    tds = ET.fromstring("<datasource name='a'/>")
    got = datasource_elements(tds)
    assert len(got) == 1 and got[0] is tds
