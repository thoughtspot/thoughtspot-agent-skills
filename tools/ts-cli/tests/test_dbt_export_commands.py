"""Command-level tests for `ts dbt-export diff`/`sync` (ts-convert-to-dbt Case B).

`build` (Case A) has no existing CLI-level test file — these fixtures follow
the same shape as test_dbt_build_export.py's pure-function fixtures, driven
through the CLI this time, against a small on-disk existing-project fixture.
"""
from __future__ import annotations

import json

import yaml

from ts_cli.cli import app

from runners import runner  # noqa: E402  (BL-139: one definition, see runners.py)


def _model_tml():
    return {
        "model": {
            "name": "Sales Model",
            "model_tables": [
                {
                    "id": "ORDERS", "name": "ORDERS",
                    "joins": [{
                        "name": "join_1", "with": "CUSTOMERS",
                        "on": "[ORDERS::Customer Id] = [CUSTOMERS::Customer Id]",
                        "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE",
                    }],
                },
                {"id": "CUSTOMERS", "name": "CUSTOMERS"},
            ],
            "columns": [
                {"name": "Customer Id", "column_id": "ORDERS::Customer Id",
                 "properties": {"column_type": "ATTRIBUTE"}},
                {"name": "Customer Name", "column_id": "CUSTOMERS::Customer Name",
                 "properties": {"column_type": "ATTRIBUTE", "synonyms": ["Client"]}},
                {"name": "Total Amount", "column_id": "ORDERS::Total Amount",
                 "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            ],
            "formulas": [],
        }
    }


def _table_tmls():
    return {
        "ORDERS": {"table": {
            "name": "ORDERS", "db": "DB", "schema": "S", "db_table": "ORDERS",
            "columns": [
                {"name": "Customer Id", "db_column_name": "CUSTOMER_ID",
                 "db_column_properties": {"data_type": "INT64"}},
                {"name": "Total Amount", "db_column_name": "AMOUNT",
                 "db_column_properties": {"data_type": "DOUBLE"}},
            ],
        }},
        "CUSTOMERS": {"table": {
            "name": "CUSTOMERS", "db": "DB", "schema": "S", "db_table": "CUSTOMERS",
            "columns": [
                {"name": "Customer Id", "db_column_name": "CUSTOMER_ID",
                 "db_column_properties": {"data_type": "INT64"}},
                {"name": "Customer Name", "db_column_name": "CUSTOMER_NAME",
                 "db_column_properties": {"data_type": "VARCHAR"}},
            ],
        }},
    }


def _write_export_fixtures(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    model_path = export_dir / "model.json"
    model_path.write_text(json.dumps(_model_tml()), encoding="utf-8")
    for name, tml in _table_tmls().items():
        (export_dir / f"table_{name}.json").write_text(json.dumps(tml), encoding="utf-8")
    return model_path, export_dir


def _write_existing_project(tmp_path, *, with_synonym=False):
    """A project that already has `stg_customers` (CUSTOMERS table only) —
    ORDERS/stg_orders does not exist yet, so it's the "new table" case."""
    proj = tmp_path / "existing_project"
    staging = proj / "models" / "staging"
    staging.mkdir(parents=True)
    (staging / "stg_customers.sql").write_text(
        "select * from {{ source('warehouse', 'CUSTOMERS') }}\n", encoding="utf-8")

    customer_meta = {"ts_column_type": "attribute"}
    if with_synonym:
        customer_meta["ts_synonym"] = "Client"
    schema_doc = {
        "version": 2,
        "models": [{
            "name": "stg_customers",
            "columns": [{"name": "CUSTOMER_NAME", "config": {"meta": customer_meta}}],
        }],
    }
    (proj / "models" / "schema.yml").write_text(
        yaml.safe_dump(schema_doc, sort_keys=False), encoding="utf-8")

    sources_doc = {
        "version": 2,
        "sources": [{
            "name": "warehouse", "database": "DB", "schema": "S",
            "tables": [{"name": "CUSTOMERS"}],
        }],
    }
    (staging / "sources.yml").write_text(
        yaml.safe_dump(sources_doc, sort_keys=False), encoding="utf-8")
    return proj


def _invoke(cmd, model_path, export_dir, project_dir):
    return runner.invoke(app, [
        "dbt-export", cmd,
        "--model", str(model_path), "--tables-dir", str(export_dir),
        "--project-name", "sales", "--source-name", "warehouse",
        "--project-dir", str(project_dir),
    ])


class TestDiffCmd:
    def test_new_table_and_new_source_table_detected(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)

        result = _invoke("diff", model_path, export_dir, proj)
        assert result.exit_code == 0, result.output
        change_set = json.loads(result.stdout)
        assert change_set["new_tables"] == ["stg_orders"]
        assert change_set["removed_tables"] == []
        assert change_set["new_source_tables"] == ["ORDERS"]
        assert change_set["removed_source_tables"] == []

    def test_modified_meta_on_existing_table_detected(self, tmp_path):
        # Existing project's stg_customers has no ts_synonym; the fresh Model
        # column carries synonyms=["Client"] -> ts_synonym should be flagged.
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path, with_synonym=False)

        result = _invoke("diff", model_path, export_dir, proj)
        change_set = json.loads(result.stdout)
        modified = change_set["changed_tables"]["stg_customers"]["modified_meta"]
        assert modified == [{
            "column": "CUSTOMER_NAME",
            "current": {"ts_column_type": "attribute"},
            "new": {"ts_column_type": "attribute", "ts_synonym": "Client"},
        }]

    def test_no_diff_when_already_in_sync(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path, with_synonym=True)

        result = _invoke("diff", model_path, export_dir, proj)
        change_set = json.loads(result.stdout)
        assert "stg_customers" not in change_set["changed_tables"]

    def test_never_writes_to_project_dir(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        before = sorted(p.relative_to(proj) for p in proj.rglob("*") if p.is_file())

        _invoke("diff", model_path, export_dir, proj)

        after = sorted(p.relative_to(proj) for p in proj.rglob("*") if p.is_file())
        assert before == after
        assert not (proj / "models" / "staging" / "stg_orders.sql").exists()

    def test_removed_table_reported(self, tmp_path):
        # A Model with only CUSTOMERS -> stg_orders should show up as removed.
        model_tml = _model_tml()
        model_tml["model"]["model_tables"] = [{"id": "CUSTOMERS", "name": "CUSTOMERS"}]
        model_tml["model"]["columns"] = [
            c for c in model_tml["model"]["columns"] if c["column_id"].startswith("CUSTOMERS")
        ]
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        model_path = export_dir / "model.json"
        model_path.write_text(json.dumps(model_tml), encoding="utf-8")
        (export_dir / "table_CUSTOMERS.json").write_text(
            json.dumps(_table_tmls()["CUSTOMERS"]), encoding="utf-8")

        proj = _write_existing_project(tmp_path)
        # Existing project also has an stg_orders.sql the Model no longer produces.
        (proj / "models" / "staging" / "stg_orders.sql").write_text("select 1\n", encoding="utf-8")

        result = _invoke("diff", model_path, export_dir, proj)
        change_set = json.loads(result.stdout)
        assert change_set["removed_tables"] == ["stg_orders"]
        assert change_set["new_tables"] == []


    def test_nested_layout_finds_sql_and_yaml(self, tmp_path):
        """SQL and schema YAML in arbitrary subdirectories are discovered
        by the recursive glob — not just flat models/staging/*.sql."""
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = tmp_path / "nested_project"

        # Nested layout: SQL and schema in a sub-subdirectory.
        nested = proj / "models" / "staging" / "core"
        nested.mkdir(parents=True)
        (nested / "stg_customers.sql").write_text(
            "select * from {{ source('warehouse', 'CUSTOMERS') }}\n", encoding="utf-8")
        schema_doc = {
            "version": 2,
            "models": [{
                "name": "stg_customers",
                "columns": [{"name": "CUSTOMER_NAME", "config": {"meta": {"ts_column_type": "attribute"}}}],
            }],
        }
        (nested / "schema.yml").write_text(
            yaml.safe_dump(schema_doc, sort_keys=False), encoding="utf-8")

        # Sources in a different nested location.
        src_dir = proj / "models" / "staging" / "sources"
        src_dir.mkdir(parents=True)
        sources_doc = {
            "version": 2,
            "sources": [{"name": "warehouse", "database": "DB", "schema": "S",
                          "tables": [{"name": "CUSTOMERS"}]}],
        }
        (src_dir / "sources.yml").write_text(
            yaml.safe_dump(sources_doc, sort_keys=False), encoding="utf-8")

        result = _invoke("diff", model_path, export_dir, proj)
        assert result.exit_code == 0, result.output
        change_set = json.loads(result.stdout)

        # stg_customers was found in the nested dir → not "new"
        assert "stg_customers" not in change_set["new_tables"]
        # stg_orders still doesn't exist anywhere → "new"
        assert "stg_orders" in change_set["new_tables"]
        # CUSTOMERS was found in the nested sources → not "new"
        assert "CUSTOMERS" not in change_set["new_source_tables"]
        # stg_customers's synonym change is detected via the nested schema.yml
        assert "stg_customers" in change_set["changed_tables"]
        modified = change_set["changed_tables"]["stg_customers"]["modified_meta"]
        assert any(m["column"] == "CUSTOMER_NAME" and "ts_synonym" in m["new"]
                   for m in modified)


class TestSyncCmd:
    def test_writes_new_table_sql_file(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)

        result = _invoke("sync", model_path, export_dir, proj)
        assert result.exit_code == 0, result.output

        new_sql = proj / "models" / "staging" / "stg_orders.sql"
        assert new_sql.is_file()
        assert "source('warehouse', 'ORDERS')" in new_sql.read_text(encoding="utf-8")

    def test_does_not_touch_existing_table_sql_file(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        existing_sql = proj / "models" / "staging" / "stg_customers.sql"
        original_content = existing_sql.read_text(encoding="utf-8")

        _invoke("sync", model_path, export_dir, proj)

        assert existing_sql.read_text(encoding="utf-8") == original_content

    def test_appends_new_model_to_schema_yaml_without_dropping_existing(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)

        _invoke("sync", model_path, export_dir, proj)

        schema_doc = yaml.safe_load(
            (proj / "models" / "schema.yml").read_text(encoding="utf-8"))
        model_names = {m["name"] for m in schema_doc["models"]}
        assert model_names == {"stg_customers", "stg_orders"}
        # The pre-existing stg_customers entry (no ts_synonym yet) is untouched.
        customers_model = next(m for m in schema_doc["models"] if m["name"] == "stg_customers")
        assert customers_model["columns"][0]["config"]["meta"] == {"ts_column_type": "attribute"}

    def test_merges_new_source_table_into_matching_source_block(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)

        _invoke("sync", model_path, export_dir, proj)

        sources_doc = yaml.safe_load(
            (proj / "models" / "staging" / "sources.yml").read_text(encoding="utf-8"))
        assert len(sources_doc["sources"]) == 1
        table_names = {t["name"] for t in sources_doc["sources"][0]["tables"]}
        assert table_names == {"CUSTOMERS", "ORDERS"}

    def test_merges_new_source_table_into_nested_sources_file(self, tmp_path):
        """sync writes to the subdirectory sources.yml that already has source_name,
        not to the default models/staging/sources.yml — regression for the bug where
        models/staging/barbershop/sources.yml existed but sync created a new top-level file."""
        model_path, export_dir = _write_export_fixtures(tmp_path)

        proj = tmp_path / "nested_project"
        sub = proj / "models" / "staging" / "barbershop"
        sub.mkdir(parents=True)
        (sub / "stg_customers.sql").write_text(
            "select * from {{ source('warehouse', 'CUSTOMERS') }}\n", encoding="utf-8")
        schema_doc = {"version": 2, "models": [{
            "name": "stg_customers",
            "columns": [{"name": "CUSTOMER_NAME",
                         "config": {"meta": {"ts_column_type": "attribute"}}}],
        }]}
        (sub / "schema.yml").write_text(
            yaml.safe_dump(schema_doc, sort_keys=False), encoding="utf-8")
        sources_doc = {"version": 2, "sources": [{
            "name": "warehouse", "database": "DB", "schema": "S",
            "tables": [{"name": "CUSTOMERS"}],
        }]}
        nested_sources = sub / "sources.yml"
        nested_sources.write_text(
            yaml.safe_dump(sources_doc, sort_keys=False), encoding="utf-8")

        _invoke("sync", model_path, export_dir, proj)

        # The nested file must be updated (new ORDERS entry merged in).
        updated_doc = yaml.safe_load(nested_sources.read_text(encoding="utf-8"))
        table_names = {t["name"] for t in updated_doc["sources"][0]["tables"]}
        assert table_names == {"CUSTOMERS", "ORDERS"}

        # A new top-level models/staging/sources.yml must NOT have been created.
        assert not (proj / "models" / "staging" / "sources.yml").exists()

    def test_reports_changed_tables_without_applying_them(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path, with_synonym=False)

        result = _invoke("sync", model_path, export_dir, proj)
        payload = json.loads(result.stdout)
        assert "stg_customers" in payload["changed_tables"]

        # stg_customers's own file was not touched despite the reported diff.
        schema_doc = yaml.safe_load(
            (proj / "models" / "schema.yml").read_text(encoding="utf-8"))
        customers_model = next(m for m in schema_doc["models"] if m["name"] == "stg_customers")
        assert customers_model["columns"][0]["config"]["meta"] == {"ts_column_type": "attribute"}


class TestSyncUpdateMetadata:
    """--update-metadata updates ts_* meta on existing tables."""

    def _setup_project(self, tmp_path):
        """Create a minimal existing dbt project with one table (stg_orders)."""
        (tmp_path / "models" / "staging").mkdir(parents=True)
        schema = {
            "version": 2,
            "models": [{
                "name": "stg_orders",
                "columns": [
                    {
                        "name": "CUSTOMER_ID",
                        "config": {"meta": {"ts_column_type": "attribute"}},
                    },
                    {
                        "name": "AMOUNT",
                        "config": {"meta": {
                            "ts_column_type": "measure",
                            "ts_aggregation": "sum",
                        }},
                    },
                ],
            }],
        }
        (tmp_path / "models" / "staging" / "schema.yml").write_text(
            yaml.safe_dump(schema), encoding="utf-8")
        (tmp_path / "models" / "staging" / "stg_orders.sql").write_text(
            "select * from orders", encoding="utf-8")
        sources = {
            "version": 2,
            "sources": [{"name": "src", "database": "DB", "schema": "S",
                          "tables": [{"name": "ORDERS"}]}],
        }
        (tmp_path / "models" / "staging" / "sources.yml").write_text(
            yaml.safe_dump(sources), encoding="utf-8")

    def _model_tml_with_synonym(self):
        return {
            "model": {
                "name": "Sales Model",
                "model_tables": [
                    {"id": "ORDERS", "name": "ORDERS"},
                ],
                "columns": [
                    {"name": "CUSTOMER_ID", "column_id": "ORDERS::CUSTOMER_ID",
                     "properties": {"column_type": "ATTRIBUTE",
                                    "synonyms": ["cust id"]}},
                    {"name": "AMOUNT", "column_id": "ORDERS::AMOUNT",
                     "description": "Revenue amount",
                     "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
                ],
                "formulas": [],
            }
        }

    def _table_tmls(self):
        return {
            "ORDERS": {"table": {
                "name": "ORDERS", "db": "DB", "schema": "S", "db_table": "ORDERS",
                "columns": [
                    {"name": "CUSTOMER_ID", "db_column_name": "CUSTOMER_ID",
                     "db_column_properties": {"data_type": "VARCHAR"}},
                    {"name": "AMOUNT", "db_column_name": "AMOUNT",
                     "db_column_properties": {"data_type": "DOUBLE"}},
                ],
            }},
        }

    def _invoke_with_flag(self, tmp_path, *extra_args):
        export_dir = tmp_path / "export"
        export_dir.mkdir(exist_ok=True)
        (export_dir / "model.json").write_text(
            json.dumps(self._model_tml_with_synonym()), encoding="utf-8")
        for name, data in self._table_tmls().items():
            (export_dir / f"table_{name}.json").write_text(
                json.dumps(data), encoding="utf-8")
        return runner.invoke(app, [
            "dbt-export", "sync",
            "--model", str(export_dir / "model.json"),
            "--tables-dir", str(export_dir),
            "--project-name", "sales",
            "--source-name", "src",
            "--project-dir", str(tmp_path),
            *extra_args,
        ])

    def test_without_flag_changed_tables_not_applied(self, tmp_path):
        """Without --update-metadata, ts_* meta changes are NOT written to disk."""
        self._setup_project(tmp_path)
        result = self._invoke_with_flag(tmp_path)
        assert result.exit_code == 0
        schema_text = (tmp_path / "models" / "staging" / "schema.yml").read_text()
        assert "cust id" not in schema_text

    def test_with_flag_ts_meta_updated(self, tmp_path):
        """With --update-metadata, ts_synonym is written to the existing column."""
        self._setup_project(tmp_path)
        result = self._invoke_with_flag(tmp_path, "--update-metadata")
        assert result.exit_code == 0, result.output
        schema_text = (tmp_path / "models" / "staging" / "schema.yml").read_text()
        assert "cust id" in schema_text

    def test_with_flag_description_updated(self, tmp_path):
        """With --update-metadata, column description is synced from fresh schema."""
        self._setup_project(tmp_path)
        result = self._invoke_with_flag(tmp_path, "--update-metadata")
        assert result.exit_code == 0, result.output
        schema_text = (tmp_path / "models" / "staging" / "schema.yml").read_text()
        assert "Revenue amount" in schema_text

    def test_with_flag_preserves_non_ts_meta(self, tmp_path):
        """With --update-metadata, non-ts_* meta keys are NOT overwritten."""
        (tmp_path / "models" / "staging").mkdir(parents=True)
        schema = {
            "version": 2,
            "models": [{
                "name": "stg_orders",
                "columns": [
                    {
                        "name": "CUSTOMER_ID",
                        "config": {"meta": {
                            "ts_column_type": "attribute",
                            "my_custom_key": "keep_this",
                        }},
                    },
                    {
                        "name": "AMOUNT",
                        "config": {"meta": {
                            "ts_column_type": "measure",
                            "ts_aggregation": "sum",
                        }},
                    },
                ],
            }],
        }
        (tmp_path / "models" / "staging" / "schema.yml").write_text(
            yaml.safe_dump(schema), encoding="utf-8")
        (tmp_path / "models" / "staging" / "stg_orders.sql").write_text(
            "select * from orders", encoding="utf-8")
        sources = {
            "version": 2,
            "sources": [{"name": "src", "database": "DB", "schema": "S",
                          "tables": [{"name": "ORDERS"}]}],
        }
        (tmp_path / "models" / "staging" / "sources.yml").write_text(
            yaml.safe_dump(sources), encoding="utf-8")

        result = self._invoke_with_flag(tmp_path, "--update-metadata")
        assert result.exit_code == 0, result.output
        schema_text = (tmp_path / "models" / "staging" / "schema.yml").read_text()
        assert "my_custom_key" in schema_text
        assert "keep_this" in schema_text

    def _setup_project_with_extra_col(self, tmp_path, extra_col_meta: dict):
        """Project with stg_orders that has an extra column beyond what the fresh Model produces."""
        (tmp_path / "models" / "staging").mkdir(parents=True)
        schema = {
            "version": 2,
            "models": [{
                "name": "stg_orders",
                "columns": [
                    {"name": "CUSTOMER_ID",
                     "config": {"meta": {"ts_column_type": "attribute"}}},
                    {"name": "AMOUNT",
                     "config": {"meta": {"ts_column_type": "measure",
                                         "ts_aggregation": "sum"}}},
                    {"name": "EXTRA_COL", "config": {"meta": extra_col_meta}},
                ],
            }],
        }
        (tmp_path / "models" / "staging" / "schema.yml").write_text(
            yaml.safe_dump(schema), encoding="utf-8")
        (tmp_path / "models" / "staging" / "stg_orders.sql").write_text(
            "select * from orders", encoding="utf-8")
        sources = {
            "version": 2,
            "sources": [{"name": "src", "database": "DB", "schema": "S",
                          "tables": [{"name": "ORDERS"}]}],
        }
        (tmp_path / "models" / "staging" / "sources.yml").write_text(
            yaml.safe_dump(sources), encoding="utf-8")

    def test_ts_only_column_removed_when_deleted_from_ts(self, tmp_path):
        """A ts_*-only column removed from the ThoughtSpot model is deleted from schema.yml."""
        self._setup_project_with_extra_col(tmp_path, {"ts_column_type": "attribute"})
        result = self._invoke_with_flag(tmp_path, "--update-metadata")
        assert result.exit_code == 0, result.output
        schema_text = (tmp_path / "models" / "staging" / "schema.yml").read_text()
        assert "EXTRA_COL" not in schema_text

    def test_non_ts_column_preserved_when_deleted_from_ts(self, tmp_path):
        """A column with non-ts_* content is NOT deleted even when removed from TS model."""
        self._setup_project_with_extra_col(
            tmp_path, {"ts_column_type": "attribute", "owner": "data-team"})
        result = self._invoke_with_flag(tmp_path, "--update-metadata")
        assert result.exit_code == 0, result.output
        schema_text = (tmp_path / "models" / "staging" / "schema.yml").read_text()
        assert "EXTRA_COL" in schema_text
        assert "owner" in schema_text


class TestCaseBAdoptsExistingNames:
    """Case B must pair Model tables with the project's existing models by the
    warehouse table they select from (database+schema+table), not by the
    generator's stg_<table> naming — and scope 'removed' to that footprint."""

    def _renamed_project(self, tmp_path):
        proj = tmp_path / "renamed_project"
        bs = proj / "models" / "staging" / "barbershop"
        other = proj / "models" / "staging" / "jaffle"
        bs.mkdir(parents=True); other.mkdir(parents=True)
        # renamed staging models (no stg_ prefix) for DB.S
        (bs / "customers.sql").write_text(
            "select * from {{ source('warehouse', 'CUSTOMERS') }}\n", encoding="utf-8")
        (bs / "orders.sql").write_text(
            "select * from {{ source('warehouse', 'ORDERS') }}\n", encoding="utf-8")
        (bs / "sources.yml").write_text(yaml.safe_dump({
            "version": 2, "sources": [{"name": "warehouse", "database": "DB", "schema": "S",
                                       "tables": [{"name": "CUSTOMERS"}, {"name": "ORDERS"}]}]},
            sort_keys=False), encoding="utf-8")
        # an unrelated source with a same-named table + its own models
        (other / "stg_customers.sql").write_text(
            "select * from {{ source('jaffle', 'customers') }}\n", encoding="utf-8")
        (other / "fct_orders.sql").write_text("select 1\n", encoding="utf-8")
        (other / "src_jaffle.yml").write_text(yaml.safe_dump({
            "version": 2, "sources": [{"name": "jaffle", "database": "RAW", "schema": "J",
                                       "tables": [{"name": "customers"}, {"name": "payment"}]}]},
            sort_keys=False), encoding="utf-8")
        return proj

    def test_adopts_names_by_location_and_scopes_removed(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = self._renamed_project(tmp_path)
        result = _invoke("diff", model_path, export_dir, proj)
        assert result.exit_code == 0, result.output
        cs = json.loads(result.stdout)
        assert cs["adopted_names"] == {"CUSTOMERS": "customers", "ORDERS": "orders"}
        assert cs["scoped_to"] == ["models/staging/barbershop"]
        assert cs["new_tables"] == [] and cs["removed_tables"] == []
        # other sources' tables are not this Model's business
        assert cs["removed_source_tables"] == [] and cs["new_source_tables"] == []

    def test_refs_use_adopted_names(self, tmp_path):
        from ts_cli.dbt_build_export import build_dbt_export
        files, info = build_dbt_export(
            model_tml=_model_tml(), table_tmls=_table_tmls(), project_name="p",
            source_name="warehouse", model_name_overrides={"CUSTOMERS": "customers"})
        assert "customers" in info["model_names"] and "stg_customers" not in info["model_names"]
        assert "models/staging/customers.sql" in files
        assert "ref('customers')" in files["models/schema.yml"]

    def test_ambiguous_location_falls_back_to_default_name(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = self._renamed_project(tmp_path)
        # two models selecting the same DB.S.CUSTOMERS, neither named like the
        # table → ambiguous source match and no name match → default stg_ name
        bs = proj / "models" / "staging" / "barbershop"
        (bs / "customers.sql").rename(bs / "cust_a.sql")
        (proj / "models" / "staging" / "jaffle" / "stg_customers.sql").rename(
            proj / "models" / "staging" / "jaffle" / "stg_jaffle_customers.sql")
        (bs / "cust_b.sql").write_text(
            "select * from {{ source('warehouse', 'CUSTOMERS') }}\n", encoding="utf-8")
        cs = json.loads(_invoke("diff", model_path, export_dir, proj).stdout)
        assert "CUSTOMERS" not in cs["adopted_names"]
        assert "stg_customers" in cs["new_tables"]

    def test_dbt_output_table_adopted_by_model_name(self, tmp_path):
        """ThoughtSpot Tables created by ts-convert-from-dbt point at the dbt
        models' OUTPUT relations (target schema), not at the raw sources — match
        them to the model of the same name and don't regenerate a source entry."""
        tables = _table_tmls()
        for t in tables.values():                      # Tables live in the dbt target schema
            t["table"]["schema"] = "DBT_OUT"
        export_dir = tmp_path / "export"; export_dir.mkdir()
        model_path = export_dir / "model.json"
        model_path.write_text(json.dumps(_model_tml()), encoding="utf-8")
        for name, tml in tables.items():
            (export_dir / f"table_{name}.json").write_text(json.dumps(tml), encoding="utf-8")
        proj = self._renamed_project(tmp_path)         # models read from DB.S (raw), named customers/orders
        cs = json.loads(_invoke("diff", model_path, export_dir, proj).stdout)
        assert cs["adopted_names"] == {"CUSTOMERS": "customers", "ORDERS": "orders"}
        assert cs["dbt_output_tables"] == ["CUSTOMERS", "ORDERS"]
        assert cs["new_tables"] == [] and cs["removed_tables"] == []
        assert cs["new_source_tables"] == []           # DBT_OUT.* is not a source to add



class TestExcludedColumnNeverAutoDeleted:
    def test_is_ts_only_column_false_for_excluded(self):
        from ts_cli.commands.dbt_export import _is_ts_only_column
        assert _is_ts_only_column({"name": "X", "config": {"meta": {"ts_column_type": "attribute"}}})
        assert not _is_ts_only_column({"name": "X", "config": {"meta": {"ts_column_type": "attribute",
                                                                         "ts_column_exclude": "yes"}}})


class TestSyncPreservesUnmanagedTsTags(TestSyncUpdateMetadata):
    """`sync --update-metadata` never deletes a `ts_*` tag. A tag the fresh
    generation lacks is kept as written and reported, because its absence is
    ambiguous: ThoughtSpot may never have had the setting (someone wrote it in
    dbt to send it TO ThoughtSpot) or it may have been removed there.

    The earlier rule cleared every generator-owned tag the fresh Model lacked.
    Once `ts_hidden`, `ts_calendar_type`, `ts_currency_type` and
    `ts_geo_config` became owned, that deleted hand-authored values with no
    report (PR #506 review, blocker 5).

    Reuses the parent's fixtures — the fresh Model has none of these tags,
    which is exactly the condition that triggered the loss.
    """

    _HAND_AUTHORED = {
        "ts_column_exclude": "yes",
        # stand-in for a tag added by a ThoughtSpot release newer than this build
        "ts_some_future_tag": "keep me",
    }

    def _setup_with_hand_authored(self, tmp_path, extra_meta=None):
        self._setup_project(tmp_path)
        path = tmp_path / "models" / "staging" / "schema.yml"
        doc = yaml.safe_load(path.read_text())
        col = next(c for c in doc["models"][0]["columns"] if c["name"] == "CUSTOMER_ID")
        col["config"]["meta"].update(extra_meta or self._HAND_AUTHORED)
        path.write_text(yaml.safe_dump(doc), encoding="utf-8")
        return path

    def test_hand_authored_ts_tags_survive_update_metadata(self, tmp_path):
        path = self._setup_with_hand_authored(tmp_path)
        result = self._invoke_with_flag(tmp_path, "--update-metadata")
        assert result.exit_code == 0, result.output

        doc = yaml.safe_load(path.read_text())
        meta = next(c for c in doc["models"][0]["columns"]
                    if c["name"] == "CUSTOMER_ID")["config"]["meta"]
        for key, value in self._HAND_AUTHORED.items():
            assert meta.get(key) == value, f"{key} was dropped by --update-metadata"
        # the managed half still syncs
        assert meta.get("ts_synonym") == "cust id"

    def test_preserved_tags_are_reported_not_silent(self, tmp_path):
        self._setup_with_hand_authored(tmp_path)
        result = self._invoke_with_flag(tmp_path, "--update-metadata")
        assert result.exit_code == 0, result.output
        assert "Kept 2 ts_* tag(s) ThoughtSpot does not set" in result.output
        assert "stg_orders.CUSTOMER_ID" in result.output
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        assert sorted(payload["preserved_meta"]["stg_orders.CUSTOMER_ID"]) == sorted(
            self._HAND_AUTHORED)

    def test_ts_column_exclude_survives_on_its_own(self, tmp_path):
        path = self._setup_with_hand_authored(
            tmp_path, {"ts_column_exclude": "yes"})
        result = self._invoke_with_flag(tmp_path, "--update-metadata")
        assert result.exit_code == 0, result.output
        doc = yaml.safe_load(path.read_text())
        meta = next(c for c in doc["models"][0]["columns"]
                    if c["name"] == "CUSTOMER_ID")["config"]["meta"]
        assert meta.get("ts_column_exclude") == "yes"

    def test_review_case_hand_authored_owned_tags_survive(self, tmp_path):
        """The exact case the review executed: owned tags written by hand were
        cleared and not reported. All of them must survive and be listed."""
        hand = {"ts_hidden": "yes", "ts_calendar_type": "fiscal",
                "ts_geo_config": {"type": "country"}, "ts_column_exclude": "no",
                "owner": "finance"}
        path = self._setup_with_hand_authored(tmp_path, hand)
        result = self._invoke_with_flag(tmp_path, "--update-metadata")
        assert result.exit_code == 0, result.output
        meta = next(c for c in yaml.safe_load(path.read_text())["models"][0]["columns"]
                    if c["name"] == "CUSTOMER_ID")["config"]["meta"]
        for key, value in hand.items():
            assert meta.get(key) == value, key
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        assert set(payload["preserved_meta"]["stg_orders.CUSTOMER_ID"]) >= {
            "ts_hidden", "ts_calendar_type", "ts_geo_config", "ts_column_exclude"}

    def test_tag_thoughtspot_does_not_set_is_kept_and_reported(self, tmp_path):
        """Even a tag `build` does generate is kept when the fresh Model lacks
        it — the removal is reported for a human, never applied."""
        self._setup_project(tmp_path)
        path = tmp_path / "models" / "staging" / "schema.yml"
        doc = yaml.safe_load(path.read_text())
        col = next(c for c in doc["models"][0]["columns"] if c["name"] == "AMOUNT")
        col["config"]["meta"]["ts_format_pattern"] = "#,##0.00"
        path.write_text(yaml.safe_dump(doc), encoding="utf-8")

        result = self._invoke_with_flag(tmp_path, "--update-metadata")
        assert result.exit_code == 0, result.output
        meta = next(c for c in yaml.safe_load(path.read_text())["models"][0]["columns"]
                    if c["name"] == "AMOUNT")["config"]["meta"]
        assert meta["ts_format_pattern"] == "#,##0.00"
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        assert "ts_format_pattern" in payload["preserved_meta"]["stg_orders.AMOUNT"]

    def test_diff_does_not_report_a_kept_tag_as_a_change(self, tmp_path):
        """`diff` shows what `sync` writes; a kept tag is not a pending removal."""
        self._setup_project(tmp_path)
        path = tmp_path / "models" / "staging" / "schema.yml"
        doc = yaml.safe_load(path.read_text())
        col = next(c for c in doc["models"][0]["columns"] if c["name"] == "AMOUNT")
        col["config"]["meta"]["ts_format_pattern"] = "#,##0.00"
        path.write_text(yaml.safe_dump(doc), encoding="utf-8")
        payload = self._run_diff(tmp_path)
        mods = (payload["changed_tables"].get("stg_orders") or {}).get("modified_meta") or []
        assert all(m["column"] != "AMOUNT" for m in mods)

    def _run_diff(self, tmp_path):
        export_dir = tmp_path / "export"
        export_dir.mkdir(exist_ok=True)
        (export_dir / "model.json").write_text(
            json.dumps(self._model_tml_with_synonym()), encoding="utf-8")
        for name, data in self._table_tmls().items():
            (export_dir / f"table_{name}.json").write_text(
                json.dumps(data), encoding="utf-8")
        result = runner.invoke(app, [
            "dbt-export", "diff",
            "--model", str(export_dir / "model.json"),
            "--tables-dir", str(export_dir),
            "--project-name", "sales", "--source-name", "src",
            "--project-dir", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout[result.stdout.index("{"):])

    def test_diff_does_not_report_unmanaged_tags_as_changes(self, tmp_path):
        """`diff` must report exactly what `sync` applies — an unmanaged tag is
        not a change, or the user chases a phantom sync then declines.

        Uses only the future-tag case: `ts_column_exclude` removes the column
        from the diff altogether (asserted separately below), so it cannot
        exercise this path.
        """
        self._setup_with_hand_authored(
            tmp_path, {"ts_some_future_tag": "keep me"})
        payload = self._run_diff(tmp_path)
        mods = payload["changed_tables"]["stg_orders"]["modified_meta"]
        cust = next(m for m in mods if m["column"] == "CUSTOMER_ID")
        assert "ts_some_future_tag" not in cust["current"]
        assert "ts_some_future_tag" not in cust["new"]
        # the managed change is still reported
        assert cust["new"].get("ts_synonym") == "cust id"

    def test_diff_omits_an_excluded_column_entirely(self, tmp_path):
        """A `ts_column_exclude` column is deliberately absent from the Model,
        so it must not read as removed or changed against it."""
        self._setup_with_hand_authored(tmp_path, {"ts_column_exclude": "yes"})
        payload = self._run_diff(tmp_path)
        table = payload["changed_tables"].get("stg_orders", {})
        assert "CUSTOMER_ID" not in (table.get("removed_columns") or [])
        assert all(m["column"] != "CUSTOMER_ID"
                   for m in (table.get("modified_meta") or []))


# ---------------------------------------------------------------------------
# --dry-run and --format md
#
# Why: the skill's Step 6b had the LLM read `diff`'s nested JSON and restate it
# as a change summary for the user. `--format md` is that restatement, done
# deterministically; `--dry-run` makes `sync` produce it without the caller
# having to construct the equivalent `diff` invocation and trust that the two
# saw the same thing.
# ---------------------------------------------------------------------------

def _invoke_with(cmd, model_path, export_dir, project_dir, *extra):
    return runner.invoke(app, [
        "dbt-export", cmd,
        "--model", str(model_path), "--tables-dir", str(export_dir),
        "--project-name", "sales", "--source-name", "warehouse",
        "--project-dir", str(project_dir), *extra,
    ])


def _project_snapshot(proj):
    return {str(p.relative_to(proj)): p.read_bytes()
            for p in sorted(proj.rglob("*")) if p.is_file()}


class TestSyncDryRun:
    def test_writes_absolutely_nothing(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        before = _project_snapshot(proj)

        result = _invoke_with("sync", model_path, export_dir, proj, "--dry-run")

        assert result.exit_code == 0, result.output
        assert _project_snapshot(proj) == before

    def test_dry_run_holds_under_update_metadata_too(self, tmp_path):
        """--update-metadata is the flag that rewrites existing files. A
        --dry-run that only guarded the additive writes would be worse than
        useless: it would look safe and still reformat schema.yml."""
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path, with_synonym=False)
        before = _project_snapshot(proj)

        result = _invoke_with("sync", model_path, export_dir, proj,
                              "--dry-run", "--update-metadata")

        assert result.exit_code == 0, result.output
        assert _project_snapshot(proj) == before

    def test_reports_the_same_change_set_as_diff(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)

        dry = json.loads(_invoke_with("sync", model_path, export_dir, proj,
                                      "--dry-run").stdout)
        diff = json.loads(_invoke("diff", model_path, export_dir, proj).stdout)

        for key in ("new_tables", "removed_tables", "changed_tables",
                    "new_source_tables", "removed_source_tables"):
            assert dry[key] == diff[key], key

    def test_dry_run_reports_no_writes(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        payload = json.loads(_invoke_with("sync", model_path, export_dir, proj,
                                          "--dry-run").stdout)
        assert payload["written"] == []

    def test_without_dry_run_the_same_call_does_write(self, tmp_path):
        """Guards against a --dry-run that is silently always on."""
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        before = _project_snapshot(proj)
        _invoke_with("sync", model_path, export_dir, proj)
        assert _project_snapshot(proj) != before


class TestSyncNeverRewritesUnreadableFiles:
    """PR #506 review, blocker 4: a property file PyYAML cannot parse was read as
    empty, and sync rewrote it with only the generated models. dbt renders Jinja
    before parsing YAML, so every input below is valid dbt."""

    JINJA_LOOP = (
        "version: 2\n"
        "models:\n"
        "{% for m in var('models') %}\n"
        "  - name: {{ m }}\n"
        "{% endfor %}\n"
    )
    UNQUOTED_DOC = (
        "version: 2\n"
        "models:\n"
        "  - name: stg_customers\n"
        "    description: {{ doc('customers') }}\n"
    )

    def _assert_refused_untouched(self, tmp_path, rel_path, content):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        target = proj / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        before = _project_snapshot(proj)

        result = _invoke_with("sync", model_path, export_dir, proj)

        assert result.exit_code == 1, result.output
        assert "Refusing to write" in result.output
        assert rel_path in result.output
        assert _project_snapshot(proj) == before

    def test_jinja_loop_in_schema_yml(self, tmp_path):
        self._assert_refused_untouched(tmp_path, "models/schema.yml", self.JINJA_LOOP)

    def test_unquoted_doc_call(self, tmp_path):
        self._assert_refused_untouched(tmp_path, "models/schema.yml", self.UNQUOTED_DOC)

    def test_jinja_in_a_file_sync_would_not_write(self, tmp_path):
        """Whatever an unread file declares is missing from the plan, so the plan
        itself is wrong — not only the write to that file."""
        self._assert_refused_untouched(
            tmp_path, "models/marts/marts.yml",
            "version: 2\nmodels:\n{% if target.name == 'prod' %}\n  - name: x\n{% endif %}\n")

    def test_diff_and_dry_run_report_the_file(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        (proj / "models" / "schema.yml").write_text(self.JINJA_LOOP, encoding="utf-8")
        before = _project_snapshot(proj)

        for args in (("diff",), ("sync", "--dry-run")):
            result = _invoke_with(args[0], model_path, export_dir, proj, *args[1:])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.stdout)
            assert payload["unreadable_files"] == [{
                "path": "models/schema.yml",
                "reason": "contains dbt Jinja, which is not plain YAML"}]
            assert "plan is incomplete" in result.stderr
        assert _project_snapshot(proj) == before

    def test_bad_format_fails_before_any_write(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        before = _project_snapshot(proj)

        result = _invoke_with("sync", model_path, export_dir, proj, "--format", "yaml")

        assert result.exit_code != 0
        assert _project_snapshot(proj) == before


class TestSyncReadsYamlSuffix:
    """dbt reads `*.yaml` property files as well as `*.yml`."""

    def _yaml_suffix_project(self, tmp_path):
        proj = _write_existing_project(tmp_path)
        (proj / "models" / "schema.yml").rename(proj / "models" / "schema.yaml")
        staging = proj / "models" / "staging"
        (staging / "sources.yml").rename(staging / "sources.yaml")
        return proj

    def test_existing_models_are_seen(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = self._yaml_suffix_project(tmp_path)

        payload = json.loads(_invoke("diff", model_path, export_dir, proj).stdout)

        assert payload["new_tables"] == ["stg_orders"]
        assert payload["new_source_tables"] == ["ORDERS"]

    def test_sync_appends_to_the_yaml_files(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = self._yaml_suffix_project(tmp_path)

        result = _invoke("sync", model_path, export_dir, proj)

        assert result.exit_code == 0, result.output
        assert not (proj / "models" / "schema.yml").exists()
        assert not (proj / "models" / "staging" / "sources.yml").exists()
        schema_doc = yaml.safe_load((proj / "models" / "schema.yaml").read_text(encoding="utf-8"))
        assert {m["name"] for m in schema_doc["models"]} == {"stg_customers", "stg_orders"}
        sources_doc = yaml.safe_load(
            (proj / "models" / "staging" / "sources.yaml").read_text(encoding="utf-8"))
        assert {t["name"] for t in sources_doc["sources"][0]["tables"]} == {"CUSTOMERS", "ORDERS"}


class TestCommitWrites:
    def test_a_failed_staging_step_changes_nothing(self, tmp_path, monkeypatch):
        from ts_cli.dbt import project_io

        first, second = tmp_path / "a.yml", tmp_path / "sub" / "b.yml"
        first.write_text("original\n", encoding="utf-8")
        real_mkstemp = project_io.tempfile.mkstemp
        calls = []

        def flaky_mkstemp(*a, **k):
            calls.append(1)
            if len(calls) == 2:
                raise OSError("disk full")
            return real_mkstemp(*a, **k)

        monkeypatch.setattr(project_io.tempfile, "mkstemp", flaky_mkstemp)
        try:
            project_io.commit_writes({first: "new\n", second: "new\n"})
        except OSError:
            pass
        else:
            raise AssertionError("commit_writes swallowed the failure")

        assert first.read_text(encoding="utf-8") == "original\n"
        assert not second.exists()
        assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == ["a.yml"]

    def test_writes_every_file(self, tmp_path):
        from ts_cli.dbt.project_io import commit_writes

        targets = {tmp_path / "x.yml": "1\n", tmp_path / "d" / "y.sql": "2\n"}
        commit_writes(targets)
        assert {p: p.read_text(encoding="utf-8") for p in targets} == targets


def test_update_metadata_without_models_dir_returns_a_pair(tmp_path):
    """Was `return []` where the caller unpacks two values (PR #506 review)."""
    from ts_cli.commands.dbt_export import _update_existing_schema_models

    writes: dict = {}
    assert _update_existing_schema_models(
        tmp_path, {"files": {}, "new_tables": []}, writes) == ([], {})
    assert writes == {}


class TestFormatMarkdown:
    def test_diff_md_names_the_new_table(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        out = _invoke_with("diff", model_path, export_dir, proj, "--format", "md").stdout
        assert out.lstrip().startswith("## dbt project change-set")
        assert "stg_orders" in out
        assert "### New tables" in out

    def test_md_is_not_json(self, tmp_path):
        import pytest
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        out = _invoke_with("diff", model_path, export_dir, proj, "--format", "md").stdout
        with pytest.raises(ValueError):
            json.loads(out)

    def test_json_is_still_the_default(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        payload = json.loads(_invoke("diff", model_path, export_dir, proj).stdout)
        assert "new_tables" in payload

    def test_removals_lead_the_report(self, tmp_path):
        """The two removed_* lists are the only lines that need a human
        decision — everything else is applied or reported for information."""
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        # A model on disk the Model no longer produces.
        (proj / "models" / "staging" / "stg_ghost.sql").write_text(
            "select * from {{ source('warehouse', 'GHOST') }}\n", encoding="utf-8")

        out = _invoke_with("diff", model_path, export_dir, proj, "--format", "md").stdout
        assert "Needs a decision" in out
        assert out.index("Needs a decision") < out.index("### New tables")
        assert "stg_ghost" in out

    def test_sync_md_lists_what_was_written(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        out = _invoke_with("sync", model_path, export_dir, proj, "--format", "md").stdout
        assert "### Applied" in out
        assert "stg_orders.sql" in out

    def test_dry_run_md_says_would_apply_not_applied(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        out = _invoke_with("sync", model_path, export_dir, proj,
                           "--dry-run", "--format", "md").stdout
        assert "### Would apply" in out
        assert "### Applied" not in out

    def test_bad_format_is_refused_by_name(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        result = _invoke_with("diff", model_path, export_dir, proj, "--format", "xml")
        assert result.exit_code != 0
        assert "json" in result.output and "md" in result.output


class TestMarkdownRenderer:
    """Pure-function coverage of the renderer, independent of the CLI."""

    def test_meta_delta_reads_as_old_to_new(self):
        from ts_cli.dbt.case_b_plan import _meta_delta
        out = _meta_delta({"ts_synonym": "Client"}, {"ts_synonym": "Customer"})
        assert "'Client'" in out and "'Customer'" in out and "→" in out

    def test_meta_delta_marks_additions_and_removals(self):
        from ts_cli.dbt.case_b_plan import _meta_delta
        assert "+" in _meta_delta({}, {"ts_hidden": True})
        assert "−" in _meta_delta({"ts_hidden": True}, {})

    def test_empty_change_set_still_renders_a_summary(self):
        from ts_cli.dbt.case_b_plan import render_report_markdown
        out = render_report_markdown({
            "new_tables": [], "removed_tables": [], "changed_tables": {},
            "new_source_tables": [], "removed_source_tables": [],
        })
        assert "## dbt project change-set" in out
        assert "| new tables | 0 |" in out

    def test_preserved_tags_are_named(self):
        from ts_cli.dbt.case_b_plan import render_report_markdown
        out = render_report_markdown(
            {"new_tables": [], "removed_tables": [], "changed_tables": {},
             "new_source_tables": [], "removed_source_tables": []},
            written=[], preserved={"stg_orders.AMOUNT": ["ts_column_exclude"]})
        assert "ts_column_exclude" in out and "stg_orders.AMOUNT" in out

    def test_removed_relationship_is_marked_never_auto_deleted(self):
        from ts_cli.dbt.case_b_plan import render_report_markdown
        out = render_report_markdown({
            "new_tables": [], "removed_tables": [], "new_source_tables": [],
            "removed_source_tables": [],
            "changed_tables": {"stg_orders": {"removed_relationship": ["CUSTOMER_ID"]}},
        })
        assert "never auto-deleted" in out


# ---------------------------------------------------------------------------
# build-model --model-guid / --import
#
# Why: the skill used to say "add "guid": "{model_guid}" at the document root"
# between emitting the TML and piping it to `ts tml import`. A hand-edit
# between two commands, where getting it wrong or skipping it does not fail —
# it silently creates a SECOND Model beside the one being updated.
# ---------------------------------------------------------------------------

_SCHEMA_YML = """\
version: 2
models:
  - name: stg_orders
    columns:
      - name: CUSTOMER_ID
        config:
          meta:
            ts_column_type: attribute
        data_tests:
          - relationships:
              arguments:
                to: ref('stg_customers')
                field: CUSTOMER_ID
              config:
                meta:
                  ts_join_name: orders_to_customers
                  ts_join_type: left_outer
                  ts_join_cardinality: many_to_one
  - name: stg_customers
    columns:
      - name: CUSTOMER_ID
        config:
          meta:
            ts_column_type: attribute
"""


class TestBuildModelGuidAndImport:
    def _schema(self, tmp_path):
        p = tmp_path / "schema.yml"
        p.write_text(_SCHEMA_YML, encoding="utf-8")
        return p

    def _invoke(self, tmp_path, *extra):
        return runner.invoke(app, [
            "dbt-export", "build-model",
            "--schema-yml", str(self._schema(tmp_path)),
            "--model-name", "SALES", *extra])

    def test_model_guid_lands_at_the_document_root(self, tmp_path):
        """`guid:` nested under `model:` is rejected — thoughtspot-model-tml.md."""
        result = self._invoke(tmp_path, "--model-guid", "m-123")
        assert result.exit_code == 0, result.output
        tml = json.loads(result.stdout)
        assert tml["guid"] == "m-123"
        assert list(tml)[0] == "guid"
        assert "guid" not in tml["model"]

    def test_no_model_guid_emits_no_guid_at_all(self, tmp_path):
        result = self._invoke(tmp_path)
        assert result.exit_code == 0, result.output
        assert "guid" not in json.loads(result.stdout)

    def test_model_guid_is_also_in_the_output_file(self, tmp_path):
        """--output and stdout must carry the identical document; a guid applied
        to only one of them is the same duplicate-Model footgun in a new place."""
        out = tmp_path / "model.json"
        result = self._invoke(tmp_path, "--model-guid", "m-123", "--output", str(out))
        assert result.exit_code == 0, result.output
        assert json.loads(out.read_text())["guid"] == "m-123"

    def test_import_requires_a_profile(self, tmp_path):
        result = self._invoke(tmp_path, "--import")
        assert result.exit_code != 0
        assert "--profile" in result.output

    def test_import_with_a_guid_updates_in_place(self, tmp_path, monkeypatch):
        seen = {}

        def fake_import(profile, doc, *, policy="PARTIAL", no_create_new=False, label=None):
            seen.update(profile=profile, doc=doc, policy=policy,
                        no_create_new=no_create_new)
            return "imported", "m-123", None

        monkeypatch.setattr("ts_cli.io_helpers.run_tml_import", fake_import)
        result = self._invoke(tmp_path, "--model-guid", "m-123",
                              "--import", "--profile", "Embed-1-Prod")
        assert result.exit_code == 0, result.output
        assert seen["no_create_new"] is True          # create_new=false
        assert seen["doc"]["guid"] == "m-123"
        assert seen["policy"] == "ALL_OR_NONE"
        payload = json.loads(result.stdout)
        assert payload["status"] == "imported" and payload["created_new"] is False

    def test_import_without_a_guid_creates_new_and_says_so(self, tmp_path, monkeypatch):
        seen = {}

        def fake_import(profile, doc, *, policy="PARTIAL", no_create_new=False, label=None):
            seen.update(no_create_new=no_create_new)
            return "imported", "brand-new", None

        monkeypatch.setattr("ts_cli.io_helpers.run_tml_import", fake_import)
        result = self._invoke(tmp_path, "--import", "--profile", "Embed-1-Prod")
        assert result.exit_code == 0, result.output
        assert seen["no_create_new"] is False
        assert json.loads(result.stdout)["created_new"] is True

    def test_a_failed_import_exits_nonzero_with_the_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ts_cli.io_helpers.run_tml_import",
            lambda *a, **k: ("failed", None, "Multiple columns with the same name found"))
        result = self._invoke(tmp_path, "--model-guid", "m-1",
                              "--import", "--profile", "P")
        assert result.exit_code != 0
        assert "Multiple columns with the same name" in result.output

    def test_no_import_flag_means_no_import_call(self, tmp_path, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("build-model must not import without --import")

        monkeypatch.setattr("ts_cli.io_helpers.run_tml_import", _boom)
        assert self._invoke(tmp_path, "--model-guid", "m-1").exit_code == 0

    def test_emitting_to_a_file_does_not_also_print_the_tml(self, tmp_path):
        out = tmp_path / "model.json"
        result = self._invoke(tmp_path, "--output", str(out))
        assert result.exit_code == 0, result.output
        assert "model_tables" not in result.stdout


class TestDeletionGate:
    """`_is_ts_only_column` decides which removed columns `sync --update-metadata`
    deletes. "Removed" means "in dbt, not in the Model", and a Model usually
    exposes only some columns — so anything not demonstrably generated must be
    kept (PR #506 review, blocker 5)."""

    GENERATED = {"name": "AMOUNT",
                 "config": {"meta": {"ts_column_type": "measure", "ts_aggregation": "sum"}}}

    def _gate(self, entry):
        from ts_cli.dbt.case_b_plan import _is_ts_only_column
        return _is_ts_only_column(entry)

    def test_a_generated_entry_is_deletable(self):
        assert self._gate(self.GENERATED) is True
        with_rel = {**self.GENERATED, "data_tests": [{"relationships": {"arguments": {}}}]}
        assert self._gate(with_rel) is True

    def test_kept(self):
        cases = {
            "bare entry, no meta": {"name": "AMOUNT"},
            "empty meta": {"name": "AMOUNT", "config": {"meta": {}}},
            "legacy bare meta": {"name": "AMOUNT", "meta": {"owner": "finance"}},
            "legacy bare meta beside config": {**self.GENERATED, "meta": {"owner": "finance"}},
            "config tags": {"name": "AMOUNT", "config": {
                "meta": {"ts_column_type": "measure"}, "tags": ["pii"]}},
            "column-level tags": {**self.GENERATED, "tags": ["pii"]},
            "data_type": {**self.GENERATED, "data_type": "number"},
            "quote": {**self.GENERATED, "quote": True},
            "constraints": {**self.GENERATED, "constraints": [{"type": "not_null"}]},
            "ts tags but no ts_column_type": {"name": "AMOUNT",
                                              "config": {"meta": {"ts_hidden": "yes"}}},
            "non-ts meta key": {"name": "AMOUNT", "config": {
                "meta": {"ts_column_type": "measure", "owner": "finance"}}},
            "description": {**self.GENERATED, "description": "Order amount"},
            "custom test": {**self.GENERATED, "data_tests": ["not_null"]},
            "excluded": {"name": "AMOUNT", "config": {
                "meta": {"ts_column_type": "measure", "ts_column_exclude": "yes"}}},
        }
        for label, entry in cases.items():
            assert self._gate(entry) is False, label


class TestBuildRefusesExistingProject:
    """`build` scaffolds a NEW project. Live-tested 2026-10-06: a second `build`
    into the same directory silently replaced the first project's sources.yml,
    schema.yml and shared staging model, and dbt-core then refused to parse the
    project (ts-convert-to-dbt open-items #6). It must refuse instead."""

    def _build(self, model_path, export_dir, out_dir):
        return runner.invoke(app, [
            "dbt-export", "build",
            "--model", str(model_path), "--tables-dir", str(export_dir),
            "--project-name", "sales", "--source-name", "warehouse",
            "--output-dir", str(out_dir),
        ])

    def test_fresh_directory_is_built(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        out = tmp_path / "proj"
        result = self._build(model_path, export_dir, out)
        assert result.exit_code == 0, result.output
        assert (out / "dbt_project.yml").is_file()

    def test_existing_empty_directory_is_built(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        out = tmp_path / "proj"
        out.mkdir()
        assert self._build(model_path, export_dir, out).exit_code == 0

    def test_second_build_refuses_and_changes_nothing(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        out = tmp_path / "proj"
        assert self._build(model_path, export_dir, out).exit_code == 0
        before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}

        result = self._build(model_path, export_dir, out)

        assert result.exit_code != 0
        assert "already holds a dbt project" in str(result.exception) + result.output
        assert "sync" in str(result.exception) + result.output
        assert {p: p.read_bytes() for p in out.rglob("*") if p.is_file()} == before

    def test_any_existing_dbt_project_is_refused(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        out = tmp_path / "proj"
        out.mkdir()
        (out / "dbt_project.yml").write_text("name: other\n", encoding="utf-8")

        result = self._build(model_path, export_dir, out)

        assert result.exit_code != 0
        assert (out / "dbt_project.yml").read_text(encoding="utf-8") == "name: other\n"
        assert not (out / "models").exists()


class TestSourceNamesCompareCaseInsensitively:
    """PR #506 review: `customers` in db.s and ThoughtSpot's `CUSTOMERS` in DB.S are
    one table. Compared exactly, the diff called it both new and removed, and sync
    appended a second `warehouse` source block — a duplicate name dbt rejects."""

    def _lowercase_project(self, tmp_path):
        proj = _write_existing_project(tmp_path)
        doc = {"version": 2, "sources": [{
            "name": "warehouse", "database": "db", "schema": "s",
            "tables": [{"name": "customers"}]}]}
        (proj / "models" / "staging" / "sources.yml").write_text(
            yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        return proj

    def test_diff_reports_neither_new_nor_removed_for_a_case_difference(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = self._lowercase_project(tmp_path)
        result = runner.invoke(app, [
            "dbt-export", "diff", "--model", str(model_path), "--tables-dir", str(export_dir),
            "--project-name", "sales", "--source-name", "warehouse",
            "--project-dir", str(proj), "--format", "json"])
        assert result.exit_code == 0, result.output
        report = json.loads(result.output[result.output.index("{"):])
        assert report["removed_source_tables"] == []
        assert [t.upper() for t in report["new_source_tables"]] == ["ORDERS"]

    def test_sync_extends_the_existing_block_instead_of_duplicating_it(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = self._lowercase_project(tmp_path)
        result = _invoke("sync", model_path, export_dir, proj)
        assert result.exit_code == 0, result.output
        doc = yaml.safe_load((proj / "models" / "staging" / "sources.yml").read_text())
        assert [s["name"] for s in doc["sources"]] == ["warehouse"]
        assert sorted(t["name"].upper() for t in doc["sources"][0]["tables"]) == [
            "CUSTOMERS", "ORDERS"]

    def test_same_source_name_at_a_different_location_is_refused(self, tmp_path):
        model_path, export_dir = _write_export_fixtures(tmp_path)
        proj = _write_existing_project(tmp_path)
        doc = {"version": 2, "sources": [{
            "name": "warehouse", "database": "OTHER_DB", "schema": "X",
            "tables": [{"name": "CUSTOMERS"}]}]}
        sources = proj / "models" / "staging" / "sources.yml"
        sources.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        before = sources.read_text()
        result = _invoke("sync", model_path, export_dir, proj)
        assert result.exit_code != 0
        assert "duplicate source names" in str(result.exception)
        assert sources.read_text() == before

