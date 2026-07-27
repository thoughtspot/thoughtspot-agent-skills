"""CliRunner tests for `ts security column-rules`. No live instance."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest
from typer.testing import CliRunner

from ansi import plain
from ts_cli.cli import app
from ts_cli.commands.security import _published_orgs

# `runner` for stdout-JSON assertions; `msg_runner` for anything a manual
# print(file=sys.stderr) emits, which the separated runner silently drops. See the
# Global Constraints section of the plan, and test_cli_alias.py / test_tml_commands.py
# for the same tradeoff documented elsewhere in this suite.
try:
    runner = CliRunner(mix_stderr=False)
except TypeError:            # Click >= 8.2 removed the parameter
    runner = CliRunner()
msg_runner = CliRunner()


class FakeResponse:
    def __init__(self, payload: Any = None, status_code: int = 200, text: str = ""):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text or json.dumps(payload or {})

    def json(self) -> Any:
        return self._payload


class FakeClient:
    """Records every POST so a test can assert on the payload that would have gone out."""

    def __init__(self, responses: Optional[Dict[str, Any]] = None):
        self.responses = responses or {}
        self.calls = []

    def post(self, path: str, json: Any = None, **kwargs: Any) -> FakeResponse:
        self.calls.append((path, json))
        result = self.responses.get(path, FakeResponse({}))
        return result(json) if callable(result) else result

    def get(self, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((path, None))
        result = self.responses.get(path, FakeResponse({}))
        return result(None) if callable(result) else result


FETCH = "/api/rest/2.0/security/column/rules/fetch"
UPDATE = "/api/rest/2.0/security/column/rules/update"

_FETCH_BODY = [{
    "table_guid": "tg-1", "obj_id": "oid",
    "column_security_rules": [
        {"column": {"id": "c1", "name": "SALARY"},
         "groups": [{"id": "g1", "name": "HR"}],
         "source_table_details": {"id": "st", "name": "EMP"}}]}]


@pytest.fixture
def patched(monkeypatch):
    """Patch the org-scoped client factory the whole command group goes through."""
    holder = {}

    def _install(client):
        holder["client"] = client
        monkeypatch.setattr("ts_cli.commands.security._client_for_org",
                            lambda profile, org=None: client)
        monkeypatch.setattr("ts_cli.commands.security.assert_org_context",
                            lambda *a, **k: None)
        return client

    return _install


SEARCH = "/api/rest/2.0/metadata/search"
ORGS = "/api/rest/2.0/orgs/search"


def _search_client(payload, status=200):
    return FakeClient({SEARCH: FakeResponse(payload, status)})


def _header_hits(org_ids, owner_org_id):
    return [{"metadata_id": "g1", "metadata_header": {"orgIds": org_ids,
                                                      "ownerOrgId": owner_org_id}}]


def _resolvable_hit(guid="tg-1", name="T2", org_ids=(0,), owner_org_id=0):
    """One `metadata/search` hit that resolves AND carries a publication header.

    `set`'s publication guard resolves the table via `_resolve_object` (untyped
    attempt, which matches on the first non-empty hit regardless of `type`) and then
    reads publication state off the SAME hit's `metadata_header` via `_published_orgs`
    -- both calls land on `SEARCH`, so one FakeResponse configured this way serves
    both. `org_ids=(0,)` (the owning Org only) is "not published anywhere"; add a
    tenant Org id to simulate a published table.
    """
    return [{"metadata_id": guid, "metadata_name": name, "metadata_type": "LOGICAL_TABLE",
             "metadata_header": {"id": guid, "name": name, "orgIds": list(org_ids),
                                 "ownerOrgId": owner_org_id}}]


def test_published_orgs_reads_an_unpublished_header_as_published_nowhere():
    # The documented shape of an UNPUBLISHED object on an Orgs-enabled cluster: orgIds
    # carries the OWNING Org. Reading that as "published into" made every table on such
    # a cluster CSR_BLOCKED, which refused every plan and made the feature unusable on
    # its own target cluster. Same header as test_publish.py's
    # test_publication_rows_excludes_owner_org_from_published_to.
    assert _published_orgs(_search_client(_header_hits([0], 0)), "g1") == []


def test_published_orgs_reads_one_additional_org():
    assert _published_orgs(_search_client(_header_hits([0, 1], 0)), "g1") == [1]


def test_published_orgs_reads_several_additional_orgs():
    hits = _header_hits([0, 12750490, 535312919], 0)
    assert _published_orgs(_search_client(hits), "g1") == [12750490, 535312919]


def test_published_orgs_excludes_a_non_primary_owner():
    # The owner is not always Org 0, so the exclusion has to be of `ownerOrgId` and not
    # of the Primary Org's id.
    assert _published_orgs(_search_client(_header_hits([5, 7], 5)), "g1") == [7]


def test_published_orgs_reads_the_metadata_envelope_form_too():
    hits = {"metadata": _header_hits([0, 1], 0)}
    assert _published_orgs(_search_client(hits), "g1") == [1]


def test_published_orgs_tolerates_a_header_with_no_org_ids():
    hits = [{"metadata_id": "g1", "metadata_header": {}}]
    assert _published_orgs(_search_client(hits), "g1") == []


def test_published_orgs_returns_none_when_the_read_fails():
    # None, not []: a failed read cannot support the claim that a table is unpublished.
    # Returning [] here made a 403 (plausible where the CSR flag is off) or a 500 read as
    # "not published", so the gate degraded to nothing.
    assert _published_orgs(_search_client(None, 403), "g1") is None


def test_published_orgs_returns_none_when_nothing_matched_the_guid():
    assert _published_orgs(_search_client([]), "g1") is None


def test_published_orgs_warns_on_stderr_when_it_could_not_determine_the_state(capsys):
    _published_orgs(_search_client(None, 500), "g1")
    assert "could not read publication state" in capsys.readouterr().err


def test_get_prints_normalised_rows_as_json(patched):
    patched(FakeClient({FETCH: FakeResponse(_FETCH_BODY)}))
    result = runner.invoke(app, ["security", "column-rules", "get", "T2", "-p", "x"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert rows == [{"org": "", "table_guid": "tg-1", "obj_id": "oid",
                     "column_id": "c1", "column_name": "SALARY",
                     "group_names": ["HR"], "source_table_name": "EMP"}]


def test_get_sends_all_tables_in_one_fetch_call(patched):
    client = patched(FakeClient({FETCH: FakeResponse([])}))
    runner.invoke(app, ["security", "column-rules", "get", "T1", "T2", "-p", "x"])
    body = next(b for p, b in client.calls if p == FETCH)
    assert body == {"tables": [{"identifier": "T1"}, {"identifier": "T2"}]}


def test_get_tags_each_row_with_the_org_it_came_from(patched):
    patched(FakeClient({FETCH: FakeResponse(_FETCH_BODY)}))
    result = runner.invoke(app, ["security", "column-rules", "get", "T2",
                                 "--org", "ORG1", "-p", "x"])
    assert json.loads(result.stdout)[0]["org"] == "ORG1"


def test_get_explains_the_feature_flag_instead_of_a_bare_403(patched):
    body = '{"error":{"code":10023,"message":"Column Security rule feature is disabled"}}'
    patched(FakeClient({FETCH: FakeResponse(None, 403, body)}))
    # msg_runner: the explanation is a manual stderr print, which the separated runner
    # drops.
    result = msg_runner.invoke(app, ["security", "column-rules", "get", "T2", "-p", "x"])
    assert result.exit_code == 1
    assert "feature-flagged" in result.output
    assert "10.12" in result.output


def test_the_group_is_registered_under_ts_security():
    result = runner.invoke(app, ["security", "column-rules", "--help"])
    assert result.exit_code == 0
    for command in ("get", "set", "clear", "export"):
        assert command in result.output


def test_set_defaults_to_replace(patched):
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204),
                                 SEARCH: FakeResponse(_resolvable_hit())}))
    result = runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                 "--rule", "PROD_NM=Analyst,Finance", "-p", "x"])
    assert result.exit_code == 0, result.output
    body = next(b for p, b in client.calls if p == UPDATE)
    assert body == {
        "identifier": "T2", "clear_csr": False,
        "column_security_rules": [
            {"column_identifier": "PROD_NM", "is_unsecured": False,
             "group_access": [{"operation": "REPLACE",
                               "group_identifiers": ["Analyst", "Finance"]}]}]}


def test_set_add_and_remove_change_the_operation(patched):
    for flag, operation in (("--add", "ADD"), ("--remove", "REMOVE")):
        client = patched(FakeClient({UPDATE: FakeResponse(None, 204),
                                     SEARCH: FakeResponse(_resolvable_hit())}))
        runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                            "--rule", "COST=Finance", flag, "-p", "x"])
        body = next(b for p, b in client.calls if p == UPDATE)
        assert body["column_security_rules"][0]["group_access"][0]["operation"] \
            == operation


def test_set_refuses_add_and_remove_together(patched):
    patched(FakeClient())
    result = msg_runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                     "--rule", "COST=Finance", "--add", "--remove",
                                     "-p", "x"])
    assert result.exit_code != 0
    assert "--add" in plain(result)


@pytest.mark.parametrize("flag", ["--add", "--remove"])
def test_set_refuses_an_empty_group_list_under_add_or_remove(patched, flag):
    # "COL=" means "secured, nobody", which only REPLACE can express. ADDING or REMOVING
    # an empty group list changes nothing, so the call would return success having done
    # nothing -- and read as "secured" to whoever ran it.
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = msg_runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                     "--rule", "SALARY=", flag, "-p", "x"])
    assert result.exit_code != 0
    assert "SALARY" in result.output
    assert client.calls == []


def test_set_still_allows_an_empty_group_list_under_the_default_replace(patched):
    # The refusal above must not swallow the form's one legitimate use.
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204),
                                 SEARCH: FakeResponse(_resolvable_hit())}))
    result = runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                 "--rule", "SALARY=", "-p", "x"])
    assert result.exit_code == 0, result.output
    body = next(b for p, b in client.calls if p == UPDATE)
    assert body["column_security_rules"][0]["group_access"][0] == {
        "operation": "REPLACE", "group_identifiers": []}


def test_set_add_still_works_when_every_named_column_has_groups(patched):
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204),
                                 SEARCH: FakeResponse(_resolvable_hit())}))
    result = runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                 "--rule", "COST=Finance", "--add", "-p", "x"])
    assert result.exit_code == 0, result.output
    assert [p for p, _ in client.calls if p == UPDATE]


def test_set_dry_run_prints_the_payload_and_posts_nothing(patched):
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                 "--rule", "COST=Finance", "--dry-run", "-p", "x"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["identifier"] == "T2"
    # --dry-run never constructs a client at all, so no call of any kind should be
    # recorded -- not just an absence of the UPDATE path specifically.
    assert client.calls == []


def test_set_rejects_a_malformed_rule_flag(patched):
    patched(FakeClient())
    result = msg_runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                     "--rule", "PROD_NM", "-p", "x"])
    assert result.exit_code != 0
    assert "COL=GROUP" in result.output


# ---------------------------------------------------------------------------
# `set` refuses a published table -- the fix for the live finding that CSR set on a
# published table is a scoping trap: the platform accepts and enforces the write in
# the owning Org, but the rule never reaches any tenant Org the table is published to.
# ---------------------------------------------------------------------------

def test_set_refuses_a_published_table_and_posts_nothing(patched):
    client = patched(FakeClient({
        UPDATE: FakeResponse(None, 204),
        SEARCH: FakeResponse(_resolvable_hit(name="T2_PUBLISH", org_ids=(0, 12750490))),
        ORGS: FakeResponse([{"id": 12750490, "name": "ORG1"}])}))
    result = msg_runner.invoke(app, ["security", "column-rules", "set", "--table",
                                     "T2_PUBLISH", "--rule", "UNIT_PRICE_AMT=Analyst",
                                     "-p", "x"])
    assert result.exit_code != 0
    # Names the actual reason (scoped to this Org, tenant keeps the column visible),
    # not a bare "cannot" -- and names the Org it is published to when known.
    assert "scoping trap" in result.output
    assert "ORG1" in result.output
    assert not [p for p, _ in client.calls if p == UPDATE]


def test_set_allow_published_proceeds(patched):
    client = patched(FakeClient({
        UPDATE: FakeResponse(None, 204),
        SEARCH: FakeResponse(_resolvable_hit(name="T2_PUBLISH", org_ids=(0, 12750490))),
        ORGS: FakeResponse([{"id": 12750490, "name": "ORG1"}])}))
    result = runner.invoke(app, ["security", "column-rules", "set", "--table",
                                 "T2_PUBLISH", "--rule", "UNIT_PRICE_AMT=Analyst",
                                 "--allow-published", "-p", "x"])
    assert result.exit_code == 0, result.output
    assert [p for p, _ in client.calls if p == UPDATE]


def test_set_allow_published_warns_on_stderr(patched):
    patched(FakeClient({
        UPDATE: FakeResponse(None, 204),
        SEARCH: FakeResponse(_resolvable_hit(name="T2_PUBLISH", org_ids=(0, 12750490))),
        ORGS: FakeResponse([{"id": 12750490, "name": "ORG1"}])}))
    result = msg_runner.invoke(app, ["security", "column-rules", "set", "--table",
                                     "T2_PUBLISH", "--rule", "UNIT_PRICE_AMT=Analyst",
                                     "--allow-published", "-p", "x"])
    assert result.exit_code == 0
    assert "--allow-published set" in plain(result)


def test_set_on_an_unpublished_table_is_unaffected(patched):
    client = patched(FakeClient({
        UPDATE: FakeResponse(None, 204),
        SEARCH: FakeResponse(_resolvable_hit(name="T2", org_ids=(0,)))}))
    result = runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                 "--rule", "COST=Finance", "-p", "x"])
    assert result.exit_code == 0, result.output
    assert [p for p, _ in client.calls if p == UPDATE]


def test_clear_is_not_blocked_on_a_published_table(patched):
    # Deliberate asymmetry with `set`: `clear` removes protection the operator asked
    # to remove, which creates no false belief, so it is never guarded against
    # publication -- and it never even reads publication state to decide.
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = runner.invoke(app, ["security", "column-rules", "clear", "--table",
                                 "T2_PUBLISH", "-p", "x"])
    assert result.exit_code == 0, result.output
    assert [p for p, _ in client.calls if p == UPDATE]
    assert not [p for p, _ in client.calls if p == SEARCH]


def test_clear_is_not_blocked_on_a_published_table_with_a_column(patched):
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = runner.invoke(app, ["security", "column-rules", "clear", "--table",
                                 "T2_PUBLISH", "--column", "UNIT_PRICE_AMT", "-p", "x"])
    assert result.exit_code == 0, result.output
    assert [p for p, _ in client.calls if p == UPDATE]


def test_clear_sends_clear_csr_with_the_required_empty_array(patched):
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = runner.invoke(app, ["security", "column-rules", "clear", "--table", "T2",
                                 "-p", "x"])
    assert result.exit_code == 0, result.output
    body = next(b for p, b in client.calls if p == UPDATE)
    assert body == {"identifier": "T2", "clear_csr": True,
                    "column_security_rules": []}


def test_clear_one_column_unsecures_just_that_column(patched):
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    runner.invoke(app, ["security", "column-rules", "clear", "--table", "T2",
                        "--column", "COST", "-p", "x"])
    body = next(b for p, b in client.calls if p == UPDATE)
    assert body == {"identifier": "T2", "clear_csr": False,
                    "column_security_rules": [
                        {"column_identifier": "COST", "is_unsecured": True}]}


def test_clear_rejects_an_explicitly_empty_column(patched):
    # --column "" (e.g. an unset shell variable spliced into `--column "$COL"`) must NOT
    # silently fall through to the whole-table clear branch -- that would strip every
    # column's security on a routine scripting mistake, which is the one failure
    # direction this feature must never take silently. An explicit empty string is
    # distinct from an omitted flag (column is None) and must be refused.
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = msg_runner.invoke(app, ["security", "column-rules", "clear", "--table", "T2",
                                     "--column", "", "-p", "x"])
    assert result.exit_code != 0
    assert not [p for p, _ in client.calls if p == UPDATE]


def test_set_asserts_the_org_context_before_writing(monkeypatch, patched):
    # The assertion and the POST are recorded into the SAME ordered list (the fake
    # client's own `.calls`) so the test can prove the assertion ran BEFORE the write,
    # not merely that it ran. An implementation that posted first and asserted
    # afterwards -- exactly the bug this assertion exists to prevent -- would still
    # pass a test that only checked "did assert_org_context get called at all".
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204),
                                 SEARCH: FakeResponse(_resolvable_hit())}))
    monkeypatch.setattr(
        "ts_cli.commands.security.assert_org_context",
        lambda c, org, profile=None: client.calls.append(("assert_org_context", org)))
    runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                        "--rule", "COST=Finance", "--org", "ORG1", "-p", "x"])
    kinds = [p for p, _ in client.calls]
    assert "assert_org_context" in kinds and UPDATE in kinds
    assert kinds.index("assert_org_context") < kinds.index(UPDATE)


EXPORT = "/api/rest/2.0/metadata/tml/export"

_CSR_EDOC = ("column_security_rules:\n"
             "  table:\n    name: T2\n"
             "  rules:\n"
             "  - column_name: PROD_NM\n"
             "    accessible_groups:\n      group_name:\n      - Analyst\n")


def test_export_asks_for_both_flags_the_beta_option_needs(patched):
    client = patched(FakeClient({EXPORT: FakeResponse([])}))
    runner.invoke(app, ["security", "column-rules", "export", "T2", "-p", "x"])
    body = next(b for p, b in client.calls if p == EXPORT)
    assert body["export_associated"] is True
    assert body["export_options"] == {"export_column_security_rules": True}
    assert body["metadata"] == [{"identifier": "T2", "type": "LOGICAL_TABLE"}]


def test_export_prints_the_parsed_documents(patched):
    patched(FakeClient({EXPORT: FakeResponse(
        [{"info": {"type": "column_security_rules", "id": "g-9"}, "edoc": _CSR_EDOC}])}))
    result = runner.invoke(app, ["security", "column-rules", "export", "T2", "-p", "x"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["documents"][0]["table_name"] == "T2"
    assert payload["documents"][0]["rules"] == {"PROD_NM": ["Analyst"]}


def test_export_writes_files_named_the_way_the_platform_names_them(patched, tmp_path):
    patched(FakeClient({EXPORT: FakeResponse(
        [{"info": {"type": "column_security_rules", "id": "g-9"}, "edoc": _CSR_EDOC}])}))
    result = runner.invoke(app, ["security", "column-rules", "export", "T2",
                                 "--out", str(tmp_path), "-p", "x"])
    assert result.exit_code == 0, result.output
    written = tmp_path / "T2_CSR.column_security_rules.tml"
    assert written.exists()
    assert "column_security_rules" in written.read_text()


_NO_CSR = [{"info": {"type": "logical_table"}, "edoc": "table:\n  name: T2\n"}]


def test_export_returns_an_empty_document_list_when_nothing_is_secured(patched):
    patched(FakeClient({EXPORT: FakeResponse(_NO_CSR)}))
    result = runner.invoke(app, ["security", "column-rules", "export", "T2", "-p", "x"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["documents"] == []


def test_export_says_on_stderr_that_it_found_nothing(patched):
    # Split from the test above: the message is a manual stderr print, so it needs the
    # mixing runner, which in turn makes result.stdout unparseable.
    patched(FakeClient({EXPORT: FakeResponse(_NO_CSR)}))
    result = msg_runner.invoke(app, ["security", "column-rules", "export", "T2",
                                     "-p", "x"])
    assert result.exit_code == 0
    assert "no column security rules" in result.output.lower()
