"""AgentQL Quest build: the encounters must keep matching the captured lesson SQL. No live calls."""
from __future__ import annotations

import copy
import json
import os
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
MODEL = "(Sample) Retail - Apparel"  # the Model lesson-sql.md's header names


@pytest.fixture(scope="module")
def capture():
    return B.parse_lesson_sql(B.LESSON_SQL.read_text(encoding="utf-8"))


@pytest.fixture
def doc():
    return yaml.safe_load(B.ENCOUNTERS.read_text(encoding="utf-8"))


def _errors(doc, capture):
    date, cases = capture
    return B.compile_quest(doc, date, cases, MODEL)[1]


def _encounter(doc):
    return next(e for e in doc["encounters"] if e["case"] == CASE)


def _recaptured(capture, old, new, case=CASE, count=-1):
    """The real capture with one edit to a lesson's generated SQL, as a recapture might make."""
    date, cases = capture
    cases = copy.deepcopy(cases)
    assert old in cases[case]["sql"], old
    cases[case]["sql"] = cases[case]["sql"].replace(old, new, count)
    return date, cases


def _built_encounters(data):
    return [e for r in data["realms"] for e in r["encounters"]]


def _built_html(doc, capture):
    data, errors = B.compile_quest(doc, *capture, MODEL)
    assert errors == []
    return B.render(B.TEMPLATE.read_text(encoding="utf-8"), data, B.font_faces())


# ---- the committed content -------------------------------------------------------------------

def test_committed_encounters_build_clean(doc, capture):
    data, errors = B.compile_quest(doc, *capture, MODEL)
    assert errors == []
    assert data["captured"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["captured"])
    first = data["realms"][0]
    assert first["id"] == "law" and first["module"] == 0 and first["halls"], "everyone starts in Law (Module 0)"
    assert any(r["encounters"] for r in data["realms"]), "at least one realm should have a dragon"


def test_main_check_passes_on_the_repo():
    assert B.main(["--check"]) == 0


def test_every_who_point_highlights_the_sql_it_asks_about(doc, capture):
    data, _ = B.compile_quest(doc, *capture, MODEL)
    src = {e["case"]: e for e in doc["encounters"]}
    for e in _built_encounters(data):
        for p, raw in zip(e["points"], src[e["case"]]["points"]):
            if raw["kind"] == "who":
                assert p["sqlHl"] == "all" or p["sqlHl"], f"{e['case']}: a who point lights up no SQL"


def test_who_answers_map_to_the_right_option(doc, capture):
    data, _ = B.compile_quest(doc, *capture, MODEL)
    e = next(x for x in _built_encounters(data) if x["case"] == CASE)
    expected = {"model": 0, "thoughtspot": 0, "agentql": 1}  # option 2, the AI, is never right
    for p, raw in zip(e["points"], _encounter(doc)["points"]):
        if raw.get("answer"):
            assert p["correct"] == expected[raw["answer"]]


# ---- drift: recaptures that would make a lesson false must fail ----------------------------

@pytest.mark.parametrize("case,old,new,why", [
    ("l5_cte_two_step", "LIMIT 100000", "LIMIT 1000000", "row cap changed (the Forests teach it)"),
    (CASE, '      JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_2"',
     '      LEFT OUTER JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_2"', "the Model's join turned outer (the Lake)"),
    ("l2_filter_case_insensitive", "WHERE LOWER(\"ta_2\".\"REGION\") = 'west'", "WHERE \"ta_2\".\"REGION\" = 'West'",
     "filter no longer case-insensitive (the Mines)"),
    ("l5_cte_two_step", '"ta_1"."STORENAME" "ca_1",', '"ta_1"."STORE_NAME" "ca_1",', "physical column renamed (the Forests)"),
])
def test_a_recapture_that_falsifies_a_lesson_fails(doc, capture, case, old, new, why):
    assert _errors(doc, _recaptured(capture, old, new, case)), f"{why}: the build should have failed"


def test_a_ranking_that_loses_its_null_guard_fails(doc, capture):
    # The Isles teach that the rank orders by the null-safe sum; the line still exists once, so
    # only sql_count notices the guard inside the ranking has gone.
    cap = _recaptured(capture, '    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")\n    ELSE 0\n  END desc)',
                      '    sum("ta_2"."SALES") desc)', "l5_rank")
    assert any("found 1" in e for e in _errors(doc, cap))


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
    errors = B.compile_quest(doc, date, cases, MODEL)[1]
    assert any("no_such_case: not in lesson-sql.md" in e for e in errors)
    assert any(f"{rejected}: captured status was not SUCCESS" in e for e in errors)


def test_choice_needs_exactly_one_correct(doc, capture):
    choice = next(p for p in _encounter(doc)["points"] if p["kind"] == "choice")
    for o in choice["options"]:
        o["correct"] = True
    assert any("exactly one correct" in e for e in _errors(doc, capture))


def test_unknown_answer_kind_and_route_fail(doc, capture):
    e = _encounter(doc)
    e["points"][0]["answer"] = "ai"
    e["points"][1]["kind"] = "riddle"
    doc["routes"][0]["path"].append("the_far_marsh")
    errors = _errors(doc, capture)
    assert any("answer must be one of" in x for x in errors)
    assert any("kind must be 'who' or 'choice'" in x for x in errors)
    assert any("unknown: ['the_far_marsh']" in x for x in errors)


