"""Data Cache readiness, P23-P28: what a Model is built on. The derived fields and their
edges; the catalog examples cover one fires / one silent case each.

ThoughtSpot's Data Cache cannot serve a Model on a source other than Snowflake or
Databricks (P23), on a connection using OAuth, PrivateLink or a template variable (P24),
on a parameterized Table (P25), with a parameter in a formula (P26), on a SQL View (P27),
or with an RLS rule reaching beyond its Table's own columns (P28). Product owner,
2026-11-18.
"""
from __future__ import annotations

import pytest

import audit_rule_fixtures as fx
from ts_cli.audit import run_audit
from ts_cli.audit.catalog_model import load_catalog
from ts_cli.audit.engine import fields, scopes
from ts_cli.audit.engine.fields_data_cache import model_connections, model_sources
from ts_cli.audit.engine.fields_data_cache_sources import (rls_rule_problems,
                                                           source_type_problem)
from ts_cli.audit.engine.run import run_rule

CAT = load_catalog()
header, conn = fx.build_cache_header, fx.build_cache_connection


def _field(ctx, name):
    return list(fields.get(next(scopes.iterate(ctx, "model")), name, ctx))


def _detail(ctx, rule_id):
    [f] = run_rule(ctx, CAT, rule_id, "general")
    return f.severity, f.detail


def _readiness(ctx):
    """The Model's Data Cache readiness and the checks not made for it, after a P run
    (its calendars searched, so P22 is judged)."""
    if ctx.calendars is None:
        ctx.calendars = []
    [model] = run_audit(None, [], ["P"], ctx=ctx)["corpus"]["models"]
    return model["data_cache"]["readiness"], model["data_cache"]["not_assessed"]


#: Facts for ORDERS' connection with every flag clear, and a Snowflake header for it.
CLEAN = [conn()]
SNOWFLAKE_HEADER = [header()]


# ── the Model's sources ─────────────────────────────────────────────────────

def test_sources_are_each_model_table_once_with_its_tml_and_header():
    ctx = fx.build_cache_ctx(sources=[{"name": "V", "fqn": "v1"}, {"name": "V again", "fqn": "v1"},
                                      {"name": "No fqn"}, "not a table"],
                             headers=[header("v1", "SQL_VIEW")])
    got = [(s["name"], s["fqn"], s["table"] is not None, s["header"].get("type"))
           for s in model_sources(ctx.models[0], ctx)]
    assert got == [("ORDERS", fx.CACHE_TABLE, True, None), ("V", "v1", False, "SQL_VIEW")]


def test_a_header_without_a_type_takes_its_rows_subtype():
    ctx = fx.build_cache_ctx(sources=[{"name": "V", "fqn": "v1"}])
    ctx.metadata = [{"metadata_subtype": "SQL_VIEW", "metadata_header": {"id": "v1"}}]
    assert _field(ctx, "@sql_view_sources") == ["V"]


def test_a_sql_views_connection_comes_from_its_header():
    ctx = fx.build_cache_ctx(sources=[{"name": "V", "fqn": "v1"}],
                             headers=[header("v1", "SQL_VIEW", connection="Warehouse B")])
    assert model_connections(ctx.models[0], ctx) == [{"name": "Warehouse A", "id": None},
                                                     {"name": "Warehouse B", "id": None}]


# ── P23: source types ───────────────────────────────────────────────────────

@pytest.mark.parametrize("table, kind, problem", [
    ({"name": "T", "connection": {"name": "C"}}, "RDBMS_SNOWFLAKE", ""),
    ({"name": "T", "connection": {"name": "C"}}, " rdbms_databricks ", ""),
    ({"name": "T", "connection": {"name": "C"}}, "DATABRICKS", ""),
    ({"name": "T", "connection": {"name": "C"}}, "snowflake", ""),
    ({"name": "T", "connection": {"name": "C"}}, "RDBMS_REDSHIFT", "RDBMS_REDSHIFT"),
    ({"name": "T", "connection": {"name": "C"}}, "DEFAULT", "DEFAULT"),
    ({"name": "T", "connection": {"name": "C"}}, None, None),
    ({"name": "T", "connection": {"name": "C"}}, "", None),
    ({"name": "T"}, "RDBMS_SNOWFLAKE", "no connection"),
    ({"name": "T", "connection": {}}, None, "no connection"),
    ({"name": "T", "connection": "C"}, None, "no connection"),
    (None, "RDBMS_POSTGRES", "RDBMS_POSTGRES"),
    (None, None, None),
])
def test_source_type_problem(table, kind, problem):
    """"" is cacheable, None is unknown (not judged). Bare and RDBMS_ forms both read."""
    head = {"dataSourceType": kind} if kind is not None else {}
    assert source_type_problem({"name": "T", "table": table, "header": head}) == problem


