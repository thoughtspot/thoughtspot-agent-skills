"""Verdict rules for the AgentQL retest suite. No live calls."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from agentql_retest import classify as K  # noqa: E402
from agentql_retest.cases import CASES  # noqa: E402

OK_GEN = {"status": "SUCCESS", "executable_sql": "SELECT x FROM t LIMIT 100000", "errors": []}


def ok_fetch(rows):
    return {"status": "SUCCESS", "rows": rows, "errors": []}


def err(status, msg="boom"):
    return {"status": status, "errors": [{"code": status, "message": msg}]}


def case(**kw):
    base = dict(id="c", sql="SELECT 1", expect=K.OK, row="✅ something")
    base.update(kw)
    return K.Case(**base)


def test_shipped_case_list_is_well_formed():
    assert K.validate_cases(CASES) == []


def test_every_case_names_a_doc_row_and_controls_are_marked():
    for c in CASES:
        assert c.row.strip()
        if c.row == "control":
            assert c.control


def test_validate_catches_dangling_and_misused_controls():
    cases = [case(id="a", same_as="missing"), case(id="b", expect=K.GEN_ERROR, values=((0, 0, 1),)),
             case(id="ctl", expect=K.GEN_ERROR), case(id="d", differs_from="ctl"), case(id="a")]
    problems = K.validate_cases(cases)
    assert "duplicate id a" in problems
    assert any("control missing is not a case" in p for p in problems)
    assert any("b: value checks need" in p for p in problems)
    assert any("control ctl must expect ok" in p for p in problems)


# ---- known failures ----------------------------------------------------------------------

def test_gen_error_still_rejected_is_as_documented():
    c = case(expect=K.GEN_ERROR, code="SELF_JOIN")
    assert K.classify(c, err("SELF_JOIN"), None, {})[0] == K.AS_DOCUMENTED


def test_gen_error_that_now_compiles_is_changed():
    c = case(expect=K.GEN_ERROR, code="SELF_JOIN")
    v, reasons = K.classify(c, OK_GEN, None, {})
    assert v == K.CHANGED and "now compiles" in reasons[0]


def test_gen_error_with_a_different_status_is_changed():
    c = case(expect=K.GEN_ERROR, code="SELF_JOIN")
    v, reasons = K.classify(c, err("QUERY_GEN_ERROR"), None, {})
    assert v == K.CHANGED and "SELF_JOIN -> QUERY_GEN_ERROR" in reasons[0]


def test_fetch_error_that_now_executes_is_changed():
    c = case(expect=K.FETCH_ERROR, code="QUERY_EXECUTION_FAILED")
    assert K.classify(c, OK_GEN, ok_fetch([[1]]), {})[0] == K.CHANGED


def test_fetch_error_that_moved_to_generate_sql_is_changed():
    c = case(expect=K.FETCH_ERROR)
    v, reasons = K.classify(c, err("QUERY_GEN_ERROR"), None, {})
    assert v == K.CHANGED and "generate-sql now fails" in reasons[0]


def test_fetch_error_checks_the_emitted_sql_too():
    c = case(expect=K.FETCH_ERROR, code="QUERY_EXECUTION_FAILED", sql_has=("like_regex",))
    gen = dict(OK_GEN, executable_sql="WHERE regexp_like(x, 'a')")
    v, reasons = K.classify(c, gen, err("QUERY_EXECUTION_FAILED"), {})
    assert v == K.CHANGED and "like_regex" in reasons[0]


# ---- silent wrong answers ----------------------------------------------------------------

def test_silent_wrong_still_differs_from_control():
    c = case(differs_from="ctl")
    results = {"ctl": {"fetch": ok_fetch([[1756]])}}
    assert K.classify(c, OK_GEN, ok_fetch([[9305]]), results)[0] == K.AS_DOCUMENTED


def test_silent_wrong_matching_control_is_reported_as_fixed():
    c = case(differs_from="ctl")
    results = {"ctl": {"fetch": ok_fetch([[1756]])}}
    v, reasons = K.classify(c, OK_GEN, ok_fetch([[1756]]), results)
    assert v == K.CHANGED and "looks fixed" in reasons[0]


def test_a_broken_control_is_an_error_not_a_verdict():
    c = case(differs_from="ctl")
    results = {"ctl": {"fetch": err("QUERY_EXECUTION_FAILED")}}
    assert K.classify(c, OK_GEN, ok_fetch([[9305]]), results)[0] == K.ERROR


def test_same_as_ignores_row_order_and_float_noise():
    c = case(same_as="ctl")
    results = {"ctl": {"fetch": ok_fetch([["b", 2.0000000000001], ["a", 1]])}}
    assert K.classify(c, OK_GEN, ok_fetch([["a", 1], ["b", 2.0]]), results)[0] == K.AS_DOCUMENTED


# ---- fixed constructs --------------------------------------------------------------------

def test_fixed_construct_that_now_fails_is_changed():
    v, reasons = K.classify(case(), err("UNSUPPORTED_AGGREGATE"), None, {})
    assert v == K.CHANGED and "generate-sql now fails" in reasons[0]


def test_value_checks_use_tolerance_for_floats_only():
    c = case(values=((0, 0, 2.718281828459045), (0, 1, "A")))
    assert K.classify(c, OK_GEN, ok_fetch([[2.7182818284590455, "A"]]), {})[0] == K.AS_DOCUMENTED
    assert K.classify(c, OK_GEN, ok_fetch([[2.7182818284590455, "a"]]), {})[0] == K.CHANGED


def test_missing_value_is_changed_not_a_crash():
    c = case(values=((0, 0, 1),))
    assert K.classify(c, OK_GEN, ok_fetch([]), {})[0] == K.CHANGED


def test_sql_shape_checks_on_sql_only_case():
    c = case(expect=K.SQL_OK, sql_has=("limit 100000",), sql_lacks=("limit 200000",))
    assert K.classify(c, OK_GEN, None, {})[0] == K.AS_DOCUMENTED
    gen = dict(OK_GEN, executable_sql="SELECT x FROM t LIMIT 200000")
    assert K.classify(c, gen, None, {})[0] == K.CHANGED


def test_bespoke_check_problem_is_changed():
    c = case(check=lambda rows, _r: None if rows == [[1]] else "wrong")
    assert K.classify(c, OK_GEN, ok_fetch([[1]]), {})[0] == K.AS_DOCUMENTED
    assert K.classify(c, OK_GEN, ok_fetch([[2]]), {})[1] == ["wrong"]


def test_cli_failure_is_an_error():
    assert K.classify(case(), {"status": K.CLI_ERROR, "errors": []}, None, {})[0] == K.ERROR
    assert K.classify(case(), OK_GEN, {"status": K.CLI_ERROR, "errors": []}, {})[0] == K.ERROR


# ---- the shipped bespoke checks, against the rows they were written from ------------------

TOTALS = {"ctl_totals_by_sp": {"fetch": ok_fetch(
    [["Dwight Schrute", 1428], ["Jim Halpert", 1756], ["Phyllis Vance", 1645],
     ["Stanley Hudson", 3157], ["Andy Bernard", 1319]])}}


def by_id(i):
    return next(c for c in CASES if c.id == i)


def test_offset_check_wants_ranks_two_and_three():
    c = by_id("offset")
    good = ok_fetch([["Jim Halpert", 1756], ["Phyllis Vance", 1645]])
    bad = ok_fetch([["Stanley Hudson", 3157], ["Jim Halpert", 1756]])  # OFFSET ignored
    assert K.classify(c, OK_GEN, good, TOTALS)[0] == K.AS_DOCUMENTED
    assert K.classify(c, OK_GEN, bad, TOTALS)[0] == K.CHANGED


def test_lag_check_wants_offset_two_with_default():
    c = by_id("lag_optional_args")
    rows = [["Andy Bernard", 0], ["Dwight Schrute", 0], ["Jim Halpert", 1319],
            ["Phyllis Vance", 1428], ["Stanley Hudson", 1756]]
    assert K.classify(c, OK_GEN, ok_fetch(rows), TOTALS)[0] == K.AS_DOCUMENTED
    rows[2][1] = 1428  # offset 1 instead of 2
    assert K.classify(c, OK_GEN, ok_fetch(rows), TOTALS)[0] == K.CHANGED


def test_stddev_check_is_hand_computed_from_the_control():
    c = by_id("stddev_over_cte")
    assert K.classify(c, OK_GEN, ok_fetch([[744.7398874775005]]), TOTALS)[0] == K.AS_DOCUMENTED
    assert K.classify(c, OK_GEN, ok_fetch([[666.1]]), TOTALS)[0] == K.CHANGED


def test_round_check_compares_to_the_unrounded_control():
    c = by_id("round")
    results = {"ctl_avg_unrounded": {"fetch": ok_fetch([[23.22795]])}}
    assert K.classify(c, OK_GEN, ok_fetch([[23.23]]), results)[0] == K.AS_DOCUMENTED
    assert K.classify(c, OK_GEN, ok_fetch([[24.0]]), results)[0] == K.CHANGED  # multiple-of-N rounding


def test_day_of_year_check_decodes_epoch_seconds():
    c = by_id("day_in_year_number")
    good = ok_fetch([[1730073600, 302, 28]])  # 2024-10-28
    assert K.classify(c, OK_GEN, good, {})[0] == K.AS_DOCUMENTED
    assert K.classify(c, OK_GEN, ok_fetch([[1730073600, 301, 28]]), {})[0] == K.CHANGED


# ---- the lessons suite ---------------------------------------------------------------------

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("agentql_retest_run", pathlib.Path(__file__).resolve().parents[1] / "run.py")
RUN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RUN)


def _hit(name, author, guid="g"):
    return {"metadata_header": {"id": guid, "name": name, "authorName": author}}


def test_sample_model_is_picked_by_exact_name_and_system_author():
    hits = [_hit("(Sample) Retail - Apparel - XY", "someone", "copy1"),
            _hit("(Sample) Retail - Apparel", "someone", "copy2"),
            _hit("(Sample) Retail - Apparel", "system", "real")]
    assert RUN.pick_sample_model(hits) == ("real", None)


def test_sample_model_missing_or_ambiguous_is_a_problem_not_a_guess():
    assert RUN.pick_sample_model([_hit("(Sample) Retail - Apparel", "someone")])[0] is None
    two = [_hit("(Sample) Retail - Apparel", "system", "a"), _hit("(Sample) Retail - Apparel", "system", "b")]
    guid, problem = RUN.pick_sample_model(two)
    assert guid is None and "found 2" in problem


def test_lesson_cases_are_all_on_the_sample_model_and_name_a_lesson():
    lessons = [c for c in CASES if c.suite == "lessons"]
    assert lessons and all(c.model == "apparel" for c in lessons)
    assert all(c.control or c.row.startswith("📘 ") for c in lessons)
    assert all(c.suite == "limitations" for c in CASES if c.model != "apparel")


def test_lesson_guarded_by_ids_in_the_doc_all_exist():
    doc = (pathlib.Path(__file__).resolve().parents[3]
           / "agents/cli/ts-object-model-agentql-query/references/learning-path.md").read_text()
    import re
    cited = {i for line in doc.splitlines() if line.startswith("**Guarded by:**")
             for i in re.findall(r"`([a-z0-9_]+)`", line)}
    ids = {c.id for c in CASES}  # a lesson may cite a limitations case (3.4 needs Dunder Mifflin)
    assert cited, "learning-path.md cites no cases"
    assert cited <= ids, f"cited but not cases: {sorted(cited - ids)}"
    uncited = {c.id for c in CASES if c.suite == "lessons" and not c.control} - cited
    assert not uncited, f"lesson cases no lesson cites: {sorted(uncited)}"


AP = {"ctl_ap_total": {"fetch": ok_fetch([[100.0]])},
      "ctl_ap_by_region": {"fetch": ok_fetch([["West", 60.0], ["East", 40.0]])}}


def test_lesson_checks_against_controls():
    assert K.classify(by_id("l2_group_by_joins_one_dim"),
                      dict(OK_GEN, executable_sql="… join dim_retapp_stores on storeid …"),
                      ok_fetch([["West", 60.0], ["East", 40.0]]), AP)[0] == K.AS_DOCUMENTED
    assert K.classify(by_id("l2_filter_case_insensitive"),
                      dict(OK_GEN, executable_sql="… join … where lower(x) = 'west'"),
                      ok_fetch([[0.0]]), AP)[0] == K.CHANGED  # case-sensitive now: matched nothing
    rows = [["West", 1.0]] * 3
    assert K.classify(by_id("l2_bare_measure_row_level"), OK_GEN, ok_fetch(rows), AP)[0] == K.CHANGED


def test_latest_date_check_wants_int_epoch_near_today():
    import datetime as dt
    today = int(dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    c = by_id("l1_dates_are_epoch_seconds")
    assert K.classify(c, OK_GEN, ok_fetch([[today, 1.0]]), {})[0] == K.AS_DOCUMENTED
    assert K.classify(c, OK_GEN, ok_fetch([["2026-10-14", 1.0]]), {})[0] == K.CHANGED
    assert K.classify(c, OK_GEN, ok_fetch([[today - 30 * 86400, 1.0]]), {})[0] == K.CHANGED
