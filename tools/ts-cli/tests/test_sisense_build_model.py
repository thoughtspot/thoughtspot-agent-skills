"""Unit tests for ts_cli.sisense.build_model — model assembly.

Pure functions, no live cluster. A tiny synthetic inventory exercises: most-connected
table = fact join orientation, default MANY_TO_ONE cardinality, the connection-name-only
invariant, the duplicate-column -> fact dedup (dimension-side duplicate dropped), and
calc-column formula translation (Migrated emitted, NEEDS REVIEW recorded but not emitted).
"""
from ts_cli.sisense.build_model import assemble
from ts_cli.sisense.tables import _col_role


def _inv():
    return {
        "source": "Sales",
        "tables": [
            {"id": "Fact.csv", "name": "Fact", "columns": [
                {"id": "Amount", "name": "Amount", "data_type": "double", "calculated": False},
                {"id": "Dim1Id", "name": "Dim1Id", "data_type": "int64", "calculated": False},
                {"id": "Dim2Id", "name": "Dim2Id", "data_type": "int64", "calculated": False},
                {"id": "Cat", "name": "Cat", "data_type": "string", "calculated": False},
                {"id": "Margin", "name": "Margin", "data_type": "double",
                 "calculated": True, "expression": "sum([Amount])"},
                {"id": "Ranked", "name": "Ranked", "data_type": "double",
                 "calculated": True, "expression": "rank([Amount])"},
            ]},
            {"id": "Dim1.csv", "name": "Dim1", "columns": [
                {"id": "Dim1Id", "name": "Dim1Id", "data_type": "int64", "calculated": False},
                {"id": "Name", "name": "Name", "data_type": "string", "calculated": False},
                {"id": "Cat", "name": "Cat", "data_type": "string", "calculated": False},
            ]},
            {"id": "Dim2.csv", "name": "Dim2", "columns": [
                {"id": "Dim2Id", "name": "Dim2Id", "data_type": "int64", "calculated": False},
                {"id": "Label", "name": "Label", "data_type": "string", "calculated": False},
            ]},
        ],
        "relations": [
            {"endpoints": [{"table": "Dim1.csv", "column": "Dim1Id"},
                           {"table": "Fact.csv", "column": "Dim1Id"}], "cardinality": "UNKNOWN"},
            {"endpoints": [{"table": "Dim2.csv", "column": "Dim2Id"},
                           {"table": "Fact.csv", "column": "Dim2Id"}], "cardinality": "UNKNOWN"},
        ],
        "warnings": [],
    }


def _build():
    files, mapping = assemble(_inv(), {}, "MyConn", "db1", "sch1", "LEFT_OUTER", False)
    model = next(tml for fn, tml in files if fn.endswith(".model.tml"))["model"]
    tables = [tml for fn, tml in files if fn.endswith(".table.tml")]
    return files, mapping, model, tables


def test_files_emitted():
    files, _, _, tables = _build()
    assert len(tables) == 3                                # Fact + Dim1 + Dim2
    assert sum(1 for fn, _ in files if fn.endswith(".model.tml")) == 1


def test_calc_column_name_collision_preserves_physical():
    # A calc column named the same as a physical column must NOT shadow/drop the base column:
    # the formula is renamed "<name> (Calc)" and its expr still references the physical [Amount].
    inv = {
        "source": "S", "relations": [],
        "tables": [{"id": "F.csv", "name": "F", "columns": [
            {"id": "Amount", "name": "Amount", "data_type": "double", "calculated": False},
            {"id": "AmountCalc", "name": "Amount", "data_type": "double",
             "calculated": True, "expression": "if([Amount] > 0, [Amount], 0)"},
        ]}],
        "warnings": [],
    }
    files, _ = assemble(inv, {}, "C", "db", "sch", "LEFT_OUTER", False)
    model = next(tml for fn, tml in files if fn.endswith(".model.tml"))["model"]
    formulas = {f["name"]: f for f in model.get("formulas", [])}
    assert "Amount (Calc)" in formulas                     # de-collided
    # the physical [Amount] reference survives (was NOT rewritten to a self-ref [formula_Amount])
    assert "[Amount]" in formulas["Amount (Calc)"]["expr"]
    assert "[formula_Amount]" not in formulas["Amount (Calc)"]["expr"]
    # the physical Amount column still exists on the model
    assert any(c["name"] == "Amount" and "formula_id" not in c for c in model["columns"])


def test_join_orientation_and_cardinality():
    _, _, model, _ = _build()
    joins = {t["name"]: t.get("joins", []) for t in model["model_tables"]}
    # Fact is most-connected -> it is the source side of both joins.
    assert len(joins["Fact"]) == 2
    assert joins["Dim1"] == []
    assert joins["Dim2"] == []
    j = {jj["with"]: jj for jj in joins["Fact"]}
    assert j["Dim1"]["cardinality"] == "MANY_TO_ONE"      # UNKNOWN in file -> default
    assert j["Dim1"]["type"] == "LEFT_OUTER"
    assert j["Dim1"]["on"] == "[Fact::Dim1Id] = [Dim1::Dim1Id]"


