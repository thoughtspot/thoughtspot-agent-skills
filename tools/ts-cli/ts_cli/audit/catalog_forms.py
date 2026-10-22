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
rule's placeholders), a threshold's values are legacy threshold mappings. And for a
declarative rule, every severity the rule can emit under each profile (its bands'
levels, or its fixed or mapped `severity`) has a template — a gap would otherwise
surface only as a run-time error. A code rule's severities are its function's to
choose, so its gaps are reported at run time (engine/messages.py).

Kept importable on Python 3.9 with only PyYAML (see catalog_model.py).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set

from ts_cli.audit.catalog_code import CODE_IMPL, rule_message_problems
from ts_cli.audit.catalog_expr import SEVERITIES, legacy_threshold_problems
from ts_cli.audit.catalog_model import Rule

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


# ── coverage: every severity a declarative rule can emit has a template ─────

def _band_severities(bands: Any) -> Set[str]:
    """Severities of a Bands object or a raw (profile override) bands mapping."""
    if isinstance(bands, dict):
        return {lv.get("severity") for lv in bands.get("levels") or [] if isinstance(lv, dict)}
    return {lv.severity for lv in getattr(bands, "levels", None) or []}


def _fixed_severities(severity: Any) -> Set[str]:
    if isinstance(severity, dict):
        mapped = severity.get("map")
        return set((mapped or {}).values() if isinstance(mapped, dict) else ()) \
            | {severity.get("default")}
    return {severity}


def emitted_severities(bands: Any, severity: Any) -> Set[str]:
    """What a declarative rule can grade a finding: its bands decide where present."""
    found = _band_severities(bands) if bands is not None else _fixed_severities(severity)
    return {s for s in found if s in SEVERITIES}


def _effective(rule: Rule, pid: str) -> Dict[str, Any]:
    """The profile's non-null overrides (a null removes nothing — bands.effective)."""
    override = rule.profiles.get(pid)
    return {k: v for k, v in override.items() if v is not None} \
        if isinstance(override, dict) else {}


def message_coverage_problems(rule: Rule, profiles: Iterable[str]) -> List[str]:
    """Under each profile, a by-severity message words every severity the rule can emit."""
    if CODE_IMPL.match(rule.implementation):
        return []
    gaps: Dict[tuple, List[str]] = {}
    for pid in profiles:
        override = _effective(rule, pid)
        message = override.get("message", rule.message)
        if not isinstance(message, dict) or not isinstance(message.get(BY_SEVERITY), dict):
            continue
        path = f"profiles.{pid}.message" if "message" in override else "message"
        emitted = emitted_severities(override.get("bands", rule.bands),
                                     override.get("severity", rule.severity))
        for sev in sorted(emitted - set(message[BY_SEVERITY]), key=SEVERITIES.index):
            gaps.setdefault((path, sev), []).append(pid)
    return [f"{path}.{BY_SEVERITY}: no template for severity {sev}, which the rule can "
            f"emit (profile: {_known(pids)})" for (path, sev), pids in gaps.items()]
