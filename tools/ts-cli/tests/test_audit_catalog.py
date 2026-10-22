"""Tests for the audit rule catalog: data model, loader and validator.

The catalog is data (YAML under ts_cli/audit/catalog/); these tests prove a mistyped
rule fails loudly — unknown keys, operators, modes, scopes, data requirements,
categories, duplicate ids, profile overrides of what a rule *means*, mis-ordered bands
and missing examples — and that the package ships the catalog files.
"""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml

from ts_cli.audit.catalog_model import (
    Band,
    Bands,
    Catalog,
    CatalogError,
    Rule,
    load_catalog,
    load_raw,
)
from ts_cli.audit.catalog_validate import (
    MODES,
    OPERATORS,
    OVERRIDABLE,
    REQUIRES,
    SCOPES,
    SEVERITIES,
    check_catalog,
    validate_catalog,
)

PKG_CATALOG = Path(__file__).resolve().parents[1] / "ts_cli" / "audit" / "catalog"


def _good_rule(**overrides) -> dict:
    """An A6-shaped rule (the plan's worked example) that validates clean."""
    rule = {
        "id": "A6",
        "title": "Measure AI context coverage below threshold",
        "description": "Visible measures should carry structured AI context.",
        "status": "active",
        "categories": ["A"],
        "requires": ["model_tml"],
        "implementation": "declarative",
        "scope": "model",
        "aggregate": {
            "mode": "ratio",
            "over": "model.column",
            "where": {"all": [
                {"field": "properties.column_type", "eq": "MEASURE"},
                {"not": {"field": "properties.is_hidden", "truthy": True}},
            ]},
            "match": {"field": "properties.ai_context", "nonblank": True},
        },
        "bands": {
            "direction": "higher_is_better",
            "unit": "percent",
            "levels": [
                {"op": "lt", "value": 40, "severity": "HIGH"},
                {"op": "lt", "value": 80, "severity": "MEDIUM"},
            ],
        },
        "profiles": {
            "general": {
                "bands": {"direction": "higher_is_better", "unit": "percent",
                          "levels": [{"op": "lt", "value": 80, "severity": "LOW"}]},
            },
        },
        "message": "{matched}/{total} measures have AI context ({pct:.0f}%)",
        "legacy_threshold": {"green": 80, "yellow": 40.0, "assessment": "{profile_label}"},
        "remediation": "Add ai_context to each measure — run /ts-object-model-coach.",
        "examples": {
            "fires": {"fixture": "model_measures_no_ai_context", "profile": "spotter",
                      "severity": "HIGH"},
            "silent": {"fixture": "model_measures_with_ai_context", "profile": "spotter"},
        },
    }
    rule.update(overrides)
    return rule


def _catalog_dir(tmp_path: Path, rules_by_file: dict[str, list]) -> Path:
    """A temp catalog: the shipped categories/profiles plus the given rule files."""
    root = tmp_path / "catalog"
    (root / "rules").mkdir(parents=True)
    for name in ("categories.yaml", "profiles.yaml"):
        shutil.copy(PKG_CATALOG / name, root / name)
    for stem, rules in rules_by_file.items():
        (root / "rules" / f"{stem}.yaml").write_text(yaml.safe_dump(rules, sort_keys=False))
    return root


def _problems(tmp_path: Path, rules_by_file: dict[str, list]) -> list[str]:
    root = _catalog_dir(tmp_path, rules_by_file)
    return validate_catalog(load_catalog(root), load_raw(root))


# ── shipped catalog ──────────────────────────────────────────────────────────

def test_loads_categories_and_profiles():
    cat = load_catalog(PKG_CATALOG)
    assert isinstance(cat, Catalog)
    assert list(cat.categories) == ["A", "D", "H", "P", "S"]
    assert [c.label for c in cat.categories.values()] == [
        "AI Readiness", "Data Modeling", "Human Readiness", "Performance", "Security"]
    assert [c.order for c in cat.categories.values()] == sorted(
        c.order for c in cat.categories.values())
    assert {p: cat.profiles[p].label for p in cat.profiles} == {
        "spotter": "Spotter-ready", "general": "General"}
    assert [p.id for p in cat.profiles.values() if p.default] == ["general"]
    assert cat.default_profile() == "general"


def test_shipped_catalog_is_valid():
    cat, problems = check_catalog()
    assert problems == []
    assert set(cat.categories) == {"A", "D", "H", "P", "S"}


