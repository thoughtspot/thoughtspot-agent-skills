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


def test_resolve_without_prune_does_not_fetch_current_state(monkeypatch):
    # Discriminates from an implementation that always fetches `/rules/fetch` and
    # computes `unsecure` unconditionally -- exactly the prune-by-default behaviour
    # the design forbids, since of the two failure directions only "silently unsecures
    # columns" leaks. A single FakeClient is captured in a closure (rather than a
    # fresh one per `_client_for_org` call) so its `calls` list survives the command.
    client = FakeClient({FETCH: FakeResponse([])})
    monkeypatch.setattr("ts_cli.commands.security_planning._client_for_org",
                        lambda profile, org=None: client)
    monkeypatch.setattr("ts_cli.commands.security_planning.assert_org_context",
                        lambda *a, **k: None)
    monkeypatch.setattr("ts_cli.commands.security_planning._resolve_table",
                        lambda client, name: {"guid": "guid-1", "name": name})
    monkeypatch.setattr("ts_cli.commands.security_planning._published_orgs",
                        lambda client, guid: [])

    result = runner.invoke(app, ["security", "column-rules", "resolve",
                                 "--source", "uniform", "--table", "T2",
                                 "--org", "ORG1", "--rule", "COST=Finance", "-p", "x"])
    assert result.exit_code == 0, result.output
    assert all(call[0] != FETCH for call in client.calls)


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


def test_resolve_db_source_requires_sf_profile(monkeypatch):
    # --table-name defaults to TS_COLUMN_SECURITY_RULES, so --sf-profile is the only
    # flag that can actually be missing here; the error must name only that one.
    result = msg_runner.invoke(app, ["security", "column-rules", "resolve",
                                     "--source", "db", "-p", "x"])
    assert result.exit_code != 0
    assert "--sf-profile" in result.output


def _plan(**overrides):
    step = {"org_name": "ORG1", "table_identifier": "guid-1", "table_name": "T2",
            "operation": "REPLACE", "rules": {"COST": ["Finance"]},
            "unsecure": [], "blocked": ""}
    step.update(overrides)
    return {"rows": [], "tables": [], "steps": [step],
            "summary": {"blocked": 1 if step["blocked"] else 0}}


def _write_plan(tmp_path, plan):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    return str(path)


@pytest.fixture
def planning_client(monkeypatch):
    def _install(client):
        monkeypatch.setattr("ts_cli.commands.security_planning._client_for_org",
                            lambda profile, org=None: client)
        monkeypatch.setattr("ts_cli.commands.security_planning.assert_org_context",
                            lambda *a, **k: None)
        return client
    return _install


