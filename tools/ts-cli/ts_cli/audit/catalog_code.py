"""Catalog checks for code rules (`implementation: code:<name>`).

A code rule names a function registered in `engine/code_rules.py`. These checks hold
its catalog entry to that registration: the name must be registered, the function
owns the logic (no `aggregate` block), the rule's message — and every profile's —
may use only the placeholders the function declares it renders, and under every
profile the entry carries exactly the severity source the function declares it reads
(`bands`, a `severity` — a plain name where it must be — or neither, for severities
fixed in the function) and no `legacy_threshold` beside a function that sets its own.

`emitted_severities(rule, override)` — what a rule, declarative or code, can grade a
finding under one profile's overrides — also lives here: the per-severity form checks
(catalog_forms.py) compare a rule's templates against it.

The registry is imported lazily, inside the functions, so the catalog gate loads it
(and the gate-safe modules it imports) without the rest of ts_cli. Kept importable on
Python 3.9 with only PyYAML (see catalog_model.py). `catalog_validate` re-exports
`CODE_IMPL` and `known_code_rules`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ts_cli.audit.catalog_expr import SEVERITIES, message_problems, placeholder_problems
from ts_cli.audit.catalog_model import Rule, profile_override

# `implementation: code:<name>` — also the name check engine/code_rules.py registers by.
CODE_IMPL = re.compile(r"^code:([a-z_][a-z0-9_]*)$")


def known_code_rules() -> Set[str]:
    """Names usable as `implementation: code:<name>` — the engine's code-rule registry.

    Imported lazily, like `known_derived_fields`: the catalog gate loads
    `engine/code_rules.py` (and the gate-safe modules it imports) without the rest of
    ts_cli. See that module's docstring for what it may import.
    """
    from ts_cli.audit.engine.code_rules import REGISTRY
    return set(REGISTRY)


def known_code_rule_placeholders(name: str) -> Optional[Set[str]]:
    """What the code rule `name` renders its message with; None if not registered."""
    from ts_cli.audit.engine.code_rules import PLACEHOLDERS
    return set(PLACEHOLDERS[name]) if name in PLACEHOLDERS else None


def implementation_problems(rule: Rule) -> List[str]:
    if rule.implementation == "declarative":
        return []
    m = CODE_IMPL.match(rule.implementation)
    if not m:
        return [f"implementation: '{rule.implementation}' must be 'declarative' "
                "or 'code:<name>'"]
    registered = known_code_rules()
    if m.group(1) not in registered:
        return [f"implementation: unknown code rule '{m.group(1)}' "
                f"(registered: {', '.join(sorted(registered)) or 'none'})"]
    return []


def rule_message_problems(rule: Rule, template: Any, path: str) -> List[str]:
    """A message (the rule's or a profile's) against what renders it: a declarative
    rule's mode, or a code rule's declared placeholders. An unregistered code rule is
    reported by `implementation_problems`; its message is not judged."""
    m = CODE_IMPL.match(rule.implementation)
    if not m:
        return message_problems(template, rule.aggregate, path)
    allowed = known_code_rule_placeholders(m.group(1))
    return [] if allowed is None else placeholder_problems(template, allowed, path)


def code_rule_aggregate_problems(rule: Rule) -> List[str]:
    """The function owns a code rule's logic, so an `aggregate` block beside it would
    be dead data that reads as if it configured something."""
    if not rule.aggregate:
        return []
    return [f"aggregate: a code rule ({rule.implementation}) owns its logic — "
            "remove the aggregate block"]


# ── what a code rule reads and emits (its registration) ─────────────────────

def code_rule_declaration(name: str) -> Optional[Tuple[Any, bool]]:
    """`(severity source, own_threshold)` the code rule `name` registered; None if
    it is not registered (see engine/code_rules.py for the sources)."""
    from ts_cli.audit.engine.code_rules import OWN_THRESHOLD, SEVERITY_SOURCES
    if name not in SEVERITY_SOURCES:
        return None
    return SEVERITY_SOURCES[name], name in OWN_THRESHOLD


def _declaration(rule: Rule) -> Optional[Tuple[Any, bool]]:
    m = CODE_IMPL.match(rule.implementation)
    return code_rule_declaration(m.group(1)) if m else None


def _band_severities(bands: Any) -> Set[Any]:
    """Severities of a Bands object or a raw (profile override) bands mapping."""
    if isinstance(bands, dict):
        return {lv.get("severity") for lv in bands.get("levels") or [] if isinstance(lv, dict)}
    return {lv.severity for lv in getattr(bands, "levels", None) or []}


def _mapped_severities(severity: Any) -> Set[Any]:
    if isinstance(severity, dict):
        mapped = severity.get("map")
        return set((mapped or {}).values() if isinstance(mapped, dict) else ()) \
            | {severity.get("default")}
    return {severity}


def emitted_severities(rule: Rule, override: Dict[str, Any]) -> Set[str]:
    """What `rule` can grade a finding under one profile's (non-null) overrides: its
    bands' levels where it is graded by bands, else its fixed or mapped `severity` —
    or, for a code rule with fixed severities, the ones its function declares. Empty
    when that is unknown (an unregistered code rule) or the source is missing (which
    other checks report)."""
    bands = override.get("bands", rule.bands)
    severity = override.get("severity", rule.severity)
    decl = _declaration(rule)
    if CODE_IMPL.match(rule.implementation):
        if decl is None:
            return set()
        source = decl[0]
        found = set(source) if isinstance(source, frozenset) else \
            _band_severities(bands) if source == "bands" else _mapped_severities(severity)
    else:
        found = _band_severities(bands) if bands is not None else _mapped_severities(severity)
    return {s for s in found if s in SEVERITIES}


def _source_problems(name: str, source: Any, override: Dict[str, Any], rule: Rule
                     ) -> List[str]:
    """Under one profile: the key the function reads is present (and of the right
    form); a key it does not read is absent — it would be silently ignored."""
    bands = override.get("bands", rule.bands)
    severity = override.get("severity", rule.severity)
    reads = {"bands"} if source == "bands" else \
        {"severity"} if source in ("severity", "severity_name") else set()
    out: List[str] = []
    if "bands" in reads and bands is None:
        out.append(f"bands are required: code:{name} grades its findings by bands")
    if "severity" in reads and severity is None:
        out.append(f"severity is required: code:{name} reads the catalog severity")
    if source == "severity_name" and severity is not None and not isinstance(severity, str):
        out.append(f"severity must be a severity name: code:{name} reports findings that "
                   "are not about one item, so has nothing to look a mapping up on")
    for key, value in (("bands", bands), ("severity", severity)):
        if value is not None and key not in reads:
            what = f"chooses its severities itself ({', '.join(sorted(source))})" \
                if isinstance(source, frozenset) else f"reads {' and '.join(sorted(reads))}"
            out.append(f"{key} has no effect: code:{name} {what}")
    return out


def _threshold_problems(name: str, own: bool, override: Dict[str, Any], rule: Rule
                        ) -> List[str]:
    if own and override.get("legacy_threshold", rule.legacy_threshold) is not None:
        return [f"legacy_threshold: code:{name} sets each finding's legacy threshold "
                "itself (own_threshold) — remove it from the entry"]
    return []


def code_rule_problems(rule: Rule, profiles: Iterable[str]) -> List[str]:
    """Under every profile, the entry matches what its code rule declared it reads."""
    m = CODE_IMPL.match(rule.implementation)
    decl = _declaration(rule)
    if not m or decl is None:
        return []  # not a code rule, or unregistered (implementation_problems says so)
    by_problem: Dict[str, List[str]] = {}
    for pid in profiles:
        override = profile_override(rule, pid)
        for problem in (_source_problems(m.group(1), decl[0], override, rule)
                        + _threshold_problems(m.group(1), decl[1], override, rule)):
            by_problem.setdefault(problem, []).append(pid)
    return [f"{problem} (profile: {', '.join(pids)})" if pids != [""] else problem
            for problem, pids in by_problem.items()]

