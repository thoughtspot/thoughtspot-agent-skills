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


def test_hidden_non_measure_formula_does_not_make_dim_a_fact():
    """A hidden boolean/attribute helper formula (e.g. an RLS/parameter filter)
    must not promote a pure dimension to a fact. Regression for DM_CUSTOMER."""
    model = _mini_model()
    model["model"]["formulas"].append(
        {"id": "formula_filter", "name": "filterModel",
         "expr": "if ( [customerCode] = 'all' ) then true "
                 "else [CUSTOMER::CODE] = [customerCode]"}
    )
    model["model"]["columns"].append(
        {"name": "filterModel", "formula_id": "formula_filter",
         "properties": {"column_type": "ATTRIBUTE", "is_hidden": True}}
    )
    m = parser.parse_model(model, {})
    customer = next(t for t in m["tables"] if t["id"] == "CUSTOMER")
    assert customer["kind"] == "dim"
    ff = next(c for c in customer["cols"] if c["name"] == "filterModel")
    assert ff["hidden"] is True
    assert ff["is_measure"] is False
    assert ff["role"] == "FORMULA"  # display role preserved (ƒ badge)


def test_dimension_with_outgoing_join_is_not_a_fact():
    """A pure dimension that merely joins out to another table (e.g. USER -> EVENT)
    must not be classified a fact. Regression for GTM Campaigns TS_USER."""
    model = {"guid": "g", "model": {
        "name": "M",
        "model_tables": [
            {"name": "USER", "joins": [{"with": "EVENT", "referencing_join": "j1"}]},
            {"name": "EVENT"},
        ],
        "columns": [
            {"name": "User Name", "column_id": "USER::name",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Amount", "column_id": "EVENT::amt",
             "properties": {"column_type": "MEASURE"}},
        ],
    }}
    kinds = {t["id"]: t["kind"] for t in parser.parse_model(model, {})["tables"]}
    assert kinds["USER"] == "dim"    # outgoing join alone must not make it a fact
    assert kinds["EVENT"] == "fact"  # has a real measure


def test_measureless_passthrough_is_a_bridge():
    """A measureless table that both receives and emits a join is a bridge."""
    model = {"guid": "g", "model": {
        "name": "M",
        "model_tables": [
            {"name": "FACT", "joins": [{"with": "BRIDGE", "referencing_join": "j1"}]},
            {"name": "BRIDGE", "joins": [{"with": "DIM", "referencing_join": "j2"}]},
            {"name": "DIM"},
        ],
        "columns": [
            {"name": "Amt", "column_id": "FACT::amt",
             "properties": {"column_type": "MEASURE"}},
            {"name": "BName", "column_id": "BRIDGE::n",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "DName", "column_id": "DIM::n",
             "properties": {"column_type": "ATTRIBUTE"}},
        ],
    }}
    kinds = {t["id"]: t["kind"] for t in parser.parse_model(model, {})["tables"]}
    assert kinds["FACT"] == "fact"
    assert kinds["BRIDGE"] == "bridge"
    assert kinds["DIM"] == "dim"


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


def test_join_to_table_absent_from_model_is_dropped():
    """A join whose `with:` target is not a table in the model (here REGION, which
    the mini fixture references but never lists in model_tables) cannot occur in a
    valid ThoughtSpot export. If malformed TML contains one, the parser drops it —
    rather than emitting a join with a non-existent endpoint that the viewer would
    have to defend against — and logs the drop. Regression for the GTM investigation
    (the crash was actually aliased joins, not this; this guards genuinely broken TML)."""
    msgs = []
    m = parser.parse_model(_mini_model(), _mini_tables(), log=msgs.append)
    names = {j["name"] for j in m["joins"]}
    assert "ORDERS_to_REGION_local" not in names   # dropped (REGION not in model_tables)
    assert "ORDERS_to_CUSTOMER" in names            # a real join is unaffected
    assert any("ORDERS_to_REGION_local" in msg and "malformed" in msg for msg in msgs)


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


def test_in_rls_path_detected():
    m = parser.parse_model(_mini_model(), _mini_tables())
    orders = next(t for t in m["tables"] if t["id"] == "ORDERS")
    cust = next(t for t in m["tables"] if t["id"] == "CUSTOMER")
    assert orders["in_rls_path"] is True
    assert cust["in_rls_path"] is False


def test_sql_view_detected():
    sql_view_tml = {
        "guid": "sv-001",
        "sql_view": {
            "name": "REVENUE_VIEW",
            "sql_query": "SELECT * FROM raw.orders",
        },
    }
    model_tml = {
        "guid": "m-sv",
        "model": {
            "name": "SV Test",
            "model_tables": [{"name": "REVENUE_VIEW"}],
            "columns": [],
        },
    }
    m = parser.parse_model(model_tml, {"REVENUE_VIEW": sql_view_tml})
    t = m["tables"][0]
    assert t["is_sql_view"] is True
    assert "SELECT" in t["sql_query"]


def test_aliased_model_tables_are_distinct_nodes_and_joins_resolve():
    """The same physical table joined multiple times is distinguished by an
    `alias:` field on the model_table, and a join's `with:` references that
    alias. Each alias must become its own node, and EVERY join endpoint must
    resolve to a real node id — the viewer indexes adjacency by node id and
    throws (`Cannot read properties of undefined`) on a dangling endpoint.
    Regression for the GTM model (SFDC_OPPORTUNITY_1/_2/_3)."""
    model = {"guid": "g", "model": {
        "name": "M",
        "model_tables": [
            {"name": "FACT", "joins": [
                {"with": "OPP_1", "referencing_join": "j1", "type": "RIGHT_OUTER"},
                {"with": "OPP_2", "referencing_join": "j2", "type": "RIGHT_OUTER"},
            ]},
            {"name": "OPP"},                    # base (un-aliased) instance
            {"name": "OPP", "alias": "OPP_1"},  # alias instance 1
            {"name": "OPP", "alias": "OPP_2"},  # alias instance 2
        ],
        "columns": [
            {"name": "Amt", "column_id": "FACT::amt",
             "properties": {"column_type": "MEASURE"}},
            {"name": "Stage", "column_id": "OPP_1::stage",
             "properties": {"column_type": "ATTRIBUTE"}},
        ],
    }}
    m = parser.parse_model(model, {})
    ids = {t["id"] for t in m["tables"]}
    assert {"FACT", "OPP", "OPP_1", "OPP_2"} <= ids
    # No dangling join endpoints — this is what crashed the viewer.
    for j in m["joins"]:
        assert j["from"] in ids, f"join {j['name']} from {j['from']} dangling"
        assert j["to"] in ids, f"join {j['name']} to {j['to']} dangling"
    # An alias node carries the columns whose column_id is prefixed by the alias.
    opp1 = next(t for t in m["tables"] if t["id"] == "OPP_1")
    assert any(c["name"] == "Stage" for c in opp1["cols"])
    # Alias nodes record their physical table even without a Table TML.
    assert opp1["alias_of"] == "OPP"


def test_alias_detected():
    table_tml = {
        "guid": "tbl-001",
        "table": {"name": "PHYSICAL_TABLE", "columns": []},
    }
    model_tml = {
        "guid": "m-alias",
        "model": {
            "name": "Alias Test",
            "model_tables": [{"name": "MY_ALIAS"}],
            "columns": [],
        },
    }
    m = parser.parse_model(model_tml, {"MY_ALIAS": table_tml})
    assert m["tables"][0]["alias_of"] == "PHYSICAL_TABLE"
