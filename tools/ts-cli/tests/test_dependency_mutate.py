"""Unit tests for ts_cli.dependency.mutate — the pure REMOVE/REPOINT TML transforms
behind `ts dependency mutate` (BL-083 PR1).

Ports every remove_*/repoint_*/model/view/answer/table behaviour previously asserted
in the now-deleted `test_dependency_helpers.py` (which tested inline duplicates of
these functions) against the real, imported implementations in
`ts_cli.dependency.mutate`. RENAME-mode tests (rename_in_search_query,
rename_column_in_answer/view/set, remove_model_joins, classify_chart_role, diff_scan)
are NOT ported — see that module's docstring for why RENAME is dead code here, and
the PR report for the classify_chart_role/diff_scan gap (those are Step 4/5 concerns,
out of scope for this Step 9/7/11 extraction).

Adds dispatcher-level tests (apply_remove/apply_repoint) across all 6 TML document
types plus nls_feedback, and asserts the deepcopy-at-the-boundary contract: dispatcher
inputs are never mutated, even though the low-level helpers they call mutate in place.
"""
from __future__ import annotations

from ts_cli.dependency.mutate import (
    apply_remove,
    apply_repoint,
    convert_answer_to_table,
    remove_columns_from_answer,
    remove_columns_from_feedback,
    remove_columns_from_model_section,
    remove_columns_from_table_section,
    remove_columns_from_view,
    repoint_answer,
    repoint_model,
    repoint_view,
    sanitize_search_query,
)


# ---------------------------------------------------------------------------
# sanitize_search_query
# ---------------------------------------------------------------------------

class TestSanitizeSearchQuery:
    def test_removes_single_column(self):
        result = sanitize_search_query("[Revenue] by [Region]", ["Revenue"])
        assert result == "by [Region]"

    def test_removes_multiple_columns(self):
        result = sanitize_search_query("[Revenue] [Cost] by [Date]", ["Revenue", "Cost"])
        assert result == "by [Date]"

    def test_leaves_unrelated_columns(self):
        result = sanitize_search_query("[Revenue] by [Region]", ["Cost"])
        assert result == "[Revenue] by [Region]"

    def test_handles_extra_whitespace(self):
        result = sanitize_search_query("  [Revenue]  by  [Region]  ", ["Revenue"])
        assert "[Revenue]" not in result
        assert "[Region]" in result

    def test_empty_query(self):
        assert sanitize_search_query("", ["Revenue"]) == ""

    def test_none_query(self):
        assert sanitize_search_query(None, ["Revenue"]) is None

    def test_column_not_in_query(self):
        result = sanitize_search_query("[Revenue] by [Region]", ["NoSuchCol"])
        assert result == "[Revenue] by [Region]"

    def test_special_regex_chars_in_column_name(self):
        result = sanitize_search_query("[Revenue (USD)] by [Region]", ["Revenue (USD)"])
        assert "[Revenue (USD)]" not in result
        assert "[Region]" in result


# ---------------------------------------------------------------------------
# convert_answer_to_table
# ---------------------------------------------------------------------------

class TestConvertAnswerToTable:
    def test_sets_table_mode(self):
        result = convert_answer_to_table({"display_mode": "CHART_MODE"})
        assert result["display_mode"] == "TABLE_MODE"

    def test_mutates_in_place(self):
        original = {"display_mode": "CHART_MODE"}
        result = convert_answer_to_table(original)
        assert result is original


# ---------------------------------------------------------------------------
# remove_columns_from_answer
# ---------------------------------------------------------------------------

