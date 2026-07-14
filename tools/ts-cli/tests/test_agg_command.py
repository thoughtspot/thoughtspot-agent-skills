import json
import yaml
from typer.testing import CliRunner
from ts_cli.cli import app
from ts_cli.commands.aggregate import _candidate_key, _merge_prior_agg_rows, _signatures_summary

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


def test_candidate_key_distinguishes_single_vs_multi_date_grains():
    """Bug (final whole-branch review): `_candidate_key` used to key off the
    single-date `date_column`/`bucket` COMPAT SHIM fields only — a candidate's
    FIRST date grain — never the full `date_grains` list. Two distinct
    candidates that share dimensions and the same first grain (one single-date,
    one multi-date) therefore hashed identically, and `_merge_prior_agg_rows`
    (below) could cross-assign a profiled `agg_rows` between them."""
    single = {"id": "cand_1", "dimensions": ["Category"], "date_column": "Order Date",
              "bucket": "MONTHLY",
              "date_grains": [{"column": "Order Date", "bucket": "MONTHLY"}]}
    multi = {"id": "cand_2", "dimensions": ["Category"], "date_column": "Order Date",
             "bucket": "MONTHLY",
             "date_grains": [{"column": "Order Date", "bucket": "MONTHLY"},
                             {"column": "Ship Date", "bucket": "MONTHLY"}]}
    assert _candidate_key(single) != _candidate_key(multi)


def test_candidate_key_stable_regardless_of_date_grains_order():
    """The key must not depend on `date_grains` list order — candidates.json
    round-trips through JSON (which preserves list order), but the key should
    still treat two grains lists with the same members in different orders as
    the same candidate identity."""
    a = {"id": "cand_1", "dimensions": ["Category"],
         "date_grains": [{"column": "Order Date", "bucket": "MONTHLY"},
                         {"column": "Ship Date", "bucket": "MONTHLY"}]}
    b = {"id": "cand_2", "dimensions": ["Category"],
         "date_grains": [{"column": "Ship Date", "bucket": "MONTHLY"},
                         {"column": "Order Date", "bucket": "MONTHLY"}]}
    assert _candidate_key(a) == _candidate_key(b)


def test_merge_prior_agg_rows_does_not_cross_assign_single_vs_multi_date(tmp_path):
    """Reproduces the bug end-to-end through `_merge_prior_agg_rows`: a prior
    `profile` run measured only the multi-date candidate. Re-running `recommend`
    must not leak that row count onto a different, single-date candidate that
    merely shares dimensions and the same first grain."""
    single = {"id": "cand_1", "dimensions": ["Category"], "date_column": "Order Date",
              "bucket": "MONTHLY",
              "date_grains": [{"column": "Order Date", "bucket": "MONTHLY"}],
              "agg_rows": None}
    multi = {"id": "cand_2", "dimensions": ["Category"], "date_column": "Order Date",
             "bucket": "MONTHLY",
             "date_grains": [{"column": "Order Date", "bucket": "MONTHLY"},
                             {"column": "Ship Date", "bucket": "MONTHLY"}],
             "agg_rows": None}
    prior_payload = {
        "base_rows": 1000,
        "candidates": [
            {"id": "cand_2_old", "dimensions": ["Category"], "date_column": "Order Date",
             "bucket": "MONTHLY",
             "date_grains": [{"column": "Order Date", "bucket": "MONTHLY"},
                             {"column": "Ship Date", "bucket": "MONTHLY"}],
             "agg_rows": 500},
        ],
    }
    prior_path = tmp_path / "candidates.json"
    prior_path.write_text(json.dumps(prior_payload))

    _merge_prior_agg_rows([single, multi], prior_path, base_rows=None)

    assert single["agg_rows"] is None, "single-date candidate must not inherit the multi-date row count"
    assert multi["agg_rows"] == 500


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
                                 "--warehouse", "WH", "--agg-model-guid", "agg-guid-1",
                                 "--no-spotql"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    outdir = tmp_path / "cand_1"
    assert set(out["files"]) == {"ddl.sql", "table_spec.json", "table.tml.yaml",
                                 "agg_model.tml.yaml", "primary_patched.tml.yaml"}
    assert (outdir / "ddl.sql").exists()
    ddl = (outdir / "ddl.sql").read_text()
    assert "DYNAMIC TABLE" in ddl and "WAREHOUSE = WH" in ddl
    patched = yaml.safe_load((outdir / "primary_patched.tml.yaml").read_text())
    # Task 17 Part B: aggregated_models entries key on the aggregate MODEL's
    # GUID (--agg-model-guid), not its display name — the aggregate model and
    # its backing table share a name, so name is ambiguous
    # (DUPLICATE_OBJECT_FOUND on a live cluster).
    assert patched["model"]["aggregated_models"][0]["id"] == "agg-guid-1"


