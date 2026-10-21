"""Tests for the join-graph invariants (I17-I19) and the opt-in JOIN-KEY rule.

The first class pins each rule to a shape the server was shown to accept or reject in
the 2026-10-21 live probe on se-thoughtspot (see ts_cli/tml_join_graph.py's table). A
rule that fires on an accepted shape blocks a valid import, so the accepted shapes are
asserted clean as deliberately as the rejected ones are asserted flagged.
"""
from ts_cli.tml_join_graph import (
    JoinGraph,
    ambiguous_paths,
    directed_cycles,
    lint_required_join_key,
    strongly_connected,
    table_join_index,
)
from ts_cli.tml_lint import lint_tml


def _j(frm_phys, to_node, lcol="K", rcol="K", to_phys=None, name=None, on=True,
       card="MANY_TO_ONE"):
    """A join from a table whose physical name is `frm_phys` to node `to_node`."""
    j = {"name": name or f"{frm_phys}_TO_{to_node}", "with": to_node,
         "type": "INNER", "cardinality": card}
    if on:
        j["on"] = f"[{frm_phys}::{lcol}] = [{to_phys or to_node}::{rcol}]"
    return j


def _t(name, *joins, alias=None):
    t = {"name": name}
    if alias:
        t["alias"] = alias
    if joins:
        t["joins"] = list(joins)
    return t


def _model(*tables):
    return {"model": {"name": "M", "model_tables": list(tables), "columns": []}}


def _ids(findings):
    return [f.split(":", 1)[0] for f in findings]