def test_duplicate_column_bound_to_fact():
    _, _, model, _ = _build()
    cols = {c["name"]: c for c in model["columns"]}
    # "Cat" exists in both Fact (score 2) and Dim1 (score 1) -> single column, bound to Fact.
    cat = [c for c in model["columns"] if c["name"] == "Cat"]
    assert len(cat) == 1
    assert cat[0]["column_id"] == "Fact::Cat"             # dimension-side duplicate dropped


def test_connection_name_only_no_fqn():
    _, _, _, tables = _build()
    conn = tables[0]["table"]["connection"]
    assert conn == {"name": "MyConn"}                     # repo invariant: name only, never fqn
    assert "fqn" not in conn


def test_db_table_strips_csv():
    _, _, _, tables = _build()
    fact = next(t for t in tables if t["table"]["name"] == "Fact")
    assert fact["table"]["db_table"] == "Fact"           # .csv stripped, not lowered (flag off)


def test_calc_column_formula_migrated():
    _, mapping, model, _ = _build()
    fmap = {f["name"]: f["expr"] for f in model.get("formulas", [])}
    assert fmap["Margin"] == "sum([Amount])"
    rows = {m["name"]: m for m in mapping["measures"]}
    assert rows["Margin"]["status"] == "Migrated"


def test_calc_column_needs_review_not_emitted():
    _, mapping, model, _ = _build()
    emitted = {f["name"] for f in model.get("formulas", [])}
    rows = {m["name"]: m for m in mapping["measures"]}
    assert "Ranked" not in emitted                        # rank() -> NEEDS REVIEW
    assert rows["Ranked"]["status"] == "NEEDS REVIEW"
    assert rows["Ranked"]["ts_formula"] == ""


def test_spotter_enabled_by_default():
    _, _, model, _ = _build()
    assert model["properties"]["spotter_config"]["is_spotter_enabled"] is True


# --------------------------------------------------------------------------- #
# Reviewer findings 3, 5, 6, 8
# --------------------------------------------------------------------------- #
def _run(inv):
    """assemble a synthetic inventory -> (mapping, model)."""
    files, mapping = assemble(inv, {}, "MyConn", "db1", "sch1", "LEFT_OUTER", False)
    model = next(tml for fn, tml in files if fn.endswith(".model.tml"))["model"]
    return mapping, model


def _composite_inv():
    """Fact joined to Store on a TWO-column key (StoreId, Region) + a simple key to Ext so
    the fact is unambiguously most-connected. Cardinality is explicit (not defaulted)."""
    return {
        "source": "Comp",
        "tables": [
            {"id": "Fact.csv", "name": "Fact", "columns": [
                {"id": "StoreId", "name": "StoreId", "data_type": "int64", "calculated": False},
                {"id": "Region", "name": "Region", "data_type": "string", "calculated": False},
                {"id": "ExtraId", "name": "ExtraId", "data_type": "int64", "calculated": False},
                {"id": "Amount", "name": "Amount", "data_type": "double", "calculated": False},
            ]},
            {"id": "Store.csv", "name": "Store", "columns": [
                {"id": "StoreId", "name": "StoreId", "data_type": "int64", "calculated": False},
                {"id": "Region", "name": "Region", "data_type": "string", "calculated": False},
                {"id": "SName", "name": "SName", "data_type": "string", "calculated": False},
            ]},
            {"id": "Ext.csv", "name": "Ext", "columns": [
                {"id": "ExtraId", "name": "ExtraId", "data_type": "int64", "calculated": False},
                {"id": "EName", "name": "EName", "data_type": "string", "calculated": False},
            ]},
        ],
        "relations": [
            {"endpoints": [{"table": "Fact.csv", "column": "StoreId"},
                           {"table": "Store.csv", "column": "StoreId"},
                           {"table": "Fact.csv", "column": "Region"},
                           {"table": "Store.csv", "column": "Region"}],
             "cardinality": "many_to_one"},
            {"endpoints": [{"table": "Fact.csv", "column": "ExtraId"},
                           {"table": "Ext.csv", "column": "ExtraId"}],
             "cardinality": "many_to_one"},
        ],
        "warnings": [],
    }


def test_composite_key_join_conjoins_all_pairs():
    # Finding 3: a two-column key must emit BOTH pairs AND'd — not just the first (double count).
    _, model = _run(_composite_inv())
    joins = {t["name"]: t.get("joins", []) for t in model["model_tables"]}
    store = next(j for j in joins["Fact"] if j["with"] == "Store")
    assert store["on"] == ("[Fact::StoreId] = [Store::StoreId] "
                           "AND [Fact::Region] = [Store::Region]")


def test_explicit_cardinality_is_migrated_not_flagged():
    # Contrast to the defaulted case: an explicit cardinality is Migrated, not NEEDS REVIEW.
    mapping, _ = _run(_composite_inv())
    statuses = {r["name"]: r["status"] for r in mapping["relationships"]}
    assert statuses and all(s == "Migrated" for s in statuses.values())


