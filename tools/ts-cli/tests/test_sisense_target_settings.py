"""--target-model: the Model's own query settings, overrides through the same checks as native
bindings, and the accounting gate. Pure functions on the synthetic "acme" fixture."""
import copy

from ts_cli.sisense import target_fields as _target_fields
from ts_cli.sisense.functions import AGG_FUNCTIONS
from ts_cli.sisense.target_answers import AGG_KEYWORD

from tests.test_sisense_target_answers import (TABLES, _answers, _f, _inv, _member, _exclude, _range, _row,
                                               _tables_for, _target, _w, build_target_liveboard)


def _cost_by_status(filters=()):
    return _w("w1", "Cost by status", "chart/column",
              [_f("[dim_case.status]", "categories"), _f("[fact_visit.cost]", "values", "measure", "sum")], filters)


def _kpi(filters=()):
    return _w("w2", "Cost", "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum")], filters)


def _model(target):
    return target["model"]


def _join(target, src, dest):
    return next(j for mt in _model(target)["model_tables"] if (mt.get("alias") or mt["name"]) == src
                for j in mt.get("joins") or [] if j["with"] == dest)


def _add_formula(target, name, expr, kind="MEASURE"):
    _model(target)["formulas"].append({"id": f"formula_{name}", "name": name, "expr": expr})
    _model(target)["columns"].append({"name": name, "formula_id": f"formula_{name}",
                                      "properties": {"column_type": kind}})


# --------------------------------------------------------------------------- Model-level settings
def test_model_filters_flag_every_tile():
    # review round 4, blocker 2: a Model filter applies to every query, Sisense applies none
    target = _target()
    _model(target)["filters"] = [{"column": ["Case Status"], "oper": "not in", "values": ["Test"]}]
    res = build_target_liveboard(_inv([_kpi()]), target)
    assert _row(res, "Cost")["status"] == "NEEDS REVIEW" and "Model-level filters" in _row(res, "Cost")["note"]
    assert _row(res, "(target model settings)")["status"] == "NEEDS REVIEW"
    assert _answers(res)["Cost"]["search_query"] == "sum [Visit Cost]"     # the tile is still built


def test_join_progressive_off_or_unset_flags_every_tile():
    for value in (False, None):
        target = _target()
        if value is None:
            del _model(target)["properties"]
        else:
            _model(target)["properties"]["join_progressive"] = value
        row = _row(build_target_liveboard(_inv([_kpi()]), target), "Cost")
        assert row["status"] == "NEEDS REVIEW" and "join_progressive" in row["note"]


def test_model_keys_this_converter_does_not_read_flag_every_tile():
    for key, value in (("constraints", {"constraint": [{"table": "fact_visit"}]}),
                       ("joins_with", [{"name": "x"}]), ("aggregated_models", [{"name": "agg"}]),
                       ("new_setting", 1)):
        target = _target()
        _model(target)[key] = value
        assert _row(build_target_liveboard(_inv([_kpi()]), target), "Cost")["status"] == "NEEDS REVIEW", key


def test_referencing_join_and_unknown_join_keys_are_reported():
    target = _target()
    _join(target, "fact_visit", "dim_case")["referencing_join"] = "fact_visit_to_dim_case"
    row = _row(build_target_liveboard(_inv([_kpi()]), target), "Cost")
    assert row["status"] == "NEEDS REVIEW" and "referencing_join" in row["note"]


def test_presentation_only_model_keys_change_nothing():
    target = _target()
    _model(target)["model_instructions"] = {"x": 1}
    _model(target)["properties"]["spotter_config"] = {"is_spotter_enabled": True}
    assert _row(build_target_liveboard(_inv([_kpi()]), target), "Cost")["status"] == "Migrated"


# --------------------------------------------------------------------------- join types
def test_a_left_outer_join_on_a_grouped_path_flags_the_tile():
    # review round 4, blocker 2: Sisense's default relation is INNER
    target = _target()
    _join(target, "fact_visit", "dim_case")["type"] = "LEFT_OUTER"
    res = build_target_liveboard(_inv([_cost_by_status(), _kpi()]), target)
    row = _row(res, "Cost by status")
    assert row["status"] == "NEEDS REVIEW" and "fact_visit > dim_case (LEFT_OUTER)" in row["note"]
    assert _row(res, "Cost")["status"] == "Migrated"            # no join on its path
    assert "INNER join" in _row(res, "(join types)")["note"]


def test_an_equality_filter_drops_nulls_as_inner_does_but_an_exclude_keeps_them():
    target = _target()
    _join(target, "fact_visit", "dim_case")["type"] = "LEFT_OUTER"
    kept = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), target)
    assert "join not INNER" not in (_row(kept, "Cost").get("note") or "")
    excluded = build_target_liveboard(_inv([_kpi([_exclude("[dim_case.status]", ["Test"])])]), target)
    assert "join not INNER" in _row(excluded, "Cost")["note"]


def test_join_with_no_type_is_not_assumed_inner():
    target = _target()
    del _join(target, "fact_visit", "dim_case")["type"]
    assert "no stated type" in _row(build_target_liveboard(_inv([_cost_by_status()]), target), "Cost by status")["note"]


def test_an_exclude_chip_over_a_left_outer_join_flags_its_tiles():
    target = _target()
    _join(target, "fact_visit", "dim_case")["type"] = "LEFT_OUTER"
    inv = _inv([_kpi()], dash_filters=[_exclude("[dim_case.status]", ["Test"])])
    assert "join not INNER" in _row(build_target_liveboard(inv, target), "Cost")["note"]
    inv = _inv([_kpi()], dash_filters=[_member("[dim_case.status]", ["Open"])])
    assert "join not INNER" not in (_row(build_target_liveboard(inv, target), "Cost").get("note") or "")


