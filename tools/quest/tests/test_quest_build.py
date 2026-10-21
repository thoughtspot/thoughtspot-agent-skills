"""The quest engine and AgentQL Quest's pack: the content must keep matching the captured lesson SQL
and the course, and the data must fit the generated schema. No live calls."""
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

CAP, CR, RULES = B.load_plugins(["agentql_capture", "course_refs", "agentql_rules"])
PACK_DIR = B.PACKS / "agentql"
CONTENT = PACK_DIR / "content.yaml"
LESSON_SQL = B.Pack("agentql").source("lesson_sql")
LEARNING_PATH = B.Pack("agentql").source("learning_path")
CASE = "l3_all_products_left_join"
EID = "every_product"  # the encounter whose case is CASE
MODEL = "(Sample) Retail - Apparel"  # the Model lesson-sql.md's header names


@pytest.fixture(scope="module")
def capture():
    return CAP.parse_lesson_sql(LESSON_SQL.read_text(encoding="utf-8"))


@pytest.fixture
def doc():
    return yaml.safe_load(CONTENT.read_text(encoding="utf-8"))


def _compile(doc, capture, model=MODEL):
    """The AgentQL pack compiled with an edited content doc and an edited capture."""
    pack = B.Pack("agentql")
    pack.doc = doc
    return B.compile_pack(pack, {"agentql_capture": CAP.Capture(*capture, model)})


def _errors(doc, capture):
    return _compile(doc, capture)[1]


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
    data, errors = _compile(doc, capture)
    assert errors == []
    return B.render(B.TEMPLATE.read_text(encoding="utf-8"), data, B.font_faces())


# ---- the committed content -------------------------------------------------------------------

def test_committed_encounters_build_clean(doc, capture):
    data, errors = _compile(doc, capture)
    assert errors == []
    captured = data["meta"]["agentql_capture"]["captured"]
    assert captured and re.fullmatch(r"\d{4}-\d{2}-\d{2}", captured)
    first = data["realms"][0]
    assert first["id"] == "law" and first["refs"]["module"] == 0 and first["halls"], "everyone starts in Law (Module 0)"
    assert any(r["encounters"] for r in data["realms"]), "at least one realm should have a dragon"


def test_main_check_passes_on_the_repo():
    assert B.main(["--check"]) == 0


def test_every_who_point_highlights_the_sql_it_asks_about(doc, capture):
    data, _ = _compile(doc, capture)
    src = {e["case"]: e for e in doc["encounters"]}
    for e in _built_encounters(data):
        for p, raw in zip(e["points"], src[e["refs"]["case"]]["points"]):
            if raw["kind"] == "who":
                assert p["highlights"]["sql"] == "all" or p["highlights"]["sql"], f"{e['id']}: a who point lights up no SQL"


def test_who_answers_map_to_the_right_option(doc, capture):
    data, _ = _compile(doc, capture)
    e = next(x for x in _built_encounters(data) if x["refs"]["case"] == CASE)
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
    e["scroll"] = e["scroll"].replace("'West'", "'East'")
    assert any("differs from the captured AgentQL" in x for x in _errors(doc, capture))


def test_relayout_of_agentql_is_allowed(doc, capture):
    e = _encounter(doc)
    e["scroll"] = " ".join(e["scroll"].split())  # the same query, all on one line
    assert _errors(doc, capture) == []


@pytest.mark.parametrize("a,b", [
    ('"(Sample) Retail"', '"(Sample)Retail"'),
    ("x IN ('North', 'West')", "x IN ('North','West')"),
    ("'a  b'", "'a b'"),
    ("WHERE x = 'West'", "WHERE x = 'west'"),
])
def test_norm_only_forgives_layout(a, b):
    assert CAP.norm(a) != CAP.norm(b)


def test_norm_forgives_line_breaks_inside_brackets():
    assert CAP.norm("WITH a AS (\n  SELECT x\n  FROM t\n), b AS (SELECT y)") == CAP.norm("WITH a AS (SELECT x FROM t), b AS (SELECT y)")


def test_missing_and_rejected_cases_fail(doc, capture):
    date, cases = capture
    rejected = next(cid for cid, c in cases.items() if c["sql"] is None)
    first = _encounter(doc)
    doc["encounters"] = [dict(copy.deepcopy(first), case="no_such_case"), dict(copy.deepcopy(first), id="rejected", case=rejected)]
    errors = _compile(doc, (date, cases))[1]
    assert any("case 'no_such_case' is not in lesson-sql.md" in e for e in errors)
    assert any(f"case {rejected}: captured status was not SUCCESS" in e for e in errors)


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
    assert any("kind must be one of ['choice', 'who']" in x for x in errors)
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
    data, _ = _compile(doc, capture)
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
    assert any(f"encounter {EID}: defined under encounters but in no realm" in e for e in errors)


def test_an_encounter_belongs_to_one_realm(doc, capture):
    _realm(doc, "mines")["encounters"].append(EID)
    assert any(f"encounter {EID!r} is already in another realm" in e for e in _errors(doc, capture))


def test_everyone_starts_in_an_open_trials_realm(doc, capture):
    doc["realms"].insert(0, doc["realms"].pop(doc["realms"].index(_realm(doc, "mines"))))
    assert any("the first realm is where every player starts" in e for e in _errors(doc, capture))


def test_an_encounter_must_sit_in_its_realms_module(doc, course):
    _realm(doc, "mines")["encounters"].append(EID)         # a Module 3 lesson in a Module 2 realm
    _realm(doc, "lake")["encounters"].remove(EID)
    errors = CR.check_course_refs("", doc, *course)
    assert any(f"{CASE}: lesson 3.4 is not in Module 2" in e for e in errors)


def test_a_realm_module_must_exist_in_the_course(doc, course):
    _realm(doc, "isles")["module"] = 9
    assert any("realm isles: Module 9 is not in learning-path.md" in e for e in CR.check_course_refs("", doc, *course))


