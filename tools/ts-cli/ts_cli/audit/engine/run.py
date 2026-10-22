"""`run_rules` — run the catalog's rules over an AuditContext.

The finding contract (what the equivalence gate compares with the legacy checks):

    check_id     the rule id
    angle        the `angle_key` of the rule's FIRST category ("ai", "data_modeling", …)
    severity, object_type/name/guid, detail, metric   from the rule's mode (modes.py)
    threshold    the rule's `legacy_threshold` — the profile's own when it sets one;
                 in its `by_severity` form, the entry for the finding's severity —
                 with `{profile_label}` rendered; key order and number types as written
                 in YAML; None when the rule has none. A code rule whose catalog entry
                 has no legacy threshold may set one per finding itself (D1: one per
                 measure); the runner keeps it
    categories   every category id of the rule (additive)
    bands        {direction, unit, levels, profile, provenance} (additive; bands.py)

A code rule (`implementation: code:<name>`) is dispatched to its registered function
(code_rules.py), which returns the finding fields above `categories`; the runner checks
its contract and stamps angle, categories, bands and threshold exactly as for a
declarative rule.

The profile is the `profile` argument and nothing else — never `ctx.assessment`, which
a replayed snapshot carries from its capture.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Iterator, List, Optional, Set

from ts_cli.audit.catalog_forms import BY_SEVERITY
from ts_cli.audit.catalog_model import Catalog, Rule
from ts_cli.audit.engine import bands, code_rules, memo
from ts_cli.audit.engine.modes import MODES
from ts_cli.audit.findings import Finding


def run_rules(ctx, catalog: Catalog, categories: List[str], profile: str,
              layers: Optional[List[Dict[str, Any]]] = None) -> List[Finding]:
    """Findings of every active rule in any of `categories`, under `profile`.

    `layers` are further override layers after the profile, each `{rule_id: {key:
    value}}`, applied in order; their provenance is `layer:2`, `layer:3`, … (the
    catalog is layer 0, the profile layer 1).
    """
    _check_selection(catalog, categories, profile)
    findings: List[Finding] = []
    with memo.run_scope():  # lookups shared across items are computed once per run
        for rule in _selected(catalog, categories):
            findings += _run_rule(ctx, catalog, rule, profile, layers or [])
    return findings


def needs_for(catalog: Catalog, categories: List[str], profile: str,
              layers: Optional[List[Dict[str, Any]]] = None) -> Set[str]:
    """The data the rules `run_rules(ctx, catalog, categories, profile, layers)` would
    run DECLARE: the union of `requires` and `uses` over the rules selected, active in
    the catalog, and still active once the profile and `layers` are applied (`status`
    is overridable; `requires` and `uses` are not). A retired rule, or one a profile or
    layer switches off, contributes nothing.

    `build_context` fetches the conditional data (`ai_instructions`, `answers`, `sets`)
    only when it is in here. Rules also read data they do not declare — Model and Table
    TML, which are fetched unconditionally for that reason; the catalog gate holds every
    rule's conditional reads to its declarations (catalog_uses.py)."""
    _check_selection(catalog, categories, profile)
    needs: Set[str] = set()
    for rule in _selected(catalog, categories):
        merged, _ = bands.effective(rule, layers_for(rule, profile, layers or []))
        if merged.status == "active":
            needs.update(rule.requires, rule.uses)
    return needs


def _selected(catalog: Catalog, categories: List[str]) -> Iterator[Rule]:
    """The catalog-active rules in any of `categories`. A layer cannot revive a rule
    retired in the catalog here (only `run_rule`, run singly, can)."""
    wanted = set(categories)
    return (r for r in catalog.rules.values()
            if r.status == "active" and wanted.intersection(r.categories))


def run_rule(ctx, catalog: Catalog, rule_id: str, profile: str,
             layers: Optional[List[Dict[str, Any]]] = None) -> List[Finding]:
    """Findings of the one rule `rule_id` under `profile` (none if it is retired) —
    what a rule's catalog examples are checked against."""
    _check_selection(catalog, [], profile)
    if rule_id not in catalog.rules:
        raise KeyError(f"unknown rule '{rule_id}'")
    with memo.run_scope():
        return _run_rule(ctx, catalog, catalog.rules[rule_id], profile, layers or [])


def _check_selection(catalog: Catalog, categories: List[str], profile: str) -> None:
    if profile not in catalog.profiles:
        raise ValueError(f"unknown profile '{profile}' (known: {', '.join(catalog.profiles)})")
    unknown = [c for c in categories if c not in catalog.categories]
    if unknown:
        raise ValueError(f"unknown categories {unknown} (known: {', '.join(catalog.categories)})")


def layers_for(rule: Rule, profile: str, extra: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The override layers for one rule: its profile block, then each extra layer."""
    out = [{"source": f"profile:{profile}", "overrides": rule.profiles.get(profile) or {}}]
    out += [{"source": f"layer:{i + 2}", "overrides": layer.get(rule.id) or {}}
            for i, layer in enumerate(extra)]
    return out


def _run_rule(ctx, catalog: Catalog, rule: Rule, profile: str,
              extra: List[Dict[str, Any]]) -> List[Finding]:
    merged, provenance = bands.effective(rule, layers_for(rule, profile, extra))
    if merged.status != "active":
        return []
    found = _dispatch(merged, ctx, profile)
    angle = catalog.categories[rule.categories[0]].angle_key
    payload = bands.payload(merged, profile, provenance)
    label = catalog.profiles[profile].label
    for f in found:
        own = f.threshold  # set only by a code rule (code_rules.check_findings)
        f.angle, f.categories = angle, list(rule.categories)
        f.bands = copy.deepcopy(payload)
        f.threshold = own if own is not None else \
            legacy_threshold(rule, profile, label, f.severity)
    return found


def _dispatch(rule: Rule, ctx, profile: str) -> List[Finding]:
    if rule.implementation != "declarative":
        return code_rules.run_code_rule(rule, ctx, profile)
    if not rule.aggregate:
        # A retired placeholder (H6) revived by an override layer: loud, never silent.
        raise ValueError(f"{rule.id}: has no logic (no aggregate, no implementation) — "
                         "a retired placeholder cannot run")
    return MODES[rule.aggregate["mode"]](rule, ctx, profile)


def legacy_threshold(rule: Rule, profile: str, profile_label: str,
                     severity: Optional[str] = None) -> Optional[dict]:
    """The pre-catalog `threshold` dict: the profile's `legacy_threshold`, else the
    rule's — in the `by_severity` form, its entry for `severity` (none: None) — with
    `{profile_label}` rendered in string values (order/types kept)."""
    source = (rule.profiles.get(profile) or {}).get("legacy_threshold", rule.legacy_threshold)
    if isinstance(source, dict) and BY_SEVERITY in source:
        source = source[BY_SEVERITY].get(severity)
    if source is None:
        return None
    return {k: v.format_map({"profile_label": profile_label}) if isinstance(v, str) else
            copy.deepcopy(v) for k, v in source.items()}