# --------------------------------------------------------------------------- column settings
def test_column_properties_that_change_aggregation_flag_the_tiles_reading_them():
    target = _target()
    cost = next(c for c in _model(target)["columns"] if c["name"] == "Visit Cost")
    cost["properties"]["is_additive"] = False
    res = build_target_liveboard(_inv([_kpi(), _w("w3", "Cases", "indicator",
                                                    [_f("[fact_visit.case_id_]", "value", "measure", "count")])]), target)
    assert "is_additive" in _row(res, "Cost")["note"] and _row(res, "Cases")["status"] == "Migrated"


def test_presentation_column_properties_change_nothing():
    target = _target()
    cost = next(c for c in _model(target)["columns"] if c["name"] == "Visit Cost")
    cost["properties"].update(synonyms=["spend"], ai_context="x", index_type="DONT_INDEX", format_pattern="#,##0")
    assert _row(build_target_liveboard(_inv([_kpi()]), target), "Cost")["status"] == "Migrated"


def test_a_formula_reading_a_parameter_is_flagged():
    target = _target()
    _model(target)["parameters"] = [{"name": "Rate", "data_type": "DOUBLE", "default_value": "1"}]
    _add_formula(target, "Weighted Cost", "sum ( [fact_visit::cost] * [Rate] )")
    inv = _inv([_kpi()])
    res = build_target_liveboard(inv, target, overrides={"field_map": {"[fact_visit.cost]": "Weighted Cost"}})
    assert "parameter [Rate]" in _row(res, "Cost")["note"]


# --------------------------------------------------------------------------- physical tables
def _with_physical(tables_physical, sis_physical):
    tables = copy.deepcopy(_tables_for(_target()))
    for t in tables:
        if t["table"]["name"] in tables_physical:
            t["table"].update(db_table=tables_physical[t["table"]["name"]])
    inv = _inv([_kpi()])
    inv["tables"] = [dict(t, physical=sis_physical.get(t["jaql_name"]), physical_problem=None) for t in TABLES]
    return inv, tables


def test_the_same_warehouse_table_is_carried_and_another_is_flagged():
    inv, tables = _with_physical({"fact_visit": "fact_visit"}, {"fact_visit": "acme.clinic.fact_visit"})
    assert _row(build_target_liveboard(inv, _target(), tables=tables), "Cost")["status"] == "Migrated"
    inv, tables = _with_physical({"fact_visit": "fact_visit_archive"}, {"fact_visit": "acme.clinic.fact_visit"})
    row = _row(build_target_liveboard(inv, _target(), tables=tables), "Cost")
    assert row["status"] == "NEEDS REVIEW" and "clinic.fact_visit_archive" in row["note"]


def test_a_custom_sql_table_on_either_side_is_flagged():
    inv, tables = _with_physical({}, {})
    inv["tables"] = [dict(t, physical=None, physical_problem="it is a custom table") if t["jaql_name"] == "fact_visit"
                     else t for t in inv["tables"]]
    assert "custom table" in _row(build_target_liveboard(inv, _target(), tables=tables), "Cost")["note"]
    inv, tables = _with_physical({}, {"fact_visit": "acme.clinic.fact_visit"})
    tables = [t for t in tables if t["table"]["name"] != "fact_visit"] + [
        {"sql_view": {"name": "fact_visit", "sql_view_columns": [{"name": "cost", "sql_output_column": "cost"}]}}]
    assert "SQL View" in _row(build_target_liveboard(inv, _target(), tables=tables), "Cost")["note"]


def test_a_dashboard_reading_another_data_model_flags_every_tile():
    inv = _inv([_kpi()])
    inv["datamodel_title"], inv["dashboard"]["datasource"] = "acme", "acme-old"
    assert "data source 'acme-old'" in _row(build_target_liveboard(inv, _target()), "Cost")["note"]


# --------------------------------------------------------------------------- overrides
def _two_counts():
    return _w("w1", "Counts", "pivot2", [_f("[dim_case.status]", "rows"),
                                         _f("[fact_visit.case_id_]", "values", "measure", "count"),
                                         _f("[fact_visit.case_id_]", "values", "measure", "countduplicates")])


def test_one_field_map_column_cannot_stand_for_two_aggregations():
    # review round 4, blocker 1: both counts collapsed onto one column, Migrated
    res = build_target_liveboard(_inv([_two_counts()]), _target(),
                                 overrides={"field_map": {"[fact_visit.case_id_]": "Visit Case Count"}})
    row = _row(res, "Counts")
    assert row["status"] == "NEEDS REVIEW" and "a unique count" in row["note"]


def test_field_map_keyed_by_aggregation_carries_both_counts():
    target = _target()
    _add_formula(target, "Visit Row Count", "count ( [fact_visit::case_id_] )")
    fmap = {"[fact_visit.case_id_]": {"count": "Visit Case Count", "countduplicates": "Visit Row Count"}}
    res = build_target_liveboard(_inv([_two_counts()]), target, overrides={"field_map": fmap})
    assert _answers(res)["Counts"]["search_query"] == "[Case Status] [Visit Case Count] [Visit Row Count]"
    assert _row(res, "Counts")["status"] == "Migrated"
    missing = build_target_liveboard(_inv([_two_counts()]), target,
                                     overrides={"field_map": {"[fact_visit.case_id_]": {"count": "Visit Case Count"}}})
    assert "no entry for countduplicates" in _row(missing, "Counts")["note"]


def test_a_mapped_calculated_column_keeps_its_aggregation_check():
    # review round 4, blocker 1: Sisense avg of a calculated column mapped onto a sum formula
    target = _target()
    _add_formula(target, "Margin", "sum ( [fact_visit::cost] )")
    inv = _inv([_w("w1", "Margin", "indicator", [_f("[fact_visit.Margin]", "value", "measure", "avg")])])
    inv["tables"] = [dict(t, calculated_columns=["Margin"]) if t["jaql_name"] == "fact_visit" else t
                     for t in inv["tables"]]
    res = build_target_liveboard(inv, target, overrides={"field_map": {"[fact_visit.Margin]": "Margin"}})
    row = _row(res, "Margin")
    assert row["status"] == "NEEDS REVIEW" and "which is a sum" in row["note"]


