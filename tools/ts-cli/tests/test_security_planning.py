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


SEARCH = "/api/rest/2.0/metadata/search"


def _patch_resolution(monkeypatch, client):
    """Wire resolve's I/O EXCEPT `_published_orgs`, so the real header parsing runs.

    The five tests above patch `_published_orgs` wholesale, which is precisely why a
    defect in its reading of `metadata_header.orgIds` was invisible to them: it read
    `orgIds` as "published into" when the field also carries the OWNING Org, so on an
    Orgs-enabled cluster every table resolved as published and every plan was refused.
    These tests feed the real header shapes through instead.
    """
    monkeypatch.setattr("ts_cli.commands.security_planning._client_for_org",
                        lambda profile, org=None: client)
    monkeypatch.setattr("ts_cli.commands.security_planning.assert_org_context",
                        lambda *a, **k: None)
    monkeypatch.setattr("ts_cli.commands.security_planning._resolve_table",
                        lambda client, name: {"guid": "guid-1", "name": name})
    return client


def _search_response(org_ids, owner_org_id, status=200):
    return FakeResponse([{"metadata_id": "guid-1",
                          "metadata_header": {"orgIds": org_ids,
                                              "ownerOrgId": owner_org_id}}], status)


def test_resolve_reads_an_unpublished_header_as_not_published(monkeypatch):
    # The documented unpublished header: orgIds carries the owning Org and nothing else.
    _patch_resolution(monkeypatch, FakeClient({FETCH: FakeResponse([]),
                                               SEARCH: _search_response([0], 0)}))
    result = runner.invoke(app, _RESOLVE_ARGS)
    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert plan["tables"][0]["published"] is False
    assert plan["steps"][0]["blocked"] == ""
    assert plan["summary"]["blocked"] == 0


def test_resolve_reads_a_header_published_to_one_other_org_as_published(monkeypatch):
    _patch_resolution(monkeypatch, FakeClient({FETCH: FakeResponse([]),
                                               SEARCH: _search_response([0, 1], 0)}))
    result = runner.invoke(app, _RESOLVE_ARGS)
    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert plan["tables"][0]["published"] is True
    assert plan["steps"][0]["blocked"].startswith("CSR_BLOCKED")


def test_resolve_reads_a_header_published_to_several_orgs_as_published(monkeypatch):
    _patch_resolution(monkeypatch, FakeClient({FETCH: FakeResponse([]),
                                               SEARCH: _search_response([0, 1, 2], 0)}))
    result = runner.invoke(app, _RESOLVE_ARGS)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["tables"][0]["published"] is True


def test_resolve_blocks_a_table_whose_publication_state_could_not_be_read(monkeypatch):
    # Failing closed: `resolve` writes nothing, so a false block costs a re-run while a
    # false pass applies CSR to a published object. A 403 here is plausible on exactly
    # the clusters where CSR itself is flagged off.
    _patch_resolution(monkeypatch, FakeClient({FETCH: FakeResponse([]),
                                               SEARCH: FakeResponse(None, 403)}))
    result = runner.invoke(app, _RESOLVE_ARGS)
    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert plan["tables"][0]["publication_known"] is False
    assert "could not be determined" in plan["steps"][0]["blocked"]
    assert plan["summary"]["blocked"] == 1


def test_resolve_warns_on_stderr_when_publication_state_is_undetermined(monkeypatch):
    # Split per the two-runner rule: the warning is a manual stderr print.
    _patch_resolution(monkeypatch, FakeClient({FETCH: FakeResponse([]),
                                               SEARCH: FakeResponse(None, 500)}))
    result = msg_runner.invoke(app, _RESOLVE_ARGS)
    assert result.exit_code == 0
    assert "could not read publication state" in result.output


def test_resolve_prune_ignores_secured_columns_belonging_to_another_table(monkeypatch):
    # `_fetch_rules` flattens every top-level entry in the response. An entry for a
    # DIFFERENT table must not contribute its columns to this table's unsecure list --
    # that is the protection-removing direction.
    fetched = [
        {"table_guid": "guid-1", "column_security_rules": [
            {"column": {"id": "c1", "name": "COST"}, "groups": []},
            {"column": {"id": "c2", "name": "SALARY"}, "groups": []}]},
        {"table_guid": "guid-OTHER", "column_security_rules": [
            {"column": {"id": "c9", "name": "SOMEONE_ELSES_COLUMN"}, "groups": []}]},
    ]
    _patch_resolution(monkeypatch, FakeClient({FETCH: FakeResponse(fetched),
                                               SEARCH: _search_response([0], 0)}))
    result = runner.invoke(app, _RESOLVE_ARGS + ["--prune"])
    assert result.exit_code == 0, result.output
    step = json.loads(result.stdout)["steps"][0]
    # SALARY belongs to this table and is genuinely stale, so pruning must still find it:
    # an implementation that filtered everything out would pass a bare "not in" assertion.
    assert step["unsecure"] == ["SALARY"]


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


