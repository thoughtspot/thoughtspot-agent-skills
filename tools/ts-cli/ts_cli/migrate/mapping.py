from __future__ import annotations

import csv
from pathlib import Path
from typing import List

from ts_cli.migrate.schema import ColumnMappingRow, ModelComparison, GAP_BLOCKER

HEADER = ["model", "tenant_column", "tenant_column_id", "published_column", "status"]


def write_mapping(path: Path, comparisons: List[ModelComparison]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        for comp in comparisons:
            for r in comp.rows:
                writer.writerow([r.model, r.tenant_column, r.tenant_column_id,
                                 r.published_column, r.status])


def read_mapping(path: Path) -> List[ColumnMappingRow]:
    rows: List[ColumnMappingRow] = []
    with open(path, newline="") as f:
        for d in csv.DictReader(f):
            rows.append(ColumnMappingRow(
                model=d["model"],
                tenant_column=d["tenant_column"],
                tenant_column_id=d["tenant_column_id"],
                published_column=(d.get("published_column") or ""),
                status=d["status"],
            ))
    return rows


def validate_mapping(rows: List[ColumnMappingRow]) -> List[str]:
    errors: List[str] = []
    for r in rows:
        if r.status == GAP_BLOCKER and not r.published_column.strip():
            errors.append(
                f"{r.model}.{r.tenant_column}: GAP_BLOCKER column has no published_column mapping"
            )
    return errors
