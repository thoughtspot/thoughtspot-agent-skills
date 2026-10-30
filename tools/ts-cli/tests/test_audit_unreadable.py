"""BL-406 item 10: a Model whose TML, or a Table it uses, holds a list or scalar where a
mapping belongs is not judged, and is listed (product owner's rulings, 2026-10-30).

What hangs off an excluded object goes with it — its Answers, its metadata header, its
Sets — or a rule judges them against something no rule can see (PR #693 review, round
5: an excluded Model's Answers raised a false H8 "not in model").
"""
from __future__ import annotations

import audit_rule_fixtures as fx
from ts_cli.audit import run_audit
from ts_cli.audit.context import make_context

BAD = ["not", "a", "mapping"]


def _model(guid="m-1", name="Sales", props=None, formulas=None, tables=None):
    body = {"name": name, "columns": [
        {"name": "Amount", "column_id": "ORDERS::AMOUNT",
         "properties": {"column_type": "MEASURE"}}],
        "model_tables": tables if tables is not None else [{"name": "ORDERS", "fqn": "t-1"}],
        "formulas": formulas or []}
    if props is not None:
        body["properties"] = props
    return {"guid": guid, "model": body}


def _answer(guid, model_guid, formula):
    return {"guid": guid, "answer": {
        "name": guid.upper(), "tables": [{"name": "Sales", "fqn": model_guid}],
        "formulas": [{"name": "Rev", "expr": formula}]}}


def _ids(out, check):
    return {f["object_guid"] for f in out["findings"] if f["check_id"] == check}


def _listed(out):
    return " | ".join(out["corpus"].get("unreadable") or [])


def test_an_excluded_models_answers_are_not_judged_against_it():
    """Round-5 blocker: the Model already holds the formula, so H9 (LOW) is right and
    H8 (HIGH, "not in model") is wrong. Unreadable, the Model and its Answers are left
    out and listed; readable, H9 fires as before."""
    formula = "sum ( [Amount] )"

    def run(props):
        ctx = make_context(
            models=[_model(props=props, formulas=[{"name": "Rev", "expr": formula}])],
            answers=[_answer("a-1", "m-1", formula), _answer("a-2", "m-1", formula)],
            model_guids=["m-1"])
        return run_audit(None, ["m-1"], ctx=ctx, angles=["H"])
    readable = run({})
    assert _ids(readable, "H9") == {"a-1", "a-2"}
    out = run(BAD)
    assert not _ids(out, "H8") and not _ids(out, "H9")
    listed = _listed(out)
    assert "Model 'Sales' (m-1)" in listed
    assert "Answer 'A-1' (a-1): built on Model 'Sales', which is not judged" in listed
    assert "Answer 'A-2' (a-2)" in listed


def test_a_malformed_table_takes_its_metadata_header_and_its_models_with_it():
    """D8 reads metadata headers: a malformed Table must not be judged there either."""
    bad_table = {"guid": "t-1", "table": {"name": "ORDERS", "columns": [
        {"name": "AMOUNT", "db_column_properties": BAD}]}}
    ctx = make_context(
        models=[_model()], tables={"t-1": bad_table}, model_guids=["m-1"],
        metadata=[fx.build_search_row("t-1", "ORDERS"), fx.build_search_row("t-2", "ORDERS")])
    out = run_audit(None, ["m-1"], ctx=ctx, angles=["D"])
    assert "t-1" not in _ids(out, "D8")
    assert not {f["object_guid"] for f in out["findings"]} & {"m-1", "t-1"}
    listed = _listed(out)
    assert "Table 'ORDERS' (t-1): 'columns[AMOUNT].db_column_properties' is not a mapping" in listed
    assert "Model 'Sales' (m-1): uses Table 'ORDERS', whose TML is malformed" in listed


def test_an_excluded_models_sets_are_not_judged():
    """H5 judges a Set by its Model's dependents; the Set is part of the excluded unit."""
    ctx = fx.human_set_without_consumers()
    assert _ids(run_audit(None, [], ctx=ctx, angles=["H"]), "H5")
    ctx = fx.human_set_without_consumers()
    ctx.models[0]["model"]["properties"] = BAD
    out = run_audit(None, [], ctx=ctx, angles=["H"])
    assert not _ids(out, "H5") and not _ids(out, "H4")


def test_a_malformed_answer_is_not_judged_and_is_listed():
    formula = "count ( [Amount] )"
    bad = _answer("a-1", "m-1", formula)
    bad["answer"]["formulas"][0]["properties"] = BAD
    ctx = make_context(models=[_model()], model_guids=["m-1"],
                       answers=[bad, _answer("a-2", "m-1", formula)])
    out = run_audit(None, ["m-1"], ctx=ctx, angles=["H"])
    assert "a-1" not in {f["object_guid"] for f in out["findings"]}
    assert "Answer 'A-1' (a-1): 'formulas[Rev].properties' is not a mapping" in _listed(out)


def test_a_table_is_linked_by_fqn_only_never_by_name():
    """A well-formed Model whose `ORDERS` is not fetched (a SQL View, a failed export)
    is not excluded because some other Table named `ORDERS` is malformed."""
    other = {"guid": "t-9", "table": {"name": "ORDERS", "properties": BAD, "columns": []}}
    ctx = make_context(models=[_model(tables=[{"name": "ORDERS", "fqn": "t-sqlview"}])],
                       tables={"t-9": other}, model_guids=["m-1"])
    out = run_audit(None, ["m-1"], ctx=ctx)
    assert "Model 'Sales'" not in _listed(out)
    assert "Table 'ORDERS' (t-9)" in _listed(out)
    assert "m-1" in {m["guid"] for m in out["corpus"]["models"]}


def test_one_entry_per_object_so_the_box_counts_objects():
    """Sixty bad columns on one Model and one on another: two entries, both named."""
    a = _model()
    a["model"]["columns"] = [{"name": f"C{i}", "column_id": f"ORDERS::C{i}",
                              "properties": BAD} for i in range(60)]
    b = _model(guid="m-2", name="Returns", props=BAD)
    out = run_audit(None, ["m-1", "m-2"],
                    ctx=make_context(models=[a, b], model_guids=["m-1", "m-2"]))
    assert len(out["corpus"]["unreadable"]) == 2
    assert "Model 'Returns' (m-2)" in _listed(out)
