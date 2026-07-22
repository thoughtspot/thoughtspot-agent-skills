"""Unit tests for ts_cli.qlik.build_model — Table + Model TML + mapping.json.

Pure-function tests over small in-memory IR objects (no live connection).
Asserts the critical TML invariants and the flag-don't-downgrade behaviour.
"""
import yaml

from ts_cli.qlik import build_model
from ts_cli.qlik.ir import Column, MasterMeasure, QlikApp, Table, Variable


def make_app(*, tables=None, measures=None, variables=None, name="MyApp") -> QlikApp:
    return QlikApp(
        app_name=name,
        tables=tables or [],
        measures=measures or [],
        variables=variables or [],
    )


def build(app, **kw):
    defaults = dict(connection_name="Snowflake_Sales", db="DB", schema="SCH")
    defaults.update(kw)
    return build_model.build_model_artifacts(app, **defaults)


# ---------------------------------------------------------------------------
# Table TML invariants
# ---------------------------------------------------------------------------

class TestTableTmlInvariants:
    def _one_table_app(self):
        return make_app(tables=[Table(name="Sales", columns=[
            Column(name="Region"), Column(name="Amount", data_type="number"),
        ])])

    def test_db_column_name_present_on_every_column(self):
        res = build(self._one_table_app())
        doc = res["tables"]["table.Sales.tml"]
        for col in doc["table"]["columns"]:
            assert "db_column_name" in col
            assert col["db_column_name"] == col["name"]

    def test_connection_uses_name_not_fqn(self):
        res = build(self._one_table_app())
        conn = res["tables"]["table.Sales.tml"]["table"]["connection"]
        assert conn == {"name": "Snowflake_Sales"}
        assert "fqn" not in conn

    def test_table_db_schema_db_table(self):
        res = build(self._one_table_app(), db="SALES_DB", schema="PUBLIC")
        t = res["tables"]["table.Sales.tml"]["table"]
        assert t["db"] == "SALES_DB"
        assert t["schema"] == "PUBLIC"
        assert t["db_table"] == "Sales"

    def test_type_overrides_applied(self):
        res = build(self._one_table_app(),
                    type_overrides={"Sales": {"Amount": "INT64", "Region": "VARCHAR"}})
        cols = {c["name"]: c["db_column_properties"]["data_type"]
                for c in res["tables"]["table.Sales.tml"]["table"]["columns"]}
        assert cols["Amount"] == "INT64"
        assert cols["Region"] == "VARCHAR"

    def test_columns_are_attributes(self):
        res = build(self._one_table_app())
        for col in res["tables"]["table.Sales.tml"]["table"]["columns"]:
            assert col["properties"]["column_type"] == "ATTRIBUTE"


# ---------------------------------------------------------------------------
# Model TML: formula_id linkage + aggregation placement
# ---------------------------------------------------------------------------

class TestModelFormulaLinkage:
    def _app(self):
        return make_app(
            tables=[Table(name="Sales", columns=[Column(name="Amount")])],
            measures=[MasterMeasure(id="m1", label="Total Sales", expression="Sum(Amount)")],
        )

    def test_formula_id_matches_column_formula_id(self):
        res = build(self._app())
        model = res["model"]["tml"]["model"]
        formula_ids = {f["id"] for f in model["formulas"]}
        col_formula_ids = {c["formula_id"] for c in model["columns"] if "formula_id" in c}
        assert formula_ids == col_formula_ids
        assert "formula_Total Sales" in formula_ids

    def test_formula_entry_has_no_aggregation(self):
        """aggregation: belongs in columns[] only, never in formulas[]."""
        res = build(self._app())
        for f in res["model"]["tml"]["model"]["formulas"]:
            assert "aggregation" not in f

    def test_measure_column_has_aggregation(self):
        res = build(self._app())
        measure_cols = [c for c in res["model"]["tml"]["model"]["columns"]
                        if "formula_id" in c]
        assert all(c["properties"]["aggregation"] == "SUM" for c in measure_cols)

    def test_physical_column_has_column_id(self):
        res = build(self._app())
        phys = [c for c in res["model"]["tml"]["model"]["columns"] if "column_id" in c]
        assert any(c["column_id"] == "Sales::Amount" for c in phys)

    def test_model_tables_carry_table_fqn(self):
        res = build(self._app())
        tbl = res["model"]["tml"]["model"]["tables"][0]
        assert tbl["fqn"] == "[Snowflake_Sales].[Sales]"

    def test_model_serializes_to_valid_yaml(self):
        from ts_cli.tml_common import dump_tml_yaml
        res = build(self._app())
        reparsed = yaml.safe_load(dump_tml_yaml(res["model"]["tml"]))
        assert "model" in reparsed


