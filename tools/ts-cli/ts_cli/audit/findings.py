from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class Finding:
    check_id: str
    angle: str
    severity: str
    object_type: str
    object_name: str
    object_guid: str
    detail: str
    metric: Optional[Union[int, float]] = None
    threshold: Optional[dict] = None
    # Additive (rule catalog): every category the rule belongs to — `angle` stays the
    # first one's legacy key — and the uniform band payload
    # {direction, unit, levels: [{op, value, severity}], profile, provenance}.
    categories: list[str] = field(default_factory=list)
    bands: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "angle": self.angle,
            "severity": self.severity,
            "object_type": self.object_type,
            "object_name": self.object_name,
            "object_guid": self.object_guid,
            "detail": self.detail,
            "metric": self.metric,
            "threshold": self.threshold,
            "categories": list(self.categories),
            "bands": self.bands,
        }


_SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
_ANGLES = ["ai", "data_modeling", "human", "performance", "security"]

def __getattr__(name: str):
    """`CHECK_META` — `{rule id: {desc, thresholds, ...}}` for the active catalog rules —
    is built from the rule catalog (generate.report_meta) on first use, not written by
    hand: the hand-kept table described checks that did not exist (S8/S9, BL-298)."""
    if name == "CHECK_META":
        from ts_cli.audit.catalog_model import load_catalog
        from ts_cli.audit.generate import report_meta
        return report_meta(load_catalog())["checks"]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def build_summary(
    findings: list[Finding],
    checks_run: int,
    models_count: int,
    tables_count: int,
    all_check_ids: list[str] | None = None,
    categories: list[str] | None = None,
) -> dict:
    """Counts for the report header. A finding counts ONCE in `by_severity` and
    `by_angle` (its first category's angle) and once under EVERY category it belongs
    to in `by_category` — so the categories may sum to more than the total.
    `categories` lists the category ids to report (each starts at 0); a finding's
    category outside it is added."""
    by_severity = {s: 0 for s in _SEVERITIES}
    by_angle = {a: 0 for a in _ANGLES}
    by_category = {c: 0 for c in (categories or [])}
    for f in findings:
        if f.severity in by_severity:
            by_severity[f.severity] += 1
        if f.angle in by_angle:
            by_angle[f.angle] += 1
        for cat in dict.fromkeys(f.categories):
            by_category[cat] = by_category.get(cat, 0) + 1
    if all_check_ids is not None:
        check_ids = sorted(set(all_check_ids))
    else:
        check_ids = sorted({f.check_id for f in findings})
    return {
        "by_severity": by_severity,
        "by_angle": by_angle,
        "by_category": by_category,
        "objects_scanned": {"models": models_count, "tables": tables_count},
        "checks_run": checks_run,
        "all_check_ids": check_ids,
    }