@pytest.mark.parametrize("facts_type, header_type, problem", [
    ("DATABRICKS", None, ""),               # the connection's type decides
    ("SNOWFLAKE", None, ""),
    ("REDSHIFT", "RDBMS_SNOWFLAKE", "REDSHIFT"),     # over the header's
    ("RDBMS_DATABRICKS", "RDBMS_REDSHIFT", ""),
    (None, "RDBMS_DATABRICKS", ""),         # no type in the facts: the header's
    (None, None, None),
])
def test_p23_reads_the_connections_type_before_the_header(facts_type, header_type, problem):
    source = {"name": "T", "table": {"name": "T", "connection": {"name": "Warehouse A"}},
              "header": {"dataSourceType": header_type} if header_type else {}}
    facts = [conn(type=facts_type), conn("Warehouse B", type="REDSHIFT")]
    assert source_type_problem(source, facts) == problem


def test_p23_reads_a_sql_views_connection_from_its_header():
    source = {"name": "V", "table": None,
              "header": {"dataSourceName": "warehouse b", "dataSourceType": "RDBMS_SNOWFLAKE"}}
    assert source_type_problem(source, [conn("Warehouse B", type="REDSHIFT")]) == "REDSHIFT"
    assert source_type_problem(source, [conn("Warehouse C", type="REDSHIFT")]) == ""


def test_p23_fires_on_a_non_cloud_connection_without_any_header():
    ctx = fx.build_cache_ctx(connections=[conn(type="REDSHIFT")])
    assert _field(ctx, "@non_cloud_sources") == ["ORDERS (REDSHIFT)"]


def test_a_source_with_no_type_leaves_p23_not_assessed():
    """No header type and no connection facts to read one from: P23 cannot judge the
    Model, so it is unknown, not ready."""
    ctx = fx.build_cache_ctx(connections=[conn(type=None)], headers=[header(source=None)])
    assert _field(ctx, "@non_cloud_sources") == []
    assert _readiness(ctx) == ("unknown", ["P23"])
    # the connection's type is enough
    typed = fx.build_cache_ctx(connections=CLEAN)
    assert _readiness(typed) == ("ready", [])


def test_p23_lists_each_source_with_its_type():
    assert _detail(fx.perf_non_cloud_sources(), "P23") == (
        "MEDIUM", "Can't use Data Cache: tables on a source other than Snowflake or "
                  "Databricks: ORDERS (RDBMS_REDSHIFT), SYS_LOG (no connection)")


# ── P24: connection settings ────────────────────────────────────────────────

def test_p24_names_what_each_connection_uses():
    assert _detail(fx.perf_connection_oauth_privatelink(), "P24") == (
        "MEDIUM", "Can't use Data Cache: connections that use OAuth, PrivateLink or a "
                  "template variable: Warehouse A: OAuth; PrivateLink read from the host "
                  "(to confirm)")
    ctx = fx.build_cache_ctx(connections=[conn(parameterized=True)])
    assert _field(ctx, "@connection_cache_blockers") == ["Warehouse A: template variable"]
    m2m = fx.build_cache_ctx(connections=[dict(conn(oauth=True), oauth_m2m=True)])
    assert _field(m2m, "@connection_cache_blockers") == ["Warehouse A: OAuth M2M (to confirm)"]


def test_p24_attaches_to_confirm_to_its_own_reading():
    """Each reading of a connection is one item; "to confirm" qualifies only the reading
    it follows, never reads as an item of its own."""
    ctx = fx.build_cache_ctx(connections=[
        conn(privatelink=True, parameterized=True),
        conn("Warehouse B", oauth=True, oauth_m2m=True)],
        sources=[{"name": "V", "fqn": "v1"}],
        headers=[header("v1", "ONE_TO_ONE_LOGICAL", connection="Warehouse B")])
    assert _field(ctx, "@connection_cache_blockers") == [
        "Warehouse A: PrivateLink read from the host (to confirm); template variable",
        "Warehouse B: OAuth M2M (to confirm)"]