def test_generate_falls_back_to_name_id_with_warning_when_no_agg_model_guid(
        tmp_path, monkeypatch):
    """Task 17 Part B: omitting --agg-model-guid must still work (backward
    compatible) but must warn on stderr that the name-based id can collide
    with the equally-named backing table."""
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
            pass

        def post(self, path, json=None):
            return FakeResponse([{"edoc": primary_edoc}])

    monkeypatch.setattr(client_mod, "ThoughtSpotClient", FakeClient)
    monkeypatch.setattr(client_mod, "resolve_profile", lambda p: "test-profile")

    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                          "--candidate", "cand_1", "--model-guid", "model-guid",
                                          "--tables-dir", str(tdir), "--db", "SALESDB",
                                          "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                          "--warehouse", "WH", "--no-spotql"])
    assert result.exit_code == 0, result.output
    assert "--agg-model-guid" in result.stderr
    assert "ambiguous" in result.stderr or "collide" in result.stderr
    out = json.loads(result.stdout)
    outdir = tmp_path / "cand_1"
    patched = yaml.safe_load((outdir / "primary_patched.tml.yaml").read_text())
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
            "--schema", "PUBLIC", "--connection-name", "SF Prod", "--warehouse", "WH",
            "--agg-model-guid", "b-guid-1", "--no-spotql"]

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

    # B's full multi-date list, including the NO_BUCKET raw grain. B's id is
    # the passed --agg-model-guid (Task 17 Part B), not the ambiguous name.
    b_name = "b-guid-1"
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
            "--schema", "PUBLIC", "--connection-name", "SF Prod", "--warehouse", "WH",
            "--agg-model-guid", "stable-guid-1", "--no-spotql"]

    result1 = runner.invoke(app, args)
    assert result1.exit_code == 0, result1.output
    # Task 17 Part B: id is the passed --agg-model-guid, stable across runs
    # (as it would be in the real flow — the aggregate model's GUID doesn't
    # change between generate calls).
    agg_id = "stable-guid-1"

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


def test_aggregate_name_sanitizes_multiword_dimension_to_valid_identifier():
    """Live-testing bug: `ts aggregate generate` emitted an aggregate name with
    a literal space — `DM_CATEGORY_AGG_MONTHLY_PRODUCT CATEGORY` — because a
    multi-word dimension name ("Product Category") was uppercased and
    concatenated without sanitizing the space first. An unquoted SQL
    identifier containing a space breaks `CREATE TABLE`. The derived name
    must contain only [A-Z0-9_] characters, with runs of anything else
    (spaces, punctuation) collapsed to a single underscore."""
    import re
    from ts_cli.commands import aggregate as agg_mod

    model_tml = {"model": {"model_tables": [{"name": "DM_CATEGORY"}]}}
    cand = {"bucket": "MONTHLY", "dimensions": ["Product Category"]}
    name = agg_mod._aggregate_name(model_tml, cand, None)
    assert " " not in name
    assert re.fullmatch(r"[A-Z0-9_]+", name), name
    assert name == "DM_CATEGORY_AGG_MONTHLY_PRODUCT_CATEGORY"


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
                                          "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                          "--no-spotql"])
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
                                          "--warehouse", "WH", "--no-spotql"])
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
                                          "--dialect", "snowflake", "--materialization", "mview",
                                          "--no-spotql"])
    assert result.exit_code == 1
    assert "cannot generate DDL" in result.stderr
    assert "002212" in result.stderr


