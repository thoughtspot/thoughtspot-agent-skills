"""Tests for ts tableau generate-tml (T3 — deterministic TML generation)."""
import json
import os
import tempfile

import yaml

from ts_cli.commands.tableau_generate import (
    _build_connection_table_index,
    _build_model_tml,
    _build_sql_view_tml,
    _build_table_tml,
    _convert_on_clause,
    _is_measure,
    _load_full_table_map,
    _load_table_map,
    _norm_key,
    _remap_sql_query,
    _sanitize_formula_id,
    _split_disambig,
    _ts_data_type,
    run_generate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col(name, local_type="string", aggregation="None", parent_table="T1"):
    return {
        "name": name,
        "local_name": name,
        "local_type": local_type,
        "aggregation": aggregation,
        "parent_table": parent_table,
    }


def _calc(caption, formula_raw, level=0, role="dimension"):
    return {
        "internal_name": f"Calculation_{caption}",
        "caption": caption,
        "datatype": "string",
        "role": role,
        "formula_raw": formula_raw,
        "formula": formula_raw,
        "level": level,
    }


def _formula_entry(caption, translated, tier="translatable", level=0):
    return {
        "caption": caption,
        "level": level,
        "original": translated,
        "translated": translated,
        "tier": tier,
        "deterministic": tier == "translatable",
        "reason": "",
    }


# ---------------------------------------------------------------------------
# _ts_data_type
# ---------------------------------------------------------------------------

def test_ts_data_type_string():
    assert _ts_data_type("string") == "VARCHAR"

def test_ts_data_type_integer():
    assert _ts_data_type("integer") == "INT64"

def test_ts_data_type_real():
    assert _ts_data_type("real") == "DOUBLE"

def test_ts_data_type_date():
    assert _ts_data_type("date") == "DATE"

def test_ts_data_type_datetime():
    assert _ts_data_type("datetime") == "DATE_TIME"

def test_ts_data_type_boolean():
    assert _ts_data_type("boolean") == "BOOL"

def test_ts_data_type_unknown_defaults_varchar():
    assert _ts_data_type("unknown_type") == "VARCHAR"

def test_ts_data_type_none():
    assert _ts_data_type(None) == "VARCHAR"


# ---------------------------------------------------------------------------
# _is_measure
# ---------------------------------------------------------------------------

def test_is_measure_sum_integer():
    assert _is_measure({"aggregation": "Sum", "local_type": "integer"}) is True

def test_is_measure_avg_real():
    assert _is_measure({"aggregation": "Avg", "local_type": "real"}) is True

def test_is_measure_count_string():
    assert _is_measure({"aggregation": "Count", "local_type": "string"}) is False

def test_is_measure_sum_string():
    assert _is_measure({"aggregation": "Sum", "local_type": "string"}) is False

def test_is_measure_none_agg():
    assert _is_measure({"aggregation": "None", "local_type": "integer"}) is False

def test_is_measure_dimension_role_overrides():
    assert _is_measure({"aggregation": "Sum", "local_type": "integer", "role": "dimension"}) is False

def test_is_measure_measure_role_preserves():
    assert _is_measure({"aggregation": "Sum", "local_type": "integer", "role": "measure"}) is True


# ---------------------------------------------------------------------------
# _sanitize_formula_id
# ---------------------------------------------------------------------------

def test_sanitize_formula_id_basic():
    assert _sanitize_formula_id("Profit Margin") == "Profit_Margin"

def test_sanitize_formula_id_starts_digit():
    assert _sanitize_formula_id("3Year Avg").startswith("f_")

def test_sanitize_formula_id_special_chars():
    result = _sanitize_formula_id("% of Total (Sales)")
    assert result == "of_Total__Sales" or result.startswith("f_")


# ---------------------------------------------------------------------------
# _load_table_map
# ---------------------------------------------------------------------------

def test_load_table_map_colon_separator():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("ORDERS : VW_ORDERS_RPT\n")
        f.write("# comment line\n")
        f.write("CUSTOMERS : VW_CUSTOMERS_RPT\n")
        f.name
    try:
        m = _load_table_map(f.name)
        assert m == {"ORDERS": "VW_ORDERS_RPT", "CUSTOMERS": "VW_CUSTOMERS_RPT"}
    finally:
        os.unlink(f.name)


def test_load_table_map_dash_separator():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("SALES - VW_SALES\n")
        f.name
    try:
        m = _load_table_map(f.name)
        assert m == {"SALES": "VW_SALES"}
    finally:
        os.unlink(f.name)


def test_load_table_map_qualified_source():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("DB.SCHEMA.ORDERS : VW_ORDERS\n")
        f.name
    try:
        m = _load_table_map(f.name)
        assert m == {"ORDERS": "VW_ORDERS"}
    finally:
        os.unlink(f.name)


# ---------------------------------------------------------------------------
# _build_table_tml
# ---------------------------------------------------------------------------

def test_build_table_tml_structure():
    cols = [_col("ORDER_ID", "integer", "Count"), _col("AMOUNT", "real", "Sum")]
    tml = _build_table_tml("VW_ORDERS", cols, "MY_CONN", "MY_DB", "MY_SCHEMA")
    t = tml["table"]
    assert t["name"] == "VW_ORDERS"
    assert t["db"] == "MY_DB"
    assert t["schema"] == "MY_SCHEMA"
    assert t["db_table"] == "VW_ORDERS"
    assert t["connection"]["name"] == "MY_CONN"
    assert len(t["columns"]) == 2


def test_build_table_tml_column_types():
    cols = [_col("ID", "integer", "Count"), _col("AMT", "real", "Sum")]
    tml = _build_table_tml("T", cols, "C", "D", "S")
    c0 = tml["table"]["columns"][0]
    assert c0["properties"]["column_type"] == "ATTRIBUTE"
    assert c0["db_column_name"] == "ID"
    assert c0["db_column_properties"]["data_type"] == "INT64"
    c1 = tml["table"]["columns"][1]
    assert c1["properties"]["column_type"] == "MEASURE"


def test_build_table_tml_deduplicates_columns():
    cols = [_col("A"), _col("A"), _col("B")]
    tml = _build_table_tml("T", cols, "C", "D", "S")
    assert len(tml["table"]["columns"]) == 2


def test_build_table_tml_db_column_name_always_present():
    cols = [_col("MY_COL")]
    tml = _build_table_tml("T", cols, "C", "D", "S")
    assert tml["table"]["columns"][0]["db_column_name"] == "MY_COL"


# ---------------------------------------------------------------------------
# _build_sql_view_tml
# ---------------------------------------------------------------------------

def test_build_sql_view_tml_structure():
    cols = [_col("COL1"), _col("COL2", "integer", "Sum")]
    tml = _build_sql_view_tml("My_View", "SELECT 1", cols, "MY_CONN")
    sv = tml["sql_view"]
    assert sv["name"] == "My_View"
    assert sv["connection"]["name"] == "MY_CONN"
    assert sv["sql_query"] == "SELECT 1"
    assert len(sv["sql_view_columns"]) == 2


def test_build_sql_view_tml_uses_sql_output_column():
    cols = [_col("X")]
    tml = _build_sql_view_tml("V", "SELECT x", cols, "C")
    assert "sql_output_column" in tml["sql_view"]["sql_view_columns"][0]
    assert "db_column_name" not in tml["sql_view"]["sql_view_columns"][0]


# ---------------------------------------------------------------------------
# _build_model_tml
# ---------------------------------------------------------------------------

def test_build_model_tml_basic():
    ds = {
        "calculated_fields": [_calc("Profit", "sum([Sales]) - sum([Cost])", role="measure")],
        "physical_columns": [_col("Sales", "real", "Sum"), _col("Cost", "real", "Sum")],
    }
    fl = {"Profit": [_formula_entry("Profit", "sum([Sales]) - sum([Cost])")]}
    tml, omitted, _ = _build_model_tml("TestModel", ["T1"], ds, fl, [])
    assert tml["model"]["name"] == "TestModel"
    assert len(tml["model"]["formulas"]) == 1
    assert tml["model"]["formulas"][0]["name"] == "Profit"
    assert omitted == []


def test_build_model_tml_omits_untranslatable():
    ds = {
        "calculated_fields": [_calc("Bad", "LOOKUP([X], -1)")],
        "physical_columns": [_col("X")],
    }
    fl = {"Bad": [_formula_entry("Bad", "LOOKUP([X], -1)", tier="untranslatable")]}
    tml, omitted, _ = _build_model_tml("M", ["T1"], ds, fl, [])
    assert len(tml["model"].get("formulas", [])) == 0
    assert "Bad" in omitted


def test_build_model_tml_omits_missing_formula():
    ds = {
        "calculated_fields": [_calc("Missing", "SUM([X])")],
        "physical_columns": [_col("X")],
    }
    tml, omitted, _ = _build_model_tml("M", ["T1"], ds, {}, [])
    assert len(tml["model"].get("formulas", [])) == 0
    assert "Missing" in omitted


def test_build_model_tml_with_joins():
    ds = {
        "calculated_fields": [],
        "physical_columns": [_col("ID", parent_table="ORDERS"), _col("CNAME", parent_table="CUSTOMERS")],
        "joins": [{"left_table": "ORDERS", "right_table": "CUSTOMERS",
                    "join_type": "left", "on_clause": "[ORDERS].[cid] = [CUSTOMERS].[id]"}],
    }
    tml, _, warnings = _build_model_tml("M", ["ORDERS", "CUSTOMERS"], ds, {}, [],
                                        joins=ds["joins"])
    mt = tml["model"]["model_tables"]
    joined = [m for m in mt if "joins" in m]
    assert len(joined) == 1
    # Join lives on the source (left) table entry, per the model TML schema
    assert joined[0]["name"] == "ORDERS"
    j = joined[0]["joins"][0]
    assert j["with"] == "CUSTOMERS"
    assert j["type"] == "LEFT_OUTER"
    assert j["on"] == "[ORDERS::cid] = [CUSTOMERS::id]"
    assert warnings["dropped_joins"] == []


def test_build_model_tml_with_parameters():
    ds = {
        "calculated_fields": [_calc("F1", "if ([Param1] = 'A') then 1 else 0")],
        "physical_columns": [_col("X")],
    }
    fl = {"F1": [_formula_entry("F1", "if ([Param1] = 'A') then 1 else 0")]}
    params = [{"caption": "Param1", "internal_name": "P1", "datatype": "string",
               "current_value": "A", "allowed_values": [{"value": "A"}, {"value": "B"}]}]
    tml, _, _ = _build_model_tml("M", ["T1"], ds, fl, params)
    assert "parameters" in tml["model"]
    assert tml["model"]["parameters"][0]["name"] == "Param1"


def test_build_model_tml_params_scoped_to_included_formulas():
    ds = {
        "calculated_fields": [
            _calc("F1", "if ([Param1] = 'A') then 1 else 0"),
            _calc("Dropped", "if ([Param2] = 'X') then 1 else 0"),
        ],
        "physical_columns": [_col("X")],
    }
    fl = {"F1": [_formula_entry("F1", "if ([Param1] = 'A') then 1 else 0")]}
    params = [
        {"caption": "Param1", "internal_name": "P1", "datatype": "string",
         "current_value": "A"},
        {"caption": "Param2", "internal_name": "P2", "datatype": "string",
         "current_value": "X"},
    ]
    tml, omitted, _ = _build_model_tml("M", ["T1"], ds, fl, params)
    assert "Dropped" in omitted
    param_names = [p["name"] for p in tml["model"].get("parameters", [])]
    assert "Param1" in param_names
    assert "Param2" not in param_names


def test_build_model_tml_formula_column_type():
    ds = {
        "calculated_fields": [
            _calc("Metric", "sum([Sales])", role="measure"),
            _calc("Label", "if ([X] > 0) then 'Y' else 'N'", role="dimension"),
        ],
        "physical_columns": [_col("Sales", "real", "Sum"), _col("X", "integer")],
    }
    fl = {
        "Metric": [_formula_entry("Metric", "sum([Sales])")],
        "Label": [_formula_entry("Label", "if ([X] > 0) then 'Y' else 'N'")],
    }
    tml, _, _ = _build_model_tml("M", ["T1"], ds, fl, [])
    cols = tml["model"]["columns"]
    formula_cols = [c for c in cols if "formula_id" in c]
    metric_col = [c for c in formula_cols if c["name"] == "Metric"][0]
    label_col = [c for c in formula_cols if c["name"] == "Label"][0]
    assert metric_col["properties"]["column_type"] == "MEASURE"
    assert label_col["properties"]["column_type"] == "ATTRIBUTE"


# ---------------------------------------------------------------------------
# run_generate (end-to-end)
# ---------------------------------------------------------------------------

def _sample_parsed():
    return {
        "datasources": [
            {
                "name": "federated.abc",
                "caption": "Sales Data",
                "is_parameters": False,
                "tables": [
                    {"relation_name": "ORDERS", "physical_table": "ORDERS"},
                    {"relation_name": "Custom SQL", "physical_table": "Custom SQL",
                     "sql_query": "SELECT id, name FROM raw.customers"},
                ],
                "physical_columns": [
                    _col("ORDER_ID", "integer", "Count", "ORDERS"),
                    _col("AMOUNT", "real", "Sum", "ORDERS"),
                    _col("id", "integer", "Count", "Custom SQL"),
                    _col("name", "string", "None", "Custom SQL"),
                ],
                "calculated_fields": [
                    _calc("Total Sales", "sum([AMOUNT])", role="measure"),
                ],
                "joins": [],
                "custom_sql_sources": [{"name": "Custom SQL", "sql_query": "SELECT id, name FROM raw.customers"}],
            },
            {
                "name": "Parameters",
                "caption": "Parameters",
                "is_parameters": True,
                "parameters": [],
            },
        ],
        "formula_column_map": {},
        "parameter_map": {},
    }


def _sample_translated():
    return {
        "formulas": [
            _formula_entry("Total Sales", "sum([AMOUNT])"),
        ],
        "summary": {"translatable": 1, "total": 1},
    }


def test_run_generate_creates_all_files():
    parsed = _sample_parsed()
    translated = _sample_translated()
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(
            parsed=parsed,
            translated=translated,
            connection="TEST_CONN",
            database="TEST_DB",
            schema="TEST_SCHEMA",
            table_map=None,
            out_dir=tmpdir,
        )
        assert len(summary["tables"]) == 1
        assert len(summary["sql_views"]) == 1
        assert len(summary["models"]) == 1

        # Verify files exist
        files = os.listdir(tmpdir)
        assert any(f.endswith(".table.tml") for f in files)
        assert any(f.endswith(".sql_view.tml") for f in files)
        assert any(f.endswith(".model.tml") for f in files)


def test_run_generate_table_tml_valid_yaml():
    parsed = _sample_parsed()
    translated = _sample_translated()
    with tempfile.TemporaryDirectory() as tmpdir:
        run_generate(parsed, translated, "C", "D", "S", None, tmpdir)
        table_files = [f for f in os.listdir(tmpdir) if f.endswith(".table.tml")]
        for tf in table_files:
            with open(os.path.join(tmpdir, tf)) as fh:
                tml = yaml.safe_load(fh)
            assert "table" in tml
            assert "columns" in tml["table"]
            for col in tml["table"]["columns"]:
                assert "db_column_name" in col


def test_run_generate_with_table_map():
    parsed = _sample_parsed()
    translated = _sample_translated()
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(
            parsed=parsed,
            translated=translated,
            connection="C",
            database="D",
            schema="S",
            table_map={"ORDERS": "VW_ORDERS_RPT"},
            out_dir=tmpdir,
        )
        assert summary["tables"][0]["name"] == "VW_ORDERS_RPT"


def test_run_generate_model_has_formula():
    parsed = _sample_parsed()
    translated = _sample_translated()
    with tempfile.TemporaryDirectory() as tmpdir:
        run_generate(parsed, translated, "C", "D", "S", None, tmpdir)
        model_files = [f for f in os.listdir(tmpdir) if f.endswith(".model.tml")]
        assert len(model_files) == 1
        with open(os.path.join(tmpdir, model_files[0])) as fh:
            tml = yaml.safe_load(fh)
        assert "formulas" in tml["model"]
        assert tml["model"]["formulas"][0]["name"] == "Total Sales"


def test_run_generate_sql_view_preserves_query():
    parsed = _sample_parsed()
    translated = _sample_translated()
    with tempfile.TemporaryDirectory() as tmpdir:
        run_generate(parsed, translated, "C", "D", "S", None, tmpdir)
        sv_files = [f for f in os.listdir(tmpdir) if f.endswith(".sql_view.tml")]
        assert len(sv_files) == 1
        with open(os.path.join(tmpdir, sv_files[0])) as fh:
            tml = yaml.safe_load(fh)
        assert "SELECT" in tml["sql_view"]["sql_query"]


def test_run_generate_skips_parameter_datasource():
    parsed = _sample_parsed()
    translated = _sample_translated()
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(parsed, translated, "C", "D", "S", None, tmpdir)
        model_names = [m["name"] for m in summary["models"]]
        assert "Parameters" not in model_names


# ---------------------------------------------------------------------------
# Customer-workbook regressions (Partner Clickstream Funnel Dashboard shape)
# ---------------------------------------------------------------------------

def test_split_disambig_with_suffix():
    assert _split_disambig("BRAND_NAME (TAB_POPULAR_CATEGORIES)") == (
        "BRAND_NAME", "TAB_POPULAR_CATEGORIES")


def test_split_disambig_without_suffix():
    assert _split_disambig("CLICKS") == ("CLICKS", "")


def test_split_disambig_empty():
    assert _split_disambig("") == ("", "")


def test_norm_key_matches_across_formats():
    assert _norm_key("Custom SQL Query1") == _norm_key("Custom_SQL_Query1")
    assert _norm_key("Chocolate Sales 2") == _norm_key("CHOCOLATE_SALES_2")


def test_table_tml_db_column_name_strips_disambig_suffix():
    cols = [_col("BRAND_NAME (TAB_POPULAR_CATEGORIES)", "string", "Count")]
    tml = _build_table_tml("T", cols, "C", "D", "S")
    c0 = tml["table"]["columns"][0]
    assert c0["name"] == "BRAND_NAME (TAB_POPULAR_CATEGORIES)"
    assert c0["db_column_name"] == "BRAND_NAME"


def test_sql_view_output_column_strips_disambig_suffix():
    cols = [_col("CATEGORY_ID (Custom SQL Query1)", "integer", "Sum")]
    tml = _build_sql_view_tml("V", "SELECT CATEGORY_ID FROM X", cols, "C")
    vc = tml["sql_view"]["sql_view_columns"][0]
    assert vc["name"] == "CATEGORY_ID (Custom SQL Query1)"
    assert vc["sql_output_column"] == "CATEGORY_ID"


def test_convert_on_clause_object_graph_form():
    # [col] = [col (Other Source)] — hint names the right table's relation
    resolve = {"CUSTOM_SQL_QUERY": "TAB_Custom_SQL"}.get
    def resolver(name):
        return resolve(_norm_key(name))
    on = _convert_on_clause(
        "[CATEGORY_ID] = [CATEGORY_ID (Custom SQL Query)]",
        "Custom_SQL_Query1", "TAB_Custom_SQL",
        resolver, lambda t, b: b)
    assert on == "[Custom_SQL_Query1::CATEGORY_ID] = [TAB_Custom_SQL::CATEGORY_ID]"


def test_convert_on_clause_classic_form():
    on = _convert_on_clause(
        "[ORDERS].[cid] = [CUSTOMERS].[id]",
        "ORDERS", "CUSTOMERS",
        lambda n: {"ORDERS": "ORDERS", "CUSTOMERS": "CUSTOMERS"}.get(n),
        lambda t, b: b)
    assert on == "[ORDERS::cid] = [CUSTOMERS::id]"


def _clickstream_parsed():
    """Mirrors the Partner Clickstream workbook: two custom-SQL relations,
    a join between them, disambiguation-suffixed column names, and stray
    metadata columns from a table that has no relation in the datasource."""
    return {
        "datasources": [
            {
                "name": "federated.xyz",
                "caption": "TAB_DS_CLICKSTREAM_POPULAR_CATEGORIES (DATA_SCIENCE_INTERNAL)",
                "is_parameters": False,
                "tables": [
                    {"relation_name": "Custom SQL Query1", "physical_table": "Custom SQL Query1",
                     "sql_query": "SELECT CATEGORY_ID, CLICKS FROM DB.SCH.T1"},
                    {"relation_name": "Custom SQL Query", "physical_table": "Custom SQL Query",
                     "sql_query": "SELECT CATEGORY_ID, CATEGORY_NAME FROM DB.SCH.T2"},
                ],
                "physical_columns": [
                    _col("CATEGORY_ID (Custom SQL Query1)", "integer", "Sum", "Custom SQL Query1"),
                    _col("CLICKS", "integer", "Sum", "Custom SQL Query1"),
                    _col("CATEGORY_ID", "integer", "Sum", "Custom SQL Query"),
                    _col("CATEGORY_NAME", "string", "Count", "Custom SQL Query"),
                    _col("BRAND_NAME", "string", "Count", "SP_TAB_POPULAR_CATEGORIES"),
                ],
                "calculated_fields": [],
                "joins": [{"left_table": "Custom SQL Query1", "right_table": "Custom SQL Query",
                           "join_type": "left",
                           "on_clause": "[CATEGORY_ID] = [CATEGORY_ID (Custom SQL Query)]",
                           "source": "object-graph"}],
                "custom_sql_sources": [],
            },
        ],
        "dashboards": [],
    }


def test_clickstream_join_survives_view_renames():
    parsed = _clickstream_parsed()
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(parsed, {"formulas": []}, "C", "D", "S", None, tmpdir)
        assert summary["dropped_joins"] == []
        model_file = [f for f in os.listdir(tmpdir) if f.endswith(".model.tml")][0]
        with open(os.path.join(tmpdir, model_file)) as fh:
            model = yaml.safe_load(fh)["model"]
        by_name = {mt["name"]: mt for mt in model["model_tables"]}
        src = by_name["Custom_SQL_Query1"]
        assert "joins" in src
        j = src["joins"][0]
        assert j["with"] == "TAB_DS_CLICKSTREAM_POPULAR_CATEGORIES_DATA_SCIENCE_INTERNAL_Custom_SQL"
        assert j["type"] == "LEFT_OUTER"
        # Left ref resolves to the suffixed display name in the left view;
        # right ref resolves to the plain name in the right view
        assert j["on"] == (
            "[Custom_SQL_Query1::CATEGORY_ID (Custom SQL Query1)] = "
            "[TAB_DS_CLICKSTREAM_POPULAR_CATEGORIES_DATA_SCIENCE_INTERNAL_Custom_SQL::CATEGORY_ID]")


def test_clickstream_column_ids_assigned_per_view():
    parsed = _clickstream_parsed()
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(parsed, {"formulas": []}, "C", "D", "S", None, tmpdir)
        model_file = [f for f in os.listdir(tmpdir) if f.endswith(".model.tml")][0]
        with open(os.path.join(tmpdir, model_file)) as fh:
            model = yaml.safe_load(fh)["model"]
        col_ids = {c["name"]: c["column_id"] for c in model["columns"] if "column_id" in c}
        assert col_ids["CLICKS"].startswith("Custom_SQL_Query1::")
        assert col_ids["CATEGORY_ID (Custom SQL Query1)"].startswith("Custom_SQL_Query1::")
        assert col_ids["CATEGORY_NAME"].startswith(
            "TAB_DS_CLICKSTREAM_POPULAR_CATEGORIES_DATA_SCIENCE_INTERNAL_Custom_SQL::")
        assert col_ids["CATEGORY_ID"].startswith(
            "TAB_DS_CLICKSTREAM_POPULAR_CATEGORIES_DATA_SCIENCE_INTERNAL_Custom_SQL::")
        # The stray metadata column is reported, not silently misassigned
        assert "BRAND_NAME" not in col_ids
        unassigned = [u["column"] for u in summary["unassigned_columns"]]
        assert unassigned == ["BRAND_NAME"]


def test_multi_table_no_blind_fallback_in_table_tml():
    """Chocolate Sales regression: with 2+ relations, an unmatched table
    must not receive every column in the datasource."""
    parsed = {
        "datasources": [
            {
                "name": "federated.abc",
                "caption": "Choco",
                "is_parameters": False,
                "tables": [
                    {"relation_name": "Chocolate Sales 2", "physical_table": "Chocolate Sales 2"},
                    {"relation_name": "dim_sales.csv", "physical_table": "dim_sales#csv"},
                ],
                "physical_columns": [
                    _col("Amount", "real", "Sum", "Chocolate Sales 2"),
                    _col("Country", "string", "Count", "Chocolate Sales 2"),
                    _col("Manager Name", "string", "Count", "dim_sales#csv"),
                ],
                "calculated_fields": [],
                "joins": [],
                "custom_sql_sources": [],
            },
        ],
        "dashboards": [],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(parsed, {"formulas": []}, "C", "D", "S", None, tmpdir)
        counts = {t["name"]: t["columns"] for t in summary["tables"]}
        assert counts["Chocolate Sales 2"] == 2
        assert counts["dim_sales#csv"] == 1


def test_dropped_join_reported_when_table_unresolvable():
    parsed = _clickstream_parsed()
    parsed["datasources"][0]["joins"][0]["right_table"] = "No Such Relation"
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(parsed, {"formulas": []}, "C", "D", "S", None, tmpdir)
        assert len(summary["dropped_joins"]) == 1
        assert summary["dropped_joins"][0]["reason"] == "unresolved table reference"


# ---------------------------------------------------------------------------
# Decisions flow (Step 5.1 as data, not hand-edits)
# ---------------------------------------------------------------------------

def _judgment_parsed():
    return {
        "datasources": [
            {
                "name": "federated.j",
                "caption": "Funnel",
                "is_parameters": False,
                "tables": [{"relation_name": "AGG", "physical_table": "AGG"}],
                "physical_columns": [
                    _col("SESSIONS", "integer", "Sum", "AGG"),
                    _col("PREV_SESSIONS", "integer", "Sum", "AGG"),
                ],
                "calculated_fields": [
                    _calc("WoW Raw", "ZN(SUM([SESSIONS])) / LOOKUP(ZN(SUM([SESSIONS])))"),
                    _calc("Vs First", "ZN(MAX([SESSIONS])) / LOOKUP(ZN(MAX([SESSIONS])), FIRST())"),
                ],
                "joins": [],
                "custom_sql_sources": [],
            },
        ],
        "dashboards": [],
    }


def _judgment_translated():
    return {"formulas": [
        _formula_entry("WoW Raw", "", tier="untranslatable"),
        _formula_entry("Vs First", "", tier="untranslatable"),
    ]}


def test_decisions_needed_file_emitted():
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(_judgment_parsed(), _judgment_translated(),
                               "C", "D", "S", None, tmpdir)
        assert summary["decisions_needed"]["count"] == 2
        needed = json.load(open(os.path.join(tmpdir, "decisions-needed.json")))
        caps = {f["caption"] for f in needed["formulas"]}
        assert caps == {"WoW Raw", "Vs First"}
        assert needed["formulas"][0]["status"] == "omitted"
        assert "SESSIONS" in needed["context"]["Funnel"]["columns"]


def test_decision_use_expr_applied_via_schema_path():
    decisions = {"WoW Raw": {
        "action": "use_expr", "name": "Sessions vs Prev",
        "expr": "sum ( [SESSIONS] ) / sum ( [PREV_SESSIONS] )",
        "column_type": "MEASURE",
    }}
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(_judgment_parsed(), _judgment_translated(),
                               "C", "D", "S", None, tmpdir, decisions=decisions)
        model = yaml.safe_load(open(os.path.join(tmpdir, "Funnel.model.tml")))["model"]
        f = [x for x in model["formulas"] if x["name"] == "Sessions vs Prev"][0]
        assert f["id"] == "formula_Sessions_vs_Prev"
        col = [c for c in model["columns"] if c.get("formula_id") == f["id"]][0]
        assert col["name"] == "Sessions vs Prev"
        assert col["properties"]["column_type"] == "MEASURE"
        # WoW Raw no longer in omitted; Vs First still is
        omitted = [o["formula"] for o in summary["omitted_formulas"]]
        assert all("Vs First" in o or "LOOKUP" in o for o in omitted)


def test_decision_skip_recorded():
    decisions = {"Vs First": {"action": "skip", "reason": "no model equivalent; use Answer-level growth"}}
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(_judgment_parsed(), _judgment_translated(),
                               "C", "D", "S", None, tmpdir, decisions=decisions)
        assert summary["skipped_by_decision"] == [{
            "model": "Funnel", "caption": "Vs First",
            "reason": "no model equivalent; use Answer-level growth"}]
        # decided formulas don't reappear in decisions-needed
        needed = json.load(open(os.path.join(tmpdir, "decisions-needed.json")))
        assert {f["caption"] for f in needed["formulas"]} == {"WoW Raw"}


def test_decision_with_unknown_ref_rejected():
    decisions = {"WoW Raw": {
        "action": "use_expr",
        "expr": "sum ( [SESIONS] ) / sum ( [PREV_SESSIONS] )",  # typo ref
    }}
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(_judgment_parsed(), _judgment_translated(),
                               "C", "D", "S", None, tmpdir, decisions=decisions)
        assert summary["invalid_decisions"] == [{
            "model": "Funnel", "caption": "WoW Raw", "unknown_refs": ["SESIONS"]}]
        model = yaml.safe_load(open(os.path.join(tmpdir, "Funnel.model.tml")))["model"]
        assert not any(f["name"] == "WoW Raw" for f in model.get("formulas", []))


def test_formula_refs_rewritten_to_sanitized_ids():
    ds = {
        "calculated_fields": [
            _calc("Select Visitors", "IF 1=1 THEN [V] END", level=0),
            _calc("Delta", "[Calculation_1] - 1", level=1),
        ],
        "physical_columns": [_col("V", "integer", "Sum")],
    }
    fl = {
        "Select Visitors": [_formula_entry("Select Visitors", "if (1 = 1) then [V] else null")],
        "Delta": [_formula_entry("Delta", "[formula_Select Visitors] - 1")],
    }
    tml, _, _ = _build_model_tml("M", ["T1"], ds, fl, [])
    delta = [f for f in tml["model"]["formulas"] if f["name"] == "Delta"][0]
    assert delta["expr"] == "[formula_Select_Visitors] - 1"


# ---------------------------------------------------------------------------
# decisions-needed enrichment (dependency slice + worksheet usage)
# ---------------------------------------------------------------------------

def test_decisions_needed_includes_referenced_formulas_and_sheets():
    parsed = _judgment_parsed()
    parsed["formula_column_map"] = {"Calculation_A": "Base Sessions",
                                    "Calculation_B": "WoW Raw"}
    parsed["datasources"][0]["calculated_fields"] = [
        _calc("Base Sessions", "SUM([SESSIONS])"),
        {**_calc("WoW Raw", "ZN([Calculation_A]) / LOOKUP(ZN([Calculation_A]))"),
         "internal_name": "Calculation_B"},
    ]
    parsed["worksheets"] = [
        {"name": "Funnel Trend", "datasources": ["federated.j"],
         "fields": ["Calculation_B", "DATE_VALUE"],
         "rows": "[federated.j].[usr:Calculation_B:qk:3]",
         "cols": "[federated.j].[none:DATE_VALUE:nk]"},
        {"name": "Unrelated", "datasources": ["federated.j"],
         "fields": ["SESSIONS"], "rows": "", "cols": ""},
    ]
    translated = {"formulas": [
        _formula_entry("Base Sessions", "sum ( [SESSIONS] )"),
        _formula_entry("WoW Raw", "", tier="untranslatable"),
    ]}
    with tempfile.TemporaryDirectory() as tmpdir:
        run_generate(parsed, translated, "C", "D", "S", None, tmpdir)
        needed = json.load(open(os.path.join(tmpdir, "decisions-needed.json")))
        entry = [f for f in needed["formulas"] if f["caption"] == "WoW Raw"][0]
        assert entry["referenced_formulas"] == {"Base Sessions": "sum ( [SESSIONS] )"}
        assert entry["used_in_sheets"] == [
            {"sheet": "Funnel Trend", "rows": "usr(WoW Raw)", "cols": "DATE_VALUE"}]


def test_decision_approve_keeps_auto_expr_and_silences_relisting():
    parsed = _judgment_parsed()
    translated = {"formulas": [
        _formula_entry("WoW Raw", "sum ( [SESSIONS] )", tier="query_time"),
        _formula_entry("Vs First", "", tier="untranslatable"),
    ]}
    # query_time entries are non-deterministic → listed as included_auto
    for f in translated["formulas"]:
        f["deterministic"] = False
    decisions = {"WoW Raw": {"action": "approve"}}
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(parsed, translated, "C", "D", "S", None, tmpdir,
                               decisions=decisions)
        model = yaml.safe_load(open(os.path.join(tmpdir, "Funnel.model.tml")))["model"]
        f = [x for x in model["formulas"] if x["name"] == "WoW Raw"][0]
        assert f["expr"] == "sum ( [SESSIONS] )"  # auto expr kept
        # approved formula no longer listed; undecided one still is
        needed = json.load(open(os.path.join(tmpdir, "decisions-needed.json")))
        assert {x["caption"] for x in needed["formulas"]} == {"Vs First"}


# ---------------------------------------------------------------------------
# _load_full_table_map
# ---------------------------------------------------------------------------

class TestLoadFullTableMap:
    def test_preserves_full_paths(self, tmp_path):
        f = tmp_path / "map.txt"
        f.write_text(
            "DATA_SCIENCE.CUSTOMER_SEGMENTS - STG.RPT.VW_CUST\n"
            "PRD.DATA_SCIENCE.CAMPAIGNS : STG.RPT.VW_CAMP\n"
        )
        pairs = _load_full_table_map(str(f))
        assert pairs == [
            ("DATA_SCIENCE.CUSTOMER_SEGMENTS", "STG.RPT.VW_CUST"),
            ("PRD.DATA_SCIENCE.CAMPAIGNS", "STG.RPT.VW_CAMP"),
        ]

    def test_skips_blank_and_comment_lines(self, tmp_path):
        f = tmp_path / "map.txt"
        f.write_text("# comment\n\nA.B - C.D.E\n")
        assert len(_load_full_table_map(str(f))) == 1


# ---------------------------------------------------------------------------
# _remap_sql_query — table remapping
# ---------------------------------------------------------------------------

class TestRemapSqlQuery:
    def test_two_part_source_matches_three_part_sql(self):
        sql = "SELECT * FROM PRD_DL.DATA_SCIENCE.CUSTOMER_SEGMENTS WHERE 1=1"
        mapping = [("DATA_SCIENCE.CUSTOMER_SEGMENTS", "STG.RPT.VW_CUST")]
        result, warnings = _remap_sql_query(sql, mapping)
        assert "STG.RPT.VW_CUST" in result
        assert "PRD_DL.DATA_SCIENCE" not in result
        assert any(w['type'] == 'table_remapped_in_sql' for w in warnings)

    def test_three_part_source_exact_match(self):
        sql = "SELECT * FROM PRD.SCHEMA.TABLE1 t"
        mapping = [("PRD.SCHEMA.TABLE1", "NEW_DB.NEW_SCH.NEW_TBL")]
        result, _ = _remap_sql_query(sql, mapping)
        assert "NEW_DB.NEW_SCH.NEW_TBL" in result
        assert "PRD.SCHEMA.TABLE1" not in result

    def test_quoted_identifiers(self):
        sql = 'SELECT * FROM "PRD"."DATA_SCIENCE"."CUST_SEG"'
        mapping = [("DATA_SCIENCE.CUST_SEG", "STG.RPT.VW_CUST")]
        result, warnings = _remap_sql_query(sql, mapping)
        assert "STG.RPT.VW_CUST" in result
        assert len(warnings) == 1

    def test_two_part_source_without_db_prefix(self):
        sql = "SELECT * FROM DATA_SCIENCE.CUSTOMER_SEGMENTS"
        mapping = [("DATA_SCIENCE.CUSTOMER_SEGMENTS", "STG.RPT.VW_CUST")]
        result, _ = _remap_sql_query(sql, mapping)
        assert result == "SELECT * FROM STG.RPT.VW_CUST"

    def test_multiple_tables_remapped(self):
        sql = "SELECT a.*, b.* FROM DB.S.T1 a JOIN DB.S.T2 b ON a.id = b.id"
        mapping = [("S.T1", "NEW.S.V1"), ("S.T2", "NEW.S.V2")]
        result, warnings = _remap_sql_query(sql, mapping)
        assert "NEW.S.V1" in result
        assert "NEW.S.V2" in result
        assert len([w for w in warnings if w['type'] == 'table_remapped_in_sql']) == 2

    def test_longer_source_wins_over_shorter(self):
        sql = "SELECT * FROM DB.SCHEMA.CAMPAIGNS"
        mapping = [
            ("CAMPAIGNS", "SHORT_MATCH"),
            ("SCHEMA.CAMPAIGNS", "LONG_MATCH"),
        ]
        result, _ = _remap_sql_query(sql, mapping)
        assert "LONG_MATCH" in result
        assert "SHORT_MATCH" not in result

    def test_no_match_leaves_sql_unchanged(self):
        sql = "SELECT * FROM SOME_TABLE"
        mapping = [("OTHER_TABLE", "MAPPED")]
        result, warnings = _remap_sql_query(sql, mapping)
        assert result == sql
        assert len(warnings) == 0

    def test_case_insensitive_match(self):
        sql = "SELECT * FROM data_science.customer_segments"
        mapping = [("DATA_SCIENCE.CUSTOMER_SEGMENTS", "STG.RPT.VW_CUST")]
        result, warnings = _remap_sql_query(sql, mapping)
        assert "STG.RPT.VW_CUST" in result
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# _remap_sql_query — Tableau parameter stripping
# ---------------------------------------------------------------------------

class TestRemapSqlParams:
    def test_param_replaced_with_null(self):
        sql = "SELECT * FROM T WHERE col = <[Parameters].[Month A]>"
        result, warnings = _remap_sql_query(sql, [])
        assert "<[Parameters]" not in result
        assert "NULL" in result
        assert any(w['type'] == 'param_removed_from_sql' for w in warnings)
        assert warnings[0]['parameter'] == 'Month A'

    def test_multiple_params_replaced(self):
        sql = (
            "WHERE a.month = <[Parameters].[Month A]> "
            "AND b.month = <[Parameters].[Month B]>"
        )
        result, warnings = _remap_sql_query(sql, [])
        assert result == "WHERE a.month = NULL AND b.month = NULL"
        param_warnings = [w for w in warnings if w['type'] == 'param_removed_from_sql']
        assert len(param_warnings) == 2

    def test_no_params_no_warning(self):
        sql = "SELECT * FROM T"
        result, warnings = _remap_sql_query(sql, [])
        assert result == sql
        assert len(warnings) == 0

    def test_combined_remap_and_param_strip(self):
        sql = (
            "SELECT * FROM DB.SCH.TBL "
            "WHERE x = <[Parameters].[P1]>"
        )
        mapping = [("SCH.TBL", "NEW.S.V")]
        result, warnings = _remap_sql_query(sql, mapping)
        assert "NEW.S.V" in result
        assert "NULL" in result
        assert "<[Parameters]" not in result
        assert len(warnings) == 2


# ---------------------------------------------------------------------------
# run_generate — SQL view remapping integration
# ---------------------------------------------------------------------------

class TestRunGenerateSqlRemap:
    def test_sql_view_query_remapped(self):
        parsed = {
            "datasources": [{
                "name": "DS1", "caption": "Test DS",
                "tables": [{
                    "relation_name": "Custom SQL Query",
                    "physical_table": "Custom SQL Query",
                    "type": "text",
                    "sql_query": "SELECT * FROM PRD.DATA_SCIENCE.CUST_SEG",
                }],
                "physical_columns": [_col("ID", parent_table="Custom SQL Query")],
                "calculated_fields": [],
                "joins": [],
            }],
        }
        translated = {"formulas": []}
        sql_map = [("DATA_SCIENCE.CUST_SEG", "STG.RPT.VW_CUST")]

        with tempfile.TemporaryDirectory() as tmpdir:
            summary = run_generate(
                parsed, translated, "CONN", "DB", "SCH", None, tmpdir,
                sql_table_map=sql_map,
            )
            assert len(summary['sql_views']) == 1
            tml_path = os.path.join(tmpdir, summary['sql_views'][0]['file'])
            tml = yaml.safe_load(open(tml_path))
            assert "STG.RPT.VW_CUST" in tml['sql_view']['sql_query']
            assert "PRD.DATA_SCIENCE" not in tml['sql_view']['sql_query']
            assert len(summary['sql_remaps']) > 0

    def test_sql_view_params_stripped(self):
        parsed = {
            "datasources": [{
                "name": "DS1", "caption": "Cohorts",
                "tables": [{
                    "relation_name": "Custom SQL Query",
                    "physical_table": "Custom SQL Query",
                    "type": "text",
                    "sql_query": (
                        "SELECT * FROM T "
                        "WHERE m = <[Parameters].[Month A]>"
                    ),
                }],
                "physical_columns": [_col("ID", parent_table="Custom SQL Query")],
                "calculated_fields": [],
                "joins": [],
            }],
        }
        translated = {"formulas": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            summary = run_generate(
                parsed, translated, "CONN", "DB", "SCH", None, tmpdir,
                sql_table_map=[],
            )
            tml_path = os.path.join(tmpdir, summary['sql_views'][0]['file'])
            tml = yaml.safe_load(open(tml_path))
            assert "<[Parameters]" not in tml['sql_view']['sql_query']
            assert "NULL" in tml['sql_view']['sql_query']
            param_remaps = [w for w in summary['sql_remaps']
                           if w['type'] == 'param_removed_from_sql']
            assert len(param_remaps) == 1


# ---------------------------------------------------------------------------
# Connection table fuzzy matching (no table map)
# ---------------------------------------------------------------------------

def test_build_connection_table_index():
    idx = _build_connection_table_index([
        "VW_ORDERS_RPT", "DIM_CUSTOMER", "fact_sales_daily",
    ])
    assert idx["VW_ORDERS_RPT"] == "VW_ORDERS_RPT"
    assert idx["DIM_CUSTOMER"] == "DIM_CUSTOMER"
    assert idx["FACT_SALES_DAILY"] == "fact_sales_daily"


def test_connection_table_match_upper_snake():
    """Tableau table 'Orders' matches connection table 'ORDERS' via normalization."""
    parsed = _sample_parsed()
    translated = _sample_translated()
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(
            parsed=parsed,
            translated=translated,
            connection="C",
            database="D",
            schema="S",
            table_map=None,
            out_dir=tmpdir,
            connection_tables=["ORDERS"],
        )
        assert summary["tables"][0]["name"] == "ORDERS"
        assert len(summary["connection_matched"]) == 1
        assert summary["connection_matched"][0]["matched"] == "ORDERS"


def test_connection_table_match_mixed_case():
    """Tableau 'orders' matches connection 'Orders_Table' when normalized keys match."""
    parsed = {
        "datasources": [{
            "name": "ds1", "caption": "DS1", "is_parameters": False,
            "tables": [{"relation_name": "my orders table", "physical_table": "my_orders_table"}],
            "physical_columns": [_col("ID", "integer", "Count", "my_orders_table")],
            "calculated_fields": [], "joins": [],
        }],
    }
    translated = {"formulas": []}
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(
            parsed=parsed, translated=translated,
            connection="C", database="D", schema="S",
            table_map=None, out_dir=tmpdir,
            connection_tables=["MY_ORDERS_TABLE"],
        )
        assert summary["tables"][0]["name"] == "MY_ORDERS_TABLE"
        assert len(summary["connection_matched"]) == 1


def test_connection_table_no_match_uses_raw_name():
    """When connection tables don't match, fall back to raw Tableau name."""
    parsed = _sample_parsed()
    translated = _sample_translated()
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(
            parsed=parsed, translated=translated,
            connection="C", database="D", schema="S",
            table_map=None, out_dir=tmpdir,
            connection_tables=["COMPLETELY_DIFFERENT"],
        )
        assert summary["tables"][0]["name"] == "ORDERS"
        assert len(summary["connection_matched"]) == 0


def test_table_map_takes_precedence_over_connection_tables():
    """Explicit table_map entries win over connection table matching."""
    parsed = _sample_parsed()
    translated = _sample_translated()
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = run_generate(
            parsed=parsed, translated=translated,
            connection="C", database="D", schema="S",
            table_map={"ORDERS": "VW_ORDERS_RPT"},
            out_dir=tmpdir,
            connection_tables=["ORDERS"],
        )
        assert summary["tables"][0]["name"] == "VW_ORDERS_RPT"
        assert len(summary["connection_matched"]) == 0
