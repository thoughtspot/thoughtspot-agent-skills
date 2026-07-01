import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import erd_data


def _model(name, rls_expr=None):
    rls = [{"name": "r", "expr": rls_expr, "scope": "s"}] if rls_expr else []
    return {
        "model": {"name": name, "guid": name.lower(), "description": ""},
        "tables": [{"id": "T", "kind": "fact", "cols": [], "rls": rls}],
        "joins": [{"from": "T", "to": "U", "name": "j", "card": "MANY_TO_ONE",
                   "origin": "table", "type": "INNER"}],
        "formulas": {}, "findings": [],
    }


def test_assemble_builds_index():
    b = erd_data.assemble([_model("Alpha")])
    assert b["index"][0]["name"] == "Alpha"
    assert b["index"][0]["tables"] == 1
    assert b["index"][0]["joins"] == 1
    assert b["dropped"] == []


def test_assemble_caps_and_logs():
    msgs = []
    models = [_model("M%d" % i) for i in range(5)]
    b = erd_data.assemble(models, max_models=2, log=msgs.append)
    assert len(b["models"]) == 2
    assert b["dropped"] == ["M2", "M3", "M4"]
    assert any("M2" in m for m in msgs)


def test_assemble_redacts_rls():
    b = erd_data.assemble([_model("Sec", rls_expr="secret_expr()")], redact_rls=True)
    assert b["models"][0]["tables"][0]["rls"][0]["expr"] == "(redacted)"