class TestProbeShapes:
    """One test per probed shape. The comment names the server's response."""

    def test_tree_is_clean(self):  # OK
        assert lint_tml(_model(
            _t("LINES", _j("LINES", "ORDERS"), _j("LINES", "PRODUCT")),
            _t("ORDERS", _j("ORDERS", "EMPLOYEE")),
            _t("PRODUCT", _j("PRODUCT", "SUPPLIER")),
            _t("EMPLOYEE"), _t("SUPPLIER"))) == []

    def test_bidirectional_pair_is_a_cycle(self):  # 13123
        f = lint_tml(_model(
            _t("ORDERS", _j("ORDERS", "EMPLOYEE")),
            _t("EMPLOYEE", _j("EMPLOYEE", "ORDERS"))))
        assert _ids(f) == ["I17"]
        assert "cycle (EMPLOYEE -> ORDERS -> EMPLOYEE)" in f[0]
        assert "13123" in f[0]

    def test_three_cycle(self):  # 13123
        f = lint_tml(_model(
            _t("LINES", _j("LINES", "PRODUCT")),
            _t("PRODUCT", _j("PRODUCT", "SUPPLIER")),
            _t("SUPPLIER", _j("SUPPLIER", "LINES"))))
        assert _ids(f) == ["I17"]
        assert "LINES -> PRODUCT -> SUPPLIER -> LINES" in f[0]

    def test_diamond(self):  # 13124
        f = lint_tml(_model(
            _t("LINES", _j("LINES", "ORDERS"), _j("LINES", "PRODUCT")),
            _t("ORDERS", _j("ORDERS", "SUPPLIER")),
            _t("PRODUCT", _j("PRODUCT", "SUPPLIER")),
            _t("SUPPLIER")))
        assert _ids(f) == ["I17"]
        assert "two join paths reach 'SUPPLIER' from 'LINES'" in f[0]
        assert "LINES -> ORDERS -> SUPPLIER" in f[0]
        assert "LINES -> PRODUCT -> SUPPLIER" in f[0]
        assert "13124" in f[0]

    def test_diamond_fixed_by_alias_is_clean(self):  # OK
        assert lint_tml(_model(
            _t("LINES", _j("LINES", "ORDERS"), _j("LINES", "PRODUCT")),
            _t("ORDERS", _j("ORDERS", "SHIPPER", to_phys="SUPPLIER")),
            _t("PRODUCT", _j("PRODUCT", "SUPPLIER")),
            _t("SUPPLIER"), _t("SUPPLIER", alias="SHIPPER"))) == []

    def test_facts_sharing_dimensions_are_clean(self):  # OK — undirected loop only
        assert lint_tml(_model(
            _t("LINES", _j("LINES", "ORDERS"), _j("LINES", "PRODUCT")),
            _t("INVENTORY", _j("INVENTORY", "PRODUCT"), _j("INVENTORY", "DATE")),
            _t("ORDERS", _j("ORDERS", "DATE")),
            _t("PRODUCT"), _t("DATE"))) == []

    def test_direct_self_join(self):  # 14565
        f = lint_tml(_model(_t("EMPLOYEE", _j("EMPLOYEE", "EMPLOYEE", "REPORTS_TO", "ID"))))
        assert _ids(f) == ["I18"]
        assert "'EMPLOYEE' to itself" in f[0]

    def test_self_join_through_an_alias(self):  # 13125
        f = lint_tml(_model(
            _t("EMPLOYEE", _j("EMPLOYEE", "MANAGER", "REPORTS_TO", "ID", to_phys="EMPLOYEE")),
            _t("EMPLOYEE", alias="MANAGER")))
        assert _ids(f) == ["I18"]

    def test_self_join_between_two_aliases(self):  # 13125
        f = lint_tml(_model(
            _t("ORDERS", _j("ORDERS", "REP", "REP_ID", "ID", to_phys="EMPLOYEE")),
            _t("EMPLOYEE", _j("EMPLOYEE", "REP_MANAGER", "REPORTS_TO", "ID",
                              to_phys="EMPLOYEE"), alias="REP"),
            _t("EMPLOYEE", alias="REP_MANAGER")))
        assert _ids(f) == ["I18"]
        assert "(REP -> REP_MANAGER)" in f[0]

    def test_on_names_a_third_table(self):  # Invalid srcTable or destTable
        f = lint_tml(_model(
            _t("LINES", _j("LINES", "ORDERS", to_phys="PRODUCT"), _j("LINES", "PRODUCT")),
            _t("ORDERS"), _t("PRODUCT")))
        assert _ids(f) == ["I19"]
        assert "names 'PRODUCT'" in f[0] and "neither of its two tables" in f[0]

    def test_on_names_an_alias(self):  # Invalid srcTable or destTable
        f = lint_tml(_model(
            _t("ORDERS", _j("ORDERS", "SHIPPER")),  # on: uses the alias name
            _t("SUPPLIER", alias="SHIPPER")))
        assert _ids(f) == ["I19"]
        assert "names alias 'SHIPPER'" in f[0] and "write 'SUPPLIER'" in f[0]

    def test_on_sides_in_reverse_order_are_clean(self):  # OK
        assert lint_tml(_model(
            _t("LINES", {"name": "L_TO_O", "with": "ORDERS",
                         "on": "[ORDERS::ID] = [LINES::ORDER_ID]"}),
            _t("ORDERS"))) == []


