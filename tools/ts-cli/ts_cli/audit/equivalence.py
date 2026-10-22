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

    python -m ts_cli.audit.equivalence --snapshot DIR --profile spotter|general [--rules A1,D2]

It prints a per-rule ``rule | old | new | diff`` table and exits 0 only when the two
sides are identical (1 when they differ, 2 when the comparison could not run).
"""
from __future__ import annotations

import argparse
import copy
import math
import re
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional

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
    """Equal including exact type and dict key order; NaN equals NaN."""
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        return a == b or (math.isnan(a) and math.isnan(b))
    if isinstance(a, dict):
        return list(a) == list(b) and all(_same(a[k], b[k]) for k in a)
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


def per_rule_rows(old: list[dict], new: list[dict], result: dict) -> list[tuple]:
    """``(rule, old count, new count, diff)`` per rule, sorted A2 before A10.

    ``diff`` counts the rule's one-sided findings plus its differing fields.
    """
    counts: dict = {}

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
    from ts_cli.audit import ANGLE_MODULES
    legacy_ctx = copy.deepcopy(ctx)
    legacy_ctx.assessment = profile  # the legacy A-checks read the bar from the context
    return [f.to_dict() for cat in categories
            for check in ANGLE_MODULES[cat].ALL_CHECKS for f in check(legacy_ctx)]


def _resolve_categories(categories: Optional[list]) -> list:
    from ts_cli.audit import ANGLE_MODULES
    cats = list(categories) if categories is not None else list(ANGLE_MODULES)
    unknown = [c for c in cats if c not in ANGLE_MODULES]
    if unknown:
        raise ValueError(f"unknown categories {unknown}: use {', '.join(ANGLE_MODULES)}")
    return cats


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


def _report(old: list[dict], new: list[dict], result: dict) -> str:
    out = [_format_table(per_rule_rows(old, new, result)), ""]
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
    p.add_argument("--rules", default=None,
                   help="comma-separated rule ids to compare (default: all)")
    return p.parse_args(argv)


def main(argv: Optional[list] = None, *, new_runner: Optional[NewRunner] = None) -> int:
    """Exit 0 when identical, 1 when the findings differ, 2 when the run could not happen."""
    from ts_cli.audit.snapshot import SnapshotError, read_snapshot
    args = _parse_args(argv)
    check_ids = [r.strip() for r in args.rules.split(",") if r.strip()] if args.rules else None
    try:
        ctx, captured = read_snapshot(args.snapshot)
        old, new = collect_both(ctx, args.profile, check_ids, new_runner=new_runner,
                                categories=captured)
    except (SnapshotError, ImportError, ValueError) as exc:
        print(f"equivalence: cannot compare: {exc}", file=sys.stderr)
        return 2
    result = compare_findings(old, new)
    print(_report(old, new, result))
    return 0 if result["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
