"""AgentQL Quest build: the encounters must keep matching the captured lesson SQL. No live calls."""
from __future__ import annotations

import copy
import json
import pathlib
import re
import sys

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import build as B  # noqa: E402

CASE = "l3_all_products_left_join"


@pytest.fixture(scope="module")
def capture():
    return B.parse_lesson_sql(B.LESSON_SQL.read_text(encoding="utf-8"))


@pytest.fixture
def doc():
    return yaml.safe_load(B.ENCOUNTERS.read_text(encoding="utf-8"))


def _errors(doc, capture):
    date, cases = capture
    return B.compile_quest(doc, date, cases)[1]


def _encounter(doc):
    return next(e for e in doc["encounters"] if e["case"] == CASE)


def test_committed_encounters_build_clean(doc, capture):
    data, errors = B.compile_quest(doc, *capture)
    assert errors == []
    assert data["captured"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["captured"])
    assert data["paths"]["dwarf"], "the dwarf path should have at least one dragon"


def test_main_check_passes_on_the_repo():
    assert B.main(["--check"]) == 0


def test_every_point_highlights_something_in_the_sql(doc, capture):
    data, _ = B.compile_quest(doc, *capture)
    for e in data["encounters"]:
        for p in e["points"]:
            assert p["sqlHl"] == "all" or p["sqlHl"], f"{e['case']}: a point lights up no SQL"


def test_who_answers_map_to_the_right_option(doc, capture):
    data, _ = B.compile_quest(doc, *capture)
    e = next(x for x in data["encounters"] if x["case"] == CASE)
    src = [p.get("answer") for p in _encounter(doc)["points"]]
    expected = {"model": 0, "thoughtspot": 0, "agentql": 1}  # option 2, the AI, is never right
    for p, answer in zip(e["points"], src):
        if answer:
            assert p["correct"] == expected[answer]


def test_sql_drift_fails_the_build(doc, capture):
    _encounter(doc)["points"][5]["sql"] = ["LIMIT 50000"]
    assert any("'LIMIT 50000' hits no line" in e for e in _errors(doc, capture))


def test_changed_agentql_fails_the_build(doc, capture):
    e = _encounter(doc)
    e["agentql"] = e["agentql"].replace("'West'", "'East'")
    assert any("agentql differs" in x for x in _errors(doc, capture))


def test_relayout_of_agentql_is_allowed(doc, capture):
    e = _encounter(doc)
    e["agentql"] = " ".join(e["agentql"].split())  # the same query, all on one line
    assert _errors(doc, capture) == []


def test_missing_and_rejected_cases_fail(doc, capture):
    date, cases = capture
    rejected = next(cid for cid, c in cases.items() if c["sql"] is None)
    first = _encounter(doc)
    doc["encounters"] = [dict(copy.deepcopy(first), case="no_such_case"), dict(copy.deepcopy(first), case=rejected)]
    errors = B.compile_quest(doc, date, cases)[1]
    assert any("no_such_case: not in lesson-sql.md" in e for e in errors)
    assert any(f"{rejected}: captured status was not SUCCESS" in e for e in errors)


def test_choice_needs_exactly_one_correct(doc, capture):
    choice = next(p for p in _encounter(doc)["points"] if p["kind"] == "choice")
    for o in choice["options"]:
        o["correct"] = True
    assert any("exactly one correct" in e for e in _errors(doc, capture))


def test_unknown_answer_path_and_kind_fail(doc, capture):
    e = _encounter(doc)
    e["points"][0]["answer"] = "ai"
    e["points"][1]["kind"] = "riddle"
    e["paths"] = ["dwarf", "orc"]
    errors = _errors(doc, capture)
    assert any("answer must be one of" in x for x in errors)
    assert any("kind must be 'who' or 'choice'" in x for x in errors)
    assert any("unknown path 'orc'" in x for x in errors)


def test_court_claims_need_a_boolean_truth(doc, capture):
    doc["court"][0]["truth"] = "false"
    assert any("court claim 1" in e for e in _errors(doc, capture))


def test_render_inlines_data_and_cannot_close_the_script_tag(doc, capture):
    data, _ = B.compile_quest(doc, *capture)
    data["court"][0]["why"] = "</script><script>alert(1)</script>"
    html = B.render(B.TEMPLATE.read_text(encoding="utf-8"), data)
    assert B.PLACEHOLDER not in html
    body = html.split('<script id="quest-data" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert json.loads(body)["court"][0]["why"] == "</script><script>alert(1)</script>"


def test_render_rejects_a_template_without_one_placeholder():
    with pytest.raises(ValueError):
        B.render("<html></html>", {})