def test_package_ships_catalog():
    cat = load_catalog()  # no args: the package's own catalog/
    assert list(cat.categories) == ["A", "D", "H", "P", "S"]
    # …and every catalog file is declared as package data, so a wheel install has it.
    pyproject = PKG_CATALOG.parents[2] / "pyproject.toml"
    globs = _package_data_globs(pyproject.read_text())
    pkg_root = PKG_CATALOG.parents[1]  # ts_cli/
    # Path.glob, not fnmatch: fnmatch's `*` crosses `/`, so `audit/catalog/*.yaml` would
    # appear to cover rules/ai.yaml while setuptools would not ship it.
    covered = {p for g in globs for p in pkg_root.glob(g)}
    shipped = sorted(PKG_CATALOG.rglob("*.yaml"))
    assert shipped, "catalog has no YAML files"
    for path in shipped:
        assert path in covered, f"{path.relative_to(pkg_root)} not in package-data"
    assert {p.name for p in shipped} >= {
        "categories.yaml", "profiles.yaml", "ai.yaml", "data.yaml", "human.yaml",
        "perf.yaml", "security.yaml"}


def _package_data_globs(text: str) -> list[str]:
    """The `"ts_cli" = [...]` list under [tool.setuptools.package-data] (3.10-safe)."""
    section = text.split("[tool.setuptools.package-data]", 1)[1].split("\n[", 1)[0]
    line = next(ln for ln in section.splitlines() if ln.strip().startswith('"ts_cli"'))
    body = line.split("=", 1)[1].strip().strip("[]")
    return [g.strip().strip('"') for g in body.split(",") if g.strip()]


def test_vocabulary_constants():
    assert SEVERITIES == ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    assert OVERRIDABLE == {"status", "bands", "severity", "message", "remediation"}
    assert {"each", "ratio", "count", "group", "pairwise", "composite"} == set(MODES)
    assert {"model", "model.column", "join", "set", "metadata"} <= set(SCOPES)
    assert {"model_tml", "answers", "sets"} <= set(REQUIRES)
    assert {"eq", "regex", "not_regex", "all", "any", "not", "count"} <= set(OPERATORS)


# ── the good rule is good (otherwise every rejection test passes trivially) ──

def test_good_rule_validates_clean(tmp_path):
    root = _catalog_dir(tmp_path, {"ai": [_good_rule()]})
    cat = load_catalog(root)
    assert validate_catalog(cat, load_raw(root)) == []
    rule = cat.rules["A6"]
    assert isinstance(rule, Rule)
    assert rule.bands == Bands("higher_is_better", "percent",
                               [Band("lt", 40.0, "HIGH"), Band("lt", 80.0, "MEDIUM")])
    assert rule.source_file == "rules/ai.yaml"
    assert rule.views == []


# ── rejections ───────────────────────────────────────────────────────────────

def test_unknown_key_names_file_and_rule(tmp_path):
    problems = _problems(tmp_path, {"ai": [_good_rule(thresholds={"green": 80})]})
    assert any(p.startswith("rules/ai.yaml: A6:") and "thresholds" in p for p in problems), problems


def _with_operator(rule):
    rule["aggregate"]["match"] = {"field": "properties.ai_context", "equals": "x"}
    return "equals"


def _with_mode(rule):
    rule["aggregate"]["mode"] = "average"
    return "average"


def _with_scope(rule):
    rule["scope"] = "model.colum"
    return "model.colum"


def _with_requires(rule):
    rule["requires"] = ["model_tmls"]
    return "model_tmls"


@pytest.mark.parametrize("mutate, word", [
    (_with_operator, "operator"),
    (_with_mode, "mode"),
    (_with_scope, "scope"),
    (_with_requires, "requires"),
])
def test_unknown_operator_mode_scope_requires_rejected(tmp_path, mutate, word):
    rule = copy.deepcopy(_good_rule())
    bad = mutate(rule)
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(p.startswith("rules/ai.yaml: A6:") and word in p and bad in p
               for p in problems), problems


def test_nested_operator_inside_count_and_not_is_checked(tmp_path):
    rule = _good_rule()
    rule["aggregate"]["where"] = {"not": {"count": "model.column",
                                          "where": {"field": "name", "matches": "x"},
                                          "gt": 1}}
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any("unknown operator 'matches'" in p for p in problems), problems


def test_registered_derived_field_accepted(tmp_path):
    rule = _good_rule()
    rule["aggregate"]["match"] = {"field": "@is_indexed", "truthy": True}
    assert _problems(tmp_path, {"ai": [rule]}) == []