def test_a_grouped_field_mapped_onto_a_measure_is_refused():
    inv = _inv([_w("w1", "By cost", "chart/column", [_f("[fact_visit.cost]", "categories"),
                                                      _f("[fact_visit.case_id_]", "values", "measure", "count")])])
    res = build_target_liveboard(inv, _target(), overrides={"field_map": {"[fact_visit.cost]": "Visit Cost"}})
    assert "is a measure" in _row(res, "By cost")["note"]


def test_two_sisense_fields_bound_to_one_column_are_reported_even_with_equal_tokens():
    w = _w("w1", "Status", "chart/column", [_f("[dim_case.status]", "categories"), _f("[dim_case.state]", "break by"),
                                            _f("[fact_visit.cost]", "values", "measure", "sum")])
    res = build_target_liveboard(_inv([w]), _target(), overrides={"field_map": {"[dim_case.state]": "Case Status"}})
    assert "already shows for another Sisense field" in _row(res, "Status")["note"]


def test_filter_map_refuses_in_lists_and_date_values():
    # review round 4, blocker 1: `in (` passes column checks and search ignores it silently
    for frag in ("[Case Status] in ('Open', 'Pending')", "[Case Status] not in ('Test')",
                 "[Visit Start Date] = '2026-02-01'", "[Visit Start Date] >= '02/01/2026'",
                 "[Visit Start Date].'last 12 months'"):
        w = _kpi([_member("[dim_case.status]", ["Open"])])
        row = _row(build_target_liveboard(_inv([w]), _target(), overrides={"filter_map": {"[dim_case.status]": frag}}),
                   "Cost")
        assert row["status"] == "NEEDS REVIEW", frag
    ok = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), _target(),
                                overrides={"filter_map": {"[dim_case.status]": "[Case Status] = 'Open'"}})
    assert _answers(ok)["Cost"]["search_query"].endswith("[Case Status] = 'Open'")


def test_formula_fields_are_reported_not_offered_a_field_map():
    w = _w("w1", "Ratio", "indicator", [{"kind": "measure", "dim": None, "agg": None, "title": "Ratio",
                                         "formula": {"expression": "sum([a])/sum([b])", "context": {}},
                                         "level": None, "panel": "value"}])
    note = _row(build_target_liveboard(_inv([w]), _target()), "Ratio")["note"]
    assert "does not translate or map" in note and "via field_map" not in note


# --------------------------------------------------------------------------- accounting gate
def test_a_field_no_check_reported_is_still_named(monkeypatch):
    monkeypatch.setattr(_target_fields, "_add_field", lambda *a, **k: None)   # a silent path
    row = _row(build_target_liveboard(_inv([_kpi()]), _target()), "Cost")
    assert row["status"] == "NEEDS REVIEW" and "no check reported why" in row["note"]


def test_gauge_bounds_are_reported():
    w = _w("w1", "Gauge", "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum"),
                                        _f("[fact_visit.cost]", "max", "measure", "max")])
    assert "the gauge max" in _row(build_target_liveboard(_inv([w]), _target()), "Gauge")["note"]


# --------------------------------------------------------------------------- ranking, aggregations, counts
def test_top_n_goes_after_every_filter():
    # ThoughtSpot ranks the filtered rows wherever `top N` sits (live-verified, 26.11); last reads so too
    w = _w("w1", "Top statuses", "chart/bar", [_f("[dim_case.status]", "categories"),
                                               _f("[fact_visit.cost]", "values", "measure", "sum")],
           [_exclude("[dim_case.status]", ["Test"]),
            {"kind": "top_n", "dim": "[dim_case.status]", "operator": "top", "values": [5],
             "raw": {"top": 5, "by": {"dim": "[fact_visit.cost]", "agg": "sum"}}}])
    q = _answers(build_target_liveboard(_inv([w]), _target()))["Top statuses"]["search_query"]
    assert q == "[Case Status] sum [Visit Cost] [Case Status] != 'Test' top 5"


def test_aggregation_keywords_come_from_the_one_function_map():
    # review round 4, should-fix 3: dupcount was refused here while the function map has it
    assert set(AGG_KEYWORD) == set(AGG_FUNCTIONS) and AGG_KEYWORD["dupcount"] == "count"


def test_a_count_formula_binding_needs_the_tables_table_tml():
    # review round 4, nit: the count path skipped the partial-Table-export check
    tables = [t for t in _tables_for(_target()) if t["table"]["name"] != "fact_visit"]
    w = _w("w1", "Cases", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")])
    row = _row(build_target_liveboard(_inv([w]), _target(), tables=tables), "Cases")
    assert row["status"] == "NEEDS REVIEW" and "Table TML for fact_visit was not supplied" in row["note"]


# --------------------------------------------------------------------------- self-review of round 4's fixes
def test_filter_map_onto_a_model_measure_is_refused_as_the_native_filter_is():
    w = _cost_by_status([_range("[fact_visit.cost]", {"from": 100})])
    native = _row(build_target_liveboard(_inv([w]), _target()), "Cost by status")
    assert native["status"] == "NEEDS REVIEW" and "Model measure" in native["note"]
    mapped = build_target_liveboard(_inv([w]), _target(), overrides={"filter_map": {"[fact_visit.cost]": "[Visit Cost] >= 100"}})
    assert "a Model measure" in _row(mapped, "Cost by status")["note"]


def test_field_map_onto_a_non_fact_measure_keeps_the_fan_out_check():
    target = _target()
    _model(target)["columns"].append({"name": "Case Score", "column_id": "dim_case::score",
                                      "properties": {"column_type": "MEASURE", "aggregation": "SUM"}})
    w = _w("w1", "Score", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="months"),
                                         _f("[dim_case.score]", "values", "measure", "sum")])
    res = build_target_liveboard(_inv([w]), target, overrides={"field_map": {"[dim_case.score]": "Case Score"}})
    assert "non-fact table" in _row(res, "Score")["note"]


