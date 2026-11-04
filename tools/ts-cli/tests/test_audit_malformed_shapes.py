"""BL-501: a list or mapping the audit reads, holding the wrong shape, is "not judged",
never a crash.

Item 10 (test_audit_unreadable.py) covered a list or scalar under a MAPPING_KEYS key.
Anywhere else the schema has a mapping, or a list of mappings, a different shape ended
`ts audit run` with an AttributeError and no warning. Each case below mutates one shape
of a populated context and runs the whole audit, both assessments, then the report: the
object holding the shape is listed under "Could not be read", with what it depends on,
and nothing about it is judged.

`rls_rules` as a flat list of rules is malformed too, not a second shape: the Table TML
schema and the 2026-07-30 census (both Tables with RLS) show a mapping only, and reading
it as absent would call a protected Table unprotected. Listed, it is judged neither way.
"""
from __future__ import annotations

import pytest

from audit_rule_fixtures.common import registry_populated_context
from ts_cli.audit import run_audit
from ts_cli.audit.report import render_report

TABLE = "Table 'ORDERS' (t-1)"
MODEL = "Model 'Sales' (m-1)"
VIA_TABLE = f"{MODEL}: uses Table 'ORDERS', whose TML is malformed"


def _ctx():
    """The populated context, plus a healthy Model m-2 with an Answer built on it that has
    a formula and a table reference: H7, H8 and H9 then run, and they read EVERY Model,
    the excluded ones included (fields_human._all_models; review of PR 1, blocker 1)."""
    ctx = registry_populated_context()
    ctx.models.append({"guid": "m-2", "model": {
        "name": "Healthy", "columns": [], "model_tables": [{"name": "ORDERS", "fqn": "t-1"}],
        "formulas": [{"name": "Rev", "expr": "sum ( [Amount] )"}]}})
    ctx.answers.append({"guid": "a-2", "answer": {
        "name": "On healthy", "tables": [{"name": "Healthy", "fqn": "m-2"}],
        "formulas": [{"name": "Rev", "expr": "sum ( [Amount] )"}]}})
    ctx.model_guids = ["m-1", "m-2"]
    ctx.dependents = {"m-1": [{"guid": "a-1", "type": "ANSWER", "name": "A"}],
                      "m-2": [{"guid": "a-2", "type": "ANSWER", "name": "On healthy"}]}
    return ctx


def _model(ctx):
    return ctx.models[0]["model"]


def _table(ctx):
    return ctx.tables["t-1"]["table"]


def _uncoached(ctx):
    ctx.ai_instructions = {"m-1": {"nl_instructions_info": []}}


# (mutation, the entries that must be listed)
CASES = {
    "rls_rules as a flat list of rules": (
        lambda c: _table(c).__setitem__(
            "rls_rules", [{"name": "r1", "expr": "[ORDERS::CUST_ID] = 'x'"}]),
        [f"{TABLE}: 'rls_rules' is not a mapping", VIA_TABLE]),
    "rls_rules as a string": (
        lambda c: _table(c).__setitem__("rls_rules", "oops"),
        [f"{TABLE}: 'rls_rules' is not a mapping", VIA_TABLE]),
    "a scalar rls rule": (
        lambda c: _table(c)["rls_rules"].__setitem__("rules", ["oops"]),
        [f"{TABLE}: 'rls_rules.rules.0' is not a mapping", VIA_TABLE]),
    "rls rules as a string": (
        lambda c: _table(c)["rls_rules"].__setitem__("rules", "oops"),
        [f"{TABLE}: 'rls_rules.rules' is not a list", VIA_TABLE]),
    "model_instructions as a list, uncoached": (
        lambda c: (_model(c).__setitem__("model_instructions", ["x"]), _uncoached(c)),
        [f"{MODEL}: 'model_instructions' is not a mapping"]),
    "model_instructions as a string, uncoached": (
        lambda c: (_model(c).__setitem__("model_instructions", "x"), _uncoached(c)),
        [f"{MODEL}: 'model_instructions' is not a mapping"]),
    "joins_with as a mapping": (
        lambda c: _table(c).__setitem__("joins_with", {"name": "j"}),
        [f"{TABLE}: 'joins_with' is not a list", VIA_TABLE]),
    "a scalar joins_with entry": (
        lambda c: _table(c).__setitem__("joins_with", ["j"]),
        [f"{TABLE}: 'joins_with.0' is not a mapping", VIA_TABLE]),
    "a scalar model_tables entry": (
        lambda c: _model(c)["model_tables"].append("oops"),
        [f"{MODEL}: 'model_tables.1' is not a mapping"]),
    "model_tables as a mapping": (
        lambda c: _model(c).__setitem__("model_tables", {"name": "ORDERS", "fqn": "t-1"}),
        [f"{MODEL}: 'model_tables' is not a list"]),
    "a scalar join": (
        lambda c: _model(c)["model_tables"][0]["joins"].append("oops"),
        [f"{MODEL}: 'model_tables[ORDERS].joins.1' is not a mapping"]),
    "a scalar Model column": (
        lambda c: _model(c)["columns"].append("oops"),
        [f"{MODEL}: 'columns.2' is not a mapping"]),
    "Model columns as a mapping": (
        lambda c: _model(c).__setitem__("columns", {"name": "x"}),
        [f"{MODEL}: 'columns' is not a list"]),
    "a scalar formula": (
        lambda c: _model(c).__setitem__("formulas", ["oops"]),
        [f"{MODEL}: 'formulas.0' is not a mapping"]),
    "a scalar Model filter": (
        lambda c: _model(c).__setitem__("filters", ["oops"]),
        [f"{MODEL}: 'filters.0' is not a mapping"]),
    "a scalar Table column": (
        lambda c: _table(c)["columns"].append("oops"),
        [f"{TABLE}: 'columns.2' is not a mapping", VIA_TABLE]),
    "a Model body that is not a mapping": (
        lambda c: c.models[0].__setitem__("model", ["oops"]),
        ["Model '' (m-1): 'model' is not a mapping"]),
    "a null Model body": (
        lambda c: c.models[0].__setitem__("model", None),
        ["Model '' (m-1): 'model' is not a mapping"]),
    "formulas as a mapping": (
        lambda c: _model(c).__setitem__("formulas", {"name": "x"}),
        [f"{MODEL}: 'formulas' is not a list"]),
    "a null formula entry": (
        lambda c: _model(c).__setitem__("formulas", [None]),
        [f"{MODEL}: 'formulas.0' is not a mapping"]),
    "model_tables as a number": (
        lambda c: _model(c).__setitem__("model_tables", 5),
        [f"{MODEL}: 'model_tables' is not a list"]),
    "a null Table body": (
        lambda c: c.tables["t-1"].__setitem__("table", None),
        ["Table '' (t-1): 'table' is not a mapping",
         f"{MODEL}: uses Table 'ORDERS', whose TML is malformed"]),
    "a Table body that is not a mapping": (
        lambda c: c.tables["t-1"].__setitem__("table", "oops"),
        ["Table '' (t-1): 'table' is not a mapping",
         f"{MODEL}: uses Table 'ORDERS', whose TML is malformed"]),
    "a scalar Answer formula": (
        lambda c: c.answers[0]["answer"].__setitem__("formulas", ["oops"]),
        ["Answer 'A' (a-1): 'formulas.0' is not a mapping"]),
    "a scalar Answer table": (
        lambda c: c.answers[0]["answer"].__setitem__("tables", ["oops"]),
        ["Answer 'A' (a-1): 'tables.0' is not a mapping"]),
}