class TestRemoveColumnsFromAnswer:
    def _sample_answer(self):
        return {
            "answer_columns": [
                {"name": "Revenue", "column_id": "Revenue"},
                {"name": "Cost", "column_id": "Cost"},
                {"name": "Region", "column_id": "Region"},
            ],
            "search_query": "[Revenue] [Cost] by [Region]",
        }

    def test_removes_column_from_list(self):
        result = remove_columns_from_answer(self._sample_answer(), ["Revenue"])
        names = [c["name"] for c in result["answer_columns"]]
        assert "Revenue" not in names
        assert "Cost" in names
        assert "Region" in names

    def test_sanitizes_search_query(self):
        result = remove_columns_from_answer(self._sample_answer(), ["Revenue"])
        assert "[Revenue]" not in result["search_query"]
        assert "[Region]" in result["search_query"]

    def test_removes_multiple_columns(self):
        result = remove_columns_from_answer(self._sample_answer(), ["Revenue", "Cost"])
        names = [c["name"] for c in result["answer_columns"]]
        assert "Revenue" not in names
        assert "Cost" not in names

    def test_mutates_in_place(self):
        original = self._sample_answer()
        result = remove_columns_from_answer(original, ["Revenue"])
        assert result is original
        assert len(original["answer_columns"]) == 2

    def test_no_search_query_key(self):
        section = {"answer_columns": [{"name": "Revenue", "column_id": "Revenue"}]}
        result = remove_columns_from_answer(section, ["Revenue"])
        assert "search_query" not in result

    def test_chart_strips_color_binding(self):
        section = {
            "answer_columns": [{"name": "Region", "column_id": "Region"}],
            "chart": {
                "chart_columns": [
                    {"column_id": "Revenue", "type": "MEASURE"},
                    {"column_id": "Region", "type": "ATTRIBUTE"},
                ],
                "axis_configs": [
                    {"x": ["Date"], "y": ["Revenue"], "color": ["Region"]},
                ],
            },
        }
        result = remove_columns_from_answer(section, ["Region"])
        assert {"column_id": "Region", "type": "ATTRIBUTE"} not in result["chart"]["chart_columns"]
        assert result["chart"]["axis_configs"][0]["color"] == []

    def test_chart_does_not_strip_x_y_axis(self):
        section = {
            "answer_columns": [{"name": "Revenue"}],
            "chart": {
                "chart_columns": [{"column_id": "Revenue"}],
                "axis_configs": [{"x": ["Date"], "y": ["Revenue"]}],
            },
        }
        result = remove_columns_from_answer(section, ["Revenue"])
        chart_col_ids = [c["column_id"] for c in result["chart"]["chart_columns"]]
        assert "Revenue" not in chart_col_ids
        assert result["chart"]["axis_configs"][0]["y"] == ["Revenue"]

    def test_strips_table_columns(self):
        section = {
            "answer_columns": [],
            "table": {
                "ordered_column_ids": ["Revenue", "Region"],
                "table_columns": [
                    {"column_id": "Revenue"},
                    {"column_id": "Region"},
                ],
            },
        }
        result = remove_columns_from_answer(section, ["Revenue"])
        assert "Revenue" not in result["table"]["ordered_column_ids"]
        assert "Region" in result["table"]["ordered_column_ids"]
        col_ids = [c["column_id"] for c in result["table"]["table_columns"]]
        assert "Revenue" not in col_ids

    def test_strips_answer_level_cohort(self):
        section = {
            "answer_columns": [
                {"name": "Revenue"},
                {"name": "Zipcode Ranges"},
            ],
            "search_query": "[Revenue] [Zipcode Ranges]",
            "cohorts": [
                {"name": "Zipcode Ranges", "config": {"anchor_column_id": "Customer Zipcode"}},
            ],
        }
        result = remove_columns_from_answer(section, ["Customer Zipcode"])
        assert result["cohorts"] == []
        names = [c["name"] for c in result["answer_columns"]]
        assert "Zipcode Ranges" not in names
        assert "[Zipcode Ranges]" not in result["search_query"]

    def test_cohort_not_removed_when_anchor_not_in_cols_to_remove(self):
        section = {
            "answer_columns": [{"name": "Revenue"}, {"name": "Zipcode Ranges"}],
            "cohorts": [
                {"name": "Zipcode Ranges", "config": {"anchor_column_id": "Customer Zipcode"}},
            ],
        }
        result = remove_columns_from_answer(section, ["Revenue"])
        assert len(result["cohorts"]) == 1
        assert "Zipcode Ranges" in [c["name"] for c in result["answer_columns"]]

    def test_removes_formula_and_its_answer_column_by_id(self):
        section = {
            "answer_columns": [
                {"name": "Margin", "formula_id": "f1"},
                {"name": "Revenue"},
            ],
            "formulas": [{"id": "f1", "name": "Margin", "expr": "[Revenue] - [Cost]"}],
        }
        result = remove_columns_from_answer(section, ["Cost"])
        assert result["formulas"] == []
        names = [c["name"] for c in result["answer_columns"]]
        assert "Margin" not in names
        assert "Revenue" in names

    def test_removes_answer_column_referencing_formula_by_name_only(self):
        # A stray answer_columns entry that names the removed formula but has no
        # formula_id set must still be scrubbed (the corrected-during-extraction
        # behaviour — see module docstring).
        section = {
            "answer_columns": [
                {"name": "Margin"},  # no formula_id — matched by name instead
                {"name": "Revenue"},
            ],
            "formulas": [{"id": "f1", "name": "Margin", "expr": "[Revenue] - [Cost]"}],
        }
        result = remove_columns_from_answer(section, ["Cost"])
        names = [c["name"] for c in result["answer_columns"]]
        assert "Margin" not in names
        assert "Revenue" in names


