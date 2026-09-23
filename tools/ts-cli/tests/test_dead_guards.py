"""Two guards that could not do their job (BL-302, BL-303).

P5 suppresses its finding when the model carries a rolling date window. The
schema: *"The outer key is `constraints:`, which contains a single `constraint:`
list (not a list at the top level)"* — a **mapping**. `for c in constraints`
therefore yields the key string `"constraint"`, which never contains
`date_range_condition`, so a model with a genuine window was still reported as
having none. The existing fixture passed a list, which is the shape that hid it.

H5 reports a set with no consumers. It read `ctx.dependents[set_guid]`, but
`build_context` only fetches dependents for models and tables — a SET guid is
never a key — so `if not set_deps` was always true and every set in the
environment was reported an orphan, with a detail asserting a lookup that never
happened.
"""
from ts_cli.audit.checks_human import check_h5
from ts_cli.audit.checks_perf import check_p5
from ts_cli.audit.context import make_context


def _fact_model(constraints=None):
    """A model with a fact table, so P5 has something to report on."""
    m = {"name": "Sales",
         "columns": [{"name": f"M{i}", "column_id": f"ORDERS::M{i}",
                      "properties": {"column_type": "MEASURE"}} for i in range(4)],
         "model_tables": [{"name": "ORDERS"}]}
    if constraints is not None:
        m["constraints"] = constraints
    return {"guid": "m-1", "model": m}


# ── P5 — the real exported shape must suppress ─────────────────────────────

REAL_CONSTRAINTS = {"constraint": [
    {"date_range_condition": {"column": "Order Date", "period": "LAST_N_DAYS", "n": 90}}]}


def test_p5_reports_a_fact_model_with_no_constraints():
    assert len(check_p5(make_context(models=[_fact_model()]))) == 1


def test_p5_is_suppressed_by_the_real_mapping_shape():
    """The shape an export actually produces — previously ignored."""
    assert check_p5(make_context(models=[_fact_model(REAL_CONSTRAINTS)])) == []


def test_p5_is_still_suppressed_by_a_list_shape():
    """A hand-built fixture may pass a list; keep tolerating it."""
    listed = [{"date_range_condition": {"column": "Order Date"}}]
    assert check_p5(make_context(models=[_fact_model(listed)])) == []


def test_p5_is_not_suppressed_by_an_unrelated_constraint():
    other = {"constraint": [{"some_other_condition": {"column": "X"}}]}
    assert len(check_p5(make_context(models=[_fact_model(other)]))) == 1


# ── H5 — only speak about sets whose dependents were actually fetched ──────

SET_GUID = "set-1"


def _set_dep():
    return {"guid": SET_GUID, "type": "SET", "name": "FY24 Top Accounts"}


def test_h5_is_silent_when_the_sets_dependents_were_never_fetched():
    """`build_context` does not query dependents for sets, so absence of a key
    means "not looked up" — not "no consumers". Reporting an orphan from that
    is an assertion the check never earned."""
    ctx = make_context(dependents={"m-1": [_set_dep()]})
    assert check_h5(ctx) == []


def test_h5_reports_a_set_fetched_and_found_to_have_no_consumers():
    ctx = make_context(dependents={"m-1": [_set_dep()], SET_GUID: []})
    findings = check_h5(ctx)
    assert len(findings) == 1
    assert findings[0].object_guid == SET_GUID


def test_h5_stays_silent_on_a_set_with_consumers():
    ctx = make_context(dependents={
        "m-1": [_set_dep()],
        SET_GUID: [{"guid": "a-1", "type": "ANSWER", "name": "Uses the set"}]})
    assert check_h5(ctx) == []
