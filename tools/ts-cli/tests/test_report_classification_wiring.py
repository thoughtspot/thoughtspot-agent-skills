# tools/ts-cli/tests/test_report_classification_wiring.py
"""Integration tests: build_report actually calls classify_dependent per dependent.

Before this fix, walker.row_to_entry hardcoded every dependent's risk to a LOW
placeholder and classify_dependent (despite being fully implemented) was never
invoked — found while porting api_work/column_impact.py's 13-pass impact
analysis into ts_cli/report (see
agents/cli/ts-convert-from-dbt/references/open-items.md #8). These tests prove
the wiring end to end with a mocked ThoughtSpotClient — no live connection.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from ts_cli.report import build_report


def _resp(body):
    r = MagicMock()
    r.json.return_value = body
    return r


def _column_hit(name="franchiseID", owner="t-1"):
    """A column GUID lookup. The header's `owner` names the owning table or Model."""
    header = {"id": "col-1", "name": name, "type": ""}
    if owner:
        header["owner"] = owner
    return _resp([{"metadata_id": "col-1", "metadata_name": name,
                   "metadata_type": "LOGICAL_COLUMN", "metadata_header": header}])


def _object_hit(guid="t-1", name="TBL", subtype="ONE_TO_ONE_LOGICAL"):
    """A LOGICAL_TABLE lookup; header `type` is the subtype (table vs WORKSHEET Model)."""
    return _resp([{"metadata_id": guid, "metadata_name": name, "metadata_type": "LOGICAL_TABLE",
                   "metadata_header": {"id": guid, "name": name, "type": subtype}}])


def _no_dependents(guid="col-1"):
    return _resp([{"metadata_id": guid, "dependent_objects": {"dependents": {}}}])


def _table_doc(guid="t-1", tml="table:\n  name: TBL\n"):
    return {"info": {"type": "table", "id": guid, "name": "TBL"}, "edoc": tml}


def _coverage(out, row_type):
    return next(c for c in out["coverage"] if c["type"] == row_type)


def _exported_identifiers(client):
    for call in client.post.call_args_list:
        if call.args and call.args[0] == "/api/rest/2.0/metadata/tml/export":
            return call.kwargs["json"]["metadata"]
    return None


_GUID = "baa451a6-02a0-42d1-8347-8cd4af13b505"

_MODEL_TML_WITH_JOIN = """
model:
  name: Customer 360
  model_tables:
    - name: Source Table
      joins_with:
        - name: J1
          "on": "[Source Table::franchiseID] = [Other::franchiseID]"
"""

_TABLE_TML_WITH_RLS = """
table:
  name: TBL
  rls_rules:
    table_paths:
      - id: p1
        table: TBL
        column: [franchiseID]
    rules:
      - name: Region rule
        expr: "[p1::franchiseID] = ts_groups"
"""


@patch("ts_cli.report.ThoughtSpotClient")
def test_join_referencing_dependent_gets_high_risk_not_placeholder(MockClient):
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _column_hit(), _object_hit(),
        _resp([{
            "metadata_id": "col-1",
            "dependent_objects": {"dependents": {"col-1": {
                "LOGICAL_TABLE": [{"id": "ws-1", "name": "Customer 360"}],
            }}},
        }]),
        _resp([_table_doc(),  # primary TML export: the owning table + the dependent Model
               {"info": {"type": "model", "id": "ws-1", "name": "Customer 360"},
                "edoc": _MODEL_TML_WITH_JOIN}]),
        _resp([]),  # formula/template variables for ws-1
        _resp([]), _resp({}),  # business terms + AI memory for ws-1
        _resp([]),  # CSR fetch
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report(_GUID, profile="test", with_deep=True, max_depth=1)

    dep = next(d for d in out["dependents"] if d["guid"] == "ws-1")
    assert dep["risk"]["tag"] == "HIGH"
    assert "join" in dep["risk"]["reason"]
    # The export carries the dependent Model: export_associated never returns
    # what is built ON an object, only what it is built from.
    assert {"identifier": "ws-1", "type": "LOGICAL_TABLE"} in _exported_identifiers(client)