def test_a_problem_follows_formula_references():
    target = _target()
    _model(target)["parameters"] = [{"name": "Cost Factor", "data_type": "DOUBLE", "default_value": "1"}]
    _add_formula(target, "Adj Cost Row", "[fact_visit::cost] * [Cost Factor]", kind="ATTRIBUTE")
    _add_formula(target, "Adj Cost", "sum ( [Adj Cost Row] )")
    res = build_target_liveboard(_inv([_kpi()]), target, overrides={"field_map": {"[fact_visit.cost]": "Adj Cost"}})
    assert "built on [Adj Cost Row]" in _row(res, "Cost")["note"]


def test_table_tml_is_allowlisted_too():
    for change in ({"rls_rules": {"rules": [{"name": "r", "expr": "[fv_1::site_id_] = 3"}]}},
                   {"dataset_id": "28ede9b627ab"}):
        tables = copy.deepcopy(_tables_for(_target()))
        next(t for t in tables if t["table"]["name"] == "fact_visit")["table"].update(change)
        row = _row(build_target_liveboard(_inv([_kpi()]), _target(), tables=tables), "Cost")
        assert row["status"] == "NEEDS REVIEW" and "Table fact_visit" in row["note"], change
    tables = copy.deepcopy(_tables_for(_target()))
    fact = next(t for t in tables if t["table"]["name"] == "fact_visit")["table"]
    fact["columns"][0]["properties"] = {"is_pre_aggregated_measure": True}
    assert "is_pre_aggregated_measure" in _row(build_target_liveboard(_inv([_kpi()]), _target(), tables=tables), "Cost")["note"]
    fact.update(joins_with=[{"name": "j"}], properties={"spotter_config": {"is_spotter_enabled": False}})
    del fact["columns"][0]["properties"]
    assert _row(build_target_liveboard(_inv([_kpi()]), _target(), tables=tables), "Cost")["status"] == "Migrated"


def test_model_bypassing_rls_flags_every_tile():
    target = _target()
    _model(target)["properties"]["is_bypass_rls"] = True
    assert "is_bypass_rls" in _row(build_target_liveboard(_inv([_kpi()]), target), "Cost")["note"]


def test_filter_map_is_read_only_as_column_op_value_terms():
    for frag in ("[Case Status] = 'Open' [Case ID]", "[Case Status] = 'Open' top 1",
                 "[Case Status] = 'Open' or [Case Status] = 'Closed'", "[Case Status] contains 'Op'",
                 "[Visit Start Date] last 30 days"):
        res = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), _target(),
                                     overrides={"filter_map": {"[dim_case.status]": frag}})
        assert _row(res, "Cost")["status"] == "NEEDS REVIEW", frag
    ok = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), _target(),
                                overrides={"filter_map": {"[dim_case.status]": "[Case Status] = 'O\\'Neil' [Case Status] = 'x'"}})
    assert "filter_map" not in (_row(ok, "Cost").get("note") or "")    # carried; only the text-matching row remains


def test_filter_map_on_a_date_column_is_refused_whatever_the_value_looks_like():
    tables = copy.deepcopy(_tables_for(_target()))
    for t in tables:
        for c in t["table"]["columns"]:
            if c["name"] == "date_day":
                c["db_column_properties"] = {"data_type": "DATE"}
    for frag in ("[Visit Start Date] >= '01-15-2024'", "[Visit Start Date] >= 'Jan 15 2024'"):
        res = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), _target(), tables=tables,
                                     overrides={"filter_map": {"[dim_case.status]": frag}})
        assert "date column" in _row(res, "Cost")["note"], frag


def test_right_and_full_outer_joins_matter_even_under_an_equality_filter():
    for kind in ("RIGHT_OUTER", "OUTER"):
        target = _target()
        _join(target, "fact_visit", "dim_case")["type"] = kind
        res = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), target)
        assert "join not INNER" in _row(res, "Cost")["note"], kind
        chip = build_target_liveboard(_inv([_kpi()], dash_filters=[_member("[dim_case.status]", ["Open"])]), target)
        assert "join not INNER" in _row(chip, "Cost")["note"], kind


def test_a_left_join_declared_from_the_dimension_side_keeps_the_dimension():
    # ONE_TO_MANY on dim_case -> fact_visit: read many -> one, so LEFT keeps dim_case rows (a RIGHT join)
    target = _target()
    fact = next(mt for mt in _model(target)["model_tables"] if mt["name"] == "fact_visit")
    j = next(j for j in fact["joins"] if j["with"] == "dim_case")
    fact["joins"].remove(j)
    dim = next(mt for mt in _model(target)["model_tables"] if mt["name"] == "dim_case")
    dim["joins"].append({"with": "fact_visit", "on": j.get("on", j.get(True)), "type": "LEFT_OUTER",
                         "cardinality": "ONE_TO_MANY"})
    res = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), target)
    assert "(RIGHT_OUTER)" in _row(res, "Cost")["note"]


def test_physical_compare_needs_a_schema_on_both_sides_and_compares_the_database():
    inv, tables = _with_physical({"fact_visit": "fact_visit"}, {"fact_visit": "fact_visit"})
    assert "cannot be compared" in _row(build_target_liveboard(inv, _target(), tables=tables), "Cost")["note"]
    inv, tables = _with_physical({"fact_visit": "fact_visit"}, {"fact_visit": "acme_dev.clinic.fact_visit"})
    assert "acme_dev" in _row(build_target_liveboard(inv, _target(), tables=tables), "Cost")["note"]
    inv, tables = _with_physical({"fact_visit": "fact_visit"}, {"fact_visit": "clinic.fact_visit"})
    assert "cannot be compared" in _row(build_target_liveboard(inv, _target(), tables=tables), "Cost")["note"]
    inv, tables = _with_physical({"fact_visit": "fact_visit"}, {"fact_visit": "acme.clinic.fact_visit"})
    assert _row(build_target_liveboard(inv, _target(), tables=tables), "Cost")["status"] == "Migrated"


