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


_MODEL_TML_WITH_JOIN = """
model:
  name: Customer 360
  model_tables:
    - name: Source Table
      joins_with:
        - name: J1
          "on": "[Source Table::franchiseID] = [Other::franchiseID]"
"""


@patch("ts_cli.report.ThoughtSpotClient")
def test_join_referencing_dependent_gets_high_risk_not_placeholder(MockClient):
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _resp([{
            "metadata_id": "col-1", "metadata_name": "franchiseID",
            "metadata_type": "LOGICAL_COLUMN",
            "metadata_header": {"id": "col-1", "name": "franchiseID"},
        }]),
        _resp([{
            "metadata_id": "col-1",
            "dependent_objects": {"dependents": {"col-1": {
                "LOGICAL_TABLE": [{"id": "ws-1", "name": "Customer 360"}],
            }}},
        }]),
        _resp([{"info": {"type": "model", "id": "ws-1", "name": "Customer 360"},
                 "edoc": _MODEL_TML_WITH_JOIN}]),
        _resp([]),  # formula/template variables for ws-1
        _resp([]), _resp({}),  # business terms + AI memory for ws-1
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report("baa451a6-02a0-42d1-8347-8cd4af13b505", profile="test",
                        with_deep=True, max_depth=1)

    dep = next(d for d in out["dependents"] if d["guid"] == "ws-1")
    assert dep["risk"]["tag"] == "HIGH"
    assert "join" in dep["risk"]["reason"]


@patch("ts_cli.report.ThoughtSpotClient")
def test_feedback_type_dependent_gets_medium_not_placeholder(MockClient):
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _resp([{
            "metadata_id": "col-1", "metadata_name": "X",
            "metadata_type": "LOGICAL_COLUMN",
            "metadata_header": {"id": "col-1", "name": "X"},
        }]),
        _resp([{
            "metadata_id": "col-1",
            "dependent_objects": {"dependents": {"col-1": {
                "FEEDBACK": [{"id": "fb-1", "name": "some feedback"}],
            }}},
        }]),
        _resp([]),  # primary TML export — no docs
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report("baa451a6-02a0-42d1-8347-8cd4af13b505", profile="test",
                        with_deep=True, max_depth=1)

    dep = next(d for d in out["dependents"] if d["guid"] == "fb-1")
    assert dep["risk"]["tag"] == "MEDIUM"


@patch("ts_cli.report.ThoughtSpotClient")
def test_no_dependents_gets_safe_not_low_placeholder(MockClient):
    """No dependents at all -> aggregate SAFE (pre-existing behavior, still holds)."""
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _resp([{
            "metadata_id": "col-1", "metadata_name": "X",
            "metadata_type": "LOGICAL_COLUMN",
            "metadata_header": {"id": "col-1", "name": "X"},
        }]),
        _resp([{"metadata_id": "col-1", "dependent_objects": {"dependents": {}}}]),
        _resp([]),  # primary TML export — no docs
        _resp([]),  # SQL-views search
        _resp([]),  # custom actions search
    ]

    out = build_report("baa451a6-02a0-42d1-8347-8cd4af13b505", profile="test",
                        with_deep=True, max_depth=1)

    assert out["classification"]["aggregate"]["tag"] == "SAFE"


@patch("ts_cli.report.ThoughtSpotClient")
def test_csr_hits_trigger_stop_recommendation(MockClient):
    """Column security rules on the source's owning table now feed the real
    STOP condition (previously dead — csr_hits was always []).
    """
    client = MagicMock()
    MockClient.return_value = client

    # Four-part-name resolution populates source.parent (LOGICAL_TABLE), which
    # the CSR probe needs.
    client.post.side_effect = [
        _resp([{  # resolve table name -> guid (3-part fallback matches the exact input string)
            "metadata_id": "t-1", "metadata_name": "DB.SCH.TBL",
            "metadata_type": "LOGICAL_TABLE", "metadata_header": {"id": "t-1", "name": "DB.SCH.TBL"},
        }]),
        _resp([{  # _fetch_table_columns
            "metadata_detail": {"columns": [{"header": {"id": "col-1", "name": "franchiseID"}}]},
        }]),
        _resp([{"metadata_id": "col-1", "dependent_objects": {"dependents": {}}}]),
        _resp([]),  # primary TML export — no docs
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
    csr_row = next(c for c in out["coverage"] if c["type"] == "Column security rules (CSR)")
    assert csr_row["checked"] is True
    assert csr_row["found"] == 1
