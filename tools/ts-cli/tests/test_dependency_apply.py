"""Unit tests for `ts_cli.dependency.apply` — the pure decision logic behind
`ts dependency apply-change` (BL-083 PR2).

Every function here is pure (no network, no I/O), so the destructive orchestrator's
safety-critical decisions — drift detection, the import/verify outcome matrix, the
set-delete consumer guard, 9c ordering, and chart-axis-role classification — are
tested deterministically without a live ThoughtSpot instance. The I/O shell that
wires these into network calls is tested separately in test_dependency_command.py.
"""
from __future__ import annotations

from ts_cli.dependency import apply


# ---------------------------------------------------------------------------
# derive_target_obj_id (SKILL.md Step 9 ~991)
# ---------------------------------------------------------------------------

class TestDeriveTargetObjId:
    def test_format_is_name_dash_first8_of_guid(self):
        assert apply.derive_target_obj_id("New Model", "abcd1234efgh5678") == "New Model-abcd1234"

    def test_short_guid_uses_whole_guid(self):
        assert apply.derive_target_obj_id("M", "abc") == "M-abc"


# ---------------------------------------------------------------------------
# is_drift (SKILL.md check_drift ~910)
# ---------------------------------------------------------------------------

class TestIsDrift:
    def test_no_snapshot_means_no_drift(self):
        # A falsy snapshot (0/None) can't be compared — be permissive, not fail-safe;
        # the source-not-found case surfaces later in the flow.
        assert apply.is_drift(0, 123) is False
        assert apply.is_drift(None, 123) is False

    def test_equal_timestamps_no_drift(self):
        assert apply.is_drift(1000, 1000) is False

    def test_changed_timestamp_is_drift(self):
        assert apply.is_drift(1000, 2000) is True


# ---------------------------------------------------------------------------
# import_outcome — the 4-cell matrix (SKILL.md import_and_verify ~1259)
# ---------------------------------------------------------------------------

class TestImportOutcome:
    def test_ok_and_verified_is_success(self):
        assert apply.import_outcome(True, True) == "SUCCESS"

    def test_error_but_verified_is_success_with_warning(self):
        # open-item #15: TS returns ERROR but actually applied the change.
        assert apply.import_outcome(False, True) == "SUCCESS_WITH_WARNING"

    def test_ok_but_not_verified_is_fail_silent(self):
        assert apply.import_outcome(True, False) == "FAIL_SILENT"

    def test_error_and_not_verified_is_fail_verified(self):
        assert apply.import_outcome(False, False) == "FAIL_VERIFIED"

    def test_is_success_outcome_helper(self):
        assert apply.is_success_outcome("SUCCESS") is True
        assert apply.is_success_outcome("SUCCESS_WITH_WARNING") is True
        assert apply.is_success_outcome("FAIL_SILENT") is False
        assert apply.is_success_outcome("FAIL_VERIFIED") is False


# ---------------------------------------------------------------------------
# verify_remove_applied (SKILL.md verify_change_applied REMOVE branch ~1202)
# ---------------------------------------------------------------------------

class TestVerifyRemoveApplied:
    def test_clean_body_verifies(self):
        body = '{"model": {"columns": [{"name": "Keep"}]}}'
        ok, detail = apply.verify_remove_applied(body, ["Revenue", "Cost"])
        assert ok is True
        assert "Revenue" in detail or "none" in detail.lower()

    def test_leftover_quoted_name_fails(self):
        body = '{"answer": {"answer_columns": [{"name": "Revenue"}]}}'
        ok, detail = apply.verify_remove_applied(body, ["Revenue"])
        assert ok is False
        assert "Revenue" in detail

    def test_leftover_bracket_token_fails(self):
        body = '{"view": {"search_query": "[Revenue] by [Region]"}}'
        ok, detail = apply.verify_remove_applied(body, ["Revenue"])
        assert ok is False

    def test_leftover_table_qualified_fails(self):
        body = '{"model": {"columns": [{"column_id": "Orders_1::Revenue"}]}}'
        ok, detail = apply.verify_remove_applied(body, ["Revenue"])
        assert ok is False

    def test_empty_columns_verifies_trivially(self):
        ok, _ = apply.verify_remove_applied('{"anything": 1}', [])
        assert ok is True


# ---------------------------------------------------------------------------
# verify_repoint_applied (SKILL.md verify_change_applied REPOINT branch ~1213)
# ---------------------------------------------------------------------------