@pytest.mark.parametrize("where", ["match", "severity", "measure", "key", "parent",
                                   "inner", "inner_known", "message"])
def test_unknown_derived_field_rejected(tmp_path, where):
    rule = _good_rule()
    if where in ("inner", "inner_known"):
        name = "no_such_field" if where == "inner" else "is_indexed"
        rule["aggregate"]["match"] = {"field": f"properties.@{name}", "truthy": True}
        problems = _problems(tmp_path, {"ai": [rule]})
        assert any("must be the whole path" in p for p in problems), problems
        return
    if where == "message":
        rule.update(bands=None, profiles={}, severity="LOW", message="{@no_such_field}",
                    aggregate={"mode": "each"})
    elif where == "match":
        rule["aggregate"]["match"] = {"field": "@no_such_field", "truthy": True}
    elif where == "parent":
        rule["aggregate"]["match"] = {"field": "parent.@no_such_field", "truthy": True}
    elif where == "severity":
        rule.update(bands=None, profiles={},
                    severity={"field": "@no_such_field", "map": {"x": "HIGH"}, "default": "LOW"},
                    aggregate={"mode": "each"})
    elif where == "measure":
        rule["aggregate"] = {"mode": "each", "measure": "@no_such_field"}
    else:
        rule.update(bands=None, profiles={}, severity="HIGH", aggregate={
            "mode": "group", "kind": "duplicates", "key": ["name", "@no_such_field"]})
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any("unknown derived field '@no_such_field'" in p for p in problems), problems


def test_duplicate_id_rejected(tmp_path):
    problems = _problems(tmp_path, {"ai": [_good_rule()], "data": [_good_rule()]})
    assert any("A6:" in p and "duplicate id" in p for p in problems), problems


def test_unknown_category_rejected(tmp_path):
    problems = _problems(tmp_path, {"ai": [_good_rule(categories=["A", "X"])]})
    assert any(p.startswith("rules/ai.yaml: A6:") and "unknown category 'X'" in p
               for p in problems), problems


def test_unknown_profile_rejected(tmp_path):
    rule = _good_rule(profiles={"strict": {"severity": "HIGH"}})
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any("unknown profile 'strict'" in p for p in problems), problems


def test_profile_override_of_non_overridable_key_rejected(tmp_path):
    rule = _good_rule(profiles={"general": {"scope": "table"}})
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(p.startswith("rules/ai.yaml: A6:") and "profiles.general.scope" in p
               and "not overridable" in p for p in problems), problems


def test_merged_bands_must_be_ordered(tmp_path):
    rule = _good_rule(profiles={"general": {"bands": {
        "direction": "higher_is_better", "unit": "percent",
        "levels": [{"op": "lt", "value": 80, "severity": "MEDIUM"},
                   {"op": "lt", "value": 40, "severity": "HIGH"}]}}})
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(p.startswith("rules/ai.yaml: A6:") and "profiles.general.bands" in p
               and "levels must be ordered worst first" in p for p in problems), problems


def test_catalog_bands_ordered_for_lower_is_better(tmp_path):
    rule = _good_rule(bands={"direction": "lower_is_better", "unit": "count", "levels": [
        {"op": "gt", "value": 75, "severity": "MEDIUM"},
        {"op": "gt", "value": 150, "severity": "HIGH"}]})
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any("bands" in p and "levels must be ordered worst first" in p
               for p in problems), problems
    rule["bands"]["levels"].reverse()
    assert _problems(tmp_path / "ok", {"ai": [rule]}) == []


def test_band_op_must_fit_direction(tmp_path):
    rule = _good_rule(bands={"direction": "higher_is_better", "unit": "percent",
                             "levels": [{"op": "gt", "value": 40, "severity": "HIGH"}]})
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any("'gt'" in p and "higher_is_better" in p for p in problems), problems


def test_missing_examples_rejected(tmp_path):
    problems = _problems(tmp_path, {"ai": [_good_rule(examples={})]})
    assert any(p.startswith("rules/ai.yaml: A6:") and "fires" in p for p in problems), problems
    assert any(p.startswith("rules/ai.yaml: A6:") and "silent" in p for p in problems), problems


def test_retired_rule_needs_no_examples(tmp_path):
    rule = _good_rule(status="retired")
    del rule["examples"]
    assert _problems(tmp_path, {"human": [rule]}) == []


def test_unknown_view_and_bad_implementation_rejected(tmp_path):
    rule = _good_rule(views=["cleanup", "trash"], implementation="python:foo")
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any("unknown view 'trash'" in p for p in problems), problems
    assert any("implementation" in p and "python:foo" in p for p in problems), problems