def test_a_sisense_table_setting_not_read_flags_every_binding_to_it():
    inv = _inv([_kpi()])
    inv["tables"] = [dict(t, unsupported=["tupleTransformations[filter]"]) if t["jaql_name"] == "fact_visit" else t
                     for t in inv["tables"]]
    assert "tupleTransformations[filter]" in _row(build_target_liveboard(inv, _target()), "Cost")["note"]


def test_a_column_with_no_column_type_and_a_non_equality_join_are_flagged():
    target = _target()
    cost = next(c for c in _model(target)["columns"] if c["name"] == "Visit Cost")
    del cost["properties"]["column_type"]
    assert "column_type" in _row(build_target_liveboard(_inv([_kpi()]), target), "Cost")["note"]
    target = _target()
    j = _join(target, "fact_visit", "dim_case")
    j[True if True in j else "on"] = "[fact_visit::case_id_] >= [dim_case::id_]"
    assert "column-equals-column" in _row(build_target_liveboard(_inv([_kpi()]), target), "Cost")["note"]


# --------------------------------------------------------------------------- second self-review
def test_field_map_onto_a_non_fact_formula_measure_keeps_the_fan_out_check():
    target = _target()
    _model(target)["columns"].append({"name": "Case Cost", "column_id": "dim_case::cost",
                                      "properties": {"column_type": "MEASURE", "aggregation": "SUM"}})
    _add_formula(target, "Case Cost Sum", "sum ( [dim_case::cost] )")
    w = _w("w1", "Case cost", "chart/column", [_f("[dim_case.status]", "categories"),
                                               _f("[dim_case.cost]", "values", "measure", "sum"),
                                               _f("[fact_visit.case_id_]", "values", "measure", "count")])
    res = build_target_liveboard(_inv([w]), target, overrides={"field_map": {"[dim_case.cost]": "Case Cost Sum"}})
    assert "non-fact table" in _row(res, "Case cost")["note"]


def test_a_table_the_tile_only_joins_through_is_checked_too():
    # sum of fact_case_stats by Case Site: the path runs through dim_case, which no column is read from
    w = _w("w1", "By case site", "chart/column", [_f("[dim_site.name]", "categories"),
                                                  _f("[fact_case_stats.visit_total]", "values", "measure", "sum")])
    tables = copy.deepcopy(_tables_for(_target()))
    next(t for t in tables if t["table"]["name"] == "dim_case")["table"]["rls_rules"] = {"rules": [{"name": "r"}]}
    assert "Table dim_case" in (_row(build_target_liveboard(_inv([w]), _target(), tables=tables), "By case site").get("note") or "")
    inv = _inv([w])
    inv["tables"] = [dict(t, physical=None, physical_problem="its import query is more than `select * from <table>`")
                     if t["jaql_name"] == "dim_case" else t for t in inv["tables"]]
    assert "Sisense table dim_case" in (_row(build_target_liveboard(inv, _target()), "By case site").get("note") or "")


def test_a_formula_over_a_date_column_is_a_date_column_for_filter_map():
    target = _target()
    _add_formula(target, "Start Day F", "date ( [Visit Start Date::date_day] )", kind="ATTRIBUTE")
    tables = copy.deepcopy(_tables_for(target))
    for t in tables:
        for c in t["table"]["columns"]:
            if c["name"] == "date_day":
                c["db_column_properties"] = {"data_type": "DATE"}
    res = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), target, tables=tables,
                                 overrides={"filter_map": {"[dim_case.status]": "[Start Day F] = 'jan 2024'"}})
    assert "date column" in _row(res, "Cost")["note"]


def test_filter_map_values_and_operators_follow_the_native_rules():
    for frag in ("[Case Status] = 'N\\\\A'", "[Visit Cost] = 1.5", "[Case Status] = true",
                 "[Case Status] = 'a' [Case Status] != 'c'", "[Case ID] = 'a' [Case ID] >= 'b'"):
        res = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), _target(),
                                     overrides={"filter_map": {"[dim_case.status]": frag}})
        assert _row(res, "Cost")["status"] == "NEEDS REVIEW", frag
    ok = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), _target(),
                                overrides={"filter_map": {"[dim_case.status]": "[Case ID] >= 'a' [Case ID] < 'm'"}})
    assert _row(ok, "Cost")["status"] == "Migrated"


def test_a_range_bound_that_is_not_a_plain_number_is_refused():
    for raw in ({"from": 1e20}, {"from": "5"}, {"from": True}, {"to": float("inf")}):
        res = build_target_liveboard(_inv([_kpi([_range("[fact_case_stats.visit_total]", raw)])]), _target())
        assert "not a plain number" in _row(res, "Cost")["note"], raw


def test_true_and_false_are_carried_on_a_boolean_column_only():
    # [Visit Started?] is `if ( ... ) then true else false`; `= true` matches its true rows (live 26.11)
    ok = build_target_liveboard(_inv([_kpi([_member("[Visit_Start_Date.id_]", ["1"])])]), _target(),
                                overrides={"filter_map": {"[Visit_Start_Date.id_]": "[Visit Started?] = true"}})
    assert _row(ok, "Cost")["status"] == "Migrated", _row(ok, "Cost")
    off = build_target_liveboard(_inv([_kpi([_member("[Visit_Start_Date.id_]", ["1"])])]), _target(),
                                 overrides={"filter_map": {"[Visit_Start_Date.id_]": "[Case Status] = true"}})
    assert "not known to be a boolean" in _row(off, "Cost")["note"]


