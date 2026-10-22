"""Catalog checks for code rules (`implementation: code:<name>`).

A code rule names a function registered in `engine/code_rules.py`. These checks hold
its catalog entry to that registration: the name must be registered, the function
owns the logic (no `aggregate` block), and the rule's message — and every profile's —
may use only the placeholders the function declares it renders.

The registry is imported lazily, inside the functions, so the catalog gate loads it
(and the gate-safe modules it imports) without the rest of ts_cli. Kept importable on
Python 3.9 with only PyYAML (see catalog_model.py). `catalog_validate` re-exports
`CODE_IMPL` and `known_code_rules`.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Set

from ts_cli.audit.catalog_expr import message_problems, placeholder_problems
from ts_cli.audit.catalog_model import Rule

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