def test_apply_surfaces_a_step_with_no_table_identifier_as_a_usage_error(
        tmp_path, planning_client):
    # A missing key must not traceback, and must NOT be quietly substituted with
    # table_name: one is a resolved GUID, the other an ambiguous name.
    client = planning_client(FakeClient({UPDATE: FakeResponse(None, 204)}))
    step = _plan()["steps"][0]
    del step["table_identifier"]
    plan = {"rows": [], "tables": [], "steps": [step], "summary": {"blocked": 0}}
    result = msg_runner.invoke(app, ["security", "column-rules", "apply", "--input",
                                     _write_plan(tmp_path, plan), "-p", "x"])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "ORG1" in result.output and "T2" in result.output
    assert client.calls == []


IMPORT = "/api/rest/2.0/metadata/tml/import"


def test_build_renders_one_document_per_step(tmp_path, planning_client):
    # A client is wired in (though `build` should never reach it) so that if `build`
    # ever regresses into contacting the platform, `client.calls == []` below fails
    # loudly instead of silently passing against an unconfigured FakeClient.
    client = planning_client(FakeClient())
    result = runner.invoke(app, ["security", "column-rules", "build", "--input",
                                 _write_plan(tmp_path, _plan())])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["documents"][0]["table_name"] == "T2"
    assert "column_security_rules" in payload["documents"][0]["yaml"]
    # The table reference is what an import fails on with code 14502 when absent.
    assert "name: T2" in payload["documents"][0]["yaml"]
    # Emit-only: no network call of any kind, not just no call to one endpoint.
    assert client.calls == []


def test_build_writes_platform_named_files_under_a_per_org_directory(tmp_path,
                                                                     planning_client):
    client = planning_client(FakeClient())
    out = tmp_path / "out"
    result = runner.invoke(app, ["security", "column-rules", "build", "--input",
                                 _write_plan(tmp_path, _plan()), "--out", str(out)])
    assert result.exit_code == 0, result.output
    # The Org is a directory, so the FILENAME stays exactly what the platform exports --
    # which is what `export` writes too, and what `import --file` is pointed at.
    assert (out / "ORG1" / "T2_CSR.column_security_rules.tml").exists()
    assert json.loads(result.stdout)["written"] == [
        str(out / "ORG1" / "T2_CSR.column_security_rules.tml")]
    assert client.calls == []


def _two_org_plan():
    """One table, two Orgs, DIFFERENT rules -- what --source file/db exist to express."""
    common = {"table_identifier": "guid-1", "table_name": "T2", "operation": "REPLACE",
              "unsecure": [], "blocked": ""}
    return {"rows": [], "tables": [], "summary": {"blocked": 0}, "steps": [
        dict(common, org_name="ORG1", rules={"COST": ["Finance_ORG1"]}),
        dict(common, org_name="ORG2", rules={"COST": ["Finance_ORG2"]}),
    ]}


def test_build_writes_one_file_per_org_for_the_same_table(tmp_path, planning_client):
    # A plan step is per (Org, table) but the platform's filename comes from the table
    # alone, so a flat layout wrote ONE file containing only the second Org's rules and
    # reported the same path twice in `written`. Importing that file into ORG1 would give
    # ORG1 the other tenant's column security.
    planning_client(FakeClient())
    out = tmp_path / "out"
    result = runner.invoke(app, ["security", "column-rules", "build", "--input",
                                 _write_plan(tmp_path, _two_org_plan()),
                                 "--out", str(out)])
    assert result.exit_code == 0, result.output
    org1 = out / "ORG1" / "T2_CSR.column_security_rules.tml"
    org2 = out / "ORG2" / "T2_CSR.column_security_rules.tml"
    assert json.loads(result.stdout)["written"] == [str(org1), str(org2)]
    assert "Finance_ORG1" in org1.read_text() and "Finance_ORG2" not in org1.read_text()
    assert "Finance_ORG2" in org2.read_text() and "Finance_ORG1" not in org2.read_text()


