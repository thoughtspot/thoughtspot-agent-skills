"""Data Cache readiness, P19-P22: the derived fields they fire on, their edges, and the
rules over them (the catalog examples cover one fires / one silent case each).

ThoughtSpot's Data Cache cannot serve a Model with a custom calendar (P19), a SQL
pass-through formula (P20) or a semantic query measure (P21); a connection defining
custom calendars warns (P22). Rules confirmed by the product owner, 2026-11-18.
"""
from __future__ import annotations

import pytest

import audit_rule_fixtures as fx
from ts_cli.audit.catalog_model import load_catalog
from ts_cli.audit.engine import fields, scopes
from ts_cli.audit.engine.fields_data_cache import (
    CODE, CUSTOM, calendar_kind, calls_sql_passthrough, column_calendars,
    connection_calendars, is_semantic_measure, model_connections,
)
from ts_cli.audit.engine.run import run_rule

CAT = load_catalog()


def _item(ctx):
    return next(scopes.iterate(ctx, "model"))


def _field(ctx, name):
    return list(fields.get(_item(ctx), name, ctx))


def _findings(ctx, rule_id, profile="general"):
    return run_rule(ctx, CAT, rule_id, profile)


col, cal = fx.build_cache_column, fx.build_cache_calendar


# ── P19: which calendars are custom ─────────────────────────────────────────

@pytest.mark.parametrize("value, kind", [
    (None, None), ("", None), ("   ", None), ({}, None), ([], None),
    ("calendar", CODE), (" Calendar ", CODE), ("FISCAL", CODE), ("fiscal", CODE),
    ("default", CODE), (" DEFAULT ", CODE),
    ("Retail 445", CUSTOM), ("calendars", CUSTOM), ("fiscal year", CUSTOM),
    ("default calendar", CUSTOM), ("CALENDAR_TYPE_GREGORIAN", CUSTOM), (2024, CUSTOM),
])
def test_calendar_kind(value, kind):
    assert calendar_kind(value) == kind


def test_the_model_columns_value_wins_and_a_blank_one_falls_back_to_the_table():
    ctx = fx.build_cache_ctx(
        model_columns=[col("A", "ORDERS::A", calendar="calendar"),
                       col("B", "ORDERS::B", calendar=""),
                       col("C", "ORDERS::C"),
                       col("D", "ORDERS::D")],
        table_columns=[{"name": "A", "properties": {"calendar": "Retail"}},
                       {"name": "B", "properties": {"calendar": "Retail"}},
                       {"name": "C", "properties": {"calendar": " Fiscal "}}])
    doc = ctx.models[0]
    assert column_calendars(doc, ctx) == [
        {"column": "A", "calendar": "calendar", "kind": CODE, "set_on": "model"},
        {"column": "B", "calendar": "Retail", "kind": CUSTOM, "set_on": "table"},
        {"column": "C", "calendar": "Fiscal", "kind": CODE, "set_on": "table"}]
    assert _field(ctx, "@custom_calendar_columns") == ["B (Retail)"]


def test_a_table_column_is_found_through_the_model_tables_alias():
    ctx = fx.build_cache_ctx(alias="O",
                             model_columns=[col("Day", "O::DAY"), col("Raw", "ORDERS::DAY")],
                             table_columns=[{"name": "DAY", "properties": {"calendar": "R"}}])
    assert _field(ctx, "@custom_calendar_columns") == ["Day (R)"]


def test_a_formula_column_and_a_table_out_of_scope_read_only_their_own_calendar():
    ctx = fx.build_cache_ctx(model_columns=[
        {"name": "Fiscal Day", "formula_id": "formula_X", "properties": {"calendar": "R2"}},
        col("Ghost", "ELSEWHERE::DAY")])
    assert _field(ctx, "@custom_calendar_columns") == ["Fiscal Day (R2)"]


def test_p19_lists_every_custom_calendar_column():
    [f] = _findings(fx.perf_custom_calendar_columns(), "P19")
    assert f.severity == "MEDIUM" and f.object_name == "Cache Sales"
    assert f.detail == ("Can't use Data Cache: columns on a custom calendar: "
                        "Order Date (Retail 445), Ship Date (Fiscal 4-4-5)")


# ── P20: SQL pass-through calls ─────────────────────────────────────────────

@pytest.mark.parametrize("expr, calls", [
    ("sql_string_op ( \"upper({0})\" , [T::C] )", True),
    ("SQL_INT_OP(\"{0}\", [T::C])", True),
    ("sql_date_time_op ( \"x\" , [T::D] )", True),
    ("sum ( sql_double_aggregate_op ( \"median({0})\" , [T::A] ) )", True),
    ("if ( [T::A] > 0 ) then sql_bool_op ( \"{0}\" , [T::B] ) else false", True),
    ("'sql_int_op ( 1 )'", False),
    ("\"sql_int_op(1)\"", False),
    ("[T::sql_int_op ( x )]", False),
    ("[Bob's sql_int_op (]", False),
    ("my_sql_int_op ( 1 )", False),
    ("sql_int_opx ( 1 )", False),
    ("sql_int_op", False),
    (None, False), (12, False),
])
def test_calls_sql_passthrough(expr, calls):
    assert calls_sql_passthrough(expr) is calls