def test_could_the_ai_write_it_needs_the_rejection_to_hold(doc, capture):
    _encounter(doc)["points"].append({"kind": "choice", "sql": [], "scroll": [], "rejected_case": "l2_current_date_rejected",
                                      "ask": "a", "hint": "h", "why": "l",
                                      "options": [{"text": "no", "correct": True}, {"text": "yes"}]})
    assert _errors(doc, capture) == []
    date, cases = copy.deepcopy(capture)
    cases["l2_current_date_rejected"]["sql"] = "SELECT CURRENT_DATE"   # as if it now compiled
    errors = _compile(doc, (date, cases))[1]
    assert any("rejected_case 'l2_current_date_rejected' now compiles" in e for e in errors)


# ---- the rendered page -----------------------------------------------------------------------

def test_inlined_data_has_no_raw_markup_and_round_trips(doc, capture):
    data, _ = _compile(doc, capture)
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
    return B.pack_schema(B.Pack("agentql"))


@pytest.fixture
def built(doc, capture):
    data, errors = _compile(doc, capture)
    assert errors == []
    return data


def test_built_data_fits_the_schema(built, schema):
    assert B.check_schema(built, schema) == []
    assert built["schema_version"] == B.SCHEMA_VERSION == schema["properties"]["schema_version"]["enum"][0]


def _first_point(data):
    return _built_encounters(data)[0]["points"][0]


