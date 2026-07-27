# tools/ts-cli/tests/test_tableau_sets_build.py
"""build_cohort_tml (BL-067 part 2) — Set spec -> `*.cohort.tml` dict.

One fixture per documented set type, asserting the exact emitted fields per
step-5-tml-generation.md "Tableau Sets -> ThoughtSpot column sets (Phase
2a/2b/2c)" and agents/shared/schemas/thoughtspot-sets-tml.md. Where the docs
give a live-verified worked example (Static Top 10, the dynamic-N form, "East
Top Revenue"), the fixture reproduces its exact field values.
"""
from __future__ import annotations

from ts_cli.tableau.sets import build_cohort_tml, classify_sets

MODEL = "TEST_SV_DMSI_AI_CONTEXT"
OBJ_ID = "TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY_AI_CONTEXT-889a704f"


# ---------------------------------------------------------------------------
# static (Phase 2a)
# ---------------------------------------------------------------------------

def test_static_set_group_based_column_set():
    spec = {
        "name": "Customer Group 1", "set_type": "static",
        "anchor_name": "Customer Name", "anchor_datatype": "string",
        "members": ["Aaron Bergman", "Aaron Hawkins"],
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL, model_obj_id=OBJ_ID)
    cohort = tml["cohort"]
    assert cohort["name"] == "Customer Group 1"
    cfg = cohort["config"]
    assert cfg["cohort_type"] == "SIMPLE"
    assert cfg["cohort_grouping_type"] == "GROUP_BASED"
    assert cfg["anchor_column_id"] == "Customer Name"
    assert cfg["combine_non_group_values"] is True
    assert cfg["null_output_value"] == "out"
    group = cfg["groups"][0]
    assert group["name"] == "in"
    assert group["combine_type"] == "ANY"
    assert group["conditions"] == [{
        "operator": "EQ", "column_name": "Customer Name",
        "value": ["Aaron Bergman", "Aaron Hawkins"], "filter_value_type": "STRING",
    }]
    # worksheet: binding, NOT model:
    assert cohort["worksheet"] == {"id": MODEL, "name": MODEL, "obj_id": OBJ_ID}
    assert "model" not in cohort
    assert any("static set" in line for line in logs)


def test_static_set_no_obj_id_when_fresh_generate():
    """Fresh GENERATE-mode build (no existing model yet) omits obj_id — same
    documented precedent as a fresh model_tables[] cross-reference."""
    spec = {
        "name": "State Set", "set_type": "static",
        "anchor_name": "State", "anchor_datatype": "string",
        "members": ["New York", "Ohio"],
    }
    tml, _logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml["cohort"]["worksheet"] == {"id": MODEL, "name": MODEL}


def test_static_set_null_member_included_adds_second_condition():
    spec = {
        "name": "01. Category Set", "set_type": "static",
        "anchor_name": "Category", "anchor_datatype": "string",
        "members": ["Furniture", "%null%"],
    }
    tml, _logs = build_cohort_tml(spec, model_name=MODEL, model_obj_id=OBJ_ID)
    conditions = tml["cohort"]["config"]["groups"][0]["conditions"]
    assert conditions == [
        {"operator": "EQ", "column_name": "Category", "value": ["Furniture"], "filter_value_type": "STRING"},
        {"operator": "EQ", "column_name": "Category", "value": ["{Null}"], "filter_value_type": "STRING"},
    ]
    assert tml["cohort"]["config"]["groups"][0]["combine_type"] == "ANY"


def test_static_set_numeric_calc_anchor_uses_double():
    spec = {
        "name": "Year Set", "set_type": "static",
        "anchor_name": "Year", "anchor_datatype": "integer", "anchor_is_calc": True,
        "members": ["2018"],
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL, model_obj_id=OBJ_ID)
    cond = tml["cohort"]["config"]["groups"][0]["conditions"][0]
    assert cond == {"operator": "EQ", "column_name": "Year", "value": [2018], "filter_value_type": "DOUBLE"}
    assert any("formula column" in line for line in logs)


def test_static_set_no_anchor_omitted():
    spec = {"name": "Broken", "set_type": "static", "members": ["A"]}
    tml, logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml is None
    assert "omitted" in logs[0]