# --- Task 18: SpotQL-first DDL generation, sqlgen as fallback ---------------

_SPOTQL_MODEL = {"model": {"name": "Sales Model", "model_tables": [{"name": "FACT"}],
                           "columns": [
    {"name": "Category", "column_id": "FACT::CATEGORY",
     "properties": {"column_type": "ATTRIBUTE"}},
    {"name": "Sales", "column_id": "FACT::AMOUNT",
     "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}]}}
_SPOTQL_CAND = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
               "bucket": None, "covered": [0], "flags": [], "agg_rows": 86,
               "measure_columns": ["Sales"]}
# Positional ca_N matches build_spotql's output_aliases for _SPOTQL_CAND:
# ["Category", "sales_sum"].
_SPOTQL_TS_SQL = (
    'SELECT "ta_1"."CATEGORY_NAME" AS "ca_1", SUM("ta_1"."AMOUNT") AS "ca_2" '
    'FROM "SALESDB"."PUBLIC"."FACT_SALES" "ta_1" GROUP BY "ca_1" LIMIT 100000'
)


def _write_spotql_fixture(tmp_path):
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(_SPOTQL_MODEL))
    (tmp_path / "candidates.json").write_text(json.dumps(
        {"base_rows": 1000000, "candidates": [_SPOTQL_CAND], "selection": {}}))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT",
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"},
                               {"name": "CATEGORY", "db_column_name": "CATEGORY"}]}}))
    return tdir


def _patch_primary_export(monkeypatch):
    """Fake the primary Model export (`_patch_and_write_primary`'s
    `_export_tml`), independent of the SpotQL `_run` monkeypatch below —
    `generate` always re-exports the primary regardless of which DDL path
    was used."""
    import ts_cli.client as client_mod

    primary_edoc = yaml.safe_dump({"model": {"name": "Sales Model"}})

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
            return FakeResponse([{"edoc": primary_edoc}])

    monkeypatch.setattr(client_mod, "ThoughtSpotClient", FakeClient)
    monkeypatch.setattr(client_mod, "resolve_profile", lambda p: "test-profile")


def test_generate_default_path_uses_spotql_and_wraps_ts_sql(tmp_path, monkeypatch):
    """Default behaviour (no --no-spotql): `generate` builds SpotQL for the
    candidate's grain, calls the existing `ts spotql generate-sql` client
    path (monkeypatched here, never a real network call), and wraps the
    returned join-correct `executable_sql` as DDL — never touching
    sqlgen.build_select's hand-rolled join walker."""
    tdir = _write_spotql_fixture(tmp_path)
    _patch_primary_export(monkeypatch)

    calls = []

    def fake_run(path, spotql, model, profile):
        calls.append((path, spotql, model, profile))
        return {"status": "SUCCESS", "executable_sql": _SPOTQL_TS_SQL,
                "errors": [], "columns": [], "rows": []}

    monkeypatch.setattr("ts_cli.commands.spotql._run", fake_run)

    result = runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                 "--candidate", "cand_1", "--model-guid", "model-guid",
                                 "--tables-dir", str(tdir), "--db", "SALESDB",
                                 "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                 "--warehouse", "WH", "--agg-model-guid", "agg-guid-1",
                                 "--profile", "my-ts-profile"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0][2] == "model-guid"
    assert calls[0][3] == "my-ts-profile"

    ddl = (tmp_path / "cand_1" / "ddl.sql").read_text()
    assert "LIMIT" not in ddl
    assert '"ca_1" AS "Category"' in ddl
    assert '"ca_2" AS "sales_sum"' in ddl
    assert ddl.startswith("CREATE OR REPLACE DYNAMIC TABLE")
    assert "WAREHOUSE = WH" in ddl
    assert 'FROM (\n' in ddl and ') "src"' in ddl
    # Never routed through the hand-rolled join walker's physical resolution.
    assert "FACT_SALES" not in ddl or '"ta_1"' in ddl  # only via the wrapped ts_sql


