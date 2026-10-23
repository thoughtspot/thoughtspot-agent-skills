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
rule's placeholders), a threshold's values are legacy threshold mappings. And the
entries match the severities the rule can emit — its bands' levels, its fixed or
mapped `severity`, or a code rule's declared severities
(catalog_code.emitted_severities): under each profile, the message in force words
every one (a gap is a run-time error); and no template or threshold names a severity
nothing can use it for — judged per profile for a profile's own entry, and across
every profile that uses it for a catalog-level entry (a severity only one profile
emits is in use).

Kept importable on Python 3.9 with only PyYAML (see catalog_model.py).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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

def _in_force(rule: Rule, pid: str, key: str) -> Optional[Tuple[str, Dict[str, Any], Set[str]]]:
    """`(path, by-severity mapping, emitted severities)` of the `key` entry in force
    under profile `pid` — None when it is not in the by-severity form, or when what the
    rule emits there is unknown (an unregistered code rule, a missing severity source:
    reported by other checks). `path` is the profile's own key when it overrides it,
    else the catalog-level key."""
    override = profile_override(rule, pid)
    value = override.get(key, getattr(rule, key))
    if not isinstance(value, dict) or not isinstance(value.get(BY_SEVERITY), dict):
        return None
    emitted = emitted_severities(rule, override)
    if not emitted:
        return None
    path = f"profiles.{pid}.{key}" if key in override else key
    return path, value[BY_SEVERITY], emitted


def _coverage(rule: Rule, profiles: Iterable[str], key: str, need_all: bool
              ) -> List[Tuple[str, str, str, List[str]]]:
    """`(path, severity, kind, profiles)` gaps between the by-severity entries of `key`
    and the severities the rule can emit: `missing` (only when `need_all`) under each
    profile the entry is in force for, and `extra` — a profile's own entry for a
    severity THAT profile never emits, a catalog-level entry for one that no profile
    using it emits (a severity only some profiles emit is in use)."""
    users: Dict[str, List[Tuple[str, Dict[str, Any], Set[str]]]] = {}
    for pid in profiles:
        found = _in_force(rule, pid, key)
        if found is not None:
            users.setdefault(found[0], []).append((pid, found[1], found[2]))
    gaps: List[Tuple[str, str, str, List[str]]] = []
    for path, uses in users.items():
        keyed = {s for s in uses[0][1] if s in SEVERITIES}
        if need_all:
            gaps += [(path, s, "missing", [pid]) for pid, _, emitted in uses
                     for s in sorted(emitted - keyed, key=SEVERITIES.index)]
        emitted_by_any = set().union(*(emitted for _, _, emitted in uses))
        gaps += [(path, s, "extra", [pid for pid, _, _ in uses])
                 for s in keyed - emitted_by_any]
    return gaps


_GAP_WORDING = {
    ("message", "missing"): "no template for severity {sev}, which the rule can emit",
    ("message", "extra"): "a template for severity {sev}, which the rule never emits",
    ("legacy_threshold", "extra"): "a threshold for severity {sev}, which the rule "
                                   "never emits",
}


def form_coverage_problems(rule: Rule, profiles: Iterable[str]) -> List[str]:
    """Under each profile, a by-severity message words every severity the rule can
    emit there (no gap) and no template is one nothing can use; a by-severity legacy
    threshold names no severity that can never be emitted (a missing one is a
    legitimate None). A profile's own entry is held to that profile's severities, a
    catalog-level one to those of the profiles that use it (see `_coverage`)."""
    profiles = list(profiles)
    gaps: Dict[Tuple[str, str, str, str], List[str]] = {}
    for key, need_all in (("message", True), ("legacy_threshold", False)):
        for path, sev, kind, pids in _coverage(rule, profiles, key, need_all):
            listed = gaps.setdefault((key, path, sev, kind), [])
            listed += [p for p in pids if p not in listed]
    order = sorted(gaps, key=lambda g: (g[1], g[3], SEVERITIES.index(g[2])))
    return [f"{path}.{BY_SEVERITY}: {_GAP_WORDING[(key, kind)].format(sev=sev)} "
            f"(profile: {_known(gaps[(key, path, sev, kind)])})"
            for key, path, sev, kind in order]