def test_mapping_where_an_id_belongs_is_a_problem_not_a_crash(tmp_path):
    rule = _good_rule(categories=[{"A": 1}])
    rule["examples"]["silent"]["profile"] = ["general"]
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any("unknown category" in p for p in problems), problems
    assert any("examples.silent.profile" in p for p in problems), problems


def test_validator_collects_every_problem(tmp_path):
    rule = _good_rule(scope="nowhere", requires=["nothing"], categories=["Z"])
    problems = _problems(tmp_path, {"ai": [rule]})
    assert len(problems) >= 3
    assert all(p.startswith("rules/ai.yaml: A6:") for p in problems), problems


# ── loader shape errors ──────────────────────────────────────────────────────

def test_loader_rejects_non_list_rule_file(tmp_path):
    root = _catalog_dir(tmp_path, {})
    (root / "rules" / "ai.yaml").write_text("id: A6\n")
    with pytest.raises(CatalogError) as exc:
        load_catalog(root)
    assert exc.value.file == "rules/ai.yaml"
    assert "rules/ai.yaml" in str(exc.value)


def test_loader_shape_error_names_file_and_rule(tmp_path):
    root = _catalog_dir(tmp_path, {"ai": [_good_rule(categories="A")]})
    with pytest.raises(CatalogError) as exc:
        load_catalog(root)
    assert (exc.value.file, exc.value.rule_id) == ("rules/ai.yaml", "A6")
    assert str(exc.value).startswith("rules/ai.yaml: A6:")


def test_loader_rejects_invalid_yaml(tmp_path):
    root = _catalog_dir(tmp_path, {})
    (root / "rules" / "ai.yaml").write_text("- id: [unclosed\n")
    with pytest.raises(CatalogError) as exc:
        load_catalog(root)
    assert exc.value.file == "rules/ai.yaml"


def test_check_catalog_reports_loader_errors_as_problems(tmp_path):
    root = _catalog_dir(tmp_path, {})
    (root / "rules" / "ai.yaml").write_text("id: A6\n")
    cat, problems = check_catalog(root)
    assert cat is None
    assert len(problems) == 1 and problems[0].startswith("rules/ai.yaml:")


# ── review round 1: typos must fail, never silently alter a rule ─────────────

@pytest.mark.parametrize("typo", ["wher", "mach", "ovr"])
def test_unknown_aggregate_key_rejected(tmp_path, typo):
    rule = _good_rule()
    rule["aggregate"][typo] = rule["aggregate"].pop(
        {"wher": "where", "mach": "match", "ovr": "over"}[typo])
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(p.startswith("rules/ai.yaml: A6:") and f"aggregate: unknown key '{typo}'" in p
               for p in problems), problems


@pytest.mark.parametrize("mode", ["ratio", "count"])
def test_ratio_and_count_need_over(tmp_path, mode):
    rule = _good_rule()
    rule["aggregate"]["mode"] = mode
    del rule["aggregate"]["over"]
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any("aggregate.over is required" in p and mode in p for p in problems), problems


def test_each_mode_needs_no_over(tmp_path):
    rule = _good_rule(aggregate={"mode": "each",
                                 "where": {"field": "join_type", "eq": "OUTER"}},
                      bands=None, profiles={}, severity="HIGH", message="{name}")
    assert _problems(tmp_path, {"data": [rule]}) == []


def _sev_map(**overrides):
    sev = {"field": "join_type", "map": {"OUTER": "HIGH", "LEFT_OUTER": "INFO"},
           "default": "MEDIUM"}
    sev.update(overrides)
    return sev


def test_mapping_severity_shape_accepted(tmp_path):
    rule = _good_rule(bands=None, severity=_sev_map(), message="{name}",
                      aggregate={"mode": "each", "where": {"field": "x", "exists": True}})
    rule["profiles"] = {"general": {"severity": _sev_map(default="LOW")}}
    assert _problems(tmp_path, {"data": [rule]}) == []