class TestCardinalitySetsDirection:
    """An arrow runs MANY -> ONE. A ONE_TO_MANY join declared under the dimension is
    the same arrow as a MANY_TO_ONE declared under the fact (review probes R4-R12)."""

    def test_one_to_many_legs_under_the_dimension_are_clean(self):  # R4: OK
        assert lint_tml(_model(
            _t("PRODUCT", _j("PRODUCT", "LINES", card="ONE_TO_MANY"),
               _j("PRODUCT", "INVENTORY", card="ONE_TO_MANY")),
            _t("LINES", _j("LINES", "ORDERS")), _t("ORDERS", _j("ORDERS", "DATE")),
            _t("INVENTORY", _j("INVENTORY", "DATE")), _t("DATE"))) == []

    def test_one_flipped_leg_makes_a_diamond(self):  # R4f: 13124
        """Same placement as the accepted shared-dimension Model, one leg 1:M: now
        PRODUCT -> INVENTORY, so LINES reaches DATE by two routes."""
        f = lint_tml(_model(
            _t("LINES", _j("LINES", "ORDERS"), _j("LINES", "PRODUCT")),
            _t("INVENTORY", _j("INVENTORY", "PRODUCT", card="ONE_TO_MANY"),
               _j("INVENTORY", "DATE")),
            _t("ORDERS", _j("ORDERS", "DATE")), _t("PRODUCT"), _t("DATE")))
        assert _ids(f) == ["I17"]
        assert "two join paths reach 'DATE' from 'LINES'" in f[0]

    def test_mirror_pair_is_two_joins_on_one_arrow(self):  # R12: 13124, not a cycle
        f = lint_tml(_model(
            _t("ORDERS", _j("ORDERS", "EMPLOYEE")),
            _t("EMPLOYEE", _j("EMPLOYEE", "ORDERS", card="ONE_TO_MANY"))))
        assert _ids(f) == ["I17"]
        assert "2 joins run from 'ORDERS' to 'EMPLOYEE'" in f[0] and "13124" in f[0]

    def test_both_many_to_one_mirror_is_a_cycle(self):  # P1: 13123
        f = lint_tml(_model(
            _t("ORDERS", _j("ORDERS", "EMPLOYEE")),
            _t("EMPLOYEE", _j("EMPLOYEE", "ORDERS"))))
        assert _ids(f) == ["I17"] and "13123" in f[0]

    def test_one_to_one_follows_placement(self):  # R4h: OK
        assert lint_tml(_model(
            _t("LINES", _j("LINES", "ORDERS"), _j("LINES", "PRODUCT")),
            _t("INVENTORY", _j("INVENTORY", "PRODUCT", card="ONE_TO_ONE"),
               _j("INVENTORY", "DATE")),
            _t("ORDERS", _j("ORDERS", "DATE")), _t("PRODUCT"), _t("DATE"))) == []


class TestEdgeCases:
    def test_deep_diamond_is_reported_once_at_its_split_point(self):
        """X -> A, then A splits and rejoins at D, which continues to E. Only (A, D) is a
        merge point; X -> D and A -> E are consequences, not separate defects."""
        f = lint_tml(_model(
            _t("X", _j("X", "A")),
            _t("A", _j("A", "B"), _j("A", "C")),
            _t("B", _j("B", "D")), _t("C", _j("C", "D")),
            _t("D", _j("D", "E")), _t("E")))
        assert _ids(f) == ["I17"]
        assert "reach 'D' from 'A'" in f[0]

    def test_triangle_shortcut_is_a_second_route(self):
        f = lint_tml(_model(
            _t("A", _j("A", "B"), _j("A", "C")),
            _t("B", _j("B", "C")), _t("C")))
        assert _ids(f) == ["I17"]
        assert "A -> C" in f[0] and "A -> B -> C" in f[0]

    def test_i14_duplicate_pair_is_not_double_reported(self):
        f = lint_tml(_model(
            _t("FACT", _j("FACT", "DATE", "D1", "D", name="J1"),
               _j("FACT", "DATE", "D2", "D", name="J2")),
            _t("DATE")))
        assert _ids(f) == ["I14"]

    def test_cycle_and_diamond_in_one_model_are_both_reported(self):
        f = lint_tml(_model(
            _t("A", _j("A", "B")), _t("B", _j("B", "A")),
            _t("P", _j("P", "Q"), _j("P", "R")),
            _t("Q", _j("Q", "S")), _t("R", _j("R", "S")), _t("S")))
        assert sorted(_ids(f)) == ["I17", "I17"]
        assert any("cycle" in x for x in f) and any("reach 'S'" in x for x in f)

    def test_route_between_two_cycles_still_counts(self):
        """Edges INSIDE a cycle are set aside for path counting; an edge from one
        cycle to another is an ordinary route. Two such routes into S are a diamond
        even though both start in cycles."""
        f = lint_tml(_model(
            _t("A", _j("A", "B"), _j("A", "S")), _t("B", _j("B", "A"), _j("B", "C")),
            _t("C", _j("C", "D"), _j("C", "S")), _t("D", _j("D", "C")),
            _t("S")))
        assert sorted(_ids(f)) == ["I17", "I17", "I17"]
        assert any("reach 'S' from 'cycle(A, B)'" in x
                   and "cycle(A, B) -> cycle(C, D) -> S" in x for x in f)

    def test_a_table_named_like_a_cycle_does_not_collide(self):
        """A real table `A/B` beside a real cycle A <-> B must not merge with it."""
        f = lint_tml(_model(
            _t("A", _j("A", "B")), _t("B", _j("B", "A")),
            _t("A/B", _j("A/B", "S")), _t("S")))
        assert _ids(f) == ["I17"] and "cycle" in f[0]

    def test_non_string_names_do_not_crash(self):
        f = lint_tml(_model(_t(2024, {"name": "j", "with": 123}), _t(123)))
        assert f == []

    def test_escaped_names_in_on_resolve(self):
        """An exported Model writes `[dim_date\\.csv::id]` for a table named
        `dim_date.csv` (seen on 7 of 599 real Models in the review sweep)."""
        assert lint_tml(_model(
            _t("FACT", {"name": "j", "with": "dim_date.csv",
                        "on": "[FACT::DATE_ID] = [dim_date\\.csv::date_id]"}),
            _t("dim_date.csv"))) == []

    def test_on_table_names_are_case_insensitive(self):
        assert lint_tml(_model(
            _t("Orders", {"name": "j", "with": "Customer",
                          "on": "[ORDERS::CUST_ID] = [customer::ID]"}),
            _t("Customer"))) == []

    def test_referencing_join_without_on_is_not_checked_by_i19(self):
        assert lint_tml(_model(
            _t("ORDERS", {"with": "CUSTOMER", "referencing_join": "ORDERS_to_CUSTOMER"}),
            _t("CUSTOMER"))) == []

    def test_unresolvable_with_target_is_left_to_xref(self):
        assert lint_tml(_model(_t("ORDERS", _j("ORDERS", "NOWHERE")))) == []

    def test_long_chain_does_not_hit_the_recursion_limit(self):
        n = 3000
        tables = [_t(f"T{i}", _j(f"T{i}", f"T{i + 1}")) for i in range(n)] + [_t(f"T{n}")]
        tables[-1]["joins"] = [_j(f"T{n}", "T0")]  # close it into one huge cycle
        g = JoinGraph(tables)
        assert [len(c) for c in strongly_connected(g.adjacency())] == [n + 1]
        assert len(directed_cycles(g)) == 1
        assert ambiguous_paths(g) == []


