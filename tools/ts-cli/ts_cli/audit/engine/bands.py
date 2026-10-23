"""Severity bands, and the override layering that picks a rule's effective values.

`classify(value, bands)` walks the levels in order (worst first) and returns the first
matching level's severity, or None — no finding. `fixed_severity(rule, item, ctx)` is
the severity of a rule without bands (a name, or a mapping looked up on the item).

`effective(rule, layers)` folds override layers onto a catalog rule:

    catalog default -> profile -> (future) cluster -> (future) Org -> ...

Each layer is `{"source": <provenance name>, "overrides": {key: value}}` and may change
only OVERRIDABLE keys (status, bands, severity, message, remediation); `bands` is
replaced whole, never merged level by level. A key outside OVERRIDABLE is ignored and
recorded in the provenance's `ignored` list — except `legacy_threshold` in a profile
layer, which the catalog allows there and `run.py` reads separately.

The provenance says which layer supplied the bands and the severity, so a report
produced under overrides is explainable. A banded rule's severity comes from its bands,
so the two share a source; a fixed-severity rule's comes from its `severity` key.
"""
from __future__ import annotations

import dataclasses
import operator
from typing import Any, Dict, List, Optional, Tuple

from ts_cli.audit.catalog_model import Bands, Rule, parse_bands
from ts_cli.audit.catalog_validate import OVERRIDABLE, PROFILE_ONLY
from ts_cli.audit.engine import fields, predicates

_OPS = {"lt": operator.lt, "lte": operator.le, "gt": operator.gt, "gte": operator.ge,
        "eq": operator.eq}
CATALOG = "catalog"


def classify(value: float, b: Bands) -> Optional[str]:
    """Severity of the first level `value` falls in (worst first); None if none."""
    for level in b.levels:
        if _OPS[level.op](value, level.value):
            return level.severity
    return None


def fixed_severity(rule: Rule, item: dict, ctx: Any) -> Optional[str]:
    """A rule's severity without bands: `severity: HIGH`, or `{field, map, default}`
    looked up on the item (exact, type-sensitive — predicates.equals)."""
    sev = rule.severity
    if not isinstance(sev, dict):
        return sev
    value = fields.get(item, sev["field"], ctx)
    return next((s for k, s in sev["map"].items() if predicates.equals(k, value)),
                sev["default"])


def effective(rule: Rule, layers: List[Dict[str, Any]]) -> Tuple[Rule, Dict[str, Any]]:
    """The rule with every layer's allowed overrides applied, and their provenance."""
    changes: Dict[str, Any] = {}
    source = {key: CATALOG for key in OVERRIDABLE}
    ignored: List[Dict[str, str]] = []
    for layer in layers:
        name = layer["source"]
        for key, value in (layer.get("overrides") or {}).items():
            if key in OVERRIDABLE and value is not None:
                changes[key] = _parsed(rule, key, value, name)
                source[key] = name
            elif not (key in PROFILE_ONLY and name.startswith("profile:")):
                ignored.append({"layer": name, "key": key})  # incl. a null: removes nothing
    merged = dataclasses.replace(rule, **changes)
    banded = merged.bands is not None
    provenance: Dict[str, Any] = {
        "bands": source["bands"],
        "severity": source["bands"] if banded else source["severity"],
    }
    if ignored:
        provenance["ignored"] = ignored
    return merged, provenance


def _parsed(rule: Rule, key: str, value: Any, layer: str) -> Any:
    return parse_bands(value, layer, rule.id) if key == "bands" else value


def payload(rule: Rule, profile: str, provenance: Dict[str, Any]) -> Dict[str, Any]:
    """The uniform `Finding.bands` payload. A fixed-severity rule has no levels."""
    b = rule.bands
    return {
        "direction": b.direction if b else None,
        "unit": b.unit if b else None,
        "levels": [{"op": lv.op, "value": lv.value, "severity": lv.severity}
                   for lv in b.levels] if b else [],
        "profile": profile,
        "provenance": provenance,
    }
