import json
import yaml
from typer.testing import CliRunner
from ts_cli.cli import app
from ts_cli.commands.aggregate import _signatures_summary

runner = CliRunner()


def test_aggregate_group_registered():
    result = runner.invoke(app, ["aggregate", "--help"])
    assert result.exit_code == 0
    for sub in ("signatures", "recommend", "profile", "generate", "history"):
        assert sub in result.output


def test_signatures_summary_counts_partials():
    sigs = [{"parse_status": "full"}, {"parse_status": "partial"},
            {"parse_status": "full"}]
    s = _signatures_summary(sigs)
    assert s == {"signatures": 3, "full": 2, "partial": 1}


def test_recommend_runs_offline_from_dir(tmp_path):
    model = {"model": {"name": "M", "columns": [
        {"name": "Sales", "column_id": "F::A",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Category", "column_id": "D::C",
         "properties": {"column_type": "ATTRIBUTE"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    sig = {"source_guid": "g", "source_name": "s", "source_type": "ANSWER",
           "viz_name": None, "dimensions": ["Category"], "date_column": None,
           "date_bucket": None, "measures": ["Sales"], "filter_columns": [],
           "parse_status": "full", "weight": 1.0}
    (tmp_path / "signatures.jsonl").write_text(json.dumps(sig) + "\n")
    result = runner.invoke(app, ["aggregate", "recommend", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["mode"] == "coverage" and out["candidates"] >= 1
    assert out["excluded_unprofiled"] == []
    saved = json.loads((tmp_path / "candidates.json").read_text())
    assert saved["candidates"][0]["dimensions"] == ["Category"]


def test_recommend_cost_mode_reports_excluded_unprofiled(tmp_path):
    """Carry-forward from Task 4 review: unprofiled candidates (agg_rows=None)
    are excluded from cost-mode selection but must still be surfaced so the
    skill can tell the user to profile them."""
    model = {"model": {"name": "M", "columns": [
        {"name": "Sales", "column_id": "F::A",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Category", "column_id": "D::C",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Region", "column_id": "D::R",
         "properties": {"column_type": "ATTRIBUTE"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    sigs = [
        {"source_guid": "g1", "source_name": "s1", "source_type": "ANSWER",
         "viz_name": None, "dimensions": ["Category"], "date_column": None,
         "date_bucket": None, "measures": ["Sales"], "filter_columns": [],
         "parse_status": "full", "weight": 1.0},
        {"source_guid": "g2", "source_name": "s2", "source_type": "ANSWER",
         "viz_name": None, "dimensions": ["Region"], "date_column": None,
         "date_bucket": None, "measures": ["Sales"], "filter_columns": [],
         "parse_status": "full", "weight": 1.0},
    ]
    (tmp_path / "signatures.jsonl").write_text(
        "\n".join(json.dumps(s) for s in sigs) + "\n")
    # First run generates candidates.json with agg_rows=None for every candidate.
    runner.invoke(app, ["aggregate", "recommend", "--dir", str(tmp_path)])
    # Profile only the Category candidate (simulating a partial `profile` run).
    saved = json.loads((tmp_path / "candidates.json").read_text())
    for c in saved["candidates"]:
        if c["dimensions"] == ["Category"]:
            c["agg_rows"] = 10
    (tmp_path / "candidates.json").write_text(json.dumps(saved, indent=2))

    result = runner.invoke(app, ["aggregate", "recommend", "--dir", str(tmp_path),
                                 "--base-rows", "1000"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["mode"] == "cost"
    region_ids = [c["id"] for c in saved["candidates"] if c["dimensions"] == ["Region"]]
    assert out["excluded_unprofiled"] == region_ids


def test_colmap_from_model_skips_formula_backed_columns():
    """Fix 1 (CRITICAL): `_colmap_from_model` (used by `ts aggregate history`
    to match warehouse query-history GROUP BY shapes back to Model display
    names) previously did `c["column_id"].split("::", 1)` for every column
    unconditionally. Every ThoughtSpot formula appears in model.columns[]
    with a formula_id and NO column_id — so a formula-backed column raised a
    bare KeyError here before this fix. It must be skipped (it has no
    physical TABLE.COL shape to match warehouse GROUP BY clauses against),
    not crash the whole command."""
    from ts_cli.commands.aggregate import _colmap_from_model

    model = {"model": {
        "formulas": [{"id": "formula_Avg Sale", "name": "Avg Sale",
                      "expr": "average ( [Sales] )"}],
        "columns": [
            {"name": "Sales", "column_id": "FACT::AMOUNT",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            {"name": "Category", "column_id": "DIM::CATEGORY",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Avg Sale", "formula_id": "formula_Avg Sale",
             "properties": {"column_type": "MEASURE"}},
        ],
    }}
    colmap = _colmap_from_model(model)
    assert colmap == {"FACT.AMOUNT": "Sales", "DIM.CATEGORY": "Category"}


def test_recommend_missing_dir_files_errors_clearly(tmp_path):
    """Fix 4 (NICE): `recommend` against a --dir missing model.tml.yaml/
    signatures.jsonl (e.g. `signatures` was never run, or the wrong --dir was
    passed) must fail with a clear diagnostic, not a bare FileNotFoundError
    traceback."""
    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "recommend", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "model.tml.yaml" in result.stderr
    assert "ts aggregate signatures" in result.stderr


def test_filtered_dependents_keeps_only_answers_and_liveboards(monkeypatch):
    from ts_cli.commands import aggregate as agg_mod

    def fake_collect(client, guid, type="LOGICAL_TABLE"):
        return [
            {"guid": "a1", "name": "Answer 1", "type": "ANSWER", "owner": None},
            {"guid": "lb1", "name": "LB 1", "type": "LIVEBOARD", "owner": None},
            {"guid": "m1", "name": "Sub Model", "type": "LOGICAL_TABLE", "owner": None},
        ]

    monkeypatch.setattr("ts_cli.commands.metadata._collect_dependents", fake_collect)
    result = agg_mod._filtered_dependents(client=None, model_guid="m")
    assert {d["guid"] for d in result} == {"a1", "lb1"}


def test_export_all_signatures_skips_and_counts_failures(monkeypatch, capsys):
    """Regression guard: ThoughtSpotClient.post raises SystemExit (not a plain
    Exception) on a non-2xx response — the skip-and-count handler must catch
    both or one bad export aborts the whole `signatures` run."""
    from ts_cli.commands import aggregate as agg_mod

    def fake_export(client, guid):
        if guid == "bad":
            raise SystemExit(1)
        return {"answer": {"search_query": "[Category] [Sales]"}}

    monkeypatch.setattr(agg_mod, "_export_tml", fake_export)
    deps = [{"guid": "good", "name": "Good Answer"}, {"guid": "bad", "name": "Bad Answer"}]
    kinds = {"Category": "ATTRIBUTE", "Sales": "MEASURE"}
    sigs, failures = agg_mod._export_all_signatures(client=None, dependents=deps, kinds=kinds)
    assert failures == 1
    assert len(sigs) == 1
    assert sigs[0]["source_guid"] == "good"
    assert "bad" in capsys.readouterr().err


def test_signatures_command_offline(monkeypatch, tmp_path):
    """Full `ts aggregate signatures` wiring, with the client, dependents walk,
    and TML export all faked — no live ThoughtSpot connection."""
    from ts_cli.commands import aggregate as agg_mod
    import ts_cli.client as client_mod

    class FakeClient:
        def __init__(self, profile_name):
            pass

    monkeypatch.setattr(client_mod, "ThoughtSpotClient", FakeClient)
    monkeypatch.setattr(client_mod, "resolve_profile", lambda p: "test-profile")

    model_doc = {"model": {"name": "M", "columns": [
        {"name": "Sales", "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Category", "properties": {"column_type": "ATTRIBUTE"}},
    ]}}
    answer_doc = {"answer": {"search_query": "[Category] [Sales]"}}

    def fake_export_tml(client, guid):
        if guid == "model-guid":
            return model_doc
        if guid == "bad-answer":
            raise SystemExit(1)
        return answer_doc

    monkeypatch.setattr(agg_mod, "_export_tml", fake_export_tml)

    def fake_collect(client, guid, type="LOGICAL_TABLE"):
        return [
            {"guid": "ans-1", "name": "Answer 1", "type": "ANSWER", "owner": None},
            {"guid": "bad-answer", "name": "Bad Answer", "type": "ANSWER", "owner": None},
            {"guid": "sub-model", "name": "Sub Model", "type": "LOGICAL_TABLE", "owner": None},
        ]

    monkeypatch.setattr("ts_cli.commands.metadata._collect_dependents", fake_collect)

    # This run deliberately hits the export-failure stderr path (bad-answer) —
    # use a non-mixing runner so the diagnostic line doesn't land in stdout
    # and break the JSON parse below (ts-cli convention: JSON stdout, stderr
    # diagnostics only, never mixed).
    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "signatures", "--model", "model-guid",
                                          "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["model_guid"] == "model-guid"
    assert out["dependents"] == 2  # sub-model filtered out (LOGICAL_TABLE)
    assert out["export_failures"] == 1
    assert out["signatures"] == 1
    assert (tmp_path / "model.tml.yaml").exists()
    assert (tmp_path / "signatures.jsonl").exists()


def test_profile_emit_sql_manual_mode(tmp_path):
    model = {"model": {"name": "M", "model_tables": [{"name": "FACT"}], "columns": [
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "covered": [0], "flags": [], "agg_rows": None,
            "measure_columns": ["Sales"]}
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": None, "candidates": [cand], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT",
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"},
                               {"name": "CATEGORY", "db_column_name": "CATEGORY"}]}}))
    script = tmp_path / "profile.sql"
    result = runner.invoke(app, ["aggregate", "profile", "--dir", str(tmp_path),
                                 "--tables-dir", str(tdir),
                                 "--emit-sql", str(script)])
    assert result.exit_code == 0, result.output
    text = script.read_text()
    assert "-- __base__" in text and "-- cand_1" in text
    assert "GROUP BY" in text


def test_profile_results_ingestion(tmp_path):
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump({"model": {"columns": []}}))
    cand = {"id": "cand_1", "dimensions": [], "date_column": None, "bucket": None,
            "covered": [0], "flags": [], "agg_rows": None, "measure_columns": []}
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": None, "candidates": [cand], "selection": {}}))
    res = tmp_path / "res.json"
    res.write_text(json.dumps({"base_rows": 1000000, "candidates": {"cand_1": 86}}))
    tdir = tmp_path / "tables"; tdir.mkdir()
    result = runner.invoke(app, ["aggregate", "profile", "--dir", str(tmp_path),
                                 "--tables-dir", str(tdir), "--results", str(res)])
    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / "candidates.json").read_text())
    assert saved["base_rows"] == 1000000
    assert saved["candidates"][0]["agg_rows"] == 86


def test_profile_requires_a_mode(tmp_path):
    """No --results, --emit-sql, or --snowflake-profile: fail clearly instead
    of silently trying to connect with an empty profile name."""
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(
        {"model": {"columns": [], "model_tables": [{"name": "FACT"}]}}))
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": None, "candidates": [], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT", "columns": []}}))
    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "profile", "--dir", str(tmp_path),
                                          "--tables-dir", str(tdir)])
    assert result.exit_code == 1
    assert "snowflake-profile" in result.stderr or "snowflake-profile" in (result.output or "")


def test_profile_skips_unsupported_candidate(tmp_path):
    """A candidate whose SELECT can't be built deterministically (aliased
    model_tables prefix) is skipped with a reason, not fatal for the run."""
    model = {"model": {"name": "M", "model_tables": [{"name": "FACT"}], "columns": [
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Alias Dim", "column_id": "FACT_ALIAS::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    cand = {"id": "cand_1", "dimensions": ["Alias Dim"], "date_column": None,
            "bucket": None, "covered": [0], "flags": [], "agg_rows": None,
            "measure_columns": ["Sales"]}
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": None, "candidates": [cand], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT",
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"}]}}))
    script = tmp_path / "profile.sql"
    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "profile", "--dir", str(tmp_path),
                                          "--tables-dir", str(tdir), "--emit-sql", str(script)])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["skipped"] == [{"id": "cand_1", "reason":
                              "table 'FACT_ALIAS' not resolvable — possibly an aliased "
                              "model_tables entry"}]
    # base statement still emitted even though the only candidate was skipped
    assert "-- __base__" in script.read_text()


def test_profile_connected_mode_writes_agg_rows_and_base_rows(tmp_path, monkeypatch):
    """Connected mode (no --emit-sql/--results): resolves the Snowflake
    profile + connects via the real `ts_cli.commands.load` helpers
    (`load_snowflake_profile` + `_connect_python` — see `_snowflake_connection`'s
    docstring for why not `_connect_snowflake`, which doesn't exist), executes
    the base + candidate statements, and writes agg_rows/base_rows back into
    candidates.json."""
    import ts_cli.commands.load as load_mod

    model = {"model": {"name": "M", "model_tables": [{"name": "FACT"}], "columns": [
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "covered": [0], "flags": [], "agg_rows": None,
            "measure_columns": ["Sales"]}
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": None, "candidates": [cand], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT",
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"},
                               {"name": "CATEGORY", "db_column_name": "CATEGORY"}]}}))

    monkeypatch.setattr(load_mod, "load_snowflake_profile",
                        lambda name: {"name": name, "default_warehouse": "WH",
                                      "default_role": "ROLE"})

    class FakeCursor:
        def __init__(self, values):
            self._values = values
            self._i = -1

        def execute(self, sql, params=None):
            self._i += 1

        def fetchone(self):
            return (self._values[self._i],)

    class FakeConn:
        def __init__(self):
            self._cursor = FakeCursor([1000000, 86])  # base_rows, then cand_1

        def cursor(self):
            return self._cursor

    monkeypatch.setattr(load_mod, "_connect_python", lambda profile, wh, role: FakeConn())

    result = runner.invoke(app, ["aggregate", "profile", "--dir", str(tmp_path),
                                 "--tables-dir", str(tdir),
                                 "--snowflake-profile", "My SF Profile"])
    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / "candidates.json").read_text())
    assert saved["base_rows"] == 1000000
    assert saved["candidates"][0]["agg_rows"] == 86


