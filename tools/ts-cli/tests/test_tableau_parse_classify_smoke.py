# tools/ts-cli/tests/test_tableau_parse_classify_smoke.py
"""End-to-end smoke test: `ts tableau parse` -> `ts tableau classify-formulas`.

Exercises the real Typer commands (not the underlying pure functions) so a
wiring regression between the two CLI commands is caught even if the unit
tests for each command's internals still pass in isolation.
"""
from __future__ import annotations
import json
from typer.testing import CliRunner
from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:  # Click >= 8.2 removed mix_stderr (stderr is separated by default)
    runner = CliRunner()

SMOKE_TWB = """<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='Orders'>
    <relation name='ORDERS' type='table' table='[db].[s].[ORDERS]'/>
    <column name='[Amount]' datatype='real' role='measure' caption='Amount'/>
    <column name='[Calculation_1]' caption='Total Amount' datatype='real'>
      <calculation class='tableau' formula='SUM([Amount])'/>
    </column>
    <column name='[Calculation_2]' caption='Geo' datatype='string'>
      <calculation class='tableau' formula='MAKEPOINT([Amount],[Amount])'/>
    </column>
  </datasource>
</workbook>
"""


def test_parse_then_classify_pipeline(tmp_path):
    twb = tmp_path / "smoke.twb"
    twb.write_text(SMOKE_TWB)
    parsed = tmp_path / "parsed.json"
    r1 = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(parsed)])
    assert r1.exit_code == 0, r1.stdout + r1.stderr

    cls = tmp_path / "classification.json"
    r2 = runner.invoke(
        app, ["tableau", "classify-formulas", "--input", str(parsed), "--output", str(cls)]
    )
    assert r2.exit_code == 0, r2.stdout + r2.stderr

    # classify-formulas emits per-datasource results for a parsed-workbook input.
    data = json.loads(cls.read_text())
    tiers = {f["name"]: f["tier"]
             for ds in data["datasources"] for f in ds["formulas"]}
    assert tiers["Total Amount"] == "native"
    assert tiers["Geo"] == "geospatial"