def test_static_set_no_members_omitted():
    spec = {"name": "Empty", "set_type": "static", "anchor_name": "Category", "members": []}
    tml, logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml is None
    assert "omitted" in logs[0]


# ---------------------------------------------------------------------------
# except of a member list (translatable via NE)
# ---------------------------------------------------------------------------

def test_except_members_uses_ne_and_combine_all():
    spec = {
        "name": "Category Set", "set_type": "except_members",
        "anchor_name": "Category", "anchor_datatype": "string",
        "members": ["Furniture", "%null%"],
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL, model_obj_id=OBJ_ID)
    cfg = tml["cohort"]["config"]
    assert cfg["cohort_type"] == "SIMPLE"
    assert cfg["cohort_grouping_type"] == "GROUP_BASED"
    group = cfg["groups"][0]
    assert group["combine_type"] == "ALL"
    # One NE condition per excluded value; %null% needs no condition (catch-all).
    assert group["conditions"] == [
        {"operator": "NE", "column_name": "Category", "value": ["Furniture"], "filter_value_type": "STRING"},
    ]
    assert any("except-of-member-list" in line for line in logs)


def test_except_members_all_null_omitted():
    spec = {
        "name": "AllNull", "set_type": "except_members",
        "anchor_name": "Category", "members": ["%null%"],
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml is None
    assert "omitted" in logs[0]


# ---------------------------------------------------------------------------
# intersect of two member lists (Phase 2c)
# ---------------------------------------------------------------------------

def test_intersect_members_group_based_eq():
    spec = {
        "name": "Region Intersect", "set_type": "intersect_members",
        "anchor_name": "State", "anchor_datatype": "string",
        "members": ["Ohio", "Texas"], "side_member_counts": [3, 3],
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL, model_obj_id=OBJ_ID)
    cfg = tml["cohort"]["config"]
    assert cfg["cohort_grouping_type"] == "GROUP_BASED"
    assert cfg["groups"][0]["combine_type"] == "ANY"
    assert cfg["groups"][0]["conditions"] == [
        {"operator": "EQ", "column_name": "State", "value": ["Ohio", "Texas"], "filter_value_type": "STRING"},
    ]
    assert any("intersect" in line and "4 common" not in line for line in logs)
    assert any("2 common members" in line for line in logs)


def test_intersect_members_empty_omitted():
    spec = {"name": "No Overlap", "set_type": "intersect_members", "anchor_name": "State", "members": []}
    tml, logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml is None
    assert "zero common members" in logs[0]


# ---------------------------------------------------------------------------
# Top-N / Bottom-N (Phase 2b) — static (literal N) form
# ---------------------------------------------------------------------------

def test_topn_static_literal_n_keyword_search_no_formulas():
    spec = {
        "name": "Static Top 10", "set_type": "topn",
        "anchor_name": "Customer State", "topn_direction": "top",
        "topn_count_literal": 10, "order_expr": "SUM([Amount])",
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL, model_obj_id=OBJ_ID)
    cohort = tml["cohort"]
    assert cohort["name"] == "Static Top 10"
    answer = cohort["answer"]
    assert "formulas" not in answer
    assert "table_paths" not in answer
    assert answer["search_query"] == "top 10 [Customer State] [Amount]"
    assert answer["answer_columns"] == [{"name": "Customer State"}, {"name": "Total Amount"}]
    assert answer["table"]["table_columns"] == [
        {"column_id": "Customer State", "show_headline": False},
        {"column_id": "Total Amount", "show_headline": False},
    ]
    assert answer["table"]["ordered_column_ids"] == ["Customer State", "Total Amount"]
    assert answer["table"]["client_state"] == ""
    assert answer["display_mode"] == "TABLE_MODE"
    cfg = cohort["config"]
    assert cfg == {
        "cohort_type": "ADVANCED",
        "anchor_column_id": "Customer State",
        "return_column_id": "Customer State",
        "cohort_grouping_type": "COLUMN_BASED",
        "hide_excluded_query_values": False,
        "group_excluded_query_values": "Others",
        "pass_thru_filter": {"accept_all": False},
    }
    assert cohort["worksheet"] == {"id": MODEL, "name": MODEL, "obj_id": OBJ_ID}
    assert any("Top-N" in line for line in logs)


def test_topn_static_bottom_n_keyword():
    spec = {
        "name": "Static Bottom 5", "set_type": "topn",
        "anchor_name": "State", "topn_direction": "bottom",
        "topn_count_literal": 5, "order_expr": "SUM([Sales])",
    }
    tml, _logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml["cohort"]["answer"]["search_query"] == "bottom 5 [State] [Sales]"


# ---------------------------------------------------------------------------
# Top-N / Bottom-N (Phase 2b) — dynamic (parameter-driven N) form
# ---------------------------------------------------------------------------

def test_topn_dynamic_parameter_driven_rank_and_filter_formulas():
    spec = {
        "name": "State Top N", "set_type": "topn",
        "anchor_name": "State", "topn_direction": "top",
        "topn_count_param": "[Parameters].[topN]", "order_expr": "SUM([gallons])",
    }
    tml, logs = build_cohort_tml(
        spec, model_name=MODEL, model_obj_id=OBJ_ID,
        param_display_name_map={"[Parameters].[topN]": "topN"},
    )
    cohort = tml["cohort"]
    answer = cohort["answer"]
    assert answer["tables"] == [{"id": MODEL, "name": MODEL, "obj_id": OBJ_ID}]
    assert answer["table_paths"] == [{"id": f"{MODEL}_1", "table": MODEL}]
    formulas = {f["id"]: f for f in answer["formulas"]}
    assert formulas["formula_filter"]["expr"] == f"[formula_rank] <= [{MODEL}_1::topN] "
    assert formulas["formula_filter"]["was_auto_generated"] is False
    assert formulas["formula_rank"]["expr"] == f"rank ( sum ( [{MODEL}_1::gallons] ) , 'desc' )"
    assert formulas["formula_rank"]["properties"] == {"column_type": "ATTRIBUTE"}
    assert [f["id"] for f in answer["formulas"]] == ["formula_filter", "formula_rank"]
    assert answer["search_query"] == "[gallons] [State] [formula_rank] [formula_filter] = true"
    assert answer["answer_columns"] == [
        {"name": "State"}, {"name": "Total gallons"}, {"name": "rank"},
    ]
    assert answer["table"]["ordered_column_ids"] == ["State", "rank", "Total gallons"]
    assert answer["table"]["table_columns"] == [
        {"column_id": "State", "show_headline": False},
        {"column_id": "Total gallons", "show_headline": False},
        {"column_id": "rank", "show_headline": False},
    ]
    cfg = cohort["config"]
    assert cfg["hide_excluded_query_values"] is True
    assert cfg["group_excluded_query_values"] == "Excluded values"
    assert cfg["cohort_grouping_type"] == "COLUMN_BASED"
    assert cfg["cohort_type"] == "ADVANCED"
    assert any("parameter-filter" in line for line in logs)


def test_topn_bottom_n_dynamic_uses_asc_rank():
    spec = {
        "name": "State Bottom N", "set_type": "topn",
        "anchor_name": "State", "topn_direction": "bottom",
        "topn_count_param": "[Parameters].[topN]", "order_expr": "SUM([gallons])",
    }
    tml, _logs = build_cohort_tml(spec, model_name=MODEL, param_display_name_map={"[Parameters].[topN]": "topN"})
    rank = next(f for f in tml["cohort"]["answer"]["formulas"] if f["id"] == "formula_rank")
    assert "'asc'" in rank["expr"]


def test_topn_dropped_nuance_flagged():
    spec = {
        "name": "Weird Top N", "set_type": "topn",
        "anchor_name": "State", "topn_direction": "top",
        "topn_count_literal": 10,
        "order_expr": "IF [Flag] THEN SUM([Sales]) END",
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml is not None
    assert any("Dropped null-padding" in line for line in logs)


def test_topn_missing_anchor_omitted():
    spec = {"name": "Bad", "set_type": "topn", "topn_count_literal": 5, "order_expr": "SUM([Sales])"}
    tml, logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml is None
    assert "omitted" in logs[0]


# ---------------------------------------------------------------------------
# all-except-Top-N (Phase 2c — inverted rank)
# ---------------------------------------------------------------------------

def test_except_topn_inverted_rank_filter_literal_n():
    spec = {
        "name": "State NotTopN", "set_type": "except_topn",
        "anchor_name": "State", "topn_direction": "top",
        "topn_count_literal": 10, "order_expr": "SUM([Sales])",
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL, model_obj_id=OBJ_ID)
    formulas = {f["id"]: f for f in tml["cohort"]["answer"]["formulas"]}
    assert formulas["formula_filter"]["expr"] == "[formula_rank] > 10 "
    assert formulas["formula_rank"]["expr"] == f"rank ( sum ( [{MODEL}_1::Sales] ) , 'desc' )"
    assert any("inverted rank" in line for line in logs)


def test_except_topn_inverted_rank_filter_param_n():
    spec = {
        "name": "State NotTopN Param", "set_type": "except_topn",
        "anchor_name": "State", "topn_direction": "top",
        "topn_count_param": "[Parameters].[topN]", "order_expr": "SUM([Sales])",
    }
    tml, _logs = build_cohort_tml(spec, model_name=MODEL, param_display_name_map={"[Parameters].[topN]": "topN"})
    formulas = {f["id"]: f for f in tml["cohort"]["answer"]["formulas"]}
    assert formulas["formula_filter"]["expr"] == f"[formula_rank] > [{MODEL}_1::topN] "


# ---------------------------------------------------------------------------
# condition-based (Phase 2c)
# ---------------------------------------------------------------------------

def test_condition_based_set_query_set_with_boolean_formula():
    spec = {
        "name": "HighRevCustomers", "set_type": "condition",
        "anchor_name": "Customer Name", "condition_expr": "SUM([Sales]) > 10000",
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL, model_obj_id=OBJ_ID)
    cohort = tml["cohort"]
    answer = cohort["answer"]
    formula = answer["formulas"][0]
    assert formula["id"] == "formula_condition"
    assert formula["expr"] == "sum ( [Sales] ) > 10000"
    assert formula["properties"] == {"column_type": "ATTRIBUTE"}
    assert answer["search_query"] == "[Sales] [Customer Name] [formula_condition] [formula_condition] = true"
    cfg = cohort["config"]
    assert cfg["cohort_type"] == "ADVANCED"
    assert cfg["cohort_grouping_type"] == "COLUMN_BASED"
    assert any("condition-based set" in line for line in logs)


def test_condition_unparsable_expression_omitted():
    spec = {
        "name": "Weird", "set_type": "condition",
        "anchor_name": "Customer Name", "condition_expr": "not a real condition",
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml is None
    assert "omitted" in logs[0]


# ---------------------------------------------------------------------------
# mixed computed set operations (Phase 2c — multi-formula query set)
# ---------------------------------------------------------------------------

def test_mixed_intersect_member_list_and_topn_worked_example():
    """Reproduces the doc's "East Top Revenue" worked example structurally."""
    spec = {
        "name": "East Top Revenue", "set_type": "mixed", "mixed_op": "intersect",
        "anchor_name": "State",
        "sides": [
            {"kind": "members", "members": ["NY", "CA", "TX"]},
            {"kind": "topn", "topn_direction": "top", "topn_count_literal": 10,
             "order_expr": "SUM([Revenue])"},
        ],
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL)
    answer = tml["cohort"]["answer"]
    formula_ids = [f["id"] for f in answer["formulas"]]
    assert formula_ids == ["formula_members_0", "formula_rank_1", "formula_topn_1"]
    members_formula = answer["formulas"][0]
    assert members_formula["expr"] == (
        f"[{MODEL}_1::State] = 'NY' or [{MODEL}_1::State] = 'CA' or [{MODEL}_1::State] = 'TX'"
    )
    topn_formula = next(f for f in answer["formulas"] if f["id"] == "formula_topn_1")
    assert topn_formula["expr"] == "[formula_rank_1] <= 10"
    # Intersect => both sides "= true".
    assert "[formula_members_0] = true" in answer["search_query"]
    assert "[formula_topn_1] = true" in answer["search_query"]
    assert tml["cohort"]["config"]["cohort_type"] == "ADVANCED"
    assert any("computed set operation" in line for line in logs)


def test_mixed_except_member_list_minus_topn_inverts_and_stays_true():
    spec = {
        "name": "East Not Top 10", "set_type": "mixed", "mixed_op": "except",
        "anchor_name": "State",
        "sides": [
            {"kind": "members", "members": ["NY", "CA"]},
            {"kind": "topn", "topn_direction": "top", "topn_count_literal": 10,
             "order_expr": "SUM([Revenue])"},
        ],
    }
    tml, _logs = build_cohort_tml(spec, model_name=MODEL)
    answer = tml["cohort"]["answer"]
    topn_formula = next(f for f in answer["formulas"] if f["id"] == "formula_topn_1")
    # Except + Top-N exclusion => invert the comparator, but still "= true".
    assert topn_formula["expr"] == "[formula_rank_1] > 10"
    assert "[formula_topn_1] = true" in answer["search_query"]
    assert "[formula_members_0] = true" in answer["search_query"]


def test_mixed_except_two_non_topn_sides_uses_false_for_second():
    spec = {
        "name": "A minus B", "set_type": "mixed", "mixed_op": "except",
        "anchor_name": "Customer Name",
        "sides": [
            {"kind": "members", "members": ["Aaron Bergman"]},
            {"kind": "condition", "condition_expr": "SUM([Sales]) > 1000"},
        ],
    }
    tml, _logs = build_cohort_tml(spec, model_name=MODEL)
    answer = tml["cohort"]["answer"]
    assert "[formula_members_0] = true" in answer["search_query"]
    assert "[formula_cond_1] = false" in answer["search_query"]


def test_mixed_nested_side_flagged_not_converted():
    spec = {
        "name": "Deeply Nested", "set_type": "mixed", "mixed_op": "intersect",
        "anchor_name": "State", "sides": [{"kind": "members", "members": ["NY"]}, None],
    }
    tml, logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml is None
    assert "flag for review" in logs[0]


# ---------------------------------------------------------------------------
# Set Control (dynamic, no fixed members — untranslatable, drop the scaffolding)
# ---------------------------------------------------------------------------

def test_set_control_no_cohort_emitted():
    spec = {"name": "01. Month Set", "set_type": "set_control", "anchor_name": "01. Month"}
    tml, logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml is None
    assert "dynamic Set Control" in logs[0]
    assert "01. Month" in logs[0]


def test_unclassified_omitted():
    spec = {"name": "???", "set_type": "unclassified"}
    tml, logs = build_cohort_tml(spec, model_name=MODEL)
    assert tml is None
    assert "unrecognized structure" in logs[0]


# ---------------------------------------------------------------------------
# classify_sets (BL-088 audit classification) — exactly the 3 documented tiers
# ---------------------------------------------------------------------------

def test_classify_sets_three_tiers_match_audit_report():
    sets = [
        {"name": "A", "set_type": "static", "members": ["x"]},
        {"name": "B", "set_type": "except_members", "members": ["y"]},
        {"name": "C", "set_type": "intersect_members", "members": ["z"]},
        {"name": "D", "set_type": "intersect_members", "members": []},
        {"name": "E", "set_type": "topn"},
        {"name": "F", "set_type": "except_topn"},
        {"name": "G", "set_type": "condition"},
        {"name": "H", "set_type": "mixed"},
        {"name": "I", "set_type": "set_control"},
        {"name": "J", "set_type": "unclassified"},
    ]
    result = classify_sets(sets)
    assert result["tier_counts"] == {"column_set": 3, "query_set": 4, "deferred": 3}
    by_name = {s["name"]: s["tier"] for s in result["sets"]}
    assert by_name["A"] == "column_set"
    assert by_name["D"] == "deferred"  # empty intersect can't emit either
    assert by_name["I"] == "deferred"


def test_classify_sets_empty_list():
    assert classify_sets([]) == {"sets": [], "tier_counts": {"column_set": 0, "query_set": 0, "deferred": 0}}
