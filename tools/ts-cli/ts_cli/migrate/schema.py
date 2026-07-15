from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# Column classification (spec: Phase 1 step 4)
MATCHED = "MATCHED"
GAP = "GAP"
GAP_BLOCKER = "GAP_BLOCKER"
BINDING_MISMATCH = "BINDING_MISMATCH"

# Model readiness verdict
READY = "READY"
NEEDS_MAPPING = "NEEDS_MAPPING"
NO_TARGET = "NO_TARGET"


@dataclass
class ColumnInfo:
    """A Model/Table column. Identity is `column_id` (physical binding); `name` is the display alias."""
    name: str
    column_id: str
    column_type: str = ""


@dataclass
class ColumnMappingRow:
    model: str
    tenant_column: str
    tenant_column_id: str
    published_column: str  # "" when a gap still needs a user-supplied mapping
    status: str


@dataclass
class ModelComparison:
    model_name: str
    source_model_guid: str
    target_model_guid: Optional[str]
    rows: List[ColumnMappingRow]
    dependents: List[dict] = field(default_factory=list)
    readiness: str = NEEDS_MAPPING