def test_snowflake_connection_requires_warehouse(monkeypatch):
    """No --warehouse and no default_warehouse on the profile: fail clearly
    instead of connecting with an empty warehouse string."""
    import ts_cli.commands.aggregate as agg_mod
    import ts_cli.commands.load as load_mod

    monkeypatch.setattr(load_mod, "load_snowflake_profile",
                        lambda name: {"name": name})
    import pytest
    with pytest.raises(SystemExit, match="No warehouse specified"):
        agg_mod._snowflake_connection("My SF Profile", None, None)


def test_history_command_offline(tmp_path, monkeypatch):
    """`ts aggregate history` connects, mines QUERY_HISTORY, matches via the
    pure `match_history`, and writes weights.json — all offline via a
    monkeypatched connection."""
    import ts_cli.commands.load as load_mod

    model = {"model": {"columns": [
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    sig = {"source_guid": "g1", "viz_name": None, "dimensions": ["Category"],
           "date_column": None, "parse_status": "full"}
    (tmp_path / "signatures.jsonl").write_text(json.dumps(sig) + "\n")

    monkeypatch.setattr(load_mod, "load_snowflake_profile",
                        lambda name: {"name": name, "default_warehouse": "WH"})

    class FakeCursor:
        def execute(self, sql, params=None):
            pass

        def fetchall(self):
            return [("SELECT 1 FROM fact GROUP BY fact.category",)]

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(load_mod, "_connect_python", lambda profile, wh, role: FakeConn())

    result = runner.invoke(app, ["aggregate", "history", "--dir", str(tmp_path),
                                 "--snowflake-profile", "My SF Profile",
                                 "--tables", "FACT"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["history_rows"] == 1
    weights = json.loads((tmp_path / "weights.json").read_text())
    assert weights["g1::"] == 2.0  # base weight + 1 history match


def test_history_empty_tables_after_strip_errors_clearly(tmp_path, monkeypatch):
    """MINOR guard: --tables that collapses to nothing after strip filtering
    (e.g. ",  ,") must fail with a clear message, not build "AND ()" and hand
    Snowflake a syntax error."""
    import ts_cli.commands.load as load_mod

    model = {"model": {"columns": [
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    (tmp_path / "signatures.jsonl").write_text(json.dumps(
        {"source_guid": "g1", "viz_name": None, "dimensions": ["Category"],
         "date_column": None, "parse_status": "full"}) + "\n")
    monkeypatch.setattr(load_mod, "load_snowflake_profile",
                        lambda name: {"name": name, "default_warehouse": "WH"})

    class FakeConn:
        def cursor(self):
            raise AssertionError("should never reach the warehouse with empty --tables")

    monkeypatch.setattr(load_mod, "_connect_python", lambda profile, wh, role: FakeConn())

    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "history", "--dir", str(tmp_path),
                                          "--snowflake-profile", "My SF Profile",
                                          "--tables", ",  ,"])
    assert result.exit_code != 0
    assert "table name" in result.stderr.lower()


def test_profile_results_missing_key_errors_clearly(tmp_path):
    """MINOR guard: a --results JSON missing base_rows or candidates must fail
    with a message naming the missing key, not a bare KeyError traceback."""
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump({"model": {"columns": []}}))
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": None, "candidates": [], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    res = tmp_path / "res.json"
    res.write_text(json.dumps({"candidates": {"cand_1": 5}}))  # base_rows missing
    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "profile", "--dir", str(tmp_path),
                                          "--tables-dir", str(tdir), "--results", str(res)])
    assert result.exit_code != 0
    # A clean SystemExit with a helpful message — NOT a bare KeyError traceback.
    assert isinstance(result.exception, SystemExit)
    assert "base_rows" in str(result.exception)


def test_generate_writes_all_artifacts_and_never_imports(tmp_path, monkeypatch):
    """`ts aggregate generate` writes ddl.sql/table_spec.json/table.tml.yaml/
    agg_model.tml.yaml/primary_patched.tml.yaml and calls the TML *export*
    endpoint only — never metadata/tml/import."""
    import ts_cli.client as client_mod

    model = {"model": {"name": "Sales Model", "model_tables": [{"name": "FACT"}],
                       "columns": [
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "covered": [0], "flags": [], "agg_rows": 86,
            "measure_columns": ["Sales"]}
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": 1000000, "candidates": [cand], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT",
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"},
                               {"name": "CATEGORY", "db_column_name": "CATEGORY"}]}}))

    primary_edoc = yaml.safe_dump({"model": {"name": "Sales Model"}})

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, profile_name):
            self.calls = []

        def post(self, path, json=None):
            self.calls.append(path)
            assert "import" not in path  # generate must never import
            return FakeResponse([{"edoc": primary_edoc}])

    monkeypatch.setattr(client_mod, "ThoughtSpotClient", FakeClient)
    monkeypatch.setattr(client_mod, "resolve_profile", lambda p: "test-profile")

    result = runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                 "--candidate", "cand_1", "--model-guid", "model-guid",
                                 "--tables-dir", str(tdir), "--db", "SALESDB",
                                 "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                 "--warehouse", "WH"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    outdir = tmp_path / "cand_1"
    assert set(out["files"]) == {"ddl.sql", "table_spec.json", "table.tml.yaml",
                                 "agg_model.tml.yaml", "primary_patched.tml.yaml"}
    assert (outdir / "ddl.sql").exists()
    ddl = (outdir / "ddl.sql").read_text()
    assert "DYNAMIC TABLE" in ddl and "WAREHOUSE = WH" in ddl
    patched = yaml.safe_load((outdir / "primary_patched.tml.yaml").read_text())
    # aggregated_models entries key on the aggregate MODEL's display name
    # ("<primary name> (<agg table name>)"), not the raw table/candidate name.
    assert (patched["model"]["aggregated_models"][0]["id"]
            == f"Sales Model ({out['aggregate_name']})")


