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


def test_profile_generate_history_are_stubs():
    for sub in ("profile", "generate", "history"):
        result = runner.invoke(app, ["aggregate", sub])
        assert result.exit_code == 2
