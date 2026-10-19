"""AgentQL Quest build: the encounters must keep matching the captured lesson SQL. No live calls."""
from __future__ import annotations

import copy
import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

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


def _recaptured(capture, old, new):
    """The real capture with one edit to lesson 3.6's generated SQL, as a recapture might make."""
    date, cases = capture
    cases = copy.deepcopy(cases)
    assert old in cases[CASE]["sql"], old
    cases[CASE]["sql"] = cases[CASE]["sql"].replace(old, new)
    return date, cases


def _built_html(doc, capture):
    data, errors = B.compile_quest(doc, *capture)
    assert errors == []
    return B.render(B.TEMPLATE.read_text(encoding="utf-8"), data, B.font_faces())


# ---- the committed content -------------------------------------------------------------------

def test_committed_encounters_build_clean(doc, capture):
    data, errors = B.compile_quest(doc, *capture)
    assert errors == []
    assert data["captured"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["captured"])
    assert data["paths"]["dwarf"], "the dwarf path should have at least one dragon"


def test_main_check_passes_on_the_repo():
    assert B.main(["--check"]) == 0


def test_every_who_point_highlights_the_sql_it_asks_about(doc, capture):
    data, _ = B.compile_quest(doc, *capture)
    src = {e["case"]: e for e in doc["encounters"]}
    for e in data["encounters"]:
        for p, raw in zip(e["points"], src[e["case"]]["points"]):
            if raw["kind"] == "who":
                assert p["sqlHl"] == "all" or p["sqlHl"], f"{e['case']}: a who point lights up no SQL"


def test_who_answers_map_to_the_right_option(doc, capture):
    data, _ = B.compile_quest(doc, *capture)
    e = next(x for x in data["encounters"] if x["case"] == CASE)
    expected = {"model": 0, "thoughtspot": 0, "agentql": 1}  # option 2, the AI, is never right
    for p, raw in zip(e["points"], _encounter(doc)["points"]):
        if raw.get("answer"):
            assert p["correct"] == expected[raw["answer"]]


# ---- drift: recaptures that would make a lesson false must fail ----------------------------

@pytest.mark.parametrize("old,new,why", [
    ("LIMIT 100000", "LIMIT 1000000", "row cap changed"),
    ('      JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_2"',
     '      LEFT OUTER JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_2"', "Model join became outer"),
    ('    FROM "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_1"\n',
     '    FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_9"\n'
     '      JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_1" ON "ta_9"."PRODUCTID" = "ta_1"."PRODUCTID"\n',
     "pruning turned off"),
    ("WHERE LOWER(\"ta_4\".\"REGION\") = 'west'", "WHERE \"ta_4\".\"REGION\" = 'West'", "filter no longer case-insensitive"),
])
def test_a_recapture_that_falsifies_a_lesson_fails(doc, capture, old, new, why):
    assert _errors(doc, _recaptured(capture, old, new)), f"{why}: the build should have failed"


def test_pruning_held_count_is_what_catches_an_extra_fact_join(doc, capture):
    # The FROM line survives in this variant, so only sql_count can see the extra fact read.
    cap = _recaptured(capture, '  "qt_1" AS (', '  "qt_x" AS (SELECT 1 FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES"),\n  "qt_1" AS (')
    assert any("expected '\"FACT_RETAPP_SALES\"' 1 time(s)" in e for e in _errors(doc, cap))


def test_changed_agentql_fails_the_build(doc, capture):
    e = _encounter(doc)
    e["agentql"] = e["agentql"].replace("'West'", "'East'")
    assert any("agentql differs" in x for x in _errors(doc, capture))


def test_relayout_of_agentql_is_allowed(doc, capture):
    e = _encounter(doc)
    e["agentql"] = " ".join(e["agentql"].split())  # the same query, all on one line
    assert _errors(doc, capture) == []