def test_generate_idempotent_multi_date_preserves_existing_and_new(tmp_path, monkeypatch):
    """Task 16: re-patching a primary that already has a single-date aggregate
    (A, in the REAL live-TML shape — date_aggregation_info, not date_grains/
    date_column) while generating a new multi-date aggregate (B, incl a
    NO_BUCKET raw grain) must preserve A's date_aggregation_info byte-for-byte
    (not silently strip it — the Task 16 bug) and emit B's full multi-date
    list, ordered most-aggregated-first. Running `generate` again against the
    same starting primary (generate never imports, so nothing on the server
    has changed) must produce byte-identical output — no drift, no
    duplication, no stripping."""
    import ts_cli.client as client_mod

    model = {"model": {"name": "Sales Model", "model_tables": [{"name": "FACT"}],
                       "columns": [
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Transaction Date", "column_id": "FACT::TXN_DT", "data_type": "DATE",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Shipped Date", "column_id": "FACT::SHIP_DT", "data_type": "DATE",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None, "bucket": None,
            "date_grains": [{"column": "Transaction Date", "bucket": "DAILY"},
                            {"column": "Shipped Date", "bucket": None}],
            "covered": [0], "flags": [], "agg_rows": 50, "measure_columns": ["Sales"]}
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": 1000000, "candidates": [cand], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT",
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"},
                               {"name": "CATEGORY", "db_column_name": "CATEGORY"},
                               {"name": "TXN_DT", "db_column_name": "TXN_DT"},
                               {"name": "SHIP_DT", "db_column_name": "SHIP_DT"}]}}))

    # The "live" primary already carries aggregate A as a real exported TML
    # entry would look — date_aggregation_info, never date_grains/date_column.
    primary_before = {"model": {"name": "Sales Model", "aggregated_models": [
        {"id": "Sales Model (A_AGG)",
         "date_aggregation_info": [{"column_id": "Order Date", "bucket": "MONTHLY"}]},
    ]}}
    primary_edoc = yaml.safe_dump(primary_before)

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, profile_name):
            pass

        def post(self, path, json=None):
            assert "import" not in path  # generate must never import
            return FakeResponse([{"edoc": primary_edoc}])

    monkeypatch.setattr(client_mod, "ThoughtSpotClient", FakeClient)
    monkeypatch.setattr(client_mod, "resolve_profile", lambda p: "test-profile")

    args = ["aggregate", "generate", "--dir", str(tmp_path),
            "--candidate", "cand_1", "--model-guid", "model-guid",
            "--tables-dir", str(tdir), "--db", "SALESDB",
            "--schema", "PUBLIC", "--connection-name", "SF Prod", "--warehouse", "WH"]

    result1 = runner.invoke(app, args)
    assert result1.exit_code == 0, result1.output
    outdir = tmp_path / "cand_1"
    patched1 = yaml.safe_load((outdir / "primary_patched.tml.yaml").read_text())
    aggs1 = patched1["model"]["aggregated_models"]
    assert len(aggs1) == 2
    by_id1 = {e["id"]: e for e in aggs1}

    # A's original single-date info survives byte-for-byte — not stripped.
    assert by_id1["Sales Model (A_AGG)"]["date_aggregation_info"] == \
        [{"column_id": "Order Date", "bucket": "MONTHLY"}]

    # B's full multi-date list, including the NO_BUCKET raw grain.
    out1 = json.loads(result1.stdout)
    b_name = f"Sales Model ({out1['aggregate_name']})"
    assert by_id1[b_name]["date_aggregation_info"] == [
        {"column_id": "Transaction Date", "bucket": "DAILY"},
        {"column_id": "Shipped Date", "bucket": "NO_BUCKET"},
    ]

    # Ordered most-aggregated-first: B has a known projected_rows (50); A's
    # existing entry carries no known row count (unprofiled) — known counts
    # sort before unknown ones.
    assert [e["id"] for e in aggs1] == [b_name, "Sales Model (A_AGG)"]

    # Re-run the same generate call again against the same starting primary
    # (generate never imports — nothing on the server has changed) — output
    # must be byte-identical: no drift, no duplication, no stripping.
    result2 = runner.invoke(app, args)
    assert result2.exit_code == 0, result2.output
    patched2 = yaml.safe_load((outdir / "primary_patched.tml.yaml").read_text())
    assert patched2 == patched1


