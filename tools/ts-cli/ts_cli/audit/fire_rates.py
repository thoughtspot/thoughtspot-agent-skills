"""How often each rule fires (the severity rubric, audit v2 roadmap PR 4.2; design:
docs/superpowers/specs/2026-11-01-audit-severity-rubric-design.md).

A rule that fires at MEDIUM or above on more than half of its objects is either telling
the reader something about the whole estate or mis-calibrated, so it warns, unless its
catalog entry carries a review for that assessment (`fire_rate_reviewed`, checked by
catalog_evidence.fire_rate_problems) that is under 180 days old and whose rate the
current one does not exceed by more than 10 points.

A rule is counted against its own objects: the top-level items of its scope (a join or
column finding carries its Model's guid, an RLS column reference its Table's), so a
Table rule is a share of Tables, an Answer rule a share of Answers. A rule whose findings
name no object (an empty or `none` guid) is listed by finding count and never warns.

Pure: counts in, counts out. Never names or guids in what it returns.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, Iterable, List, Optional

WARN_SHARE = 0.5
REVIEW_DAYS = 180
REVIEW_RISE = 0.10
_AT_LEAST_MEDIUM = {"MEDIUM", "HIGH", "CRITICAL"}
#: A scope whose findings carry another scope's guid.
_COUNTED_AS = {"join": "model", "rls_column_ref": "table"}


def object_kind(scope: str) -> str:
    """The kind of object a rule's findings are counted against."""
    top = (scope or "").split(".")[0]
    return _COUNTED_AS.get(top, top)


def object_counts(ctx: Any, kinds: Iterable[str]) -> Dict[str, int]:
    """How many top-level objects of each kind the context holds."""
    from ts_cli.audit.engine import scopes
    return {k: sum(1 for _ in scopes.iterate(ctx, k)) for k in set(kinds) if k}


def _as_date(value: Any) -> Optional[datetime.date]:
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


def _review_holds(review: Any, share: float, today: datetime.date) -> bool:
    if not isinstance(review, dict):
        return False
    when = _as_date(review.get("date"))
    rate = review.get("rate")
    return (when is not None and (today - when).days <= REVIEW_DAYS
            and isinstance(rate, (int, float)) and share <= rate + REVIEW_RISE)


def _row(rule: Any, found: List[dict], profile: str, counts: Dict[str, int],
         today: datetime.date) -> dict:
    kind = object_kind(rule.scope)
    by_severity: Dict[str, int] = {}
    for f in found:
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
    objectless = any(str(f.get("object_guid") or "").lower() in ("", "none") for f in found)
    objects = counts.get(kind, 0)
    fired = len({f["object_guid"] for f in found if f["severity"] in _AT_LEAST_MEDIUM})
    share = None if objectless or not objects else round(fired / objects, 4)
    review = (rule.fire_rate_reviewed or {}).get(profile)
    reviewed = share is not None and _review_holds(review, share, today)
    return {"rule": rule.id, "kind": kind, "objects": objects,
            "fired": None if objectless else fired, "findings": len(found),
            "share": share, "by_severity": by_severity,
            "warns": share is not None and share > WARN_SHARE and not reviewed,
            "reviewed": reviewed}


def fire_rates(findings: List[dict], catalog: Any, profile: str, counts: Dict[str, int],
               today: datetime.date) -> List[dict]:
    """One row per active rule — `rule, kind, objects, fired, findings, share,
    by_severity, warns, reviewed` — the highest share first."""
    by_rule: Dict[str, List[dict]] = {}
    for f in findings:
        by_rule.setdefault(f["check_id"], []).append(f)
    rows = [_row(rule, by_rule.get(rule.id, []), profile, counts, today)
            for rule in catalog.rules.values() if rule.status == "active"]
    return sorted(rows, key=lambda r: (-(r["share"] or 0), r["rule"]))
