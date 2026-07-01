from __future__ import annotations

from dataclasses import dataclass
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
        }


_SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
_ANGLES = ["ai", "data_modeling", "human", "performance", "security"]


def build_summary(
    findings: list[Finding],
    checks_run: int,
    models_count: int,
    tables_count: int,
) -> dict:
    by_severity = {s: 0 for s in _SEVERITIES}
    by_angle = {a: 0 for a in _ANGLES}
    for f in findings:
        if f.severity in by_severity:
            by_severity[f.severity] += 1
        if f.angle in by_angle:
            by_angle[f.angle] += 1
    return {
        "by_severity": by_severity,
        "by_angle": by_angle,
        "objects_scanned": {"models": models_count, "tables": tables_count},
        "checks_run": checks_run,
    }