# --------------------------------------------------------------------------- third self-review
def test_a_chip_joining_through_a_checked_table_flags_its_tiles():
    # the chip on [dim_site.name] binds Case Site, joined from fact_case_stats through dim_case
    stats = _w("w9", "Stats", "indicator", [_f("[fact_case_stats.visit_total]", "value", "measure", "sum")])
    inv = _inv([stats], dash_filters=[_member("[dim_site.name]", ["North"])])
    tables = copy.deepcopy(_tables_for(_target()))
    next(t for t in tables if t["table"]["name"] == "dim_case")["table"]["rls_rules"] = {"rules": [{"name": "r"}]}
    res = build_target_liveboard(inv, _target(), tables=tables)
    assert res["liveboard"]["liveboard"]["filters"][0]["column"] == ["Case Site Name"]
    assert "Table dim_case" in _row(res, "Stats")["note"]
    inv["tables"] = [dict(t, physical=None, physical_problem="a custom import query") if t["jaql_name"] == "dim_case"
                     else t for t in inv["tables"]]
    assert "Sisense table dim_case" in _row(build_target_liveboard(inv, _target()), "Stats")["note"]


def test_a_tile_naming_no_fact_does_not_inherit_a_facts_settings():
    tables = copy.deepcopy(_tables_for(_target()))
    next(t for t in tables if t["table"]["name"] == "fact_case_stats")["table"]["rls_rules"] = {"rules": [{"name": "r"}]}
    w = _w("w1", "Statuses", "pivot2", [_f("[dim_case.status]", "rows")])
    assert _row(build_target_liveboard(_inv([w]), _target(), tables=tables), "Statuses")["status"] == "Migrated"


def test_a_formula_over_an_unexposed_date_column_is_a_date_column():
    target = _target()
    _add_formula(target, "Opened F", "date ( [dim_case::opened_on] )", kind="ATTRIBUTE")
    tables = copy.deepcopy(_tables_for(target))
    case = next(t for t in tables if t["table"]["name"] == "dim_case")["table"]
    case["columns"].append({"name": "opened_on", "db_column_name": "opened_on", "db_column_properties": {"data_type": "DATE"}})
    res = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), target, tables=tables,
                                 overrides={"filter_map": {"[dim_case.status]": "[Opened F] = 'jan 2024'"}})
    assert "date column" in _row(res, "Cost")["note"]


def test_only_the_verified_boolean_forms_are_carried():
    for frag, ok in (("[Visit Started?] = true", True), ("[Visit Started?] = false", True),
                     ("[Visit Started?] != true", True), ("[Visit Started?] != false", False),
                     ("[Visit Started?] >= true", False), ("[Visit Started?] = 1", False),
                     ("[Visit Started?] = 'true'", False)):
        res = build_target_liveboard(_inv([_kpi([_member("[Visit_Start_Date.id_]", ["1"])])]), _target(),
                                     overrides={"filter_map": {"[Visit_Start_Date.id_]": frag}})
        assert (_row(res, "Cost")["status"] == "Migrated") == ok, frag


def test_a_widget_naming_no_fact_is_checked_through_the_fact_linking_its_tables():
    # status and start date are linked only through fact_visit: its settings change the rows
    w = _w("w1", "Pairs", "pivot2", [_f("[dim_case.status]", "rows"), _f("[Visit_Start_Date.date_day]", "rows")])
    tables = copy.deepcopy(_tables_for(_target()))
    next(t for t in tables if t["table"]["name"] == "fact_visit")["table"]["rls_rules"] = {"rules": [{"name": "r"}]}
    assert "Table fact_visit" in (_row(build_target_liveboard(_inv([w]), _target(), tables=tables), "Pairs").get("note") or "")


def test_a_formula_using_a_date_function_is_a_date_column():
    target = _target()
    _add_formula(target, "F", "to_date ( [dim_case::status] , '%Y-%m-%d' )", kind="ATTRIBUTE")
    res = build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), target,
                                 overrides={"filter_map": {"[dim_case.status]": "[F] = 'jan 2024'"}})
    assert "date column" in _row(res, "Cost")["note"]


def test_boolean_terms_are_carried_as_verified_only_and_branch_parsing_stays_in_its_branch():
    res = build_target_liveboard(_inv([_kpi([_member("[Visit_Start_Date.id_]", ["1"])])]), _target(),
                                 overrides={"filter_map": {"[Visit_Start_Date.id_]": "[Visit Started?] = TRUE"}})
    assert _row(res, "Cost")["status"] == "NEEDS REVIEW"
    from ts_cli.sisense.target_settings import _boolean_formula
    assert not _boolean_formula("if ( [a] > 0 ) then 1 else if ( [b] ) then true else false")
    assert _boolean_formula("if ( [a] > 0 ) then true else if ( [b] < 2 ) then false else true")


def test_a_non_finite_data_limit_is_reported_not_raised():
    from ts_cli.sisense.allowlist import _data_limit_problems
    for v in (float("nan"), float("inf")):
        assert _data_limit_problems({"dataLimits": {"seriesCapacity": v}})


# --------------------------------------------------------------------------- review round 5
def _started(filters, title):
    return _w(title, title, "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum")], filters)


