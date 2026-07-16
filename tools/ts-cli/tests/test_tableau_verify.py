"""Unit tests for `ts tableau verify` (tableau_verify module).

Pure-function tests — no live ThoughtSpot connection, no network.
"""

import os
import tempfile

from ts_cli.commands.tableau_verify import (
    is_untranslatable,
    is_query_time,
    classify,
    is_lod,
    normalize_tableau_formula,
    normalize_ts_formula,
    formula_similarity,
    match_ds_to_model,
    check_structural,
    check_validity,
    parse_model_tml,
    parse_sql_view_tml,
    TMLModel,
    TMLFormula,
    load_tml_dir,
)


# --- untranslatable / LOD classification (runs on RAW Tableau formulas) ---

def test_untranslatable_only_no_equivalent_functions():
    # genuinely no TS equivalent
    assert is_untranslatable("LOOKUP([Sales], -1)")[0] is True
    assert is_untranslatable("INDEX()")[0] is True
    assert is_untranslatable("DATENAME('weekday',[date])")[0] is True
    # query-time functions are NOT untranslatable (they have TS equivalents)
    assert is_untranslatable("WINDOW_SUM(SUM([Sales]))")[0] is False
    assert is_untranslatable("RUNNING_SUM(SUM([x]))")[0] is False
    assert is_untranslatable("RANK([Profit])")[0] is False


def test_query_time_classification():
    assert is_query_time("WINDOW_SUM(SUM([Sales]))")[0] is True
    assert is_query_time("RUNNING_AVG(AVG([x]))")[0] is True
    assert is_query_time("RANK_DENSE([Profit])")[0] is True
    assert is_query_time("TOTAL(SUM([Sales]))")[0] is True
    assert is_query_time("SUM([Sales])")[0] is False


def test_classify_three_way():
    assert classify("LOOKUP([x], -1)")[0] == 'untranslatable'
    assert classify("WINDOW_SUM(SUM([x]))")[0] == 'query_time'
    assert classify("SUM([x]) / COUNT([y])")[0] == 'translatable'
    # untranslatable wins even when an aggregate is nested inside
    assert classify("LOOKUP(SUM([x]), -1)")[0] == 'untranslatable'


def test_translatable_simple_formulas_not_flagged():
    assert is_untranslatable("IF [x] > 0 THEN 1 ELSE 0 END")[0] is False
    assert is_untranslatable("SUM([Sales]) / COUNT([Id])")[0] is False


def test_cross_datasource_ref_untranslatable():
    assert is_untranslatable("[Other DS].[Revenue]")[0] is True
    assert classify("[Other DS].[Revenue] + [Sales]")[0] == 'untranslatable'
    # [Parameters].[X] is NOT a cross-datasource ref — it's a parameter
    assert is_untranslatable("[Parameters].[MyParam]")[0] is False
    # Regular column refs are fine
    assert is_untranslatable("[Sales] + [Profit]")[0] is False


def test_lod_detected_but_translatable():
    # LOD is translatable (→ group_aggregate) but flagged for review,
    # so it must NOT be classed untranslatable.
    f = "{ FIXED [Region] : SUM([Sales]) }"
    assert is_lod(f) is True
    assert is_untranslatable(f)[0] is False


# --- formula normalization & similarity ---

def test_identical_formula_high_similarity():
    tab = normalize_tableau_formula("SUM([Sales]) / COUNT([Id])")
    ts = normalize_ts_formula("sum([Sales]) / count([Id])")
    assert formula_similarity(tab, ts) >= 0.85


def test_countd_matches_either_unique_count_spelling():
    # spelling-robust: COUNTD must match BOTH `unique_count` and `unique count`
    tab = normalize_tableau_formula("COUNTD([order_id])")
    assert formula_similarity(tab, normalize_ts_formula("unique_count([order_id])")) >= 0.85
    assert formula_similarity(tab, normalize_ts_formula("unique count([order_id])")) >= 0.85


def test_spaced_func_canonicalized():
    # `unique count` (two tokens) collapses to the same canonical token as `unique_count`
    assert normalize_ts_formula("unique count([x])") == normalize_ts_formula("unique_count([x])")


