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


# ---------------------------------------------------------------------------
# Column name → data generator mapping
# ---------------------------------------------------------------------------

_FIRST_NAMES = ["Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace", "Hank",
                "Iris", "Jack", "Karen", "Leo", "Mia", "Noah", "Olivia", "Paul",
                "Quinn", "Rosa", "Sam", "Tina"]
_LAST_NAMES = ["Chen", "Martinez", "Smith", "Johnson", "Williams", "Brown", "Jones",
               "Garcia", "Miller", "Davis", "Rodriguez", "Wilson", "Moore", "Taylor",
               "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin"]
_CITIES = ["Seattle", "Portland", "Denver", "Austin", "Chicago", "Miami", "Boston",
           "Phoenix", "Atlanta", "Detroit", "Dallas", "Orlando", "Memphis", "Reno",
           "Boise", "Tampa", "Tucson", "Omaha", "Fresno", "Mesa"]
_REGIONS = ["West", "East", "North", "South", "Central", "Pacific", "Atlantic",
            "Mountain", "Midwest", "Southeast"]
_STATUSES = ["Active", "Pending", "Closed", "Open", "Cancelled", "Processing",
             "Shipped", "Delivered", "Returned", "On Hold"]


def _pick_generator(col_name: str, col_type: str, rng):
    """Return a generator function for a column based on name and type patterns."""
    lower = col_name.lower()

    if ("id" in lower or "key" in lower) and "INTEGER" in col_type:
        counter = [0]
        def gen_seq():
            counter[0] += 1
            return str(counter[0])
        return gen_seq

    if "email" in lower:
        def gen_email():
            return f"user_{rng.randint(1, 9999)}@example.com"
        return gen_email

    if any(w in lower for w in ("name", "customer")):
        def gen_name():
            return f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
        return gen_name

    if any(w in lower for w in ("date", "_at", "_on")) or "DATE" in col_type:
        def gen_date():
            y = rng.randint(2023, 2025)
            m = rng.randint(1, 12)
            d = rng.randint(1, 28)
            return f"{y}-{m:02d}-{d:02d}"
        return gen_date

    if any(w in lower for w in ("price", "amount", "cost", "sales", "revenue")):
        def gen_money():
            return f"{rng.uniform(1, 10000):.2f}"
        return gen_money

    if any(w in lower for w in ("quantity", "count", "qty")):
        def gen_qty():
            return str(rng.randint(1, 100))
        return gen_qty

    if any(w in lower for w in ("status", "state", "type", "category")):
        def gen_cat():
            return rng.choice(_STATUSES)
        return gen_cat

    if any(w in lower for w in ("city",)):
        def gen_city():
            return rng.choice(_CITIES)
        return gen_city

    if any(w in lower for w in ("region",)):
        def gen_region():
            return rng.choice(_REGIONS)
        return gen_region

    if "phone" in lower:
        def gen_phone():
            return f"555-{rng.randint(0, 9999):04d}"
        return gen_phone

    if any(w in lower for w in ("percent", "ratio", "rate")):
        def gen_pct():
            return f"{rng.uniform(0, 1):.4f}"
        return gen_pct

    if "BOOLEAN" in col_type:
        def gen_bool():
            return rng.choice(["true", "false"])
        return gen_bool
    if "INTEGER" in col_type:
        def gen_int():
            return str(rng.randint(1, 1000))
        return gen_int
    if "FLOAT" in col_type:
        def gen_float():
            return f"{rng.uniform(0, 1000):.2f}"
        return gen_float
    if "TIMESTAMP" in col_type:
        def gen_ts():
            y = rng.randint(2023, 2025)
            m = rng.randint(1, 12)
            d = rng.randint(1, 28)
            h = rng.randint(0, 23)
            mi = rng.randint(0, 59)
            s = rng.randint(0, 59)
            return f"{y}-{m:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"
        return gen_ts

    counter = [0]
    def gen_default():
        counter[0] += 1
        return f"val_{counter[0]:05d}"
    return gen_default


def generate_csv(table_schema: dict, rows: int, output_dir: Path, seed: int = 42) -> Path:
    """Generate a CSV file with synthetic data for one table schema."""
    import random
    rng = random.Random(seed)

    output_dir.mkdir(parents=True, exist_ok=True)
    table_name = table_schema["table_name"]
    columns = table_schema["columns"]
    csv_path = output_dir / f"{table_name}.csv"

    generators = []
    for col in columns:
        col_name = col.get("db_column_name", col.get("name", ""))
        col_type = col.get("inferred_type", col.get("type", "VARCHAR(256)"))
        generators.append(_pick_generator(col_name, col_type, rng))

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv_mod.writer(f)
        header = [col.get("db_column_name", col.get("name")) for col in columns]
        writer.writerow(header)
        for _ in range(rows):
            writer.writerow([gen() for gen in generators])

    return csv_path


def generate_all(source_path: Path, rows: int, output_dir: Path, seed: int = 42) -> list[dict]:
    """Generate CSVs for all tables in a schema/manifest file."""
    schema = infer_schema(source_path)
    results = []
    for tbl in schema["tables"]:
        csv_path = generate_csv(tbl, rows=rows, output_dir=output_dir, seed=seed)
        results.append({
            "table_name": tbl["table_name"],
            "rows": rows,
            "file": str(csv_path),
        })
    return results


@app.command()
def generate(
    source: str = typer.Option(..., "--source", "-s", help="Path to schema JSON or infer output"),
    rows: int = typer.Option(100, "--rows", "-r", help="Number of rows to generate per table"),
    output_dir: str = typer.Option(".", "--output", "-o", help="Directory to write generated CSVs"),
) -> None:
    """Generate synthetic sample data from a schema definition."""
    result = generate_all(Path(source), rows=rows, output_dir=Path(output_dir))
    print(json.dumps(result, indent=2, default=str))
