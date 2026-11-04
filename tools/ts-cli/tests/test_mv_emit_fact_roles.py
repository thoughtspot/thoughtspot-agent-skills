"""BL-505: the to-Databricks emitter's fact tables agree with the shared table-role
classifier (agents/shared/erd/roles.py) on what is a join root.

`mv_emit.detect_fact_tables` is vendored into the Databricks Genie notebook
(agents/databricks/build_mv_lib.py concatenates ts_cli modules only), so it cannot load
the classifier, which lives outside ts_cli. It reads join direction by the classifier's
rule instead — MANY_TO_ONE (or none) points from the declaring table to `with`,
ONE_TO_MANY the other way, ONE_TO_ONE and MANY_TO_MANY not at all — and this test holds
the two to the same answer. `_join_target_tables` read every `with` as joined-to, so a
ONE_TO_MANY join made the fact the dimension and split no Metric View around it.

Measures differ on purpose: the emitter also counts a formula measure toward the table
it reads, because those are the measures a Metric View carries; the classifier counts
physical columns only.
"""
from __future__ import annotations

import pytest

from ts_cli.audit.erd import load_table_roles
from ts_cli.databricks.mv_emit import detect_fact_tables


def _col(table, name, kind="MEASURE"):
    return {"name": name, "column_id": f"{table}::{name}",
            "properties": {"column_type": kind}}


def _model(joins_on_fact=(), joins_on_dim=(), extra_tables=()):
    return {"name": "M", "model_tables": [
        {"name": "FACT", "joins": list(joins_on_fact)},
        {"name": "DIM", "joins": list(joins_on_dim)}, *extra_tables],
        "columns": [_col("FACT", "AMOUNT"), _col("DIM", "NAME", "ATTRIBUTE"),
                    _col("DIM", "WEIGHT")]}


CASES = {
    "many-to-one from the fact": _model(joins_on_fact=[
        {"with": "DIM", "on": "[FACT::K] = [DIM::K]", "cardinality": "MANY_TO_ONE"}]),
    "no cardinality": _model(joins_on_fact=[{"with": "DIM", "on": "[FACT::K] = [DIM::K]"}]),
    "one-to-many declared on the dimension": _model(joins_on_dim=[
        {"with": "FACT", "on": "[DIM::K] = [FACT::K]", "cardinality": "ONE_TO_MANY"}]),
    "one-to-one": _model(joins_on_fact=[
        {"with": "DIM", "on": "[FACT::K] = [DIM::K]", "cardinality": "ONE_TO_ONE"}]),
}


def _classifier_roots(model):
    roles = load_table_roles()(model)
    measured = {k for k, r in roles.items() if r["measures"]}
    joined_to = {k for k, r in roles.items()
                 if r["role"] in ("dimension", "dimension_with_measures")
                 and not r["unjoined"] and len(roles) > 1}
    return [k for k in roles if k in measured and k not in joined_to]


@pytest.mark.parametrize("case", list(CASES))
def test_fact_tables_match_the_classifiers_measured_roots(case):
    model = CASES[case]
    assert detect_fact_tables(model) == _classifier_roots(model)


def test_a_one_to_many_join_keeps_the_fact_the_fact():
    model = CASES["one-to-many declared on the dimension"]
    assert detect_fact_tables(model) == ["FACT"]


def test_a_formula_measure_counts_toward_its_table():
    model = {"name": "M", "model_tables": [
        {"name": "FACT", "joins": [{"with": "DIM", "on": "[FACT::K] = [DIM::K]"}]},
        {"name": "DIM"}],
        "formulas": [{"id": "f_total", "name": "Total", "expr": "sum ( [FACT::AMOUNT] )"}],
        "columns": [{"name": "Total", "formula_id": "f_total",
                     "properties": {"column_type": "MEASURE"}},
                    _col("DIM", "NAME", "ATTRIBUTE")]}
    assert detect_fact_tables(model) == ["FACT"]
    assert load_table_roles()(model)["FACT"]["role"] == "factless"   # physical only
