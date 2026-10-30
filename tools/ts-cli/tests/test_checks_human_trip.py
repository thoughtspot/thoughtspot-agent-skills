"""H2 / H5 / H6 / H7 / H8 / H9 — the human-angle checks nothing ever called.

2026-09-22 audit finding 6.1: 27 of 51 checks are *imported* by a test and never
*invoked* by one. `test_checks_human.py:2-3` imports all ten human checks and
calls four (H1, H3, H4, H10). An import satisfies a coverage grep and exercises
nothing — which is how `check_p6`/`check_d2` shipped structurally unable to
return a finding and stayed that way for months (PR #528,
`test_checks_varchar_join_keys.py`).

Every test here either trips its check on a realistic TML shape, or pins the
behaviour of one that is *reachable but wrong*. Nothing below asserts a desired
behaviour that would need a check edited to make it pass: where H5 and H7 are
broken, the test asserts what the code does today and its name says so.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import audit_rule_fixtures as fx
from audit_run_rule import active_rule_ids, catalog, run_rule

# The contexts are named builders in audit_rule_fixtures (human.py), whose legacy
# answers test_audit_pinned_findings.py pins. The `checks_human.py:N` references below
# are to the legacy module (deleted when the rule catalog replaced them), which the H catalog rules reproduce.
MODEL_GUID, SET_GUID, ANSWER_1 = fx.HUMAN_MODEL_GUID, fx.HUMAN_SET_GUID, fx.HUMAN_ANSWER_1


# --------------------------------------------------------------------------- H2
# checks_human.py:69-94 — description quality. Three branches, all reachable.

def test_h2_trips_on_a_description_under_20_chars():
    findings = run_rule(fx.human_description_short(), "H2")   # "Revenue." -> the <20 branch
    assert len(findings) == 1
    assert findings[0].check_id == "H2"
    assert findings[0].severity == "LOW"
    assert "too short (8 chars)" in findings[0].detail
    assert findings[0].metric == 1


def test_h2_trips_on_a_description_over_400_chars():
    findings = run_rule(fx.human_description_long(), "H2")   # 527 chars stripped
    assert len(findings) == 1
    assert "too long (527 chars)" in findings[0].detail


def test_h2_no_longer_flags_an_ordinary_the_opening():
    """"The total revenue recognised for this order line." — 49 characters, clear of
    both length branches — was "boilerplate" until 2026-10, when "The " and "A " were
    dropped from the pattern (4,772 of 4,841 flagged descriptions on the SE demo
    snapshot)."""
    assert run_rule(fx.human_description_boilerplate(), "H2") == []


def test_h2_counts_every_offending_column_into_one_per_model_finding():
    findings = run_rule(fx.human_description_two_short(), "H2")
    assert len(findings) == 1, "H2 emits one finding per model, not per column"
    assert findings[0].metric == 2
    assert findings[0].object_guid == MODEL_GUID


def test_h2_clean_model_returns_nothing():
    # A column with no description is A1's remit; an empty one is skipped.
    assert run_rule(fx.human_description_clean(), "H2") == []


# --------------------------------------------------------------------------- H5
# checks_human.py:154-168 — orphan sets.

def test_h5_trips_on_a_set_with_no_dependents_of_its_own():
    findings = run_rule(fx.human_set_without_consumers(), "H5")   # looked up, no consumers
    assert len(findings) == 1
    assert findings[0].check_id == "H5"
    assert findings[0].severity == "MEDIUM"
    assert findings[0].object_guid == SET_GUID
    assert "FY24 Top Accounts" in findings[0].detail


def test_h5_returns_nothing_when_the_set_has_a_consumer():
    assert run_rule(fx.human_set_with_consumer(), "H5") == []


def test_h5_ignores_dependents_that_are_not_sets():
    assert run_rule(fx.human_dependents_not_sets(), "H5") == []


# NOTE: the H5 'cannot say no' characterization test was removed when BL-302
# was fixed — absence of a set guid now means 'not looked up', and the check is
# silent. See tools/ts-cli/tests/test_dead_guards.py.

def test_h5_labels_a_set_as_object_type_table():
    """Pinned, not fixed: the object_type is wrong (checks_human.py:164)."""
    assert run_rule(fx.human_set_without_consumers(), "H5")[0].object_type == "set"


# --------------------------------------------------------------------------- H6
# A deliberate stub, not a defect: the legacy check_h6 returned [] and was left out of
# ALL_CHECKS; the catalog keeps the id as a retired rule with no logic (rules/human.yaml).

def test_h6_is_a_deliberate_stub_and_returns_nothing_by_design():
    assert catalog().rules["H6"].status == "retired", (
        "H6 is deliberately retired (rules/human.yaml) — see test_every_inactive_rule_is_retired_on_purpose_and_listed"
    )
    assert "H6" not in active_rule_ids("H")
    assert run_rule(fx.human_rich_context(), "H6") == []


def test_h6_deferral_is_declared_in_the_check_catalog():
    """The third independent piece of evidence that the stub is intentional."""
    catalog = (Path(__file__).resolve().parents[3]
               / "agents/cli/ts-audit/references/check-catalog.md")
    if not catalog.exists():
        pytest.skip("check-catalog.md not present in this checkout")
    rows = [ln for ln in catalog.read_text().splitlines() if ln.startswith("| H6 ")]
    assert rows, "H6 must carry a catalog row saying it is deferred"
    assert "deferred" in rows[0].lower()


# --------------------------------------------------------------------------- H7
# checks_human.py:186-206 — "answer bypasses the model layer".

def test_h7_returns_nothing_for_a_context_with_no_answers():
    assert run_rule(fx.human_no_answers(), "H7") == []


def test_h7_returns_nothing_when_the_source_reference_carries_no_fqn():
    assert run_rule(fx.human_answer_source_without_fqn(), "H7") == []

# --------------------------------------------------------------------------- H8/H9
# checks_human.py:209-233 and :236-255 — near-clones over the same loop.

def test_h8_trips_when_one_off_model_formula_is_repeated_across_two_answers():
    findings = run_rule(fx.human_formula_in_two_answers(), "H8")   # one spaced differently
    assert len(findings) == 1
    assert findings[0].check_id == "H8"
    assert findings[0].severity == "HIGH"
    assert findings[0].metric == 2
    assert "West QBR" in findings[0].detail and "East QBR" in findings[0].detail


def test_h8_returns_nothing_when_only_one_answer_uses_the_formula():
    assert run_rule(fx.human_formula_in_one_answer(), "H8") == []


def test_h8_returns_nothing_when_the_formula_is_already_on_the_model():
    assert run_rule(fx.human_formula_on_model_and_two_answers(), "H8") == []


def test_h8_returns_nothing_without_answers():
    assert run_rule(fx.human_model_formula_without_answers(), "H8") == []


def test_h8_names_the_object_by_a_count_rather_than_a_name():
    """Pinned, not fixed: object_name is prose and object_guid is blank (:227-229).

    Nothing in the report can link an H8 finding back to an object.
    """
    finding = run_rule(fx.human_formula_in_two_answers_model_without_formulas(), "H8")[0]
    assert finding.object_name == "shared in 2 answers"
    assert finding.object_guid == ""


def test_h9_trips_when_an_answer_formula_duplicates_a_model_formula():
    findings = run_rule(fx.human_answer_formula_duplicates_model(), "H9")
    assert len(findings) == 1
    assert findings[0].check_id == "H9"
    assert findings[0].severity == "LOW"
    assert findings[0].object_guid == ANSWER_1
    assert "'Margin %' duplicates model formula 'Margin'" in findings[0].detail


def test_h9_returns_nothing_when_the_answer_formula_is_new():
    assert run_rule(fx.human_answer_formula_new(), "H9") == []


def test_h9_returns_nothing_without_answers():
    assert run_rule(fx.human_model_formula_without_answers(), "H9") == []


def test_h8_and_h9_are_complementary_halves_of_one_scan():
    """Near-clones: the same nested loop, with inverse membership tests.

    checks_human.py:209-233 and :236-255 differ only in `not in` vs `in` against
    the same normalized-model-formula set, and in what they build from the hit.
    One expression can never trip both, so they are cheaper as one pass.
    """
    already_on_model = fx.human_formula_on_model_and_two_answers()
    assert run_rule(already_on_model, "H8") == []
    assert len(run_rule(already_on_model, "H9")) == 2

    not_on_model = fx.human_formula_in_two_answers_same_text()
    assert len(run_rule(not_on_model, "H8")) == 1
    assert run_rule(not_on_model, "H9") == []

# NOTE: the H7/P17 defect-characterization tests that lived here were removed
# when BL-300/BL-301 were fixed — they asserted the broken behaviour by design
# and their names encoded it. The corrected behaviour is covered by
# tools/ts-cli/tests/test_unreachable_checks.py.