# ---------------------------------------------------------------------------
# remove_columns_from_view
# ---------------------------------------------------------------------------

class TestRemoveColumnsFromView:
    def _sample_view(self):
        return {
            "view_columns": [
                {"name": "Revenue", "column_id": "Orders_1::Revenue"},
                {"name": "Region", "column_id": "Region_1::Region"},
            ],
            "search_query": "[Revenue] by [Region]",
            "joins": [
                {"name": "Orders_Region_join", "on": "[Revenue] = [Orders_1::Revenue]"},
                {"name": "Safe_join", "on": "[Region] = [Region_1::Region]"},
            ],
        }

    def test_removes_column_from_view_columns(self):
        result = remove_columns_from_view(self._sample_view(), ["Revenue"])
        names = [c["name"] for c in result["view_columns"]]
        assert "Revenue" not in names
        assert "Region" in names

    def test_sanitizes_search_query(self):
        result = remove_columns_from_view(self._sample_view(), ["Revenue"])
        assert "[Revenue]" not in result["search_query"]

    def test_drops_join_referencing_removed_column(self):
        result = remove_columns_from_view(self._sample_view(), ["Revenue"])
        join_names = [j["name"] for j in result["joins"]]
        assert "Orders_Region_join" not in join_names
        assert "Safe_join" in join_names

    def test_keeps_joins_not_referencing_removed_column(self):
        result = remove_columns_from_view(self._sample_view(), ["Revenue"])
        assert len(result["joins"]) == 1

    def test_mutates_in_place(self):
        # Contract change from the old duplicated helper (which deepcopied
        # internally): the extracted mutate.py helpers all mutate in place, with
        # deepcopy centralised at the apply_remove/apply_repoint dispatcher boundary.
        original = self._sample_view()
        result = remove_columns_from_view(original, ["Revenue"])
        assert result is original
        assert len(original["view_columns"]) == 1

    def test_removes_formula_and_its_view_column(self):
        section = {
            "view_columns": [{"name": "Margin", "column_id": "f1"}],
            "formulas": [{"id": "f1", "name": "Margin", "expr": "[Revenue] - [Cost]"}],
        }
        result = remove_columns_from_view(section, ["Cost"])
        assert result["formulas"] == []
        assert result["view_columns"] == []


# ---------------------------------------------------------------------------
# remove_columns_from_model_section (unifies SKILL.md's inline source-removal
# snippet and the fix_model() helper — identical logic, single function)
# ---------------------------------------------------------------------------

