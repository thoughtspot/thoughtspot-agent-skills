"""Every catalog rule's examples run as tests — and code rules, which they also cover.

`test_rule_example` is parametrised over every ACTIVE rule in the shipped catalog
(ts_cli/audit/catalog/), twice: its `fires` example must produce at least one finding,
every one of them at the stated severity, under the stated profile (the catalog's
default profile when the example names none); its `silent` example must produce none.
It grows by itself as rules are added — there is nothing to register here. With no
rules shipped it collects no cases; the synthetic-catalog tests below prove the runner
catches what it should.

A rule's `examples.<kind>.fixture` names a function in the `audit_rule_fixtures` package
(tests/audit_rule_fixtures/, one module per category) that returns an AuditContext. Only that one rule is run over it (`run_rule`), so a fixture
need not keep every other rule quiet.

The catalog is loaded with `check_catalog()` (load + full validation, including the raw
YAML key checks); any problem it reports fails every example test, so a broken catalog
can never pass vacuously.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import List, Optional, Tuple

import pytest
import yaml

import audit_rule_fixtures as fx
from ts_cli.audit.catalog_model import CATALOG_DIR, CATEGORIES_FILE, PROFILES_FILE, Catalog
from ts_cli.audit.catalog_validate import EXAMPLE_KINDS, check_catalog
from ts_cli.audit.engine import bands, code_rules, scopes
from ts_cli.audit.engine.run import run_rule, run_rules
from ts_cli.audit.findings import Finding

# ── the example runner ──────────────────────────────────────────────────────


def default_profile(cat: Catalog) -> str:
    return next(p.id for p in cat.profiles.values() if p.default)


def example_problems(cat: Catalog, rule_id: str, kind: str, fixtures=fx) -> List[str]:
    """What is wrong with one rule's `fires` or `silent` example ([] = it holds)."""
    rule = cat.rules[rule_id]
    ex = rule.examples.get(kind)
    where = f"{rule.source_file}: {rule_id}: examples.{kind}"
    if not isinstance(ex, dict):
        return [f"{where}: missing"]
    builder = getattr(fixtures, str(ex.get("fixture")), None)
    if not callable(builder):
        return [f"{where}: no fixture '{ex.get('fixture')}' in the {fixtures.__name__} package"]
    profile = ex.get("profile") or default_profile(cat)
    found = run_rule(builder(), cat, rule_id, profile)
    seen = [f"{f.severity} {f.object_type} '{f.object_name}'" for f in found]
    if kind == "silent":
        return [f"{where}: expected no finding under profile {profile}, got {seen}"] \
            if found else []
    if not found:
        return [f"{where}: expected a {ex['severity']} finding under profile {profile}, "
                "got none"]
    wrong = [s for f, s in zip(found, seen) if f.severity != ex["severity"]]
    return [f"{where}: expected only {ex['severity']} findings under profile {profile}, "
            f"got {wrong}"] if wrong else []


def run_examples(root: Optional[Path] = None, fixtures=fx) -> List[str]:
    """Validate the catalog at `root`, then run every active rule's examples. A catalog
    problem is reported instead of running anything."""
    cat, problems = check_catalog(root)
    if problems:
        return problems
    out: List[str] = []
    for rule_id, kind in _cases(cat):
        out += example_problems(cat, rule_id, kind, fixtures)
    return out


def _cases(cat: Optional[Catalog]) -> List[Tuple[str, str]]:
    if cat is None:
        return []
    return [(r.id, kind) for r in cat.rules.values() if r.status == "active"
            for kind in EXAMPLE_KINDS]


# ── the shipped catalog ─────────────────────────────────────────────────────

_SHIPPED, _SHIPPED_PROBLEMS = check_catalog()


def test_shipped_catalog_is_valid():
    assert _SHIPPED_PROBLEMS == []


@pytest.mark.parametrize("rule_id,kind",
                         [pytest.param(r, k, id=f"{r}-{k}") for r, k in _cases(_SHIPPED)])
def test_rule_example(rule_id, kind):
    assert _SHIPPED_PROBLEMS == []
    assert example_problems(_SHIPPED, rule_id, kind) == []


# ── synthetic rules: the runner and code-rule dispatch ──────────────────────

