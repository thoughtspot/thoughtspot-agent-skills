"""Tests for the CSR manifest layer: resolve, apply, build, import."""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.commands.security_planning import expand_uniform_rules

# Bare module name, not `tests.test_security_commands`: pytest puts the tests directory
# itself on sys.path, and this matches `from fixtures import ...` in
# test_worked_examples.py.
from test_security_commands import FakeClient, FakeResponse  # noqa: E402

# See the Global Constraints section: `runner` is stream-separated so result.stdout is
# parseable JSON; `msg_runner` mixes, which is the only way to see a manual stderr print.
try:
    runner = CliRunner(mix_stderr=False)
except TypeError:            # Click >= 8.2 removed the parameter
    runner = CliRunner()
msg_runner = CliRunner()

FETCH = "/api/rest/2.0/security/column/rules/fetch"
UPDATE = "/api/rest/2.0/security/column/rules/update"


def test_uniform_crosses_tables_orgs_and_rules():
    rows = expand_uniform_rules(["T1", "T2"], ["ORG1", "ORG2"], {"COST": ["Finance"]})
    assert len(rows) == 4
    assert {"org_name": "ORG1", "table_name": "T1", "column_name": "COST",
            "group_name": "Finance"} in rows


def test_uniform_emits_one_blank_group_row_for_a_column_secured_for_nobody():
    rows = expand_uniform_rules(["T1"], ["ORG1"], {"SALARY": []})
    assert rows == [{"org_name": "ORG1", "table_name": "T1",
                     "column_name": "SALARY", "group_name": ""}]


def test_uniform_requires_an_org():
    with pytest.raises(ValueError, match="--org"):
        expand_uniform_rules(["T1"], [], {"COST": ["Finance"]})


def test_uniform_requires_a_table():
    with pytest.raises(ValueError, match="--table"):
        expand_uniform_rules([], ["ORG1"], {"COST": ["Finance"]})


def test_uniform_requires_a_rule():
    # The audience is never inferred. An empty rule set would plan a no-op that reads
    # as success.
    with pytest.raises(ValueError, match="--rule"):
        expand_uniform_rules(["T1"], ["ORG1"], {})


def test_resolve_init_table_prints_the_ddl_and_exits():
    result = runner.invoke(app, ["security", "column-rules", "resolve", "--init-table"])
    assert result.exit_code == 0
    assert "TS_COLUMN_SECURITY_RULES" in result.stdout
    assert "PRIMARY KEY" in result.stdout


def test_resolve_uniform_builds_one_step_per_org_table(monkeypatch):
    monkeypatch.setattr("ts_cli.commands.security_planning._client_for_org",
                        lambda profile, org=None: FakeClient({FETCH: FakeResponse([])}))
    monkeypatch.setattr("ts_cli.commands.security_planning.assert_org_context",
                        lambda *a, **k: None)
    monkeypatch.setattr("ts_cli.commands.security_planning._resolve_table",
                        lambda client, name: {"guid": f"guid-{name}", "name": name})
    monkeypatch.setattr("ts_cli.commands.security_planning._published_orgs",
                        lambda client, guid: [])

    result = runner.invoke(app, ["security", "column-rules", "resolve",
                                 "--source", "uniform", "--table", "T2",
                                 "--org", "ORG1", "--org", "ORG2",
                                 "--rule", "COST=Finance", "-p", "x"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert [s["org_name"] for s in plan["steps"]] == ["ORG1", "ORG2"]
    assert plan["steps"][0]["rules"] == {"COST": ["Finance"]}
    assert plan["steps"][0]["table_identifier"] == "guid-T2"
    assert plan["summary"]["blocked"] == 0


def _patch_published(monkeypatch, org_ids):
    monkeypatch.setattr("ts_cli.commands.security_planning._client_for_org",
                        lambda profile, org=None: FakeClient({FETCH: FakeResponse([])}))
    monkeypatch.setattr("ts_cli.commands.security_planning.assert_org_context",
                        lambda *a, **k: None)
    monkeypatch.setattr("ts_cli.commands.security_planning._resolve_table",
                        lambda client, name: {"guid": "guid-1", "name": name})
    monkeypatch.setattr("ts_cli.commands.security_planning._published_orgs",
                        lambda client, guid: org_ids)


_RESOLVE_ARGS = ["security", "column-rules", "resolve", "--source", "uniform",
                 "--table", "T2", "--org", "ORG1", "--rule", "COST=Finance", "-p", "x"]


def test_resolve_marks_a_published_table_blocked_in_the_plan(monkeypatch):
    _patch_published(monkeypatch, [0, 1])
    result = runner.invoke(app, _RESOLVE_ARGS)
    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert plan["steps"][0]["blocked"].startswith("CSR_BLOCKED")
    assert plan["summary"]["blocked"] == 1


def test_resolve_reports_the_block_on_stderr(monkeypatch):
    # Split from the test above: the warning is a manual stderr print.
    _patch_published(monkeypatch, [0, 1])
    result = msg_runner.invoke(app, _RESOLVE_ARGS)
    assert result.exit_code == 0
    assert "CSR_BLOCKED" in result.output


def test_resolve_prune_reads_current_state_and_lists_stale_columns(monkeypatch):
    fetched = [{"table_guid": "guid-1", "column_security_rules": [
        {"column": {"id": "c1", "name": "COST"}, "groups": []},
        {"column": {"id": "c2", "name": "SALARY"}, "groups": []}]}]
    monkeypatch.setattr("ts_cli.commands.security_planning._client_for_org",
                        lambda profile, org=None: FakeClient(
                            {FETCH: FakeResponse(fetched)}))
    monkeypatch.setattr("ts_cli.commands.security_planning.assert_org_context",
                        lambda *a, **k: None)
    monkeypatch.setattr("ts_cli.commands.security_planning._resolve_table",
                        lambda client, name: {"guid": "guid-1", "name": name})
    monkeypatch.setattr("ts_cli.commands.security_planning._published_orgs",
                        lambda client, guid: [])

    result = runner.invoke(app, ["security", "column-rules", "resolve",
                                 "--source", "uniform", "--table", "T2",
                                 "--org", "ORG1", "--rule", "COST=Finance",
                                 "--prune", "-p", "x"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["steps"][0]["unsecure"] == ["SALARY"]


def test_resolve_file_source_reads_the_csv(monkeypatch, tmp_path):
    csv_path = tmp_path / "rules.csv"
    csv_path.write_text("org_name,table_name,column_name,group_name\n"
                        "ORG1,T2,COST,Finance\n")
    monkeypatch.setattr("ts_cli.commands.security_planning._client_for_org",
                        lambda profile, org=None: FakeClient({FETCH: FakeResponse([])}))
    monkeypatch.setattr("ts_cli.commands.security_planning.assert_org_context",
                        lambda *a, **k: None)
    monkeypatch.setattr("ts_cli.commands.security_planning._resolve_table",
                        lambda client, name: {"guid": "guid-1", "name": name})
    monkeypatch.setattr("ts_cli.commands.security_planning._published_orgs",
                        lambda client, guid: [])

    result = runner.invoke(app, ["security", "column-rules", "resolve",
                                 "--source", "file", "--csv", str(csv_path), "-p", "x"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert plan["steps"][0]["rules"] == {"COST": ["Finance"]}


def test_resolve_file_source_requires_csv(monkeypatch):
    result = msg_runner.invoke(app, ["security", "column-rules", "resolve",
                                     "--source", "file", "-p", "x"])
    assert result.exit_code != 0
    assert "--csv" in result.output