def _law(doc):
    return next(r for r in doc["realms"] if r["id"] == "law")


def _law_trials(doc):
    return [t for h in _law(doc)["halls"] for t in h["trials"]]


def test_trial_claims_need_a_boolean_truth(doc, capture):
    next(t for t in _law_trials(doc) if t["kind"] == "claim")["truth"] = "false"
    assert any("realm law hall" in e and "true/false truth" in e for e in _errors(doc, capture))


def test_a_petition_must_go_to_a_known_engine(doc, capture):
    next(t for t in _law_trials(doc) if t["kind"] == "route")["answer"] = "spellbook"
    assert any("answer must be one of ['keyword', 'agentql', 'code_complete']" in e for e in _errors(doc, capture))


def test_trial_answers_compile_to_the_right_option(doc, capture):
    data, _ = B.compile_quest(doc, *capture, MODEL)
    law = [t for h in data["realms"][0]["halls"] for t in h["trials"]]
    for raw, t in zip(_law_trials(doc), law):
        if raw["kind"] == "claim":
            assert t["correct"] == (0 if raw["truth"] else 1)
        else:
            assert t["options"][t["correct"]].endswith(doc["engines"][raw["answer"]])


# ---- realm rules -----------------------------------------------------------------------------

def _realm(doc, rid):
    return next(r for r in doc["realms"] if r["id"] == rid)


def test_a_sealed_realm_cannot_hold_content(doc, capture):
    _realm(doc, "isles")["sealed"] = True
    assert any("a sealed realm has no trials or encounters" in e for e in _errors(doc, capture))


def test_an_open_realm_needs_content(doc, capture):
    _realm(doc, "lake")["encounters"] = []
    errors = _errors(doc, capture)
    assert any("realm lake: an open realm needs" in e for e in errors)
    assert any(f"{CASE}: defined under encounters but in no realm" in e for e in errors)


def test_an_encounter_belongs_to_one_realm(doc, capture):
    _realm(doc, "mines")["encounters"].append(CASE)
    assert any(f"encounter {CASE!r} is already in another realm" in e for e in _errors(doc, capture))


def test_everyone_starts_in_an_open_trials_realm(doc, capture):
    doc["realms"].insert(0, doc["realms"].pop(doc["realms"].index(_realm(doc, "mines"))))
    assert any("the first realm is where every player starts" in e for e in _errors(doc, capture))


def test_an_encounter_must_sit_in_its_realms_module(doc, course):
    _realm(doc, "mines")["encounters"].append(CASE)        # a Module 3 lesson in a Module 2 realm
    _realm(doc, "lake")["encounters"].remove(CASE)
    errors = B.check_course_refs("", doc, *course)
    assert any(f"{CASE}: lesson 3.4 is not in Module 2" in e for e in errors)


def test_a_realm_module_must_exist_in_the_course(doc, course):
    _realm(doc, "isles")["module"] = 9
    assert any("realm isles: Module 9 is not in learning-path.md" in e for e in B.check_course_refs("", doc, *course))


def test_could_the_ai_write_it_needs_the_rejection_to_hold(doc, capture):
    _encounter(doc)["points"].append({"kind": "choice", "sql": [], "scroll": [], "rejected_case": "l2_current_date_rejected",
                                      "ask": "a", "hint": "h", "lesson": "l",
                                      "options": [{"text": "no", "correct": True}, {"text": "yes"}]})
    assert _errors(doc, capture) == []
    date, cases = copy.deepcopy(capture)
    cases["l2_current_date_rejected"]["sql"] = "SELECT CURRENT_DATE"   # as if it now compiled
    errors = B.compile_quest(doc, date, cases, MODEL)[1]
    assert any("rejected_case 'l2_current_date_rejected' now compiles" in e for e in errors)


# ---- the rendered page -----------------------------------------------------------------------

