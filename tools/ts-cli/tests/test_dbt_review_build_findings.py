"""PR #506 review findings against ts-convert-to-dbt's Case A generator
(`ts dbt-export build`) and its schema.yml return leg — each a place where a
table, a column, a property or a file location was lost or misdirected without
a word.

One class per finding; every test here fails against the pre-fix code.
"""
from __future__ import annotations

import re

import pytest
import yaml

from ts_cli.commands.dbt_export import _handle_schema_yml_rls
from ts_cli.dbt.model_from_schema_yml import extract_table_rls_from_schema_yml
from ts_cli.dbt.tags import _build_column_meta, tml_properties_from_ts_meta
from ts_cli.dbt_build_export import build_dbt_export, build_model_tml_from_schema_yml


def _tt(name, cols, db_table=None):
    return {"table": {
        "name": name, "db": "DB", "schema": "S", "db_table": db_table or name,
        "columns": [{"name": c, "db_column_name": c,
                     "db_column_properties": {"data_type": "VARCHAR"}} for c in cols]}}


def _export(model, tables, **kw):
    return build_dbt_export(model_tml={"model": model}, table_tmls=tables,
                            project_name="p", source_name="src", **kw)


def _refs(files):
    """Every dbt model name any generated file `ref()`s."""
    out = set()
    for content in files.values():
        out.update(re.findall(r"ref\('([^']+)'\)", content))
    return out


def _sql_models(files):
    return {p.rsplit("/", 1)[1][:-4] for p in files if p.endswith(".sql")}


def _schema_models(files):
    return yaml.safe_load(files["models/schema.yml"])["models"]


# ---------------------------------------------------------------------------
# 1. --rls-out path traversal via a model alias
# ---------------------------------------------------------------------------

class TestRlsOutRefusesPathEscape:
    _RULES = [{"name": "r", "expr": "x = 1"}]

    def test_alias_with_dot_dot_is_refused_and_nothing_written(self, tmp_path):
        out = tmp_path / "a" / "b"
        with pytest.raises(SystemExit, match=r"\.\./\.\./escaped"):
            _handle_schema_yml_rls({"../../escaped": self._RULES}, str(out))
        assert not list(tmp_path.rglob("*_rls_rules.json"))

    def test_alias_from_schema_yml_is_refused(self, tmp_path):
        schema = (
            "models:\n  - name: m\n    config:\n      alias: ../../escaped\n"
            "      meta:\n        ts_rls_rules:\n          - name: r\n            expr: x = 1\n")
        with pytest.raises(SystemExit):
            _handle_schema_yml_rls(extract_table_rls_from_schema_yml(schema),
                                   str(tmp_path / "a" / "b"))
        assert not list(tmp_path.rglob("*_rls_rules.json"))

    @pytest.mark.parametrize("name", ["sub/dir", "/abs/path", "..", "a\\b"])
    def test_any_path_separator_is_refused(self, tmp_path, name):
        with pytest.raises(SystemExit):
            _handle_schema_yml_rls({name: self._RULES}, str(tmp_path / "out"))
        assert not list(tmp_path.rglob("*_rls_rules.json"))

    def test_a_bad_name_writes_none_of_the_good_ones(self, tmp_path):
        out = tmp_path / "out"
        with pytest.raises(SystemExit):
            _handle_schema_yml_rls({"GOOD": self._RULES, "../BAD": self._RULES}, str(out))
        assert not list(tmp_path.rglob("*_rls_rules.json"))

    def test_plain_name_still_written_and_escape_still_refused(self, tmp_path):
        out = tmp_path / "out"
        _handle_schema_yml_rls({"ORDERS": self._RULES}, str(out))
        assert (out / "ORDERS_rls_rules.json").is_file()
        with pytest.raises(SystemExit):
            _handle_schema_yml_rls({"../ORDERS": self._RULES}, str(out))
        assert not (tmp_path / "ORDERS_rls_rules.json").exists()


