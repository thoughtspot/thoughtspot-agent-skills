"""The combined Model + RLS join graph (`rls_join_cycles`, `rls_edges`).

Every table here is synthetic. The shape is the one a support case root-caused: a
Model joins `bridge -> users`, and the RLS rule on `users` walks back out to `bridge`
through a table-level join, so query generation sees `bridge` with two roots.
"""
from __future__ import annotations

from ts_cli.tml_rls_graph import RlsEdge, rls_edges, rls_join_cycles


def mt(name, *joins, alias=None):
    entry = {"name": name, "joins": list(joins)}
    if alias:
        entry["alias"] = alias
    return entry


def join(with_, name=None, cardinality="MANY_TO_ONE"):
    return {"with": with_, "name": name or f"to_{with_}", "cardinality": cardinality,
            "on": "[a::k] = [b::k]", "type": "LEFT_OUTER"}


def rls_table(secured, joins, paths, exprs):
    """A Table body with `rls_rules`. `joins`: (name, source, destination);
    `paths`: (id, table, [[join names per segment], ...] or None)."""
    return {
        "name": secured,
        "joins_with": [{"name": n, "destination": {"name": d}} for n, _s, d in joins],
        "rls_rules": {
            "tables": [{"name": secured}],
            "joins": [{"name": n, "source": s, "destination": d, "type": "INNER"}
                      for n, s, d in joins],
            "table_paths": [
                {"id": pid, "table": tbl, "column": ["c"],
                 **({"join_path": [{"join": seg} for seg in segs]} if segs else {})}
                for pid, tbl, segs in paths
            ],
            "rules": [{"name": f"r{i}", "expr": e} for i, e in enumerate(exprs)],
        },
    }


CASE_MODEL = [
    mt("fact", join("users", "fact_users"), join("bridge", "fact_bridge")),
    mt("bridge", join("users", "bridge_users")),
    mt("users"),
]


def case_users(source="users", destination="bridge"):
    return rls_table(
        "users", [("users_to_bridge", source, destination)],
        [("bridge_1", "bridge", [["users_to_bridge"]]), ("users_1", "users", None)],
        ["[users_1::c] in ts_var(a) and [bridge_1::c] in ts_var(b)"])


def test_case_shape_is_a_cycle():
    found = rls_join_cycles(CASE_MODEL, {"users": case_users()})
    assert len(found) == 1
    assert found[0]["cycle"] == ["users", "bridge", "users"]
    assert found[0]["rls_edge"] == RlsEdge("users", "bridge", "users", "users_to_bridge")
    assert found[0]["model_joins"] == ["bridge_users"]


def test_workaround_is_silent():
    model = [mt("fact", join("users_plain"), join("bridge")),
             mt("bridge", join("users_plain")), mt("users_plain")]
    assert rls_join_cycles(model, {"users": case_users()}) == []


def test_same_direction_rls_is_silent():
    model = [mt("users", join("orgs")), mt("orgs")]
    orgs = rls_table("users", [("u_to_o", "users", "orgs")],
                     [("orgs_1", "orgs", [["u_to_o"]])], ["[orgs_1::c] = 1"])
    assert rls_join_cycles(model, {"users": orgs}) == []


def test_unused_join_and_unreferenced_path_are_silent():
    unused = rls_table("users", [("users_to_bridge", "users", "bridge")],
                       [("users_1", "users", None)], ["[users_1::c] = 1"])
    assert rls_join_cycles(CASE_MODEL, {"users": unused}) == []
    unreferenced = rls_table("users", [("users_to_bridge", "users", "bridge")],
                             [("bridge_1", "bridge", [["users_to_bridge"]]),
                              ("users_1", "users", None)], ["[users_1::c] = 1"])
    assert rls_join_cycles(CASE_MODEL, {"users": unreferenced}) == []