@pytest.mark.parametrize("assessment", ["general", "spotter"])
@pytest.mark.parametrize("case", list(CASES))
def test_a_misshapen_list_or_mapping_is_listed_not_a_crash(case, assessment):
    mutate, expected = CASES[case]
    ctx = _ctx()
    mutate(ctx)
    out = run_audit(None, ["m-1", "m-2"], ctx=ctx, assessment_name=assessment)
    listed = out["corpus"].get("unreadable") or []
    for entry in expected:
        assert any(line.startswith(entry) for line in listed), (entry, listed)
    judged = {f["object_guid"] for f in out["findings"]}
    if expected[0].startswith("Answer"):
        gone = {"a-1"}
    elif any(e.startswith("Table") for e in expected):
        gone = {"m-1", "t-1", "tg-1"}           # the Table and the Model using it
    else:
        gone = {"m-1"}                           # its well-formed Table is still judged
    assert not judged & gone
    assert "Could not be read" in render_report(out)


@pytest.mark.parametrize("value", [None, 0, False, ""])
@pytest.mark.parametrize("key", ["columns", "formulas", "model_tables"])
def test_an_empty_looking_list_reads_as_empty_and_ends_nothing(key, value):
    """Falsy values are read as empty, as every reader takes them (review of PR 1,
    must-fix 2: `formulas: null` ended run_audit in the shared ERD parser)."""
    ctx = _ctx()
    _model(ctx)[key] = value
    out = run_audit(None, ["m-1", "m-2"], ctx=ctx)
    assert not out["corpus"].get("unreadable")
    render_report(out)


@pytest.mark.parametrize("builder", ["sec_lists_none", "data_lists_none", "human_lists_none"])
def test_the_pinned_empty_inputs_run_end_to_end(builder):
    """They were judged only through run_rules; the whole run ended on them."""
    import audit_rule_fixtures as fx
    out = run_audit(None, [], ctx=getattr(fx, builder)())
    render_report(out)


@pytest.mark.parametrize("mutate", [
    lambda c: _model(c).__setitem__("parameters", ["oops"]),
    lambda c: _table(c)["rls_rules"].__setitem__("table_paths", "oops"),
    lambda c: _table(c)["rls_rules"].__setitem__("tables", ["oops"]),
], ids=["scalar parameter", "rls table_paths string", "scalar rls tables entry"])
def test_a_shape_no_rule_reads_does_not_exclude_its_model(mutate):
    """SHAPES covers what the audit reads; these readers guard or read nothing, and
    main judged such a Model (review of PR 1, minor 5)."""
    ctx = _ctx()
    mutate(ctx)
    out = run_audit(None, ["m-1", "m-2"], ctx=ctx)
    assert not out["corpus"].get("unreadable")
    render_report(out)


def test_listed_data_model_instructions_end_nothing():
    """The ai/instructions API's list shape written into the TML (review must-fix 3)."""
    ctx = _ctx()
    _model(ctx)["model_instructions"] = {"data_model_instructions": ["Use last 30 days"]}
    ctx.ai_instructions = {"m-1": {"nl_instructions_info": []}}
    render_report(run_audit(None, ["m-1"], ctx=ctx))


def test_the_well_formed_context_lists_nothing():
    for assessment in ("general", "spotter"):
        out = run_audit(None, ["m-1"], ctx=_ctx(), assessment_name=assessment)
        assert not out["corpus"].get("unreadable")
        render_report(out)


def test_a_protected_table_read_as_a_flat_list_is_never_called_unprotected():
    """The safety half of the rls_rules ruling: no Security finding on its Model."""
    mutate, _ = CASES["rls_rules as a flat list of rules"]
    ctx = _ctx()
    mutate(ctx)
    out = run_audit(None, ["m-1"], ctx=ctx, angles=["S"])
    assert not [f for f in out["findings"] if f["object_guid"] in {"m-1", "t-1", "tg-1"}]