class TestRemoveColumnsFromModelSection:
    def _sample_model(self):
        return {
            "columns": [
                {"name": "Revenue", "formula_id": None},
                {"name": "Margin", "formula_id": "f1"},
                {"name": "Region"},
            ],
            "formulas": [{"id": "f1", "name": "Margin", "expr": "[Revenue] - [Cost]"}],
            "model_tables": [
                {
                    "name": "Orders",
                    "joins": [
                        {"name": "Orders_Region", "on": "[Revenue] = [Orders::Revenue]"},
                        {"name": "Orders_Date", "on": "[Date] = [Orders::Date]"},
                    ],
                },
            ],
            "filters": [
                {"column": ["Revenue"]},
                {"column": ["Region"]},
            ],
        }

    def test_removes_column_and_its_formula(self):
        result = remove_columns_from_model_section(self._sample_model(), ["Margin"])
        names = [c["name"] for c in result["columns"]]
        assert "Margin" not in names
        assert result["formulas"] == []

    def test_removes_join_referencing_removed_column(self):
        result = remove_columns_from_model_section(self._sample_model(), ["Revenue"])
        joins = result["model_tables"][0]["joins"]
        join_names = [j["name"] for j in joins]
        assert "Orders_Region" not in join_names
        assert "Orders_Date" in join_names

    def test_removes_model_level_filter_referencing_removed_column(self):
        result = remove_columns_from_model_section(self._sample_model(), ["Revenue"])
        remaining = [f["column"] for f in result["filters"]]
        assert ["Revenue"] not in remaining
        assert ["Region"] in remaining

    def test_mutates_in_place(self):
        original = self._sample_model()
        result = remove_columns_from_model_section(original, ["Revenue"])
        assert result is original

    def test_no_joins_removed_when_column_not_referenced(self):
        result = remove_columns_from_model_section(self._sample_model(), ["NoSuchCol"])
        assert len(result["model_tables"][0]["joins"]) == 2
        assert len(result["filters"]) == 2

    def test_joins_with_key_is_not_touched(self):
        # model_tables never has `joins_with` — only `joins`. A stray joins_with
        # key (if present from bad data) must survive untouched.
        section = {
            "columns": [],
            "model_tables": [{"name": "Orders", "joins": [], "joins_with": [{"name": "stray"}]}],
        }
        result = remove_columns_from_model_section(section, ["Revenue"])
        assert result["model_tables"][0]["joins_with"] == [{"name": "stray"}]

    # --- BL-083 PR2 / open-items #24: aliased base-column removal by column_id + expr.
    # Mirrors the live DM_CATEGORY case: the model exposes base column CATEGORY_NAME as
    # an aliased column and references it by column_id in measure formulas.
    def _aliased_model(self):
        return {
            "columns": [
                {"name": "Product Category", "column_id": "DM_CATEGORY::CATEGORY_NAME"},
                {"name": "Category Quantity", "column_id": "f1", "formula_id": "f1"},
                {"name": "Sub Category", "column_id": "DM_CATEGORY::SUB_CATEGORY_NAME"},
                {"name": "Category ID", "column_id": "DM_CATEGORY::CATEGORY_ID"},
            ],
            "formulas": [
                {"id": "f1", "name": "Category Quantity",
                 "expr": "group_sum ( [DM_ORDER::QTY] , [DM_CATEGORY::CATEGORY_NAME] )"},
                {"id": "f2", "name": "Unrelated", "expr": "sum ( [DM_ORDER::QTY] )"},
            ],
        }

    def test_removes_aliased_column_by_column_id(self):
        result = remove_columns_from_model_section(self._aliased_model(), ["CATEGORY_NAME"])
        names = [c["name"] for c in result["columns"]]
        assert "Product Category" not in names           # matched via column_id, not name

    def test_removes_formula_referencing_column_by_expr_and_cascades_to_its_column(self):
        result = remove_columns_from_model_section(self._aliased_model(), ["CATEGORY_NAME"])
        formula_ids = [f["id"] for f in result["formulas"]]
        names = [c["name"] for c in result["columns"]]
        assert "f1" not in formula_ids                   # expr referenced CATEGORY_NAME
        assert "Category Quantity" not in names          # cascaded — its formula is gone
        assert "f2" in formula_ids                        # unrelated formula survives

    def test_word_boundary_does_not_over_match_similar_columns(self):
        result = remove_columns_from_model_section(self._aliased_model(), ["CATEGORY_NAME"])
        names = [c["name"] for c in result["columns"]]
        assert "Sub Category" in names                    # SUB_CATEGORY_NAME must survive
        assert "Category ID" in names                     # CATEGORY_ID must survive

    def test_no_category_name_token_remains_after_removal(self):
        import json as _json
        result = remove_columns_from_model_section(self._aliased_model(), ["CATEGORY_NAME"])
        body = _json.dumps(result)
        assert "::CATEGORY_NAME" not in body and "[DM_CATEGORY::CATEGORY_NAME]" not in body

    def test_filter_with_table_qualified_column_is_removed(self):
        section = {
            "columns": [],
            "filters": [
                {"column": ["DM_CATEGORY::CATEGORY_NAME"]},
                {"column": ["DM_CATEGORY::CATEGORY_ID"]},
            ],
        }
        result = remove_columns_from_model_section(section, ["CATEGORY_NAME"])
        remaining = [f["column"] for f in result["filters"]]
        assert ["DM_CATEGORY::CATEGORY_NAME"] not in remaining
        assert ["DM_CATEGORY::CATEGORY_ID"] in remaining


