"""Catalog checks that what a reader sees agrees with the rule itself.

Two things a rule says twice, where nothing else holds the copies together:

  * **Prose shows no engine identifiers.** `title`, `description`, `remediation` and
    the literal text of a `message` (catalog and profile overrides) are read by audit
    readers — in the check catalog doc and the HTML report — so they never name a
    derived field (`@name`), a code rule (`code:<name>`) or an engine module
    (`engine/<module>.py`). A `{@name}` placeholder in
    a message is fine: it renders as a value. Why a rule is code belongs in a YAML
    comment beside `implementation:`. Category descriptions are held to the same.
  * **`legacy_threshold` agrees with `bands`.** The legacy threshold payload repeats a
    rule's band values in the shape the old checks emitted (`{green: 50, yellow: 25}`).
    Under every profile the rule is active in, each number in its effective
    `legacy_threshold` must be one of its effective band values: change a band and the
    payload must change with it, or findings claim a pass mark the grading no longer
    uses. A rule without bands (its threshold lives in a `where:`) is not checked.

A third copy — numbers the `description` quotes — is checked against history by the
gate's `--base` mode (catalog_history.description_drift_problems): a band value that
changed since the base and is still quoted fails.

Kept importable on Python 3.9 with only PyYAML (see catalog_model.py).
"""
from __future__ import annotations

import re
from typing import Any, Iterator, List, Optional, Set

from ts_cli.audit.catalog_forms import BY_SEVERITY
from ts_cli.audit.catalog_model import (
    Bands, Catalog, CatalogError, Rule, parse_bands, profile_override,
)

ENGINE_ID = re.compile(r"@[A-Za-z_]\w*|\bcode:[a-z_]\w*|\bengine/[\w*]+(?:\.py)?")
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_PROSE_KEYS = ("title", "description", "remediation")


def engine_ids(text: Any) -> List[str]:
    """Engine identifiers in `text` (strings only; placeholders `{...}` excluded)."""
    if not isinstance(text, str):
        return []
    return ENGINE_ID.findall(_PLACEHOLDER.sub("", text))


def _texts(value: Any) -> Iterator[str]:
    """Every string in a message — plain, or a `{by_severity: {...}}` mapping."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _texts(v)


def _prose_problem(key: str, text: Any) -> List[str]:
    found = sorted({i for t in _texts(text) for i in engine_ids(t)})
    if not found:
        return []
    return [f"{key}: shows engine identifier(s) {', '.join(found)} to audit readers — "
            "write it in words (an implementation note goes in a YAML comment)"]


def prose_problems(rule: Rule) -> List[str]:
    out: List[str] = []
    for key in _PROSE_KEYS:
        out += _prose_problem(key, getattr(rule, key, None))
    out += _prose_problem("message", rule.message)
    for pid in sorted(rule.profiles):
        override = profile_override(rule, pid)
        for key in ("message", "remediation"):
            out += _prose_problem(f"profiles.{pid}.{key}", override.get(key))
    return out


def category_prose_problems(cat: Catalog, file: str) -> List[str]:
    return [f"{file}: {c.id}: {m}" for c in cat.categories.values()
            for key in ("label", "description")
            for m in _prose_problem(key, getattr(c, key, None))]


# ── legacy_threshold vs bands ───────────────────────────────────────────────

def _numbers(value: Any) -> Iterator[float]:
    """Numeric leaves of a legacy threshold payload (booleans are not numbers)."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _numbers(v)
    elif isinstance(value, list):
        for v in value:
            yield from _numbers(v)


def _parsed(bands: Any) -> Optional[Bands]:
    if bands is None or isinstance(bands, Bands):
        return bands
    try:
        return parse_bands(bands, "", "")
    except (CatalogError, TypeError, ValueError, AttributeError):
        return None  # malformed bands are reported by the band checks


def _payload_numbers(payload: Any, severities: Set[str]) -> Set[float]:
    """The numbers a profile's payload claims: of a `{by_severity: ...}` payload, only
    the entries for severities its bands can grade (the others are another profile's)."""
    if isinstance(payload, dict) and BY_SEVERITY in payload:
        entries = payload[BY_SEVERITY] if isinstance(payload[BY_SEVERITY], dict) else {}
        return {n for sev, v in entries.items() if sev in severities for n in _numbers(v)}
    return set(_numbers(payload))


def _num(v: float) -> str:
    return str(int(v)) if v.is_integer() else str(v)


def threshold_problems(rule: Rule, cat: Catalog) -> List[str]:
    out: List[str] = []
    for pid in cat.profiles:
        override = profile_override(rule, pid)
        if override.get("status", rule.status) != "active":
            continue
        bands = _parsed(override.get("bands", rule.bands))
        payload = override.get("legacy_threshold", rule.legacy_threshold)
        if bands is None or payload is None:
            continue
        values = {float(lv.value) for lv in bands.levels
                  if isinstance(lv.value, (int, float)) and not isinstance(lv.value, bool)}
        claimed = _payload_numbers(payload, {lv.severity for lv in bands.levels})
        stray = sorted(n for n in claimed if n not in values)
        if stray:
            out.append(
                f"legacy_threshold under {pid}: {', '.join(_num(n) for n in stray)} "
                f"is not a band value ({', '.join(_num(v) for v in sorted(values))}) — "
                "when bands change, change legacy_threshold with them (per profile), and "
                "any number the description quotes")
    return out


def rule_consistency_problems(rule: Rule, cat: Catalog) -> List[str]:
    return prose_problems(rule) + threshold_problems(rule, cat)
