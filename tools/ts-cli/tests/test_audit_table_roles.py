"""The audit reads table roles from the shared classifier (agents/shared/erd/roles.py;
audit v2 roadmap PR 4.1): the role fields, D7, D11 and the corpus."""
from __future__ import annotations

import pytest

from ts_cli.audit import build_corpus, erd
from ts_cli.audit.context import make_context
from ts_cli.audit.engine import fields, scopes, tml


def _col(table, i, kind="MEASURE"):
    return {"name": f"{table} {kind} {i}", "column_id": f"{table}::C{kind}{i}",
            "properties": {"column_type": kind}}


def _model(name="Sales", lines=3, header=1, card="ONE_TO_MANY", referencing=False):
    """HEADER declares a one-to-many join to LINES (so LINES is the many side) and a
    many-to-one join to CUSTOMER. LINES holds `lines` measures, HEADER `header`."""
    to_lines = {"with": "LINES"}
    if referencing:
        to_lines["referencing_join"] = "header_lines"
    else:
        to_lines["cardinality"] = card
    cols = ([_col("LINES", i) for i in range(lines)] + [_col("HEADER", i) for i in range(header)]
            + [_col("CUSTOMER", 0, "ATTRIBUTE")])
    return {"name": name, "columns": cols, "model_tables": [
        {"name": "LINES", "fqn": "t-lines"},
        {"name": "HEADER", "fqn": "t-header",
         "joins": [to_lines, {"with": "CUSTOMER", "cardinality": "MANY_TO_ONE"}]},
        {"name": "CUSTOMER", "fqn": "t-cust"}]}


def _ctx(*models, tables=None):
    return make_context(models=[{"guid": f"m-{i}", "model": m} for i, m in enumerate(models)],
                        model_guids=[f"m-{i}" for i in range(len(models))], tables=tables or {})


def _items(ctx, scope):
    return list(scopes.iterate(ctx, scope))


def test_load_table_roles_fails_loudly(monkeypatch, tmp_path):
    monkeypatch.setattr(erd, "_TABLE_ROLES", None)
    monkeypatch.setattr(erd, "_ERD_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="roles.py"):
        erd.load_table_roles()


def test_fields_read_roles():
    ctx = _ctx(_model())
    roles = {i["name"]: fields.get(i, "@table_role", ctx) for i in _items(ctx, "model.table")}
    assert roles == {"LINES": "fact", "HEADER": "dimension_with_measures",
                     "CUSTOMER": "dimension"}
    (model,) = _items(ctx, "model")
    assert fields.get(model, "@fact_tables", ctx) == ["LINES"]
    assert fields.get(model, "@fact_table_count", ctx) == 1
    assert fields.get(model, "@fact_table_set", ctx) == ["t-lines"]
    both = {j["obj"]["with"]: fields.get(j, "@is_fact_to_fact_join", ctx)
            for j in _items(ctx, "join")}
    assert both == {"LINES": True, "CUSTOMER": False}


def test_a_root_with_one_measure_is_a_fact_the_old_count_missed():
    ctx = _ctx(_model(lines=1, header=0))
    (model,) = _items(ctx, "model")
    assert fields.get(model, "@fact_tables", ctx) == ["LINES"]


def test_referencing_join_cardinality_comes_from_the_table():
    tables = {"t-header": {"table": {"joins_with": [
        {"name": "header_lines", "destination": {"name": "LINES"},
         "cardinality": "ONE_TO_MANY"}]}}}
    roles = tml.model_table_roles(_model(referencing=True), tables)
    assert (roles["LINES"]["role"], roles["HEADER"]["role"]) == (
        "fact", "dimension_with_measures")


def test_referencing_join_without_table_tml_reads_many_to_one():
    roles = tml.model_table_roles(_model(referencing=True), {})
    # HEADER is now the declaring, many side of both joins: a root holding a measure
    assert (roles["HEADER"]["role"], roles["LINES"]["role"]) == (
        "fact", "dimension_with_measures")


def test_corpus_carries_roles():
    corpus = build_corpus(_ctx(_model()), angles=["D"])
    (m,) = corpus["models"]
    assert [(t["name"], t["role"]) for t in m["model_tables"]] == [
        ("LINES", "fact"), ("HEADER", "dimension_with_measures"), ("CUSTOMER", "dimension")]