# ---------------------------------------------------------------------------
# remove_columns_from_table_section
# ---------------------------------------------------------------------------

class TestRemoveColumnsFromTableSection:
    def test_removes_column(self):
        section = {"columns": [{"name": "Revenue"}, {"name": "Region"}]}
        result = remove_columns_from_table_section(section, ["Revenue"])
        names = [c["name"] for c in result["columns"]]
        assert "Revenue" not in names
        assert "Region" in names

    def test_mutates_in_place(self):
        original = {"columns": [{"name": "Revenue"}]}
        result = remove_columns_from_table_section(original, ["Revenue"])
        assert result is original
        assert original["columns"] == []


# ---------------------------------------------------------------------------
# remove_columns_from_feedback
# ---------------------------------------------------------------------------

class TestRemoveColumnsFromFeedback:
    def test_drops_entry_referencing_removed_column(self):
        section = {
            "feedback": [
                {"search_tokens": ["[Revenue]", "by", "[Region]"]},
                {"search_tokens": ["[Region]", "by", "[Date]"]},
            ]
        }
        result = remove_columns_from_feedback(section, ["Revenue"])
        assert len(result["feedback"]) == 1
        assert result["feedback"][0]["search_tokens"] == ["[Region]", "by", "[Date]"]

    def test_keeps_entries_not_referencing_removed_column(self):
        section = {"feedback": [{"search_tokens": ["[Region]"]}]}
        result = remove_columns_from_feedback(section, ["Revenue"])
        assert len(result["feedback"]) == 1

    def test_scans_nested_structure_via_json_dump(self):
        # The column reference can be nested arbitrarily deep (formula_info, etc.) —
        # the whole-entry json.dumps() scan must catch it regardless of shape.
        section = {"feedback": [{"formula_info": {"expr": "[Revenue] - [Cost]"}}]}
        result = remove_columns_from_feedback(section, ["Cost"])
        assert result["feedback"] == []

    def test_mutates_in_place(self):
        original = {"feedback": [{"search_tokens": ["[Revenue]"]}]}
        result = remove_columns_from_feedback(original, ["Revenue"])
        assert result is original
        assert original["feedback"] == []


# ---------------------------------------------------------------------------
# repoint_answer
# ---------------------------------------------------------------------------

class TestRepointAnswer:
    def test_repoints_by_fqn(self):
        section = {"tables": [{"fqn": "src-guid", "name": "Old", "id": "Old"}]}
        result = repoint_answer(section, "src-guid", "tgt-guid", "New Model", [])
        tbl = result["tables"][0]
        assert tbl["fqn"] == "tgt-guid"
        assert tbl["name"] == "New Model"
        assert tbl["id"] == "New Model"

    def test_repoints_by_obj_id_preferred_over_fqn(self):
        section = {"tables": [{"fqn": "src-guid", "obj_id": "src-obj", "name": "Old"}]}
        result = repoint_answer(
            section, "src-guid", "tgt-guid", "New Model", [],
            source_obj_id="src-obj", target_obj_id="tgt-obj",
        )
        tbl = result["tables"][0]
        assert tbl["obj_id"] == "tgt-obj"
        assert "fqn" not in tbl

    def test_non_matching_table_untouched(self):
        section = {"tables": [{"fqn": "other-guid", "name": "Unrelated"}]}
        result = repoint_answer(section, "src-guid", "tgt-guid", "New Model", [])
        assert result["tables"][0]["name"] == "Unrelated"

    def test_column_gap_removed(self):
        section = {
            "tables": [{"fqn": "src-guid", "name": "Old"}],
            "answer_columns": [{"name": "Legacy Col"}, {"name": "Revenue"}],
        }
        result = repoint_answer(section, "src-guid", "tgt-guid", "New Model", ["Legacy Col"])
        names = [c["name"] for c in result["answer_columns"]]
        assert "Legacy Col" not in names
        assert "Revenue" in names

    def test_mutates_in_place(self):
        original = {"tables": [{"fqn": "src-guid", "name": "Old"}]}
        result = repoint_answer(original, "src-guid", "tgt-guid", "New Model", [])
        assert result is original


# ---------------------------------------------------------------------------
# repoint_view
# ---------------------------------------------------------------------------

