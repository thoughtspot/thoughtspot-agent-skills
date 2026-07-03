"""Integration test for the matched_columns wiring in ts_cli.report.build_report
(2026-07 audit fix for the dependency-manager column-scope filter bug).

Before this fix, ts-dependency-manager's Step 4 "Filtering by scope" table
instructed matching dependents by whether `risk.reason` referenced the column
name — but every reason string produced by classifier.classify_dependent is a
fixed literal (e.g. "referenced in a join condition") that never names a
column, so the filter could never match anything.

This test drives build_report end to end with a mocked ThoughtSpotClient and
confirms that dependents which the deep TML probes (join, AI-surface, Monitor
alert) actually matched against the target column get a populated
`matched_columns` field, while an unrelated dependent does not — following the
same mocked-client pattern as test_report_probe_failures.py / test_report_entry.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from ts_cli.report import build_report


def _resp(body):
    r = MagicMock()
    r.json.return_value = body
    return r


_TABLE_TML_WITH_RLS = """
table:
  name: Source Table
  rls_rules:
    table_paths:
      - id: T_1
        table: Source Table
        column: [ZIPCODE]
    rules:
      - name: geo_rule
        expr: "[T_1::ZIPCODE] = ts_groups_int"
"""

_MODEL_TML_WITH_JOIN_AND_DMI = """
model:
  name: Customer 360
  model_tables:
    - name: Source Table
      joins_with:
        - name: J1
          on: "[Source Table::ZIPCODE] = [Other::ZIPCODE]"
  model_instructions:
    data_model_instructions: "Always filter using [ZIPCODE] before aggregating"
"""

_MONITOR_ALERT_TML = """
monitor_alert:
  - guid: alert-1
    name: ZIPCODE Alert
    metric_id:
      pinboard_viz_id:
        viz_id: viz-1
    personalised_view_info:
      filters:
        - column: ["Customer 360::ZIPCODE"]
"""


@patch("ts_cli.report.ThoughtSpotClient")
def test_matched_columns_attributed_to_the_right_dependents(MockClient):
    client = MagicMock()
    MockClient.return_value = client

    # Call 1: resolve_source — GUID resolves to a LOGICAL_COLUMN.
    # Call 2: walk_dependents_recursive (max_depth=1) — one hop, three dependents:
    #   ws-1 (Model, referenced by the join+DMI hit), lb-1 (Liveboard, referenced
    #   by the Monitor-alert hit), ans-1 (Answer, referenced by nothing).
    # Call 3: primary TML probe export — table doc (RLS) + model doc (join, AI-surface).
    # Call 4: Monitor-alerts export for the one Liveboard dependent.
    client.post.side_effect = [
        _resp([{
            "metadata_id": "col-1", "metadata_name": "ZIPCODE",
            "metadata_type": "LOGICAL_COLUMN",
            "metadata_header": {"id": "col-1", "name": "ZIPCODE"},
        }]),
        _resp([{
            "metadata_id": "col-1",
            "dependent_objects": {
                "dependents": {
                    "col-1": {
                        "LOGICAL_TABLE": [
                            {"id": "ws-1", "name": "Customer 360",
                             "author": "u1", "authorDisplayName": "Alice"},
                        ],
                        "PINBOARD_ANSWER_BOOK": [
                            {"id": "lb-1", "name": "Regional Dashboard",
                             "author": "u2", "authorDisplayName": "Bob"},
                        ],
                        "QUESTION_ANSWER_BOOK": [
                            {"id": "ans-1", "name": "Unrelated Answer",
                             "author": "u3", "authorDisplayName": "Carol"},
                        ],
                    },
                },
            },
        }]),
        _resp([
            {"info": {"type": "table", "id": "src-tbl-1", "name": "Source Table"},
             "edoc": _TABLE_TML_WITH_RLS},
            {"info": {"type": "model", "id": "ws-1", "name": "Customer 360"},
             "edoc": _MODEL_TML_WITH_JOIN_AND_DMI},
        ]),
        _resp([
            {"info": {"type": "liveboard", "id": "lb-1", "name": "Regional Dashboard"},
             "edoc": _MONITOR_ALERT_TML},
        ]),
    ]

    out = build_report("baa451a6-02a0-42d1-8347-8cd4af13b505", profile="test",
                        with_deep=True, max_depth=1)

    deps_by_guid = {d["guid"]: d for d in out["dependents"]}
    assert set(deps_by_guid) == {"ws-1", "lb-1", "ans-1"}

    # ws-1 matched via both the join hit and the AI-surface (DMI) hit — deduped.
    assert deps_by_guid["ws-1"]["matched_columns"] == ["ZIPCODE"]

    # lb-1 matched via the Monitor-alert hit (correlated by the export doc's own
    # info.id, i.e. the requested Liveboard GUID — not the alert's internal guid).
    assert deps_by_guid["lb-1"]["matched_columns"] == ["ZIPCODE"]

    # ans-1 has no probe hits at all — must default to an empty list, not be
    # omitted or crash.
    assert deps_by_guid["ans-1"]["matched_columns"] == []


@patch("ts_cli.report.ThoughtSpotClient")
def test_no_deep_probes_leaves_matched_columns_empty(MockClient):
    """with_deep=False must not populate matched_columns for anyone (no probes ran)."""
    client = MagicMock()
    MockClient.return_value = client

    client.post.side_effect = [
        _resp([{
            "metadata_id": "col-1", "metadata_name": "ZIPCODE",
            "metadata_type": "LOGICAL_COLUMN",
            "metadata_header": {"id": "col-1", "name": "ZIPCODE"},
        }]),
        _resp([{
            "metadata_id": "col-1",
            "dependent_objects": {
                "dependents": {
                    "col-1": {
                        "LOGICAL_TABLE": [{"id": "ws-1", "name": "Customer 360"}],
                    },
                },
            },
        }]),
    ]

    out = build_report("baa451a6-02a0-42d1-8347-8cd4af13b505", profile="test",
                        with_deep=False, max_depth=1)

    assert out["dependents"][0]["matched_columns"] == []
