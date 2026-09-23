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

from ts_cli.audit.checks_human import (
    ALL_CHECKS, check_h2, check_h5, check_h6, check_h7, check_h8, check_h9,
)
from ts_cli.audit.context import make_context

# GUIDs, in the shapes the v2 API actually returns them.
MODEL_GUID = "0a1b2c3d-1111-4a5b-8c9d-000000000001"   # the Model TML's root `guid`
TABLE_FQN = "0a1b2c3d-2222-4a5b-8c9d-000000000002"    # model_tables[].fqn — a *Table* guid
OTHER_TABLE_FQN = "0a1b2c3d-2222-4a5b-8c9d-000000000099"
SET_GUID = "0a1b2c3d-3333-4a5b-8c9d-000000000003"
ANSWER_1 = "0a1b2c3d-4444-4a5b-8c9d-000000000004"
ANSWER_2 = "0a1b2c3d-4444-4a5b-8c9d-000000000005"


def _model(guid=MODEL_GUID, name="Retail Sales", columns=None, formulas=None,
           model_tables=None):
    """A Model TML per agents/shared/schemas/thoughtspot-model-tml.md."""
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": model_tables if model_tables is not None else [
                {"name": "SALES", "fqn": TABLE_FQN},
            ],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": {},
        },
    }


def _col(name, description=None):
    col = {
        "name": name,
        "column_id": f"SALES::{name.upper().replace(' ', '_')}",
        "properties": {"column_type": "ATTRIBUTE"},
    }
    if description is not None:
        col["description"] = description
    return col


def _formula(name, expr):
    return {"id": f"formula_{name}", "name": name, "expr": expr,
            "was_auto_generated": False}


def _answer(guid, name, source_fqn=MODEL_GUID, source_name="Retail Sales",
            formulas=None, tables=None):
    """An Answer TML per agents/shared/schemas/thoughtspot-answer-tml.md:24-27.

    `tables[].fqn` is the GUID of the *data source* — the Model or Worksheet the
    answer was built on, or a Table when it was built straight off one.
    """
    return {
        "guid": guid,
        "answer": {
            "name": name,
            "display_mode": "TABLE_MODE",
            "tables": tables if tables is not None else [
                {"id": source_name, "name": source_name, "fqn": source_fqn},
            ],
            "search_query": "[Revenue] by [Region]",
            "answer_columns": [{"name": "Revenue"}, {"name": "Region"}],
            "formulas": formulas or [],
        },
    }


def _dep(guid, name, dep_type, source_guid):
    """One row as `_normalize_dependents_response` (metadata.py:363-403) emits it."""
    bucket = {"SET": "COHORT", "ANSWER": "QUESTION_ANSWER_BOOK",
              "LIVEBOARD": "PINBOARD_ANSWER_BOOK"}[dep_type]
    return {"source_guid": source_guid, "guid": guid, "name": name,
            "type": dep_type, "raw_bucket": bucket,
            "author_id": "u-1", "author_display_name": "Dana Ruiz"}


# --------------------------------------------------------------------------- H2
# checks_human.py:69-94 — description quality. Three branches, all reachable.

GOOD_DESC = "Net revenue recognised per order line, in USD, excluding tax."