# ---------------------------------------------------------------------------
# 2. A Table used ONLY through role-play aliases
# ---------------------------------------------------------------------------

class TestRolePlayOnlyTableGetsItsStagingModel:
    def _model(self):
        return {
            "name": "M",
            "model_tables": [
                {"name": "ORDERS", "joins": [
                    {"with": "SHIP_ACCOUNT", "on": "[ORDERS::SHIP_ID] = [SHIP_ACCOUNT::ID]",
                     "type": "INNER", "cardinality": "MANY_TO_ONE"},
                    {"with": "BILL_ACCOUNT", "on": "[ORDERS::BILL_ID] = [BILL_ACCOUNT::ID]",
                     "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
                {"name": "ACCOUNT", "alias": "SHIP_ACCOUNT"},
                {"name": "ACCOUNT", "alias": "BILL_ACCOUNT"}],
            "columns": [
                {"name": "Ship Name", "column_id": "SHIP_ACCOUNT::NAME"},
                {"name": "Bill Name", "column_id": "BILL_ACCOUNT::NAME"},
                {"name": "Order Id", "column_id": "ORDERS::ID"}]}

    def _tables(self):
        return {"ORDERS": _tt("ORDERS", ["ID", "SHIP_ID", "BILL_ID"]),
                "ACCOUNT": _tt("ACCOUNT", ["ID", "NAME"])}

    def test_base_staging_model_is_written(self):
        files, info = _export(self._model(), self._tables())
        assert files["models/staging/stg_account.sql"] == (
            "select * from {{ source('src', 'ACCOUNT') }}\n")
        assert files["models/marts/dim_ship_account.sql"] == (
            "select * from {{ ref('stg_account') }}\n")
        assert "stg_account" in info["model_names"]
        # ...and selects from a source that sources.yml actually declares
        sources = yaml.safe_load(files["models/staging/sources.yml"])["sources"]
        assert {"name": "ACCOUNT"} in sources[0]["tables"]

    def test_every_ref_has_a_model_file(self):
        files, _ = _export(self._model(), self._tables())
        assert _refs(files) <= _sql_models(files)

    def test_adopted_base_name_is_what_the_aliases_ref(self):
        files, info = _export(self._model(), self._tables(),
                              model_name_overrides={"ACCOUNT": "accounts"})
        assert files["models/marts/dim_bill_account.sql"] == (
            "select * from {{ ref('accounts') }}\n")
        assert "accounts" in info["model_names"]


# ---------------------------------------------------------------------------
# 3. Two Tables that snake-case to one dbt model name
# ---------------------------------------------------------------------------

class TestModelNameCollisions:
    def _model(self):
        return {
            "name": "M",
            "model_tables": [
                {"name": "ORDERS", "joins": [
                    {"name": "to_sales", "with": "Sales Data",
                     "on": "[ORDERS::SD_ID] = [Sales Data::ID]",
                     "type": "INNER", "cardinality": "MANY_TO_ONE"},
                    {"name": "to_sales_2", "with": "SALES_DATA",
                     "on": "[ORDERS::K1] = [SALES_DATA::K1] and [ORDERS::K2] = [SALES_DATA::K2]",
                     "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
                {"name": "Sales Data"},
                {"name": "SALES_DATA"},
                {"name": "SALES_DATA", "alias": "SD_ALIAS"}],
            "columns": [
                {"name": "A", "column_id": "Sales Data::A"},
                {"name": "B", "column_id": "SALES_DATA::B"},
                {"name": "Order Id", "column_id": "ORDERS::SD_ID"}]}

    def _tables(self):
        return {"ORDERS": _tt("ORDERS", ["SD_ID", "K1", "K2"]),
                "Sales Data": _tt("Sales Data", ["ID", "A"]),
                "SALES_DATA": _tt("SALES_DATA", ["K1", "K2", "B"])}

    def test_both_tables_keep_their_own_sql_file(self):
        files, info = _export(self._model(), self._tables())
        assert files["models/staging/stg_sales_data.sql"] == (
            "select * from {{ source('src', 'Sales Data') }}\n")
        assert files["models/staging/stg_sales_data_2.sql"] == (
            "select * from {{ source('src', 'SALES_DATA') }}\n")
        assert {"stg_sales_data", "stg_sales_data_2"} <= set(info["model_names"])

    def test_schema_yml_names_are_unique_and_aliased_to_their_own_table(self):
        files, _ = _export(self._model(), self._tables())
        models = _schema_models(files)
        names = [m["name"] for m in models]
        assert len(names) == len(set(names))
        by_name = {m["name"]: m for m in models}
        assert by_name["stg_sales_data"]["config"]["alias"] == "Sales Data"
        assert by_name["stg_sales_data_2"]["config"]["alias"] == "SALES_DATA"
        assert [c["name"] for c in by_name["stg_sales_data_2"]["columns"]] == ["B"]

    def test_relationship_constraint_and_passthrough_use_the_disambiguated_name(self):
        files, _ = _export(self._model(), self._tables())
        orders = next(m for m in _schema_models(files) if m["name"] == "stg_orders")
        sd_id = next(c for c in orders["columns"] if c["name"] == "SD_ID")
        assert sd_id["data_tests"][0]["relationships"]["arguments"]["to"] == (
            "ref('stg_sales_data')")
        assert orders["constraints"][0]["to"] == "ref('stg_sales_data_2')"
        assert files["models/marts/dim_sd_alias.sql"] == (
            "select * from {{ ref('stg_sales_data_2') }}\n")
        assert _refs(files) <= _sql_models(files)

    def test_rename_is_reported(self):
        _, info = _export(self._model(), self._tables())
        assert info["renamed_models"] == [
            {"table": "SALES_DATA", "model": "stg_sales_data_2", "wanted": "stg_sales_data"}]

    def test_generated_name_yields_to_an_adopted_one(self):
        files, info = _export(self._model(), self._tables(),
                              model_name_overrides={"SALES_DATA": "stg_sales_data"})
        assert files["models/staging/stg_sales_data.sql"] == (
            "select * from {{ source('src', 'SALES_DATA') }}\n")
        assert files["models/staging/stg_sales_data_2.sql"] == (
            "select * from {{ source('src', 'Sales Data') }}\n")
        assert info["renamed_models"][0]["table"] == "Sales Data"

    def test_two_tables_adopting_one_model_are_refused(self):
        with pytest.raises(SystemExit, match="collision"):
            _export(self._model(), self._tables(),
                    model_name_overrides={"SALES_DATA": "sales", "Sales Data": "sales"})


# ---------------------------------------------------------------------------
# 4. Two Model columns on one physical column
# ---------------------------------------------------------------------------

class TestTwoModelColumnsOnOneDbColumn:
    def _export(self):
        model = {"name": "M", "model_tables": [{"name": "T"}], "columns": [
            {"name": "Amount", "column_id": "T::AMT",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                            "synonyms": ["rev"]}},
            {"name": "Avg Amount", "column_id": "T::AMT",
             "properties": {"column_type": "MEASURE", "aggregation": "AVERAGE"}}]}
        return _export(model, {"T": _tt("T", ["AMT"])})

    def test_first_column_meta_is_kept_unblended(self):
        files, _ = self._export()
        cols = _schema_models(files)[0]["columns"]
        assert cols == [{"name": "AMT", "config": {"meta": {
            "ts_column_type": "measure", "ts_aggregation": "sum",
            "ts_synonym": "rev", "ts_display_name": "Amount"}}}]

    def test_later_column_is_reported(self):
        _, info = self._export()
        dup = [u for u in info["unmapped_properties"]
               if u["property"] == "duplicate_db_column"]
        assert len(dup) == 1
        assert dup[0]["column"] == "Avg Amount"
        assert dup[0]["value"] == "AMT"
        assert "'Amount'" in dup[0]["reason"] and "ts_formula" in dup[0]["reason"]

    def test_counts_describe_what_was_written(self):
        _, info = self._export()
        assert info["metrics"] == 1


# ---------------------------------------------------------------------------
# 5. Model-level description / parameters / filters
# ---------------------------------------------------------------------------

class TestModelLevelPropertiesReported:
    def _export(self, **extra):
        model = {"name": "M", "model_tables": [{"name": "T"}],
                 "columns": [{"name": "Amount", "column_id": "T::AMT"}], **extra}
        return _export(model, {"T": _tt("T", ["AMT"])})

    def test_each_present_property_is_reported(self):
        _, info = self._export(
            description="MODEL DESC",
            parameters=[{"name": "P", "data_type": "INT64", "default_value": "1"}],
            filters=[{"column": ["Amount"], "oper": "in", "values": ["1"]},
                     {"column": ["Amount"], "oper": "in", "values": ["2"]}])
        by_prop = {u["property"]: u for u in info["unmapped_properties"]}
        assert by_prop["model.description"]["value"] == "MODEL DESC"
        assert by_prop["model.parameters"]["value"] == 1
        assert by_prop["model.filters"]["value"] == 2
        assert all(by_prop[p]["column"] is None for p in by_prop)
        assert all("dbt" in by_prop[p]["reason"] for p in by_prop)
        # and an absent property reports nothing
        _, bare = self._export()
        assert not [u for u in bare["unmapped_properties"]
                    if u["property"].startswith("model.")]

    def test_long_description_is_shortened(self):
        _, info = self._export(description="x" * 500)
        value = info["unmapped_properties"][0]["value"]
        assert len(value) <= 80 and value.endswith("...")


# ---------------------------------------------------------------------------
# 6. A synonym that contains a comma
# ---------------------------------------------------------------------------

class TestSynonymWithComma:
    def _entry(self, synonyms):
        return {"kind": "dimension", "display_name": "City", "synonyms": synonyms}

    def test_written_as_a_list_and_read_back_whole(self):
        meta = _build_column_meta(self._entry(["Washington, D.C.", "Town"]), [])
        assert meta["ts_synonym"] == ["Washington, D.C.", "Town"]
        props = tml_properties_from_ts_meta(meta)
        assert props["synonyms"] == ["Washington, D.C.", "Town"]
        # The common case keeps the documented comma-string shape.
        meta = _build_column_meta(self._entry(["Town", "Municipality"]), [])
        assert meta["ts_synonym"] == "Town, Municipality"
        assert tml_properties_from_ts_meta(meta)["synonyms"] == ["Town", "Municipality"]

    def test_round_trip_through_schema_yml(self):
        model = {"name": "M", "model_tables": [{"name": "T"}], "columns": [
            {"name": "City", "column_id": "T::CITY",
             "properties": {"column_type": "ATTRIBUTE",
                            "synonyms": ["Washington, D.C.", "Town"]}}]}
        files, _ = _export(model, {"T": _tt("T", ["CITY"])})
        tml = build_model_tml_from_schema_yml(files["models/schema.yml"], "M")
        col = next(c for c in tml["model"]["columns"] if c["name"] in ("CITY", "City"))
        assert col["properties"]["synonyms"] == ["Washington, D.C.", "Town"]


class TestBuildCommandLabelsModelLevelEntries:
    """`ts dbt-export build` printed a column-less entry as `join '<value>'`,
    which reads wrong for a Model-level property."""

    def test_model_level_entry_is_labelled_the_model(self):
        from ts_cli.commands.dbt_export import _unmapped_label
        assert _unmapped_label({"column": None, "property": "model.filters",
                                "value": 2}) == "the Model"
        assert _unmapped_label({"column": None, "property": "join_type",
                                "value": "x"}) == "join 'x'"
        assert _unmapped_label({"column": "Amt", "property": "index_type"}) == "'Amt'"