def test_opposite_cardinality_pair_is_a_two_node_cycle():
    model = [mt("a", join("b", "a_b")), mt("b")]
    b = rls_table("b", [("b_to_a", "b", "a")], [("a_1", "a", [["b_to_a"]])],
                  ["[a_1::c] = 1"])
    found = rls_join_cycles(model, {"b": b})
    assert [f["cycle"] for f in found] == [["b", "a", "b"]]


def test_labels_reversed_still_fires():
    found = rls_join_cycles(CASE_MODEL, {"users": case_users("bridge", "users")})
    assert [f["cycle"] for f in found] == [["users", "bridge", "users"]]


def test_star_diamond_is_silent():
    model = [mt("fact", join("users"), join("orgs")), mt("users"), mt("orgs")]
    users = rls_table("users", [("u_to_o", "users", "orgs")],
                      [("orgs_1", "orgs", [["u_to_o"]])], ["[orgs_1::c] = 1"])
    assert rls_join_cycles(model, {"users": users}) == []


def test_aliased_role_playing_is_silent():
    model = [
        mt("fact", join("users_buyer"), join("users_seller")),
        mt("users", join("orgs_buyer"), alias="users_buyer"),
        mt("users", join("orgs_seller"), alias="users_seller"),
        mt("orgs", alias="orgs_buyer"), mt("orgs", alias="orgs_seller"),
    ]
    users = rls_table("users", [("u_to_o", "users", "orgs")],
                      [("orgs_1", "orgs", [["u_to_o"]])], ["[orgs_1::c] = 1"])
    assert rls_join_cycles(model, {"users": users}) == []


def test_aliased_case_shape_fires():
    model = [mt("fact", join("users_a"), join("bridge")),
             mt("bridge", join("users_a", "bridge_users")), mt("users", alias="users_a")]
    found = rls_join_cycles(model, {"users": case_users()})
    assert [f["cycle"] for f in found] == [["users_a", "bridge", "users_a"]]


def test_malformed_path_is_skipped():
    bad = rls_table("users", [("x", "orgs", "bridge")],
                    [("bridge_1", "bridge", [["x"]])], ["[bridge_1::c] = 1"])
    assert rls_join_cycles(CASE_MODEL, {"users": bad}) == []
    edges, notes = rls_edges(CASE_MODEL, {"users": bad})
    assert edges == [] and len(notes) == 1 and "bridge_1" in notes[0]


def test_single_table_rls_adds_nothing():
    single = {"name": "users", "rls_rules": {
        "tables": [{"name": "users"}],
        "table_paths": [{"id": "users_1", "table": "users", "column": ["c"]}],
        "rules": [{"name": "r", "expr": "[users_1::c] = 1"}]}}
    assert rls_edges(CASE_MODEL, {"users": single}) == ([], [])


def test_unknown_join_name_skips_path():
    unknown = rls_table("users", [], [("bridge_1", "bridge", [["nope"]])],
                        ["[bridge_1::c] = 1"])
    edges, notes = rls_edges(CASE_MODEL, {"users": unknown})
    assert edges == [] and len(notes) == 1 and "nope" in notes[0]


def test_table_name_match_is_case_insensitive():
    found = rls_join_cycles(CASE_MODEL, {"USERS": case_users()})
    assert len(found) == 1


def test_two_rls_edges_in_one_cycle_are_reported_in_stable_order():
    model = [mt("a", join("b", "a_b")), mt("c", join("d", "c_d")), mt("b"), mt("d")]
    b = rls_table("b", [("b_to_c", "b", "c")], [("c_1", "c", [["b_to_c"]])],
                  ["[c_1::c] = 1"])
    d = rls_table("d", [("d_to_a", "d", "a")], [("a_1", "a", [["d_to_a"]])],
                  ["[a_1::c] = 1"])
    found = rls_join_cycles(model, {"d": d, "b": b})
    assert [(f["rls_edge"].table, f["rls_edge"].join) for f in found] == [
        ("b", "b_to_c"), ("d", "d_to_a")]
    assert found == rls_join_cycles(model, {"b": b, "d": d})