WIDE = "synthetic_wide_model"


def _wide_model(rule, ctx, profile) -> List[Finding]:
    """A code rule: one finding per model with more columns than the bands allow.
    Iterates with `scopes.available`, as the code-rule contract asks."""
    out = []
    for item in scopes.available(ctx, rule):
        count = len(item["obj"].get("columns") or [])
        severity = bands.classify(count, rule.bands)
        if severity:
            out.append(Finding(check_id=rule.id, angle="", severity=severity,
                               object_type=item["object_type"], object_name=item["name"],
                               object_guid=item["guid"],
                               detail=rule.message.format(count=count, profile=profile),
                               metric=count))
    return out


@pytest.fixture
def wide_registered():
    """`_wide_model` registered through the decorator, unregistered afterwards."""
    code_rules.code_rule(WIDE, placeholders={"count", "profile"}, severity="bands",
                         uses=())(_wide_model)
    yield
    code_rules.REGISTRY.pop(WIDE, None)
    code_rules.PLACEHOLDERS.pop(WIDE, None)
    code_rules.SEVERITY_SOURCES.pop(WIDE, None)
    code_rules.CODE_USES.pop(WIDE, None)


def _code_rule_entry(**body) -> dict:
    rule = {
        "id": "D99", "title": "Synthetic wide model (code rule)", "categories": ["D", "P"],
        "requires": ["model_tml"], "implementation": f"code:{WIDE}", "scope": "model",
        "bands": {"direction": "lower_is_better", "unit": "count",
                  "levels": [{"op": "gt", "value": 75, "severity": "MEDIUM"}]},
        "profiles": {"spotter": {
            "bands": {"direction": "lower_is_better", "unit": "count",
                      "levels": [{"op": "gt", "value": 75, "severity": "HIGH"}]},
            "message": "{count} columns (strict)"}},
        "message": "{count} columns",
        "legacy_threshold": {"max": 75, "assessment": "{profile_label}"},
        "examples": {"fires": {"fixture": "model_76_columns", "severity": "MEDIUM"},
                     "silent": {"fixture": "model_75_columns"}},
    }
    rule.update(body)
    return rule


def _ratio_entry(**body) -> dict:
    """A declarative ratio rule (measure AI-context coverage)."""
    rule = {
        "id": "A98", "title": "Synthetic measure AI context", "categories": ["A"],
        "requires": ["model_tml"], "scope": "model",
        "aggregate": {
            "mode": "ratio", "over": "model.column",
            "where": {"all": [
                {"field": "properties.column_type", "eq": "MEASURE"},
                {"not": {"field": "properties.is_hidden", "truthy": True}}]},
            "match": {"field": "properties.ai_context", "nonblank": True}},
        "bands": {"direction": "higher_is_better", "unit": "percent",
                  "levels": [{"op": "lt", "value": 40, "severity": "HIGH"},
                             {"op": "lt", "value": 80, "severity": "MEDIUM"}]},
        "message": "{matched}/{total} measures have AI context",
        "examples": {
            "fires": {"fixture": "model_measures_no_ai_context", "profile": "spotter",
                      "severity": "HIGH"},
            "silent": {"fixture": "model_measures_with_ai_context", "profile": "spotter"}},
    }
    rule.update(body)
    return rule


def _write_catalog(tmp_path: Path, *rules: dict) -> Path:
    """The shipped categories and profiles plus `rules`, as a catalog directory."""
    root = tmp_path / "catalog"
    (root / "rules").mkdir(parents=True)
    for name in (CATEGORIES_FILE, PROFILES_FILE):
        (root / name).write_text((CATALOG_DIR / name).read_text())
    (root / "rules" / "test.yaml").write_text(
        yaml.safe_dump([copy.deepcopy(r) for r in rules], sort_keys=False))
    return root


def test_example_runner_passes_correct_examples(tmp_path, wide_registered):
    root = _write_catalog(tmp_path, _ratio_entry(), _code_rule_entry())
    assert run_examples(root) == []