def test_build_refuses_two_steps_that_would_write_the_same_file(tmp_path,
                                                                planning_client):
    # Refuse rather than overwrite: the same path appearing twice in `written` must be
    # impossible, however the plan was edited.
    planning_client(FakeClient())
    plan = _two_org_plan()
    plan["steps"][1]["org_name"] = "ORG1"
    out = tmp_path / "out"
    result = msg_runner.invoke(app, ["security", "column-rules", "build", "--input",
                                     _write_plan(tmp_path, plan), "--out", str(out)])
    assert result.exit_code != 0
    # Whitespace-normalised: the usage error is rendered in a wrapped box, so the phrase
    # is split across lines in the raw output.
    assert "Two plan steps would both write" in " ".join(result.output.split())
    # Nothing at all was written: the paths are all resolved before the first write, so a
    # collision cannot leave a half-written directory behind.
    assert not out.exists()


def test_build_refuses_an_org_name_that_would_escape_the_out_directory(tmp_path,
                                                                       planning_client):
    planning_client(FakeClient())
    plan = _plan(org_name="../elsewhere")
    out = tmp_path / "out"
    result = msg_runner.invoke(app, ["security", "column-rules", "build", "--input",
                                     _write_plan(tmp_path, plan), "--out", str(out)])
    assert result.exit_code != 0
    assert not out.exists()
    assert not (tmp_path / "elsewhere").exists()


def test_build_refuses_a_step_with_no_org_name(tmp_path, planning_client):
    # Task 9 made this apply-only, when `build` used org_name as a warning label. It is
    # now the output directory that keeps two Orgs' documents for one table apart, so a
    # blank one collapses them onto the same path.
    planning_client(FakeClient())
    out = tmp_path / "out"
    result = msg_runner.invoke(app, ["security", "column-rules", "build", "--input",
                                     _write_plan(tmp_path, _plan(org_name="")),
                                     "--out", str(out)])
    assert result.exit_code != 0
    assert "org_name" in result.output
    assert not out.exists()


def test_build_surfaces_a_step_with_no_table_name_as_a_usage_error(tmp_path,
                                                                   planning_client):
    # A hand-edited plan is a usage error naming the step, not a KeyError traceback --
    # the same standard `apply` already held itself to.
    planning_client(FakeClient())
    step = _plan()["steps"][0]
    del step["table_name"]
    plan = {"rows": [], "tables": [], "steps": [step], "summary": {"blocked": 0}}
    out = tmp_path / "out"
    result = msg_runner.invoke(app, ["security", "column-rules", "build", "--input",
                                     _write_plan(tmp_path, plan), "--out", str(out)])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "ORG1" in result.output
    assert not out.exists()


def test_build_refuses_a_blocked_step(tmp_path, planning_client):
    client = planning_client(FakeClient())
    plan = _plan(blocked="CSR_BLOCKED: 'T2' is published")
    result = msg_runner.invoke(app, ["security", "column-rules", "build", "--input",
                                     _write_plan(tmp_path, plan)])
    assert result.exit_code == 1
    assert "CSR_BLOCKED" in result.output
    assert client.calls == []


