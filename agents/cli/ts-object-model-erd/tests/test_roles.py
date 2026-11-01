"""The shared table-role classifier (agents/shared/erd/roles.py; audit v2 roadmap PR 4.1):
a table's role from join direction, refined by the measures it holds."""
from roles import ATTRIBUTE_HEAVY_LABEL, ROLE_LABELS, erd_kind, role_text, table_roles


def _m(tables, joins=(), measures=None, attributes=None, hidden=(), aliases=None):
    """A Model body. `tables`: keys; `joins`: (from, to[, cardinality]) or
    (from, to, None, referencing_join); `measures`/`attributes`: {key: count}."""
    aliases = aliases or {}
    mts = []
    for t in tables:
        mt = {"name": aliases.get(t, t)}
        if t in aliases:
            mt["alias"] = t
        mts.append(mt)
    by_key = {t: mt for t, mt in zip(tables, mts)}
    for j in joins:
        a, b = j[0], j[1]
        entry = {"with": b}
        if len(j) > 2 and j[2]:
            entry["cardinality"] = j[2]
        if len(j) > 3:
            entry["referencing_join"] = j[3]
        by_key[a].setdefault("joins", []).append(entry)
    cols = []
    for t, n in (measures or {}).items():
        for i in range(n):
            props = {"column_type": "MEASURE"}
            if (t, i) in hidden:
                props["is_hidden"] = True
            cols.append({"name": f"{t}_m{i}", "column_id": f"{t}::M{i}", "properties": props})
    for t, n in (attributes or {}).items():
        for i in range(n):
            cols.append({"name": f"{t}_a{i}", "column_id": f"{t}::A{i}",
                         "properties": {"column_type": "ATTRIBUTE"}})
    return {"name": "M", "model_tables": mts, "columns": cols}


def _roles(model, **kw):
    return {k: v["role"] for k, v in table_roles(model, **kw).items()}


def test_root_with_a_measure_is_a_fact_and_one_side_without_is_a_dimension():
    assert _roles(_m(["ORDERS", "CUSTOMER"], [("ORDERS", "CUSTOMER")],
                     measures={"ORDERS": 1})) == {"ORDERS": "fact", "CUSTOMER": "dimension"}


def test_header_detail():
    r = table_roles(_m(["LINES", "HEADER", "CUSTOMER"],
                       [("LINES", "HEADER", "MANY_TO_ONE"), ("HEADER", "CUSTOMER")],
                       measures={"LINES": 3, "HEADER": 1}))
    assert {k: v["role"] for k, v in r.items()} == {
        "LINES": "fact", "HEADER": "dimension_with_measures", "CUSTOMER": "dimension"}
    assert r["CUSTOMER"]["outrigger"] is True
    assert r["HEADER"]["outrigger"] is False
    assert (r["LINES"]["measures"], r["HEADER"]["measures"]) == (3, 1)


def test_root_without_measures_is_factless():
    assert _roles(_m(["BRIDGE", "A", "B"], [("BRIDGE", "A"), ("BRIDGE", "B")])) == {
        "BRIDGE": "factless", "A": "dimension", "B": "dimension"}


def test_single_table_model():
    for n, role in ((2, "fact"), (0, "dimension")):
        r = table_roles(_m(["T"], measures={"T": n}))["T"]
        assert (r["role"], r["unjoined"]) == (role, False)


def test_cardinalities():
    assert _roles(_m(["A", "B"], [("A", "B", "ONE_TO_MANY")], measures={"B": 1})) == {
        "A": "dimension", "B": "fact"}
    for card in ("ONE_TO_ONE", "MANY_TO_MANY"):
        r = table_roles(_m(["A", "B"], [("A", "B", card)], measures={"A": 1}))
        assert (r["A"]["role"], r["B"]["role"]) == ("fact", "dimension")
        assert r["A"]["unjoined"] and r["B"]["unjoined"]
    r = table_roles(_m(["A", "B"], [("A", "ELSEWHERE"), ("A", "B")], measures={"A": 1}))
    assert (r["A"]["role"], r["B"]["role"], r["A"]["unjoined"]) == ("fact", "dimension", False)