class TestVerifyRepointApplied:
    def test_target_guid_present_verifies(self):
        body = '{"answer": {"tables": [{"fqn": "target-guid-123"}]}}'
        ok, _ = apply.verify_repoint_applied(body, "target-guid-123", None, [])
        assert ok is True

    def test_target_obj_id_present_verifies(self):
        body = '{"answer": {"tables": [{"obj_id": "New Model-abcd1234"}]}}'
        ok, _ = apply.verify_repoint_applied(body, "target-guid-123", "New Model-abcd1234", [])
        assert ok is True

    def test_target_absent_fails(self):
        body = '{"answer": {"tables": [{"fqn": "some-other-guid"}]}}'
        ok, detail = apply.verify_repoint_applied(body, "target-guid-123", None, [])
        assert ok is False
        assert "not in TML" in detail

    def test_gap_column_still_present_fails(self):
        body = '{"answer": {"tables": [{"fqn": "target-guid-123"}], "x": "[Legacy]"}}'
        ok, detail = apply.verify_repoint_applied(body, "target-guid-123", None, ["Legacy"])
        assert ok is False
        assert "gap" in detail.lower()

    def test_target_present_and_gap_absent_verifies(self):
        body = '{"answer": {"tables": [{"fqn": "target-guid-123"}]}}'
        ok, _ = apply.verify_repoint_applied(body, "target-guid-123", None, ["Legacy"])
        assert ok is True


# ---------------------------------------------------------------------------
# 9c fix ordering (SKILL.md Step 9 overview ~887-890)
# ---------------------------------------------------------------------------

class TestFixOrdering:
    def test_terminal_types_first_models_last(self):
        deps = [
            {"guid": "m", "type": "MODEL"},
            {"guid": "a", "type": "ANSWER"},
            {"guid": "v", "type": "VIEW"},
            {"guid": "l", "type": "LIVEBOARD"},
            {"guid": "s", "type": "SET"},
            {"guid": "f", "type": "FEEDBACK"},
        ]
        ordered = [d["type"] for d in apply.sort_fixes(deps)]
        # Answers/Liveboards before Sets before Views before Feedback before Models.
        assert ordered.index("ANSWER") < ordered.index("SET")
        assert ordered.index("LIVEBOARD") < ordered.index("SET")
        assert ordered.index("SET") < ordered.index("VIEW")
        assert ordered.index("VIEW") < ordered.index("FEEDBACK")
        assert ordered.index("FEEDBACK") < ordered.index("MODEL")

    def test_case_insensitive_type(self):
        deps = [{"guid": "m", "type": "model"}, {"guid": "a", "type": "answer"}]
        ordered = [d["guid"] for d in apply.sort_fixes(deps)]
        assert ordered == ["a", "m"]

    def test_unknown_type_sorts_last(self):
        deps = [{"guid": "x", "type": "MYSTERY"}, {"guid": "m", "type": "MODEL"}]
        ordered = [d["guid"] for d in apply.sort_fixes(deps)]
        assert ordered == ["m", "x"]

    def test_stable_within_same_type(self):
        deps = [{"guid": "a1", "type": "ANSWER"}, {"guid": "a2", "type": "ANSWER"}]
        ordered = [d["guid"] for d in apply.sort_fixes(deps)]
        assert ordered == ["a1", "a2"]


# ---------------------------------------------------------------------------
# set_delete_decision — the consumer-fix guard (SKILL.md Step 9d ~1908)
# ---------------------------------------------------------------------------

class TestSetDeleteDecision:
    def test_delete_when_no_consumers_failed(self):
        s = {"guid": "set-1", "name": "Cohort", "in_use_by": ["a", "b"]}
        should_delete, reason = apply.set_delete_decision(s, failed_fix_guids=set())
        assert should_delete is True
        assert reason == ""

    def test_skip_when_a_consumer_fix_failed(self):
        s = {"guid": "set-1", "name": "Cohort", "in_use_by": ["a", "b"]}
        should_delete, reason = apply.set_delete_decision(s, failed_fix_guids={"b"})
        assert should_delete is False
        assert "b" in reason
        assert "consumer" in reason.lower()

    def test_delete_when_failed_guids_are_unrelated(self):
        s = {"guid": "set-1", "name": "Cohort", "in_use_by": ["a"]}
        should_delete, _ = apply.set_delete_decision(s, failed_fix_guids={"z"})
        assert should_delete is True

    def test_no_consumers_always_deletes(self):
        s = {"guid": "set-1", "name": "Cohort"}
        should_delete, _ = apply.set_delete_decision(s, failed_fix_guids={"z"})
        assert should_delete is True


# ---------------------------------------------------------------------------
# chart_role_for_answer / classify_liveboard_viz_roles (BL-083 PR2 —
# codifies the REMOVE_CHART vs REMOVE_COLUMN decision the SKILL's Step 4/6
# previously made by hand; ts metadata report does not emit it)
# ---------------------------------------------------------------------------