def test_p24_matches_by_id_when_the_header_carries_one():
    ctx = fx.build_cache_ctx(connection="Renamed", connections=[
        dict(conn("Old name", oauth=True), id="conn-a")])
    ctx.metadata = [{"metadata_header": dict(header(), dataSourceId="conn-a")}]
    assert _field(ctx, "@connection_cache_blockers") == ["Renamed: OAuth"]


@pytest.mark.parametrize("facts", [
    pytest.param([dict(conn(), oauth=None, oauth_m2m=None, privatelink=None,
                       parameterized=None)], id="facts all unknown"),
    pytest.param([dict(conn(), privatelink=None)], id="one flag unknown"),
    pytest.param([conn("Warehouse B")], id="connection missing from the list"),
    pytest.param([], id="no connections listed"),
    pytest.param([conn(), dict(conn(), id="conn-2", oauth=None)], id="a duplicate unknown"),
])
def test_a_connection_p24_cannot_read_leaves_the_model_not_assessed(facts):
    ctx = fx.build_cache_ctx(connections=facts, headers=SNOWFLAKE_HEADER)
    assert run_rule(ctx, CAT, "P24", "general") == []
    assert _readiness(ctx) == ("unknown", ["P24"])


def test_an_unknown_connection_does_not_hide_a_firm_blocker():
    ctx = fx.build_cache_ctx(connections=[conn(oauth=None, parameterized=True)],
                             headers=SNOWFLAKE_HEADER)
    assert _field(ctx, "@connection_cache_blockers") == ["Warehouse A: template variable"]
    # its OAuth setting is unread, so P24 is not assessed in full: listed, not hidden
    assert _readiness(ctx) == ("blocked", ["P24"])


# ── P24: readings the product team is to confirm ────────────────────────────

@pytest.mark.parametrize("facts, readiness, lead", [
    ([conn(oauth=True, oauth_m2m=True)], "confirm", "May not be able to use Data Cache"),
    ([conn(privatelink=True)], "confirm", "May not be able to use Data Cache"),
    ([conn(oauth=True, oauth_m2m=True, privatelink=True)], "confirm",
     "May not be able to use Data Cache"),
    ([conn(oauth=True)], "blocked", "Can't use Data Cache"),
    ([conn(oauth=True, privatelink=True)], "blocked", "Can't use Data Cache"),
    ([conn(privatelink=True, parameterized=True)], "blocked", "Can't use Data Cache"),
    ([conn(privatelink=True), conn("Warehouse B", parameterized=True)], "confirm",
     "May not be able to use Data Cache"),
])
def test_a_reading_to_confirm_is_not_a_firm_cant_use(facts, readiness, lead):
    ctx = fx.build_cache_ctx(connections=facts, headers=SNOWFLAKE_HEADER)
    [finding] = run_rule(ctx, CAT, "P24", "general")
    assert finding.severity == "MEDIUM"
    assert finding.detail.startswith(lead + ": connections that use OAuth")
    assert _readiness(ctx)[0] == readiness


def test_an_unread_connection_is_not_hidden_by_a_reading_to_confirm():
    """WH A reads PrivateLink from its host (to confirm); WH B is missing from the
    connection search. Both show: P24's reason, and P24 not checked. An unread
    connection outranks a reading to confirm, so the Model is unknown, not To confirm."""
    ctx = fx.build_cache_ctx(connections=[conn(privatelink=True)],
                             sources=[{"name": "ITEMS", "fqn": "t-b"}],
                             headers=[header(), header("t-b", connection="Warehouse B")])
    ctx.tables["t-b"] = {"guid": "t-b", "table": {
        "name": "ITEMS", "connection": {"name": "Warehouse B"}, "columns": []}}
    if ctx.calendars is None:
        ctx.calendars = []
    [model] = run_audit(None, [], ["P"], ctx=ctx)["corpus"]["models"]
    dc = model["data_cache"]
    assert dc["readiness"] == "unknown" and dc["not_assessed"] == ["P24"]
    assert [(r["rule"], r["effect"], r["items"]) for r in dc["reasons"]] == [
        ("P24", "may block", ["Warehouse A: PrivateLink read from the host (to confirm)"])]