def test_p20_lists_formulas_by_name_else_id():
    ctx = fx.build_cache_ctx(formulas=[
        {"id": "formula_X", "expr": "sql_int_op ( \"1\" )"},
        {"id": "formula_Y", "name": "Y", "expr": "sql_string_op ( \"a\" )"},
        "not a formula"])
    assert _field(ctx, "@sql_passthrough_formulas") == ["formula_X", "Y"]
    [f] = _findings(fx.perf_sql_passthrough_formulas(), "P20")
    assert f.detail.endswith("formulas call a SQL pass-through function: Upper Name, Median")


# ── P21: semantic query measures ────────────────────────────────────────────

@pytest.mark.parametrize("own, table, semantic", [
    ({"aggregation": "AGGREGATE"}, {}, True),
    ({"aggregation": " aggregate "}, {}, True),
    ({"aggregation": "SUM"}, {"aggregation": "Aggregate"}, True),
    ({"aggregation": "SUM"}, {"is_pre_aggregated_measure": True}, True),
    ({}, {"is_pre_aggregated_measure": "true"}, False),
    ({}, {"is_pre_aggregated_measure": False}, False),
    ({"aggregation": "SUM"}, {"aggregation": "SUM"}, False),
    ({"aggregation": "AGGREGATES"}, {}, False),
    ({"aggregation": None}, {}, False),
])
def test_is_semantic_measure(own, table, semantic):
    assert is_semantic_measure({"properties": own}, {"properties": table}) is semantic


def test_p21_lists_the_semantic_measures():
    [f] = _findings(fx.perf_semantic_query_measures(), "P21")
    assert f.severity == "MEDIUM" and f.detail.endswith("aggregates: Revenue, Margin")


def test_malformed_properties_read_as_absent():
    ctx = fx.build_cache_ctx(model_columns=[
        {"name": "A", "column_id": "ORDERS::A", "properties": ["aggregation", "AGGREGATE"]},
        {"name": "B", "column_id": "ORDERS::B", "properties": "calendar: Retail"}])
    assert _field(ctx, "@semantic_query_measures") == []
    assert _field(ctx, "@custom_calendar_columns") == []


# ── P22: connections defining custom calendars ──────────────────────────────

def test_calendars_match_a_connection_by_name_in_any_case():
    ctx = fx.perf_connection_custom_calendars()
    assert connection_calendars(ctx.models[0], ctx) == [
        {"connection": "Warehouse A", "calendars": ["Fiscal 52", "Retail 445"]}]
    [f] = _findings(ctx, "P22")
    assert f.severity == "LOW" and f.detail.endswith("Warehouse A (2 custom calendars)")


def test_calendars_match_by_the_metadata_headers_connection_id():
    ctx = fx.build_cache_ctx(connection="Renamed Since", calendars=[cal("R", "Old Name", "conn-a")])
    ctx.metadata = [{"metadata_header": {"id": fx.CACHE_TABLE, "dataSourceId": "conn-a"}}]
    assert model_connections(ctx.models[0], ctx) == [{"name": "Renamed Since", "id": "conn-a"}]
    assert _field(ctx, "@connection_custom_calendars") == ["Renamed Since (1 custom calendar)"]


def test_a_table_with_no_connection_has_no_calendars():
    ctx = fx.build_cache_ctx(connection=None, calendars=[cal("R")])
    assert model_connections(ctx.models[0], ctx) == []
    assert connection_calendars(ctx.models[0], ctx) == []


def test_unfetched_calendars_are_unknown_and_p22_skips_the_model():
    ctx = fx.build_cache_ctx(calendars=None)
    assert connection_calendars(ctx.models[0], ctx) is None
    assert _field(ctx, "@connection_custom_calendars") == []
    rule = CAT.rules["P22"]
    assert "calendars" in rule.requires
    assert list(scopes.available(ctx, rule)) == []
    assert len(list(scopes.available(fx.build_cache_ctx(calendars=[]), rule))) == 1


def test_a_connection_is_listed_once_across_its_tables():
    ctx = fx.build_cache_ctx(calendars=[cal("R")])
    second = dict(ctx.tables[fx.CACHE_TABLE], guid="t-2")
    ctx.tables["t-2"] = second
    ctx.models[0]["model"]["model_tables"].append({"name": "ORDERS2", "fqn": "t-2"})
    assert model_connections(ctx.models[0], ctx) == [{"name": "Warehouse A", "id": None}]


# ── the rules ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rule_id, severity", [("P19", "MEDIUM"), ("P20", "MEDIUM"),
                                               ("P21", "MEDIUM"), ("P22", "LOW")])
def test_each_rule_is_a_fact_in_performance_graded_the_same_under_both_profiles(rule_id, severity):
    rule = CAT.rules[rule_id]
    assert rule.evidence == "fact" and rule.categories == ["P"] and rule.scope == "model"
    assert rule.aggregate["mode"] == "each"
    assert set(rule.aggregate["where"]) == {"field", "len_gt"}   # what data_cache.py reads
    for profile in CAT.profiles:
        assert rule.profiles.get(profile) is None
    assert rule.severity == severity