# ---------------------------------------------------------------------------
# Flag, don't downgrade
# ---------------------------------------------------------------------------

class TestFlagDontDowngrade:
    def test_untranslatable_set_analysis_flagged_needs_review(self):
        app = make_app(
            tables=[Table(name="T", columns=[Column(name="X")])],
            measures=[MasterMeasure(id="m", label="Sel Sales",
                                    expression="Sum({$<Region=>} Sales)")],
        )
        res = build(app)
        m = next(e for e in res["mapping"]["measures"] if e["name"] == "Sel Sales")
        assert m["status"] == "NEEDS REVIEW"
        assert m["reason"]
        # Original Qlik expression retained; ts_expr is a TODO marker, NOT a
        # plausible-but-wrong substitute.
        assert m["qlik_expr"] == "Sum({$<Region=>} Sales)"
        assert "TODO review" in m["ts_expr"]

    def test_translatable_measure_status_ok(self):
        app = make_app(
            tables=[Table(name="T", columns=[Column(name="Sales")])],
            measures=[MasterMeasure(id="m", label="Total", expression="Sum(Sales)")],
        )
        res = build(app)
        m = res["mapping"]["measures"][0]
        assert m["status"] == "OK"
        assert m["ts_expr"] == "sum(Sales)"

    def test_variables_flagged_needs_review(self):
        app = make_app(
            tables=[Table(name="T", columns=[Column(name="X")])],
            variables=[Variable(name="vYear", definition="2024")],
        )
        res = build(app)
        assert len(res["mapping"]["variables"]) == 1
        assert res["mapping"]["variables"][0]["status"] == "NEEDS REVIEW"
        assert res["counts"]["variables_needs_review"] == 1


# ---------------------------------------------------------------------------
# Name collisions
# ---------------------------------------------------------------------------

class TestNameCollisions:
    def test_duplicate_column_names_across_tables_renamed(self):
        app = make_app(tables=[
            Table(name="Sales", columns=[Column(name="StoreID"), Column(name="Amt")]),
            Table(name="Stores", columns=[Column(name="StoreID"), Column(name="Region")]),
        ])
        res = build(app)
        names = [c["name"] for c in res["model"]["tml"]["model"]["columns"]]
        assert len(names) == len(set(names)), "model column display names must be unique"
        assert res["mapping"]["columns_renamed"], "a rename should have been recorded"

    def test_measure_wins_over_same_named_column(self):
        app = make_app(
            tables=[Table(name="T", columns=[Column(name="Revenue")])],
            measures=[MasterMeasure(id="m", label="Revenue", expression="Sum(Revenue)")],
        )
        res = build(app)
        cols = res["model"]["tml"]["model"]["columns"]
        revenue_entries = [c for c in cols if c["name"] == "Revenue"]
        assert len(revenue_entries) == 1
        assert "formula_id" in revenue_entries[0]  # the measure, not the physical column


# ---------------------------------------------------------------------------
# Empty / degraded input
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_no_tables_warns_but_does_not_crash(self):
        app = make_app(tables=[])
        res = build(app)
        assert res["tables"] == {}
        assert any("No tables" in w for w in res["mapping"]["warnings"])
