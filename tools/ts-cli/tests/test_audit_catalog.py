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


def test_derived_field_names_are_accepted_until_registry_exists(tmp_path):
    rule = _good_rule()
    rule["aggregate"]["match"] = {"field": "@is_indexed", "truthy": True}
    assert _problems(tmp_path, {"ai": [rule]}) == []


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
                                 "where": {"field": "join_type", "eq": "OUTER"}})
    assert _problems(tmp_path, {"data": [rule]}) == []


def _sev_map(**overrides):
    sev = {"field": "join_type", "map": {"OUTER": "HIGH", "LEFT_OUTER": "INFO"},
           "default": "MEDIUM"}
    sev.update(overrides)
    return sev


def test_mapping_severity_shape_accepted(tmp_path):
    rule = _good_rule(bands=None, severity=_sev_map(),
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