def test_example_runner_detects_wrong_severity(tmp_path, wide_registered):
    ratio = _ratio_entry()
    ratio["examples"]["fires"]["severity"] = "MEDIUM"      # it fires HIGH under spotter
    code = _code_rule_entry()
    code["examples"]["fires"]["profile"] = "spotter"        # HIGH there, MEDIUM expected
    problems = run_examples(_write_catalog(tmp_path, ratio, code))
    assert problems == [
        "rules/test.yaml: A98: examples.fires: expected only MEDIUM findings under profile "
        "spotter, got [\"HIGH model 'Sales'\"]",
        "rules/test.yaml: D99: examples.fires: expected only MEDIUM findings under profile "
        "spotter, got [\"HIGH model 'Wide'\"]",
    ]


def test_example_runner_detects_a_silent_example_that_fires(tmp_path, wide_registered):
    code = _code_rule_entry()
    code["examples"]["silent"]["fixture"] = "model_76_columns"
    assert run_examples(_write_catalog(tmp_path, code)) == [
        "rules/test.yaml: D99: examples.silent: expected no finding under profile general, "
        "got [\"MEDIUM model 'Wide'\"]"]


def test_example_runner_detects_a_fires_example_that_is_silent(tmp_path, wide_registered):
    code = _code_rule_entry()
    code["examples"]["fires"]["fixture"] = "model_75_columns"
    assert run_examples(_write_catalog(tmp_path, code)) == [
        "rules/test.yaml: D99: examples.fires: expected a MEDIUM finding under profile "
        "general, got none"]


def test_example_runner_detects_a_mixed_severity_fires_example(tmp_path):
    # A fires example must produce exactly the stated severity — one finding at it is
    # not enough when another finding of the same rule is at a different one.
    rule = _ratio_entry(id="P98", categories=["P"], scope="model.column", aggregate={
        "mode": "each", "where": {"field": "name", "regex": "_id$"}},
        bands=None, message="{name}",
        severity={"field": "@is_indexed", "map": {True: "HIGH"}, "default": "INFO"})
    rule["examples"]["fires"]["fixture"] = "model_id_columns"
    rule["examples"]["silent"]["fixture"] = "model_75_columns"
    del rule["bands"]
    [problem] = run_examples(_write_catalog(tmp_path, rule))
    assert problem.startswith("rules/test.yaml: P98: examples.fires: expected only HIGH")
    assert "INFO column 'row_id'" in problem


def test_example_runner_detects_a_missing_fixture(tmp_path):
    rule = _ratio_entry()
    rule["examples"]["fires"]["fixture"] = "no_such_fixture"
    assert run_examples(_write_catalog(tmp_path, rule)) == [
        "rules/test.yaml: A98: examples.fires: no fixture 'no_such_fixture' in the "
        "audit_rule_fixtures package"]


def test_example_runner_reports_catalog_problems_instead_of_running(tmp_path):
    # check_catalog, not validate_catalog(load_catalog()): a raw-YAML key typo is caught.
    rule = _ratio_entry(remedation="typo")
    problems = run_examples(_write_catalog(tmp_path, rule))
    assert problems == ["rules/test.yaml: A98: unknown key 'remedation'"]


def test_example_runner_skips_retired_rules(tmp_path):
    rule = _ratio_entry(status="retired")
    rule["examples"]["fires"]["fixture"] = "no_such_fixture"
    assert run_examples(_write_catalog(tmp_path, rule)) == []


def test_unknown_code_rule_rejected_by_validator(tmp_path, wide_registered):
    root = _write_catalog(tmp_path, _code_rule_entry(implementation="code:no_such_rule"))
    _cat, problems = check_catalog(root)
    [problem] = problems
    assert problem.startswith("rules/test.yaml: D99: implementation: unknown code rule "
                              "'no_such_rule' (registered: ")
    assert WIDE in problem  # the registered names are listed (shipped ones too)
    _cat, problems = check_catalog(_write_catalog(tmp_path / "ok", _code_rule_entry()))
    assert problems == []


def test_code_rule_with_an_aggregate_block_is_rejected(tmp_path, wide_registered):
    """The function owns a code rule's logic: an `aggregate` block beside it would be
    dead data that reads as if it configured something."""
    rule = _code_rule_entry(aggregate={"mode": "count", "over": "model.column"})
    _cat, problems = check_catalog(_write_catalog(tmp_path, rule))
    assert problems == [
        "rules/test.yaml: D99: aggregate: a code rule (code:synthetic_wide_model) owns its "
        "logic — remove the aggregate block"]