def test_generate_falls_back_to_sqlgen_when_spotql_status_not_success(tmp_path, monkeypatch):
    """SpotQL generate-sql returning a non-SUCCESS status (e.g. a rejected
    statement) must fall back to sqlgen.build_select, with a stderr note that
    role-playing/ambiguous-path dimensions may be wrong on that fallback."""
    tdir = _write_spotql_fixture(tmp_path)
    _patch_primary_export(monkeypatch)

    def fake_run(path, spotql, model, profile):
        return {"status": "COLUMN_NOT_FOUND", "executable_sql": "",
                "errors": [{"code": "COLUMN_NOT_FOUND", "message": "nope"}],
                "columns": [], "rows": []}

    monkeypatch.setattr("ts_cli.commands.spotql._run", fake_run)

    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                          "--candidate", "cand_1", "--model-guid", "model-guid",
                                          "--tables-dir", str(tdir), "--db", "SALESDB",
                                          "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                          "--warehouse", "WH", "--agg-model-guid", "agg-guid-1"])
    assert result.exit_code == 0, result.output
    assert "falling back" in result.stderr.lower()
    assert "role-playing" in result.stderr.lower()

    ddl = (tmp_path / "cand_1" / "ddl.sql").read_text()
    # sqlgen.build_select's physical-column-resolution shape, not the SpotQL wrap.
    assert 'SUM("FACT"."AMOUNT") AS "sales_sum"' in ddl
    assert '"src"' not in ddl


def test_generate_falls_back_to_sqlgen_when_spotql_run_raises(tmp_path, monkeypatch):
    """An exception from the SpotQL client path (e.g. no ThoughtSpot profile
    configured, network error) must not crash `generate` — it falls back to
    sqlgen.build_select just like a rejected statement."""
    tdir = _write_spotql_fixture(tmp_path)
    _patch_primary_export(monkeypatch)

    def fake_run(path, spotql, model, profile):
        raise SystemExit("no profile configured")

    monkeypatch.setattr("ts_cli.commands.spotql._run", fake_run)

    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                          "--candidate", "cand_1", "--model-guid", "model-guid",
                                          "--tables-dir", str(tdir), "--db", "SALESDB",
                                          "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                          "--warehouse", "WH", "--agg-model-guid", "agg-guid-1"])
    assert result.exit_code == 0, result.output
    assert "falling back" in result.stderr.lower()
    ddl = (tmp_path / "cand_1" / "ddl.sql").read_text()
    assert 'SUM("FACT"."AMOUNT") AS "sales_sum"' in ddl


def test_generate_no_spotql_flag_never_calls_spotql_run(tmp_path, monkeypatch):
    """--no-spotql skips the SpotQL attempt entirely — the built-in join
    walker is used directly, matching pre-Task-18 behaviour."""
    tdir = _write_spotql_fixture(tmp_path)
    _patch_primary_export(monkeypatch)

    def fake_run(path, spotql, model, profile):
        raise AssertionError("SpotQL must not be attempted with --no-spotql")

    monkeypatch.setattr("ts_cli.commands.spotql._run", fake_run)

    result = runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                 "--candidate", "cand_1", "--model-guid", "model-guid",
                                 "--tables-dir", str(tdir), "--db", "SALESDB",
                                 "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                 "--warehouse", "WH", "--agg-model-guid", "agg-guid-1",
                                 "--no-spotql"])
    assert result.exit_code == 0, result.output
    ddl = (tmp_path / "cand_1" / "ddl.sql").read_text()
    assert 'SUM("FACT"."AMOUNT") AS "sales_sum"' in ddl