def test_generate_regenerating_same_aggregate_produces_no_duplicate(tmp_path, monkeypatch):
    """Task 16 (idempotence): `_aggregate_name` is deterministic, so
    re-generating an already-imported aggregate produces the same model_name.
    The re-exported primary then already carries that entry — patch_association
    must NOT append a second entry with the same id. Exactly one entry
    survives, and it reflects the freshly generated grains (last wins), not the
    stale imported ones."""
    import ts_cli.client as client_mod

    model = {"model": {"name": "Sales Model", "model_tables": [{"name": "FACT"}],
                       "columns": [
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Transaction Date", "column_id": "FACT::TXN_DT", "data_type": "DATE",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None, "bucket": None,
            "date_grains": [{"column": "Transaction Date", "bucket": "DAILY"}],
            "covered": [0], "flags": [], "agg_rows": 50, "measure_columns": ["Sales"]}
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": 1000000, "candidates": [cand], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT",
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"},
                               {"name": "CATEGORY", "db_column_name": "CATEGORY"},
                               {"name": "TXN_DT", "db_column_name": "TXN_DT"}]}}))

    # Mutable exported-primary state so the second run can "see" the aggregate
    # as if it had been imported between runs.
    state = {"edoc": yaml.safe_dump({"model": {"name": "Sales Model",
                                               "aggregated_models": []}})}

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, profile_name):
            pass

        def post(self, path, json=None):
            assert "import" not in path
            return FakeResponse([{"edoc": state["edoc"]}])

    monkeypatch.setattr(client_mod, "ThoughtSpotClient", FakeClient)
    monkeypatch.setattr(client_mod, "resolve_profile", lambda p: "test-profile")

    args = ["aggregate", "generate", "--dir", str(tmp_path),
            "--candidate", "cand_1", "--model-guid", "model-guid",
            "--tables-dir", str(tdir), "--db", "SALESDB",
            "--schema", "PUBLIC", "--connection-name", "SF Prod", "--warehouse", "WH"]

    result1 = runner.invoke(app, args)
    assert result1.exit_code == 0, result1.output
    agg_id = f"Sales Model ({json.loads(result1.stdout)['aggregate_name']})"

    # Simulate the aggregate having been imported, with a STALE bucket, since
    # the last run — the re-exported primary now carries it.
    state["edoc"] = yaml.safe_dump({"model": {"name": "Sales Model",
                                              "aggregated_models": [
        {"id": agg_id, "date_aggregation_info": [
            {"column_id": "Transaction Date", "bucket": "MONTHLY"}]}]}})

    result2 = runner.invoke(app, args)
    assert result2.exit_code == 0, result2.output
    patched = yaml.safe_load(((tmp_path / "cand_1") / "primary_patched.tml.yaml").read_text())
    aggs = patched["model"]["aggregated_models"]
    assert [e["id"] for e in aggs].count(agg_id) == 1  # no duplicate
    entry = next(e for e in aggs if e["id"] == agg_id)
    # Fresh grains won (DAILY from cand), not the stale imported MONTHLY.
    assert entry["date_aggregation_info"] == [
        {"column_id": "Transaction Date", "bucket": "DAILY"}]