def test_h2_trips_on_a_description_under_20_chars():
    ctx = make_context(models=[_model(columns=[
        _col("Revenue", "Revenue."),          # 8 chars -> the <20 branch, :80
        _col("Region", GOOD_DESC),
    ])])
    findings = check_h2(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "H2"
    assert findings[0].severity == "LOW"
    assert "too short (8 chars)" in findings[0].detail
    assert findings[0].metric == 1


def test_h2_trips_on_a_description_over_400_chars():
    long_desc = "Gross merchandise value for the order line. " * 12   # 527 stripped
    ctx = make_context(models=[_model(columns=[_col("GMV", long_desc)])])
    findings = check_h2(ctx)
    assert len(findings) == 1
    assert "too long (527 chars)" in findings[0].detail


def test_h2_trips_on_boilerplate_prose_of_acceptable_length():
    # 49 chars, so it clears both length branches and reaches _BOILERPLATE (:84).
    ctx = make_context(models=[_model(columns=[
        _col("Revenue", "The total revenue recognised for this order line."),
    ])])
    findings = check_h2(ctx)
    assert len(findings) == 1
    assert "boilerplate" in findings[0].detail


def test_h2_counts_every_offending_column_into_one_per_model_finding():
    ctx = make_context(models=[_model(columns=[
        _col("Revenue", "Revenue."),
        _col("Cost", "Cost."),
        _col("Region", GOOD_DESC),
    ])])
    findings = check_h2(ctx)
    assert len(findings) == 1, "H2 emits one finding per model, not per column"
    assert findings[0].metric == 2
    assert findings[0].object_guid == MODEL_GUID


def test_h2_clean_model_returns_nothing():
    ctx = make_context(models=[_model(columns=[
        _col("Revenue", GOOD_DESC),
        _col("Region", "Sales region the store is assigned to, per the FY24 map."),
        _col("Order Date"),      # no description at all — that is A1's remit, not H2's
        _col("Store", ""),       # empty string is skipped by the `if not desc` guard
    ])])
    assert check_h2(ctx) == []


# --------------------------------------------------------------------------- H5
# checks_human.py:154-168 — orphan sets.

def test_h5_trips_on_a_set_with_no_dependents_of_its_own():
    ctx = make_context(
        models=[_model()],
        dependents={MODEL_GUID: [_dep(SET_GUID, "FY24 Top Accounts", "SET", MODEL_GUID)],
                    SET_GUID: []},   # the set WAS looked up, and has no consumers
    )
    findings = check_h5(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "H5"
    assert findings[0].severity == "MEDIUM"
    assert findings[0].object_guid == SET_GUID
    assert "FY24 Top Accounts" in findings[0].detail


def test_h5_returns_nothing_when_the_set_has_a_consumer():
    ctx = make_context(models=[_model()], dependents={
        MODEL_GUID: [_dep(SET_GUID, "FY24 Top Accounts", "SET", MODEL_GUID)],
        SET_GUID: [_dep(ANSWER_1, "Top Accounts QBR", "ANSWER", SET_GUID)],
    })
    assert check_h5(ctx) == []


def test_h5_ignores_dependents_that_are_not_sets():
    ctx = make_context(models=[_model()], dependents={
        MODEL_GUID: [
            _dep(ANSWER_1, "Revenue by Region", "ANSWER", MODEL_GUID),
            _dep(ANSWER_2, "Exec Liveboard", "LIVEBOARD", MODEL_GUID),
        ],
    })
    assert check_h5(ctx) == []


# NOTE: the H5 'cannot say no' characterization test was removed when BL-302
# was fixed — absence of a set guid now means 'not looked up', and the check is
# silent. See tools/ts-cli/tests/test_dead_guards.py.

def test_h5_labels_a_set_as_object_type_table():
    """Pinned, not fixed: the object_type is wrong (checks_human.py:164)."""
    ctx = make_context(models=[_model()], dependents={
        MODEL_GUID: [_dep(SET_GUID, "FY24 Top Accounts", "SET", MODEL_GUID)],
        SET_GUID: []})
    assert check_h5(ctx)[0].object_type == "set"


# --------------------------------------------------------------------------- H6
# checks_human.py:171-182 — a deliberate stub (`return []` at :182), not a defect.

def _rich_context():
    """A context fat enough to trip several other human checks."""
    return make_context(
        models=[_model(columns=[_col("col1", "Bad.")],
                       formulas=[_formula("Margin", "[Revenue] - [Cost]")])],
        tables={TABLE_FQN: {"guid": TABLE_FQN, "table": {"name": "SALES", "columns": []}}},
        dependents={MODEL_GUID: [_dep(SET_GUID, "FY24 Top Accounts", "SET", MODEL_GUID)]},
        answers=[_answer(ANSWER_1, "West QBR",
                         formulas=[_formula("Margin", "[Revenue] - [Cost]")])],
        model_guids=[MODEL_GUID],
    )


def test_h6_is_a_deliberate_stub_and_returns_nothing_by_design():
    assert check_h6(_rich_context()) == []
    assert check_h6 not in ALL_CHECKS, (
        "H6 is deliberately unregistered — see DEFERRED in test_checks_registry.py:95-100"
    )


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
    assert check_h7(make_context(models=[_model()], answers=[])) == []


def test_h7_returns_nothing_when_the_source_reference_carries_no_fqn():
    ctx = make_context(models=[_model()], answers=[
        _answer(ANSWER_1, "Revenue by Region",
                tables=[{"id": "Retail Sales", "name": "Retail Sales"}]),
    ])
    assert check_h7(ctx) == []

# --------------------------------------------------------------------------- H8/H9
# checks_human.py:209-233 and :236-255 — near-clones over the same loop.

MARGIN = "( [Revenue] - [Cost] ) / [Revenue]"
MARGIN_SPACED = "( [Revenue] - [Cost] )   /  [Revenue]"     # same after _normalize_expr
NEW_RATE = "sum([Returns]) / sum([Orders])"


def test_h8_trips_when_one_off_model_formula_is_repeated_across_two_answers():
    ctx = make_context(
        models=[_model(formulas=[_formula("Revenue LY", "sum([Revenue])")])],
        answers=[
            _answer(ANSWER_1, "West QBR", formulas=[_formula("Margin", MARGIN)]),
            _answer(ANSWER_2, "East QBR", formulas=[_formula("Margin", MARGIN_SPACED)]),
        ],
    )
    findings = check_h8(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "H8"
    assert findings[0].severity == "HIGH"
    assert findings[0].metric == 2
    assert "West QBR" in findings[0].detail and "East QBR" in findings[0].detail


def test_h8_returns_nothing_when_only_one_answer_uses_the_formula():
    ctx = make_context(
        models=[_model(formulas=[_formula("Revenue LY", "sum([Revenue])")])],
        answers=[_answer(ANSWER_1, "West QBR", formulas=[_formula("Margin", MARGIN)])],
    )
    assert check_h8(ctx) == []


def test_h8_returns_nothing_when_the_formula_is_already_on_the_model():
    ctx = make_context(
        models=[_model(formulas=[_formula("Margin", MARGIN)])],
        answers=[
            _answer(ANSWER_1, "West QBR", formulas=[_formula("Margin", MARGIN)]),
            _answer(ANSWER_2, "East QBR", formulas=[_formula("Margin", MARGIN)]),
        ],
    )
    assert check_h8(ctx) == []


def test_h8_returns_nothing_without_answers():
    ctx = make_context(models=[_model(formulas=[_formula("Margin", MARGIN)])])
    assert check_h8(ctx) == []


def test_h8_names_the_object_by_a_count_rather_than_a_name():
    """Pinned, not fixed: object_name is prose and object_guid is blank (:227-229).

    Nothing in the report can link an H8 finding back to an object.
    """
    ctx = make_context(models=[_model()], answers=[
        _answer(ANSWER_1, "West QBR", formulas=[_formula("Margin", MARGIN)]),
        _answer(ANSWER_2, "East QBR", formulas=[_formula("Margin", MARGIN)]),
    ])
    finding = check_h8(ctx)[0]
    assert finding.object_name == "shared in 2 answers"
    assert finding.object_guid == ""


def test_h9_trips_when_an_answer_formula_duplicates_a_model_formula():
    ctx = make_context(
        models=[_model(formulas=[_formula("Margin", MARGIN)])],
        answers=[_answer(ANSWER_1, "West QBR",
                         formulas=[_formula("Margin %", MARGIN_SPACED)])],
    )
    findings = check_h9(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "H9"
    assert findings[0].severity == "LOW"
    assert findings[0].object_guid == ANSWER_1
    assert "'Margin %' duplicates model formula 'Margin'" in findings[0].detail


def test_h9_returns_nothing_when_the_answer_formula_is_new():
    ctx = make_context(
        models=[_model(formulas=[_formula("Margin", MARGIN)])],
        answers=[_answer(ANSWER_1, "West QBR",
                         formulas=[_formula("Return Rate", NEW_RATE)])],
    )
    assert check_h9(ctx) == []


def test_h9_returns_nothing_without_answers():
    ctx = make_context(models=[_model(formulas=[_formula("Margin", MARGIN)])])
    assert check_h9(ctx) == []


def test_h8_and_h9_are_complementary_halves_of_one_scan():
    """Near-clones: the same nested loop, with inverse membership tests.

    checks_human.py:209-233 and :236-255 differ only in `not in` vs `in` against
    the same normalized-model-formula set, and in what they build from the hit.
    One expression can never trip both, so they are cheaper as one pass.
    """
    already_on_model = make_context(
        models=[_model(formulas=[_formula("Margin", MARGIN)])],
        answers=[_answer(ANSWER_1, "West QBR", formulas=[_formula("Margin", MARGIN)]),
                 _answer(ANSWER_2, "East QBR", formulas=[_formula("Margin", MARGIN)])],
    )
    assert check_h8(already_on_model) == []
    assert len(check_h9(already_on_model)) == 2

    not_on_model = make_context(
        models=[_model(formulas=[_formula("Revenue LY", "sum([Revenue])")])],
        answers=[_answer(ANSWER_1, "West QBR", formulas=[_formula("Margin", MARGIN)]),
                 _answer(ANSWER_2, "East QBR", formulas=[_formula("Margin", MARGIN)])],
    )
    assert len(check_h8(not_on_model)) == 1
    assert check_h9(not_on_model) == []

# NOTE: the H7/P17 defect-characterization tests that lived here were removed
# when BL-300/BL-301 were fixed — they asserted the broken behaviour by design
# and their names encoded it. The corrected behaviour is covered by
# tools/ts-cli/tests/test_unreachable_checks.py.
