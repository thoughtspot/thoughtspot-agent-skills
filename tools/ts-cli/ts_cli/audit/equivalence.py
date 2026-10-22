"""`compare_findings` — are two audit finding lists the same, exactly?

This was the equivalence gate that proved the rule catalog reproduces the legacy
``check_*`` functions. The rule catalog replaced those functions (their last version is main@982c2010); their findings for every
committed test input are pinned in ``tests/audit_rule_fixtures/legacy_findings.json.gz``
and ``tests/test_audit_pinned_findings.py`` holds the catalog to them with this
comparator. Its one obligation is never to call two different finding lists
identical, so it errs strict:

- A finding is keyed by ``(check_id, object_type, object_guid, object_name, detail)``
  and the lists are compared as MULTISETS of keys: a finding emitted twice must be
  emitted twice on the other side too.
- ``angle``, ``severity``, ``metric`` and ``threshold`` are compared EXACTLY — same
  type, same value, same dict key order. Python's ``==`` calls ``1 == 1.0 == True``
  and ignores dict order, but each of those serialises differently in the report
  JSON, so each is a difference here. (NaN on both sides is the one value treated
  as equal to itself.) A field absent on one side differs from ``None`` on the other.
- Fields outside the key and the compared set (for example the engine's additive
  ``categories``) are ignored.
- Order is ignored: the comparison is a multiset.

The legacy-vs-catalog runner (``run_both``) and its snapshot CLI went with the legacy
checks: there is no "old" side left to run.
"""
from __future__ import annotations

import math

KEY_FIELDS = ("check_id", "object_type", "object_guid", "object_name", "detail")
COMPARED_FIELDS = ("angle", "severity", "metric", "threshold")


class _Missing:
    """A field absent from a finding — distinct from a field set to None."""

    def __repr__(self) -> str:
        return "<missing>"


MISSING = _Missing()


# ── exact comparison ────────────────────────────────────────────────────────

def _same(a, b) -> bool:
    """Equal including exact type, sign of zero and dict key order/type; NaN equals NaN.

    Dict keys go through the strict list branch, so ``{1: x}``, ``{1.0: x}`` and
    ``{True: x}`` differ; floats compare their sign, so ``0.0`` and ``-0.0`` differ.
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    if isinstance(a, dict):
        return _same(list(a), list(b)) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _field(finding: dict, name: str):
    return finding.get(name, MISSING)


def _differing_fields(old: dict, new: dict) -> list[str]:
    return [f for f in COMPARED_FIELDS if not _same(_field(old, f), _field(new, f))]


def _tag(value):
    """A hashable stand-in that keeps the type, so 1 / 1.0 / True group apart."""
    try:
        hash(value)
        return (type(value).__name__, value)
    except TypeError:
        return (type(value).__name__, repr(value))


def finding_key(finding: dict) -> tuple:
    """The identity of a finding: ``(check_id, object_type, object_guid, object_name, detail)``."""
    return tuple(_field(finding, f) for f in KEY_FIELDS)


def _group(old: list[dict], new: list[dict]) -> dict:
    """Tagged key -> (key, old findings, new findings), in first-seen order."""
    groups: dict = {}
    for side, findings in ((1, old), (2, new)):
        for f in findings:
            key = finding_key(f)
            entry = groups.setdefault(tuple(_tag(v) for v in key), (key, [], []))
            entry[side].append(f)
    return groups


def _pop_exact(candidates: list[dict], finding: dict) -> bool:
    for i, other in enumerate(candidates):
        if not _differing_fields(finding, other):
            del candidates[i]
            return True
    return False


def _compare_group(key: tuple, old: list[dict], new: list[dict], out: dict) -> None:
    """Exact matches cancel; the rest pair in order as changes, any excess is one-sided."""
    remaining_new = list(new)
    unmatched_old = [f for f in old if not _pop_exact(remaining_new, f)]
    for o, n in zip(unmatched_old, remaining_new):
        for field in _differing_fields(o, n):
            out["changed"].append({"key": key, "field": field,
                                   "old": _field(o, field), "new": _field(n, field)})
    paired = min(len(unmatched_old), len(remaining_new))
    out["only_old"].extend(unmatched_old[paired:])
    out["only_new"].extend(remaining_new[paired:])


def compare_findings(old: list[dict], new: list[dict]) -> dict:
    """Compare two finding lists as multisets keyed by ``KEY_FIELDS``.

    Returns ``{"identical", "only_old", "only_new", "changed"}``; each ``changed``
    entry is ``{"key", "field", "old", "new"}`` for one differing compared field.
    """
    out: dict = {"identical": False, "only_old": [], "only_new": [], "changed": []}
    for key, old_group, new_group in _group(old, new).values():
        _compare_group(key, old_group, new_group, out)
    out["identical"] = not (out["only_old"] or out["only_new"] or out["changed"])
    return out
