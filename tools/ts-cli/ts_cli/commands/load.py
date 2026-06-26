"""ts load — source data loading commands for warehouse provisioning."""
from __future__ import annotations

import csv as csv_mod
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Optional

import typer

app = typer.Typer(help="Load source data into a warehouse.")


def sanitise_name(name: str) -> str:
    """Convert a human-readable name to a warehouse-safe identifier.

    Uppercase, spaces/special chars → underscores, collapse runs, strip ends.
    """
    s = name.upper()
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def detect_source(path: Path) -> tuple[str, list[dict]]:
    """Auto-detect source type and return normalised file info list.

    Returns (source_type, file_infos) where source_type is one of:
      csv_dir, tableau_download, manifest, schema_only
    """
    if path.is_dir():
        csv_files = sorted(path.glob("*.csv"))
        if not csv_files:
            raise SystemExit(f"No .csv files found in {path}")
        file_infos = []
        for f in csv_files:
            table_name = sanitise_name(f.stem)
            file_infos.append({"csv_path": f, "table_name": table_name})
        return "csv_dir", file_infos

    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))

        if "data_files" in data:
            file_infos = []
            for df in data["data_files"]:
                if df.get("type") != "csv":
                    continue
                csv_path = Path(df["path"])
                table_name = sanitise_name(csv_path.stem)
                file_infos.append({"csv_path": csv_path, "table_name": table_name})
            if not file_infos:
                raise SystemExit("No CSV data_files found in Tableau download output")
            return "tableau_download", file_infos

        if "tables" in data:
            has_data = any(t.get("data_file") for t in data["tables"])
            if has_data:
                file_infos = []
                for t in data["tables"]:
                    info: dict[str, Any] = {
                        "table_name": t["table_name"],
                        "columns": t.get("columns", []),
                    }
                    if t.get("data_file"):
                        info["csv_path"] = Path(t["data_file"])
                    file_infos.append(info)
                return "manifest", file_infos
            else:
                file_infos = []
                for t in data["tables"]:
                    file_infos.append({
                        "table_name": t["table_name"],
                        "columns": t.get("columns", []),
                    })
                return "schema_only", file_infos

    raise SystemExit(f"Cannot detect source type for {path}. "
                     "Provide a CSV directory, Tableau download JSON, or manifest JSON.")


def _infer_type(values: list[str]) -> str:
    """Infer a Snowflake-compatible type from a list of non-blank string values."""
    if not values:
        return "VARCHAR(256)"

    all_int = True
    all_float = True
    all_bool = True
    all_date = True
    all_timestamp = True
    max_len = 0

    date_re = re.compile(r"\d{4}-\d{2}-\d{2}$")
    ts_re = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?")
    bool_vals = {"true", "false", "0", "1"}

    for v in values:
        stripped = v.strip()
        if len(stripped) > max_len:
            max_len = len(stripped)

        if all_bool and stripped.lower() not in bool_vals:
            all_bool = False

        if all_int:
            try:
                int(stripped)
            except ValueError:
                all_int = False

        if all_float and not all_int:
            try:
                float(stripped)
            except ValueError:
                all_float = False

        if all_date and not date_re.match(stripped):
            all_date = False

        if all_timestamp and not ts_re.match(stripped):
            all_timestamp = False

    if all_bool:
        return "BOOLEAN"
    if all_int:
        return "INTEGER"
    if all_float:
        return "FLOAT"
    if all_date:
        return "DATE"
    if all_timestamp:
        return "TIMESTAMP"

    varchar_len = max(int(math.ceil(max_len * 1.5)), 256)
    return f"VARCHAR({varchar_len})"


def infer_column_types(csv_path: Path, max_rows: int = 1000) -> list[dict]:
    """Infer column types from a CSV file by scanning sample rows.

    Returns a list of dicts with keys: name, db_column_name, inferred_type.
    """
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv_mod.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            raise SystemExit(f"CSV file {csv_path} is empty (no header row)")

        col_values: list[list[str]] = [[] for _ in headers]
        row_count = 0
        for row in reader:
            if row_count >= max_rows:
                break
            for i, val in enumerate(row):
                if i < len(headers) and val.strip():
                    col_values[i].append(val.strip())
            row_count += 1

    columns = []
    for i, header in enumerate(headers):
        col_name = header.strip()
        columns.append({
            "name": col_name,
            "db_column_name": sanitise_name(col_name),
            "inferred_type": _infer_type(col_values[i]),
        })
    return columns


def _count_csv_rows(csv_path: Path) -> int:
    """Count data rows in a CSV (excludes header)."""
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f) - 1


def infer_schema(source_path: Path) -> dict:
    """Top-level inference: detect source, infer types, return full JSON output."""
    source_type, file_infos = detect_source(source_path)

    tables = []
    for info in file_infos:
        if source_type == "schema_only":
            tables.append({
                "table_name": info["table_name"],
                "row_count": 0,
                "columns": info.get("columns", []),
                "has_data": False,
            })
            continue

        if source_type == "manifest" and info.get("columns"):
            csv_path = info.get("csv_path")
            row_count = _count_csv_rows(csv_path) if csv_path else 0
            tables.append({
                "file": csv_path.name if csv_path else None,
                "table_name": info["table_name"],
                "row_count": row_count,
                "columns": info["columns"],
                "has_data": csv_path is not None,
            })
            continue

        csv_path = info["csv_path"]
        columns = infer_column_types(csv_path)
        row_count = _count_csv_rows(csv_path)
        tables.append({
            "file": csv_path.name,
            "table_name": info["table_name"],
            "row_count": row_count,
            "columns": columns,
            "has_data": True,
        })

    return {"source_type": source_type, "tables": tables}


@app.command()
def infer(
    source: str = typer.Option(..., "--source", "-s", help="Path to CSV directory, download JSON, or manifest JSON"),
) -> None:
    """Infer table schemas from source data."""
    result = infer_schema(Path(source))
    print(json.dumps(result, indent=2, default=str))