@pytest.mark.parametrize("break_it,needle", [
    (lambda d: _first_point(d).update(colour="red"), "'colour' is not in quest.schema.json"),
    (lambda d: d["realms"][0]["refs"].update(module="0"), "realms[0].refs.module: expected integer"),
    (lambda d: _first_point(d).update(correct=True), "correct: expected integer, got bool"),
    (lambda d: _built_encounters(d)[0].pop("takeaway"), "missing 'takeaway'"),
    (lambda d: _first_point(d).update(ruleTag="wizard"), "'wizard' is not one of"),
    (lambda d: _first_point(d)["highlights"].update(sql="some"), "highlights.sql: matches none of its allowed shapes"),
    (lambda d: _built_encounters(d)[0].update(points=[]), "points: needs at least 1 item(s)"),
    (lambda d: d.update(schema_version=3), "schema_version: 3 is not one of [2]"),
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
    assert any(f"realm law: {field} must be" in e for e in _compile(doc, capture)[1])


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
    monkeypatch.setattr(B, "CORE_SCHEMA", tmp_path / "core.json")
    B.CORE_SCHEMA.write_text(text, encoding="utf-8")
    assert any(needle in e for e in B.build(check=True)[3])


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
        monkeypatch.setattr(B, "CORE_SCHEMA", tmp_path / "core.json")
        B.CORE_SCHEMA.write_text(json.dumps(schema), encoding="utf-8")
    if capture is not None:
        (tmp_path / "lesson-sql.md").write_text(capture, encoding="utf-8")
        source = B.Pack.source
        monkeypatch.setattr(B.Pack, "source", lambda self, name: tmp_path / "lesson-sql.md" if name == "lesson_sql"
                            else source(self, name))
    return B.build(check=True)[3]


def test_the_gate_fails_when_the_schema_changes_and_the_build_does_not(monkeypatch, tmp_path, schema, capsys):
    drifted = copy.deepcopy(schema)
    drifted["properties"]["title"] = {"type": "string"}
    drifted["required"].append("title")
    assert any("missing 'title'" in e for e in _gate_with(monkeypatch, tmp_path, schema=drifted))
    assert B.main(["--check"]) == 1
    assert "missing 'title'" in capsys.readouterr().err


def test_the_gate_fails_when_the_header_names_no_model(monkeypatch, tmp_path):
    real = LESSON_SQL.read_text(encoding="utf-8")
    for header in ("the sample Model", "the sample Model ** **", "the sample Model **` `**"):
        text = real.replace("the sample Model **`(Sample) Retail - Apparel`**", header)
        assert text != real
        errors = _gate_with(monkeypatch, tmp_path, capture=text)
        assert "lesson-sql.md: no Model named in its header" in errors, header


@pytest.mark.parametrize("name", ["Acme Sales", "(Sample) Retail"])  # another Model, or a prefix of the real one
def test_the_gate_fails_when_the_header_names_another_model(monkeypatch, tmp_path, name):
    # The caption names the header's Model, so it must be the one the AgentQL queries.
    real = LESSON_SQL.read_text(encoding="utf-8")
    text = real.replace("**`(Sample) Retail - Apparel`**", f"**`{name}`**")
    errors = _gate_with(monkeypatch, tmp_path, capture=text)
    assert any(f"names Model {name!r}, but this AgentQL does not query" in e for e in errors), errors


@pytest.mark.parametrize("model", [None, "", "   "])
def test_compile_quest_refuses_a_blank_model(doc, capture, model):
    assert "lesson-sql.md: no Model named in its header" in _compile(doc, capture, model)[1]


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
    errors = _compile(doc, (date, cases))[1]
    flagged = any(e.startswith(f"encounter {EID}: the capture header names Model") for e in errors)
    assert flagged is not ok, errors


def test_the_header_model_is_read_from_the_capture_line_only():
    text = "A note on Model **`Decoy`**.\n\ncaptured live on the sample Model **` Real `** (a cluster)"
    assert CAP.parse_capture_model(text) == "Real"


def test_the_gate_reads_the_committed_header(monkeypatch, tmp_path):
    # A decoy before the capture line must not change the Model the caption names.
    real = LESSON_SQL.read_text(encoding="utf-8")
    text = real.replace("# Captured warehouse SQL", "Model **`Decoy`**\n\n# Captured warehouse SQL", 1)
    assert text != real
    assert _gate_with(monkeypatch, tmp_path, capture=text) == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_fails_its_play_through_without_a_model(doc, capture, tmp_path):
    data, errors = _compile(doc, capture)
    assert errors == []
    data["meta"]["agentql_capture"]["model"] = ""
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
    assert json.loads((tmp_path / "quest.schema.json").read_text(encoding="utf-8")) == B.pack_schema(B.Pack("agentql"))
    assert data["meta"]["agentql_capture"]["model"] == MODEL


def test_the_model_name_comes_from_the_capture_not_the_page():
    assert MODEL not in B.TEMPLATE.read_text(encoding="utf-8")
    assert CAP.parse_capture_model("captured live on the sample Model **`Acme Sales`** (a cluster)") == "Acme Sales"
    assert CAP.parse_capture_model("no header here") is None


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
    published = json.loads((game.parent / "quest.schema.json").read_text(encoding="utf-8"))
    assert published["$id"].endswith("/agentql-quest/quest.schema.json")
    assert published == B.pack_schema(B.Pack("agentql"))
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


def _tracked() -> list[str]:
    """Committed files only: a clone keeps ignored leftovers (dist/, __pycache__/) of a moved folder."""
    out = subprocess.run(["git", "ls-files"], cwd=B.ROOT, capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def _tracked_path_exists(rel: str, tracked: list[str]) -> bool:
    return rel in tracked or any(t.startswith(rel.rstrip("/") + "/") for t in tracked)


def test_pages_path_filters_cover_the_game_and_its_sources():
    # A stale filter never fails: pushes to main just stop redeploying the game.
    wf = yaml.safe_load((B.ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8"))
    triggers = wf[True] if True in wf else wf["on"]
    filters = [_github_glob(f) for f in triggers["push"]["paths"]]
    files = _tracked()
    for f, rx in zip(triggers["push"]["paths"], filters):
        assert any(rx.fullmatch(x) for x in files), f"pages.yml path filter {f!r} matches nothing in the repo"
    # Everything the site is built from: the game, its data, schema, fonts, poster and capture.
    poster = PACK_DIR / "promo/agentql-quest-poster.png"
    for needed in (B.HERE / "build.py", CONTENT, PACK_DIR / "pack.yaml", PACK_DIR / "strings.yaml",
                   B.CHECKS / "agentql_capture.py", B.TEMPLATE, B.CORE_SCHEMA, B.DENYLIST, poster, LESSON_SQL,
                   *sorted(B.FONT_DIR.glob("*.woff2"))):
        assert any(rx.fullmatch(_rel(needed)) for rx in filters), f"pages.yml would not redeploy for {_rel(needed)}"


def _github_glob(pattern: str) -> re.Pattern:
    """A workflow path filter as a regex, for the subset pages.yml uses: `**/` is zero or more
    folders, `**` anything, `*` anything within one folder. Other syntax (`?`, `[...]`, `!`) isn't
    modelled; it would fail this test loudly, never let a stale filter pass."""
    out = (re.escape(pattern).replace(r"\*\*/", "\1").replace(r"\*\*", "\0")
           .replace(r"\*", "[^/]*").replace("\1", "(?:.*/)?").replace("\0", ".*"))
    return re.compile(out)


def test_github_glob_follows_the_documented_forms_it_models():
    assert _github_glob("docs/**/*.md").fullmatch("docs/README.md")
    assert _github_glob("docs/**/*.md").fullmatch("docs/a/b/c.md")
    assert _github_glob("**/README.md").fullmatch("README.md")
    assert not _github_glob("docs/*").fullmatch("docs/a/b.md")
    assert not _github_glob("tools/quest/**").fullmatch("tools/questx/a.py")
    assert not _github_glob("a.md").fullmatch("aXmd")


def test_pre_commit_runs_the_quest_gate_for_the_game_and_the_course():
    # A stale trigger never fails either: the gate just stops running locally.
    text = (B.ROOT / "scripts/pre-commit.sh").read_text(encoding="utf-8")
    m = re.search(r"grep -qE '([^']+)'; then\n\s*run_check \"agentql quest\"", text)
    assert m, "the agentql quest trigger in pre-commit.sh has moved; update this test"
    trigger = re.compile(m.group(1))
    for path in (B.HERE / "build.py", CONTENT, PACK_DIR / "pack.yaml", B.TEMPLATE, LESSON_SQL, LEARNING_PATH):
        assert trigger.search(_rel(path)), f"pre-commit would not run the quest gate for {_rel(path)}"


def test_every_tools_path_named_in_the_quest_docs_exists():
    # Commands and docstrings that name a tools/ path (the quest's README, build.py and promo, the
    # validator, pages.yml and the root README) must keep pointing at committed files after a move.
    sources = [B.HERE / "README.md", B.HERE / "build.py", PACK_DIR / "promo/README.md",
               PACK_DIR / "promo/make_ad.py", B.ROOT / "tools/validate/check_agentql_quest.py",
               B.ROOT / ".github/workflows/pages.yml", B.ROOT / "README.md"]
    named = {m for f in sources for m in re.findall(r"\btools/[\w./-]*\w", f.read_text(encoding="utf-8"))}
    assert any(n.startswith("tools/quest/") for n in named)
    # dist/ is build output and isn't committed, so check the folder it is written into.
    tracked = _tracked()
    missing = sorted(n for n in named if not _tracked_path_exists(n.partition("/dist")[0], tracked))
    assert missing == [], missing


def test_the_root_readme_tree_and_the_design_doc_name_the_folder():
    # check_consistency only looks for the name as a substring, and "quest" is in the URL.
    readme = (B.ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(rf"[\u251c\u2514]\u2500\u2500 {re.escape(B.HERE.name)}/ ", readme), "README tree"
    # check_references skips docs/superpowers/.
    spec = B.ROOT / "docs/superpowers/specs/2026-10-21-agentql-quest-pack-design.md"
    links = re.findall(r"\]\((\.\./[^)\s#]+)\)", spec.read_text(encoding="utf-8"))
    assert links and all((spec.parent / link).resolve().exists() for link in links), links


# ---- lesson and module numbers the text names ------------------------------------------------

@pytest.fixture(scope="module")
def course():
    return CR.parse_learning_path(LEARNING_PATH.read_text(encoding="utf-8"))


def test_course_refs_in_the_committed_encounters_are_current(doc, course):
    assert CR.check_course_refs(CONTENT.read_text(encoding="utf-8"), doc, *course) == []


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
    errors = CR.check_course_refs(text, {"encounters": []}, *course)
    assert any(needle in e for e in errors), errors


def test_an_encounter_pointing_at_the_wrong_lesson_fails(doc, course):
    _, lessons, _ = course
    wrong = next(n for n, ids in lessons.items() if CASE not in ids)
    _encounter(doc)["lesson"] = wrong
    errors = CR.check_course_refs("", doc, *course)
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
    data, _ = _compile(doc, capture)
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
    rls = next(p for p in _encounter(doc)["points"] if p["kind"] == "choice" and p.get("rule_tag") == "model")
    del rls["rule_tag"]
    assert any("rule_tag must be one of" in e for e in _errors(doc, capture))


def test_the_hoard_separates_rules_from_the_players_part(doc, capture):
    data, _ = _compile(doc, capture)
    lake = next(r for r in data["realms"] if r["id"] == "lake")["encounters"][0]
    by = {p["rule"]: p["ruleTag"] for p in lake["points"] if p["rule"]}
    assert by["Every product kept, sold in the West or not"] == "agentql"
    assert {"model", "agentql"} <= set(by.values())



# ---- second review: the course's own numbering, statement shape, quoted names --------------------

def test_a_renumbered_or_retitled_lesson_fails(doc, course):
    modules, lessons, titles = course
    # Swap what 3.3 and 3.4 are about: the numbers still exist, but "Lesson 3.3 shows the injected
    # filter" would now name the outer-join lesson.
    swapped = dict(titles, **{"3.3": titles["3.4"], "3.4": titles["3.3"]})
    errors = CR.check_course_refs(CONTENT.read_text(encoding="utf-8"), doc, modules, lessons, swapped)
    assert any("lesson 3.3 is now" in e for e in errors) and any("lesson 3.4 is now" in e for e in errors)


def test_every_named_lesson_declares_its_title(doc, course):
    del doc["lesson_titles"]["5.2"]
    errors = CR.check_course_refs(CONTENT.read_text(encoding="utf-8"), doc, *course)
    assert any("lesson 5.2 is named but has no entry in lesson_titles" in e for e in errors)


@pytest.mark.parametrize("case,old,new,needle", [
    ("l2_filter_case_insensitive", "  ELSE 0\n", "  ELSE NULL\n", "sql: no line is exactly 'ELSE 0'"),
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
    assert CAP.norm('"(Sample)  Retail  -  Apparel"') != CAP.norm('"(Sample) Retail - Apparel"')


def test_planned_capabilities_are_labelled_coming_soon(doc):
    # AgentQL keyword review and pinning are planned, near term: the game must not teach them as
    # shipped, and the comparison must say "Coming soon" where it describes them for AgentQL.
    scroll = _law(doc)["scroll"]
    agentql = scroll["columns"].index("AgentQL")
    rows = {r["label"]: r["cells"][agentql] for r in scroll["rows"]}
    assert rows["How a person checks it"].startswith("Coming soon")
    assert "Coming soon: pin it" in rows["Where the answer lives"]
    raw = CONTENT.read_text(encoding="utf-8")
    for shipped_claim in ("Still the keywords", "shown as keywords too", "Keyword Search and AgentQL produce ThoughtSpot Answers you can pin"):
        assert shipped_claim not in raw


# ---- packs, plugins and the engine's general rules (quest-pack design §3) ---------------------

def _copy_packs(tmp_path) -> pathlib.Path:
    packs = tmp_path / "packs"
    shutil.copytree(B.PACKS, packs, ignore=shutil.ignore_patterns("promo"))
    return packs


def test_unknown_content_keys_are_refused(doc, capture):
    doc["colour"] = "red"
    _encounter(doc)["mood"] = "grim"
    _encounter(doc)["points"][0]["sqll"] = ["typo"]
    errors = _errors(doc, capture)
    for key in ("colour", "mood", "sqll"):
        assert any(f"unknown key {key!r} (no check owns it)" in e for e in errors), key


def test_a_key_is_known_only_while_its_plugin_runs(doc, capture):
    # `case` belongs to agentql_capture: without that plugin it is an unknown key.
    pack = B.Pack("agentql")
    pack.doc = doc
    pack.manifest = dict(pack.manifest, checks=["course_refs", "agentql_rules"])
    compiler = B.Compiler(pack, B.load_plugins(["course_refs", "agentql_rules"]))
    compiler.compile()
    assert any("unknown key 'case'" in e for e in compiler.errors)
    assert any("agentql_capture did not fill the sql pane" in e for e in compiler.errors)


@pytest.mark.parametrize("bad_id,needle", [
    ("hall", "and not 'hall'"),
    ("Every-Product", "must be lowercase letters"),
    ("west_sales", "duplicate id 'west_sales'"),
])
def test_encounter_ids_follow_the_step_id_grammar(doc, capture, bad_id, needle):
    _encounter(doc)["id"] = bad_id
    assert any(needle in e for e in _errors(doc, capture))


def test_the_first_realm_cannot_be_sealed_when_it_unlocks_the_rest(doc, capture):
    law = _law(doc)
    law["sealed"], law["halls"], law["decree"] = True, [], []
    assert any("can't be sealed" in e for e in _errors(doc, capture))


def _in_scope_who_points(doc, capture):
    """(encounter, point) pairs whose highlighted SQL lies wholly within a row cap or null guard."""
    data, _ = _compile(doc, capture)
    out = []
    built = {e["id"]: e for r in data["realms"] for e in r["encounters"]}
    for e_raw in doc["encounters"]:
        e = built[e_raw["id"]]
        credit = RULES._credit_lines(e["panes"][1]["lines"])
        for raw, p in zip(e_raw["points"], e["points"]):
            lit = p["highlights"]["sql"]
            if raw["kind"] == "who" and isinstance(lit, list) and lit and set(lit) <= credit:
                out.append((e_raw["id"], raw))
    return out


def test_row_caps_and_null_guards_are_credited_to_thoughtspot_today(doc, capture):
    scope = _in_scope_who_points(doc, capture)
    assert {eid for eid, _ in scope} >= {"west_sales", "two_steps", "rank_in_region"}, scope
    assert all(raw["answer"] == "thoughtspot" for _, raw in scope)


@pytest.mark.parametrize("answer", ["model", "agentql"])
def test_crediting_a_row_cap_or_null_guard_to_anyone_else_fails(doc, capture, answer):
    for eid, raw in _in_scope_who_points(doc, capture):
        d = copy.deepcopy(doc)
        point = next(p for p in next(e for e in d["encounters"] if e["id"] == eid)["points"] if p == raw)
        point["answer"] = answer
        errors = _errors(d, capture)
        assert any("it asks about a row cap or a null guard, which ThoughtSpot adds" in e for e in errors), (eid, raw["ask"])


@pytest.mark.parametrize("sql,lit,inside", [
    (["SELECT a", "LIMIT 100000"], [1], True),
    (["SELECT a", "LIMIT 100000 OFFSET 5"], [1], False),                        # not a bare row cap
    (["SELECT CASE", '  WHEN sum("x") IS NOT NULL THEN sum("x")', "  ELSE 0", "END"], [1, 2], True),
    (["rank() over (order by CASE", '    WHEN sum("x") IS NOT NULL THEN sum("x")', "    ELSE 0", "  END desc)"],
     [3], False),                                                                 # END desc) runs past the guard
    (["CASE", '  WHEN "x" IS NOT NULL THEN "x"', "  ELSE 0", "END"], [1], False),  # no aggregate: the AgentQL's own CASE
    (["CASE", '  WHEN sum("x") IS NOT NULL THEN sum("y")', "  ELSE 0", "END"], [1], False),  # not the same aggregate
])
def test_the_crediting_scope_is_exactly_a_row_cap_or_a_full_null_guard(sql, lit, inside):
    assert (set(lit) <= RULES._credit_lines(sql)) is inside


# Made-up names stand in for the real list, so no published name is ever written here.
INVENTED = {"glimmerdeep", "ashen vale"}


def _invented(monkeypatch):
    import denylist as D
    hashes = {D.digest(n) for n in INVENTED}
    monkeypatch.setattr(D, "load", lambda *a, **k: hashes)
    return hashes


def test_the_denylist_hashes_words_and_two_word_names():
    import denylist as D
    hashes = {D.digest(n) for n in INVENTED}
    assert D.hits("Into the GLIMMERDEEP below", hashes) == ["glimmerdeep"]
    assert D.hits("The Ashen\n  Vale", hashes) == ["ashen vale"]
    assert D.hits("The White Peaks", hashes) == []
    assert D.hits("Glímmerdéep", hashes) == ["glimmerdeep"]           # accents don't hide a name
    assert all(len(h) == 20 and "glimmer" not in h for h in hashes)   # only hashes are committed


@pytest.mark.parametrize("where", ["packs/agentql/content.yaml", "packs/agentql/art/classic/mines",
                                   "packs/agentql/promo/encode_mp4.swift", "packs/agentql/maps/over.TMJ",
                                   "classic/game.html"])
def test_a_published_name_anywhere_in_the_pack_or_page_fails_the_build(tmp_path, monkeypatch, where):
    # Every file but known binaries, any suffix or none, any case; and the classic page itself.
    quest = tmp_path / "quest"
    shutil.copytree(B.PACKS, quest / "packs", ignore=shutil.ignore_patterns("*.png", "*.gif"))
    shutil.copytree(B.TEMPLATE.parent, quest / "classic")
    target = quest / where
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text((target.read_text(encoding="utf-8") if target.exists() else "") + "\n# the glimmerdeep\n",
                      encoding="utf-8")
    monkeypatch.setattr(B, "PACKS", quest / "packs")
    monkeypatch.setattr(B, "TEMPLATE", quest / "classic/game.html")
    _invented(monkeypatch)
    errors = B.build(check=True)[3]
    assert any("'glimmerdeep' is a name from a published work" in e for e in errors), errors


def test_the_committed_quest_uses_no_listed_name():
    import denylist as D
    assert D.scan(B.PACKS) == [] and D.scan(B.TEMPLATE.parent) == [] and D.scan(HERE) == []


def test_adding_names_writes_only_hashes(tmp_path):
    import denylist as D
    path = tmp_path / "denylist.txt"
    path.write_text("# header\n", encoding="utf-8")
    assert D.add(["Glimmerdeep", "ashen vale", ""], path) == 2
    text = path.read_text(encoding="utf-8")
    assert "glimmer" not in text.lower() and "ashen" not in text.lower() and text.startswith("# header")
    assert D.load(path) == {D.digest("glimmerdeep"), D.digest("ashen vale")}
    with pytest.raises(ValueError, match="more than two words"):
        D.add(["the ashen vale road"], path)


def test_two_packs_may_not_share_a_save_key(tmp_path):
    packs = _copy_packs(tmp_path)
    shutil.copytree(packs / "agentql", packs / "second")
    manifest = packs / "second/pack.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("id: agentql", "id: second")
                        .replace("publish_path: agentql-quest", "publish_path: second-quest"), encoding="utf-8")
    assert B.check_packs_unique(packs) == ["packs agentql and second share storage_key 'aqq'"]


def test_the_build_refuses_packs_that_share_a_save_key(tmp_path, monkeypatch):
    packs = _copy_packs(tmp_path)
    shutil.copytree(packs / "agentql", packs / "second")
    manifest = packs / "second/pack.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("id: agentql", "id: second")
                        .replace("publish_path: agentql-quest", "publish_path: second-quest"), encoding="utf-8")
    monkeypatch.setattr(B, "PACKS", packs)
    assert "packs agentql and second share storage_key 'aqq'" in B.build(check=True)[3]


@pytest.mark.parametrize("old,new,needle", [
    ("storage_key: aqq", "storage_key: AQQ!", "storage_key must be"),
    ("checks: [agentql_capture, course_refs, agentql_rules]", "checks: [agentql_capture, course_refs, agentql_rules, no_such]",
     "no plugin checks/no_such.py"),
    ("label: pane_sql_label,", "label: pane_missing,", "label 'pane_missing' is not in strings.yaml"),
    ("unlock: first_realm_first", "unlock: whenever", "unlock must be one of"),
    ("  foe: dragon\n", "", "lexicon must name exactly"),
    ("  model:       {label: MODEL,       group: rules}", "  model:       {label: MODEL,       group: loot}", "rule tag 'model' needs"),
])
def test_the_manifest_is_checked(tmp_path, old, new, needle):
    packs = _copy_packs(tmp_path)
    manifest = packs / "agentql/pack.yaml"
    text = manifest.read_text(encoding="utf-8")
    assert old in text
    manifest.write_text(text.replace(old, new), encoding="utf-8")
    assert any(needle in e for e in B.Pack("agentql", packs).errors)


def test_a_caption_must_name_only_what_something_provides(doc, capture):
    pack = B.Pack("agentql")
    pack.doc = doc
    pack.strings = dict(pack.strings, pane_sql_caption="Captured on {model}, by {wizard}.")
    _, errors = B.compile_pack(pack, {"agentql_capture": CAP.Capture(*capture, MODEL)})
    assert any("names {wizard}, which nothing provides" in e for e in errors)


# A second game: no plugins, nothing about AgentQL. The engine and its schema must carry it.
SECOND_PACK = {
    "pack.yaml": """
id: second
title: The Second Quest
publish_path: second-quest
storage_key: sq
unlock: first_realm_first
checks: []
sources: {}
panes:
  - {id: rune, from: content, match: contains, label: rune_label, name: rune_name, caption: ""}
rule_tags:
  lore: {label: LORE, group: rules}
lexicon: {guide: The Scribe, compiler: The Loom, foe: golem, reward: chest, currency: shells}
explore: {realms: []}
""",
    "strings.yaml": """
claim_true: True.
claim_false: False.
rune_label: THE RUNE
rune_name: The rune
""",
    "content.yaml": """
realms:
  - id: shore
    name: The Shore
    depth: Overview
    minutes: 2
    covers: Reading runes.
    halls:
      - id: first
        title: The First Hall
        teach: [A rune has two parts.]
        trials:
          - {kind: claim, claim: Runes have two parts., why: They do., truth: true}
          - kind: choice
            text: Which part comes first?
            why: The stem.
            options: [{text: The stem, correct: true}, {text: The leaf}]
    decree: [Runes have two parts.]
  - id: cave
    name: The Cave
    depth: Reads runes
    minutes: 2
    covers: One rune.
    encounters: [the_rune]
routes:
  - {who: Everyone, path: [shore, cave]}
encounters:
  - id: the_rune
    quest: Read this rune.
    rune: |
      stem
      leaf
    path:
      options:
        - {text: Read it, outcome: win, why: Yes.}
        - {text: Burn it, outcome: loss, why: No.}
    points:
      - kind: choice
        rune: [leaf]
        ask: What is the second part?
        hint: Look down.
        why: The leaf.
        rule: Every rune ends in a leaf
        rule_tag: lore
        options: [{text: The leaf, correct: true}, {text: The stem}]
    takeaway: Runes are read stem first.
""",
}


@pytest.fixture
def second_pack(tmp_path):
    packs = tmp_path / "packs"
    (packs / "second").mkdir(parents=True)
    for name, text in SECOND_PACK.items():
        (packs / "second" / name).write_text(text.lstrip(), encoding="utf-8")
    return B.Pack("second", packs)


def test_a_second_game_needs_only_a_pack(second_pack):
    assert second_pack.errors == []
    data, errors = B.compile_pack(second_pack)
    assert errors == []
    schema = B.pack_schema(second_pack)
    assert B.check_schema(data, schema) == []
    assert data["meta"] == {} and data["realms"][1]["encounters"][0]["refs"] == {}
    point = data["realms"][1]["encounters"][0]["points"][0]
    assert point["highlights"] == {"rune": [1]} and point["ruleTag"] == "lore"
    # Nothing AgentQL leaks into the second game's data or schema. ($id is the site's address,
    # checked below: every game is published under the repo's Pages host.)
    blob = json.dumps([data, {k: v for k, v in schema.items() if k != "$id"}]).lower()
    for word in ("agentql", "lesson", "module", "case", "model", "thoughtspot", "dragon", "sql"):
        assert word not in blob, word
    assert schema["$id"].endswith("/second-quest/quest.schema.json") and schema["title"] == "The Second Quest data"


def test_the_core_schema_alone_is_valid_for_a_pack_with_no_plugins():
    core = json.loads(B.CORE_SCHEMA.read_text(encoding="utf-8"))
    assert B.lint_schema(core, core) == []
    assert "$id" not in core  # each pack's generated schema sets its own, at the address it is published


# ---- review of PR 2a: holes in the new checks, and a second game that builds but breaks --------

def test_a_who_point_cannot_retag_its_answer(doc, capture):
    # answer: thoughtspot with rule_tag: model would show MODEL beside a null guard on the hoard.
    eid, raw = _in_scope_who_points(doc, capture)[0]
    point = next(p for p in next(e for e in doc["encounters"] if e["id"] == eid)["points"] if p == raw)
    point["rule_tag"] = "model"
    assert any("takes its rule tag from its answer" in e for e in _errors(doc, capture))


def test_agentql_halls_ask_claims_and_routes_only(doc, capture):
    _law(doc)["halls"][0]["trials"].append({"kind": "choice", "text": "Which is a Model?", "why": "This one.",
                                            "options": [{"text": "A", "correct": True}, {"text": "B"}]})
    assert any("halls ask claims and routes only, got 'choice'" in e for e in _errors(doc, capture))


def test_each_pack_schema_describes_its_own_game(schema):
    assert schema["description"].startswith("The data of AgentQL Quest")
    assert "empty here" not in schema["description"]


@pytest.mark.parametrize("level,edit", [
    ("realm", lambda d: _law(d).update(colour="red")),
    ("hall", lambda d: _law(d)["halls"][0].update(colour="red")),
    ("trial", lambda d: _law(d)["halls"][0]["trials"][0].update(colour="red")),
    ("path", lambda d: _encounter(d)["path"].update(colour="red")),
])
def test_unknown_keys_are_refused_at_every_level(doc, capture, level, edit):
    edit(doc)
    assert any("unknown key 'colour' (no check owns it)" in e for e in _errors(doc, capture)), level


@pytest.mark.parametrize("edit,needle", [
    (lambda d: _law(d).update(id="Law"), "realm 1: id 'Law' must be lowercase"),
    (lambda d: _realm(d, "mines").update(id="law"), "duplicate id 'law'"),
    (lambda d: _law(d)["halls"][1].update(id="two_paths"), "duplicate id 'two_paths'"),
    (lambda d: _law(d)["halls"][0].pop("id"), "id None must be lowercase"),
])
def test_realm_and_hall_ids_are_checked(doc, capture, edit, needle):
    edit(doc)
    assert any(needle in e for e in _errors(doc, capture))


def test_routes_name_only_realms(doc, capture):
    doc["routes"][0]["path"].append("the_far_marsh")
    assert any("unknown: ['the_far_marsh']" in e for e in _errors(doc, capture))


@pytest.mark.parametrize("old,new,needle", [
    ("id: agentql", "id: other", "id must be the folder name"),
    ("title: AgentQL Quest", "title: ''", "missing title"),
    ("publish_path: agentql-quest", "publish_path: Agentql Quest", "publish_path must be a folder name"),
    ("  lesson_sql: agents/cli/ts-object-model-agentql-query/references/lesson-sql.md",
     "  lesson_sql: no/such/file.md", "source 'lesson_sql' is not a file in the repo"),
    ("explore:\n  realms: []", "explore:\n  realms: mines", "explore.realms must be a list"),
    ("checks: [agentql_capture, course_refs, agentql_rules]", "checks: [agentql_capture, course_refs, agentql_rules, ../build]",
     "no plugin checks/../build.py"),
    ("unlock: first_realm_first", "unlock: none", "unlock must be one of"),
    ("lexicon:", "colour: red\nlexicon:", "unknown key 'colour'"),
    ("{id: scroll, from: content,", "{id: scroll, from: nowhere,", "from must be content or one of the pack's checks"),
    ("match: contains,", "match: regex,", "match must be one of"),
    ("{id: sql,    from: agentql_capture,", "{id: scroll, from: agentql_capture,", "id must be unique"),
    ("caption: pane_sql_caption}", "caption: no_such_caption}", "caption 'no_such_caption' is not in strings.yaml"),
    ("name: pane_sql_name,", "name: pane_sql_name, colour: red,", "needs exactly id, from, match, label, name, caption"),
])
def test_every_manifest_rule_is_checked(tmp_path, old, new, needle):
    packs = _copy_packs(tmp_path)
    manifest = packs / "agentql/pack.yaml"
    text = manifest.read_text(encoding="utf-8")
    assert old in text, old
    manifest.write_text(text.replace(old, new), encoding="utf-8")
    assert any(needle in e for e in B.Pack("agentql", packs).errors), B.Pack("agentql", packs).errors


def test_strings_keys_and_send_to_are_checked(doc, capture, tmp_path):
    packs = _copy_packs(tmp_path)
    strings = packs / "agentql/strings.yaml"
    strings.write_text(strings.read_text(encoding="utf-8") + "Bad Key: x\n", encoding="utf-8")
    assert any("'Bad Key' must be a lowercase key" in e for e in B.Pack("agentql", packs).errors)
    pack = B.Pack("agentql")
    pack.doc, pack.strings = doc, dict(pack.strings, send_to="Send it along")
    _, errors = B.compile_pack(pack, {"agentql_capture": CAP.Capture(*capture, MODEL)})
    assert "strings.yaml: send_to must name {engine}" in errors


def test_two_packs_may_not_share_a_pages_folder(tmp_path):
    packs = _copy_packs(tmp_path)
    shutil.copytree(packs / "agentql", packs / "second")
    manifest = packs / "second/pack.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("id: agentql", "id: second")
                        .replace("storage_key: aqq", "storage_key: sq"), encoding="utf-8")
    assert B.check_packs_unique(packs) == ["packs agentql and second share publish_path 'agentql-quest'"]


def test_a_plugin_source_the_pack_does_not_name_fails_before_compiling(tmp_path):
    packs = _copy_packs(tmp_path)
    manifest = packs / "agentql/pack.yaml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace("  learning_path: agents/cli/ts-object-model-agentql-query/references/learning-path.md\n", ""),
                        encoding="utf-8")
    data, errors = B.compile_pack(B.Pack("agentql", packs))
    assert data == {} and errors == ["pack.yaml: checks/course_refs.py reads the source 'learning_path', which sources doesn't name"]


def test_a_kind_belongs_to_one_owner(doc, capture, monkeypatch):
    monkeypatch.setattr(RULES, "TRIAL_KINDS", {"route", "claim"})
    monkeypatch.setattr(CR, "POINT_KINDS", {"who"}, raising=False)
    pack = B.Pack("agentql")
    pack.doc = doc
    compiler = B.Compiler(pack, [CAP, CR, RULES], {"agentql_capture": CAP.Capture(*capture, MODEL)})
    assert any("TRIAL_KINDS 'claim' already belongs to the engine" in e for e in compiler.errors)
    assert any("POINT_KINDS 'who' already belongs to course_refs" in e for e in compiler.errors)


def test_strings_are_filled_once():
    pack = B.Pack("agentql")
    pack.strings = dict(pack.strings, x="{a} and {b}")
    assert pack.string("x", a="{b}", b="two") == "{b} and two"


def _second(tmp_path, edit_text=None, files=None) -> B.Pack:
    packs = tmp_path / "packs"
    (packs / "second").mkdir(parents=True, exist_ok=True)
    for name, text in SECOND_PACK.items():
        if files and name in files:
            text = files[name]
        (packs / "second" / name).write_text(text.lstrip(), encoding="utf-8")
    return B.Pack("second", packs)


@pytest.mark.parametrize("file,old,new,needle", [
    ("strings.yaml", "claim_true: True.\n", "", "which has no claim_true"),
    ("pack.yaml", "{id: rune,", "{id: why,", "pane id 'why' is also a content key"),
    ("pack.yaml", "{id: rune,", "{id: path,", "pane id 'path' is also a content key"),
    ("content.yaml", "- {text: Burn it, outcome: loss, why: No.}", "- {text: Burn it, outcome: win, why: No.}",
     "exactly one win"),
    ("content.yaml", "- {text: Burn it, outcome: loss, why: No.}", "- {text: Burn it, outcome: maybe, why: No.}",
     "an outcome (win/loss/blocked)"),
    ("content.yaml", "options: [{text: The stem, correct: true}, {text: The leaf}]",
     "options: [{text: The stem}, {text: The leaf}]", "a choice needs text, why, 2+ options and exactly one correct"),
    ("content.yaml", "rule_tag: lore", "rule_tag: legend", "rule_tag must be one of ['lore']"),
])
def test_a_second_game_that_would_break_does_not_build(tmp_path, file, old, new, needle):
    text = SECOND_PACK[file]
    assert old in text, old
    pack = _second(tmp_path, files={file: text.replace(old, new)})
    errors = pack.errors or B.compile_pack(pack)[1]
    assert any(needle in e for e in errors), errors


@pytest.mark.parametrize("file,old,new,needle", [
    ("content.yaml", "- {text: Read it, outcome: win, why: Yes.}", "- {text: Read it, outcome: win, why: Yes., colour: red}",
     "unknown key 'colour'"),
    ("content.yaml", "    path:\n      options:", "    path:\n      colour: red\n      options:", "unknown key 'colour'"),
    ("pack.yaml", "explore: {realms: []}", "explore: {realms: [moon]}", "explore realm 'moon' is not a realm"),
    ("content.yaml", "    rune: |\n      stem\n      leaf\n", "", "missing the rune pane"),
    ("content.yaml", "        rune: [leaf]", "        rune: leaf", "rune must be a list of matches"),
])
def test_a_second_game_with_a_broken_path_pane_or_map_does_not_build(tmp_path, file, old, new, needle):
    text = SECOND_PACK[file]
    assert old in text, old
    pack = _second(tmp_path, files={file: text.replace(old, new)})
    errors = pack.errors or B.compile_pack(pack)[1]
    assert any(needle in e for e in errors), errors


def test_a_pack_needs_a_pane(tmp_path):
    text = SECOND_PACK["pack.yaml"]
    old = "panes:\n  - {id: rune, from: content, match: contains, label: rune_label, name: rune_name, caption: \"\"}\n"
    assert old in text
    assert "pack.yaml: needs at least one pane" in _second(tmp_path, files={"pack.yaml": text.replace(old, "panes: []\n")}).errors


def test_pane_ids_are_closed_in_the_schema(schema, built):
    assert schema["$defs"]["pane"]["properties"]["id"] == {"enum": ["scroll", "sql"]}
    built["realms"][1]["encounters"][0]["panes"][0]["id"] = "notes"
    assert any("'notes' is not one of ['scroll', 'sql']" in e for e in B.check_schema(built, schema))


def test_a_point_lighting_every_line_in_scope_is_still_in_scope():
    sql = ["SELECT CASE", '  WHEN sum("x") IS NOT NULL THEN sum("x")', "  ELSE 0", "END", "LIMIT 100000"]
    credit = RULES._credit_lines(sql)
    assert credit == {1, 2, 3, 4}            # SELECT CASE runs past the guard; END and LIMIT are in it
    assert {1, 2, 3, 4} <= credit and {4} <= credit


def test_a_capture_without_a_date_fails(doc, capture):
    _, cases = capture
    assert "lesson-sql.md: no capture date found in its header" in _compile(doc, (None, cases))[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_saves_under_the_packs_key(doc, capture, tmp_path):
    # Another pack's key: a page that still wrote aqq-* would fail the play-through's save checks.
    data, errors = _compile(doc, capture)
    assert errors == []
    data["pack"]["storage_key"] = "zz"
    page = tmp_path / "index.html"
    page.write_text(B.render(B.TEMPLATE.read_text(encoding="utf-8"), data, B.font_faces()), encoding="utf-8")
    r = subprocess.run(["node", str(HERE / "play_quest.js"), str(page)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_choice_options_take_only_text_and_correct(doc, capture):
    choice = next(p for p in _encounter(doc)["points"] if p["kind"] == "choice")
    choice["options"][0]["corect"] = True
    assert any("option 1: unknown key 'corect'" in e for e in _errors(doc, capture))


def test_a_who_point_lighting_exactly_the_lines_in_scope_must_credit_thoughtspot():
    rules = RULES.Rules(B.Pack("agentql"))
    panes = {"sql": ["SELECT a", "LIMIT 100000"], "scroll": ["SELECT a"]}
    errors = []
    RULES.point(rules, {"kind": "who", "answer": "model", "sql": ["LIMIT 100000"], "rule": "r"}, panes,
                {"sql": [1], "scroll": []}, "p", errors)
    assert any("row cap or a null guard" in e for e in errors), errors
