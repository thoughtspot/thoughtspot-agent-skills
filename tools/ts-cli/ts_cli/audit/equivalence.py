"""Equivalence gate: do the legacy checks and the rule engine emit the same findings?

The rule catalog must reproduce the legacy ``check_*`` functions exactly, and this
module is how that is proved. Its one obligation is never to call two different
finding lists identical, so it errs strict:

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

Run it over a snapshot (``audit/snapshot.py``)::

    python -m ts_cli.audit.equivalence --snapshot DIR --profile spotter|general [--rules|--checks A1,D2]

It prints a per-rule ``rule | old | new | diff`` table and exits 0 only when the two
sides are identical (1 when they differ, 2 when the comparison could not run or the
rule selection names nothing it can compare).
"""
from __future__ import annotations

import argparse
import copy
import math
import re
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional

from ts_cli.audit import checks_ai, checks_data, checks_human, checks_perf, checks_security

#: The legacy check modules by category — the "old" side. `ts audit run` no longer
#: uses them (it runs the catalog); this comparison is their last caller.
ANGLE_MODULES = {
    "A": checks_ai,
    "D": checks_data,
    "H": checks_human,
    "P": checks_perf,
    "S": checks_security,
}

KEY_FIELDS = ("check_id", "object_type", "object_guid", "object_name", "detail")
COMPARED_FIELDS = ("angle", "severity", "metric", "threshold")
MAX_LISTED_DIFFERENCES = 20


class _Missing:
    """A field absent from a finding — distinct from a field set to None."""

    def __repr__(self) -> str:
        return "<missing>"


MISSING = _Missing()

NewRunner = Callable[[object, str, list], Iterable]


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


# ── per-rule summary ────────────────────────────────────────────────────────

def _rule_sort_key(rule) -> tuple:
    text = str(rule)
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", text)
    return (m.group(1), int(m.group(2)), "") if m else (text, -1, text)


def per_rule_rows(old: list[dict], new: list[dict], result: dict,
                  requested: Optional[list] = None) -> list[tuple]:
    """``(rule, old count, new count, diff)`` per rule, sorted A2 before A10.

    ``diff`` counts the rule's one-sided findings plus its differing fields. Every
    ``requested`` rule gets a row even when neither side found anything, so a rule
    the comparison never exercised is visible instead of absent.
    """
    counts: dict = {rule: [0, 0, 0] for rule in (requested or [])}

    def bump(rule, col):
        counts.setdefault(rule, [0, 0, 0])[col] += 1

    for f in old:
        bump(_field(f, "check_id"), 0)
    for f in new:
        bump(_field(f, "check_id"), 1)
    for f in result["only_old"] + result["only_new"]:
        bump(_field(f, "check_id"), 2)
    for c in result["changed"]:
        bump(c["key"][0], 2)
    return [(rule, *vals) for rule, vals in sorted(counts.items(), key=lambda kv: _rule_sort_key(kv[0]))]


# ── running both sides ──────────────────────────────────────────────────────

def _engine_runner(ctx, profile: str, categories: list) -> list:
    """The rule engine (Task 4), imported lazily so this module imports without it."""
    from ts_cli.audit.catalog_model import load_catalog
    from ts_cli.audit.engine.run import run_rules
    return run_rules(ctx, load_catalog(), categories, profile)


def _as_dict(finding) -> dict:
    return finding if isinstance(finding, dict) else finding.to_dict()


def _legacy_findings(ctx, profile: str, categories: list) -> list[dict]:
    legacy_ctx = copy.deepcopy(ctx)
    legacy_ctx.assessment = profile  # the legacy A-checks read the bar from the context
    return [f.to_dict() for cat in categories
            for check in ANGLE_MODULES[cat].ALL_CHECKS for f in check(legacy_ctx)]


def _resolve_categories(categories: Optional[list]) -> list:
    cats = list(categories) if categories is not None else list(ANGLE_MODULES)
    unknown = [c for c in cats if c not in ANGLE_MODULES]
    if unknown:
        raise ValueError(f"unknown categories {unknown}: use {', '.join(ANGLE_MODULES)}")
    return cats


def legacy_rule_ids(categories: Optional[list] = None) -> list[str]:
    """The rule ids the legacy checks run for ``categories``, named as
    ``audit/__init__.py`` names them: ``check_a1`` -> ``A1``."""
    return [fn.__name__.replace("check_", "").upper()
            for cat in _resolve_categories(categories) for fn in ANGLE_MODULES[cat].ALL_CHECKS]


def resolve_check_ids(check_ids: Optional[list], categories: Optional[list] = None):
    """Validate requested rule ids; None means every rule.

    Raises ``ValueError`` for an empty selection or an id the legacy checks do not
    run for ``categories`` (a typo, the wrong case, or an uncaptured category) —
    each of those would otherwise compare nothing and read as identical.
    """
    if check_ids is None:
        return None
    ids = list(dict.fromkeys(check_ids))
    if not ids:
        raise ValueError("no rule ids given: name at least one, or omit the selection")
    known = legacy_rule_ids(categories)
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ValueError(f"rule id(s) {', '.join(map(str, unknown))} are not run for "
                         f"categories {', '.join(_resolve_categories(categories))} "
                         f"(known: {', '.join(known)})")
    return ids