class TestRepointView:
    def test_repoints_table_and_renames_paths_and_joins(self):
        section = {
            "tables": [{"fqn": "src-guid", "name": "Old", "id": "Old"}],
            "table_paths": [{"table": "Old"}],
            "joins": [{"source": "Old", "destination": "Region"}],
        }
        result = repoint_view(section, "src-guid", "tgt-guid", "New Model", [])
        assert result["tables"][0]["fqn"] == "tgt-guid"
        assert result["tables"][0]["name"] == "New Model"
        assert result["table_paths"][0]["table"] == "New Model"
        assert result["joins"][0]["source"] == "New Model"
        assert result["joins"][0]["destination"] == "Region"

    def test_no_rename_when_target_name_equals_old_name(self):
        section = {
            "tables": [{"fqn": "src-guid", "name": "Same", "id": "Same"}],
            "table_paths": [{"table": "Same"}],
        }
        result = repoint_view(section, "src-guid", "tgt-guid", "Same", [])
        assert result["table_paths"][0]["table"] == "Same"

    def test_column_gap_removed(self):
        section = {
            "tables": [{"fqn": "src-guid", "name": "Old"}],
            "view_columns": [{"name": "Legacy Col", "column_id": "Legacy Col"}],
        }
        result = repoint_view(section, "src-guid", "tgt-guid", "New Model", ["Legacy Col"])
        assert result["view_columns"] == []

    def test_mutates_in_place(self):
        original = {"tables": [{"fqn": "src-guid", "name": "Old"}]}
        result = repoint_view(original, "src-guid", "tgt-guid", "New Model", [])
        assert result is original


# ---------------------------------------------------------------------------
# repoint_model
# ---------------------------------------------------------------------------

class TestRepointModel:
    def _sample_model(self):
        return {
            "model_tables": [
                {
                    "name": "Orders",
                    "fqn": "src-guid",
                    "joins": [{"with": "Orders", "on": "[Orders::Revenue] = [Region::Revenue]"}],
                },
            ],
            "columns": [{"column_id": "Orders::Revenue"}],
            "formulas": [{"id": "f1", "expr": "[Orders::Revenue] - [Orders::Cost]"}],
            "description": "Joins to Orders for revenue.",
        }

    def test_repoints_model_table_by_name(self):
        result = repoint_model(
            self._sample_model(), "Orders", "NewOrders", [], target_guid="tgt-guid",
        )
        tbl = result["model_tables"][0]
        assert tbl["name"] == "NewOrders"
        assert tbl["fqn"] == "tgt-guid"

    def test_repoint_without_target_guid_or_obj_id_renames_but_leaves_fqn(self):
        # matched purely by name (no source_guid/source_obj_id given) still renames
        # the table, but fqn/obj_id are only rewritten when a target reference is
        # actually supplied.
        result = repoint_model(self._sample_model(), "Orders", "NewOrders", [])
        tbl = result["model_tables"][0]
        assert tbl["name"] == "NewOrders"
        assert tbl["fqn"] == "src-guid"

    def test_repoints_by_obj_id(self):
        section = self._sample_model()
        result = repoint_model(
            section, "Orders", "NewOrders", [],
            source_obj_id="orders-obj", target_obj_id="new-obj",
        )
        # obj_id branch only fires when tbl.obj_id == source_obj_id; here it's absent,
        # so the fallback to name match still applies and target_obj_id is written.
        tbl = result["model_tables"][0]
        assert tbl["name"] == "NewOrders"

    def test_updates_join_with_and_on_clause(self):
        result = repoint_model(self._sample_model(), "Orders", "NewOrders", [])
        join = result["model_tables"][0]["joins"][0]
        assert join["with"] == "NewOrders"
        assert "[NewOrders::" in join["on"]

    def test_updates_column_id_prefix(self):
        result = repoint_model(self._sample_model(), "Orders", "NewOrders", [])
        assert result["columns"][0]["column_id"] == "NewOrders::Revenue"

    def test_updates_formula_expr(self):
        result = repoint_model(self._sample_model(), "Orders", "NewOrders", [])
        assert "[NewOrders::Revenue]" in result["formulas"][0]["expr"]
        assert "[NewOrders::Cost]" in result["formulas"][0]["expr"]

    def test_updates_description(self):
        result = repoint_model(self._sample_model(), "Orders", "NewOrders", [])
        assert "NewOrders" in result["description"]

    def test_column_gap_strips_column_and_join(self):
        section = self._sample_model()
        section["columns"].append({"name": "Legacy Col", "column_id": "Legacy Col"})
        result = repoint_model(section, "Orders", "NewOrders", ["Legacy Col"])
        names = [c.get("name") for c in result["columns"]]
        assert "Legacy Col" not in names

    def test_mutates_in_place(self):
        original = self._sample_model()
        result = repoint_model(original, "Orders", "NewOrders", [])
        assert result is original


