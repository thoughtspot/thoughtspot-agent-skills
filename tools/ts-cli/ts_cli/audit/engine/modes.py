"""The aggregation modes: one function per mode, each turning one rule into findings.

Every mode skips an item the rule `requires` data for that the context does not hold
(it iterates with scopes.available, as code rules do), and renders the rule's `message` with its own placeholders
(catalog_expr.MODE_PLACEHOLDERS). The `aggregate` keys each mode reads are listed in
catalog_expr.AGGREGATE_KEYS; what a mode puts in `metric`:

    each       the `measure` value (None without a measure)
    ratio      round(pct, 1) — pct = matched / total * 100, the legacy expression
    count      the count (an int)
    group      the group's size / distinct-value count when the rule has bands, else None
    pairwise   round(similarity, 2)
    composite  round(score, 1)

The functions return findings with `angle`, `categories`, `bands` and `threshold`
unset; run.py stamps those (they depend on the catalog and the profile, not the mode).
"""
from __future__ import annotations

from itertools import combinations
from typing import Any, Callable, Dict, Iterator, List, Optional

from ts_cli.audit.catalog_model import Rule
from ts_cli.audit.engine import bands, fields, predicates, scopes
from ts_cli.audit.engine.messages import Key, NameList, render
from ts_cli.audit.findings import Finding

Mode = Callable[[Rule, Any, str], List[Finding]]


# ── shared ──────────────────────────────────────────────────────────────────

def _filtered(rule: Rule, ctx) -> Iterator[dict]:
    """Scope items with their data present that pass the aggregate's `where`."""
    where = rule.aggregate.get("where")
    return (i for i in scopes.available(ctx, rule) if predicates.passes(where, i, ctx))


def _children(rule: Rule, item: dict, ctx) -> List[dict]:
    where = rule.aggregate.get("where")
    return [c for c in scopes.iterate(ctx, rule.aggregate["over"], parent=item)
            if predicates.passes(where, c, ctx)]


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _graded(rule: Rule, value: Any) -> Optional[str]:
    """The banded severity for `value`; None for no finding (or a non-number)."""
    return bands.classify(value, rule.bands) if _is_number(value) else None


def _fixed_severity(rule: Rule, item: dict, ctx) -> Optional[str]:
    """`severity: HIGH`, or `{field, map, default}` looked up on the item."""
    sev = rule.severity
    if not isinstance(sev, dict):
        return sev
    value = fields.get(item, sev["field"], ctx)
    return next((s for k, s in sev["map"].items() if predicates.equals(k, value)),
                sev["default"])


def _finding(rule: Rule, item: dict, severity: str, detail: str, metric: Any = None,
             name: Optional[str] = None, guid: Optional[str] = None) -> Finding:
    return Finding(
        check_id=rule.id, angle="", severity=severity,
        object_type=item["object_type"],
        object_name=item["name"] if name is None else name,
        object_guid=item["guid"] if guid is None else guid,
        detail=detail, metric=metric,
    )


def _names(items: List[dict]) -> NameList:
    return NameList(i["name"] for i in items)


# ── each ────────────────────────────────────────────────────────────────────

def each(rule: Rule, ctx, profile: str) -> List[Finding]:
    """One finding per scope item passing `where`.

    Message placeholders: `{name}` is the FINDING's object name (scopes.py) — which
    shadows the object's own name where they differ: an RLS rule reports its Table, a
    model table its alias, an Answer's table reference its Answer. `{value}` is the
    `measure` value. Read the object itself with `{obj.<path>}` (`{obj.name}`,
    `{obj.properties.column_type}`) and a derived field with `{@name}`.
    """
    measure = rule.aggregate.get("measure")
    out: List[Finding] = []
    for item in _filtered(rule, ctx):
        value = fields.get(item, measure, ctx) if measure else None
        severity = _graded(rule, value) if rule.bands is not None \
            else _fixed_severity(rule, item, ctx)
        if severity is None:
            continue
        detail = render(rule.message, {"name": item["name"], "value": value}, item, ctx)
        out.append(_finding(rule, item, severity, detail, metric=value if measure else None))
    return out


# ── ratio and count (children of each scope item) ───────────────────────────

def ratio(rule: Rule, ctx, profile: str) -> List[Finding]:
    """Share of the item's `over` children passing `where` that also `match`.

    An empty population is silent. Bands grade the percentage, or the fraction when
    their unit is `ratio`.
    """
    out: List[Finding] = []
    for item in scopes.available(ctx, rule):
        population = _children(rule, item, ctx)
        if not population:
            continue
        matched = [c for c in population if predicates.evaluate(rule.aggregate["match"], c, ctx)]
        fraction = len(matched) / len(population)
        pct = (len(matched) / len(population)) * 100
        value = fraction if rule.bands.unit == "ratio" else pct
        severity = _graded(rule, value)
        if severity is None:
            continue
        hit = {id(c) for c in matched}
        values = {"name": item["name"], "value": value, "matched": len(matched),
                  "total": len(population), "pct": pct,
                  "matched_names": _names(matched),
                  "unmatched_names": _names([c for c in population if id(c) not in hit])}
        out.append(_finding(rule, item, severity, render(rule.message, values),
                            metric=round(pct, 1)))
    return out


