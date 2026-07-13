"""Unit tests for ts_cli.promote — pure formula-promotion merge (BL-066).

Pure-function tests — no ThoughtSpot connection required.
"""
from ts_cli.promote import (
    build_merged_model,
    detect_duplicates,
    detect_param_duplicates,
    extract_answer_formulas,
    find_formula_dependencies,
    find_param_dependencies,
    map_references,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _answer_tml(formulas=None, parameters=None, tables=None):
    return {
        "answer": {
            "formulas": formulas or [],
            "parameters": parameters or [],
            "tables": tables or [{"name": "Model A", "fqn": "guid-model-a"}],
        }
    }


def _model_tml(formulas=None, columns=None, model_tables=None, parameters=None, guid=None):
    tml = {
        "model": {
            "formulas": formulas or [],
            "columns": columns or [],
            "model_tables": model_tables or [{"name": "FACT_ORDERS"}],
            "parameters": parameters or [],
        }
    }
    if guid:
        tml["guid"] = guid
    return tml


# ---------------------------------------------------------------------------
# extract_answer_formulas
# ---------------------------------------------------------------------------

def test_extract_answer_formulas_basic():
    tml = _answer_tml(
        formulas=[
            {"name": "Profit", "id": "formula_Profit", "expr": "[Revenue] - [Cost]"},
            {"name": "Auto", "id": "formula_Auto", "expr": "([Count])", "was_auto_generated": True},
        ],
        parameters=[{"name": "today", "data_type": "DATE"}],
        tables=[{"name": "Sales Model", "fqn": "guid-123"}],
    )
    result = extract_answer_formulas(tml)
    assert len(result["formulas"]) == 2
    assert result["formulas"][0]["name"] == "Profit"
    assert result["formulas"][1]["was_auto_generated"] is True
    assert result["data_source_guid"] == "guid-123"
    assert result["data_source_name"] == "Sales Model"
    assert len(result["parameters"]) == 1


def test_extract_answer_formulas_empty():
    tml = {"answer": {"formulas": [], "parameters": [], "tables": []}}
    result = extract_answer_formulas(tml)
    assert result["formulas"] == []
    assert result["data_source_guid"] is None


# ---------------------------------------------------------------------------
# detect_duplicates
# ---------------------------------------------------------------------------

def test_detect_duplicates_no_collision():
    formulas = [{"name": "Profit", "expr": "[Revenue] - [Cost]"}]
    model = _model_tml(formulas=[{"name": "Revenue", "id": "formula_Revenue", "expr": "[Amount]"}])
    result = detect_duplicates(formulas, model)
    assert len(result["to_add"]) == 1
    assert result["skipped"] == []
    assert result["to_overwrite"] == []


def test_detect_duplicates_skip_policy():
    formulas = [
        {"name": "Revenue", "expr": "sum([Amount])"},
        {"name": "Profit", "expr": "[Revenue] - [Cost]"},
    ]
    model = _model_tml(formulas=[{"name": "Revenue", "id": "formula_Revenue", "expr": "[Amount]"}])
    result = detect_duplicates(formulas, model, policy="skip")
    assert len(result["to_add"]) == 1
    assert result["to_add"][0]["name"] == "Profit"
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["name"] == "Revenue"


def test_detect_duplicates_overwrite_policy():
    formulas = [{"name": "Revenue", "expr": "sum([Amount])"}]
    model = _model_tml(formulas=[{"name": "Revenue", "id": "formula_Revenue", "expr": "[Amount]"}])
    result = detect_duplicates(formulas, model, policy="overwrite")
    assert result["to_add"] == []
    assert result["skipped"] == []
    assert len(result["to_overwrite"]) == 1


# ---------------------------------------------------------------------------
# detect_param_duplicates
# ---------------------------------------------------------------------------

def test_detect_param_duplicates_skip():
    params = [{"name": "today", "data_type": "DATE"}]
    model = _model_tml(parameters=[{"name": "today", "data_type": "DATE"}])
    result = detect_param_duplicates(params, model, policy="skip")
    assert len(result["skipped"]) == 1
    assert result["to_add"] == []


def test_detect_param_duplicates_new():
    params = [{"name": "rate", "data_type": "INT64"}]
    model = _model_tml(parameters=[{"name": "today", "data_type": "DATE"}])
    result = detect_param_duplicates(params, model)
    assert len(result["to_add"]) == 1


# ---------------------------------------------------------------------------
# map_references
# ---------------------------------------------------------------------------

def test_map_references_class_a_formula_ref():
    """Class A: [token] matches an existing formula or one being promoted."""
    formulas = [{"name": "Margin", "id": "formula_Margin", "expr": "[Revenue] - [Cost]"}]
    model = _model_tml(
        formulas=[
            {"name": "Revenue", "id": "formula_Revenue", "expr": "sum([Amount])"},
            {"name": "Cost", "id": "formula_Cost", "expr": "sum([COST_AMOUNT])"},
        ],
    )
    result = map_references(formulas, model)
    assert result[0]["unresolved"] == []
    assert result[0]["rewrites"] == {}
    assert result[0]["rewritten_expr"] == "[Revenue] - [Cost]"


def test_map_references_class_b_valid_table_column():
    """Class B: [TABLE::column] with a valid table name."""
    formulas = [{"name": "Rev", "expr": "[FACT_ORDERS::AMOUNT]"}]
    model = _model_tml(model_tables=[{"name": "FACT_ORDERS"}])
    result = map_references(formulas, model)
    assert result[0]["unresolved"] == []


def test_map_references_class_b_invalid_table():
    """Class B: [TABLE::column] with an unknown table name."""
    formulas = [{"name": "Rev", "expr": "[UNKNOWN_TABLE::AMOUNT]"}]
    model = _model_tml(model_tables=[{"name": "FACT_ORDERS"}])
    result = map_references(formulas, model)
    assert result[0]["unresolved"] == ["UNKNOWN_TABLE::AMOUNT"]


def test_map_references_class_c_bare_name_resolved():
    """Class C: bare [Name] resolved via col_by_name."""
    formulas = [{"name": "Margin", "expr": "[Amount] + 1"}]
    model = _model_tml(
        columns=[{"name": "Amount", "column_id": "FACT_ORDERS::LINE_TOTAL"}],
    )
    result = map_references(formulas, model)
    assert result[0]["rewrites"] == {"[Amount]": "[FACT_ORDERS::LINE_TOTAL]"}
    assert result[0]["rewritten_expr"] == "[FACT_ORDERS::LINE_TOTAL] + 1"
    assert result[0]["unresolved"] == []


def test_map_references_class_c_unresolved():
    """Class C: bare [Name] not found anywhere."""
    formulas = [{"name": "Margin", "expr": "[Unknown Column] + 1"}]
    model = _model_tml()
    result = map_references(formulas, model)
    assert result[0]["unresolved"] == ["Unknown Column"]


def test_map_references_promoting_names_recognized():
    """A ref to another formula being promoted is Class A (no rewrite)."""
    formulas = [
        {"name": "Revenue", "id": "formula_Revenue", "expr": "sum([FACT_ORDERS::AMOUNT])"},
        {"name": "Margin", "id": "formula_Margin", "expr": "[Revenue] / 100"},
    ]
    model = _model_tml(model_tables=[{"name": "FACT_ORDERS"}])
    result = map_references(formulas, model)
    margin_result = next(r for r in result if r["name"] == "Margin")
    assert margin_result["unresolved"] == []
    assert margin_result["rewrites"] == {}


def test_map_references_param_recognized():
    """A ref to a model parameter is Class A (no rewrite)."""
    formulas = [{"name": "Growth", "expr": "[Revenue] * [rate]"}]
    model = _model_tml(
        formulas=[{"name": "Revenue", "id": "formula_Revenue", "expr": "sum([Amount])"}],
        parameters=[{"name": "rate", "data_type": "INT64"}],
    )
    result = map_references(formulas, model)
    assert result[0]["unresolved"] == []


def test_map_references_alias_table():
    """Table alias is recognized for Class B validation."""
    formulas = [{"name": "Rev", "expr": "[Orders::AMOUNT]"}]
    model = _model_tml(model_tables=[{"name": "FACT_ORDERS", "alias": "Orders"}])
    result = map_references(formulas, model)
    assert result[0]["unresolved"] == []


# ---------------------------------------------------------------------------
# build_merged_model
# ---------------------------------------------------------------------------

def test_build_merged_model_basic_add():
    model = _model_tml(
        formulas=[{"name": "Revenue", "id": "formula_Revenue", "expr": "sum([Amount])"}],
        columns=[
            {"name": "Revenue", "formula_id": "formula_Revenue",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        ],
        guid="guid-model",
    )
    to_add = [{"name": "Profit", "expr": "[Revenue] - [Cost]"}]
    ref_map = [{"name": "Profit", "rewritten_expr": "[Revenue] - [Cost]"}]

    result = build_merged_model(model, to_add, [], ref_map)

    assert len(result["added"]) == 1
    assert result["added"][0]["name"] == "Profit"
    assert result["added"][0]["column_type"] == "ATTRIBUTE"
    assert result["added"][0]["formula_id"] == "formula_Profit"
    assert result["overwritten"] == []

    merged = result["merged_tml"]
    m = merged["model"]
    assert len(m["formulas"]) == 2
    assert len(m["columns"]) == 2
    assert any(f["name"] == "Profit" for f in m["formulas"])


def test_build_merged_model_measure_classification():
    model = _model_tml(guid="guid-model")
    to_add = [{"name": "Total", "expr": "sum([FACT_ORDERS::AMOUNT])"}]
    ref_map = [{"name": "Total", "rewritten_expr": "sum([FACT_ORDERS::AMOUNT])"}]

    result = build_merged_model(model, to_add, [], ref_map)

    assert result["added"][0]["column_type"] == "MEASURE"
    assert result["added"][0]["aggregation"] == "SUM"

    m = result["merged_tml"]["model"]
    col = next(c for c in m["columns"] if c["name"] == "Total")
    assert col["properties"]["column_type"] == "MEASURE"
    assert col["properties"]["aggregation"] == "SUM"


def test_build_merged_model_overwrite():
    model = _model_tml(
        formulas=[
            {"name": "Revenue", "id": "formula_Revenue", "expr": "sum([Amount])"},
            {"name": "Profit", "id": "formula_Profit", "expr": "[Revenue] - [Old Cost]"},
        ],
        columns=[
            {"name": "Revenue", "formula_id": "formula_Revenue",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            {"name": "Profit", "formula_id": "formula_Profit",
             "properties": {"column_type": "ATTRIBUTE"}},
        ],
        guid="guid-model",
    )
    to_overwrite = [{"name": "Profit", "expr": "[Revenue] - [Cost]"}]
    ref_map = [{"name": "Profit", "rewritten_expr": "[Revenue] - [Cost]"}]

    result = build_merged_model(model, [], to_overwrite, ref_map)

    assert len(result["overwritten"]) == 1
    assert result["overwritten"][0]["name"] == "Profit"
    assert result["added"] == []

    m = result["merged_tml"]["model"]
    assert len(m["formulas"]) == 2
    profit_f = next(f for f in m["formulas"] if f["name"] == "Profit")
    assert profit_f["expr"] == "[Revenue] - [Cost]"


def test_build_merged_model_params():
    model = _model_tml(guid="guid-model")
    to_add = [{"name": "Growth", "expr": "[Revenue] * [rate]"}]
    ref_map = [{"name": "Growth", "rewritten_expr": "[Revenue] * [rate]"}]
    params = [{"name": "rate", "data_type": "INT64", "default_value": "40"}]

    result = build_merged_model(model, to_add, [], ref_map, params_to_add=params)

    assert len(result["params_added"]) == 1
    assert result["params_added"][0]["name"] == "rate"
    m = result["merged_tml"]["model"]
    assert len(m["parameters"]) == 1
    assert m["parameters"][0]["name"] == "rate"
    assert m["parameters"][0]["default_value"] == "40"


def test_build_merged_model_param_dynamic_default():
    model = _model_tml(guid="guid-model")
    to_add = [{"name": "Recent", "expr": "[Date] > [today]"}]
    ref_map = [{"name": "Recent", "rewritten_expr": "[Date] > [today]"}]
    params = [{"name": "today", "data_type": "DATE", "dynamic_default_date": "TODAY"}]

    result = build_merged_model(model, to_add, [], ref_map, params_to_add=params)

    m = result["merged_tml"]["model"]
    assert m["parameters"][0]["dynamic_default_date"] == "TODAY"


def test_build_merged_model_formula_id_dedup():
    """If formula_id would collide, disambiguate with _promoted suffix."""
    model = _model_tml(
        formulas=[{"name": "Other", "id": "formula_Profit", "expr": "[A]"}],
        columns=[{"name": "Other", "formula_id": "formula_Profit",
                  "properties": {"column_type": "ATTRIBUTE"}}],
        guid="guid-model",
    )
    to_add = [{"name": "Profit", "expr": "[Revenue] - [Cost]"}]
    ref_map = [{"name": "Profit", "rewritten_expr": "[Revenue] - [Cost]"}]

    result = build_merged_model(model, to_add, [], ref_map)

    assert result["added"][0]["formula_id"] == "formula_Profit_promoted"


def test_build_merged_model_yaml_starts_with_guid():
    model = _model_tml(guid="guid-abc-123")
    to_add = [{"name": "Test", "expr": "1 + 1"}]
    ref_map = [{"name": "Test", "rewritten_expr": "1 + 1"}]

    result = build_merged_model(model, to_add, [], ref_map)

    assert result["merged_yaml"].strip().startswith("guid:")


# ---------------------------------------------------------------------------
# find_param_dependencies
# ---------------------------------------------------------------------------

def test_find_param_dependencies_found():
    formulas = [{"name": "Growth", "expr": "[Revenue] * [rate]"}]
    params = [{"name": "rate", "data_type": "INT64"}, {"name": "unused", "data_type": "CHAR"}]
    result = find_param_dependencies(formulas, params)
    assert len(result) == 1
    assert result[0]["name"] == "rate"


def test_find_param_dependencies_none():
    formulas = [{"name": "Profit", "expr": "[Revenue] - [Cost]"}]
    params = [{"name": "rate", "data_type": "INT64"}]
    result = find_param_dependencies(formulas, params)
    assert result == []


# ---------------------------------------------------------------------------
# find_formula_dependencies
# ---------------------------------------------------------------------------

def test_find_formula_dependencies_found():
    all_formulas = [
        {"name": "Revenue", "id": "formula_Revenue", "expr": "sum([Amount])"},
        {"name": "Cost", "id": "formula_Cost", "expr": "sum([COST_AMOUNT])"},
        {"name": "Profit", "id": "formula_Profit", "expr": "[formula_Revenue] - [formula_Cost]"},
    ]
    selected = [all_formulas[2]]  # Profit only
    result = find_formula_dependencies(selected, all_formulas)
    dep_names = {d["name"] for d in result}
    assert dep_names == {"Revenue", "Cost"}


def test_find_formula_dependencies_none():
    all_formulas = [
        {"name": "Revenue", "id": "formula_Revenue", "expr": "sum([Amount])"},
    ]
    selected = [all_formulas[0]]
    result = find_formula_dependencies(selected, all_formulas)
    assert result == []


def test_find_formula_dependencies_by_name():
    """Dependencies can also be referenced by display name (not just id)."""
    all_formulas = [
        {"name": "Revenue", "id": "formula_Revenue", "expr": "sum([Amount])"},
        {"name": "Margin", "id": "formula_Margin", "expr": "[Revenue] / 100"},
    ]
    selected = [all_formulas[1]]  # Margin references [Revenue] by name
    result = find_formula_dependencies(selected, all_formulas)
    assert len(result) == 1
    assert result[0]["name"] == "Revenue"