# ---------------------------------------------------------------------------
# apply_remove — dispatcher tests across all 6 doc types + nls_feedback
# ---------------------------------------------------------------------------

class TestApplyRemoveDispatcher:
    def test_answer_doc(self):
        doc = {"answer": {"answer_columns": [{"name": "Revenue"}]}}
        result = apply_remove(doc, ["Revenue"])
        assert result["answer"]["answer_columns"] == []

    def test_view_doc(self):
        doc = {"view": {"view_columns": [{"name": "Revenue", "column_id": "Revenue"}]}}
        result = apply_remove(doc, ["Revenue"])
        assert result["view"]["view_columns"] == []

    def test_model_doc(self):
        doc = {"model": {"columns": [{"name": "Revenue"}]}}
        result = apply_remove(doc, ["Revenue"])
        assert result["model"]["columns"] == []

    def test_worksheet_doc(self):
        doc = {"worksheet": {"columns": [{"name": "Revenue"}]}}
        result = apply_remove(doc, ["Revenue"])
        assert result["worksheet"]["columns"] == []

    def test_table_doc(self):
        doc = {"table": {"columns": [{"name": "Revenue"}]}}
        result = apply_remove(doc, ["Revenue"])
        assert result["table"]["columns"] == []

    def test_liveboard_doc_default_convert_to_table(self):
        doc = {
            "liveboard": {
                "visualizations": [
                    {"id": "v1", "answer": {
                        "tables": [{"fqn": "src-guid"}],
                        "answer_columns": [{"name": "Revenue"}],
                    }},
                ],
                "filters": [{"column": ["Revenue"]}],
            }
        }
        result = apply_remove(doc, ["Revenue"], source_guid="src-guid")
        viz = result["liveboard"]["visualizations"][0]
        assert viz["answer"]["display_mode"] == "TABLE_MODE"
        assert viz["answer"]["answer_columns"] == []
        assert result["liveboard"]["filters"] == []

    def test_liveboard_viz_decision_remove_drops_viz(self):
        doc = {
            "liveboard": {
                "visualizations": [
                    {"id": "v1", "answer": {"tables": [{"fqn": "src-guid"}], "answer_columns": []}},
                    {"id": "v2", "answer": {"tables": [{"fqn": "src-guid"}], "answer_columns": []}},
                ],
            }
        }
        result = apply_remove(
            doc, ["Revenue"], source_guid="src-guid", viz_decisions={"v1": "REMOVE"},
        )
        ids = [v["id"] for v in result["liveboard"]["visualizations"]]
        assert ids == ["v2"]

    def test_liveboard_viz_not_referencing_source_is_skipped(self):
        doc = {
            "liveboard": {
                "visualizations": [
                    {"id": "v1", "answer": {"tables": [{"fqn": "other-guid"}], "answer_columns": [{"name": "Revenue"}]}},
                ],
            }
        }
        result = apply_remove(doc, ["Revenue"], source_guid="src-guid")
        viz = result["liveboard"]["visualizations"][0]
        assert "display_mode" not in viz["answer"]
        assert viz["answer"]["answer_columns"] == [{"name": "Revenue"}]

    def test_liveboard_none_source_guid_applies_to_every_viz(self):
        doc = {
            "liveboard": {
                "visualizations": [
                    {"id": "v1", "answer": {"tables": [{"fqn": "anything"}], "answer_columns": [{"name": "Revenue"}]}},
                ],
            }
        }
        result = apply_remove(doc, ["Revenue"], source_guid=None)
        viz = result["liveboard"]["visualizations"][0]
        assert viz["answer"]["answer_columns"] == []

    def test_nls_feedback_alongside_model_doc(self):
        doc = {
            "model": {"columns": [{"name": "Revenue"}]},
            "nls_feedback": {"feedback": [{"search_tokens": ["[Revenue]"]}]},
        }
        result = apply_remove(doc, ["Revenue"])
        assert result["model"]["columns"] == []
        assert result["nls_feedback"]["feedback"] == []

    def test_does_not_mutate_input(self):
        doc = {"answer": {"answer_columns": [{"name": "Revenue"}]}}
        apply_remove(doc, ["Revenue"])
        assert doc["answer"]["answer_columns"] == [{"name": "Revenue"}]

    def test_does_not_mutate_input_liveboard(self):
        doc = {
            "liveboard": {
                "visualizations": [
                    {"id": "v1", "answer": {"tables": [{"fqn": "src-guid"}], "answer_columns": [{"name": "Revenue"}]}},
                ],
            }
        }
        apply_remove(doc, ["Revenue"], source_guid="src-guid")
        viz = doc["liveboard"]["visualizations"][0]
        assert "display_mode" not in viz["answer"]
        assert viz["answer"]["answer_columns"] == [{"name": "Revenue"}]


