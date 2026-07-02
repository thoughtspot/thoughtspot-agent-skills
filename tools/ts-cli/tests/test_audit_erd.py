"""Tests for ts_cli.audit.erd — ERD data generation for audit reports."""
from ts_cli.audit.erd import parse_model, build_erd_for_audit
from ts_cli.audit.context import make_context


def _model_tml(name="TestModel", guid="m-1", tables=None, columns=None,
               formulas=None, joins=None):
    m = {"name": name, "model_tables": tables or []}
    if columns:
        m["columns"] = columns
    if formulas:
        m["formulas"] = formulas
    if joins:
        m["joins"] = joins
    return {"guid": guid, "model": m}


def _table_tml(name="DIM_A", joins_with=None, rls_rules=None):
    t = {"name": name}
    if joins_with:
        t["joins_with"] = joins_with
    if rls_rules:
        t["rls_rules"] = rls_rules
    return {"table": t}


def test_parse_model_basic():
    model = _model_tml(
        tables=[{"name": "FACT_SALES", "fqn": "db.sch.FACT_SALES"},
                {"name": "DIM_PRODUCT", "fqn": "db.sch.DIM_PRODUCT"}],
        columns=[
            {"name": "Revenue", "column_id": "FACT_SALES::revenue",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            {"name": "Product Name", "column_id": "DIM_PRODUCT::product_name",
             "properties": {}},
        ],
    )
    result = parse_model(model, {})
    assert result["model"]["name"] == "TestModel"
    assert result["model"]["guid"] == "m-1"
    assert len(result["tables"]) == 2

    fact = next(t for t in result["tables"] if t["id"] == "FACT_SALES")
    dim = next(t for t in result["tables"] if t["id"] == "DIM_PRODUCT")
    assert fact["kind"] == "fact"
    assert dim["kind"] == "dim"
    assert any(c["name"] == "Revenue" and c["role"] == "MEASURE" for c in fact["cols"])


def test_hidden_non_measure_formula_does_not_make_dim_a_fact():
    """A hidden attribute/boolean helper formula (RLS/parameter filter) must not
    promote a pure dimension to a fact. Regression for DM_CUSTOMER."""
    model = _model_tml(
        tables=[{"name": "FACT_SALES", "fqn": "db.sch.FACT_SALES"},
                {"name": "DIM_CUSTOMER", "fqn": "db.sch.DIM_CUSTOMER"}],
        formulas=[{"id": "f_filter", "name": "filterModel",
                   "expr": "if ( [code] = 'all' ) then true "
                           "else [DIM_CUSTOMER::CODE] = [code]"}],
        columns=[
            {"name": "Revenue", "column_id": "FACT_SALES::revenue",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            {"name": "Customer Name", "column_id": "DIM_CUSTOMER::name",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "filterModel", "formula_id": "f_filter",
             "properties": {"column_type": "ATTRIBUTE", "is_hidden": True}},
        ],
    )
    result = parse_model(model, {})
    cust = next(t for t in result["tables"] if t["id"] == "DIM_CUSTOMER")
    assert cust["kind"] == "dim"
    ff = next(c for c in cust["cols"] if c["name"] == "filterModel")
    assert ff["hidden"] is True and ff["is_measure"] is False


def test_parse_model_with_joins():
    model = _model_tml(
        tables=[
            {"name": "FACT_SALES", "fqn": "db.sch.FACT_SALES",
             "joins": [{"with": "DIM_PRODUCT", "referencing_join": "j1"}]},
            {"name": "DIM_PRODUCT", "fqn": "db.sch.DIM_PRODUCT"},
        ],
        columns=[
            {"name": "Revenue", "column_id": "FACT_SALES::revenue",
             "properties": {"column_type": "MEASURE"}},
        ],
    )
    table_tmls = {
        "DIM_PRODUCT": _table_tml("DIM_PRODUCT", joins_with=[{
            "name": "j1", "cardinality": "MANY_TO_ONE", "type": "LEFT_OUTER",
            "on": "[FACT_SALES::product_id] = [DIM_PRODUCT::id]",
        }]),
    }

    result = parse_model(model, table_tmls)
    assert len(result["joins"]) == 1
    j = result["joins"][0]
    assert j["from"] == "FACT_SALES"
    assert j["to"] == "DIM_PRODUCT"
    assert j["card"] == "MANY_TO_ONE"
    assert j["origin"] == "table"


def test_parse_model_rls():
    model = _model_tml(
        tables=[{"name": "FACT_SALES", "fqn": "db.sch.FACT_SALES"},
                {"name": "DIM_REGION", "fqn": "db.sch.DIM_REGION"}],
        columns=[
            {"name": "Amount", "column_id": "FACT_SALES::amount",
             "properties": {"column_type": "MEASURE"}},
        ],
    )
    table_tmls = {
        "FACT_SALES": _table_tml("FACT_SALES", rls_rules=[{
            "name": "Region filter",
            "expression": "[DIM_REGION::region] = ts_username",
        }]),
    }
    result = parse_model(model, table_tmls)
    fact = next(t for t in result["tables"] if t["id"] == "FACT_SALES")
    assert len(fact["rls"]) == 1
    dim = next(t for t in result["tables"] if t["id"] == "DIM_REGION")
    assert dim["in_rls_path"] is True


def test_parse_model_sql_view():
    model = _model_tml(
        tables=[{"name": "SALES_VIEW", "fqn": "db.sch.SALES_VIEW"}],
        columns=[],
    )
    table_tmls = {
        "SALES_VIEW": {"sql_view": {"name": "SALES_VIEW",
                                     "sql_query": "SELECT * FROM sales"}},
    }
    result = parse_model(model, table_tmls)
    t = result["tables"][0]
    assert t["is_sql_view"] is True
    assert t["sql_query"] == "SELECT * FROM sales"


def test_parse_model_alias():
    model = _model_tml(
        tables=[{"name": "MY_ALIAS", "fqn": "db.sch.REAL_TABLE"}],
        columns=[],
    )
    table_tmls = {
        "MY_ALIAS": _table_tml("REAL_TABLE"),
    }
    result = parse_model(model, table_tmls)
    assert result["tables"][0]["alias_of"] == "REAL_TABLE"


def test_build_erd_for_audit():
    model = _model_tml(
        tables=[{"name": "T1", "fqn": "db.sch.T1"}],
        columns=[{"name": "c1", "column_id": "T1::c1", "properties": {}}],
    )
    ctx = make_context(
        models=[model],
        tables={"db.sch.T1": _table_tml("T1")},
    )
    results = build_erd_for_audit(ctx)
    assert len(results) == 1
    assert results[0]["model"]["name"] == "TestModel"
    assert len(results[0]["tables"]) == 1
