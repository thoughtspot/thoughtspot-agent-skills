"""The severity rubric's catalog checks (audit v2 roadmap PR 4.2; design:
docs/superpowers/specs/2026-11-01-audit-severity-rubric-design.md).

Every active rule declares `evidence:` — what kind of evidence its findings rest on:

    fact        something the TML or metadata states, read exactly
    measure     a count, share or ratio the TML states, graded against a pass mark
    heuristic   an inference: a name pattern, a role guess, a similarity

A rule that combines kinds takes the weakest one it needs to fire. A heuristic rule may
not grade above MEDIUM under any profile — every severity `emitted_severities` reports,
bands, severity maps, fixed and code-registered severities and profile overrides alike —
unless it carries `severity_exception: {reason: <why>, approved: <YYYY-MM-DD>}`.

Run-time override layers (engine/run.py `layers`) are not user-facing; if they become so,
the cap must be enforced there too. Gate-safe: standard library and catalog modules only.
"""
from __future__ import annotations

import datetime
from typing import Any, Iterable, List

from ts_cli.audit.catalog_code import emitted_severities
from ts_cli.audit.catalog_model import Rule, profile_override

EVIDENCE_CLASSES = ("fact", "measure", "heuristic")
#: The highest severity a heuristic rule may grade without an approved exception.
HEURISTIC_CAP = "MEDIUM"
_ORDER = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
EXCEPTION_KEYS = {"reason", "approved"}


def is_iso_date(value: Any) -> bool:
    """A YYYY-MM-DD date (a YAML date, or a string in that form)."""
    if isinstance(value, datetime.date):
        return True
    try:
        datetime.date.fromisoformat(str(value))
        return len(str(value)) == 10
    except ValueError:
        return False


def _above_cap(rule: Rule, profiles: Iterable[str]) -> List[str]:
    """`<profile>: <severity>` for each severity above the cap the rule can grade."""
    out = []
    for pid in sorted(profiles):
        for sev in sorted(emitted_severities(rule, profile_override(rule, pid))):
            if sev in _ORDER and _ORDER.index(sev) > _ORDER.index(HEURISTIC_CAP):
                out.append(f"{pid}: {sev}")
    return out


def _exception_problems(exc: Any) -> List[str]:
    if not isinstance(exc, dict):
        return ["severity_exception must be a mapping {reason, approved}"]
    out = [f"severity_exception: unknown key '{k}'" for k in sorted(set(exc) - EXCEPTION_KEYS)]
    if not isinstance(exc.get("reason"), str) or not exc["reason"].strip():
        out.append("severity_exception.reason is required: why a name match alone "
                   "warrants this grade")
    if not is_iso_date(exc.get("approved")):
        out.append("severity_exception.approved must be the approval date, YYYY-MM-DD")
    return out


def evidence_problems(rule: Rule, profiles: Iterable[str]) -> List[str]:
    """The rule's evidence class and the heuristic cap (see the module docstring)."""
    if rule.status != "active":
        return []
    if rule.evidence not in EVIDENCE_CLASSES:
        return [f"evidence must be one of {', '.join(EVIDENCE_CLASSES)} "
                f"(got {rule.evidence!r})"]
    exc = rule.severity_exception
    if exc is not None and rule.evidence != "heuristic":
        return ["severity_exception applies only to a heuristic rule"]
    if exc is not None:
        return _exception_problems(exc)
    if rule.evidence != "heuristic":
        return []
    return [f"a heuristic rule grades at most {HEURISTIC_CAP}, but this one can grade "
            f"{above} (lower it, or add an approved severity_exception)"
            for above in _above_cap(rule, profiles)]