def test_filter_map_replaces_only_the_condition_it_states():
    dim = "[Visit_Start_Date.id_]"
    widgets = [_started([_member(dim, ["1"])], "Started"), _started([_member(dim, ["0"])], "Not started"),
               _started([dict(_member(dim, []), raw={"all": True})], "All visits"),
               _started([_exclude(dim, ["1", "2"])], "Excluded")]
    # one fragment for a dim filtered four ways: refused where it would replace another condition
    res = build_target_liveboard(_inv(widgets), _target(), overrides={"filter_map": {dim: "[Visit Started?] = true"}})
    assert "different conditions" in _row(res, "Started")["note"]
    assert "[Visit Started?]" not in _answers(res)["All visits"]["search_query"]       # `all` stays unfiltered
    keyed = [{"when": {"members": ["1"]}, "search": "[Visit Started?] = true"},
             {"when": {"members": ["0"]}, "search": "[Visit Started?] = false"}]
    res = build_target_liveboard(_inv(widgets), _target(), overrides={"filter_map": {dim: keyed}})
    answers = _answers(res)
    assert answers["Started"]["search_query"].endswith("[Visit Started?] = true")
    assert answers["Not started"]["search_query"].endswith("[Visit Started?] = false")
    assert "[Visit Started?]" not in answers["All visits"]["search_query"]
    assert "no entry for this condition" in _row(res, "Excluded")["note"]


def test_a_measure_at_a_date_level_is_refused():
    w = _w("w1", "Months", "indicator", [dict(_f("[Visit_Start_Date.date_day (Calendar)]", "value", "measure", "count"),
                                              level="months")])
    row = _row(build_target_liveboard(_inv([w]), _target()), "Months")
    assert row["status"] == "NEEDS REVIEW" and "level months" in row["note"]


def test_chips_are_checked_together_against_each_tile():
    # status and site chips together close the visit / case / site loop the tile does not name
    res = build_target_liveboard(_inv([_kpi()], dash_filters=[_exclude("[dim_case.status]", ["T"]),
                                                              _exclude("[dim_site.name]", ["T"])]), _target())
    assert "with its dashboard filters" in _row(res, "Cost")["note"]


def test_a_loop_closed_through_a_table_the_widget_does_not_name():
    from ts_cli.sisense.target_paths import loop_problem
    from tests.test_sisense_target_answers import _rel
    rels = [_rel("fact_visit", "case_id_", "dim_case", "id_"), _rel("fact_visit", "site_id_", "dim_site", "id_"),
            _rel("dim_case", "site_id_", "dim_site", "id_"), _rel("dim_case", "payer_id_", "dim_payer", "id_")]
    assert loop_problem(rels, {"dim_payer", "dim_site", "fact_visit"})


def test_a_dash_export_passed_as_the_bundle_is_read_as_the_dashboard():
    from ts_cli.sisense.parsing import parse_inventory
    dash = {"title": "D", "oid": "d1", "script": "dashboard.on('widgetbeforequery', f);", "filters": [],
            "widgets": [{"oid": "w1", "title": "Cost", "type": "indicator", "metadata": {"panels": []}}]}
    inv = parse_inventory(dash)
    assert inv["dashboard"]["title"] == "D" and "script" in inv["dashboard"]["unsupported"]


def test_a_bundle_without_a_data_model_flags_every_tile():
    inv = _inv([_kpi()])
    inv["tables"] = []
    res = build_target_liveboard(inv, _target())
    assert "no Sisense data model" in _row(res, "Cost")["note"]


def test_the_warehouse_connection_is_declared_or_reported():
    tables = copy.deepcopy(_tables_for(_target()))
    for t in tables:
        t["table"]["connection"] = {"name": "ts_wh"}
    inv = _inv([_kpi()])
    inv["connections"] = ["sisense_wh"]
    assert "same warehouse is not checked" in _row(build_target_liveboard(inv, _target(), tables=tables), "Cost")["note"]
    ok = build_target_liveboard(inv, _target(), tables=tables, overrides={"connections": {"sisense_wh": "ts_wh"}})
    assert "warehouse" not in (_row(ok, "Cost").get("note") or "")


def test_number_and_padded_text_filters_are_reported():
    target = _target()
    _model(target)["columns"].append({"name": "Visit Duration", "column_id": "fact_visit::duration",
                                      "properties": {"column_type": "ATTRIBUTE"}})
    tables = copy.deepcopy(_tables_for(target))
    fact = next(t for t in tables if t["table"]["name"] == "fact_visit")["table"]
    next(c for c in fact["columns"] if c["name"] == "duration")["db_column_properties"] = {"data_type": "INT64"}
    res = build_target_liveboard(_inv([_kpi([_exclude("[fact_visit.duration]", [0])])]), target, tables=tables)
    assert "filter value matching" in _row(res, "Cost")["note"]       # != keeps NULL rows (live 26.11)
    for vals in ([""], [" Open "]):
        assert "empty or space-padded" in _row(build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", vals)])]),
                                                                       _target()), "Cost")["note"]
    res = build_target_liveboard(_inv([_kpi([_member("[fact_visit.duration]", ["30"])])]), target, tables=tables)
    assert "text on a number column" in _row(res, "Cost")["note"]


def test_a_drill_narrowed_through_another_copy_is_needs_review():
    src = _w("w1", "Cost by Site", "chart/column", [_f("[dim_site.name]", "categories"),
                                                    _f("[fact_visit.cost]", "values", "measure", "sum")],
             drill_targets=["Detail"])
    detail = {"dashboard": {"title": "Detail", "filters": []},
              "widgets": [_w("d1", "Stats list", "tablewidget", [_f("[dim_site.name]", "columns"),
                                                                 _f("[fact_case_stats.visit_total]", "columns",
                                                                    "measure", "sum")])]}
    row = _row(build_target_liveboard(_inv([src]), _target(), drills=[detail]), "Stats list")
    assert row["status"] == "NEEDS REVIEW" and "would not narrow" in row["note"]


