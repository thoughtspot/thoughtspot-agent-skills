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

from typer.testing import CliRunner

from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:  # Click >= 8.2 removed mix_stderr (stderr is separated by default)
    runner = CliRunner()

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
    assert data["table_calc_addressing"] == {"column_level": {}, "ws_overrides": {}}
    # No blends in this fixture — blend_plan is the all-empty shape.
    assert data["blend_plan"] == {"components": [], "ds_table_map": {}, "joins": []}


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
