"""`ts audit run` resolves its own scope: all Models, optionally narrowed to connections.

The rules here used to be skill prose the LLM carried out by hand (ts-audit Step 3): tell a
Model from a legacy Worksheet, and keep the Models on the chosen connections. A Model's
search result rarely names a connection, so connection scope goes through its Tables.
"""
import pytest

from ts_cli.audit import scope


def _row(guid, name, version="V2", source=None):
    header = {"id": guid, "name": name}
    if version:
        header["worksheetVersion"] = version
    if source is not None:
        header["dataSourceName"] = source
    return {"metadata_id": guid, "metadata_name": name, "metadata_header": header}


def test_select_models_keeps_v2_and_counts_legacy_worksheets():
    models, legacy = scope.select_models([
        _row("m1", "Sales"), _row("w1", "Old sheet", version=None), _row("m2", "Ops")])
    assert [m["guid"] for m in models] == ["m1", "m2"]
    assert models[0] == {"guid": "m1", "name": "Sales"}
    assert legacy == 1


def test_tables_on_connections_matches_case_insensitively():
    rows = [_row("t1", "FACT", None, "Snowflake Prod"), _row("t2", "DIM", None, "snowflake PROD "),
            _row("t3", "OTHER", None, "BigQuery"), _row("t4", "NOSRC", None)]
    assert scope.tables_on_connections(rows, ["SNOWFLAKE prod"]) == ["t1", "t2"]
    assert scope.tables_on_connections(rows, ["bigquery", "snowflake prod"]) == ["t1", "t2", "t3"]


def _graph(edges):
    """dependents_of over a fixed {source: [dependent, ...]} map, recording each batch."""
    calls = []

    def dependents_of(guids):
        calls.append(sorted(guids))
        return {g: edges.get(g, []) for g in guids}
    return dependents_of, calls


def test_models_reached_directly_and_through_views():
    # FACT -> M1 (Model); FACT -> V1 (View) -> M2; DIM -> M1 again
    dependents_of, calls = _graph({"FACT": ["M1", "V1"], "DIM": ["M1"], "V1": ["M2"]})
    reached = scope.models_reached(["FACT", "DIM"], dependents_of, {"M1", "M2", "M3"})
    assert reached == {"M1", "M2"}
    assert calls == [["DIM", "FACT"], ["V1"]]  # batched per level; Models are not followed


def test_models_reached_stops_on_a_view_cycle():
    dependents_of, _ = _graph({"T": ["V1"], "V1": ["V2"], "V2": ["V1", "M"]})
    assert scope.models_reached(["T"], dependents_of, {"M"}) == {"M"}


def test_models_reached_respects_the_depth_cap():
    dependents_of, _ = _graph({"T": ["V1"], "V1": ["V2"], "V2": ["M"]})
    assert scope.models_reached(["T"], dependents_of, {"M"}, max_depth=2) == set()
    assert scope.models_reached(["T"], dependents_of, {"M"}, max_depth=3) == {"M"}


def test_models_reached_skips_legacy_worksheets_and_does_not_follow_them():
    dependents_of, calls = _graph({"T": ["W"], "W": ["M"]})
    assert scope.models_reached(["T"], dependents_of, {"M"}, skip={"W"}) == set()
    assert calls == [["T"]]


def test_inventory_shape():
    inv = scope.inventory([{"guid": "m1", "name": "Sales"}], legacy=2,
                          connections=["Snowflake Prod"], tables_on_connections=5)
    assert inv == {"models": [{"guid": "m1", "name": "Sales"}], "model_count": 1,
                   "legacy_worksheets_skipped": 2, "connections": ["Snowflake Prod"],
                   "tables_on_connections": 5}