class TestChartRoleForAnswer:
    def test_x_axis_use_is_remove_chart(self):
        answer = {
            "display_mode": "CHART_MODE",
            "chart": {"axis_configs": [{"x": ["Region"], "y": ["Revenue"]}]},
        }
        assert apply.chart_role_for_answer(answer, ["Region"]) == "REMOVE_CHART"

    def test_y_axis_use_is_remove_chart(self):
        answer = {
            "display_mode": "CHART_MODE",
            "chart": {"axis_configs": [{"x": ["Region"], "y": ["Revenue"]}]},
        }
        assert apply.chart_role_for_answer(answer, ["Revenue"]) == "REMOVE_CHART"

    def test_color_binding_only_is_remove_column(self):
        answer = {
            "display_mode": "CHART_MODE",
            "chart": {"axis_configs": [{"x": ["Region"], "y": ["Revenue"], "color": ["Segment"]}]},
        }
        assert apply.chart_role_for_answer(answer, ["Segment"]) == "REMOVE_COLUMN"

    def test_table_mode_answer_is_remove_column_even_if_axis_lists_column(self):
        # A table-mode answer can always just drop the column; a stale axis_config
        # binding does not cause an import rejection when the answer isn't a chart.
        answer = {
            "display_mode": "TABLE_MODE",
            "chart": {"axis_configs": [{"x": ["Region"]}]},
        }
        assert apply.chart_role_for_answer(answer, ["Region"]) == "REMOVE_COLUMN"

    def test_no_chart_is_remove_column(self):
        answer = {"display_mode": "TABLE_MODE", "answer_columns": [{"name": "Region"}]}
        assert apply.chart_role_for_answer(answer, ["Region"]) == "REMOVE_COLUMN"

    def test_column_not_used_is_remove_column(self):
        answer = {
            "display_mode": "CHART_MODE",
            "chart": {"axis_configs": [{"x": ["Region"], "y": ["Revenue"]}]},
        }
        assert apply.chart_role_for_answer(answer, ["Unrelated"]) == "REMOVE_COLUMN"


class TestClassifyLiveboardVizRoles:
    def test_per_viz_roles(self):
        lb = {
            "visualizations": [
                {"id": "v1", "answer": {
                    "display_mode": "CHART_MODE",
                    "tables": [{"fqn": "src"}],
                    "chart": {"axis_configs": [{"x": ["Region"], "y": ["Revenue"]}]}}},
                {"id": "v2", "answer": {
                    "display_mode": "CHART_MODE",
                    "tables": [{"fqn": "src"}],
                    "chart": {"axis_configs": [{"x": ["Product"], "y": ["Units"], "color": ["Region"]}]}}},
                {"id": "v3", "answer": {
                    "display_mode": "TABLE_MODE",
                    "tables": [{"fqn": "src"}]}},
            ]
        }
        roles = apply.classify_liveboard_viz_roles(lb, ["Region"], source_guid="src")
        assert roles["v1"] == "REMOVE_CHART"     # Region on x axis
        assert roles["v2"] == "REMOVE_COLUMN"    # Region only a color binding
        assert roles["v3"] == "REMOVE_COLUMN"    # table mode

    def test_only_vizzes_referencing_source_included(self):
        lb = {
            "visualizations": [
                {"id": "v1", "answer": {
                    "display_mode": "CHART_MODE",
                    "tables": [{"fqn": "other"}],
                    "chart": {"axis_configs": [{"x": ["Region"]}]}}},
            ]
        }
        roles = apply.classify_liveboard_viz_roles(lb, ["Region"], source_guid="src")
        assert roles == {}

    def test_source_guid_none_includes_all_vizzes(self):
        lb = {
            "visualizations": [
                {"id": "v1", "answer": {
                    "display_mode": "CHART_MODE",
                    "tables": [{"fqn": "anything"}],
                    "chart": {"axis_configs": [{"x": ["Region"]}]}}},
            ]
        }
        roles = apply.classify_liveboard_viz_roles(lb, ["Region"], source_guid=None)
        assert roles == {"v1": "REMOVE_CHART"}


# ---------------------------------------------------------------------------
# v2 delete type mapping is reused from backup.py — assert apply re-exports it
# so the command module has a single import surface.
# ---------------------------------------------------------------------------

class TestReexports:
    def test_v2_type_map_available(self):
        assert apply.v2_type_for("MODEL") == "LOGICAL_TABLE"
        assert apply.v2_type_for("ANSWER") == "ANSWER"
        assert apply.v2_type_for("SET") == "LOGICAL_COLUMN"
        assert apply.v2_type_for("mystery") == "LOGICAL_TABLE"  # default