def test_table_qualified_ref_normalizes():
    # [Model::col] and [col] should normalize to the same token
    assert normalize_ts_formula("[Sales Model::revenue]") == normalize_ts_formula("[revenue]")


def test_dissimilar_formula_low_similarity():
    tab = normalize_tableau_formula("SUM([Sales])")
    ts = normalize_ts_formula("max([discount]) - min([cost]) + average([qty])")
    assert formula_similarity(tab, ts) < 0.5


# --- structural completeness: the silent-drop catch ---

def _twb_one_ds(calcs):
    return {
        "datasources": [{
            "is_parameters": False,
            "caption": "DS1",
            "tables": [{"relation_name": "Custom SQL Query", "physical_table": None,
                        "type": None, "sql_query": "SELECT 1"}],
            "custom_sql_sources": [{"name": "Custom SQL Query", "sql_query": "SELECT 1"}],
            "joins": [],
            "calculated_fields": calcs,
        }]
    }


def test_structural_detects_silent_drop():
    # Two translatable calcs in TWB; model has only one → one silently dropped.
    twb = _twb_one_ds([
        {"internal_name": "c1", "caption": "Revenue", "formula_raw": "SUM([rev])"},
        {"internal_name": "c2", "caption": "Orders", "formula_raw": "SUM([ord])"},
    ])
    model = TMLModel(name="DS1", formulas=[TMLFormula(id="formula_Revenue", name="Revenue", expr="sum([rev])")])
    ds_map = {"DS1": model}
    stats, issues = check_structural(twb, [model], [], [parse_sql_view_stub()], ds_map)
    assert stats["translatable_calculated_fields"] == 2
    assert stats["formulas_in_tml"] == 1
    assert any("translatable formula" in i.message and i.severity == "WARNING" for i in issues)


def parse_sql_view_stub():
    from ts_cli.commands.tableau_verify import TMLSqlView
    return TMLSqlView(name="Custom SQL Query", sql_query="SELECT 1")


def test_structural_untranslatable_excluded_from_translatable_count():
    twb = _twb_one_ds([
        {"internal_name": "c1", "caption": "Look", "formula_raw": "LOOKUP([x], -1)"},
        {"internal_name": "c2", "caption": "Good", "formula_raw": "SUM([x])"},
    ])
    model = TMLModel(name="DS1", formulas=[TMLFormula(id="formula_Good", name="Good", expr="sum([x])")])
    stats, issues = check_structural(twb, [model], [], [parse_sql_view_stub()], {"DS1": model})
    assert stats["untranslatable_calculated_fields"] == 1
    assert stats["translatable_calculated_fields"] == 1
    # the one translatable formula is present → no silent-drop warning
    assert not any("translatable formula" in i.message for i in issues)


def test_structural_query_time_not_a_silent_drop():
    # A WINDOW_ formula is query-time → expected absent from the model.
    # It must NOT count as translatable, and its absence must NOT warn.
    twb = _twb_one_ds([
        {"internal_name": "c1", "caption": "Win", "formula_raw": "WINDOW_SUM(SUM([x]))"},
        {"internal_name": "c2", "caption": "Good", "formula_raw": "SUM([x])"},
    ])
    model = TMLModel(name="DS1", formulas=[TMLFormula(id="formula_Good", name="Good", expr="sum([x])")])
    stats, issues = check_structural(twb, [model], [], [parse_sql_view_stub()], {"DS1": model})
    assert stats["query_time_calculated_fields"] == 1
    assert stats["translatable_calculated_fields"] == 1
    assert stats["untranslatable_calculated_fields"] == 0
    assert not any("translatable formula" in i.message for i in issues)


# --- TML validity: banned functions, INT, join enums ---

def test_validity_flags_banned_function():
    model = TMLModel(name="M", formulas=[TMLFormula(id="formula_F", name="F", expr="split([x], ',', 1)")])
    issues = check_validity([model], [], [])
    assert any("split" in i.message and i.severity == "ERROR" for i in issues)