def _idname_inv():
    """Join keys whose column *id* differs from the display *name* (id 'f_ckey' -> 'CustKey').
    The ON clause must reference the name the model column registers under, not the id."""
    return {
        "source": "IdName",
        "tables": [
            {"id": "Fact.csv", "name": "Fact", "columns": [
                {"id": "f_ckey", "name": "CustKey", "data_type": "int64", "calculated": False},
                {"id": "f_gkey", "name": "GeoKey", "data_type": "int64", "calculated": False},
                {"id": "f_amt", "name": "Amount", "data_type": "double", "calculated": False},
            ]},
            {"id": "Cust.csv", "name": "Cust", "columns": [
                {"id": "c_ckey", "name": "CustKey", "data_type": "int64", "calculated": False},
                {"id": "c_nm", "name": "CName", "data_type": "string", "calculated": False},
            ]},
            {"id": "Geo.csv", "name": "Geo", "columns": [
                {"id": "g_gkey", "name": "GeoKey", "data_type": "int64", "calculated": False},
                {"id": "g_nm", "name": "GName", "data_type": "string", "calculated": False},
            ]},
        ],
        "relations": [
            {"endpoints": [{"table": "Fact.csv", "column": "f_ckey"},
                           {"table": "Cust.csv", "column": "c_ckey"}],
             "cardinality": "many_to_one"},
            {"endpoints": [{"table": "Fact.csv", "column": "f_gkey"},
                           {"table": "Geo.csv", "column": "g_gkey"}],
             "cardinality": "many_to_one"},
        ],
        "warnings": [],
    }


def test_join_on_uses_column_name_not_id():
    # Finding 6: endpoints carry the column id; the ON must resolve to the display name so it
    # matches the model column_id ({Table}::{name}) and resolves on import.
    _, model = _run(_idname_inv())
    joins = {t["name"]: t.get("joins", []) for t in model["model_tables"]}
    cust = next(j for j in joins["Fact"] if j["with"] == "Cust")
    assert cust["on"] == "[Fact::CustKey] = [Cust::CustKey]"
    # and the model column registers under the name, matching the ON token
    ids = {c["column_id"] for c in model["columns"]}
    assert "Fact::CustKey" in ids


def test_defaulted_cardinality_flagged_needs_review():
    # Finding 5: the base inventory has no cardinality (UNKNOWN) -> defaulted MANY_TO_ONE,
    # so every relation row must be NEEDS REVIEW with the fan-out caveat (join still emitted).
    _, mapping, model, _ = _build()
    rels = mapping["relationships"]
    assert len(rels) == 2
    for r in rels:
        assert r["status"] == "NEEDS REVIEW"
        assert "defaulted to MANY_TO_ONE" in r["note"]
    # flag, don't downgrade: the joins are still emitted with MANY_TO_ONE
    fact_joins = next(t.get("joins", []) for t in model["model_tables"] if t["name"] == "Fact")
    assert len(fact_joins) == 2
    assert all(j["cardinality"] == "MANY_TO_ONE" for j in fact_joins)


def _dims_inv():
    return {
        "source": "Dims",
        "tables": [{"id": "T.csv", "name": "T", "columns": [
            {"id": "Year", "name": "Year", "data_type": "int64", "calculated": False},
            {"id": "Age", "name": "Age", "data_type": "int64", "calculated": False},
            {"id": "Revenue", "name": "Revenue", "data_type": "double", "calculated": False},
        ]}],
        "relations": [],
        "warnings": [],
    }


def test_year_age_not_plain_sum_measure():
    # Finding 8: Year/Age are numeric but dimensional -> ATTRIBUTE, not a silent SUM measure.
    mapping, model = _run(_dims_inv())
    cols = {c["name"]: c for c in model["columns"]}
    assert cols["Year"]["properties"]["column_type"] == "ATTRIBUTE"
    assert "aggregation" not in cols["Year"]["properties"]
    assert cols["Age"]["properties"]["column_type"] == "ATTRIBUTE"
    assert cols["Revenue"]["properties"]["column_type"] == "MEASURE"
    flagged = {m["name"] for m in mapping["measures"] if m["status"] == "NEEDS REVIEW"}
    assert "Year" not in flagged and "Age" not in flagged
    assert "Revenue" in flagged                            # defaulted measure is flagged


def test_col_role_dimensional_vs_measure_heuristic():
    # Guard the heuristic: dimensional names -> ATTRIBUTE; real metrics stay MEASURE.
    def role(name, dt="int64"):
        return _col_role({"name": name, "data_type": dt})[0]
    for dim in ("Year", "Age", "Quarter", "Order No", "PostalCode", "CustomerId",
                "StatusFlag", "Rank", "Zip"):
        assert role(dim) == "ATTRIBUTE", dim
    for meas in ("Revenue", "Cost", "Quantity", "Amount"):
        assert role(meas, "double") == "MEASURE", meas
    # a non-numeric column is always an attribute regardless of name
    assert role("Notes", "string") == "ATTRIBUTE"
