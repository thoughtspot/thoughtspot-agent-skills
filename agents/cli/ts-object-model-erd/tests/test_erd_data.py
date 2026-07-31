import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import erd_data
import parser


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


# ---------------------------------------------------------------------------
# BL-203 — inline joins must keep their declared name
# ---------------------------------------------------------------------------

def _inline(name, with_, on, frm="FACT_SALES"):
    return {"name": name, "with": with_, "on": on,
            "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"}


def _model_tml(joins, extra_tables=()):
    return {"model": {
        "name": "M",
        "model_tables": [{"name": "FACT_SALES", "joins": list(joins)},
                         {"name": "DIM_TIME"}, *extra_tables],
        "columns": [], "formulas": []}}


def test_inline_join_keeps_its_declared_name():
    """The synthesized `{from}_{to}` discarded the real name, and the viewer
    keys edges by name — so a pair joined twice was unreachable past the
    first."""
    parsed = parser.parse_model(_model_tml([
        _inline("FACT_SALES_TO_DIM_TIME_TXN", "DIM_TIME",
                "[FACT_SALES::TXN_DATE_ID] = [DIM_TIME::DATE_ID]"),
        _inline("FACT_SALES_TO_DIM_TIME_SHIP", "DIM_TIME",
                "[FACT_SALES::SHIP_DATE_ID] = [DIM_TIME::DATE_ID]"),
    ]), {})
    names = [j["name"] for j in parsed["joins"]]
    assert names == ["FACT_SALES_TO_DIM_TIME_TXN", "FACT_SALES_TO_DIM_TIME_SHIP"]
    assert len(set(names)) == 2, "same-pair joins must stay distinguishable"


def test_inline_join_without_a_name_falls_back():
    parsed = parser.parse_model(_model_tml([
        {"with": "DIM_TIME", "on": "[FACT_SALES::A] = [DIM_TIME::DATE_ID]",
         "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"}]), {})
    assert parsed["joins"][0]["name"] == "FACT_SALES_DIM_TIME"


def test_inline_join_does_not_report_degraded_fidelity():
    """An inline join carries cardinality and type itself, so a Table-TML miss
    costs it nothing — the warning fired on every inline-join model."""
    logs = []
    parser.parse_model(_model_tml([
        _inline("FACT_SALES_TO_DIM_TIME_TXN", "DIM_TIME",
                "[FACT_SALES::TXN_DATE_ID] = [DIM_TIME::DATE_ID]")]),
        {}, log=logs.append)
    assert not [m for m in logs if "Fidelity degraded" in m], logs


def test_referencing_join_still_reports_degraded_fidelity():
    """A referencing join genuinely depends on the Table TML for its
    cardinality and type, so the warning must survive for that shape."""
    logs = []
    parser.parse_model({"model": {
        "name": "M",
        "model_tables": [
            {"name": "FACT_SALES", "joins": [
                {"with": "DIM_TIME", "referencing_join": "SYS_CONSTRAINT_1"}]},
            {"name": "DIM_TIME"}],
        "columns": [], "formulas": []}}, {}, log=logs.append)
    assert [m for m in logs if "Fidelity degraded" in m], logs
