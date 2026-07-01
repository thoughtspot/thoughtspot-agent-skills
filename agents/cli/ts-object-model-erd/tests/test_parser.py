import os

import parser

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_load_tml_returns_dict():
    data = parser.load_tml(os.path.join(FIXTURES, "mini.model.tml"))
    assert data["model"]["name"] == "Mini Sales"
    assert data["guid"] == "model-guid-001"


def _mini_model():
    return parser.load_tml(os.path.join(FIXTURES, "mini.model.tml"))


def test_parse_model_tables_and_columns():
    m = parser.parse_model(_mini_model(), {})
    assert m["model"]["name"] == "Mini Sales"
    ids = {t["id"] for t in m["tables"]}
    assert ids == {"ORDERS", "CUSTOMER"}
    orders = next(t for t in m["tables"] if t["id"] == "ORDERS")
    amount = next(c for c in orders["cols"] if c["name"] == "Amount")
    assert amount["role"] == "MEASURE"
    assert amount["agg"] == "SUM"


def test_parse_model_classifies_fact_and_dim():
    m = parser.parse_model(_mini_model(), {})
    kinds = {t["id"]: t["kind"] for t in m["tables"]}
    assert kinds["ORDERS"] == "fact"
    assert kinds["CUSTOMER"] == "dim"


def test_parse_model_formula_bound_to_table():
    m = parser.parse_model(_mini_model(), {})
    orders = next(t for t in m["tables"] if t["id"] == "ORDERS")
    rev = next(c for c in orders["cols"] if c["name"] == "Revenue")
    assert rev["role"] == "FORMULA"
    assert m["formulas"]["Revenue"] == "sum ( [ORDERS::AMOUNT] )"


def test_parse_model_joins_default_unknown_without_tables():
    m = parser.parse_model(_mini_model(), {})
    j = next(j for j in m["joins"] if j["name"] == "ORDERS_to_CUSTOMER")
    assert j["from"] == "ORDERS" and j["to"] == "CUSTOMER"
    assert j["card"] == "UNKNOWN" and j["origin"] == "model"


def _mini_tables():
    return {
        "ORDERS": parser.load_tml(os.path.join(FIXTURES, "mini_orders.table.tml")),
        "CUSTOMER": parser.load_tml(os.path.join(FIXTURES, "mini_customer.table.tml")),
    }


def test_stitch_table_join_sets_origin_and_cardinality():
    m = parser.parse_model(_mini_model(), _mini_tables())
    j = next(j for j in m["joins"] if j["name"] == "ORDERS_to_CUSTOMER")
    assert j["origin"] == "table"
    assert j["card"] == "MANY_TO_ONE"
    assert j["type"] == "INNER"


def test_unmatched_join_stays_model_local():
    m = parser.parse_model(_mini_model(), _mini_tables())
    j = next(j for j in m["joins"] if j["name"] == "ORDERS_to_REGION_local")
    assert j["origin"] == "model"


def test_rls_extracted_from_table_tml():
    m = parser.parse_model(_mini_model(), _mini_tables())
    cust = next(t for t in m["tables"] if t["id"] == "CUSTOMER")
    assert len(cust["rls"]) == 1
    assert cust["rls"][0]["name"] == "Territory scope"
    assert "ts_user_territories" in cust["rls"][0]["expr"]


def test_join_keys_added_as_hidden_columns():
    m = parser.parse_model(_mini_model(), _mini_tables())
    orders = next(t for t in m["tables"] if t["id"] == "ORDERS")
    key = next(c for c in orders["cols"] if c["name"] == "CUSTOMER_CODE")
    assert key["key"] is True and key["hidden"] is True


def test_degraded_mode_logs_when_tables_missing():
    msgs = []
    parser.parse_model(_mini_model(), {}, log=msgs.append)
    assert any("degraded" in m.lower() for m in msgs)
