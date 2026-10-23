"""`run_rule` — what one catalog rule reports for a context, run the way `ts audit run`
runs it.

The audit's tests called the legacy check functions (`check_d3(ctx)`) until the rule
catalog replaced them; they now call `run_rule(ctx, "D3")`. It runs the rule's whole first
category through the engine's `run_rules` (the call `ts audit run` makes) and keeps
the rule's own findings, so a test sees exactly what an audit would report for it.

The profile is an argument, never `ctx.assessment` — the engine does not read it.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List

from ts_cli.audit.catalog_model import Catalog, load_catalog
from ts_cli.audit.engine.run import run_rules
from ts_cli.audit.findings import Finding


@lru_cache(maxsize=1)
def catalog() -> Catalog:
    """The packaged catalog, loaded once per test session (the engine never mutates it)."""
    return load_catalog()


def findings_by_rule(ctx, category: str, profile: str = "general") -> Dict[str, List[Finding]]:
    """Every finding `run_rules(ctx, catalog, [category], profile)` returns, grouped by
    rule id in the order the rules ran."""
    out: Dict[str, List[Finding]] = {}
    for f in run_rules(ctx, catalog(), [category], profile):
        out.setdefault(f.check_id, []).append(f)
    return out


def run_rule(ctx, rule_id: str, profile: str = "general") -> List[Finding]:
    """The findings of catalog rule `rule_id` over `ctx` under `profile`: its first
    category run through `run_rules`, filtered to the rule. KeyError for an unknown id;
    a retired rule reports nothing, as it does in an audit."""
    rule = catalog().rules[rule_id]
    return findings_by_rule(ctx, rule.categories[0], profile).get(rule_id, [])


def active_rule_ids(category: str) -> List[str]:
    """The ids of the catalog's active rules in `category`, in catalog order."""
    return [r.id for r in catalog().rules.values()
            if r.status == "active" and category in r.categories]