@pytest.mark.parametrize("a,b", [
    ('"(Sample) Retail"', '"(Sample)Retail"'),
    ("x IN ('North', 'West')", "x IN ('North','West')"),
    ("'a  b'", "'a b'"),
    ("WHERE x = 'West'", "WHERE x = 'west'"),
])
def test_norm_only_forgives_layout(a, b):
    assert B._norm(a) != B._norm(b)


def test_norm_forgives_line_breaks_inside_brackets():
    assert B._norm("WITH a AS (\n  SELECT x\n  FROM t\n), b AS (SELECT y)") == B._norm("WITH a AS (SELECT x FROM t), b AS (SELECT y)")


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


# ---- the rendered page -----------------------------------------------------------------------

def test_inlined_data_has_no_raw_markup_and_round_trips(doc, capture):
    data, _ = B.compile_quest(doc, *capture)
    data["court"][0]["why"] = "<!--<script></script>-->&amp;"
    html = B.render(B.TEMPLATE.read_text(encoding="utf-8"), data, "")
    body = html.split('<script id="quest-data" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert not set(body) & set("<>&"), "the data block must contain no raw <, > or &"
    assert json.loads(body)["court"][0]["why"] == "<!--<script></script>-->&amp;"


def test_page_makes_no_outside_requests(doc, capture):
    html = _built_html(doc, capture)
    assert "fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html
    # Links are fine (the course link); anything the browser would fetch on load is not.
    assert not re.search(r'<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)="https?://', html)
    assert not re.search(r'url\(\s*["\']?https?://', html)
    assert html.count("url(data:font/woff2;base64,") == len(B.FONTS)


def test_highlight_rule_outranks_the_agentql_text_colour():
    # B1 from review: `.scroll .on` lost to `.scroll .agent` (same specificity, declared later),
    # painting highlighted AgentQL amber on amber. The highlight needs the extra class.
    css = B.TEMPLATE.read_text(encoding="utf-8")
    assert re.search(r"\.scroll \.ln\.on \{[^}]*color:", css)
    assert not re.search(r"\.scroll \.on \{", css)


def test_render_rejects_a_template_without_one_placeholder():
    with pytest.raises(ValueError):
        B.render("<html></html>", {})


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_every_path_plays_through_headlessly(doc, capture, tmp_path):
    page = tmp_path / "index.html"
    page.write_text(_built_html(doc, capture), encoding="utf-8")
    r = subprocess.run(["node", str(HERE / "play_quest.js"), str(page)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ---- the published site ----------------------------------------------------------------------

def _site_build_script():
    wf = yaml.safe_load((B.ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["build"]["steps"]
    return next(s["run"] for s in steps if s.get("name") == "Build the site")


def test_pages_workflow_builds_home_page_and_game_in_its_folder(tmp_path):
    # Run the workflow's own build commands (minus the pip install), writing into tmp_path.
    script = "\n".join(line for line in _site_build_script().splitlines() if not line.strip().startswith("pip "))
    site = tmp_path / "_site"
    r = subprocess.run(["bash", "-euc", script.replace("_site", str(site))], cwd=B.ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    home, game = site / "index.html", site / "agentql-quest" / "index.html"
    assert home.is_file() and game.is_file()
    assert "<title>ThoughtSpot Agent Skills</title>" in home.read_text(encoding="utf-8")
    assert "<title>AgentQL Quest</title>" in game.read_text(encoding="utf-8")


def test_home_page_lists_the_game_and_loads_nothing_from_outside():
    home = (B.ROOT / ".github/pages/index.html").read_text(encoding="utf-8")
    assert 'href="agentql-quest/"' in home
    assert not re.search(r'<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)="https?://', home)


def test_pages_workflow_deploys_only_from_main():
    wf = yaml.safe_load((B.ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8"))
    for job in ("build", "deploy"):
        assert wf["jobs"][job].get("if") == "github.ref == 'refs/heads/main'", job
    triggers = wf[True] if True in wf else wf["on"]  # PyYAML reads the bare key `on` as True
    assert "pull_request" not in triggers and "pull_request_target" not in triggers
