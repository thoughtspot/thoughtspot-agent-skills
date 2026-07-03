"""ts_cli.report.schema — JSON-contract dataclasses.

The CLI emits these as the stable contract (schema_version "1.0").
Consumers MUST check `schema_version` prefix before parsing.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional

SCHEMA_VERSION = "1.0"

RISK_TAGS = ("SAFE", "LOW", "MEDIUM", "HIGH", "STOP")
RECOMMENDATIONS = (
    "SAFE_TO_DROP",
    "REVIEW_RECOMMENDED",
    "PLAN_REQUIRED",
    "PLAN_REQUIRED_WITH_PER_VIZ_DECISIONS",
    "BLOCKED_RESOLVE_RLS_FIRST",
)


@dataclass
class Owner:
    id: str
    display_name: str

    def to_dict(self):
        return asdict(self)


@dataclass
class RiskTag:
    tag: str  # one of RISK_TAGS
    reason: str

    def __post_init__(self):
        if self.tag not in RISK_TAGS:
            raise ValueError(f"Invalid RiskTag.tag {self.tag!r}; must be one of {RISK_TAGS}")

    def to_dict(self):
        return asdict(self)


@dataclass
class SourceDescriptor:
    input: str
    guid: str
    type: str       # LOGICAL_TABLE, LOGICAL_COLUMN, etc.
    name: str
    parent: Optional[dict] = None   # {"guid": ..., "name": ..., "type": ...} when source is a column

    def to_dict(self):
        return asdict(self)


@dataclass
class DependentEntry:
    guid: str
    name: str
    type: str
    subtype: Optional[str]
    via: str         # "v2_dependents" | "tml_probe" | "fetch_permissions"
    hops: int
    owner: Optional[Owner]
    modified_at: Optional[str]
    risk: RiskTag
    # Column name(s) the deep TML probes (RLS/join/alias/AI-surface/alert) actually
    # matched for THIS dependent, populated by classifier.build_matched_columns_map.
    # Fixes the 2026-07 audit finding that ts-dependency-manager's Step 4 scope
    # filter instructed matching on `risk.reason` text, which never names a column
    # (classifier.py's reasons are fixed literals) — callers should filter on this
    # field instead.
    matched_columns: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "guid": self.guid,
            "name": self.name,
            "type": self.type,
            "subtype": self.subtype,
            "via": self.via,
            "hops": self.hops,
            "owner": self.owner.to_dict() if self.owner else None,
            "modified_at": self.modified_at,
            "risk": self.risk.to_dict(),
            "matched_columns": list(self.matched_columns),
        }


@dataclass
class CoverageEntry:
    type: str
    checked: bool
    found: int = 0
    informational: bool = False
    reason: Optional[str] = None     # only set when checked=False

    def to_dict(self):
        d = {"type": self.type, "checked": self.checked, "found": self.found}
        if self.informational:
            d["informational"] = True
        if self.reason is not None:
            d["reason"] = self.reason
        return d


@dataclass
class Classification:
    per_dependent: List[DependentEntry]
    aggregate: RiskTag
    recommendation: str = ""  # one of RECOMMENDATIONS — set by classifier

    def __post_init__(self):
        if self.recommendation and self.recommendation not in RECOMMENDATIONS:
            raise ValueError(f"Invalid recommendation {self.recommendation!r}; must be one of {RECOMMENDATIONS}")

    def to_dict(self):
        return {
            "per_dependent": [d.to_dict() for d in self.per_dependent],
            "aggregate": self.aggregate.to_dict(),
            "recommendation": self.recommendation,
        }


@dataclass
class Report:
    source: SourceDescriptor
    walked_at: str
    profile: str
    dependents: List[DependentEntry]
    coverage: List[CoverageEntry]
    classification: Classification
    warnings: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "source": self.source.to_dict(),
            "walked_at": self.walked_at,
            "profile": self.profile,
            "dependents": [d.to_dict() for d in self.dependents],
            "coverage": [c.to_dict() for c in self.coverage],
            "classification": self.classification.to_dict(),
            "warnings": list(self.warnings),
        }
