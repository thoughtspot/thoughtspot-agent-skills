"""Catalog checks for the per-severity forms of `message` and `legacy_threshold`.

Most rules word every finding alike. A rule whose wording differs with the finding's
severity — D3 (a FULL OUTER join, HIGH, vs a one-sided outer join, INFO), D7
(identical table sets vs overlapping ones) — keeps every wording in the catalog:

    message:
      by_severity:
        HIGH: FULL OUTER join causes performance issues
        INFO: "{@join_type} join — may indicate data discrepancies"

The engine renders the template for the finding's severity (engine/messages.py
`template`). The same form serves `legacy_threshold`, whose pre-catalog dict also
varied with severity on one rule (D7 set none on its HIGH findings); a severity with
no entry there has no threshold (None).

    legacy_threshold:
      by_severity:
        MEDIUM: {high_overlap: 0.5}

What these checks hold a rule to: the form has exactly the one key `by_severity`
holding a non-empty mapping; its keys are severities; a message's values are
templates (each checked as a plain message would be — against the mode's or the code
rule's placeholders), a threshold's values are legacy threshold mappings. And under
each profile, the message words exactly the severities the rule can emit — its bands'
levels, its fixed or mapped `severity`, or a code rule's declared severities
(catalog_code.emitted_severities) — so neither a gap (a run-time error) nor a template
that can never be used passes; a threshold names no severity the rule never emits.

Kept importable on Python 3.9 with only PyYAML (see catalog_model.py).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from ts_cli.audit.catalog_code import emitted_severities, rule_message_problems
from ts_cli.audit.catalog_expr import SEVERITIES, legacy_threshold_problems
from ts_cli.audit.catalog_model import Rule, profile_override

BY_SEVERITY = "by_severity"


def _known(values: Iterable[str]) -> str:
    return ", ".join(values)


def _by_severity(value: Any, path: str, what: str) -> tuple:
    """`(mapping, problems)` for a `{by_severity: {...}}` value; mapping None if bad."""
    if not isinstance(value, dict) or set(value) != {BY_SEVERITY}:
        return None, [f"{path}: must be {what} or {{{BY_SEVERITY}: {{SEVERITY: ...}}}}"]
    mapping = value[BY_SEVERITY]
    if not isinstance(mapping, dict) or not mapping:
        return None, [f"{path}.{BY_SEVERITY}: must be a non-empty mapping of severity -> "
                      f"{what}"]
    bad = [f"{path}.{BY_SEVERITY}.{sev}: unknown severity '{sev}' "
           f"(known: {_known(SEVERITIES)})" for sev in mapping if sev not in SEVERITIES]
    return mapping, bad


def message_problems_any(rule: Rule, message: Any, path: str) -> List[str]:
    """A message (the rule's or a profile's): a template, or templates by severity."""
    if isinstance(message, str):
        return rule_message_problems(rule, message, path)
    mapping, out = _by_severity(message, path, "a template string")
    for sev, template in (mapping or {}).items():
        where = f"{path}.{BY_SEVERITY}.{sev}"
        if not isinstance(template, str):
            out.append(f"{where}: must be a string")
        else:
            out += rule_message_problems(rule, template, where)
    return out


def legacy_threshold_form_problems(value: Any, path: str) -> List[str]:
    """A legacy threshold mapping, or such mappings by severity."""
    if not isinstance(value, dict) or BY_SEVERITY not in value:
        return legacy_threshold_problems(value, path)
    mapping, out = _by_severity(value, path, "a legacy threshold mapping")
    for sev, threshold in (mapping or {}).items():
        where = f"{path}.{BY_SEVERITY}.{sev}"
        if not isinstance(threshold, dict):
            out.append(f"{where}: must be a mapping")
        else:
            out += legacy_threshold_problems(threshold, where)
    return out


# ── coverage: the templates match what the rule can emit ────────────────────

def _coverage(rule: Rule, pid: str, key: str, need_all: bool) -> List[Tuple[str, str, str]]:
    """`(path, severity, kind)` gaps between the by-severity entries of `key` in force
    under profile `pid` and the severities the rule can emit there: `missing` (only
    when `need_all`) and `extra`."""
    override = profile_override(rule, pid)
    value = override.get(key, getattr(rule, key))
    if not isinstance(value, dict) or not isinstance(value.get(BY_SEVERITY), dict):
        return []
    emitted = emitted_severities(rule, override)
    if not emitted:
        return []  # unknown or missing severity source: reported by other checks
    path = f"profiles.{pid}.{key}" if key in override else key
    keyed = {s for s in value[BY_SEVERITY] if s in SEVERITIES}
    gaps = [(path, s, "missing") for s in emitted - keyed] if need_all else []
    return gaps + [(path, s, "extra") for s in keyed - emitted]


_GAP_WORDING = {
    ("message", "missing"): "no template for severity {sev}, which the rule can emit",
    ("message", "extra"): "a template for severity {sev}, which the rule never emits",
    ("legacy_threshold", "extra"): "a threshold for severity {sev}, which the rule "
                                   "never emits",
}


def form_coverage_problems(rule: Rule, profiles: Iterable[str]) -> List[str]:
    """Under each profile, a by-severity message words exactly the severities the rule
    can emit (no gap, no template that can never be used), and a by-severity legacy
    threshold names none it never emits (a missing one is a legitimate None)."""
    gaps: Dict[Tuple[str, str, str, str], List[str]] = {}
    for pid in profiles:
        for key, need_all in (("message", True), ("legacy_threshold", False)):
            for path, sev, kind in _coverage(rule, pid, key, need_all):
                gaps.setdefault((key, path, sev, kind), []).append(pid)
    order = sorted(gaps, key=lambda g: (g[1], g[3], SEVERITIES.index(g[2])))
    return [f"{path}.{BY_SEVERITY}: {_GAP_WORDING[(key, kind)].format(sev=sev)} "
            f"(profile: {_known(gaps[(key, path, sev, kind)])})"
            for key, path, sev, kind in order]