@pytest.mark.parametrize("sev, needle", [
    (_sev_map(feild="x"), "unknown key 'feild'"),
    (_sev_map(map={"OUTER": "HIHG"}), "unknown severity 'HIHG'"),
    (_sev_map(default="MED"), "unknown severity 'MED'"),
    ({"map": {"OUTER": "HIGH"}, "default": "LOW"}, "severity.field"),
    ({"field": "x", "default": "LOW"}, "severity.map"),
    ({"field": "x", "map": {"OUTER": "HIGH"}}, "severity.default"),
    (_sev_map(map=[]), "severity.map"),
])
def test_mapping_severity_shape_enforced(tmp_path, sev, needle):
    rule = _good_rule(bands=None, severity=sev,
                      aggregate={"mode": "each", "where": {"field": "x", "exists": True}})
    problems = _problems(tmp_path, {"data": [rule]})
    assert any(p.startswith("rules/data.yaml: A6:") and needle in p for p in problems), problems


def test_profile_mapping_severity_is_checked(tmp_path):
    rule = _good_rule(profiles={"general": {"severity": _sev_map(wat=1)}})
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any("profiles.general.severity" in p and "unknown key 'wat'" in p
               for p in problems), problems


def test_missing_rules_dir_is_an_error(tmp_path):
    root = _catalog_dir(tmp_path, {})
    (root / "rules").rmdir()
    with pytest.raises(CatalogError) as exc:
        load_catalog(root)
    assert exc.value.file == "rules"


@pytest.mark.parametrize("name", ["ai.yml", "ai.YAML", "notes.txt"])
def test_non_yaml_file_in_rules_is_an_error(tmp_path, name):
    root = _catalog_dir(tmp_path, {})
    (root / "rules" / name).write_text(yaml.safe_dump([_good_rule()]))
    with pytest.raises(CatalogError) as exc:
        load_catalog(root)
    assert exc.value.file == f"rules/{name}"
    assert ".yaml" in exc.value.message


def test_dotfiles_in_rules_are_ignored(tmp_path):
    root = _catalog_dir(tmp_path, {"ai": [_good_rule()]})
    (root / "rules" / ".DS_Store").write_bytes(b"\x00")
    assert list(load_catalog(root).rules) == ["A6"]


@pytest.mark.parametrize("expr, needle", [
    ({"field": "x", "in": "MEASURE"}, "'in' needs a list"),
    ({"field": "x", "regex": "["}, "does not compile"),
    ({"field": "x", "not_regex": "(?P<"}, "does not compile"),
    ({"field": "x", "regex": 5}, "does not compile"),
    ({"field": "x", "gt": "10"}, "'gt' needs a number"),
    ({"field": "x", "lte": True}, "'lte' needs a number"),
    ({"field": "x", "len_lt": None}, "'len_lt' needs a number"),
    ({"field": "x", "exists": "yes"}, "'exists' needs true or false"),
    ({"field": "x", "truthy": 1}, "'truthy' needs true or false"),
    ({"count": "model.column", "where": {"field": "x", "nonblank": True}, "gte": "2"},
     "'gte' needs a number"),
])
def test_operand_values_checked(tmp_path, expr, needle):
    rule = _good_rule()
    rule["aggregate"]["match"] = expr
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(p.startswith("rules/ai.yaml: A6:") and "aggregate.match" in p and needle in p
               for p in problems), problems


def test_valid_operands_accepted(tmp_path):
    rule = _good_rule()
    rule["aggregate"]["match"] = {"all": [
        {"field": "name", "regex": "^id$|_id$", "not_regex": "(?i)valid"},
        {"field": "type", "in": ["INT64", "INT32"]},
        {"field": "n", "gt": 1, "lte": 2.5, "len_gt": 0},
        {"field": "y", "exists": False, "eq": "x", "contains": "a"},
    ]}
    assert _problems(tmp_path, {"ai": [rule]}) == []


# ── Task 4: categories carry the legacy angle key ────────────────────────────

def test_shipped_categories_carry_legacy_angle_keys():
    cat = load_catalog(PKG_CATALOG)
    assert {c.id: c.angle_key for c in cat.categories.values()} == {
        "A": "ai", "D": "data_modeling", "H": "human", "P": "performance", "S": "security"}


def _with_categories(tmp_path: Path, rows: list) -> list[str]:
    root = _catalog_dir(tmp_path, {})
    (root / "categories.yaml").write_text(yaml.safe_dump(rows, sort_keys=False))
    return validate_catalog(load_catalog(root), load_raw(root))


def test_angle_key_required_and_unique(tmp_path):
    rows = [{"id": "A", "label": "AI", "order": 1, "angle_key": "ai"},
            {"id": "B", "label": "B", "order": 2},
            {"id": "C", "label": "C", "order": 3, "angle_key": "ai"}]
    problems = _with_categories(tmp_path, rows)
    assert any(p.startswith("categories.yaml: B:") and "angle_key is required" in p
               for p in problems), problems
    assert any(p.startswith("categories.yaml: C:") and "angle_key 'ai' repeats A" in p
               for p in problems), problems


