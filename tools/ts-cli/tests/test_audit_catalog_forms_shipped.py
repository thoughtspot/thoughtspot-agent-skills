"""The audit rule catalog's per-severity forms and the shipped rules one key wrong at a
time — moved from test_audit_catalog.py (which passed 1,000 lines) unchanged, test
names preserved."""
from __future__ import annotations

import copy

import pytest

from audit_catalog_helpers import PKG_CATALOG, _problems
from ts_cli.audit.catalog_model import load_raw
from ts_cli.audit.catalog_validate import validate_catalog


# ── per-severity forms (`{by_severity: {...}}`) ─────────────────────────────

def _join_type_rule(**overrides) -> dict:
    rule = {
        "id": "D3", "title": "Join types", "categories": ["D"], "requires": ["model_tml"],
        "scope": "join",
        "aggregate": {"mode": "each", "where": {"field": "type", "in": ["OUTER", "LEFT_OUTER"]}},
        "severity": {"field": "type", "map": {"OUTER": "HIGH"}, "default": "INFO"},
        "message": {"by_severity": {"HIGH": "full outer {name}", "INFO": "{obj.type} join"}},
        "examples": {"fires": {"fixture": "f", "severity": "HIGH"}, "silent": {"fixture": "s"}},
    }
    rule.update(overrides)
    return rule


def test_message_by_severity_accepted(tmp_path):
    assert _problems(tmp_path, {"data": [_join_type_rule()]}) == []


@pytest.mark.parametrize("message,word", [
    ({"by_severity": {"HIGH": "x"}},
     "message.by_severity: no template for severity INFO, which the rule can emit"),
    ({"by_severity": {"HIGH": "x", "INFO": "y", "SEVERE": "z"}},
     "message.by_severity.SEVERE: unknown severity 'SEVERE'"),
    ({"by_severity": {"HIGH": "x", "INFO": 5}}, "message.by_severity.INFO: must be a string"),
    ({"by_severity": {"HIGH": "{nmae}", "INFO": "y"}},
     "message.by_severity.HIGH: unknown placeholder 'nmae'"),
    ({"by_severity": {}}, "message.by_severity: must be a non-empty mapping"),
    ({"by_sevrity": {"HIGH": "x"}}, "message: must be a template string or {by_severity:"),
    ({"by_severity": {"HIGH": "x", "INFO": "y"}, "extra": 1},
     "message: must be a template string or {by_severity:"),
])
def test_message_by_severity_rejects_typos_and_gaps(tmp_path, message, word):
    problems = _problems(tmp_path, {"data": [_join_type_rule(message=message)]})
    assert any(word in p for p in problems), problems


def test_message_by_severity_must_cover_every_profiles_severities(tmp_path):
    """A profile that changes the severities must not leave one unworded."""
    rule = _join_type_rule(profiles={"spotter": {
        "severity": {"field": "type", "map": {"OUTER": "CRITICAL"}, "default": "INFO"}}})
    problems = _problems(tmp_path, {"data": [rule]})
    assert any("no template for severity CRITICAL" in p and "spotter" in p
               for p in problems), problems


def test_profile_message_override_may_be_by_severity(tmp_path):
    ok = _join_type_rule(profiles={"spotter": {
        "message": {"by_severity": {"HIGH": "h", "INFO": "i"}}}})
    assert _problems(tmp_path / "ok", {"data": [ok]}) == []
    bad = _join_type_rule(profiles={"spotter": {"message": {"by_severity": {"HIGH": "{x}"}}}})
    problems = _problems(tmp_path / "bad", {"data": [bad]})
    assert any("profiles.spotter.message.by_severity.HIGH: unknown placeholder 'x'" in p
               for p in problems), problems
    assert any("profiles.spotter.message.by_severity: no template for severity INFO" in p
               for p in problems), problems


def test_legacy_threshold_by_severity(tmp_path):
    ok = _join_type_rule(legacy_threshold={"by_severity": {"INFO": {"a": 1}}})
    assert _problems(tmp_path / "ok", {"data": [ok]}) == []
    for i, (value, word) in enumerate([
            ({"by_severity": {"SEVERE": {"a": 1}}},
             "legacy_threshold.by_severity.SEVERE: unknown severity"),
            ({"by_severity": {"INFO": 3}},
             "legacy_threshold.by_severity.INFO: must be a mapping"),
            ({"by_severity": {"INFO": {"a": "{nope}"}}},
             "legacy_threshold.by_severity.INFO.a: unknown placeholder 'nope'")]):
        problems = _problems(tmp_path / str(i), {"data": [_join_type_rule(legacy_threshold=value)]})
        assert any(word in p for p in problems), problems


