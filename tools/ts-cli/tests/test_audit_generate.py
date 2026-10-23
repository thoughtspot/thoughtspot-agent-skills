"""What is generated from the rule catalog (ts_cli/audit/generate.py).

Mapping-valued catalog forms — `message: {by_severity: …}`, `legacy_threshold:
{by_severity: …}`, severity maps, profile overrides and code rules that grade or set
thresholds in code — must render as text, per severity and per profile, never as a
Python data structure.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ts_cli.audit import generate
from ts_cli.audit.catalog_model import build_catalog, load_catalog
from ts_cli.audit.catalog_validate import validate_catalog

REPO = Path(__file__).resolve().parents[3]
_REPR = re.compile(r"\{'|'\}|\{\"|by_severity|Bands\(|Band\(|frozenset|\bNone\b")


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def meta(cat):
    return generate.report_meta(cat)


@pytest.fixture(scope="module")
def doc(cat):
    return generate.catalog_markdown(cat)


#: A frozen toy catalog, one rule per catalog form the renderer must turn into text.
#: The renderer's assertions read THESE rules, never the shipped ones, so changing or
#: retiring a shipped rule (rule-authoring.md procedures 2 and 3) cannot break them.
_TOY_CATEGORIES = [
    {"id": "A", "angle_key": "ai", "label": "AI Readiness", "order": 1, "description": "a"},
    {"id": "D", "angle_key": "data_modeling", "label": "Data Modeling", "order": 2,
     "description": "d"},
]
_TOY_PROFILES = [{"id": "spotter", "label": "Spotter-ready", "default": False},
                 {"id": "general", "label": "General", "default": True}]
_EX = {"fires": {"fixture": "toy_fires", "severity": "HIGH"}, "silent": {"fixture": "toy_silent"}}
_TOY_RULES = yaml.safe_load("""
- id: T1
  title: Toy outer join
  categories: [D]
  requires: [model_tml]
  scope: join
  aggregate: {mode: each, where: {field: "@join_type", in: [OUTER, LEFT_OUTER]}}
  severity: {field: "@join_type", map: {OUTER: HIGH}, default: INFO}
  message:
    by_severity:
      HIGH: Full outer join
      INFO: "{@join_type} join"
  remediation: Inner-join it, or document why it is outer
- id: T2
  title: Toy coverage
  categories: [A]
  requires: [model_tml]
  scope: model
  aggregate: {mode: ratio, over: model.column, match: {field: description, nonblank: true}}
  bands:
    direction: higher_is_better
    unit: percent
    levels: [{op: lt, value: 25, severity: HIGH}, {op: lt, value: 50, severity: MEDIUM}]
  profiles:
    spotter:
      bands:
        direction: higher_is_better
        unit: percent
        levels: [{op: lt, value: 47.5, severity: HIGH}, {op: lt, value: 95, severity: MEDIUM}]
      legacy_threshold: {green: 95, assessment: "{profile_label}", yellow: 47.5}
  message: "{matched}/{total} described"
  legacy_threshold: {green: 50, assessment: "{profile_label}", yellow: 25}
- id: T3
  title: Toy uncoached
  categories: [A]
  requires: [model_tml, ai_instructions]
  scope: model
  aggregate: {mode: each, where: {field: "@is_coached", truthy: false}}
  severity: MEDIUM
  profiles: {spotter: {severity: HIGH}}
  message: Not coached
- id: T4
  title: Toy depth
  categories: [D]
  requires: [model_tml]
  scope: model
  aggregate: {mode: each, measure: "@join_depth"}
  bands:
    direction: lower_is_better
    unit: depth
    levels: [{op: gt, value: 5, severity: HIGH}, {op: gt, value: 3, severity: MEDIUM}]
  message: "Depth {value}"
- id: T5
  title: Toy complexity
  categories: [D]
  requires: [model_tml]
  implementation: code:model_complexity
  scope: model
  message: "{value} {measure} (>{yellow} HIGH, >{green} MEDIUM)"
- id: T6
  title: Toy readiness
  categories: [A]
  requires: [model_tml]
  uses: [ai_instructions]
  implementation: code:spotter_readiness
  scope: model
  bands:
    direction: higher_is_better
    unit: score
    levels: [{op: lt, value: 50, severity: HIGH}, {op: lt, value: 80, severity: MEDIUM}]
  message: "Score {score:.0f}"
- id: T7
  title: Toy credential
  categories: [D]
  requires: [model_tml]
  scope: model.column
  aggregate: {mode: each, where: {field: name, regex: "(?i)token|password"}}
  severity: {field: name, map: {token: MEDIUM}, default: CRITICAL}
  message:
    by_severity:
      MEDIUM: "Token {name}"
      CRITICAL: "Credential {name}"
  legacy_threshold:
    by_severity:
      MEDIUM: {high_overlap: 0.5}
- id: T8
  title: Toy retired
  description: Retired because the toy says so.
  status: retired
  categories: [D]
  scope: model
