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
    ("A5", _drop("bands"), "A5: bands are required: code:spotter_readiness grades"),
    # …and nothing it ignores
    ("A5", _set("severity", "HIGH"),
     "A5: severity has no effect: code:spotter_readiness reads bands"),
    ("D1", _set("bands", _COUNT_BANDS),
     "D1: bands has no effect: code:model_complexity chooses its severities itself"),
    ("D1", _set("profiles.spotter.bands", _COUNT_BANDS), "(profile: spotter)"),
    ("D2", _set("bands", _COUNT_BANDS), "D2: bands has no effect: code:join_keys"),
    ("D2", _set("severity", "HIGH"),
     "D2: severity has no effect: code:join_keys chooses its severities itself (HIGH, MEDIUM)"),
    ("D12", _set("bands", _COUNT_BANDS),
     "D12: bands has no effect: code:column_type_divergence reads severity"),
    ("D10", _set("bands", _COUNT_BANDS), "D10: bands has no effect"),
    # a code rule's own threshold beside a catalog one
    ("D1", _set("legacy_threshold", {"green": 10}),
     "D1: legacy_threshold: code:model_complexity sets each finding's legacy threshold"),
    ("D1", _set("profiles.spotter.legacy_threshold", {"green": 10}), "(profile: spotter)"),
    # a code rule's message words exactly its declared severities
    ("D2", lambda r: r["message"]["by_severity"].pop("MEDIUM"),
     "D2: message.by_severity: no template for severity MEDIUM, which the rule can emit"),
    ("D2", _set("profiles.spotter.message", {"by_severity": {"HIGH": "{varchar_keys}"}}),
     "D2: profiles.spotter.message.by_severity: no template for severity MEDIUM"),
    ("D2", lambda r: r["message"]["by_severity"].update(LOW="x"),
     "D2: message.by_severity: a template for severity LOW, which the rule never emits"),
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


def test_shipped_catalog_still_clean_under_the_new_checks():
    assert _shipped_with("D1", lambda r: None) == []