# ── the shipped code rules and by-severity forms, one key wrong at a time ──
# Each mistake below used to validate clean and then raise at run time (aborting the
# whole category) or be silently ignored; each must now fail the gate.

def _shipped_with(rule_id: str, edit) -> list[str]:
    """Problems of the shipped catalog with `edit(rule)` applied to one raw rule."""
    raw = copy.deepcopy(load_raw(PKG_CATALOG))
    [rule] = [r for f, rules in raw.items() if f.startswith("rules/") for r in rules
              if r["id"] == rule_id]
    edit(rule)
    from ts_cli.audit.catalog_model import build_catalog
    return validate_catalog(build_catalog(raw), raw)


def _set(path: str, value):
    def edit(rule):
        *parents, last = path.split(".")
        node = rule
        for p in parents:
            node = node.setdefault(p, {})
        node[last] = value
    return edit


def _drop(key: str):
    return lambda rule: rule.pop(key)


_MAPPED = {"field": "@zero_column_role", "map": {"bridge": "INFO"}, "default": "MEDIUM"}
_COUNT_BANDS = {"direction": "lower_is_better", "unit": "count",
                "levels": [{"op": "gt", "value": 5, "severity": "HIGH"}]}


@pytest.mark.parametrize("rule_id,edit,expected", [
    # code rules: the severity source the function reads, present and of its form
    ("D12", _set("severity", _MAPPED),
     "D12: severity must be a severity name: code:column_type_divergence"),
    ("D12", _set("profiles.spotter.severity", _MAPPED),
     "(profile: spotter)"),
    ("D12", _drop("severity"),
     "D12: severity is required: code:column_type_divergence reads the catalog severity"),
    ("D10", _drop("severity"),
     "D10: severity is required: code:zero_column_tables reads the catalog severity"),
    ("D1", _set("profiles.spotter.bands", {
        "direction": "lower_is_better", "unit": "count",
        "levels": [{"op": "gte", "value": 50, "severity": "HIGH"},
                   {"op": "gte", "value": 30, "severity": "MEDIUM"}]}),
     "D1: bands must be exactly the levels gt HIGH, gt MEDIUM (any values): "
     "code:model_complexity words its findings by them (profile: spotter)"),
    ("D1", _set("bands.levels", [{"op": "gt", "value": 40, "severity": "HIGH"}]),
     "D1: bands must be exactly the levels gt HIGH, gt MEDIUM"),
    ("D1", _drop("bands"),
     "D1: bands are required: code:model_complexity grades its findings by bands"),
    ("H10", _drop("severity"),
     "H10: severity is required: code:stale_names reads the catalog severity"),
    # …and nothing it ignores
    ("D1", _set("severity", "HIGH"), "D1: severity has no effect: code:model_complexity"),
    ("P6", _set("bands", _COUNT_BANDS), "P6: bands has no effect: code:join_keys"),
    ("P6", _set("profiles.spotter.bands", _COUNT_BANDS), "(profile: spotter)"),
    ("P6", _set("severity", "HIGH"),
     "P6: severity has no effect: code:join_keys chooses its severities itself (INFO, LOW)"),
    ("D12", _set("bands", _COUNT_BANDS),
     "D12: bands has no effect: code:column_type_divergence reads severity"),
    ("D10", _set("bands", _COUNT_BANDS), "D10: bands has no effect"),
    # a code rule's own threshold beside a catalog one
    ("D1", _set("legacy_threshold", {"green": 10}),
     "D1: legacy_threshold: code:model_complexity sets each finding's legacy threshold"),
    ("D1", _set("profiles.spotter.legacy_threshold", {"green": 10}), "(profile: spotter)"),
    # a code rule's message words exactly its declared severities
    ("P6", lambda r: r["message"]["by_severity"].pop("INFO"),
     "P6: message.by_severity: no template for severity INFO, which the rule can emit"),
    ("P6", _set("profiles.spotter.message", {"by_severity": {"LOW": "{varchar_keys}"}}),
     "P6: profiles.spotter.message.by_severity: no template for severity INFO"),
    ("P6", lambda r: r["message"]["by_severity"].update(MEDIUM="x"),
     "P6: message.by_severity: a template for severity MEDIUM, which the rule never emits"),
    # a code rule's parameters: exactly the names it reads, each a number
    ("H2", _drop("parameters"), "H2: parameters missing issues_shown, max_chars, "
     "min_chars: code:description_quality reads them"),
    ("H2", lambda r: r["parameters"].update(min_length=5),
     "H2: parameters min_length have no effect: code:description_quality does not read"),
    ("H2", lambda r: r["parameters"].update(min_chars="20"),
     "H2: parameters.min_chars must be a finite number, not negative, got '20'"),
    ("H10", _set("parameters.quote_chars", True),
     "H10: parameters.quote_chars must be a finite number, not negative, got True"),
    ("H10", _set("parameters.quote_chars", float("inf")),
     "H10: parameters.quote_chars must be a finite number, not negative, got inf"),
    ("H2", _set("parameters.issues_shown", -1),
     "H2: parameters.issues_shown must be a finite number, not negative, got -1"),
    ("D1", _set("profiles.general.bands", {"direction": "lower_is_better",
                                           "unit": "count", "levels": 5}),
     "D1: 'profiles.general.bands.levels' must be a list of mappings"),
    ("H10", _set("parameters", {5: 1}),
     "H10: parameters 5 have no effect: code:stale_names does not read them"),
    ("H10", _set("profiles.spotter.parameters", [60]),
     "H10: parameters must be a mapping of names to numbers, got [60] (profile: spotter)"),
    # …replaced whole under a profile, never merged
    ("H2", _set("profiles.spotter.parameters", {"min_chars": 10}),
     "parameters missing issues_shown, max_chars: code:description_quality reads them "
     "(profile: spotter)"),
    ("P1", _set("parameters", {"min_chars": 10}),
     "P1: parameters are read only by a code rule; this rule has none"),
    # declarative: templates and thresholds for severities never emitted
    ("D3", lambda r: r["message"]["by_severity"].update(LOW="x"),
     "D3: message.by_severity: a template for severity LOW, which the rule never emits"),
    ("D7", lambda r: r["message"]["by_severity"].update(CRITICAL="x"),
     "D7: message.by_severity: a template for severity CRITICAL, which the rule never emits"),
    ("D7", _set("legacy_threshold", {"by_severity": {"LOW": {"high_overlap": 0.5}}}),
     "D7: legacy_threshold.by_severity: a threshold for severity LOW, which the rule "
     "never emits"),
])
def test_shipped_rule_mistakes_fail_validation(rule_id, edit, expected):
    problems = _shipped_with(rule_id, edit)
    assert any(expected in p and f": {rule_id}: " in p for p in problems), problems