def test_a_firm_blocker_from_another_rule_keeps_a_to_confirm_model_blocked():
    ctx = fx.build_cache_ctx(connections=[conn(privatelink=True)], headers=SNOWFLAKE_HEADER,
                             table={"db": "${TENANT_DB}"})
    assert _readiness(ctx) == ("blocked", [])


def test_p24_is_heuristic_and_skips_every_model_when_connections_are_unknown():
    rule = CAT.rules["P24"]
    assert rule.evidence == "heuristic" and "connections" in rule.requires
    unknown = fx.build_cache_ctx(connections=None)
    assert list(scopes.available(unknown, rule)) == []
    assert _field(unknown, "@connection_cache_blockers") == []
    assert len(list(scopes.available(fx.build_cache_ctx(connections=[]), rule))) == 1


# ── P25: template variables in a Table's names ──────────────────────────────

@pytest.mark.parametrize("table, listed", [
    ({"db": "${DB}"}, ["ORDERS (database)"]),
    ({"db": "${DB}", "schema": "${S}", "db_table": "${T}"},
     ["ORDERS (database, schema, table name)"]),
    ({"db_table": " ${T} "}, ["ORDERS (table name)"]),
    ({"db": "x${DB}"}, []), ({"db": "${}"}, []), ({"db": 12}, []), ({}, []),
])
def test_parameterized_tables(table, listed):
    assert _field(fx.build_cache_ctx(table=table), "@parameterized_tables") == listed


# ── P26: parameters in formulas (A9's reading) ──────────────────────────────

def test_p26_reads_a9s_field():
    assert CAT.rules["P26"].aggregate["where"]["field"] == \
        CAT.rules["A9"].aggregate["where"]["all"][1]["field"]
    assert _detail(fx.perf_parameter_formula(), "P26") == (
        "MEDIUM", "Can't use Data Cache: formulas read a parameter: Adjusted")
    assert run_rule(fx.perf_parameter_named_in_a_literal(), CAT, "P26", "general") == []


# ── P27: SQL Views ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind, listed", [("SQL_VIEW", ["V"]), (" sql_view ", ["V"]),
                                          ("ONE_TO_ONE_LOGICAL", []), (None, [])])
def test_sql_view_sources(kind, listed):
    ctx = fx.build_cache_ctx(sources=[{"name": "V", "fqn": "v1"}],
                             headers=[header("v1", kind)])
    assert _field(ctx, "@sql_view_sources") == listed


def test_p27_lists_the_sql_views():
    assert _detail(fx.perf_sql_view_source(), "P27") == (
        "MEDIUM", "Can't use Data Cache: SQL Views: V_SALES")


# ── P28: RLS rules ──────────────────────────────────────────────────────────

OWN = {"ORDERS_1": {"id": "ORDERS_1", "table": "ORDERS"},
       "T_1": {"id": "T_1", "table": "TEAMS"},
       "J_1": {"id": "J_1", "table": "orders", "join_path": [{"join": ["J"]}]},
       "E_1": {"id": "E_1", "table": "ORDERS", "join_path": [{}]},
       "E_2": {"id": "E_2", "table": "ORDERS", "join_path": [{"join": []}, {"join": [""]}]}}
NULL_TEST = "a null test that keeps outer-join rows, see S12"


