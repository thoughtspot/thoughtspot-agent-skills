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


# ── the rules that read roles ───────────────────────────────────────────────

def _d11(ctx):
    from audit_run_rule import run_rule
    return {(f.object_name, f.severity) for f in run_rule(ctx, "D11")}


def test_d11_medium_when_both_ends_hold_one_to_three_measures():
    # the old count (more than 3) called neither end a fact, so this was INFO
    from audit_run_rule import run_rule
    (finding,) = run_rule(_ctx(_model(lines=2, header=1)), "D11")
    assert finding.severity == "MEDIUM"
    assert "both hold measures" in finding.detail


def test_d11_info_when_one_end_holds_no_measures():
    assert {sev for _, sev in _d11(_ctx(_model(lines=5, header=0)))} == {"INFO"}


def _overlap(name, shared, own):
    """A Model holding the shared tables plus its own dimension, all joined from the
    first shared table (LINES or HEADER), which then is the root."""
    mts = [{"name": t, "fqn": f"t-{t}"} for t in shared + [own]]
    mts[0]["joins"] = [{"with": t["name"], "cardinality": "MANY_TO_ONE"} for t in mts[1:]]
    return {"name": name, "model_tables": mts,
            "columns": [_col(t, 0) for t in shared] + [_col(own, 0, "ATTRIBUTE")]}


def _d7(ctx):
    from audit_run_rule import run_rule
    return sorted(f.severity for f in run_rule(ctx, "D7"))


def test_d7_medium_needs_a_shared_fact_not_a_shared_header():
    # two Models share LINES (a root holding a measure: a fact) and CAL: 2/4 tables...
    a, b = _overlap("A", ["LINES", "CAL", "X"], "OWN_A"), _overlap("B", ["LINES", "CAL", "X"], "OWN_B")
    assert _d7(_ctx(a, b)) == ["MEDIUM"]
    # ...but when the shared table holding measures is joined to (a header, here
    # under each Model's own root), the pair shares only dimensions: no finding
    def under_root(m, root):
        m["model_tables"].insert(0, {"name": root, "fqn": f"t-{root}", "joins": [
            {"with": m["model_tables"][0]["name"], "cardinality": "MANY_TO_ONE"}]})
        m["columns"].append(_col(root, 0))
        return m
    shared = ["HEADER", "CAL", "X", "Y", "Z"]  # 5 of 9 tables: above 0.5, below 1
    a = under_root(_overlap("A", list(shared), "OWN_A"), "ROOT_A")
    b = under_root(_overlap("B", list(shared), "OWN_B"), "ROOT_B")
    assert _d7(_ctx(a, b)) == []
    # the same pair, with the header read as a fact, would be MEDIUM: prove the size
    a["model_tables"].pop(0), b["model_tables"].pop(0)
    a["model_tables"].append({"name": "ROOT_A", "fqn": "t-ROOT_A"})
    b["model_tables"].append({"name": "ROOT_B", "fqn": "t-ROOT_B"})
    assert _d7(_ctx(a, b)) == ["MEDIUM"]