def unused_code_rules(cat: Catalog) -> List[str]:
    """Registered code rules no rule in `cat` names. Only functions defined in the
    ts_cli package count: the synthetic rules these tests register come from test
    modules (and are unregistered after each test)."""
    used = {code_rules.code_rule_name(r.implementation) for r in cat.rules.values()
            if r.implementation != "declarative"}
    shipped = {name for name, fn in code_rules.REGISTRY.items()
               if fn.__module__.startswith("ts_cli.")}
    return sorted(shipped - used)


def test_code_rule_message_placeholders_are_checked(tmp_path, wide_registered):
    """A code rule declares what it renders; its catalog message and every profile's
    message are held to that — `{scroe}` must not pass because no mode applies."""
    rule = _code_rule_entry(message="{cuont} columns")
    rule["profiles"]["spotter"]["message"] = "{count} columns ({strict})"
    _cat, problems = check_catalog(_write_catalog(tmp_path, rule))
    assert problems == [
        "rules/test.yaml: D99: message: unknown placeholder 'cuont' (known: count, profile)",
        "rules/test.yaml: D99: profiles.spotter.message: unknown placeholder 'strict' "
        "(known: count, profile)"]


def test_code_rule_placeholders_must_be_names():
    for bad in (["9x"], ["a.b"], "score"):
        with pytest.raises(ValueError, match="placeholders"):
            code_rules.code_rule("synthetic_bad_placeholders", placeholders=bad)
    assert "synthetic_bad_placeholders" not in code_rules.REGISTRY


def test_every_registered_code_rule_is_used_by_a_shipped_rule():
    """A function left behind after its catalog entry is removed fails here."""
    assert _SHIPPED is not None
    assert unused_code_rules(_SHIPPED) == []


def test_a_code_rule_left_behind_is_detected(monkeypatch):
    def left_behind(rule, ctx, profile):
        return []
    left_behind.__module__ = "ts_cli.audit.engine.code_rules"
    monkeypatch.setitem(code_rules.REGISTRY, "left_behind", left_behind)
    assert unused_code_rules(_SHIPPED) == ["left_behind"]


def test_code_rule_dispatch(tmp_path, wide_registered):
    cat, problems = check_catalog(_write_catalog(tmp_path, _code_rule_entry()))
    assert problems == []
    # ctx.assessment says spotter; the profile is the argument and nothing else.
    ctx = fx.model_76_columns()
    ctx.assessment = "spotter"
    [f] = run_rules(ctx, cat, ["P"], "general")
    assert (f.check_id, f.severity, f.object_type, f.object_name, f.object_guid,
            f.detail, f.metric) == ("D99", "MEDIUM", "model", "Wide", fx.MODEL_GUID,
                                    "76 columns", 76)
    # The runner stamps a code rule's findings exactly as a declarative rule's:
    assert f.angle == "data_modeling"                      # first category's angle_key
    assert f.categories == ["D", "P"]
    assert f.threshold == {"max": 75, "assessment": "General"}
    assert f.bands == {"direction": "lower_is_better", "unit": "count",
                       "levels": [{"op": "gt", "value": 75, "severity": "MEDIUM"}],
                       "profile": "general", "provenance": f.bands["provenance"]}
    # The code rule receives the EFFECTIVE rule: the profile's bands and message.
    [s] = run_rules(ctx, cat, ["D"], "spotter")
    assert (s.severity, s.detail, s.threshold) == (
        "HIGH", "76 columns (strict)", {"max": 75, "assessment": "Spotter-ready"})
    assert s.bands["provenance"]["bands"] == "profile:spotter"
    assert run_rule(fx.model_75_columns(), cat, "D99", "spotter") == []


def test_code_rule_findings_have_the_declarative_shape(tmp_path, wide_registered):
    cat, problems = check_catalog(_write_catalog(tmp_path, _code_rule_entry(),
                                                 _ratio_entry()))
    assert problems == []
    [code] = run_rule(fx.model_76_columns(), cat, "D99", "general")
    [declarative] = run_rule(fx.model_measures_no_ai_context(), cat, "A98", "general")
    assert list(code.to_dict()) == list(declarative.to_dict())
    assert set(code.bands) == set(declarative.bands)
    assert set(code.bands["provenance"]) == set(declarative.bands["provenance"])


