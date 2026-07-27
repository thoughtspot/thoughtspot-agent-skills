"""Tests for `ts databricks build-mv` (Task 12) — emit-only CLI wrapper over
mv_emit.build_metric_view / mv_build_view.build_view_ddl.

Mirrors TestBuildModelCommand in test_databricks_build_model.py: CliRunner
invocations of the registered `databricks` Typer app, asserting exit codes,
pure-JSON stdout, and files written to --output-dir.
"""
import json

from typer.testing import CliRunner

from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:  # Click >= 8.2 removed mix_stderr (stderr separated by default)
    runner = CliRunner()

# --- Fixture models --------------------------------------------------------
# Physical-column-only models (no formulas) keep these tests focused on the
# command's own plumbing (fact detection, file writing, summary assembly) --
# mv_emit's formula-translation behaviour is already covered by
# test_databricks_emit.py.

MODEL_SINGLE_FACT = {
    "name": "Sales Model",
    "model_tables": [{"name": "FACT"}],
    "columns": [
        {"name": "Amount", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE"}},
        {"name": "Region", "column_id": "FACT::REGION",
         "properties": {"column_type": "ATTRIBUTE"}},
    ],
    "formulas": [],
}
TABLES_SINGLE_FACT = [
    {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
               "columns": [
                   {"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}},
                   {"name": "REGION", "db_column_properties": {"data_type": "VARCHAR"}},
               ]}},
]

MODEL_MULTI_FACT = {
    "name": "Multi Model",
    "model_tables": [{"name": "FACT_A"}, {"name": "FACT_B"}],
    "columns": [
        {"name": "Amount A", "column_id": "FACT_A::AMOUNT",
         "properties": {"column_type": "MEASURE"}},
        {"name": "Amount B", "column_id": "FACT_B::AMOUNT",
         "properties": {"column_type": "MEASURE"}},
    ],
    "formulas": [],
}
TABLES_MULTI_FACT = [
    {"table": {"name": "FACT_A", "db": "c", "schema": "s", "db_table": "fact_a",
               "columns": [{"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}}]}},
    {"table": {"name": "FACT_B", "db": "c", "schema": "s", "db_table": "fact_b",
               "columns": [{"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}}]}},
]

# A MEASURE formula using a function with no Databricks translation (same
# proven pattern as test_databricks_emit.py's dangling-ref tests) so the
# measure fails emission and lands in skipped[] -- yielding a zero-measure MV
# while Region still emits cleanly as a dimension.
MODEL_ZERO_MEASURE = {
    "name": "Zero Measure Model",
    "model_tables": [{"name": "FACT"}],
    "columns": [
        {"name": "Region", "column_id": "FACT::REGION",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Weird Measure", "formula_id": "formula_weird",
         "properties": {"column_type": "MEASURE"}},
    ],
    "formulas": [
        {"id": "formula_weird", "name": "Weird Measure",
         "expr": "totally_unsupported_fn ( [FACT::REGION] )"},
    ],
}
TABLES_ZERO_MEASURE = [
    {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
               "columns": [{"name": "REGION", "db_column_properties": {"data_type": "VARCHAR"}}]}},
]

# A 2-table joined model (FACT --[inline `on`]--> DIM) used by two tests below:
# one where both tables are present in tables.json (happy path through
# mv_emit.build_joins) and one where DIM is absent (build_joins raises
# UntranslatableError -- the Task 12 review-fix case: that error must surface
# as a clean stderr message + exit 1, not a raw Python traceback).
MODEL_JOINED = {
    "name": "Joined Model",
    "model_tables": [
        {"name": "FACT", "joins": [{"with": "DIM", "on": "[FACT::DIM_ID] = [DIM::ID]"}]},
        {"name": "DIM"},
    ],
    "columns": [
        {"name": "Amount", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE"}},
        {"name": "Dim Name", "column_id": "DIM::NAME",
         "properties": {"column_type": "ATTRIBUTE"}},
    ],
    "formulas": [],
}
TABLES_JOINED_COMPLETE = [
    {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
               "columns": [
                   {"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}},
                   {"name": "DIM_ID", "db_column_properties": {"data_type": "VARCHAR"}},
               ]}},
    {"table": {"name": "DIM", "db": "c", "schema": "s", "db_table": "dim",
               "columns": [
                   {"name": "ID", "db_column_properties": {"data_type": "VARCHAR"}},
                   {"name": "NAME", "db_column_properties": {"data_type": "VARCHAR"}},
               ]}},
]
TABLES_JOINED_MISSING_DIM = [
    {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
               "columns": [
                   {"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}},
                   {"name": "DIM_ID", "db_column_properties": {"data_type": "VARCHAR"}},
               ]}},
]


def _write_build_mv_inputs(tmp_path, model=None, tables=None):
    """Write model.json + tables.json into tmp_path; return tmp_path."""
    (tmp_path / "model.json").write_text(json.dumps({"model": model or MODEL_SINGLE_FACT}))
    (tmp_path / "tables.json").write_text(json.dumps(tables if tables is not None else TABLES_SINGLE_FACT))
    return tmp_path


class TestBuildMvCommand:
    def _run(self, tmp_path, *extra):
        args = ["databricks", "build-mv",
                "--model", str(tmp_path / "model.json"),
                "--tables", str(tmp_path / "tables.json"),
                "--catalog", "c", "--schema", "s",
                "--output-dir", str(tmp_path / "out"), *extra]
        return runner.invoke(app, args)

    def test_happy_path_single_fact(self, tmp_path):
        result = self._run(_write_build_mv_inputs(tmp_path))
        assert result.exit_code == 0, result.output
        summary = json.loads(result.stdout)  # raises if a diagnostic leaked to stdout
        assert len(summary["metric_views"]) == 1
        view_name = summary["metric_views"][0]["view_name"]
        assert view_name.endswith("_mv")
        sql_file = tmp_path / "out" / f"{view_name}.sql"
        assert sql_file.exists()
        assert "CREATE OR REPLACE VIEW" in sql_file.read_text()

    def test_accepts_bare_model_dict(self, tmp_path):
        # Model file need not be envelope-wrapped in {"model": ...}.
        (tmp_path / "model.json").write_text(json.dumps(MODEL_SINGLE_FACT))
        (tmp_path / "tables.json").write_text(json.dumps(TABLES_SINGLE_FACT))
        result = self._run(tmp_path)
        assert result.exit_code == 0, result.output
        summary = json.loads(result.stdout)
        assert summary["model_name"] == "Sales Model"

    def test_multi_fact_no_source_table(self, tmp_path):
        result = self._run(_write_build_mv_inputs(
            tmp_path, model=MODEL_MULTI_FACT, tables=TABLES_MULTI_FACT))
        assert result.exit_code == 0, result.output
        summary = json.loads(result.stdout)
        assert len(summary["metric_views"]) == 2
        for mv in summary["metric_views"]:
            assert (tmp_path / "out" / f"{mv['view_name']}.sql").exists()

    def test_missing_model_file_exits_1(self, tmp_path):
        (tmp_path / "tables.json").write_text(json.dumps(TABLES_SINGLE_FACT))
        result = runner.invoke(app, ["databricks", "build-mv",
                                      "--model", str(tmp_path / "nope.json"),
                                      "--tables", str(tmp_path / "tables.json"),
                                      "--catalog", "c", "--schema", "s",
                                      "--output-dir", str(tmp_path / "out")])
        assert result.exit_code == 1
        assert result.stdout == ""

    def test_missing_tables_file_exits_1(self, tmp_path):
        (tmp_path / "model.json").write_text(json.dumps({"model": MODEL_SINGLE_FACT}))
        result = runner.invoke(app, ["databricks", "build-mv",
                                      "--model", str(tmp_path / "model.json"),
                                      "--tables", str(tmp_path / "nope.json"),
                                      "--catalog", "c", "--schema", "s",
                                      "--output-dir", str(tmp_path / "out")])
        assert result.exit_code == 1

    def test_unparseable_tables_file_exits_1(self, tmp_path):
        (tmp_path / "model.json").write_text(json.dumps({"model": MODEL_SINGLE_FACT}))
        (tmp_path / "tables.json").write_text("not json")
        result = runner.invoke(app, ["databricks", "build-mv",
                                      "--model", str(tmp_path / "model.json"),
                                      "--tables", str(tmp_path / "tables.json"),
                                      "--catalog", "c", "--schema", "s",
                                      "--output-dir", str(tmp_path / "out")])
        assert result.exit_code == 1

    def test_no_fact_detected_exits_1(self, tmp_path):
        model = {"name": "No Measures", "model_tables": [{"name": "FACT"}],
                  "columns": [{"name": "Region", "column_id": "FACT::REGION",
                               "properties": {"column_type": "ATTRIBUTE"}}],
                  "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
                              "columns": [{"name": "REGION",
                                           "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        result = self._run(_write_build_mv_inputs(tmp_path, model=model, tables=tables))
        assert result.exit_code == 1

    def test_source_table_with_view_name_override(self, tmp_path):
        result = self._run(
            _write_build_mv_inputs(tmp_path),
            "--source-table", "FACT", "--view-name", "custom_view")
        assert result.exit_code == 0, result.output
        summary = json.loads(result.stdout)
        assert len(summary["metric_views"]) == 1
        assert summary["metric_views"][0]["view_name"] == "custom_view"
        assert (tmp_path / "out" / "custom_view.sql").exists()

    def test_zero_measure_mv_exits_1(self, tmp_path):
        result = self._run(_write_build_mv_inputs(
            tmp_path, model=MODEL_ZERO_MEASURE, tables=TABLES_ZERO_MEASURE),
            "--source-table", "FACT")
        assert result.exit_code == 1
        summary = json.loads(result.stdout)  # summary still printed before the exit
        assert summary["metric_views"][0]["measures"] == 0
        assert summary["metric_views"][0]["dimensions"] == 1

    def test_joined_model_complete_tables(self, tmp_path):
        # Proves build-mv works end-to-end on a joined model (mv_emit.build_joins
        # actually walking a join), which no prior test in this file covered --
        # every other fixture here is a single, unjoined fact table.
        result = self._run(_write_build_mv_inputs(
            tmp_path, model=MODEL_JOINED, tables=TABLES_JOINED_COMPLETE))
        assert result.exit_code == 0, result.output
        summary = json.loads(result.stdout)
        assert len(summary["metric_views"]) == 1
        view_name = summary["metric_views"][0]["view_name"]
        sql_file = tmp_path / "out" / f"{view_name}.sql"
        assert sql_file.exists()
        ddl = sql_file.read_text()
        assert "CREATE OR REPLACE VIEW" in ddl
        assert "joins:" in ddl

    def test_joined_model_missing_joined_table_clean_error(self, tmp_path):
        # DIM is referenced by FACT's join but absent from tables.json --
        # mv_emit.build_joins raises UntranslatableError (a plain Exception
        # subclass, not ValueError). Before the fix, _build_one_mv's
        # `except ValueError` didn't catch it, so it escaped as a raw
        # traceback instead of the clean stderr message + exit 1 every other
        # failure path gives.
        result = self._run(_write_build_mv_inputs(
            tmp_path, model=MODEL_JOINED, tables=TABLES_JOINED_MISSING_DIM))
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "Traceback" not in result.stderr
        assert "cannot build metric view for fact table 'FACT'" in result.stderr