def collect_both(ctx, profile: str, check_ids: Optional[list] = None, *,
                 new_runner: Optional[NewRunner] = None,
                 categories: Optional[list] = None) -> tuple[list[dict], list[dict]]:
    """Run the legacy checks and the new side over copies of ``ctx``; return both finding lists.

    The legacy side gets ``ctx.assessment = profile``. The new side gets ``profile``
    as an argument and a copy of ``ctx`` with its CAPTURED assessment left as is, so
    an engine that reads the context instead of its argument shows up as a
    difference rather than being masked. ``ctx`` itself is never mutated.
    """
    from ts_cli.audit import assessment
    profile = assessment.normalise(profile)
    cats = _resolve_categories(categories)
    check_ids = resolve_check_ids(check_ids, cats)
    old = _legacy_findings(ctx, profile, cats)
    runner = new_runner or _engine_runner
    new = [_as_dict(f) for f in runner(copy.deepcopy(ctx), profile, cats)]
    if check_ids is not None:
        wanted = set(check_ids)
        old = [f for f in old if f.get("check_id") in wanted]
        new = [f for f in new if f.get("check_id") in wanted]
    return old, new


def run_both(ctx, profile: str, check_ids: Optional[list] = None, *,
             new_runner: Optional[NewRunner] = None,
             categories: Optional[list] = None) -> dict:
    """``compare_findings`` of the legacy checks vs the rule engine for ``check_ids``.

    ``new_runner(ctx, profile, categories)`` replaces the engine (tests inject a fake);
    by default it is ``run_rules`` over the packaged catalog. ``check_ids=None``
    compares every rule; ``categories=None`` runs every category.
    """
    old, new = collect_both(ctx, profile, check_ids, new_runner=new_runner,
                            categories=categories)
    return compare_findings(old, new)


# ── CLI ─────────────────────────────────────────────────────────────────────

def _format_table(rows: list[tuple]) -> str:
    header = ("rule", "old", "new", "diff")
    body = [tuple(str(v) for v in r) for r in rows]
    total = ("TOTAL", *(str(sum(r[i] for r in rows)) for i in (1, 2, 3)))
    widths = [max(len(r[i]) for r in [header, *body, total]) for i in range(4)]

    def line(r):
        return " | ".join(v.ljust(w) if i == 0 else v.rjust(w)
                          for i, (v, w) in enumerate(zip(r, widths)))
    rule = "-+-".join("-" * w for w in widths)
    return "\n".join([line(header), rule, *map(line, body), rule, line(total)])


def _format_differences(result: dict) -> list[str]:
    lines = [f"  only_old: {finding_key(f)}" for f in result["only_old"]]
    lines += [f"  only_new: {finding_key(f)}" for f in result["only_new"]]
    lines += [f"  changed:  {c['key']} {c['field']}: {c['old']!r} -> {c['new']!r}"
              for c in result["changed"]]
    if len(lines) > MAX_LISTED_DIFFERENCES:
        hidden = len(lines) - MAX_LISTED_DIFFERENCES
        lines = lines[:MAX_LISTED_DIFFERENCES] + [f"  ... and {hidden} more"]
    return lines


def _report(old: list[dict], new: list[dict], result: dict,
            requested: Optional[list] = None) -> str:
    rows = per_rule_rows(old, new, result, requested)
    out = [_format_table(rows), ""]
    idle = [r[0] for r in rows if r[0] in (requested or []) and r[1] == r[2] == 0]
    if idle:
        out.append(f"not exercised: {', '.join(idle)} (no findings on either side, "
                   "so this snapshot proves nothing about them)")
    if result["identical"]:
        out.append(f"IDENTICAL: {len(old)} findings on both sides")
    else:
        out.append(f"NOT identical: {len(result['only_old'])} only in old, "
                   f"{len(result['only_new'])} only in new, "
                   f"{len(result['changed'])} changed field(s)")
        out.extend(_format_differences(result))
    return "\n".join(out)


def _parse_args(argv: Optional[list]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m ts_cli.audit.equivalence",
        description="Compare legacy audit checks with the rule engine over a snapshot.")
    p.add_argument("--snapshot", required=True, type=Path, help="snapshot directory")
    p.add_argument("--profile", default="general", choices=["spotter", "general"])
    p.add_argument("--rules", "--checks", dest="rules", default=None,
                   help="comma-separated rule ids to compare (default: all)")
    return p.parse_args(argv)


def main(argv: Optional[list] = None, *, new_runner: Optional[NewRunner] = None) -> int:
    """Exit 0 when identical, 1 when the findings differ, 2 when the run could not happen."""
    from ts_cli.audit.snapshot import SnapshotError, read_snapshot
    args = _parse_args(argv)
    check_ids = (None if args.rules is None
                 else [r.strip() for r in args.rules.split(",") if r.strip()])
    try:
        ctx, captured = read_snapshot(args.snapshot)
        check_ids = resolve_check_ids(check_ids, captured)
        old, new = collect_both(ctx, args.profile, check_ids, new_runner=new_runner,
                                categories=captured)
    except (SnapshotError, ImportError, ValueError) as exc:
        print(f"equivalence: cannot compare: {exc}", file=sys.stderr)
        return 2
    result = compare_findings(old, new)
    print(_report(old, new, result, check_ids))
    return 0 if result["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