OWN = "synthetic_own_threshold"


def _own_threshold(rule, ctx, profile) -> List[Finding]:
    """A code rule whose legacy threshold varies per finding (as D1's does per measure)."""
    from ts_cli.audit.engine.messages import render, template
    out = []
    for item in scopes.available(ctx, rule):
        count = len(item["obj"].get("columns") or [])
        severity = "HIGH" if count > 75 else "INFO"
        out.append(Finding(check_id=rule.id, angle="", severity=severity,
                           object_type="model", object_name=item["name"],
                           object_guid=item["guid"],
                           detail=render(template(rule, severity), {"count": count}),
                           metric=count, threshold={"max": 75, "seen": count}))
    return out


@pytest.fixture
def own_registered():
    code_rules.code_rule(OWN, placeholders={"count"}, severity={"HIGH", "INFO"},
                          uses=(), own_threshold=True)(_own_threshold)
    yield
    code_rules.REGISTRY.pop(OWN, None)
    code_rules.PLACEHOLDERS.pop(OWN, None)
    code_rules.SEVERITY_SOURCES.pop(OWN, None)
    code_rules.CODE_USES.pop(OWN, None)
    code_rules.OWN_THRESHOLD.discard(OWN)


def _own_entry(**body) -> dict:
    rule = _code_rule_entry(implementation=f"code:{OWN}", profiles={},
                            message={"by_severity": {"HIGH": "{count} columns",
                                                     "INFO": "only {count}"}})
    del rule["legacy_threshold"], rule["bands"]
    rule.update(body)
    return rule


def test_code_rule_may_set_its_own_threshold_and_word_by_severity(tmp_path, own_registered):
    cat, problems = check_catalog(_write_catalog(tmp_path, _own_entry()))
    assert problems == []
    [wide] = run_rule(fx.model_76_columns(), cat, "D99", "general")
    assert (wide.severity, wide.detail, wide.threshold) == (
        "HIGH", "76 columns", {"max": 75, "seen": 76})
    [narrow] = run_rule(fx.model_75_columns(), cat, "D99", "general")
    assert (narrow.severity, narrow.detail, narrow.threshold) == (
        "INFO", "only 75", {"max": 75, "seen": 75})


@pytest.mark.parametrize("body,profiles", [
    ({"legacy_threshold": {"max": 75}}, "spotter, general"),
    ({"profiles": {"spotter": {"legacy_threshold": {"max": 75}}}}, "spotter"),
])
def test_code_rule_threshold_beside_a_catalog_legacy_threshold_fails_the_gate(
        tmp_path, own_registered, body, profiles):
    cat, problems = check_catalog(_write_catalog(tmp_path, _own_entry(**body)))
    assert problems == [
        f"rules/test.yaml: D99: legacy_threshold: code:{OWN} sets each finding's legacy "
        f"threshold itself (own_threshold) — remove it from the entry (profile: {profiles})"]
    # …and the runner backstops it, should a catalog ever be built past the gate.
    with pytest.raises(ValueError, match="declares legacy_threshold"):
        run_rule(fx.model_76_columns(), cat, "D99", "spotter")


def test_code_rule_with_no_template_for_its_severity_fails_the_gate(tmp_path, own_registered):
    entry = _own_entry(message={"by_severity": {"HIGH": "{count} columns"}})
    cat, problems = check_catalog(_write_catalog(tmp_path, entry))
    assert problems == [
        "rules/test.yaml: D99: message.by_severity: no template for severity INFO, which "
        "the rule can emit (profile: spotter, general)"]
    with pytest.raises(ValueError, match="D99: no message for severity INFO"):
        run_rule(fx.model_75_columns(), cat, "D99", "general")


@pytest.mark.parametrize("kwargs", [
    {}, {"severity": "band"}, {"severity": ["HIGH", "SEVERE"]}, {"severity": []},
    {"severity": "bands", "own_threshold": "yes"},
])
def test_code_rule_registration_declares_a_valid_severity_source(kwargs):
    with pytest.raises(ValueError, match="severity must be|own_threshold must be"):
        code_rules.code_rule("synthetic_undeclared", **kwargs)
    assert "synthetic_undeclared" not in code_rules.REGISTRY