def test_filter_conditions_differing_in_level_count_or_unknown_keys_are_different():
    from ts_cli.sisense.target_filters import condition_key
    assert condition_key({"members": ["2024-01-01"]}, "years") != condition_key({"members": ["2024-01-01"]}, "months")
    assert condition_key({"last": {"count": 7, "offset": 0}}) != condition_key({"last": {"count": 30, "offset": 0}})
    assert condition_key({"contains": "a"}) != condition_key({"contains": "b"}) != condition_key({})
    assert condition_key({"members": ["1"], "explicit": True}) == condition_key({"members": [1]})
    dim = "[Visit_Start_Date.id_]"
    widgets = [_started([{"kind": "relative_date", "dim": dim, "operator": "last", "values": [7],
                          "raw": {"last": {"count": 7, "offset": 0}}}], "Week"),
               _started([{"kind": "relative_date", "dim": dim, "operator": "last", "values": [30],
                          "raw": {"last": {"count": 30, "offset": 0}}}], "Month")]
    res = build_target_liveboard(_inv(widgets), _target(), overrides={"filter_map": {dim: "[Visit Started?] = true"}})
    assert "different conditions" in _row(res, "Week")["note"]
    keyed = [{"when": {"last": {"count": 7, "offset": 0}}, "search": "[Visit Started?] = true"}]
    res = build_target_liveboard(_inv(widgets), _target(), overrides={"filter_map": {dim: keyed}})
    assert "no entry for this condition" in _row(res, "Month")["note"]


def test_a_no_fact_widget_joins_through_the_one_table_relating_all_its_tables():
    from ts_cli.sisense.target_paths import loop_problem
    from tests.test_sisense_target_answers import _rel
    rels = [_rel("f1", "a", "d1", "id"), _rel("f1", "b", "d2", "id"), _rel("f1", "c", "d3", "id"),
            _rel("f2", "b", "d2", "id"), _rel("f2", "c", "d3", "id")]
    assert not loop_problem(rels, {"d1", "d2", "d3"})


def test_widgets_in_the_dashboard_and_the_bundle_are_both_read():
    from ts_cli.sisense.parsing import parse_inventory
    a = {"oid": "w1", "title": "A", "type": "indicator", "metadata": {"panels": []}}
    b = {"oid": "w2", "title": "B", "type": "indicator", "metadata": {"panels": []}}
    inv = parse_inventory({"dashboard": {"title": "D", "filters": [], "widgets": [a, b]}, "widgets": [a]})
    assert [w["oid"] for w in inv["widgets"]] == ["w1", "w2"]
    assert parse_inventory({"title": "D", "oid": "d", "dashboard": "x", "widgets": [a]})["widgets"]


def test_declared_connections_must_be_the_ones_sisense_reads():
    tables = copy.deepcopy(_tables_for(_target()))
    for t in tables:
        t["table"]["connection"] = {"name": "Y" if t["table"]["name"] == "dim_case" else "X"}
    inv = _inv([_cost_by_status()])
    inv["connections"] = ["A"]
    res = build_target_liveboard(inv, _target(), tables=tables, overrides={"connections": {"A": "X", "Zbogus": "Y"}})
    assert "same warehouse is not checked" in _row(res, "Cost by status")["note"]


# --------------------------------------------------------------------------- review round 6
def test_filter_map_never_replaces_an_aggregate_filter_or_one_with_unread_keys():
    agg = dict(_range("[fact_visit.cost]", {"from": 100}), agg="sum")
    w = _cost_by_status([agg])
    res = build_target_liveboard(_inv([w]), _target(),
                                 overrides={"filter_map": {"[fact_visit.cost]": "[Case ID] >= 'a'"}})
    assert "filters an aggregate" in _row(res, "Cost by status")["note"]
    odd = dict(_member("[dim_case.status]", ["Open"]), unsupported=["explicit=False"])
    res = build_target_liveboard(_inv([_kpi([odd])]), _target(),
                                 overrides={"filter_map": {"[dim_case.status]": "[Case Status] = 'Open'"}})
    assert "does not read" in _row(res, "Cost")["note"]
    from ts_cli.sisense.target_filters import condition_key
    assert condition_key({"from": 100}, None, "sum") != condition_key({"from": 100})


def test_an_all_filter_is_never_replaced_by_filter_map():
    dim = "[Visit_Start_Date.id_]"
    widgets = [_started([_member(dim, ["1"])], "Started"),
               _started([dict(_member(dim, []), raw={"all": True})], "All visits")]
    res = build_target_liveboard(_inv(widgets), _target(), overrides={"filter_map": {dim: "[Visit Started?] = true"}})
    answers = _answers(res)
    assert answers["Started"]["search_query"].endswith("[Visit Started?] = true")
    assert "[Visit Started?]" not in answers["All visits"]["search_query"]


def test_a_filter_no_check_reported_is_still_named(monkeypatch):
    from ts_cli.sisense import target_answers as ta
    monkeypatch.setattr(ta._Binder, "filter_fragment", lambda self, sf, anchors: (None, None, ""))
    row = _row(build_target_liveboard(_inv([_kpi([_member("[dim_case.status]", ["Open"])])]), _target()), "Cost")
    assert "no check reported why" in row["note"]


def test_a_date_measure_with_no_level_is_flagged():
    w = _w("w1", "Dates", "indicator", [dict(_f("[Visit_Start_Date.date_day (Calendar)]", "value", "measure", "count"),
                                             datatype="datetime")])
    assert "carries no level" in _row(build_target_liveboard(_inv([w]), _target()), "Dates")["note"]


def test_a_hidden_tab_differing_in_a_measures_level_is_not_merged():
    from tests.test_sisense_target_answers import _w as w_
    date = "[Visit_Start_Date.date_day (Calendar)]"
    shown = w_("t1", "Visits (Daily)", "indicator", [_f(date, "value", "measure", "count")])
    hidden = w_("t2", "Visits (Monthly)", "indicator", [dict(_f(date, "value", "measure", "count"), level="months")])
    tabber = w_("tb", "Visits", "WidgetsTabber", [], tabber={"tabs": [{"title": "Daily", "show": ["t1"]},
                                                                      {"title": "Monthly", "show": ["t2"]}], "active": 0})
    res = build_target_liveboard(_inv([tabber, shown, hidden]), _target())
    row = next(r for r in res["visual_rows"] if r["visual"] == "Visits (Monthly)")
    assert row["status"] != "Merged"