""")
for _rule in _TOY_RULES:
    if _rule.get("status") != "retired":
        _rule["examples"] = _EX


@pytest.fixture(scope="module")
def toy():
    raw = {"categories.yaml": _TOY_CATEGORIES, "profiles.yaml": _TOY_PROFILES,
           "rules/toy.yaml": _TOY_RULES}
    toy_cat = build_catalog(raw)
    assert validate_catalog(toy_cat, raw) == []      # the toy is a real, valid catalog
    return toy_cat


@pytest.fixture(scope="module")
def toy_meta(toy):
    return generate.report_meta(toy)


@pytest.fixture(scope="module")
def toy_doc(toy):
    return generate.catalog_markdown(toy)


def _row(doc: str, rule_id: str) -> str:
    [row] = [ln for ln in doc.splitlines() if ln.startswith(f"| {rule_id} | **")]
    return row


def test_no_data_structure_is_rendered_anywhere(meta, doc, toy_meta, toy_doc):
    for m, d in ((meta, doc), (toy_meta, toy_doc)):
        for rid, check in m["checks"].items():
            for key in ("thresholds", "message"):
                assert not _REPR.search(check[key]), (rid, key, check[key])
        assert not _REPR.search(d), _REPR.search(d)


def test_message_by_severity_renders_one_entry_per_severity(toy_meta, toy_doc):
    assert toy_meta["checks"]["T1"]["message"] == \
        "HIGH: “Full outer join”; INFO: “{join type} join”"
    assert "MEDIUM: “Token {name}”" in _row(toy_doc, "T7")


def test_legacy_threshold_by_severity_and_per_profile(toy_doc):
    rows = {ln.split(" | ")[0][2:]: ln for ln in toy_doc.splitlines()
            if re.match(r"\| [A-Z]\d+ \| (?!\*\*)", ln)}
    assert rows["T7"] == "| T7 | MEDIUM: high_overlap=0.5 |"
    # per profile, with {profile_label} rendered as each profile's label
    assert rows["T2"] == ("| T2 | Spotter-ready: green=95, assessment=Spotter-ready, "
                          "yellow=47.5 · General: green=50, assessment=General, yellow=25 |")
    # a code rule that sets its own threshold per finding
    assert rows["T5"] == ("| T5 | set per finding — graded per size measure (tables, "
                          "columns, joins, join depth, formulas), each against its own "
                          "lines |")


def test_profile_overrides_render_per_profile(toy_meta):
    assert toy_meta["checks"]["T2"]["thresholds"] == (
        "Spotter-ready: HIGH < 47.5%, MEDIUM < 95% · General: HIGH < 25%, MEDIUM < 50%")
    assert toy_meta["checks"]["T3"]["thresholds"] == "Spotter-ready: HIGH · General: MEDIUM"
    assert toy_meta["checks"]["T4"]["thresholds"] == "HIGH > 5, MEDIUM > 3"


def test_severity_maps_and_code_rules_render_as_text(toy_meta):
    assert toy_meta["checks"]["T1"]["thresholds"] == \
        "HIGH when the join type is OUTER; otherwise INFO"
    assert toy_meta["checks"]["T7"]["thresholds"] == \
        "MEDIUM when the name is token; otherwise CRITICAL"
    assert toy_meta["checks"]["T5"]["thresholds"] == (
        "graded per size measure (tables, columns, joins, join depth, formulas), each "
        "against its own lines — HIGH, MEDIUM")
    assert toy_meta["checks"]["T6"]["thresholds"] == "HIGH < 50, MEDIUM < 80"


def test_report_meta_shape(cat, meta):
    assert [c["id"] for c in meta["categories"]] == list(cat.categories)
    assert {p["id"] for p in meta["profiles"]} == set(cat.profiles)
    active = [r for r in cat.rules.values() if r.status == "active"]
    assert set(meta["checks"]) == {r.id for r in active}
    views = {}
    for rule in active:
        for view in rule.views:
            views.setdefault(view, []).append(rule.id)
    assert {v: sorted(ids) for v, ids in meta["views"].items()} == \
        {v: sorted(ids) for v, ids in views.items()}
    for rule in active:
        assert meta["checks"][rule.id]["desc"] == rule.title, rule.id


def test_report_meta_carries_titles_and_remediation(toy_meta):
    assert toy_meta["checks"]["T1"]["desc"] == "Toy outer join"
    assert toy_meta["checks"]["T1"]["remediation"] == "Inner-join it, or document why it is outer"
    assert "T8" not in toy_meta["checks"]                 # retired: not in the report meta


def test_doc_lists_every_active_rule_under_each_category_and_retired_ones(cat, doc):
    retired_part = doc[doc.index("### Retired rules"):]
    for rule in cat.rules.values():
        rows = [ln for ln in doc.splitlines() if ln.startswith(f"| {rule.id} |")]
        if rule.status == "retired":
            assert len(rows) == 1 and rows[0] in retired_part, rule.id
        else:
            assert len([r for r in rows if r.startswith(f"| {rule.id} | **")]) == \
                len(rule.categories), rule.id


def test_toy_retired_rule_is_listed_with_its_reason(toy_doc):
    retired_part = toy_doc[toy_doc.index("### Retired rules"):]
    assert "| T8 | Toy retired | Retired because the toy says so. |" in retired_part


def test_pipes_in_rule_text_are_escaped():
    assert generate._cell("a | b\n c") == "a \\| b c"


def test_render_doc_needs_the_markers():
    with pytest.raises(ValueError, match="markers"):
        generate.render_doc("no markers here", load_catalog())


def _repo_copy(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / generate.DOC_REL).parent.mkdir(parents=True)
    (root / generate.DOC_REL).write_text((REPO / generate.DOC_REL).read_text())
    import shutil
    shutil.copytree(REPO / generate.CATALOG_REL, root / generate.CATALOG_REL)
    return root


def test_check_fails_when_the_catalog_changes(tmp_path):
    root = _repo_copy(tmp_path)
    assert generate.check(root) == []
    # Any rule's title will do: edit the first one in perf.yaml, whatever it says.
    rules = root / generate.CATALOG_REL / "rules" / "perf.yaml"
    rules.write_text(re.sub(r"(?m)^  title: ", "  title: Edited ", rules.read_text(), count=1))
    assert generate.check(root) and "stale" in generate.check(root)[0]
    assert generate.write(root) is True and generate.check(root) == []


def test_cli_check_exit_codes(tmp_path):
    root = _repo_copy(tmp_path)
    cmd = [sys.executable, "-m", "ts_cli.audit.generate", "--root", str(root), "--check"]
    env = {**os.environ, "PYTHONPATH": str(REPO / "tools" / "ts-cli")}
    assert subprocess.run(cmd, capture_output=True, text=True, env=env).returncode == 0
    doc = root / generate.DOC_REL
    doc.write_text(re.sub(r"(?m)^(\| [A-Z]\d+ \| \*\*)", r"\1Edited. ", doc.read_text(), count=1))
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 1 and "stale" in res.stdout


def test_check_reports_a_malformed_catalog_without_a_traceback(tmp_path):
    root = _repo_copy(tmp_path)
    (root / generate.CATALOG_REL / "rules" / "perf.yaml").write_text("- id: P1\n  title: [\n")
    problems = generate.check(root)
    assert problems and "perf.yaml" in problems[0]
    cmd = [sys.executable, "-m", "ts_cli.audit.generate", "--root", str(root), "--check"]
    env = {**os.environ, "PYTHONPATH": str(REPO / "tools" / "ts-cli")}
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 1 and "Traceback" not in res.stderr, res.stderr
    assert "FAIL" in res.stdout and "perf.yaml" in res.stdout


# ── generated text never shows an engine identifier (final review I2) ────────
# The report, the ERD's "Fix." line and check-catalog.md are read by audit readers:
# a derived field reads as its registered label, a code rule as its registration's.

_ENGINE_ID = re.compile(r"@[A-Za-z_]\w*|\bcode:[a-z_]\w*|\bengine/")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def test_shipped_report_meta_and_doc_show_no_engine_identifiers(meta, cat):
    found = sorted({m for s in _strings(meta) for m in _ENGINE_ID.findall(s)})
    assert found == []
    doc = generate.catalog_markdown(cat)
    assert _ENGINE_ID.findall(doc) == []


@pytest.mark.parametrize("severity, text", [
    ({"field": "@join_type", "map": {"OUTER": "HIGH"}, "default": "INFO"},
     "HIGH when the join type is OUTER; otherwise INFO"),
    ({"field": "@is_fact_to_fact_join", "map": {True: "MEDIUM"}, "default": "INFO"},
     "MEDIUM when the join links two fact tables; otherwise INFO"),
    ({"field": "@owning_table_has_rls", "map": {False: "HIGH"}, "default": "INFO"},
     "HIGH unless the column's table has row-level security; otherwise INFO"),
    ({"field": "@credential_term", "map": {None: "LOW"}, "default": "HIGH"},
     "LOW when the credential word in the column name is absent; otherwise HIGH"),
    ({"field": "properties.column_type", "map": {"MEASURE": "LOW"}, "default": "INFO"},
     "LOW when the column type is MEASURE; otherwise INFO"),
])
def test_severity_maps_read_as_words(severity, text):
    assert generate.severity_text(severity) == text


@pytest.mark.parametrize("template, text", [
    ("{@join_type} join", "{join type} join"),
    ("tables: {@fact_tables:head3}", "tables: {fact tables, first 3}"),
    ("keys: {@varchar_join_keys:all}", "keys: {string-typed join keys}"),
    ("'{@join_from_name}' -> '{obj.with}'", "'{table the join starts from}' -> '{with}'"),
    ("{count}/{total} ({pct:.0f}%)", "{count}/{total} ({pct:.0f}%)"),
])
def test_message_placeholders_read_as_words(template, text):
    assert generate.template_text(template) == text