def test_profile_spotql_path_used_when_model_guid_given(tmp_path, monkeypatch):
    """`ts aggregate profile --model-guid ... --profile ...` builds SpotQL per
    candidate and wraps the returned executable_sql as
    `SELECT COUNT(*) FROM (<ts_sql_no_limit>) _agg` for the compression count."""
    tdir = _write_spotql_fixture(tmp_path)

    def fake_run(path, spotql, model, profile):
        return {"status": "SUCCESS", "executable_sql": _SPOTQL_TS_SQL,
                "errors": [], "columns": [], "rows": []}

    monkeypatch.setattr("ts_cli.commands.spotql._run", fake_run)

    script = tmp_path / "profile.sql"
    result = runner.invoke(app, ["aggregate", "profile", "--dir", str(tmp_path),
                                 "--tables-dir", str(tdir), "--emit-sql", str(script),
                                 "--model-guid", "model-guid", "--profile", "my-ts-profile"])
    assert result.exit_code == 0, result.output
    text = script.read_text()
    assert "-- __base__" in text and "-- cand_1" in text
    assert 'SUM("ta_1"."AMOUNT") AS "ca_2"' in text
    assert "LIMIT" not in text.split("-- cand_1", 1)[1]


def test_profile_spotql_falls_back_to_sqlgen_on_failure(tmp_path, monkeypatch):
    tdir = _write_spotql_fixture(tmp_path)

    def fake_run(path, spotql, model, profile):
        return {"status": "QUERY_GEN_ERROR", "executable_sql": "", "errors": [],
                "columns": [], "rows": []}

    monkeypatch.setattr("ts_cli.commands.spotql._run", fake_run)

    script = tmp_path / "profile.sql"
    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "profile", "--dir", str(tmp_path),
                                          "--tables-dir", str(tdir), "--emit-sql", str(script),
                                          "--model-guid", "model-guid"])
    assert result.exit_code == 0, result.output
    assert "falling back" in result.stderr.lower()
    text = script.read_text()
    assert "GROUP BY" in text.split("-- cand_1", 1)[1]


def test_profile_without_model_guid_never_calls_spotql(tmp_path, monkeypatch):
    """Backward compatibility: omitting --model-guid (every pre-Task-18 caller)
    must never attempt the SpotQL path at all."""
    tdir = _write_spotql_fixture(tmp_path)

    def fake_run(path, spotql, model, profile):
        raise AssertionError("SpotQL must not be attempted without --model-guid")

    monkeypatch.setattr("ts_cli.commands.spotql._run", fake_run)

    script = tmp_path / "profile.sql"
    result = runner.invoke(app, ["aggregate", "profile", "--dir", str(tmp_path),
                                 "--tables-dir", str(tdir), "--emit-sql", str(script)])
    assert result.exit_code == 0, result.output
    assert "GROUP BY" in script.read_text()


# --- Task 23: wire RLS propagation into recommend/generate --------------------