class TestRequiredJoinKey:
    KEY = ["customer_id"]

    def _m(self, *tables):
        return _model(*tables)

    def test_join_equating_the_key_passes(self):
        m = self._m(_t("ORDERS", {"name": "j", "with": "CUSTOMER",
                                  "on": "[ORDERS::CUST] = [CUSTOMER::ID] AND "
                                        "[ORDERS::customer_id] = [CUSTOMER::customer_id]"}),
                    _t("CUSTOMER"))
        assert lint_required_join_key(m, self.KEY) == []

    def test_join_missing_the_key_is_flagged(self):
        m = self._m(_t("ORDERS", _j("ORDERS", "INCIDENT", "INC_ID", "ID")), _t("INCIDENT"))
        f = lint_required_join_key(m, self.KEY)
        assert len(f) == 1 and f[0].startswith("JOIN-KEY:")
        assert "AND [ORDERS::customer_id] = [INCIDENT::customer_id]" in f[0]

    def test_key_must_span_both_tables(self):
        """`[ORDERS::customer_id] = [ORDERS::customer_id]` names the key twice on ONE
        table — it constrains nothing across the join."""
        m = self._m(_t("ORDERS", {"name": "j", "with": "INCIDENT",
                                  "on": "[ORDERS::INC] = [INCIDENT::ID] AND "
                                        "[ORDERS::customer_id] = [ORDERS::customer_id]"}),
                    _t("INCIDENT"))
        assert len(lint_required_join_key(m, self.KEY)) == 1

    def test_reversed_sides_parens_and_case_pass(self):
        m = self._m(_t("ORDERS", {"name": "j", "with": "INCIDENT",
                                  "on": "([INCIDENT::ID] = [ORDERS::INC]) and "
                                        "([incident::CUSTOMER_ID] = [orders::Customer_Id])"}),
                    _t("INCIDENT"))
        assert lint_required_join_key(m, self.KEY) == []

    def test_aliased_target_uses_physical_names_in_the_suggestion(self):
        m = self._m(_t("ORDERS", _j("ORDERS", "BILL_TO", "BILL_ID", "ID", to_phys="ACCOUNT")),
                    _t("ACCOUNT", alias="BILL_TO"))
        f = lint_required_join_key(m, self.KEY)
        assert "[ACCOUNT::customer_id]" in f[0] and "(ORDERS -> BILL_TO)" in f[0]

    def test_exempt_by_physical_or_alias_name(self):
        m = self._m(_t("ORDERS", _j("ORDERS", "CAL", "D", "D", to_phys="CALENDAR")),
                    _t("CALENDAR", alias="CAL"))
        assert lint_required_join_key(m, self.KEY, exempt=["calendar"]) == []
        assert lint_required_join_key(m, self.KEY, exempt=["CAL"]) == []
        assert len(lint_required_join_key(m, self.KEY, exempt=["OTHER"])) == 1

    def test_every_key_is_required(self):
        m = self._m(_t("ORDERS", {"name": "j", "with": "INCIDENT",
                                  "on": "[ORDERS::customer_id] = [INCIDENT::customer_id]"}),
                    _t("INCIDENT"))
        f = lint_required_join_key(m, ["customer_id", "region_id"])
        assert len(f) == 1 and "'region_id'" in f[0]

    def test_referencing_join_resolved_from_the_table_tml(self):
        m = self._m(_t("ORDERS", {"with": "INCIDENT", "referencing_join": "O_TO_I"}),
                    _t("INCIDENT"))
        idx = table_join_index({"ORDERS": {"joins_with": [
            {"name": "O_TO_I", "destination": {"name": "INCIDENT"},
             "on": "[ORDERS::INC] = [INCIDENT::ID]"}]}})
        f = lint_required_join_key(m, self.KEY, table_joins=idx)
        assert len(f) == 1 and "does not equate 'customer_id'" in f[0]

    def test_referencing_join_is_looked_up_on_the_declaring_table_only(self):
        """A referencing join lives in the declaring entry's Table TML; one placed under
        its destination is rejected at import (14504, review probe R14), so a join of
        that name on the OTHER table is not this join."""
        m = self._m(_t("LINES", {"with": "ORDERS", "referencing_join": "O_TO_L"}),
                    _t("ORDERS"))
        idx = table_join_index({"ORDERS": {"joins_with": [
            {"name": "O_TO_L", "destination": {"name": "LINES"},
             "on": "[ORDERS::ID] = [LINES::ORDER_ID] AND "
                   "[ORDERS::customer_id] = [LINES::customer_id]"}]}})
        f = lint_required_join_key(m, self.KEY, table_joins=idx)
        assert len(f) == 1 and "cannot be checked" in f[0]

    def test_key_under_or_does_not_count(self):
        m = self._m(_t("ORDERS", {"name": "j", "with": "CUSTOMER",
                                  "on": "[ORDERS::CUST] = [CUSTOMER::ID] or "
                                        "[ORDERS::customer_id] = [CUSTOMER::customer_id]"}),
                    _t("CUSTOMER"))
        assert len(lint_required_join_key(m, self.KEY)) == 1

    def test_key_inside_an_expression_does_not_count(self):
        m = self._m(_t("ORDERS", {"name": "j", "with": "CUSTOMER",
                                  "on": "[ORDERS::CUST] = [CUSTOMER::ID] and "
                                        "[ORDERS::customer_id] = [CUSTOMER::customer_id] + 1"}),
                    _t("CUSTOMER"))
        assert len(lint_required_join_key(m, self.KEY)) == 1

    def test_separately_parenthesised_conjuncts_count(self):
        m = self._m(_t("ORDERS", {"name": "j", "with": "CUSTOMER",
                                  "on": "([ORDERS::CUST] = [CUSTOMER::ID]) and "
                                        "([ORDERS::customer_id] = [CUSTOMER::customer_id])"}),
                    _t("CUSTOMER"))
        assert lint_required_join_key(m, self.KEY) == []

    def test_a_column_named_like_or_is_not_an_operator(self):
        m = self._m(_t("ORDERS", {"name": "j", "with": "CUSTOMER",
                                  "on": "[ORDERS::or] = [CUSTOMER::not] and "
                                        "[ORDERS::customer_id] = [CUSTOMER::customer_id]"}),
                    _t("CUSTOMER"))
        assert lint_required_join_key(m, self.KEY) == []

    def test_referencing_join_without_its_table_tml_says_so(self):
        m = self._m(_t("ORDERS", {"with": "INCIDENT", "referencing_join": "O_TO_I"}),
                    _t("INCIDENT"))
        f = lint_required_join_key(m, self.KEY)
        assert len(f) == 1 and "cannot be checked" in f[0]

    def test_no_keys_means_no_findings(self):
        m = self._m(_t("ORDERS", _j("ORDERS", "INCIDENT")), _t("INCIDENT"))
        assert lint_required_join_key(m, []) == []

    def test_not_part_of_lint_tml(self):
        """Opt-in: the default lint never applies it."""
        m = self._m(_t("ORDERS", _j("ORDERS", "INCIDENT", "INC", "ID")), _t("INCIDENT"))
        assert lint_tml(m) == []