# ── Task 4: per-mode aggregate keys, operands, placeholders, severity source ─

def _each(**overrides) -> dict:
    """A clean `each` rule: fixed severity, no bands."""
    rule = _good_rule(bands=None, profiles={}, severity="HIGH", message="{name}",
                      aggregate={"mode": "each", "where": {"field": "name", "exists": True}})
    rule.update(overrides)
    return rule


def _group(**agg) -> dict:
    return _each(aggregate={"mode": "group", **agg})


@pytest.mark.parametrize("rule, needle", [
    (_each(aggregate={"mode": "each", "match": {"field": "x", "truthy": True}}),
     "unknown key 'match' for mode each"),
    (_good_rule(aggregate={"mode": "ratio", "over": "model.column", "key": "name",
                           "match": {"field": "x", "truthy": True}}),
     "unknown key 'key' for mode ratio"),
    (_good_rule(aggregate={"mode": "ratio", "over": "model.column"}),
     "aggregate.match is required for mode ratio"),
    (_group(key="name"), "aggregate.kind is required for mode group"),
    (_group(kind="duplicates"), "aggregate.key is required for mode group"),
    (_group(key="name", kind="twins"), "unknown kind 'twins'"),
    (_group(key="name", kind="divergence"), "aggregate.value is required"),
    (_group(key="name", kind="duplicates", value="x"), "only used by kind divergence"),
    (_group(key="name", kind="duplicates", guid="last"), "aggregate.guid"),
    (_group(key=[], kind="duplicates"), "composite key needs at least one path"),
    (_group(key="name", kind="duplicates", name="{nme}"), "unknown placeholder 'nme'"),
    (_each(aggregate={"mode": "pairwise"}), "aggregate.set is required for mode pairwise"),
    (_each(aggregate={"mode": "composite", "components": {"a": "x"}, "weights": {"b": 1}}),
     "aggregate.weights: must give one number per component"),
    (_each(aggregate={"mode": "composite", "components": {"a": "x"}, "weights": {"a": "1"}}),
     "aggregate.weights.a: needs a number"),
    (_each(aggregate={"mode": "composite", "components": {"score": "x"},
                      "weights": {"score": 1}}),
     "'score' must be a placeholder-safe name"),
    (_each(aggregate={"mode": "composite", "components": [], "weights": {}}),
     "aggregate.components: must be a non-empty mapping"),
])
def test_mode_specific_aggregate_keys(tmp_path, rule, needle):
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(p.startswith("rules/ai.yaml: A6:") and needle in p for p in problems), problems


@pytest.mark.parametrize("rule", [
    _group(key=["dataSourceName", "name"], kind="duplicates", guid="none",
           name="{key[0]} ({size})", member="parent.name"),
    _group(key="name", kind="divergence", value="properties.column_type"),
    _each(aggregate={"mode": "pairwise", "set": "model_tables.fqn"},
          bands={"direction": "lower_is_better", "unit": "ratio",
                 "levels": [{"op": "gt", "value": 0.5, "severity": "MEDIUM"}]},
          severity=None, message="{a} / {b}: {similarity:.2f} ({shared}/{union})"),
    _each(aggregate={"mode": "composite", "components": {"desc": "x", "syn": "@has_synonyms"},
                     "weights": {"desc": 0.5, "syn": 0.5}},
          bands={"direction": "higher_is_better", "unit": "score",
                 "levels": [{"op": "lt", "value": 80, "severity": "MEDIUM"}]},
          severity=None, message="{score:.0f} ({desc}, {syn})"),
    _each(aggregate={"mode": "each", "measure": "@join_depth"},
          bands={"direction": "lower_is_better", "unit": "depth",
                 "levels": [{"op": "gt", "value": 3, "severity": "MEDIUM"}]},
          severity=None, message="{value} {obj.anything.at.all} {@is_indexed} {name}"),
])
def test_mode_specific_aggregate_keys_accepted(tmp_path, rule):
    assert _problems(tmp_path, {"ai": [rule]}) == []


def test_over_must_be_a_child_of_the_scope(tmp_path):
    rule = _good_rule(scope="table")
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any("'model.column' items are not children of scope 'table'" in p
               for p in problems), problems


