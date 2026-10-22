"""Catalog checks that what a reader sees agrees with the rule itself.

  * **Prose shows no engine identifiers.** `title`, `description`, `remediation` and
    the literal text of a `message` (catalog and profile overrides) are read by audit
    readers — in the check catalog doc and the HTML report — so they never name a
    derived field (`@name`), a code rule (`code:<name>`) or an engine module
    (`engine/<module>.py`). A `{@name}` placeholder in
    a message is fine: it renders as a value. Why a rule is code belongs in a YAML
    comment beside `implementation:`. Category descriptions are held to the same.

Kept importable on Python 3.9 with only PyYAML (see catalog_model.py).
"""
from __future__ import annotations

import re
from typing import Any, Iterator, List

from ts_cli.audit.catalog_model import Catalog, Rule, profile_override

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


def rule_consistency_problems(rule: Rule, cat: Catalog) -> List[str]:
    return prose_problems(rule)
