"""Catalog tests for the per-severity forms (catalog_forms.py), beyond the basic
validation in test_audit_catalog.py (kept under the 1000-line gate):

- coverage of a CATALOG-level `{by_severity: ...}` entry is judged against every
  profile that uses it — an entry only some profiles emit is not "never emitted" —
  while a PROFILE-level entry keeps the strict per-profile check;
- S2's two wordings live in security.yaml, not in a derived field.
"""
from __future__ import annotations

import copy

from ts_cli.audit.catalog_model import build_catalog, load_catalog, load_raw
from ts_cli.audit.catalog_validate import validate_catalog
from ts_cli.audit.engine import fields

_HIGH_ONLY = {"direction": "lower_is_better", "unit": "ratio",
              "levels": [{"op": "gte", "value": 1.0, "severity": "HIGH"}]}


def _shipped_with(rule_id: str, edit) -> list[str]:
    """Problems of the shipped catalog with `edit(rule)` applied to one raw rule."""
    raw = copy.deepcopy(load_raw())
    [rule] = [r for f, rules in raw.items() if f.startswith("rules/") for r in rules
              if r["id"] == rule_id]
    edit(rule)
    return validate_catalog(build_catalog(raw), raw)


def _general_bands(bands):
    def edit(rule):
        rule.setdefault("profiles", {}).setdefault("general", {})["bands"] = bands
    return edit


# ── catalog-level entries: extra only when no profile using them emits it ────

def test_catalog_level_entries_for_a_severity_only_some_profiles_emit_pass():
    """D7 under general graded HIGH only: spotter still emits MEDIUM, so the
    catalog-level MEDIUM template and MEDIUM threshold are in use."""
    assert _shipped_with("D7", _general_bands(_HIGH_ONLY)) == []


def test_catalog_level_entry_no_profile_emits_still_fails():
    def edit(rule):
        rule.setdefault("profiles", {})["general"] = {"bands": _HIGH_ONLY}
        rule["profiles"]["spotter"] = {"bands": copy.deepcopy(_HIGH_ONLY)}
    problems = _shipped_with("D7", edit)
    assert any("D7: message.by_severity: a template for severity MEDIUM, which the rule "
               "never emits (profile: spotter, general)" in p for p in problems), problems
    assert any("D7: legacy_threshold.by_severity: a threshold for severity MEDIUM"
               in p for p in problems), problems


def test_catalog_level_missing_template_is_still_judged_per_profile():
    """A profile that uses the catalog-level message and emits a severity it does not
    word is a gap, whatever the other profile emits."""
    critical = {"direction": "lower_is_better", "unit": "ratio",
                "levels": [{"op": "gte", "value": 1.0, "severity": "CRITICAL"}]}
    problems = _shipped_with("D7", _general_bands(critical))
    assert any("D7: message.by_severity: no template for severity CRITICAL, which the "
               "rule can emit (profile: general)" in p for p in problems), problems


def test_profile_level_entries_keep_the_strict_per_profile_check():
    """A profile's own by-severity entry words exactly what THAT profile emits."""
    def edit(rule):
        rule.setdefault("profiles", {})["general"] = {
            "bands": _HIGH_ONLY,
            "message": {"by_severity": {"HIGH": "h", "MEDIUM": "m"}},
            "legacy_threshold": {"by_severity": {"MEDIUM": {"high_overlap": 0.5}}}}
    problems = _shipped_with("D7", edit)
    assert any("D7: profiles.general.message.by_severity: a template for severity MEDIUM, "
               "which the rule never emits (profile: general)" in p for p in problems), problems
    assert any("D7: profiles.general.legacy_threshold.by_severity: a threshold for severity "
               "MEDIUM" in p for p in problems), problems


def test_catalog_level_entry_judged_only_by_profiles_that_use_it():
    """spotter overrides the message, so only general uses the catalog-level one; general
    never emits MEDIUM, so the catalog-level MEDIUM template is never used."""
    def edit(rule):
        rule.setdefault("profiles", {})["general"] = {"bands": _HIGH_ONLY}
        rule["profiles"]["spotter"] = {"message": copy.deepcopy(rule["message"])}
    problems = _shipped_with("D7", edit)
    assert any("D7: message.by_severity: a template for severity MEDIUM, which the rule "
               "never emits (profile: general)" in p for p in problems), problems


# ── S2's wording is catalog data ────────────────────────────────────────────

def test_s2_words_its_two_severities_in_the_catalog():
    s2 = load_catalog().rules["S2"]
    assert s2.message == {"by_severity": {
        "HIGH": "PII column '{name}' is indexed WITHOUT table RLS",
        "INFO": "PII column '{name}' is indexed (table has RLS)"}}
    assert "owning_table_rls_note" not in fields.FIELDS