def test_apply_posts_one_update_per_step(tmp_path, planning_client):
    client = planning_client(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = runner.invoke(app, ["security", "column-rules", "apply", "--input",
                                 _write_plan(tmp_path, _plan()), "-p", "x"])
    assert result.exit_code == 0, result.output
    posted = [b for p, b in client.calls if p == UPDATE]
    assert posted == [{"identifier": "guid-1", "clear_csr": False,
                       "column_security_rules": [
                           {"column_identifier": "COST", "is_unsecured": False,
                            "group_access": [{"operation": "REPLACE",
                                              "group_identifiers": ["Finance"]}]}]}]


def test_apply_dry_run_posts_nothing(tmp_path, planning_client):
    client = planning_client(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = runner.invoke(app, ["security", "column-rules", "apply", "--input",
                                 _write_plan(tmp_path, _plan()), "--dry-run", "-p", "x"])
    assert result.exit_code == 0
    # Not just "no UPDATE call": no call of any kind. FakeClient records every POST and
    # GET, so this also catches a --dry-run that still constructs a client and probes
    # the session (e.g. an Org-context check) before honouring the flag.
    assert client.calls == []
    assert json.loads(result.stdout)["payloads"][0]["identifier"] == "guid-1"


def test_apply_refuses_a_blocked_step(tmp_path, planning_client):
    client = planning_client(FakeClient({UPDATE: FakeResponse(None, 204)}))
    plan = _plan(blocked="CSR_BLOCKED: 'T2' is published")
    result = msg_runner.invoke(app, ["security", "column-rules", "apply", "--input",
                                     _write_plan(tmp_path, plan), "-p", "x"])
    assert result.exit_code == 1
    assert "CSR_BLOCKED" in result.output
    assert not [p for p, _ in client.calls if p == UPDATE]


def test_allow_published_overrides_the_refusal(tmp_path, planning_client):
    # msg_runner, not runner: the warning that the platform is expected to reject these
    # steps anyway is printed to stderr, and only msg_runner's mixed output can see it.
    # With `runner` this assertion would be silently unreachable, so deleting the
    # warning print would not fail any test.
    client = planning_client(FakeClient({UPDATE: FakeResponse(None, 204)}))
    plan = _plan(blocked="CSR_BLOCKED: 'T2' is published")
    result = msg_runner.invoke(app, ["security", "column-rules", "apply", "--input",
                                     _write_plan(tmp_path, plan), "--allow-published",
                                     "-p", "x"])
    assert result.exit_code == 0, result.output
    assert [p for p, _ in client.calls if p == UPDATE]
    assert "platform is expected to reject" in result.output


def test_apply_sends_prune_unsecures_alongside_the_rules(tmp_path, planning_client):
    client = planning_client(FakeClient({UPDATE: FakeResponse(None, 204)}))
    plan = _plan(unsecure=["SALARY"])
    runner.invoke(app, ["security", "column-rules", "apply", "--input",
                        _write_plan(tmp_path, plan), "-p", "x"])
    body = next(b for p, b in client.calls if p == UPDATE)
    assert {"column_identifier": "SALARY", "is_unsecured": True} \
        in body["column_security_rules"]


def test_apply_explains_the_feature_flag(tmp_path, planning_client):
    body = '{"error":{"code":10023,"message":"Column Security rule feature is disabled"}}'
    planning_client(FakeClient({UPDATE: FakeResponse(None, 403, body)}))
    result = msg_runner.invoke(app, ["security", "column-rules", "apply", "--input",
                                     _write_plan(tmp_path, _plan()), "-p", "x"])
    assert result.exit_code == 1
    assert "feature-flagged" in result.output


def test_apply_refuses_a_plan_with_no_steps(tmp_path, planning_client):
    planning_client(FakeClient())
    plan = {"rows": [], "tables": [], "steps": [], "summary": {}}
    result = msg_runner.invoke(app, ["security", "column-rules", "apply", "--input",
                                     _write_plan(tmp_path, plan), "-p", "x"])
    assert result.exit_code != 0
    assert "no steps" in result.output.lower()


def test_apply_refuses_a_step_with_no_org_name(tmp_path, planning_client):
    # No legitimate plan reaches this state -- parse_rule_rows already refuses a blank
    # org_name at resolve time -- but a plan file is something a human can hand-edit in
    # between resolve and apply, and a silent write to the profile's default Org is
    # exactly the failure mode that Org-context assertion exists to prevent.
    client = planning_client(FakeClient({UPDATE: FakeResponse(None, 204)}))
    plan = _plan(org_name="")
    result = msg_runner.invoke(app, ["security", "column-rules", "apply", "--input",
                                     _write_plan(tmp_path, plan), "-p", "x"])
    assert result.exit_code != 0
    assert "org_name" in result.output
    assert not [p for p, _ in client.calls if p == UPDATE]


def test_apply_surfaces_an_empty_step_as_a_usage_error(tmp_path, planning_client):
    # rules={} and unsecure=[] together make build_update_payload's own "nothing to do"
    # ValueError fire. It must surface as a named usage error, not an unhandled
    # traceback, and it must name the offending Org/table so the operator can find the
    # broken row in the plan file.
    client = planning_client(FakeClient({UPDATE: FakeResponse(None, 204)}))
    plan = _plan(rules={}, unsecure=[])
    result = msg_runner.invoke(app, ["security", "column-rules", "apply", "--input",
                                     _write_plan(tmp_path, plan), "-p", "x"])
    assert result.exit_code != 0
    assert "ORG1" in result.output and "T2" in result.output
    assert "nothing to do" in result.output.lower()
    assert not [p for p, _ in client.calls if p == UPDATE]