@pytest.mark.parametrize("expr, needle", [
    ({"field": "x", "eq": ["a"]}, "'eq' needs a single value"),
    ({"field": "x", "eq": {"a": 1}}, "'eq' needs a single value"),
    ({"field": "x", "in": [["a"]]}, "'in' needs a list of single values"),
    ({"field": "x", "contains": None}, "'contains' needs a single"),
    ({"field": "x", "contains": ["a"]}, "'contains' needs a single"),
])
def test_eq_in_contains_operands_checked(tmp_path, expr, needle):
    rule = _good_rule()
    rule["aggregate"]["match"] = expr
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(needle in p for p in problems), problems


def test_eq_accepts_null_and_booleans(tmp_path):
    rule = _good_rule()
    rule["aggregate"]["match"] = {"all": [{"field": "x", "eq": None},
                                          {"field": "y", "eq": False},
                                          {"field": "z", "in": [1, "a", None]}]}
    assert _problems(tmp_path, {"ai": [rule]}) == []


@pytest.mark.parametrize("mutate, needle", [
    (lambda r: r.update(message="{matchd}/{total}"), "message: unknown placeholder 'matchd'"),
    (lambda r: r.update(message="{matched"), "message: malformed template"),
    (lambda r: r.update(message="{} measures"), "positional"),
    (lambda r: r["profiles"]["general"].update(message="{count}"),
     "profiles.general.message: unknown placeholder 'count'"),
    (lambda r: r.update(legacy_threshold={"assessment": "{profile}"}),
     "legacy_threshold.assessment: unknown placeholder 'profile'"),
    (lambda r: r["profiles"]["general"].update(legacy_threshold={"a": "{x}"}),
     "profiles.general.legacy_threshold.a: unknown placeholder 'x'"),
])
def test_message_placeholders_checked(tmp_path, mutate, needle):
    rule = _good_rule()
    mutate(rule)
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(p.startswith("rules/ai.yaml: A6:") and needle in p for p in problems), problems


@pytest.mark.parametrize("rule, needle", [
    (_good_rule(bands=None, profiles={}), "bands are required for mode ratio"),
    (_each(severity=None), "mode each needs a severity (or bands)"),
    (_each(bands={"direction": "lower_is_better", "unit": "count",
                  "levels": [{"op": "gt", "value": 3, "severity": "LOW"}]}),
     "bands need aggregate.measure in mode each"),
])
def test_severity_source_required(tmp_path, rule, needle):
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(needle in p for p in problems), problems


def test_severity_source_checked_under_every_profile(tmp_path):
    rule = _good_rule(bands=None)  # bands only under profiles.general
    problems = _problems(tmp_path, {"ai": [rule]})
    assert [p for p in problems if "bands are required" in p] == [
        "rules/ai.yaml: A6: bands are required for mode ratio "
        "(it grades a measured value) (profile: spotter)"]
    each = _each(severity=None, profiles={"general": {"severity": "LOW"},
                                          "spotter": {"severity": "HIGH"}})
    assert _problems(tmp_path / "each", {"ai": [each]}) == []


def test_group_without_a_severity_source(tmp_path):
    rule = _group(key="name", kind="duplicates") | {"severity": None}
    assert _problems(tmp_path, {"ai": [rule]}) == [
        "rules/ai.yaml: A6: mode group needs a severity (or bands) (profile: spotter, general)"]


# ── fix round 1: one expression form per mapping ─────────────────────────────

@pytest.mark.parametrize("expr, needle", [
    ({"all": [{"field": "n", "gt": 1}], "not": {"field": "f", "truthy": True}},
     "'all' must stand alone"),
    ({"field": "n", "eq": 999, "not": {"field": "f", "truthy": True}},
     "'not' must stand alone"),
    ({"any": [{"field": "n", "gt": 1}], "field": "n"}, "'any' must stand alone"),
    ({"count": "model.column"}, "'count' given with no comparison operator"),
    ({"count": "model.column", "where": {"field": "x", "exists": True}},
     "'count' given with no comparison operator"),
    ({"count": "model.column", "field": "x", "gt": 1}, "'field' cannot be combined with 'count'"),
    ({"field": "x"}, "'field' given with no comparison operator"),
    ({"field": "x", "gt": 1, "where": {"field": "y", "exists": True}},
     "'where' cannot be combined with 'field'"),
])
def test_one_expression_form_per_mapping(tmp_path, expr, needle):
    rule = _good_rule()
    rule["aggregate"]["match"] = expr
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(p.startswith("rules/ai.yaml: A6: aggregate.match") and needle in p
               for p in problems), problems