def test_validity_skips_banned_inside_sql_string_op():
    expr = "sql_string_op ( 'sql_string_op ( 'upper({0})' , {0} )' , substr ( sql_string_op ( 'sql_string_op ( 'sql_string_op ( 'replace({0}, \\'_\\', \\' \\')' , {0} )' , {0} )' , [COL] , 1 , 1 ) )"
    model = TMLModel(name="M", formulas=[TMLFormula(id="formula_F", name="F", expr=expr)])
    issues = check_validity([model], [], [])
    assert not any("replace" in i.message for i in issues)
    assert not any("upper" in i.message for i in issues)


def test_validity_flags_int_data_type():
    from ts_cli.commands.tableau_verify import TMLTable
    tbl = TMLTable(name="T", db="DB", schema="SC",
                   columns=[{"name": "c", "db_column_name": "c", "data_type": "INT"}])
    issues = check_validity([], [tbl], [])
    assert any("INT64" in i.message and i.severity == "ERROR" for i in issues)


def test_validity_flags_sql_xml_artifact():
    from ts_cli.commands.tableau_verify import TMLSqlView
    sv = TMLSqlView(name="V", sql_query="SELECT * FROM t WHERE d >>= '2023-01-01'")
    issues = check_validity([], [], [sv])
    assert any("XML artifact" in i.message for i in issues)


def test_validity_flags_invalid_join_type():
    model = TMLModel(name="M", joins=[{"with": "T2", "on": "[a]=[b]",
                                       "type": "LEFT", "cardinality": "MANY_TO_ONE"}])
    issues = check_validity([model], [], [])
    assert any("invalid join type" in i.message for i in issues)


# --- ds → model matching ---

def test_match_by_caption():
    twb = {"datasources": [{"is_parameters": False, "caption": "Sales", "tables": [], "calculated_fields": []}]}
    model = TMLModel(name="Sales")
    assert match_ds_to_model(twb, [model])["Sales"] is model


def test_match_unmatched_returns_none():
    twb = {"datasources": [{"is_parameters": False, "caption": "Ghost", "tables": [], "calculated_fields": []}]}
    assert match_ds_to_model(twb, [TMLModel(name="Other")])["Ghost"] is None


def test_match_by_obj_id_prefix():
    """Datasource caption matches model obj_id prefix (strips -hash suffix)."""
    twb = {"datasources": [
        {"is_parameters": False, "caption": "TAB_DS_POPULAR (CONNECTION)",
         "tables": [{"relation_name": "Custom SQL Query"}], "calculated_fields": []},
    ]}
    model = TMLModel(name="Popular Categories",
                     tables=["VW_POPULAR_RPT"],
                     obj_id="TAB_DS_POPULAR-a1b2c3d4")
    result = match_ds_to_model(twb, [model])
    assert result["TAB_DS_POPULAR (CONNECTION)"] is model


def test_match_by_obj_id_prefix_partial():
    """obj_id prefix matching works with startswith fallback."""
    twb = {"datasources": [
        {"is_parameters": False, "caption": "PX_TBL_TAB_DS_CLICKSTREAM",
         "tables": [], "calculated_fields": []},
    ]}
    model = TMLModel(name="Clickstream",
                     tables=["VW_PX_RPT"],
                     obj_id="PX_TBL_TAB_DS_CLICKSTREAM-abcdef01")
    result = match_ds_to_model(twb, [model])
    assert result["PX_TBL_TAB_DS_CLICKSTREAM"] is model


# --- sql_view parsing handles list-form sql_query ---

def test_parse_sql_view_list_query():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "v.sql_view.tml")
        with open(p, "w") as f:
            f.write("sql_view:\n  name: V\n  sql_query:\n    - 'SELECT a'\n    - 'FROM t'\n")
        sv = parse_sql_view_tml(p)
        assert sv.name == "V"
        assert "SELECT a" in sv.sql_query and "FROM t" in sv.sql_query


def test_load_tml_dir_buckets_by_type():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "m.model.tml"), "w") as f:
            f.write("model:\n  name: M\n")
        with open(os.path.join(d, "v.sql_view.tml"), "w") as f:
            f.write("sql_view:\n  name: V\n  sql_query: 'SELECT 1'\n")
        models, tables, sql_views, bad = load_tml_dir(d)
        assert len(models) == 1 and len(sql_views) == 1 and len(tables) == 0 and not bad