@patch("ts_cli.report.ThoughtSpotClient")
def test_feedback_type_dependent_gets_medium_not_placeholder(MockClient):
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _column_hit(name="X"), _object_hit(),
        _resp([{
            "metadata_id": "col-1",
            "dependent_objects": {"dependents": {"col-1": {
                "FEEDBACK": [{"id": "fb-1", "name": "some feedback"}],
            }}},
        }]),
        _resp([_table_doc()]),  # primary TML export
        _resp([]),  # CSR fetch
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report(_GUID, profile="test", with_deep=True, max_depth=1)

    dep = next(d for d in out["dependents"] if d["guid"] == "fb-1")
    assert dep["risk"]["tag"] == "MEDIUM"


@patch("ts_cli.report.ThoughtSpotClient")
def test_no_dependents_and_both_security_checks_ran_is_safe(MockClient):
    """SAFE requires the RLS and CSR checks to have actually run on the owning table."""
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _column_hit(name="X"), _object_hit(), _no_dependents(),
        _resp([_table_doc()]),  # primary TML export — table with no rls_rules
        _resp([{"table_guid": "t-1", "column_security_rules": []}]),  # CSR fetch
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report(_GUID, profile="test", with_deep=True, max_depth=1)

    assert out["classification"]["aggregate"]["tag"] == "SAFE"
    assert _coverage(out, "RLS rules")["checked"] is True
    assert _coverage(out, "Column security rules (CSR)")["checked"] is True


@patch("ts_cli.report.ThoughtSpotClient")
def test_column_export_asks_for_the_owning_table_never_the_column(MockClient):
    """metadata/tml/export rejects LOGICAL_COLUMN with HTTP 400 (live-verified
    2026-10-02), which aborted every column report. It must export the table."""
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _column_hit(), _object_hit(), _no_dependents(),
        _resp([_table_doc(tml=_TABLE_TML_WITH_RLS)]),
        _resp([]),  # CSR fetch
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report(_GUID, profile="test", with_deep=True, max_depth=1)

    assert _exported_identifiers(client) == [{"identifier": "t-1", "type": "LOGICAL_TABLE"}]
    assert _coverage(out, "RLS rules")["found"] == 1
    assert out["classification"]["aggregate"]["tag"] == "STOP"


@patch("ts_cli.report.ThoughtSpotClient")
def test_rls_on_another_base_table_is_not_counted(MockClient):
    """A dependent Model's associated docs bring its other base tables; a
    same-named column there is a different column and must not trigger STOP."""
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _column_hit(), _object_hit(),
        _resp([{
            "metadata_id": "col-1",
            "dependent_objects": {"dependents": {"col-1": {
                "LOGICAL_TABLE": [{"id": "ws-1", "name": "Customer 360"}],
            }}},
        }]),
        _resp([_table_doc(),
               {"info": {"type": "model", "id": "ws-1", "name": "Customer 360"},
                "edoc": "model:\n  name: Customer 360\n"},
               _table_doc(guid="t-other", tml=_TABLE_TML_WITH_RLS)]),
        _resp([]),  # formula/template variables for ws-1
        _resp([]), _resp({}),  # business terms + AI memory for ws-1
        _resp([]),  # CSR fetch
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report(_GUID, profile="test", with_deep=True, max_depth=1)

    assert _coverage(out, "RLS rules")["found"] == 0
    assert out["classification"]["aggregate"]["tag"] != "STOP"


@patch("ts_cli.report.ThoughtSpotClient")
def test_csr_hits_trigger_stop_recommendation(MockClient):
    """Column security rules on the source's owning table feed the STOP condition."""
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _object_hit(name="DB.SCH.TBL"),  # resolve table name -> guid (exact-name match)
        _resp([{  # _fetch_table_columns
            "metadata_detail": {"columns": [{"header": {"id": "col-1", "name": "franchiseID"}}]},
        }]),
        _no_dependents(),
        _resp([_table_doc()]),  # primary TML export
        _resp([{  # CSR fetch
            "table_guid": "t-1",
            "column_security_rules": [
                {"column": {"name": "franchiseID", "id": "col-1"}, "groups": [{"name": "Sales"}]},
            ],
        }]),
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report("DB.SCH.TBL.franchiseID", profile="test", with_deep=True, max_depth=1)

    assert out["classification"]["aggregate"]["tag"] == "STOP"
    assert out["classification"]["recommendation"] == "BLOCKED_RESOLVE_RLS_FIRST"
    csr_row = _coverage(out, "Column security rules (CSR)")
    assert csr_row["checked"] is True
    assert csr_row["found"] == 1