def count(rule: Rule, ctx, profile: str) -> List[Finding]:
    """How many of the item's `over` children pass `where`, graded by bands."""
    out: List[Finding] = []
    for item in scopes.available(ctx, rule):
        children = list(scopes.iterate(ctx, rule.aggregate["over"], parent=item))
        where = rule.aggregate.get("where")
        n = sum(1 for c in children if predicates.passes(where, c, ctx))
        severity = _graded(rule, n)
        if severity is None:
            continue
        values = {"name": item["name"], "value": n, "count": n, "total": len(children)}
        out.append(_finding(rule, item, severity, render(rule.message, values), metric=n))
    return out


# ── group ───────────────────────────────────────────────────────────────────

def _hashable(v: Any) -> Any:
    """A grouping key that keeps types apart (True vs 1) and accepts lists/dicts."""
    if isinstance(v, (list, tuple)):
        return ("seq", tuple(_hashable(x) for x in v))
    if isinstance(v, dict):
        return ("map", repr(v))
    return (type(v).__name__, v)


def _group_key(key_spec: Any, item: dict, ctx) -> Any:
    if isinstance(key_spec, list):
        return Key(fields.get(item, p, ctx) for p in key_spec)
    return fields.get(item, key_spec, ctx)


def _distinct(values: List[Any]) -> NameList:
    seen, out = set(), NameList()
    for v in values:
        h = _hashable(v)
        if h not in seen:
            seen.add(h)
            out.append(v)
    return out


def _groups(rule: Rule, ctx) -> Dict[Any, tuple]:
    groups: Dict[Any, tuple] = {}
    for item in _filtered(rule, ctx):
        key = _group_key(rule.aggregate["key"], item, ctx)
        groups.setdefault(_hashable(key), (key, []))[1].append(item)
    return groups


def _group_severity(rule: Rule, first: dict, value: int, ctx) -> Optional[str]:
    if rule.bands is not None:
        return _graded(rule, value)
    return _fixed_severity(rule, first, ctx) if value > 1 else None


def _labels(agg: dict, members: List[dict], ctx) -> NameList:
    if "member" in agg:
        return NameList(fields.get(m, agg["member"], ctx) for m in members)
    return _names(members)


def group(rule: Rule, ctx, profile: str) -> List[Finding]:
    """Scope items grouped by `key`: duplicates (size > 1) or divergence (> 1 distinct
    `value`). With bands, the bands grade that number instead of the `> 1` test."""
    agg = rule.aggregate
    out: List[Finding] = []
    for key, members in _groups(rule, ctx).values():
        distinct = _distinct([fields.get(m, agg["value"], ctx) for m in members]) \
            if "value" in agg else NameList()
        value = len(distinct) if agg["kind"] == "divergence" else len(members)
        first = members[0]
        severity = _group_severity(rule, first, value, ctx)
        if severity is None:
            continue
        values = {"key": key, "size": len(members), "members": _labels(agg, members, ctx),
                  "values": distinct, "value": value}
        name = render(agg.get("name", "{key}"), values)
        guid = first["guid"] if agg.get("guid", "first") == "first" else ""
        out.append(_finding(rule, first, severity, render(rule.message, dict(values, name=name)),
                            metric=value if rule.bands is not None else None,
                            name=name, guid=guid))
    return out


# ── pairwise ────────────────────────────────────────────────────────────────

def _as_set(value: Any) -> set:
    """The collection at a pairwise `set` path; None elements (absent keys) dropped."""
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {_hashable(v) for v in value if v is not None}


def pairwise(rule: Rule, ctx, profile: str) -> List[Finding]:
    """Every unordered pair of scope items sharing at least one element of `set`,
    graded by their Jaccard similarity. A pair with an empty side is skipped."""
    sets = [(i, _as_set(fields.get(i, rule.aggregate["set"], ctx))) for i in _filtered(rule, ctx)]
    out: List[Finding] = []
    for (a, sa), (b, sb) in combinations(sets, 2):
        shared = sa & sb
        if not shared:
            continue
        union = sa | sb
        similarity = len(shared) / len(union)
        severity = _graded(rule, similarity)
        if severity is None:
            continue
        name = f"{a['name']} / {b['name']}"
        values = {"name": name, "value": similarity, "a": a["name"], "b": b["name"],
                  "similarity": similarity, "shared": len(shared), "union": len(union)}
        out.append(_finding(rule, a, severity, render(rule.message, values),
                            metric=round(similarity, 2), name=name))
    return out


# ── composite ───────────────────────────────────────────────────────────────

def _component(v: Any) -> Any:
    """A component's contribution: a number as is, true -> 100, anything else 0."""
    if isinstance(v, bool):
        return 100 if v else 0
    return v if _is_number(v) else 0


def composite(rule: Rule, ctx, profile: str) -> List[Finding]:
    """Per scope item, the sum of `weights[n] * components[n]` in component order."""
    agg = rule.aggregate
    out: List[Finding] = []
    for item in _filtered(rule, ctx):
        parts = {n: _component(fields.get(item, p, ctx)) for n, p in agg["components"].items()}
        score = 0
        for n, v in parts.items():
            score = score + v * agg["weights"][n]
        severity = _graded(rule, score)
        if severity is None:
            continue
        values = {**parts, "name": item["name"], "value": score, "score": score}
        out.append(_finding(rule, item, severity, render(rule.message, values),
                            metric=round(score, 1)))
    return out


MODES: Dict[str, Mode] = {
    "each": each, "ratio": ratio, "count": count, "group": group,
    "pairwise": pairwise, "composite": composite,
}