class TestLintCommand:
    """`ts tml lint` wiring: I17-I19 always run; JOIN-KEY only when asked for."""

    @staticmethod
    def _run(tmp_path, *args):
        import json as _json
        from typer.testing import CliRunner
        from ts_cli.cli import app
        res = CliRunner().invoke(app, ["tml", "lint", "--dir", str(tmp_path), *args])
        out = _json.loads(res.stdout) if res.stdout.strip().startswith("{") else None
        findings = [f for r in (out or {}).get("results", []) for f in r["findings"]]
        return res, findings

    @staticmethod
    def _write(tmp_path, model, *tables):
        import yaml as _yaml
        (tmp_path / "m.model.tml").write_text(_yaml.safe_dump(model))
        for t in tables:
            (tmp_path / f"{t['name']}.table.tml").write_text(_yaml.safe_dump({"table": t}))

    def test_diamond_fails_the_lint(self, tmp_path):
        self._write(tmp_path, _model(
            _t("LINES", _j("LINES", "ORDERS"), _j("LINES", "PRODUCT")),
            _t("ORDERS", _j("ORDERS", "SUPPLIER")),
            _t("PRODUCT", _j("PRODUCT", "SUPPLIER")), _t("SUPPLIER")))
        res, findings = self._run(tmp_path)
        assert res.exit_code == 1
        assert [f[:4] for f in findings] == ["I17:"]

    def test_join_key_is_opt_in(self, tmp_path):
        self._write(tmp_path, _model(_t("ORDERS", _j("ORDERS", "INCIDENT", "INC", "ID")),
                                     _t("INCIDENT")))
        res, findings = self._run(tmp_path)
        assert res.exit_code == 0 and findings == []
        res, findings = self._run(tmp_path, "--require-join-key", "customer_id")
        assert res.exit_code == 1 and findings[0].startswith("JOIN-KEY:")
        res, findings = self._run(tmp_path, "--require-join-key", "customer_id",
                                  "--exempt", "INCIDENT")
        assert res.exit_code == 0 and findings == []

    def test_join_key_reads_a_referencing_join_from_the_batch(self, tmp_path):
        self._write(
            tmp_path,
            _model(_t("ORDERS", {"with": "INCIDENT", "referencing_join": "O_TO_I"}),
                   _t("INCIDENT")),
            {"name": "ORDERS", "columns": [], "joins_with": [{
                "name": "O_TO_I", "destination": {"name": "INCIDENT"},
                "on": "[ORDERS::INC] = [INCIDENT::ID] AND "
                      "[ORDERS::customer_id] = [INCIDENT::customer_id]"}]})
        res, findings = self._run(tmp_path, "--require-join-key", "customer_id")
        assert not [f for f in findings if f.startswith("JOIN-KEY:")]

    def test_exempt_without_a_key_is_a_usage_error(self, tmp_path):
        self._write(tmp_path, _model(_t("ORDERS")))
        res, _ = self._run(tmp_path, "--exempt", "X")
        assert res.exit_code == 2
