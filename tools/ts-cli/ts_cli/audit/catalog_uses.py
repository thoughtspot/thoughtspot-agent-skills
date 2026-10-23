"""Catalog checks for what a rule reads: `uses:`, and `requires ∪ uses` coverage.

`build_context` fetches AI instructions, Answer TML and Sets only when a selected rule
declares them: needs = `requires ∪ uses` over the rules that will run
(`engine.run.needs_for`). Dependents are fetched for every audit, but are conditional
data all the same (`CONDITIONAL_DATA`): Set discovery writes into them, and a rule that
reads them declares them. A rule declares data one of two ways:

    requires: [answers]          fetched, AND an object lacking it is skipped
    uses: [ai_instructions]      fetched, never gates — the rule reads it but judges an
                                 object without it (A5 scores a Model whose lookup
                                 failed as uncoached rather than skip it)

`uses` takes only conditional data: Model and Table TML and metadata are fetched for
every audit, so there is nothing to declare for fetching. It is not overridable — what
a rule reads does not change with the profile.

What a rule reads is derived, not trusted to the rule: each derived field
(`@register(..., uses=...)`, engine/fields.py), code rule (`@code_rule(..., uses=...)`,
engine/code_rules.py) and scope (`SCOPE_USES`, engine/scopes.py) declares the
conditional data it reads. `undeclared_read_problems` fails a rule whose scope, the
`@fields` named anywhere in its entry, or its code read data its `requires ∪ uses`
does not cover — the mistake that would starve it silently when it moves category or
the rule that happened to fetch its data is retired. The registrations themselves are
checked statically against the code they register (catalog_reads.py), and again, as a
second layer, against what each rule's examples read when run.

The registries are imported lazily, as in catalog_expr / catalog_code, so the catalog
gate loads only the gate-safe modules. Kept importable on Python 3.9 with only PyYAML.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ts_cli.audit.catalog_expr import CONDITIONAL_DATA, SCOPES
from ts_cli.audit.catalog_model import Rule
from ts_cli.audit.catalog_reads import registry_read_problems  # noqa: F401 (re-exported)

# `@name` wherever a rule's entry may name a derived field (paths, message placeholders).
_FIELD_REF = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")
_CODE = re.compile(r"^code:([a-z_][a-z0-9_]*)$")


def data_declaration_problems(rule: Rule, requires_vocabulary: List[str]) -> List[str]:
    """`uses` values; and, for an active rule, reads neither `requires` nor `uses`
    declares (a retired rule neither runs nor fetches)."""
    out = uses_problems(rule, requires_vocabulary)
    return out + (undeclared_read_problems(rule) if rule.status == "active" else [])


def uses_problems(rule: Rule, requires_vocabulary: List[str]) -> List[str]:
    """`uses` values: conditional data only, and not already in `requires`."""
    out: List[str] = []
    for value in rule.uses:
        if value in CONDITIONAL_DATA:
            if value in rule.requires:
                out.append(f"uses: '{value}' is already in requires (which also fetches "
                           "it) — declare it once")
        elif value in requires_vocabulary:
            out.append(f"uses: '{value}' is not conditional data — model_tml, table_tml "
                       "and metadata are fetched for every audit, so they are never declared "
                       f"in uses (uses takes: {', '.join(CONDITIONAL_DATA)})")
        else:
            out.append(f"uses: unknown uses value '{value}' "
                       f"(known: {', '.join(CONDITIONAL_DATA)})")
    return out


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def _field_refs(rule: Rule) -> List[str]:
    """Registered derived fields named anywhere the engine reads them: the aggregate,
    a severity mapping, the message — the rule's and every profile's override."""
    from ts_cli.audit.engine.fields import FIELDS
    parts = [rule.aggregate, rule.severity, rule.message,
             [{k: v for k, v in (p or {}).items() if k in ("severity", "message")}
              for p in rule.profiles.values() if isinstance(p, dict)]]
    names = {m for s in _strings(parts) for m in _FIELD_REF.findall(s)}
    return sorted(n for n in names if n in FIELDS)


def data_reads(rule: Rule) -> Dict[str, List[str]]:
    """Conditional data `rule` reads -> what reads it (`scope <s>`, `@field`,
    `code:<name>`), from the registries' declarations."""
    from ts_cli.audit.engine.code_rules import CODE_USES
    from ts_cli.audit.engine.fields import FIELD_USES
    from ts_cli.audit.engine.scopes import SCOPE_USES
    sources: List[tuple] = [(f"scope {rule.scope}", SCOPE_USES.get(rule.scope, ()))]
    sources += [(f"@{name}", FIELD_USES.get(name, ())) for name in _field_refs(rule)]
    m = _CODE.match(rule.implementation)
    if m:
        sources.append((rule.implementation, CODE_USES.get(m.group(1), ())))
    reads: Dict[str, List[str]] = {}
    for source, data in sources:
        for d in sorted(data):
            reads.setdefault(d, []).append(source)
    return reads


def undeclared_read_problems(rule: Rule) -> List[str]:
    """Conditional data the rule reads that neither `requires` nor `uses` declares. A
    scope SCOPE_USES does not list fails closed: what it reads is unknown. (An unknown
    scope is reported by the scope check.)"""
    from ts_cli.audit.engine.scopes import SCOPE_USES
    if rule.scope in SCOPES and rule.scope not in SCOPE_USES:
        return [f"scope '{rule.scope}' is not registered in engine/scopes.py SCOPE_USES, "
                "so what it reads cannot be checked — register it"]
    declared = set(rule.requires) | set(rule.uses)
    return [f"reads '{data}' (via {', '.join(via)}) but neither requires nor uses "
            f"declares it — it would not be fetched unless another selected rule asks "
            f"for it; add it to uses (fetched, never skips) or requires (fetched, and "
            f"an object lacking it is skipped)"
            for data, via in data_reads(rule).items() if data not in declared]
