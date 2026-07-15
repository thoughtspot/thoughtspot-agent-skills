from __future__ import annotations

from typing import List, Optional, Set

from ts_cli.migrate.schema import (
    ColumnInfo, ColumnMappingRow, ModelComparison,
    MATCHED, GAP, GAP_BLOCKER, BINDING_MISMATCH, READY, NEEDS_MAPPING, NO_TARGET,
)


def classify_columns(
    model_name: str,
    source_cols: List[ColumnInfo],
    target_cols: List[ColumnInfo],
    used_names: Set[str],
) -> List[ColumnMappingRow]:
    target_by_name = {c.name.lower(): c for c in target_cols}
    used_lower = {n.lower() for n in used_names}
    rows: List[ColumnMappingRow] = []
    for c in source_cols:
        t = target_by_name.get(c.name.lower())
        if t is None:
            status = GAP_BLOCKER if c.name.lower() in used_lower else GAP
            published = ""
        elif t.column_id == c.column_id:
            status = MATCHED
            published = t.name
        else:
            status = BINDING_MISMATCH
            published = t.name
        rows.append(ColumnMappingRow(model_name, c.name, c.column_id, published, status))
    return rows


def readiness(rows: List[ColumnMappingRow], target_guid: Optional[str]) -> str:
    if target_guid is None:
        return NO_TARGET
    if any(r.status == GAP_BLOCKER and not r.published_column for r in rows):
        return NEEDS_MAPPING
    return READY


def compare_model(
    model_name: str,
    source_guid: str,
    target_guid: Optional[str],
    source_cols: List[ColumnInfo],
    target_cols: List[ColumnInfo],
    used_names: Set[str],
    dependents: List[dict],
) -> ModelComparison:
    rows = classify_columns(model_name, source_cols, target_cols, used_names)
    return ModelComparison(
        model_name=model_name,
        source_model_guid=source_guid,
        target_model_guid=target_guid,
        rows=rows,
        dependents=list(dependents),
        readiness=readiness(rows, target_guid),
    )