def test_build_still_emits_the_document_but_omits_pruned_columns(tmp_path,
                                                                  planning_client):
    # The one real capability gap between the two routes: `is_unsecured` has no TML
    # equivalent, so a step's `unsecure` entries cannot appear in the document. The
    # document must still be produced for the columns the plan does secure.
    planning_client(FakeClient())
    plan = _plan(unsecure=["SALARY"])
    result = runner.invoke(app, ["security", "column-rules", "build", "--input",
                                 _write_plan(tmp_path, plan)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    yaml_text = payload["documents"][0]["yaml"]
    assert "COST" in yaml_text
    assert "SALARY" not in yaml_text


def test_build_warns_on_stderr_when_pruning_cannot_be_expressed(tmp_path,
                                                                 planning_client):
    # Split from the test above per the two-runner rule: the warning is a manual
    # stderr print, so only msg_runner's mixed output can see it. The warning names
    # the org/table and the count -- not the column names themselves.
    planning_client(FakeClient())
    plan = _plan(unsecure=["SALARY"])
    result = msg_runner.invoke(app, ["security", "column-rules", "build", "--input",
                                     _write_plan(tmp_path, plan)])
    assert result.exit_code == 0, result.output
    assert "ORG1/T2" in result.output
    assert "cannot express" in result.output
    assert "apply" in result.output


def test_import_sends_the_document_with_create_new_false(tmp_path, planning_client):
    client = planning_client(FakeClient({IMPORT: FakeResponse([{"response": {}}])}))
    doc = tmp_path / "T2_CSR.column_security_rules.tml"
    doc.write_text("column_security_rules:\n  table:\n    name: T2\n  rules: []\n")
    result = runner.invoke(app, ["security", "column-rules", "import", "--file",
                                 str(doc), "-p", "x"])
    assert result.exit_code == 0, result.output
    body = next(b for p, b in client.calls if p == IMPORT)
    assert body["create_new"] is False
    assert body["metadata_tmls"] == [doc.read_text()]


def test_import_dry_run_posts_nothing(tmp_path, planning_client):
    client = planning_client(FakeClient({IMPORT: FakeResponse([{"response": {}}])}))
    doc = tmp_path / "T2_CSR.column_security_rules.tml"
    doc.write_text("column_security_rules:\n  table:\n    name: T2\n  rules: []\n")
    result = runner.invoke(app, ["security", "column-rules", "import", "--file",
                                 str(doc), "--dry-run", "-p", "x"])
    assert result.exit_code == 0
    # Not just "no IMPORT call": no call of any kind, the same standard applied to
    # `apply --dry-run` above.
    assert client.calls == []


def test_import_refuses_a_document_with_no_table_reference(tmp_path, planning_client):
    # Catching it here turns code 14502's opaque "table with name  not found" into
    # something that names the actual problem before the round trip.
    client = planning_client(FakeClient({IMPORT: FakeResponse([{"response": {}}])}))
    doc = tmp_path / "bad.column_security_rules.tml"
    doc.write_text("column_security_rules:\n  rules: []\n")
    result = msg_runner.invoke(app, ["security", "column-rules", "import", "--file",
                                     str(doc), "-p", "x"])
    assert result.exit_code != 0
    assert "table:" in result.output
    # The refusal fires before the round trip: no call of any kind, matching the
    # standard already applied to the dry-run and build tests.
    assert client.calls == []


def test_import_explains_the_feature_flag(tmp_path, planning_client):
    body = '{"error":{"code":10023,"message":"Column Security rule feature is disabled"}}'
    planning_client(FakeClient({IMPORT: FakeResponse(None, 403, body)}))
    doc = tmp_path / "T2_CSR.column_security_rules.tml"
    doc.write_text("column_security_rules:\n  table:\n    name: T2\n  rules: []\n")
    result = msg_runner.invoke(app, ["security", "column-rules", "import", "--file",
                                     str(doc), "-p", "x"])
    assert result.exit_code == 1
    assert "feature-flagged" in result.output


def test_import_fails_when_the_platform_reports_success_but_buries_a_failure(
        tmp_path, planning_client):
    # Live-observed 2026-07-27: HTTP 200 from `metadata/tml/import`, with the failure
    # buried in the body. Before this fix, `import_cmd` only checked `resp.ok`, so this
    # exact response printed its body and exited 0 -- importing nothing while reporting
    # success.
    payload = [{"response": {"status": {
        "error_message": "Referenced table with name T2_PUBLISH not found.",
        "status_code": "ERROR", "error_code": 14502}}, "request_index": 0}]
    client = planning_client(FakeClient({IMPORT: FakeResponse(payload, 200)}))
    doc = tmp_path / "T2_PUBLISH_CSR.column_security_rules.tml"
    doc.write_text("column_security_rules:\n  table:\n    name: T2_PUBLISH\n  "
                    "rules: []\n")
    result = msg_runner.invoke(app, ["security", "column-rules", "import", "--file",
                                     str(doc), "-p", "x"])
    assert result.exit_code != 0
    # The message is routed through explain_csr_error, not the raw JSON blob.
    assert "T2_PUBLISH" in result.output
    assert "portable" in result.output
    # The call really was made -- this is a body-level failure, not a refused call.
    assert any(p == IMPORT for p, _ in client.calls)


def test_import_succeeds_when_every_item_reports_ok(tmp_path, planning_client):
    payload = [{"response": {"status": {"status_code": "OK"},
                             "object": [{"header": {"id_guid": "g-1"}}]},
               "request_index": 0}]
    planning_client(FakeClient({IMPORT: FakeResponse(payload, 200)}))
    doc = tmp_path / "T2_CSR.column_security_rules.tml"
    doc.write_text("column_security_rules:\n  table:\n    name: T2\n  rules: []\n")
    result = runner.invoke(app, ["security", "column-rules", "import", "--file",
                                 str(doc), "-p", "x"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == payload