def test_d1_bands_with_other_values_are_valid():
    assert _shipped_with("D1", _set("profiles.spotter.bands", {
        "direction": "lower_is_better", "unit": "count",
        "levels": [{"op": "gt", "value": 40, "severity": "HIGH"},
                   {"op": "gt", "value": 25, "severity": "MEDIUM"}]})) == []


def test_a_huge_integer_parameter_is_judged_not_crashed_on():
    """An integer is finite however large: `math.isfinite` would overflow on it."""
    assert _shipped_with("H10", _set("parameters.quote_chars", 10 ** 400)) == []


def test_parameters_on_a_retired_rule_with_no_logic_are_still_checked():
    problems = _shipped_with("D2", _set("profiles.spotter.parameters", [60]))
    assert any("D2: parameters must be a mapping" in p for p in problems), problems


def test_a_complete_profile_parameters_override_is_valid():
    """A profile may override `parameters` (review blocker: the gate rejected every
    profile block as "must be a string")."""
    assert _shipped_with("H2", _set("profiles.spotter.parameters", {
        "min_chars": 25, "max_chars": 400, "issues_shown": 3})) == []
    assert _shipped_with("H10", _set("profiles.general.parameters", {"quote_chars": 80})) == []


def test_shipped_catalog_still_clean_under_the_new_checks():
    assert _shipped_with("D1", lambda r: None) == []