@pytest.mark.parametrize("count_scope, needle", [
    ("model", "'model' is a top-level scope"),
    ("answer.formula", "'answer.formula' items are not children of 'model.column'"),
])
def test_count_scope_must_belong_to_the_item(tmp_path, count_scope, needle):
    rule = _good_rule()  # match/where run on model.column items (the `over` scope)
    rule["aggregate"]["match"] = {"count": count_scope, "gt": 1}
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(needle in p for p in problems), problems


def test_count_scope_may_belong_to_an_enclosing_item(tmp_path):
    rule = _good_rule()
    rule["aggregate"]["match"] = {"count": "model.formula", "gt": 1, "where": {
        "count": "model.column", "gte": 0}}  # nested: formula items' enclosing model
    assert _problems(tmp_path, {"ai": [rule]}) == []
    each = _each(scope="model", aggregate={"mode": "each", "where": {
        "count": "model.column", "where": {"field": "name", "exists": True}, "gt": 75}})
    assert _problems(tmp_path / "each", {"ai": [each]}) == []


# ── fix round 1: a severity bands override is rejected, never dropped ────────

def test_profile_severity_under_bands_rejected(tmp_path):
    rule = _good_rule(profiles={"general": {"severity": "CRITICAL"}})
    problems = _problems(tmp_path, {"ai": [rule]})
    assert "rules/ai.yaml: A6: profiles.general.severity has no effect: bands set the " \
           "severity under profile general" in problems, problems


def test_catalog_severity_under_bands_everywhere_rejected(tmp_path):
    rule = _good_rule(severity="HIGH")
    problems = _problems(tmp_path, {"ai": [rule]})
    assert "rules/ai.yaml: A6: severity has no effect: bands set the severity under " \
           "every profile" in problems, problems


def test_catalog_severity_with_bands_in_one_profile_accepted(tmp_path):
    rule = _each(severity="HIGH", aggregate={"mode": "each", "measure": "@join_depth"},
                 profiles={"spotter": {"bands": {
                     "direction": "lower_is_better", "unit": "depth",
                     "levels": [{"op": "gt", "value": 3, "severity": "MEDIUM"}]}}})
    assert _problems(tmp_path, {"ai": [rule]}) == []


# ── fix round 1: each messages are validated ─────────────────────────────────

@pytest.mark.parametrize("message, needle", [
    ("{nme}", "unknown placeholder 'nme'"),
    ("{properties.column_type}", "unknown placeholder 'properties'"),
    ("{@nope}", "unknown derived field '@nope'"),
])
def test_each_message_placeholders_checked(tmp_path, message, needle):
    problems = _problems(tmp_path, {"ai": [_each(message=message)]})
    assert any(p.startswith("rules/ai.yaml: A6: message") and needle in p
               for p in problems), problems


def test_derived_placeholders_only_in_each(tmp_path):
    rule = _good_rule(message="{@is_indexed} {matched}")
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any("unknown placeholder '@is_indexed'" in p for p in problems), problems


# ── fix round 2 ──────────────────────────────────────────────────────────────

def test_null_profile_override_rejected(tmp_path):
    # The engine skips a null override, so under `general` the catalog bands would win
    # and the profile's LOW would be silently dropped. The validator must say so.
    rule = _each(severity="HIGH", aggregate={"mode": "each", "measure": "@join_depth"},
                 bands={"direction": "lower_is_better", "unit": "depth",
                        "levels": [{"op": "gt", "value": 3, "severity": "MEDIUM"}]},
                 profiles={"general": {"bands": None, "severity": "LOW"}})
    problems = _problems(tmp_path, {"ai": [rule]})
    assert "rules/ai.yaml: A6: profiles.general.bands: null removes nothing — omit the " \
           "key, or give the replacement value" in problems, problems
    assert any("profiles.general.severity has no effect" in p for p in problems), problems


@pytest.mark.parametrize("key", ["status", "severity", "message", "remediation",
                                 "legacy_threshold"])
def test_null_profile_override_rejected_for_every_key(tmp_path, key):
    rule = _good_rule(profiles={"general": {key: None}})
    problems = _problems(tmp_path, {"ai": [rule]})
    assert any(f"profiles.general.{key}: null removes nothing" in p for p in problems), problems


@pytest.mark.parametrize("message", ["{@is_indexed.x}", "{@is_indexed[0]}"])
def test_derived_placeholder_must_be_the_whole_name(tmp_path, message):
    problems = _problems(tmp_path, {"ai": [_each(message=message)]})
    assert any("a derived placeholder is the whole name" in p for p in problems), problems