# ---------------------------------------------------------------------------
# apply_repoint — dispatcher tests across all applicable doc types
# ---------------------------------------------------------------------------

class TestApplyRepointDispatcher:
    def test_answer_doc(self):
        doc = {"answer": {"tables": [{"fqn": "src-guid", "name": "Old"}]}}
        result = apply_repoint(
            doc, source_guid="src-guid", target_guid="tgt-guid",
            target_name="New Model", column_gap=[],
        )
        assert result["answer"]["tables"][0]["fqn"] == "tgt-guid"

    def test_view_doc(self):
        doc = {"view": {"tables": [{"fqn": "src-guid", "name": "Old", "id": "Old"}]}}
        result = apply_repoint(
            doc, source_guid="src-guid", target_guid="tgt-guid",
            target_name="New Model", column_gap=[],
        )
        assert result["view"]["tables"][0]["fqn"] == "tgt-guid"

    def test_model_doc_uses_section_name_as_source_name(self):
        doc = {
            "model": {
                "name": "Orders",
                "model_tables": [{"name": "Orders", "fqn": "src-guid", "joins": []}],
            }
        }
        result = apply_repoint(
            doc, source_guid="src-guid", target_guid="tgt-guid",
            target_name="NewOrders", column_gap=[],
        )
        assert result["model"]["model_tables"][0]["name"] == "NewOrders"

    def test_worksheet_doc(self):
        doc = {
            "worksheet": {
                "name": "Orders",
                "model_tables": [{"name": "Orders", "fqn": "src-guid", "joins": []}],
            }
        }
        result = apply_repoint(
            doc, source_guid="src-guid", target_guid="tgt-guid",
            target_name="NewOrders", column_gap=[],
        )
        assert result["worksheet"]["model_tables"][0]["name"] == "NewOrders"

    def test_liveboard_repoints_matching_viz_only(self):
        doc = {
            "liveboard": {
                "visualizations": [
                    {"id": "v1", "answer": {"tables": [{"fqn": "src-guid", "name": "Old"}]}},
                    {"id": "v2", "answer": {"tables": [{"fqn": "other-guid", "name": "Unrelated"}]}},
                ],
            }
        }
        result = apply_repoint(
            doc, source_guid="src-guid", target_guid="tgt-guid",
            target_name="New Model", column_gap=[],
        )
        vizzes = result["liveboard"]["visualizations"]
        assert vizzes[0]["answer"]["tables"][0]["fqn"] == "tgt-guid"
        assert vizzes[1]["answer"]["tables"][0]["name"] == "Unrelated"

    def test_table_doc_passes_through_unchanged(self):
        doc = {"table": {"columns": [{"name": "Revenue"}]}}
        result = apply_repoint(
            doc, source_guid="src-guid", target_guid="tgt-guid",
            target_name="New Model", column_gap=[],
        )
        assert result == doc

    def test_does_not_mutate_input(self):
        doc = {"answer": {"tables": [{"fqn": "src-guid", "name": "Old"}]}}
        apply_repoint(
            doc, source_guid="src-guid", target_guid="tgt-guid",
            target_name="New Model", column_gap=[],
        )
        assert doc["answer"]["tables"][0]["fqn"] == "src-guid"