def test_shipped_code_rules_declare_what_they_read():
    assert {n: code_rules.SEVERITY_SOURCES[n] for n in (
        "spotter_readiness", "model_complexity", "join_keys", "zero_column_tables",
        "column_type_divergence")} == {
        "spotter_readiness": "bands", "model_complexity": frozenset({"HIGH", "MEDIUM"}),
        "join_keys": frozenset({"HIGH", "MEDIUM"}), "zero_column_tables": "severity",
        "column_type_divergence": "severity_name"}
    assert code_rules.OWN_THRESHOLD >= {"model_complexity"}
    assert "join_keys" not in code_rules.OWN_THRESHOLD


def test_runner_backstops_what_the_registration_declared(tmp_path, own_registered):
    """Built past the gate: a severity outside the declared set, or a threshold from a
    function that did not declare own_threshold, raises rather than reports."""
    cat, problems = check_catalog(_write_catalog(tmp_path, _own_entry()))
    assert problems == []
    code_rules.SEVERITY_SOURCES[OWN] = frozenset({"HIGH"})
    try:
        with pytest.raises(ValueError, match="emitted INFO, outside its declared"):
            run_rule(fx.model_75_columns(), cat, "D99", "general")
    finally:
        code_rules.SEVERITY_SOURCES[OWN] = frozenset({"HIGH", "INFO"})
    code_rules.OWN_THRESHOLD.discard(OWN)
    with pytest.raises(ValueError, match="without declaring own_threshold"):
        run_rule(fx.model_76_columns(), cat, "D99", "general")


def _bad_return(value):
    def rule(_rule, _ctx, _profile):
        return value
    return rule


def _finding(**over) -> Finding:
    base = dict(check_id="D99", angle="", severity="MEDIUM", object_type="model",
                object_name="Wide", object_guid=fx.MODEL_GUID, detail="x")
    base.update(over)
    return Finding(**base)


@pytest.mark.parametrize("value,error", [
    (None, "must return a list of Finding"),
    ([{"check_id": "D99"}], "must return a list of Finding"),
    ([_finding(check_id="D1")], "finding for 'D1'"),
    ([_finding(severity="SEVERE")], "unknown severity 'SEVERE'"),
])
def test_code_rule_breaking_the_contract_raises(tmp_path, monkeypatch, value, error):
    monkeypatch.setitem(code_rules.REGISTRY, WIDE, _bad_return(value))
    cat, problems = check_catalog(_write_catalog(tmp_path, _code_rule_entry()))
    assert problems == []
    with pytest.raises(ValueError, match=error):
        run_rule(fx.model_76_columns(), cat, "D99", "general")


def test_unregistered_code_rule_raises_at_run_time(tmp_path, wide_registered):
    # Built past the validator (registered then), run after it is gone: never silent.
    cat, _ = check_catalog(_write_catalog(tmp_path, _code_rule_entry()))
    code_rules.REGISTRY.pop(WIDE)
    with pytest.raises(KeyError, match="no code rule registered as 'synthetic_wide_model'"):
        run_rule(fx.model_76_columns(), cat, "D99", "general")


def test_code_rule_registration_rejects_duplicates_and_bad_names(wide_registered):
    with pytest.raises(ValueError, match="already registered"):
        code_rules.code_rule(WIDE, severity="bands", uses=())(_wide_model)
    for bad in ("Wide", "wide-model", "1wide", ""):
        with pytest.raises(ValueError, match="not a valid code rule name"):
            code_rules.code_rule(bad)
    assert code_rules.REGISTRY[WIDE] is _wide_model


def test_run_rule_rejects_unknown_rule_and_profile(tmp_path):
    cat, _ = check_catalog(_write_catalog(tmp_path, _ratio_entry()))
    with pytest.raises(KeyError, match="unknown rule 'A97'"):
        run_rule(fx.model_76_columns(), cat, "A97", "general")
    with pytest.raises(ValueError, match="unknown profile 'strict'"):
        run_rule(fx.model_76_columns(), cat, "A98", "strict")