def test_inlined_data_has_no_raw_markup_and_round_trips(doc, capture):
    data, _ = B.compile_quest(doc, *capture, MODEL)
    data["realms"][0]["halls"][0]["trials"][0]["why"] = "<!--<script></script>-->&amp;"
    html = B.render(B.TEMPLATE.read_text(encoding="utf-8"), data, "")
    body = html.split('<script id="quest-data" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert not set(body) & set("<>&"), "the data block must contain no raw <, > or &"
    assert json.loads(body)["realms"][0]["halls"][0]["trials"][0]["why"] == "<!--<script></script>-->&amp;"


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


# ---- the data contract (quest.json / quest.schema.json) -----------------------------------------

def _embedded(page: pathlib.Path) -> dict:
    html = page.read_text(encoding="utf-8")
    m = re.search(r'<script id="quest-data" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


@pytest.fixture(scope="module")
def schema():
    return json.loads(B.SCHEMA.read_text(encoding="utf-8"))


@pytest.fixture
def built(doc, capture):
    data, errors = B.compile_quest(doc, *capture, MODEL)
    assert errors == []
    return data


def test_built_data_fits_the_schema(built, schema):
    assert B.check_schema(built, schema) == []
    assert built["schema_version"] == B.SCHEMA_VERSION == schema["properties"]["schema_version"]["enum"][0]


def _first_point(data):
    return _built_encounters(data)[0]["points"][0]


@pytest.mark.parametrize("break_it,needle", [
    (lambda d: _first_point(d).update(colour="red"), "'colour' is not in quest.schema.json"),
    (lambda d: d["realms"][0].update(module="0"), "realms[0].module: expected integer"),
    (lambda d: _first_point(d).update(correct=True), "correct: expected integer, got bool"),
    (lambda d: _built_encounters(d)[0].pop("takeaway"), "missing 'takeaway'"),
    (lambda d: _first_point(d).update(ruleBy="wizard"), "'wizard' is not one of"),
    (lambda d: _first_point(d).update(sqlHl="some"), "sqlHl: matches none of its allowed shapes"),
    (lambda d: _built_encounters(d)[0].update(points=[]), "points: needs at least 1 item(s)"),
    (lambda d: d.update(schema_version=2), "schema_version: 2 is not one of [1]"),
])
def test_data_that_drifts_from_the_schema_fails(built, schema, break_it, needle):
    break_it(built)
    errors = B.check_schema(built, schema)
    assert any(needle in e for e in errors), errors


def test_the_schema_checker_refuses_keywords_it_cannot_enforce():
    # A schema rule the checker silently skipped would look enforced and not be.
    assert "does not support" in B.check_schema("x", {"type": "string", "pattern": "^y"})[0]
    assert "unknown $ref" in B.check_schema("x", {"$ref": "#/$defs/nope"})[0]


def _one_field(field: dict, defs: dict | None = None) -> dict:
    """A schema for {"a": ...} whose one field is `field`."""
    return {"type": "object", "properties": {"a": field}, "required": ["a"], "additionalProperties": False,
            "$defs": defs or {}}


@pytest.mark.parametrize("field,defs,value,needle", [
    # 2020-12 applies $ref AND its siblings: a rule beside $ref must not be skipped.
    ({"$ref": "#/$defs/t", "minItems": 2}, {"t": {"type": "array"}}, [1], "needs at least 2 item(s)"),
    ({"$ref": "#/$defs/t", "type": "string"}, {"t": {"enum": [1, "x"]}}, 1, "expected string, got int"),
    ({"$ref": "#/$defs/t", "enum": ["x"]}, {"t": {"type": "string"}}, "y", "'y' is not one of ['x']"),
    ({"description": "lines", "$ref": "#/$defs/t", "minItems": 1}, {"t": {"type": "array"}}, [], "needs at least 1"),
    # JSON keeps true/false apart from 1/0; Python's == does not.
    ({"enum": [1]}, {}, True, "True is not one of [1]"),
    ({"enum": [0]}, {}, False, "False is not one of [0]"),
    ({"type": "integer"}, {}, True, "expected integer, got bool"),
    # A failed anyOf says why each shape failed.
    ({"anyOf": [{"enum": ["all"]}, {"type": "array"}]}, {}, "some", "'some' is not one of ['all']; or "),
])
def test_the_schema_checker_applies_every_rule(field, defs, value, needle):
    errors = B.check_schema({"a": value}, _one_field(field, defs))
    assert any(needle in e for e in errors), errors


@pytest.mark.parametrize("field", ["minutes", "module"])
def test_integer_fields_must_be_whole_numbers_in_the_yaml(doc, capture, field):
    # 2020-12 calls 4.0 an integer, but strictly typed decoders (Go, serde) don't.
    doc["realms"][0][field] = 4.0
    assert any(f"realm law: {field} must be" in e for e in B.compile_quest(doc, *capture, MODEL)[1])


def test_the_schema_checker_follows_2020_12_integers():
    assert B.check_schema({"a": 1.0}, _one_field({"type": "integer"})) == []
    assert B.check_schema({"a": 1.5}, _one_field({"type": "integer"})) != []


@pytest.mark.parametrize("field,needle", [
    ({"type": "object", "properties": {"b": {"type": "string"}}, "required": ["b"],
      "additionalProperties": {"type": "string"}}, "only additionalProperties: false is supported"),
    ({"type": "object"}, "an object needs type: object, properties and additionalProperties: false"),
    ({"type": "object", "properties": {"b": {"type": "string"}}, "required": [], "additionalProperties": False},
     "every property must be required"),
    ({"type": "number"}, "type 'number' is not supported"),
    ({"type": ["string", "null"]}, "is not supported"),
    (True, "boolean schemas are not supported"),
    ({"anyOf": [{"type": "array", "items": {"type": "integer", "minimum": 0}}]}, "uses ['minimum']"),
    ({"$ref": "#/$defs/nope"}, "unknown $ref"),
    # Object rules that _check only applies beside properties must not appear without them.
    ({"required": ["k"]}, "an object needs type: object"),
    ({"additionalProperties": False}, "an object needs type: object"),
    ({"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}, "an object needs type: object"),
    # $ref resolves against the root only, so nothing below may open a new scope.
    ({"$id": "realm.schema.json", "type": "string"}, "supported only at the root"),
    ({"$defs": {"x": {"type": "string"}}, "type": "string"}, "supported only at the root"),
    # Malformed forms are refused, not a traceback.
    ({"type": "object", "properties": {"b": {"type": "string"}}, "required": 5, "additionalProperties": False},
     "required a list of names"),
    ({"type": "object", "properties": [], "required": [], "additionalProperties": False}, "properties must be an object"),
    ({"type": "array", "minItems": "1"}, "minItems must be an integer"),
    ({"enum": "x"}, "enum must be a list"),
    ({"anyOf": []}, "anyOf must be a non-empty list"),
    # What the 2020-12 metaschema requires, so a consumer's validator never errors on the schema.
    ({"type": "string", "title": None}, "title must be a string"),
    ({"type": "string", "description": ["two", "lines"]}, "description must be a string"),
    ({"type": "object", "properties": {"b": {"type": "string"}}, "required": ["b", "b"],
      "additionalProperties": False}, "required lists a name twice"),
    ({"type": "array", "minItems": -1}, "minItems must be an integer, 0 or more"),
    ({"type": "array", "minItems": True}, "minItems must be an integer, 0 or more"),
    ({"type": "object", "properties": {"b": {"type": "string"}}, "required": [["b"]],
      "additionalProperties": False}, "required a list of names"),
    ({"$schema": "http://json-schema.org/draft-04/schema#", "type": "string"}, "supported only at the root"),
])
def test_the_schema_checker_refuses_what_it_cannot_enforce(field, needle):
    # Refused as a schema problem before any data is checked, never a silent pass or a traceback.
    errors = B.check_schema({"a": "x"}, _one_field(field))
    assert errors and all(e.startswith("quest.schema.json") for e in errors), errors
    assert any(needle in e for e in errors), errors


@pytest.mark.parametrize("field,defs", [
    # beside a $ref, these would apply in 2020-12 but not in _check
    ({"$ref": "#/$defs/t", "required": ["k"]}, {"t": {"type": "string"}}),
    ({"$ref": "#/$defs/t", "additionalProperties": False}, {"t": {"type": "string"}}),
])
def test_object_rules_beside_a_ref_are_refused(field, defs):
    errors = B.check_schema({"a": "x"}, _one_field(field, defs))
    assert errors and all(e.startswith("quest.schema.json") for e in errors), errors


@pytest.mark.parametrize("defs", [{"loop": {"$ref": "#/$defs/loop"}},
                                  {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}])
def test_a_ref_that_loops_is_refused_not_a_recursion_error(defs):
    errors = B.check_schema({"a": "x"}, _one_field({"$ref": f"#/$defs/{next(iter(defs))}"}, defs))
    assert any("refers back to itself" in e for e in errors), errors


@pytest.mark.parametrize("root_keys,needle", [
    ({"$schema": "http://json-schema.org/draft-04/schema#"}, "$schema must be"),
    ({"$id": "https://example.com/quest.schema.json#part"}, "$id must be a URI without a fragment"),
    ({"$id": 5}, "$id must be a URI without a fragment"),
])
def test_the_root_pins_the_dialect_and_a_plain_id(root_keys, needle):
    schema = dict(_one_field({"type": "string"}), **root_keys)
    assert any(needle in e for e in B.check_schema({"a": "x"}, schema))


@pytest.mark.parametrize("name", ["lines~1text", "lines/text", "high%6Cight", "a b"])
def test_definition_names_need_no_decoding(name):
    # A real validator decodes JSON Pointer (~1) and percent escapes in $ref; the checker doesn't.
    schema = _one_field({"$ref": f"#/$defs/{name}"}, {name: {"type": "string"}})
    assert any("use letters, digits and _ only" in e for e in B.check_schema({"a": "x"}, schema))


@pytest.mark.parametrize("defs", [
    {"h": {"anyOf": [{"enum": ["all"], "$ref": "#/$defs/h"}, {"type": "array"}]}},
    {"h": {"anyOf": [{"type": "array"}, {"$ref": "#/$defs/h"}]}},                       # in a later branch
    {"h": {"anyOf": [{"$ref": "#/$defs/g"}]}, "g": {"anyOf": [{"$ref": "#/$defs/h"}]}},  # through another def
])
def test_a_ref_that_loops_through_anyof_is_refused_not_a_recursion_error(defs):
    errors = B.check_schema({"a": "all"}, _one_field({"$ref": "#/$defs/h"}, defs))
    assert any("reaches itself" in e for e in errors), errors


def test_a_ref_to_a_non_object_definition_is_refused():
    errors = B.check_schema({"a": "x"}, _one_field({"$ref": "#/$defs/t"}, {"t": True}))
    assert errors and all(e.startswith("quest.schema.json") for e in errors), errors


@pytest.mark.parametrize("text,needle", [
    ('{"type": "object", "enum": [NaN]}', "NaN is not JSON"),
    ('{"type": "object",}', "not valid JSON"),
])
def test_a_schema_file_that_is_not_strict_json_fails_the_gate(monkeypatch, tmp_path, text, needle):
    monkeypatch.setattr(B, "SCHEMA", tmp_path / "quest.schema.json")
    B.SCHEMA.write_text(text, encoding="utf-8")
    assert any(needle in e for e in B.build(check=True)[2])


@pytest.mark.parametrize("field", [{"type": "string"}, {"$ref": "#/$defs/x"}])
@pytest.mark.parametrize("defs", [[], "xyz"])  # a string "contains" the name, then can't be indexed by it
def test_defs_must_be_an_object(field, defs):
    schema = dict(_one_field(field), **{"$defs": defs})
    errors = B.check_schema({"a": "x"}, schema)
    assert any("$defs must be an object" in e for e in errors) and all(e.startswith("quest.schema.json") for e in errors)


def test_unused_schema_definitions_are_checked_too():
    # A definition no data reaches yet still can't hide an unenforceable rule.
    schema = _one_field({"type": "string"}, {"later": {"type": "string", "pattern": "^x"}})
    assert any("#/$defs/later" in e and "pattern" in e for e in B.check_schema({"a": "x"}, schema))


# The gate itself (build() / main --check), not just check_schema, must fail on drift.

def _gate_with(monkeypatch, tmp_path, *, schema=None, capture=None):
    if schema is not None:
        monkeypatch.setattr(B, "SCHEMA", tmp_path / "quest.schema.json")
        B.SCHEMA.write_text(json.dumps(schema), encoding="utf-8")
    if capture is not None:
        monkeypatch.setattr(B, "LESSON_SQL", tmp_path / "lesson-sql.md")
        B.LESSON_SQL.write_text(capture, encoding="utf-8")
    return B.build(check=True)[2]


def test_the_gate_fails_when_the_schema_changes_and_the_build_does_not(monkeypatch, tmp_path, schema, capsys):
    drifted = copy.deepcopy(schema)
    drifted["properties"]["title"] = {"type": "string"}
    drifted["required"].append("title")
    assert any("missing 'title'" in e for e in _gate_with(monkeypatch, tmp_path, schema=drifted))
    assert B.main(["--check"]) == 1
    assert "missing 'title'" in capsys.readouterr().err


def test_the_gate_fails_when_the_header_names_no_model(monkeypatch, tmp_path):
    real = B.LESSON_SQL.read_text(encoding="utf-8")
    for header in ("the sample Model", "the sample Model ** **", "the sample Model **` `**"):
        text = real.replace("the sample Model **`(Sample) Retail - Apparel`**", header)
        assert text != real
        errors = _gate_with(monkeypatch, tmp_path, capture=text)
        assert "lesson-sql.md: no Model named in its header" in errors, header


@pytest.mark.parametrize("name", ["Acme Sales", "(Sample) Retail"])  # another Model, or a prefix of the real one
def test_the_gate_fails_when_the_header_names_another_model(monkeypatch, tmp_path, name):
    # The caption names the header's Model, so it must be the one the AgentQL queries.
    real = B.LESSON_SQL.read_text(encoding="utf-8")
    text = real.replace("**`(Sample) Retail - Apparel`**", f"**`{name}`**")
    errors = _gate_with(monkeypatch, tmp_path, capture=text)
    assert any(f"names Model {name!r}, but this AgentQL does not query" in e for e in errors), errors


@pytest.mark.parametrize("model", [None, "", "   "])
def test_compile_quest_refuses_a_blank_model(doc, capture, model):
    assert "lesson-sql.md: no Model named in its header" in B.compile_quest(doc, *capture, model)[1]


@pytest.mark.parametrize("old,new,ok", [
    ('FROM "(Sample) Retail - Apparel"', 'from "(Sample) Retail - Apparel"', True),   # AgentQL is case-insensitive
    ('FROM "(Sample) Retail - Apparel"', 'FROM\n  "(Sample) Retail - Apparel"', True),  # laid out over two lines
    ('FROM "(Sample) Retail - Apparel"', 'XFROM "(Sample) Retail - Apparel"', False),  # not the keyword
    ('FROM "(Sample) Retail - Apparel"', 'FROM "(Sample) Retail - Apparel 2"', False),  # a longer name
])
def test_the_from_check_matches_the_keyword_and_the_whole_name(doc, capture, old, new, ok):
    date, cases = capture
    cases = copy.deepcopy(cases)
    assert old in cases[CASE]["agentql"]
    cases[CASE]["agentql"] = cases[CASE]["agentql"].replace(old, new)
    errors = B.compile_quest(doc, date, cases, MODEL)[1]
    flagged = any(e.startswith(f"{CASE}: the capture header names Model") for e in errors)
    assert flagged is not ok, errors


def test_the_header_model_is_read_from_the_capture_line_only():
    text = "A note on Model **`Decoy`**.\n\ncaptured live on the sample Model **` Real `** (a cluster)"
    assert B.parse_capture_model(text) == "Real"


def test_the_gate_reads_the_committed_header(monkeypatch, tmp_path):
    # A decoy before the capture line must not change the Model the caption names.
    real = B.LESSON_SQL.read_text(encoding="utf-8")
    text = real.replace("# Captured warehouse SQL", "Model **`Decoy`**\n\n# Captured warehouse SQL", 1)
    assert text != real
    assert _gate_with(monkeypatch, tmp_path, capture=text) == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_fails_its_play_through_without_a_model(doc, capture, tmp_path):
    data, errors = B.compile_quest(doc, *capture, MODEL)
    assert errors == []
    data["model"] = ""
    page = tmp_path / "index.html"
    page.write_text(B.render(B.TEMPLATE.read_text(encoding="utf-8"), data, B.font_faces()), encoding="utf-8")
    r = subprocess.run(["node", str(HERE / "play_quest.js"), str(page)], capture_output=True, text=True)
    assert r.returncode != 0 and "should name the Model" in r.stdout + r.stderr


@pytest.mark.parametrize("name", ["quest.json", "quest.schema.json", "Quest.json", "QUEST.SCHEMA.JSON"])
def test_out_may_not_name_a_file_written_beside_the_page(tmp_path, name):
    assert B.main(["--out", str(tmp_path / name)]) == 2
    assert not (tmp_path / name).exists()


def test_a_real_2020_12_validator_accepts_the_published_pair(tmp_path):
    # The built-in checker is a strict subset; this is a consumer's jsonschema.validate() call. CI
    # installs jsonschema 4.x (validate.yml), so there it always runs; elsewhere it skips unless a
    # 2020-12-capable jsonschema is installed (Ubuntu 22.04's system one is 3.2).
    try:
        import jsonschema
        validator = jsonschema.Draft202012Validator
    except (ImportError, AttributeError) as e:  # absent, broken, or older than 4.0
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail(f"CI must install jsonschema 4.x (see validate.yml): {e!r}")
        pytest.skip(f"no 2020-12 jsonschema here: {e!r}")
    page = tmp_path / "index.html"
    assert B.main(["--out", str(page)]) == 0
    schema = json.loads((tmp_path / "quest.schema.json").read_text(encoding="utf-8"))
    data = json.loads((tmp_path / "quest.json").read_text(encoding="utf-8"))
    assert jsonschema.validators.validator_for(schema) is validator  # what jsonschema.validate() would pick
    jsonschema.validate(data, schema)  # a consumer's call: metaschema check, then the data


def test_every_schema_field_is_required(schema):
    # A front end may rely on every field being present; an optional one would need a default.
    def walk(node, where):
        if isinstance(node, dict):
            if "properties" in node:
                assert set(node.get("required", [])) == set(node["properties"]), where
                assert node.get("additionalProperties") is False, where
            for k, v in node.items():
                walk(v, f"{where}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{where}[{i}]")
    walk(schema, "#")


def test_main_writes_quest_json_beside_the_page(tmp_path):
    page = tmp_path / "index.html"
    assert B.main(["--out", str(page)]) == 0
    data = json.loads((tmp_path / "quest.json").read_text(encoding="utf-8"))
    assert data == _embedded(page)
    assert (tmp_path / "quest.schema.json").read_text(encoding="utf-8") == B.SCHEMA.read_text(encoding="utf-8")
    assert data["model"] == MODEL


def test_the_model_name_comes_from_the_capture_not_the_page():
    assert MODEL not in B.TEMPLATE.read_text(encoding="utf-8")
    assert B.parse_capture_model("captured live on the sample Model **`Acme Sales`** (a cluster)") == "Acme Sales"
    assert B.parse_capture_model("no header here") is None


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
    # The data contract is published beside the game, identical to what the page embeds.
    assert json.loads((game.parent / "quest.json").read_text(encoding="utf-8")) == _embedded(game)
    # ...with the schema its $id names, at that same path.
    schema_url = json.loads(B.SCHEMA.read_text(encoding="utf-8"))["$id"]
    assert schema_url.endswith("/agentql-quest/quest.schema.json")
    assert (game.parent / "quest.schema.json").read_text(encoding="utf-8") == B.SCHEMA.read_text(encoding="utf-8")
    # Every local image the home page shows must be in the site, or it renders as a broken image.
    for src in re.findall(r'<img[^>]+src="([^":]+)"', home.read_text(encoding="utf-8")):
        assert (site / src).is_file(), f"home page shows {src}, which the build did not copy"


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


# ---- paths that would go stale silently if the folder moved ------------------------------------

def _rel(path: pathlib.Path) -> str:
    return path.relative_to(B.ROOT).as_posix()


def test_pages_path_filters_cover_the_game_and_its_sources():
    # A stale filter never fails: pushes to main just stop redeploying the game.
    wf = yaml.safe_load((B.ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8"))
    triggers = wf[True] if True in wf else wf["on"]
    filters = [_github_glob(f) for f in triggers["push"]["paths"]]
    files = [_rel(f) for f in B.ROOT.rglob("*") if f.is_file() and ".git" not in f.parts]
    for f, rx in zip(triggers["push"]["paths"], filters):
        assert any(rx.fullmatch(x) for x in files), f"pages.yml path filter {f!r} matches nothing in the repo"
    for needed in (B.HERE / "build.py", B.ENCOUNTERS, B.TEMPLATE, B.LESSON_SQL):
        assert any(rx.fullmatch(_rel(needed)) for rx in filters), f"pages.yml would not redeploy for {_rel(needed)}"


def _github_glob(pattern: str) -> re.Pattern:
    """A workflow path filter as a regex: ** crosses folders, * stays within one."""
    out = re.escape(pattern).replace(r"\*\*", "\0").replace(r"\*", "[^/]*").replace("\0", ".*")
    return re.compile(out)


def test_pre_commit_runs_the_quest_gate_for_the_game_and_the_course():
    # A stale trigger never fails either: the gate just stops running locally.
    text = (B.ROOT / "scripts/pre-commit.sh").read_text(encoding="utf-8")
    m = re.search(r"grep -qE '([^']+)'; then\n\s*run_check \"agentql quest\"", text)
    assert m, "the agentql quest trigger in pre-commit.sh has moved; update this test"
    trigger = re.compile(m.group(1))
    for path in (B.HERE / "build.py", B.ENCOUNTERS, B.TEMPLATE, B.LESSON_SQL, B.LEARNING_PATH):
        assert trigger.search(_rel(path)), f"pre-commit would not run the quest gate for {_rel(path)}"


def test_every_tools_path_named_in_the_quest_docs_exists():
    # Commands and docstrings that name a tools/ path (README, build.py, promo, the validator,
    # the workflows' comments) must keep pointing at real files after a move.
    sources = [B.HERE / "README.md", B.HERE / "build.py", B.HERE / "promo/README.md",
               B.HERE / "promo/make_ad.py", B.ROOT / "tools/validate/check_agentql_quest.py",
               B.ROOT / ".github/workflows/pages.yml", B.ROOT / "README.md"]
    named = {m for f in sources for m in re.findall(r"\btools/[\w./-]*\w", f.read_text(encoding="utf-8"))}
    assert any(n.startswith("tools/quest/") for n in named)
    missing = sorted(n for n in named if not (B.ROOT / n).exists() and not any(part in n for part in ("/dist", "*")))
    assert missing == [], missing


# ---- lesson and module numbers the text names ------------------------------------------------

@pytest.fixture(scope="module")
def course():
    return B.parse_learning_path(B.LEARNING_PATH.read_text(encoding="utf-8"))


def test_course_refs_in_the_committed_encounters_are_current(doc, course):
    assert B.check_course_refs(B.ENCOUNTERS.read_text(encoding="utf-8"), doc, *course) == []


def test_each_encounter_names_the_lesson_that_guards_its_case(doc, course):
    _, lessons, _ = course
    for e in doc["encounters"]:
        assert e["case"] in lessons[str(e["lesson"])]


@pytest.mark.parametrize("text,needle", [
    ("Lesson 9.9 shows it.", "lesson 9.9"),
    ("backed_by: learning-path.md lesson 9.9", "lesson 9.9"),
    ("backed_by: learning-path.md Modules 1 and 9", "Module 9"),
    ("backed_by: learning-path.md Module 9", "Module 9"),
])
def test_a_renumbered_course_fails_the_build(doc, course, text, needle):
    errors = B.check_course_refs(text, {"encounters": []}, *course)
    assert any(needle in e for e in errors), errors


def test_an_encounter_pointing_at_the_wrong_lesson_fails(doc, course):
    _, lessons, _ = course
    wrong = next(n for n, ids in lessons.items() if CASE not in ids)
    _encounter(doc)["lesson"] = wrong
    errors = B.check_course_refs("", doc, *course)
    assert any(f"lesson {wrong}'s Guarded by line does not list {CASE}" in e for e in errors)


def test_scroll_rows_have_one_cell_per_column(doc, capture):
    # An unquoted comma in a YAML flow list splits one cell into two; it rendered as a 4-cell row.
    scroll = _law(doc)["scroll"]
    cols = len(scroll["columns"])
    scroll["rows"][0]["cells"] = ["A person", "in natural language"] + ["x"] * (cols - 1)
    assert any(f"has {cols + 1} cells for {cols} columns" in e for e in _errors(doc, capture))



# ---- halls and the quest path ----------------------------------------------------------------

def _mines(doc):
    return next(e for e in doc["encounters"] if e["case"] == "l2_filter_case_insensitive")


def test_the_dragon_path_must_be_agentql(doc, capture):
    _encounter(doc)["path"]["answer"] = "keyword"
    assert any("path.answer must be 'agentql'" in e for e in _errors(doc, capture))


def test_the_right_path_cannot_be_blocked(doc, capture):
    _mines(doc)["path"]["blocked"]["agentql"] = "closed"
    assert any("the right path can't be blocked" in e for e in _errors(doc, capture))


def test_every_path_explains_itself(doc, capture):
    del _encounter(doc)["path"]["why"]["code_complete"]
    assert any("path needs a why (or blocked) text for code_complete" in e for e in _errors(doc, capture))


def test_the_mines_block_the_keyword_path(doc, capture):
    data, _ = B.compile_quest(doc, *capture, MODEL)
    mines = next(r for r in data["realms"] if r["id"] == "mines")["encounters"][0]["path"]
    kinds = {o: x["kind"] for o, x in zip(mines["options"], mines["outcomes"])}
    assert kinds == {"Send it to Keyword Search": "blocked", "Send it to AgentQL": "win", "Send it to Code Complete": "loss"}


def test_a_hall_needs_questions(doc, capture):
    _law(doc)["halls"][0]["trials"] = []
    assert any("realm law hall 1: needs at least one question" in e for e in _errors(doc, capture))


def test_every_recap_row_is_taught_in_a_hall(doc, capture):
    for h in _law(doc)["halls"]:
        h["rows"] = [x for x in h["rows"] if x != "Where the answer lives"]
    assert any("'Where the answer lives' is in the recap but no hall teaches it" in e for e in _errors(doc, capture))


def test_a_hall_teaches_only_scroll_columns_and_rows(doc, capture):
    _law(doc)["halls"][0]["columns"] = ["Keyword Search", "Telepathy"]
    assert any("unknown scroll columns ['Telepathy']" in e for e in _errors(doc, capture))


def test_who_points_name_their_rule(doc, capture):
    del _mines(doc)["points"][0]["rule"]
    assert any("a who point needs a rule" in e for e in _errors(doc, capture))


def test_every_rule_says_who_adds_it(doc, capture):
    rls = next(p for p in _encounter(doc)["points"] if p["kind"] == "choice" and p.get("rule_by") == "model")
    del rls["rule_by"]
    assert any("rule_by must be one of" in e for e in _errors(doc, capture))


def test_the_hoard_separates_rules_from_the_players_part(doc, capture):
    data, _ = B.compile_quest(doc, *capture, MODEL)
    lake = next(r for r in data["realms"] if r["id"] == "lake")["encounters"][0]
    by = {p["rule"]: p["ruleBy"] for p in lake["points"] if p["rule"]}
    assert by["Every product kept, sold in the West or not"] == "agentql"
    assert {"model", "agentql"} <= set(by.values())



# ---- second review: the course's own numbering, statement shape, quoted names --------------------

def test_a_renumbered_or_retitled_lesson_fails(doc, course):
    modules, lessons, titles = course
    # Swap what 3.3 and 3.4 are about: the numbers still exist, but "Lesson 3.3 shows the injected
    # filter" would now name the outer-join lesson.
    swapped = dict(titles, **{"3.3": titles["3.4"], "3.4": titles["3.3"]})
    errors = B.check_course_refs(B.ENCOUNTERS.read_text(encoding="utf-8"), doc, modules, lessons, swapped)
    assert any("lesson 3.3 is now" in e for e in errors) and any("lesson 3.4 is now" in e for e in errors)


def test_every_named_lesson_declares_its_title(doc, course):
    del doc["lesson_titles"]["5.2"]
    errors = B.check_course_refs(B.ENCOUNTERS.read_text(encoding="utf-8"), doc, *course)
    assert any("lesson 5.2 is named but has no entry in lesson_titles" in e for e in errors)


@pytest.mark.parametrize("case,old,new,needle", [
    ("l2_filter_case_insensitive", "  ELSE 0\n", "  ELSE NULL\n", "no SQL line is exactly 'ELSE 0'"),
    ("l5_rank", "ELSE 0", "ELSE NULL", "expected 'ELSE 0' 2 time(s)"),
    ("l5_cte_two_step", '  GROUP BY "ca_1"\n)', '  GROUP BY "ca_1"\nLIMIT 100000\n)', "expected 'LIMIT' 1 time(s)"),
    (CASE, '    ON "ta_5"."ca_1" = "ta_6"."ca_2"\nLIMIT 100000',
     '    ON "ta_5"."ca_1" = "ta_6"."ca_2"\nWHERE "ta_6"."ca_3" IS NOT NULL\nLIMIT 100000', "expected 'WHERE' 1 time(s)"),
    (CASE, '    WHERE LOWER("ta_4"."REGION") = \'west\'', '      JOIN "RETAILAPPAREL"."PUBLIC"."DIM_X" "ta_9" ON 1 = 1\n'
     '    WHERE LOWER("ta_4"."REGION") = \'west\'', "expected 'JOIN \"RETAILAPPAREL\"' 2 time(s)"),
])
def test_second_review_falsifications_fail(doc, capture, case, old, new, needle):
    errors = _errors(doc, _recaptured(capture, old, new, case))
    assert any(needle in e for e in errors), errors


def test_statement_order_checks(doc, capture):
    # The row cap must close the statement, and the West filter must come before the outer join.
    cap = _recaptured(capture, "LIMIT 100000", "LIMIT 100000\nORDER BY 1", "l5_cte_two_step")
    assert any("expected the statement to end with 'LIMIT 100000'" in e for e in _errors(doc, cap))


def test_norm_keeps_quoted_names_exact():
    assert B._norm('"(Sample)  Retail  -  Apparel"') != B._norm('"(Sample) Retail - Apparel"')


def test_planned_capabilities_are_labelled_coming_soon(doc):
    # AgentQL keyword review and pinning are planned, near term: the game must not teach them as
    # shipped, and the comparison must say "Coming soon" where it describes them for AgentQL.
    scroll = _law(doc)["scroll"]
    agentql = scroll["columns"].index("AgentQL")
    rows = {r["label"]: r["cells"][agentql] for r in scroll["rows"]}
    assert rows["How a person checks it"].startswith("Coming soon")
    assert "Coming soon: pin it" in rows["Where the answer lives"]
    raw = B.ENCOUNTERS.read_text(encoding="utf-8")
    for shipped_claim in ("Still the keywords", "shown as keywords too", "Keyword Search and AgentQL produce ThoughtSpot Answers you can pin"):
        assert shipped_claim not in raw