def test_resolve_scope_end_to_end_with_a_fake_client():
    class Resp:
        def __init__(self, data):
            self._d = data

        def json(self):
            return self._d

    models = [_row("M1", "Sales"), _row("M2", "Ops"), _row("W", "Legacy", version=None)]
    tables = [_row("T1", "FACT", None, "Snowflake Prod"), _row("T2", "X", None, "BigQuery")]

    class Client:
        def post(self, path, json):
            md = json["metadata"]
            if json.get("include_dependent_objects"):
                deps = {"T1": ["M1"]}
                return Resp([{"metadata_id": m["identifier"], "dependent_objects": {"dependents": {
                    m["identifier"]: {"LOGICAL_TABLE": [{"id": d} for d in deps.get(m["identifier"], [])]}}}}
                    for m in md])
            if json["record_offset"]:
                return Resp([])
            return Resp(models if md[0].get("subtypes") == ["WORKSHEET"] else tables)

    inv = scope.resolve_scope(Client(), connections=["snowflake prod"])
    assert [m["guid"] for m in inv["models"]] == ["M1"]
    assert inv["legacy_worksheets_skipped"] == 1 and inv["tables_on_connections"] == 1

    inv = scope.resolve_scope(Client(), connections=None)
    assert [m["guid"] for m in inv["models"]] == ["M1", "M2"]
    assert inv["connections"] == [] and inv["tables_on_connections"] is None


# --- `ts audit run` scope options -------------------------------------------------

def _cli(monkeypatch, inv=None):
    from typer.testing import CliRunner
    from ts_cli.cli import app
    from ts_cli.commands import audit as audit_cmd
    seen = {}

    def fake_resolve(client, connections=None):
        seen["connections"] = connections
        return inv
    monkeypatch.setattr(scope, "resolve_scope", fake_resolve)
    monkeypatch.setattr(audit_cmd, "ThoughtSpotClient", lambda cfg: object())
    monkeypatch.setattr(audit_cmd, "resolve_profile", lambda p: {})
    runner = CliRunner(mix_stderr=False) if "mix_stderr" in CliRunner.__init__.__code__.co_varnames \
        else CliRunner()
    return (lambda *args: runner.invoke(app, ["audit", "run", *args])), seen


@pytest.mark.parametrize("args, hint", [
    ([], "--models"),
    (["--models", "m1", "--all-models"], "--all-models"),
    (["--connection", "X"], "--connection"),
    (["--models", "m1", "--dry-run"], "--dry-run"),
    (["--all-models", "--snapshot-in", "/nonexistent"], "--snapshot-in"),
])
def test_scope_options_are_refused_in_bad_combinations(monkeypatch, args, hint):
    run, _ = _cli(monkeypatch)
    res = run(*args)
    assert res.exit_code == 2
    assert hint in (res.output + (res.stderr if hasattr(res, "stderr") else ""))


def test_dry_run_prints_the_inventory_and_audits_nothing(monkeypatch):
    import json
    from ts_cli import audit as audit_pkg
    inv = scope.inventory([{"guid": "m1", "name": "Sales"}], 0, ["Snowflake Prod"], 3)
    run, seen = _cli(monkeypatch, inv)
    monkeypatch.setattr(audit_pkg, "run_audit", lambda *a, **k: pytest.fail("audited on --dry-run"))
    res = run("--all-models", "--connection", "Snowflake Prod", "--dry-run")
    assert res.exit_code == 0, res.output
    assert seen["connections"] == ["Snowflake Prod"]
    assert json.loads(res.stdout)["models"] == [{"guid": "m1", "name": "Sales"}]


def test_an_empty_scope_exits_non_zero_and_never_audits(monkeypatch):
    from ts_cli import audit as audit_pkg
    run, _ = _cli(monkeypatch, scope.inventory([], 2, ["Nowhere"], 0))
    monkeypatch.setattr(audit_pkg, "run_audit", lambda *a, **k: pytest.fail("audited an empty scope"))
    res = run("--all-models", "--connection", "Nowhere")
    assert res.exit_code == 1


def test_all_models_passes_the_resolved_guids_to_the_audit(monkeypatch):
    from ts_cli import audit as audit_pkg
    run, _ = _cli(monkeypatch, scope.inventory([{"guid": "m1", "name": "A"},
                                                {"guid": "m2", "name": "B"}], 0, [], None))
    got = {}

    def fake_run_audit(client, models, angles, assessment, **kw):
        got["models"] = models
        return {"findings": [], "summary": {}}
    monkeypatch.setattr(audit_pkg, "run_audit", fake_run_audit)
    res = run("--all-models")
    assert res.exit_code == 0, res.output
    assert got["models"] == ["m1", "m2"]