@pytest.mark.parametrize("expr, problems", [
    ("[ORDERS_1::REGION] = ts_username", []),
    ("[ORDERS_1::REGION] in ts_groups", []),
    ("'admin' in ts_groups or [ORDERS_1::R] in ts_var ( region_var )", []),
    ("[ORDERS_1::R] in ( 'a' , 'b' ) and not ( [ORDERS_1::R] = 'c' )", []),
    ("[ORDERS_1::R] = 'upper(x)'", []),
    ("[UNKNOWN_1::R] = ts_username", []),
    ("[T_1::MEMBER] = ts_username", ["another table's column"]),
    ("[J_1::R] = ts_username", ["a join"]),
    ("upper ( [ORDERS_1::R] ) = ts_username", ["a formula"]),
    ("if ( [ORDERS_1::R] = 'x' ) then true else false", ["a formula"]),
    ("sql_bool_op ( \"{0}\" , [ORDERS_1::R] )", ["a SQL pass-through"]),
    ("contains ( [T_1::X] , ts_username ) or SQL_INT_OP ( \"1\" ) = 1",
     ["another table's column", "a formula", "a SQL pass-through"]),
    (None, []),
    # an own-column path whose join_path names no join is not a join
    ("[E_1::R] = ts_username", []),
    ("[E_2::R] = ts_username", []),
    # a null test is named for the S12 trade-off, not as "a formula"
    ("[ORDERS_1::R] = ts_username or isnull ( [ORDERS_1::K] )", [NULL_TEST]),
    ("[ORDERS_1::R] = ts_username or IS_NULL ( [ORDERS_1::K] )", [NULL_TEST]),
    ("upper ( [ORDERS_1::R] ) = ts_username or isnull ( [ORDERS_1::K] )",
     ["a formula", NULL_TEST]),
    # `= null` is not a call: P28 does not read it (whether it stops Data Cache is open)
    ("[ORDERS_1::R] = ts_username or [ORDERS_1::K] = null", []),
    ("[ORDERS_1::R] = 'isnull ( x )'", []),
])
def test_rls_rule_problems(expr, problems):
    assert rls_rule_problems({"expr": expr}, "ORDERS", OWN) == problems


def test_p28_lists_each_rule_and_what_it_uses():
    severity, detail = _detail(fx.perf_rls_beyond_own_columns(), "P28")
    assert severity == "MEDIUM"
    assert detail == ("Can't use Data Cache: RLS rules reaching beyond their Table's own "
                      "columns: ORDERS: By team (a join, another table's column), ORDERS: "
                      "Upper region (a formula), ORDERS: Raw (a SQL pass-through)")


def test_p28_skips_a_model_that_bypasses_rls():
    """A Model with `is_bypass_rls` applies no RLS rule, as S17 reads it."""
    ctx = fx.perf_rls_beyond_own_columns()
    ctx.models[0]["model"]["properties"] = {"is_bypass_rls": True}
    assert _field(ctx, "@rls_rules_beyond_own_table") == []
    assert run_rule(ctx, CAT, "P28", "general") == []
    ctx.models[0]["model"]["properties"] = {"is_bypass_rls": False}
    assert len(_field(ctx, "@rls_rules_beyond_own_table")) == 3


def test_a_null_test_rule_is_listed_with_its_trade_off():
    ctx = fx.build_cache_ctx(table={"rls_rules": {
        "table_paths": [fx.CACHE_OWN_PATH],
        "rules": [{"name": "Keep unmatched",
                   "expr": "[ORDERS_1::REGION] = ts_username or isnull ( [ORDERS_1::ID] )"}]}})
    assert _field(ctx, "@rls_rules_beyond_own_table") == [
        f"ORDERS: Keep unmatched ({NULL_TEST})"]


def test_p28_reads_only_the_models_own_tables_and_survives_malformed_rls():
    ctx = fx.build_cache_ctx(table={"rls_rules": {"rules": "not a list"}})
    assert _field(ctx, "@rls_rules_beyond_own_table") == []
    ctx = fx.build_cache_ctx(table={"rls_rules": {"table_paths": ["x", {"id": 3}],
                                                  "rules": [{"expr": "upper ( [X::Y] )"}]}})
    assert _field(ctx, "@rls_rules_beyond_own_table") == ["ORDERS: ? (a formula)"]


# ── the rules ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rule_id, evidence", [
    ("P23", "fact"), ("P24", "heuristic"), ("P25", "fact"), ("P26", "fact"),
    ("P27", "fact"), ("P28", "fact")])
def test_each_rule_blocks_at_medium_in_performance(rule_id, evidence):
    rule = CAT.rules[rule_id]
    assert (rule.evidence, rule.categories, rule.scope, rule.severity) == \
        (evidence, ["P"], "model", "MEDIUM")
    assert rule.aggregate["mode"] == "each"
    assert set(rule.aggregate["where"]) == {"field", "len_gt"}   # what data_cache.py reads
    assert all(rule.profiles.get(p) is None for p in CAT.profiles)
