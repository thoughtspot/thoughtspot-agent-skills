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

CHECK_META: dict[str, dict[str, str]] = {
    "A1": {"desc": "Description coverage below threshold", "thresholds": "GREEN >= 80%, YELLOW >= 50%"},
    "A2": {"desc": "Synonym coverage below threshold", "thresholds": "GREEN >= 50%, YELLOW >= 25%"},
    "A3": {"desc": "No AI instructions configured", "thresholds": "HIGH if absent"},
    "A4": {"desc": "Missing Spotter config", "thresholds": "HIGH (Spotter) / MEDIUM (General)"},
    "A5": {"desc": "Spotter readiness composite score", "thresholds": "Weighted score -> severity"},
    "D1": {"desc": "Model complexity exceeds threshold", "thresholds": "Tables >15 RED, Columns >75 RED"},
    "D2": {"desc": "VARCHAR join keys detected", "thresholds": "HIGH per occurrence"},
    "D3": {"desc": "Join type analysis (FULL OUTER, LEFT/RIGHT)", "thresholds": "HIGH for FULL OUTER, INFO for others"},
    "D4": {"desc": "Progressive joins disabled on large models", "thresholds": "HIGH if >5 tables + join_progressive:false"},
    "D5": {"desc": "Orphan tables in model (Cartesian risk)", "thresholds": "MEDIUM per orphan table"},
    "D6": {"desc": "Grain consistency — fact tables with >40% attributes", "thresholds": "MEDIUM per model"},
    "D7": {"desc": "High model overlap detected", "thresholds": "Jaccard >= 0.5 with shared facts"},
    "D8": {"desc": "Duplicate table objects found", "thresholds": "HIGH per duplicate group"},
    "D9": {"desc": "SQL pass-through function usage (>20% formulas)", "thresholds": "MEDIUM / HIGH by percentage"},
    "D10": {"desc": "Zero-column tables (bridge vs leaf)", "thresholds": "INFO (bridge) / MEDIUM (leaf)"},
    "D11": {"desc": "Fan-out join risk (row multiplication)", "thresholds": "HIGH with mitigation reduction"},
    "D12": {"desc": "Conformed dimension divergence", "thresholds": "MEDIUM per divergence"},
    "H1": {"desc": "Column name quality (anti-pattern regexes)", "thresholds": "LOW per bad name"},
    "H2": {"desc": "Description quality (too-short, boilerplate)", "thresholds": "LOW per violation"},
    "H3": {"desc": "Unnecessary hidden columns", "thresholds": "MEDIUM per column"},
    "H4": {"desc": "Orphan model with no dependents", "thresholds": "MEDIUM per model"},
    "H5": {"desc": "Orphan sets (zero consumers)", "thresholds": "MEDIUM per set"},
    "H7": {"desc": "Direct table connections (bypasses semantic layer)", "thresholds": "MEDIUM per answer"},
    "H8": {"desc": "Formula promotion candidate", "thresholds": "HIGH if duplicated in 2+ answers"},
    "H9": {"desc": "Redundant answer formulas (duplicating model formula)", "thresholds": "LOW per formula"},
    "H10": {"desc": "Stale / temporary objects (name pattern match)", "thresholds": "LOW (name only), MEDIUM if also orphan"},
    "P1": {"desc": "SQL View used as model source", "thresholds": "MEDIUM per view"},
    "P2": {"desc": "Scalar formula density (run at query time)", "thresholds": "MEDIUM >5, HIGH >10"},
    "P3": {"desc": "Model filters lacking apply_on_tables", "thresholds": "MEDIUM per non-progressive filter"},
    "P4": {"desc": "Apply-all-joins anti-pattern (join_progressive:false)", "thresholds": "HIGH if >5 tables"},
    "P5": {"desc": "No date constraints on fact tables", "thresholds": "MEDIUM per model"},
    "P6": {"desc": "VARCHAR join keys (performance framing of D2)", "thresholds": "HIGH per key"},
    "P7": {"desc": "Join depth exceeding thresholds", "thresholds": "MEDIUM >3, HIGH >5"},
    "P8": {"desc": "Column sprawl (>75 columns)", "thresholds": "MEDIUM per model"},
    "P9": {"desc": "High-cardinality ID column indexed as ATTRIBUTE", "thresholds": "MEDIUM per column"},
    "P11": {"desc": "Excessive indexed columns on Spotter-enabled model", "thresholds": "INFO >30"},
    "P13": {"desc": "High RLS rule count (cost compounds per query)", "thresholds": "MEDIUM >3, HIGH >6"},
    "P14": {"desc": "RLS expression uses functions (prevents index pruning)", "thresholds": "MEDIUM per expression"},
    "P15": {"desc": "VARCHAR RLS column without value_casing", "thresholds": "MEDIUM per column"},
    "P16": {"desc": "Deeply nested if() in formulas", "thresholds": "INFO >3, LOW >5"},
    "P17": {"desc": "Formula cross-reference chain depth", "thresholds": "INFO >2, LOW >3"},
    "P18": {"desc": "COUNT_DISTINCT aggregation (most expensive)", "thresholds": "INFO per column"},
    "S1": {"desc": "PII column detection (heuristic regex)", "thresholds": "MEDIUM per column"},
    "S2": {"desc": "PII indexed without RLS (exposes in autocomplete)", "thresholds": "HIGH per column"},
    "S3": {"desc": "PII without CLS or masking formula", "thresholds": "MEDIUM per column"},
    "S4": {"desc": "RLS bypass + PII columns in model", "thresholds": "HIGH per model"},
    "S5": {"desc": "Credentials in analytics", "thresholds": "CRITICAL per column"},
    "S8": {"desc": "Overly permissive sharing (FULL access to all users)", "thresholds": "MEDIUM per object"},
    "S9": {"desc": "Sharing to external groups", "thresholds": "INFO per object"},
    "S10": {"desc": "RLS bypass enabled (disables row-level security)", "thresholds": "MEDIUM per model"},
}


def build_summary(
    findings: list[Finding],
    checks_run: int,
    models_count: int,
    tables_count: int,
    all_check_ids: list[str] | None = None,
) -> dict:
    by_severity = {s: 0 for s in _SEVERITIES}
    by_angle = {a: 0 for a in _ANGLES}
    for f in findings:
        if f.severity in by_severity:
            by_severity[f.severity] += 1
        if f.angle in by_angle:
            by_angle[f.angle] += 1
    if all_check_ids is not None:
        check_ids = sorted(set(all_check_ids))
    else:
        check_ids = sorted({f.check_id for f in findings})
    return {
        "by_severity": by_severity,
        "by_angle": by_angle,
        "objects_scanned": {"models": models_count, "tables": tables_count},
        "checks_run": checks_run,
        "all_check_ids": check_ids,
    }