def test_join_cardinality_callback_is_used_only_when_the_join_has_none():
    seen = []

    def card(mt, join):
        seen.append(join.get("referencing_join"))
        return "ONE_TO_MANY"
    model = _m(["A", "B", "C"], [("A", "B", None, "j1"), ("A", "C", "MANY_TO_ONE")],
               measures={"B": 1, "A": 1})
    assert _roles(model, join_cardinality=card) == {
        "A": "dimension_with_measures", "B": "fact", "C": "dimension"}
    assert seen == ["j1"]
    # no callback, or the callback finds nothing: the declaring table is the many side
    assert _roles(model)["A"] == "fact"
    assert _roles(model, join_cardinality=lambda mt, j: None)["A"] == "fact"


def test_aliases_are_classified_separately():
    model = _m(["SALES", "SHIP_DATE", "BILL_DATE", "STORE"],
               [("SALES", "SHIP_DATE"), ("SALES", "BILL_DATE"), ("STORE", "BILL_DATE")],
               measures={"SALES": 2}, aliases={"SHIP_DATE": "DATE", "BILL_DATE": "DATE"})
    r = table_roles(model)
    assert set(r) == {"SALES", "SHIP_DATE", "BILL_DATE", "STORE"}
    assert (r["SHIP_DATE"]["role"], r["BILL_DATE"]["role"], r["STORE"]["role"]) == (
        "dimension", "dimension", "factless")


def test_a_directed_cycle_gives_no_fact():
    r = _roles(_m(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")],
                  measures={"A": 2, "B": 0, "C": 1}))
    assert r == {"A": "dimension_with_measures", "B": "dimension",
                 "C": "dimension_with_measures"}


def test_hidden_measures_count_formula_measures_do_not():
    model = _m(["F", "D"], [("F", "D")], measures={"F": 1}, hidden={("F", 0)})
    model["columns"].append({"name": "Ratio", "formula_id": "formula_Ratio",
                             "properties": {"column_type": "MEASURE"}})
    model["formulas"] = [{"id": "formula_Ratio", "name": "Ratio", "expr": "sum ( [D::X] )"}]
    r = table_roles(model)
    assert (r["F"]["role"], r["F"]["measures"]) == ("fact", 1)
    assert (r["D"]["role"], r["D"]["measures"]) == ("dimension", 0)


def test_attribute_heavy():
    r = table_roles(_m(["F", "D"], [("F", "D")], measures={"F": 1}, attributes={"F": 2}))
    assert r["F"]["attribute_heavy"] is True and r["F"]["attributes"] == 2
    r = table_roles(_m(["F", "D"], [("F", "D")], measures={"F": 2}, attributes={"F": 2}))
    assert r["F"]["attribute_heavy"] is False
    assert r["D"]["attribute_heavy"] is False


def test_malformed_entries_are_skipped():
    model = {"model_tables": [None, "x", {"name": ["L"]}, {"name": "A", "joins": [None, {"with": 5}]},
                              {"name": "B"}],
             "columns": [None, {"column_id": 7}, {"column_id": "A::X", "properties": ["MEASURE"]},
                         {"column_id": "A::Y", "properties": {"column_type": "MEASURE"}}]}
    assert _roles(model) == {"A": "fact", "B": "dimension"}
    assert table_roles({}) == {}
    assert table_roles({"model_tables": "nope", "columns": 3}) == {}


def test_erd_kind_and_labels():
    assert [erd_kind(r) for r in ("fact", "factless", "dimension", "dimension_with_measures")] == [
        "fact", "fact", "dim", "dim"]
    assert ROLE_LABELS["dimension_with_measures"] == "Dimension holding measures"
    assert ROLE_LABELS["factless"] == "Factless / bridge"
    assert ATTRIBUTE_HEAVY_LABEL == "Fact with descriptive attributes"


def test_role_text():
    r = table_roles(_m(["LINES", "HEADER", "CUSTOMER", "F2", "D2"],
                       [("LINES", "HEADER"), ("HEADER", "CUSTOMER"), ("F2", "D2")],
                       measures={"LINES": 1, "HEADER": 1, "F2": 1}, attributes={"F2": 3}))
    label, note = role_text(r["HEADER"])
    assert label == "Dimension holding measures" and "repeat" in note
    label, note = role_text(r["CUSTOMER"])
    assert label == "Dimension (outrigger)" and "snowflaked" in note
    assert role_text(r["F2"])[0] == "Fact with descriptive attributes"
    assert role_text(r["LINES"])[0] == "Fact"