def test_recommend_attaches_rls_conflict_and_summary(tmp_path):
    """Part A: when a base table (from the default `<dir>/tables`) carries
    `rls_rules` and a candidate's grain omits the filter column, `recommend`
    attaches `rls: {required, missing}` + `rls_conflict: true` to that
    candidate in candidates.json, and lists its id in the stdout summary's
    `rls_conflicts`."""
    model = {"model": {"name": "M", "columns": [
        {"name": "Sales", "column_id": "F::A",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Category", "column_id": "F::C",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Region", "column_id": "F::R",
         "properties": {"column_type": "ATTRIBUTE"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    sig = {"source_guid": "g", "source_name": "s", "source_type": "ANSWER",
           "viz_name": None, "dimensions": ["Category"], "date_column": None,
           "date_bucket": None, "measures": ["Sales"], "filter_columns": [],
           "parse_status": "full", "weight": 1.0}
    (tmp_path / "signatures.jsonl").write_text(json.dumps(sig) + "\n")
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "F.tml.yaml").write_text(yaml.safe_dump({
        "table": {"name": "F", "rls_rules": {
            "table_paths": [{"id": "T_1", "table": "F", "column": ["R"]}],
            "rules": [{"name": "region_rule", "expr": "[T_1::R] = ts_groups"}],
        }}}))

    result = runner.invoke(app, ["aggregate", "recommend", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    saved = json.loads((tmp_path / "candidates.json").read_text())
    cand = next(c for c in saved["candidates"] if c["dimensions"] == ["Category"])
    assert cand["rls"] == {"required": ["Region"], "missing": ["Region"]}
    assert cand["rls_conflict"] is True
    assert cand["id"] in out["rls_conflicts"]


def test_recommend_no_conflict_when_grain_covers_rls_column(tmp_path):
    """Part A: a candidate whose grain already covers the RLS filter column
    gets `rls_conflict: false` and is absent from `rls_conflicts`."""
    model = {"model": {"name": "M", "columns": [
        {"name": "Sales", "column_id": "F::A",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Category", "column_id": "F::C",
         "properties": {"column_type": "ATTRIBUTE"}}]}}
    (tmp_path / "model.tml.yaml").write_text(yaml.safe_dump(model))
    sig = {"source_guid": "g", "source_name": "s", "source_type": "ANSWER",
           "viz_name": None, "dimensions": ["Category"], "date_column": None,
           "date_bucket": None, "measures": ["Sales"], "filter_columns": [],
           "parse_status": "full", "weight": 1.0}
    (tmp_path / "signatures.jsonl").write_text(json.dumps(sig) + "\n")
    tdir = tmp_path / "tables"
    tdir.mkdir()
    (tdir / "F.tml.yaml").write_text(yaml.safe_dump({
        "table": {"name": "F", "rls_rules": {
            "table_paths": [{"id": "T_1", "table": "F", "column": ["C"]}],
            "rules": [{"name": "cat_rule", "expr": "[T_1::C] = ts_groups"}],
        }}}))

    result = runner.invoke(app, ["aggregate", "recommend", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    saved = json.loads((tmp_path / "candidates.json").read_text())
    cand = next(c for c in saved["candidates"] if c["dimensions"] == ["Category"])
    assert cand["rls"] == {"required": ["Category"], "missing": []}
    assert cand["rls_conflict"] is False
    assert out["rls_conflicts"] == []


def test_recommend_rls_no_op_without_base_rls(tmp_path):
    """No base table RLS at all (no `--tables-dir` given and no `<dir>/tables`
    on disk either) is a complete no-op: candidates.json carries no `rls`/
    `rls_conflict` keys and the summary's `rls_conflicts` is empty — no
    behavior change for a Model without RLS."""
    model = {"model": {"name": "M", "columns": [
        {"name": "Sales", "column_id": "F::A",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Category", "column_id": "F::C",
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
    assert out["rls_conflicts"] == []
    saved = json.loads((tmp_path / "candidates.json").read_text())
    assert "rls" not in saved["candidates"][0]
    assert "rls_conflict" not in saved["candidates"][0]


def test_build_filter_to_aggcol_resolves_display_name():
    """Part B helper: `_build_filter_to_aggcol` resolves an RLS filter's
    `(base_table, physical_col)` to the model's DISPLAY name via `column_id`
    — the same string `build_aggregate_table_spec` stores the grain column
    under, so no further lookup against the table spec is needed."""
    from ts_cli.aggregate.rls import extract_rls
    from ts_cli.commands.aggregate_rls import _build_filter_to_aggcol

    model_tml = {"model": {"columns": [
        {"name": "Customer Zipcode", "column_id": "Source Table::ZIPCODE",
         "properties": {"column_type": "ATTRIBUTE"}}]}}
    table_tml = {"table": {"name": "Source Table", "rls_rules": {
        "table_paths": [{"id": "T_1", "table": "Source Table", "column": ["ZIPCODE"]}],
        "rules": [{"name": "geo_rule", "expr": "[T_1::ZIPCODE] = ts_groups_int"}],
    }}}
    rules = extract_rls({"Source Table": table_tml})
    mapping = _build_filter_to_aggcol(rules, model_tml)
    assert mapping == {("Source Table", "ZIPCODE"): "Customer Zipcode"}


def test_build_filter_to_aggcol_skips_unmodeled_column():
    """An RLS filter column the model doesn't expose at all can't resolve to
    a display name — `_build_filter_to_aggcol` must skip it (never emit a
    bogus mapping), relying on the fail-closed guard upstream to have already
    refused to reach this point for a candidate that needed it."""
    from ts_cli.aggregate.rls import extract_rls
    from ts_cli.commands.aggregate_rls import _build_filter_to_aggcol

    model_tml = {"model": {"columns": []}}
    table_tml = {"table": {"name": "Source Table", "rls_rules": {
        "table_paths": [{"id": "T_1", "table": "Source Table", "column": ["SECRET"]}],
        "rules": [{"name": "r", "expr": "[T_1::SECRET] = ts_groups"}],
    }}}
    rules = extract_rls({"Source Table": table_tml})
    mapping = _build_filter_to_aggcol(rules, model_tml)
    assert mapping == {}


def test_generate_fails_closed_when_grain_omits_rls_column(tmp_path):
    """Part B: a candidate whose grain omits a required RLS filter column
    must fail closed (exit 1, NOTHING written to the output directory)
    rather than emit an unsecured aggregate table. No client mock needed —
    the guard runs before any network call."""
    model = {"model": {"name": "Sales Model", "model_tables": [{"name": "FACT"}],
                       "columns": [
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Region", "column_id": "FACT::REGION",
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
                   "rls_rules": {
                       "table_paths": [{"id": "T_1", "table": "FACT", "column": ["REGION"]}],
                       "rules": [{"name": "region_rule", "expr": "[T_1::REGION] = ts_groups"}],
                   },
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"},
                               {"name": "CATEGORY", "db_column_name": "CATEGORY"},
                               {"name": "REGION", "db_column_name": "REGION"}]}}))
    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                          "--candidate", "cand_1", "--model-guid", "model-guid",
                                          "--tables-dir", str(tdir), "--db", "SALESDB",
                                          "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                          "--warehouse", "WH", "--no-spotql"])
    assert result.exit_code == 1
    assert "Region" in result.stderr
    assert "row-level security" in result.stderr
    outdir = tmp_path / "cand_1"
    assert list(outdir.iterdir()) == []  # fail closed — zero side effects


def test_generate_propagates_rls_onto_aggregate_table(tmp_path, monkeypatch):
    """Part B: when the candidate's grain covers every RLS filter column,
    `generate` propagates the base rule(s) onto both `table_spec.json` and
    `table.tml.yaml`, remapped to the aggregate's own (display-name) grain
    column and a new `<agg_name>_1` path id."""
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
                   "rls_rules": {
                       "table_paths": [{"id": "T_1", "table": "FACT", "column": ["CATEGORY"]}],
                       "rules": [{"name": "cat_rule", "expr": "[T_1::CATEGORY] = ts_groups"}],
                   },
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
            pass

        def post(self, path, json=None):
            assert "import" not in path
            return FakeResponse([{"edoc": primary_edoc}])

    monkeypatch.setattr(client_mod, "ThoughtSpotClient", FakeClient)
    monkeypatch.setattr(client_mod, "resolve_profile", lambda p: "test-profile")

    result = runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                 "--candidate", "cand_1", "--model-guid", "model-guid",
                                 "--tables-dir", str(tdir), "--db", "SALESDB",
                                 "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                 "--warehouse", "WH", "--agg-model-guid", "agg-guid-1",
                                 "--no-spotql"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    agg_name = out["aggregate_name"]

    table_tml = yaml.safe_load((tmp_path / "cand_1" / "table.tml.yaml").read_text())
    rls = table_tml["table"]["rls_rules"]
    assert rls["table_paths"] == [
        {"id": f"{agg_name}_1", "table": agg_name, "column": ["Category"]}]
    assert rls["rules"] == [
        {"name": "cat_rule", "expr": f"[{agg_name}_1::Category] = ts_groups"}]

    spec = json.loads((tmp_path / "cand_1" / "table_spec.json").read_text())
    assert spec["rls_rules"] == rls


def test_generate_no_op_when_no_base_rls(tmp_path, monkeypatch):
    """No base table RLS at all: `table.tml.yaml`/`table_spec.json` carry no
    `rls_rules` key at all — byte-identical to pre-Task-23 behavior."""
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
            pass

        def post(self, path, json=None):
            return FakeResponse([{"edoc": primary_edoc}])

    monkeypatch.setattr(client_mod, "ThoughtSpotClient", FakeClient)
    monkeypatch.setattr(client_mod, "resolve_profile", lambda p: "test-profile")

    result = runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                 "--candidate", "cand_1", "--model-guid", "model-guid",
                                 "--tables-dir", str(tdir), "--db", "SALESDB",
                                 "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                 "--warehouse", "WH", "--agg-model-guid", "agg-guid-1",
                                 "--no-spotql"])
    assert result.exit_code == 0, result.output
    table_tml = yaml.safe_load((tmp_path / "cand_1" / "table.tml.yaml").read_text())
    assert "rls_rules" not in table_tml["table"]
    spec = json.loads((tmp_path / "cand_1" / "table_spec.json").read_text())
    assert "rls_rules" not in spec


def test_generate_fails_closed_when_tables_dir_empty(tmp_path):
    """Task 23 review fix (security, fail-OPEN on bad input): the RLS guard is
    only as strong as `--tables-dir`. An EMPTY tables-dir would make
    `extract_rls` return `[]`, silently skip propagation, and emit an
    UNSECURED aggregate. For a security control this must fail CLOSED —
    exit 1, no files written — because the base tables it would need to assess
    RLS were never loaded."""
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
    tdir.mkdir()  # deliberately empty — no Table TMLs exported

    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                          "--candidate", "cand_1", "--model-guid", "model-guid",
                                          "--tables-dir", str(tdir), "--db", "SALESDB",
                                          "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                          "--warehouse", "WH", "--no-spotql"])
    assert result.exit_code == 1
    assert "row-level security" in result.stderr
    outdir = tmp_path / "cand_1"
    assert list(outdir.iterdir()) == []  # fail closed — zero side effects


def test_generate_fails_closed_when_tables_dir_incomplete(tmp_path):
    """Same fail-closed input guard, but for an INCOMPLETE tables-dir: the
    Model has two base tables (FACT, DIM) but only FACT's TML was exported.
    RLS on the un-loaded DIM would be invisible, so `generate` must fail
    closed and name the missing table rather than emit a possibly-unsecured
    aggregate."""
    model = {"model": {"name": "Sales Model",
                       "model_tables": [{"name": "FACT"}, {"name": "DIM"}],
                       "columns": [
        {"name": "Category", "column_id": "DIM::CATEGORY",
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
    # Only FACT exported — DIM (an RLS-bearing base table) is missing.
    (tdir / "FACT.tml.yaml").write_text(yaml.safe_dump(
        {"table": {"db": "DB", "schema": "S", "db_table": "FACT",
                   "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"}]}}))

    isolated_runner = CliRunner(mix_stderr=False)
    result = isolated_runner.invoke(app, ["aggregate", "generate", "--dir", str(tmp_path),
                                          "--candidate", "cand_1", "--model-guid", "model-guid",
                                          "--tables-dir", str(tdir), "--db", "SALESDB",
                                          "--schema", "PUBLIC", "--connection-name", "SF Prod",
                                          "--warehouse", "WH", "--no-spotql"])
    assert result.exit_code == 1
    assert "DIM" in result.stderr
    outdir = tmp_path / "cand_1"
    assert list(outdir.iterdir()) == []  # fail closed — zero side effects


def test_load_tables_dir_matches_yml_and_json(tmp_path):
    """Task 23 review fix: `_load_tables_dir`'s glob broadened beyond `*.yaml`
    (which already covers Step 3's `.tml.yaml` exports) to also pick up
    `.yml`/`.json` — so an export written in a sibling format is loaded rather
    than silently ignored (which would be a fail-open for the RLS guard)."""
    from ts_cli.commands.aggregate import _load_tables_dir

    (tmp_path / "FACT.tml.yaml").write_text(yaml.safe_dump({"table": {"name": "FACT"}}))
    (tmp_path / "DIM.yml").write_text(yaml.safe_dump({"table": {"name": "DIM"}}))
    (tmp_path / "GEO.json").write_text(json.dumps({"table": {"name": "GEO"}}))
    loaded = _load_tables_dir(str(tmp_path))
    assert set(loaded) == {"FACT", "DIM", "GEO"}