@patch("ts_cli.report.ThoughtSpotClient")
def test_column_with_unresolved_owner_is_unverified_not_safe(MockClient):
    """No owner means no table to check: both rows unchecked, verdict UNVERIFIED,
    and no request is made that could not answer the question."""
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _column_hit(owner=None), _no_dependents(),
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report(_GUID, profile="test", with_deep=True, max_depth=1)

    assert _coverage(out, "RLS rules")["checked"] is False
    assert _coverage(out, "Column security rules (CSR)")["checked"] is False
    assert out["classification"]["aggregate"]["tag"] == "UNVERIFIED"
    assert out["classification"]["recommendation"] == "BLOCKED_VERIFY_SECURITY_FIRST"
    assert _exported_identifiers(client) is None
    assert not any("security/column/rules/fetch" in str(c) for c in client.post.call_args_list)


@patch("ts_cli.report.ThoughtSpotClient")
def test_model_column_is_unverified(MockClient):
    """A Model's column: RLS and CSR live on its base tables, so neither can be
    checked from the Model — never SAFE."""
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _column_hit(owner="m-1"), _object_hit(guid="m-1", name="Sales Model", subtype="WORKSHEET"),
        _no_dependents(),
        _resp([]),  # primary TML export (of the Model) — no docs
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report(_GUID, profile="test", with_deep=True, max_depth=1)

    assert out["classification"]["aggregate"]["tag"] == "UNVERIFIED"
    assert "base tables" in out["classification"]["aggregate"]["reason"]
    assert _coverage(out, "Column security rules (CSR)")["checked"] is False
    assert _exported_identifiers(client) == [{"identifier": "m-1", "type": "LOGICAL_TABLE"}]


@patch("ts_cli.report.ThoughtSpotClient")
def test_whole_table_source_counts_every_rule(MockClient):
    """Removing a table removes every RLS and CSR rule on it, so all of them count."""
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _object_hit(),  # resolve the table GUID
        _no_dependents(guid="t-1"),
        _resp([_table_doc(tml=_TABLE_TML_WITH_RLS)]),
        _resp([{"table_guid": "t-1", "column_security_rules": [
            {"column": {"name": "a", "id": "c-a"}, "groups": [{"name": "G1"}]},
            {"column": {"name": "b", "id": "c-b"}, "groups": [{"name": "G2"}]},
        ]}]),
    ]

    out = build_report(_GUID, profile="test", with_deep=True, max_depth=1)

    assert _coverage(out, "RLS rules") == {"type": "RLS rules", "checked": True, "found": 1}
    assert _coverage(out, "Column security rules (CSR)")["found"] == 2
    assert out["classification"]["aggregate"]["tag"] == "STOP"


@patch("ts_cli.report.ThoughtSpotClient")
def test_model_source_is_unverified(MockClient):
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _object_hit(guid="m-1", name="Sales Model", subtype="WORKSHEET"),
        _no_dependents(guid="m-1"),
        _resp([]),  # primary TML export
    ]

    out = build_report(_GUID, profile="test", with_deep=True, max_depth=1)

    assert out["classification"]["aggregate"]["tag"] == "UNVERIFIED"
    assert _coverage(out, "RLS rules")["checked"] is False


@patch("ts_cli.report.ThoughtSpotClient")
def test_csr_http_failure_is_unchecked_not_a_crash(MockClient):
    """The real client ends a non-2xx with SystemExit(1); the CSR probe must
    report its row unchecked rather than abort the report."""
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _column_hit(), _object_hit(), _no_dependents(),
        _resp([_table_doc()]),
        SystemExit(1),  # CSR fetch: HTTP error
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report(_GUID, profile="test", with_deep=True, max_depth=1)

    assert _coverage(out, "Column security rules (CSR)")["checked"] is False
    assert out["classification"]["aggregate"]["tag"] == "UNVERIFIED"
    assert any("Column security rules (CSR) probe failed" in w for w in out["warnings"])
