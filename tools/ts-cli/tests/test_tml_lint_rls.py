"""I22 — an RLS join that closes a cycle with the Model's joins (synthetic tables)."""
from __future__ import annotations

import json

import yaml
from typer.testing import CliRunner

from test_rls_join_cycles import CASE_MODEL, case_users, rls_table
from ts_cli.tml_lint import lint_rls_join_cycles


def _model(model_tables):
    return {"model": {"name": "m", "model_tables": model_tables, "columns": []}}


def test_i22_fires_on_case_shape():
    found = lint_rls_join_cycles(_model(CASE_MODEL), {"users": case_users()})
    assert len(found) == 1
    msg = found[0]
    assert msg.startswith("I22: ")
    for word in ("'users'", "'bridge'", "users_to_bridge", "bridge_users", "Guid Mismatch"):
        assert word in msg


def test_i22_silent_without_table_tmls():
    assert lint_rls_join_cycles(_model(CASE_MODEL), {}) == []


def test_i22_partial_batch():
    orgs = rls_table("orgs", [], [("orgs_1", "orgs", None)], ["[orgs_1::c] = 1"])
    assert lint_rls_join_cycles(_model(CASE_MODEL), {"orgs": orgs}) == []


def test_i22_ignores_non_models():
    assert lint_rls_join_cycles({"table": {"name": "t"}}, {"users": case_users()}) == []


def _table_doc(body):
    return {"table": {**body, "db": "d", "schema": "s", "db_table": body["name"],
                      "connection": {"name": "X"},
                      "columns": [{"name": "c", "db_column_name": "c",
                                   "properties": {"column_type": "ATTRIBUTE"},
                                   "db_column_properties": {"data_type": "VARCHAR"}}]}}


def test_i22_cli_batch(tmp_path):
    from ts_cli.cli import app
    (tmp_path / "users.table.tml").write_text(yaml.safe_dump(_table_doc(case_users())))
    for name in ("fact", "bridge"):
        (tmp_path / f"{name}.table.tml").write_text(
            yaml.safe_dump(_table_doc({"name": name})))
    (tmp_path / "m.model.tml").write_text(yaml.safe_dump(_model(CASE_MODEL)))
    res = CliRunner().invoke(app, ["tml", "lint", "--dir", str(tmp_path)])
    out = json.loads(res.stdout)
    assert res.exit_code == 1
    assert any(f.startswith("I22:") for r in out["results"] for f in r["findings"])
    alone = CliRunner().invoke(app, ["tml", "lint", "--file", str(tmp_path / "m.model.tml")])
    assert not any(f.startswith("I22:") for r in json.loads(alone.stdout)["results"]
                   for f in r["findings"])
