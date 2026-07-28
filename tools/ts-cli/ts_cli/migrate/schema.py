from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# Column classification (spec: Phase 1 step 4)
MATCHED = "MATCHED"
GAP = "GAP"
GAP_BLOCKER = "GAP_BLOCKER"
BINDING_MISMATCH = "BINDING_MISMATCH"
# The Model carries a cohort column, so it cannot be published at all and no column-level
# mapping can rescue it. Distinct from GAP_BLOCKER, which one mapping decision resolves:
# SET_BLOCKER is a property of the MODEL and is only cleared by retiring or rebuilding the
# Set. Produced by `ts migrate scan-sets` (Phase 0); `apply` refuses it with no override.
SET_BLOCKER = "SET_BLOCKER"

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