def test_generate_requires_warehouse_for_snowflake_dynamic_table(tmp_path):
    """Task 5 review carry-forward: a Snowflake dynamic table with no
    --warehouse must fail clearly rather than emit DDL missing the
    WAREHOUSE clause Snowflake requires at execution time."""
    model = {"model": {"name": "M", "model_tables": [{"name": "FACT"}], "columns": [
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "covered": [0], "flags": [], "agg_rows": None,
            "measure_columns": ["Sales"]}
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": None, "candidates": [cand], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT",
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"},
                               {"name": "CATEGORY", "db_column_name": "CATEGORY"}]}}))
    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                          "--candidate", "cand_1", "--model-guid", "model-guid",
                                          "--tables-dir", str(tdir), "--db", "SALESDB",
                                          "--schema", "PUBLIC", "--connection-name", "SF Prod"])
    assert result.exit_code != 0
    assert "--warehouse is required" in str(result.exception)


def test_generate_reports_unsupported_candidate_instead_of_crashing(tmp_path):
    """A candidate needing a manual-SQL fallback (aliased model_tables prefix
    sqlgen can't resolve) must exit cleanly with a diagnostic, not crash with
    an unhandled UnsupportedModelError traceback."""
    model = {"model": {"name": "M", "model_tables": [{"name": "FACT"}], "columns": [
        {"name": "Alias Dim", "column_id": "FACT_ALIAS::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    cand = {"id": "cand_1", "dimensions": ["Alias Dim"], "date_column": None,
            "bucket": None, "covered": [0], "flags": [], "agg_rows": None,
            "measure_columns": ["Sales"]}
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": None, "candidates": [cand], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT",
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"}]}}))
    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                          "--candidate", "cand_1", "--model-guid", "model-guid",
                                          "--tables-dir", str(tdir), "--db", "SALESDB",
                                          "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                          "--warehouse", "WH"])
    assert result.exit_code == 1
    assert "cannot generate SQL" in result.stderr


def test_generate_rejects_snowflake_materialized_view_cleanly(tmp_path):
    """Task 13 (c): --dialect snowflake --materialization mview must exit
    cleanly with the 002212 guidance, not crash with an unhandled
    UnsupportedModelError traceback."""
    model = {"model": {"name": "M", "model_tables": [{"name": "FACT"}], "columns": [
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "covered": [0], "flags": [], "agg_rows": None,
            "measure_columns": ["Sales"]}
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": None, "candidates": [cand], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT",
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"},
                               {"name": "CATEGORY", "db_column_name": "CATEGORY"}]}}))
    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                          "--candidate", "cand_1", "--model-guid", "model-guid",
                                          "--tables-dir", str(tdir), "--db", "SALESDB",
                                          "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                          "--dialect", "snowflake", "--materialization", "mview"])
    assert result.exit_code == 1
    assert "cannot generate DDL" in result.stderr
    assert "002212" in result.stderr
