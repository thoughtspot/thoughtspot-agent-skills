# ts-load-source-data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `ts load` CLI commands (infer, generate, snowflake) and a `ts-load-source-data` SKILL.md that loads CSV data into Snowflake using existing Snowflake profiles.

**Architecture:** Three CLI subcommands under `ts load` in a new `commands/load.py` module — `infer` (schema inference), `generate` (synthetic data), `snowflake` (warehouse loading via PUT/COPY INTO or `snow` CLI). A SKILL.md wraps these with interactive guidance. Auth reuses `~/.claude/snowflake-profiles.json` managed by `/ts-profile-snowflake`.

**Tech Stack:** Python 3.9+, typer, csv stdlib, json stdlib. `snowflake-connector-python` imported at runtime only when `method:python` is used (not a ts-cli dependency). `snow` CLI for `method:cli` profiles.

## Global Constraints

- `snowflake-connector-python` is NOT added to `pyproject.toml` dependencies — it is imported at runtime inside a try/except with a clear error message when missing
- Snowflake profiles are read from `~/.claude/snowflake-profiles.json` — the exact format managed by `/ts-profile-snowflake` (both list `[{...}]` and wrapped `{"profiles": [...]}` formats)
- All structured data output goes to stdout as JSON; all diagnostics/progress to stderr
- No credentials are ever printed, logged, or written to files — presence-check only
- `db_column_name` derivation: uppercase, spaces → underscores, strip non-alphanumeric (except underscores), collapse runs of underscores
- Table names derived from CSV filenames: strip `.csv` extension, apply same rules as `db_column_name`
- Version bump: both `ts_cli/__init__.py` and `pyproject.toml` — determine current version at implementation time and bump MINOR
- All new files use `from __future__ import annotations` as the first import
- Tests must not require a live Snowflake connection — test pure functions in isolation, mock subprocess/connector calls
- The `ts load` command group is registered in `cli.py` alongside existing groups

---

### Task 1: Source detection, name sanitisation, and schema inference (`_infer`)

**Files:**
- Create: `tools/ts-cli/ts_cli/commands/load.py`
- Modify: `tools/ts-cli/ts_cli/cli.py:6-24`
- Create: `tools/ts-cli/tests/test_load.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `detect_source(path: Path) -> tuple[str, list[dict]]` — returns `(source_type, file_infos)` where `source_type` is one of `"csv_dir"`, `"tableau_download"`, `"manifest"`, `"schema_only"` and `file_infos` is a list of `{"csv_path": Path, "table_name": str}` dicts (or `{"table_name": str, "columns": list}` for schema_only)
  - `sanitise_name(name: str) -> str` — returns uppercase, underscore-separated, alphanumeric-only name
  - `infer_column_types(csv_path: Path, max_rows: int = 1000) -> list[dict]` — returns `[{"name": str, "db_column_name": str, "inferred_type": str}]`
  - `infer_schema(source_path: Path) -> dict` — top-level function returning the full infer output JSON shape
  - Typer command `infer` registered under the `load` command group

- [ ] **Step 1: Write the failing tests**

Create `tools/ts-cli/tests/test_load.py`:

```python
"""Unit tests for ts load commands — source detection, name sanitisation, schema inference."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest


class TestSanitiseName:
    @pytest.mark.parametrize("raw,expected", [
        ("Row ID", "ROW_ID"),
        ("Order Date", "ORDER_DATE"),
        ("Customer Name", "CUSTOMER_NAME"),
        ("  spaces  ", "SPACES"),
        ("col--with---dashes", "COL_WITH_DASHES"),
        ("already_UPPER", "ALREADY_UPPER"),
        ("special!@#chars$%", "SPECIAL_CHARS"),
        ("123numeric_start", "123NUMERIC_START"),
    ])
    def test_sanitise(self, raw, expected):
        from ts_cli.commands.load import sanitise_name
        assert sanitise_name(raw) == expected


class TestDetectSource:
    def test_csv_directory(self, tmp_path):
        (tmp_path / "sales.csv").write_text("a,b\n1,2\n")
        (tmp_path / "orders.csv").write_text("x,y\n3,4\n")
        from ts_cli.commands.load import detect_source
        source_type, file_infos = detect_source(tmp_path)
        assert source_type == "csv_dir"
        assert len(file_infos) == 2
        names = {f["table_name"] for f in file_infos}
        assert names == {"SALES", "ORDERS"}

    def test_tableau_download_json(self, tmp_path):
        download_output = {
            "tdsx_path": "/tmp/test.tdsx",
            "extracted_dir": str(tmp_path),
            "files": ["Data/sales.csv"],
            "data_files": [
                {"name": "Data/sales.csv", "path": str(tmp_path / "Data" / "sales.csv"),
                 "type": "csv", "validation": {"total_lines": 3, "header_columns": 2, "corrupt_lines": []}}
            ],
        }
        json_path = tmp_path / "download.json"
        json_path.write_text(json.dumps(download_output))
        (tmp_path / "Data").mkdir()
        (tmp_path / "Data" / "sales.csv").write_text("a,b\n1,2\n3,4\n")

        from ts_cli.commands.load import detect_source
        source_type, file_infos = detect_source(json_path)
        assert source_type == "tableau_download"
        assert len(file_infos) == 1
        assert file_infos[0]["table_name"] == "SALES"

    def test_manifest_with_data(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("x,y\n1,2\n")
        manifest = {
            "source": "manual",
            "tables": [{"table_name": "MY_TABLE", "data_file": str(csv_file),
                         "columns": [{"name": "x", "db_column_name": "X", "type": "INTEGER"}]}],
        }
        json_path = tmp_path / "manifest.json"
        json_path.write_text(json.dumps(manifest))
        from ts_cli.commands.load import detect_source
        source_type, file_infos = detect_source(json_path)
        assert source_type == "manifest"

    def test_schema_only_manifest(self, tmp_path):
        manifest = {
            "source": "manual",
            "tables": [{"table_name": "MY_TABLE",
                         "columns": [{"name": "x", "db_column_name": "X", "type": "INTEGER"}]}],
        }
        json_path = tmp_path / "schema.json"
        json_path.write_text(json.dumps(manifest))
        from ts_cli.commands.load import detect_source
        source_type, _ = detect_source(json_path)
        assert source_type == "schema_only"


class TestInferColumnTypes:
    def test_integer_column(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("id\n1\n2\n3\n42\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "INTEGER"
        assert cols[0]["db_column_name"] == "ID"

    def test_float_column(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("price\n1.5\n2.99\n3.0\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "FLOAT"

    def test_date_column(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("order_date\n2024-01-15\n2024-02-20\n2024-03-10\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "DATE"

    def test_timestamp_column(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("created_at\n2024-01-15 09:30:00\n2024-02-20 14:00:00\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "TIMESTAMP"

    def test_boolean_column(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("active\ntrue\nfalse\ntrue\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "BOOLEAN"

    def test_varchar_column_with_length(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("name\nAlice\nBob\nCharlie Brown The Third\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"].startswith("VARCHAR")
        length = int(cols[0]["inferred_type"].replace("VARCHAR(", "").replace(")", ""))
        assert length >= 256

    def test_blank_column_defaults_varchar(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("empty\n\n\n\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "VARCHAR(256)"

    def test_mixed_int_and_blank(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("qty\n5\n\n10\n\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "INTEGER"

    def test_multiple_columns(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("id,name,price,active\n1,Alice,9.99,true\n2,Bob,19.50,false\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        types = {c["db_column_name"]: c["inferred_type"] for c in cols}
        assert types["ID"] == "INTEGER"
        assert types["PRICE"] == "FLOAT"
        assert types["ACTIVE"] == "BOOLEAN"
        assert types["NAME"].startswith("VARCHAR")


class TestInferSchema:
    def test_csv_dir_full_output(self, tmp_path):
        (tmp_path / "sales.csv").write_text("id,amount\n1,9.99\n2,19.50\n")
        from ts_cli.commands.load import infer_schema
        result = infer_schema(tmp_path)
        assert result["source_type"] == "csv_dir"
        assert len(result["tables"]) == 1
        tbl = result["tables"][0]
        assert tbl["table_name"] == "SALES"
        assert tbl["row_count"] == 2
        assert len(tbl["columns"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python -m pytest tools/ts-cli/tests/test_load.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ts_cli.commands.load'`

- [ ] **Step 3: Write the implementation**

Create `tools/ts-cli/ts_cli/commands/load.py`:

```python
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
```

- [ ] **Step 4: Register the load command group in cli.py**

Modify `tools/ts-cli/ts_cli/cli.py`. Add to the import line (line 6):

```python
from ts_cli.commands import auth, connections, load, metadata, orgs, profiles, spotql, tables, tableau, tml, users, variables
```

Add after line 24 (the `tableau` registration):

```python
app.add_typer(load.app, name="load")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python -m pytest tools/ts-cli/tests/test_load.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add tools/ts-cli/ts_cli/commands/load.py tools/ts-cli/tests/test_load.py tools/ts-cli/ts_cli/cli.py
git commit -m "feat(ts-cli): add ts load infer command — source detection and schema inference"
```

---

### Task 2: Synthetic data generation (`generate`)

**Files:**
- Modify: `tools/ts-cli/ts_cli/commands/load.py`
- Modify: `tools/ts-cli/tests/test_load.py`

**Interfaces:**
- Consumes: `infer_schema(path)` from Task 1, `sanitise_name(name)` from Task 1
- Produces:
  - `generate_csv(table_schema: dict, rows: int, output_dir: Path, seed: int = 42) -> Path` — writes a CSV file, returns the path
  - `generate_all(source_path: Path, rows: int, output_dir: Path, seed: int = 42) -> list[dict]` — generates CSVs for all tables in the schema, returns summary list
  - Typer command `generate` under the `load` command group

- [ ] **Step 1: Write the failing tests**

Append to `tools/ts-cli/tests/test_load.py`:

```python
class TestGenerateCsv:
    def _make_schema(self, columns):
        return {"table_name": "TEST_TABLE", "columns": columns, "row_count": 0, "has_data": False}

    def test_integer_id_column(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([{"name": "id", "db_column_name": "ID", "inferred_type": "INTEGER"}])
        path = generate_csv(schema, rows=5, output_dir=tmp_path)
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert lines[0] == "ID"
        assert len(lines) == 6
        assert lines[1] == "1"
        assert lines[5] == "5"

    def test_varchar_name_column(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "customer_name", "db_column_name": "CUSTOMER_NAME", "inferred_type": "VARCHAR(256)"},
        ])
        path = generate_csv(schema, rows=3, output_dir=tmp_path)
        lines = path.read_text().strip().split("\n")
        assert lines[0] == "CUSTOMER_NAME"
        assert len(lines) == 4
        for line in lines[1:]:
            assert len(line) > 0

    def test_date_column(self, tmp_path):
        import re
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "order_date", "db_column_name": "ORDER_DATE", "inferred_type": "DATE"},
        ])
        path = generate_csv(schema, rows=3, output_dir=tmp_path)
        lines = path.read_text().strip().split("\n")
        for line in lines[1:]:
            assert re.match(r"\d{4}-\d{2}-\d{2}", line)

    def test_float_price_column(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "price", "db_column_name": "PRICE", "inferred_type": "FLOAT"},
        ])
        path = generate_csv(schema, rows=3, output_dir=tmp_path)
        lines = path.read_text().strip().split("\n")
        for line in lines[1:]:
            val = float(line)
            assert 1.0 <= val <= 10000.0

    def test_boolean_column(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "active", "db_column_name": "ACTIVE", "inferred_type": "BOOLEAN"},
        ])
        path = generate_csv(schema, rows=10, output_dir=tmp_path)
        lines = path.read_text().strip().split("\n")
        for line in lines[1:]:
            assert line in ("true", "false")

    def test_multiple_columns(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "id", "db_column_name": "ID", "inferred_type": "INTEGER"},
            {"name": "email", "db_column_name": "EMAIL", "inferred_type": "VARCHAR(256)"},
            {"name": "sales", "db_column_name": "SALES", "inferred_type": "FLOAT"},
        ])
        path = generate_csv(schema, rows=5, output_dir=tmp_path)
        lines = path.read_text().strip().split("\n")
        assert lines[0] == "ID,EMAIL,SALES"
        assert len(lines) == 6

    def test_deterministic_with_seed(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "price", "db_column_name": "PRICE", "inferred_type": "FLOAT"},
        ])
        path1 = generate_csv(schema, rows=5, output_dir=tmp_path / "a", seed=42)
        path2 = generate_csv(schema, rows=5, output_dir=tmp_path / "b", seed=42)
        assert path1.read_text() == path2.read_text()


class TestGenerateAll:
    def test_generates_from_schema_file(self, tmp_path):
        schema = {
            "source": "manual",
            "tables": [
                {"table_name": "ORDERS", "columns": [
                    {"name": "id", "db_column_name": "ID", "inferred_type": "INTEGER"},
                    {"name": "amount", "db_column_name": "AMOUNT", "inferred_type": "FLOAT"},
                ]},
            ],
        }
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(json.dumps(schema))
        output_dir = tmp_path / "output"

        from ts_cli.commands.load import generate_all
        result = generate_all(schema_path, rows=10, output_dir=output_dir)
        assert len(result) == 1
        assert result[0]["table_name"] == "ORDERS"
        assert result[0]["rows"] == 10
        assert (output_dir / "ORDERS.csv").exists()
```

- [ ] **Step 2: Run tests to verify the new tests fail**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python -m pytest tools/ts-cli/tests/test_load.py::TestGenerateCsv -v`
Expected: FAIL — `ImportError: cannot import name 'generate_csv'`

- [ ] **Step 3: Write the implementation**

Add to `tools/ts-cli/ts_cli/commands/load.py`, after the `infer` command:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python -m pytest tools/ts-cli/tests/test_load.py -v`
Expected: All tests PASS (Task 1 tests + Task 2 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/commands/load.py tools/ts-cli/tests/test_load.py
git commit -m "feat(ts-cli): add ts load generate command — synthetic data from schema"
```

---

### Task 3: Snowflake loading (`snowflake`)

**Files:**
- Modify: `tools/ts-cli/ts_cli/commands/load.py`
- Modify: `tools/ts-cli/tests/test_load.py`

**Interfaces:**
- Consumes: `infer_schema(path)` from Task 1, `generate_csv(schema, rows, dir)` from Task 2, `sanitise_name(name)` from Task 1, `detect_source(path)` from Task 1
- Produces:
  - `load_snowflake_profile(profile_name: str) -> dict` — reads `~/.claude/snowflake-profiles.json`, returns matching profile dict
  - `_build_create_table_sql(table_name: str, columns: list[dict], database: str, schema: str) -> str` — returns CREATE TABLE DDL
  - `_load_via_python(profile: dict, tables: list[dict], database: str, schema: str, warehouse: str, role: str, if_exists: str, csv_dir: Path) -> list[dict]` — loads via snowflake.connector
  - `_load_via_cli(profile: dict, tables: list[dict], database: str, schema: str, warehouse: str, role: str, if_exists: str, csv_dir: Path) -> list[dict]` — loads via snow CLI
  - Typer command `snowflake` under the `load` command group

- [ ] **Step 1: Write the failing tests**

Append to `tools/ts-cli/tests/test_load.py`:

```python
from unittest.mock import MagicMock, patch, call


class TestLoadSnowflakeProfile:
    def test_load_list_format(self, tmp_path):
        profiles_file = tmp_path / "snowflake-profiles.json"
        profiles_file.write_text(json.dumps([
            {"name": "Production", "method": "cli", "cli_connection": "prod",
             "default_warehouse": "WH", "default_role": "ROLE"},
        ]))
        from ts_cli.commands.load import load_snowflake_profile
        with patch("ts_cli.commands.load.SF_PROFILES_PATH", profiles_file):
            p = load_snowflake_profile("Production")
        assert p["cli_connection"] == "prod"

    def test_load_wrapped_format(self, tmp_path):
        profiles_file = tmp_path / "snowflake-profiles.json"
        profiles_file.write_text(json.dumps({"profiles": [
            {"name": "Dev", "method": "python", "account": "acct",
             "username": "user", "auth": "key_pair",
             "default_warehouse": "WH", "default_role": "ROLE"},
        ]}))
        from ts_cli.commands.load import load_snowflake_profile
        with patch("ts_cli.commands.load.SF_PROFILES_PATH", profiles_file):
            p = load_snowflake_profile("Dev")
        assert p["method"] == "python"

    def test_profile_not_found_exits(self, tmp_path):
        profiles_file = tmp_path / "snowflake-profiles.json"
        profiles_file.write_text(json.dumps([{"name": "Other"}]))
        from ts_cli.commands.load import load_snowflake_profile
        with patch("ts_cli.commands.load.SF_PROFILES_PATH", profiles_file):
            with pytest.raises(SystemExit):
                load_snowflake_profile("Missing")

    def test_no_file_exits(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        from ts_cli.commands.load import load_snowflake_profile
        with patch("ts_cli.commands.load.SF_PROFILES_PATH", missing):
            with pytest.raises(SystemExit):
                load_snowflake_profile("Any")


class TestBuildCreateTableSql:
    def test_basic_ddl(self):
        from ts_cli.commands.load import _build_create_table_sql
        columns = [
            {"db_column_name": "ID", "inferred_type": "INTEGER"},
            {"db_column_name": "NAME", "inferred_type": "VARCHAR(256)"},
            {"db_column_name": "PRICE", "inferred_type": "FLOAT"},
        ]
        sql = _build_create_table_sql("MY_TABLE", columns, "DB", "SCH")
        assert "CREATE TABLE DB.SCH.MY_TABLE" in sql
        assert "ID INTEGER" in sql
        assert "NAME VARCHAR(256)" in sql
        assert "PRICE FLOAT" in sql

    def test_uses_type_field_when_present(self):
        from ts_cli.commands.load import _build_create_table_sql
        columns = [{"db_column_name": "X", "type": "DATE"}]
        sql = _build_create_table_sql("T", columns, "DB", "SCH")
        assert "X DATE" in sql


class TestLoadViaCli:
    def test_builds_correct_commands(self, tmp_path):
        csv_file = tmp_path / "SALES.csv"
        csv_file.write_text("ID,AMOUNT\n1,9.99\n")
        tables = [{
            "table_name": "SALES",
            "columns": [
                {"db_column_name": "ID", "inferred_type": "INTEGER"},
                {"db_column_name": "AMOUNT", "inferred_type": "FLOAT"},
            ],
            "has_data": True,
            "file": "SALES.csv",
        }]
        profile = {"method": "cli", "cli_connection": "myconn",
                    "default_warehouse": "WH", "default_role": "ROLE"}

        from ts_cli.commands.load import _load_via_cli

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("ts_cli.commands.load.subprocess.run", return_value=mock_result) as mock_run:
            results = _load_via_cli(profile, tables, "DB", "SCH", "WH", "ROLE",
                                     "error", tmp_path)

        assert len(results) == 1
        assert results[0]["status"] == "created"
        calls_made = [str(c) for c in mock_run.call_args_list]
        assert any("CREATE DATABASE" in c for c in calls_made)
        assert any("CREATE SCHEMA" in c for c in calls_made)
        assert any("CREATE TABLE" in c for c in calls_made)
        assert any("COPY INTO" in c for c in calls_made)


class TestLoadViaPython:
    def test_builds_correct_queries(self, tmp_path):
        csv_file = tmp_path / "ORDERS.csv"
        csv_file.write_text("ID,TOTAL\n1,50.00\n")
        tables = [{
            "table_name": "ORDERS",
            "columns": [
                {"db_column_name": "ID", "inferred_type": "INTEGER"},
                {"db_column_name": "TOTAL", "inferred_type": "FLOAT"},
            ],
            "has_data": True,
            "file": "ORDERS.csv",
        }]
        profile = {"method": "python", "account": "acct", "username": "user",
                    "auth": "key_pair", "private_key_path": "~/.ssh/key.p8",
                    "default_warehouse": "WH", "default_role": "ROLE"}

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (2,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        from ts_cli.commands.load import _load_via_python

        with patch("ts_cli.commands.load._connect_python", return_value=mock_conn):
            results = _load_via_python(profile, tables, "DB", "SCH", "WH", "ROLE",
                                        "error", tmp_path)

        assert len(results) == 1
        assert results[0]["status"] == "created"
        executed = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("CREATE DATABASE" in q for q in executed)
        assert any("CREATE TABLE" in q for q in executed)
        assert any("PUT" in q for q in executed)
        assert any("COPY INTO" in q for q in executed)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python -m pytest tools/ts-cli/tests/test_load.py::TestLoadSnowflakeProfile -v`
Expected: FAIL — `ImportError: cannot import name 'load_snowflake_profile'`

- [ ] **Step 3: Write the implementation**

Add to `tools/ts-cli/ts_cli/commands/load.py`, after the `generate` command. Add `import subprocess` to the imports at the top of the file.

```python
import subprocess

# ---------------------------------------------------------------------------
# Snowflake profile loading
# ---------------------------------------------------------------------------

SF_PROFILES_PATH = Path.home() / ".claude" / "snowflake-profiles.json"


def load_snowflake_profile(profile_name: str) -> dict:
    """Load a Snowflake profile from ~/.claude/snowflake-profiles.json."""
    if not SF_PROFILES_PATH.exists():
        raise SystemExit(
            f"No Snowflake profiles found at {SF_PROFILES_PATH}.\n"
            "Run /ts-profile-snowflake to create one."
        )
    raw = json.loads(SF_PROFILES_PATH.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "profiles" in raw:
        profiles = raw["profiles"]
    elif isinstance(raw, list):
        profiles = raw
    else:
        raise SystemExit(f"Unexpected format in {SF_PROFILES_PATH}")

    for p in profiles:
        if p.get("name") == profile_name:
            return p

    available = [p.get("name") for p in profiles]
    raise SystemExit(
        f"Profile '{profile_name}' not found. Available: {', '.join(str(n) for n in available)}"
    )


def _build_create_table_sql(table_name: str, columns: list[dict],
                             database: str, schema: str) -> str:
    """Build a CREATE TABLE DDL statement."""
    col_defs = []
    for col in columns:
        db_name = col.get("db_column_name", col.get("name", "UNKNOWN"))
        col_type = col.get("inferred_type", col.get("type", "VARCHAR(256)"))
        col_defs.append(f"  {db_name} {col_type}")
    cols_sql = ",\n".join(col_defs)
    return f"CREATE TABLE {database}.{schema}.{table_name} (\n{cols_sql}\n)"


# ---------------------------------------------------------------------------
# Snowflake loading: method:cli
# ---------------------------------------------------------------------------

def _run_snow_sql(connection: str, query: str) -> None:
    """Execute a SQL statement via the snow CLI."""
    result = subprocess.run(
        ["snow", "sql", "-c", connection, "-q", query],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        typer.echo(f"snow sql failed: {result.stderr.strip()}", err=True)
        raise SystemExit(1)


def _load_via_cli(profile: dict, tables: list[dict], database: str,
                   schema: str, warehouse: str, role: str,
                   if_exists: str, csv_dir: Path) -> list[dict]:
    """Load CSV data into Snowflake via the snow CLI."""
    conn = profile["cli_connection"]

    _run_snow_sql(conn, f"CREATE DATABASE IF NOT EXISTS {database}")
    _run_snow_sql(conn, f"CREATE SCHEMA IF NOT EXISTS {database}.{schema}")
    _run_snow_sql(conn, f"USE WAREHOUSE {warehouse}")

    results = []
    for tbl in tables:
        table_name = tbl["table_name"]
        fqn = f"{database}.{schema}.{table_name}"

        check = subprocess.run(
            ["snow", "sql", "-c", conn, "-q",
             f"SELECT COUNT(*) FROM information_schema.tables WHERE table_catalog='{database}' AND table_schema='{schema}' AND table_name='{table_name}'"],
            capture_output=True, text=True,
        )
        table_exists = "1" in check.stdout if check.returncode == 0 else False

        if table_exists:
            if if_exists == "error":
                raise SystemExit(f"Table {fqn} already exists. Use --if-exists skip|replace.")
            if if_exists == "skip":
                typer.echo(f"  Skipping {fqn} (already exists)", err=True)
                results.append({"table_name": table_name, "status": "skipped",
                                "rows_loaded": 0, "columns": len(tbl["columns"]),
                                "source_file": tbl.get("file", "")})
                continue
            if if_exists == "replace":
                _run_snow_sql(conn, f"DROP TABLE IF EXISTS {fqn}")

        ddl = _build_create_table_sql(table_name, tbl["columns"], database, schema)
        _run_snow_sql(conn, ddl)

        csv_path = csv_dir / tbl.get("file", f"{table_name}.csv")
        if csv_path.exists():
            stage_name = f"@{database}.{schema}.%{table_name}"
            subprocess.run(
                ["snow", "stage", "copy", str(csv_path), stage_name, "-c", conn],
                capture_output=True, text=True, check=True,
            )
            copy_sql = (
                f"COPY INTO {fqn} FROM {stage_name} "
                f"FILE_FORMAT=(TYPE=CSV FIELD_OPTIONALLY_ENCLOSED_BY='\"' SKIP_HEADER=1)"
            )
            _run_snow_sql(conn, copy_sql)
            _run_snow_sql(conn, f"REMOVE {stage_name}")

        row_result = subprocess.run(
            ["snow", "sql", "-c", conn, "-q", f"SELECT COUNT(*) FROM {fqn}"],
            capture_output=True, text=True,
        )
        rows_loaded = 0
        if row_result.returncode == 0:
            import re as re_mod
            match = re_mod.search(r"(\d+)", row_result.stdout)
            if match:
                rows_loaded = int(match.group(1))

        results.append({"table_name": table_name, "status": "created",
                        "rows_loaded": rows_loaded, "columns": len(tbl["columns"]),
                        "source_file": tbl.get("file", "")})

    return results


# ---------------------------------------------------------------------------
# Snowflake loading: method:python
# ---------------------------------------------------------------------------

def _connect_python(profile: dict, warehouse: str, role: str):
    """Connect to Snowflake via snowflake.connector using profile credentials."""
    try:
        import snowflake.connector
    except ImportError:
        raise SystemExit(
            "snowflake-connector-python is required for method:python profiles.\n"
            "Install it: pip install snowflake-connector-python"
        )

    account = profile["account"]
    username = profile["username"]
    auth = profile.get("auth", "password")

    if auth == "key_pair":
        import os
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend
        key_path = os.path.expanduser(profile.get("private_key_path", "~/.ssh/snowflake_key.p8"))
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())
        private_key_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return snowflake.connector.connect(
            account=account, user=username, private_key=private_key_bytes,
            warehouse=warehouse, role=role,
        )
    else:
        import os
        password_env = profile.get("password_env", "")
        password = os.environ.get(password_env, "")
        if not password:
            raise SystemExit(f"Password env var {password_env} is empty. Source your shell profile first.")
        return snowflake.connector.connect(
            account=account, user=username, password=password,
            warehouse=warehouse, role=role,
        )


def _load_via_python(profile: dict, tables: list[dict], database: str,
                      schema: str, warehouse: str, role: str,
                      if_exists: str, csv_dir: Path) -> list[dict]:
    """Load CSV data into Snowflake via snowflake.connector."""
    conn = _connect_python(profile, warehouse, role)
    cur = conn.cursor()

    try:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {database}.{schema}")
        cur.execute(f"USE DATABASE {database}")
        cur.execute(f"USE SCHEMA {schema}")

        results = []
        for tbl in tables:
            table_name = tbl["table_name"]
            fqn = f"{database}.{schema}.{table_name}"

            cur.execute(
                f"SELECT COUNT(*) FROM information_schema.tables "
                f"WHERE table_catalog='{database}' AND table_schema='{schema}' "
                f"AND table_name='{table_name}'"
            )
            table_exists = cur.fetchone()[0] > 0

            if table_exists:
                if if_exists == "error":
                    raise SystemExit(f"Table {fqn} already exists. Use --if-exists skip|replace.")
                if if_exists == "skip":
                    typer.echo(f"  Skipping {fqn} (already exists)", err=True)
                    results.append({"table_name": table_name, "status": "skipped",
                                    "rows_loaded": 0, "columns": len(tbl["columns"]),
                                    "source_file": tbl.get("file", "")})
                    continue
                if if_exists == "replace":
                    cur.execute(f"DROP TABLE IF EXISTS {fqn}")

            ddl = _build_create_table_sql(table_name, tbl["columns"], database, schema)
            cur.execute(ddl)

            csv_path = csv_dir / tbl.get("file", f"{table_name}.csv")
            if csv_path.exists():
                cur.execute(f"PUT file://{csv_path} @%{table_name}")
                cur.execute(
                    f"COPY INTO {table_name} FROM @%{table_name} "
                    f"FILE_FORMAT=(TYPE=CSV FIELD_OPTIONALLY_ENCLOSED_BY='\"' SKIP_HEADER=1)"
                )
                cur.execute(f"REMOVE @%{table_name}")

            cur.execute(f"SELECT COUNT(*) FROM {fqn}")
            rows_loaded = cur.fetchone()[0]

            results.append({"table_name": table_name, "status": "created",
                            "rows_loaded": rows_loaded, "columns": len(tbl["columns"]),
                            "source_file": tbl.get("file", "")})

        return results
    finally:
        cur.close()
        conn.close()


@app.command()
def snowflake(
    source: str = typer.Option(..., "--source", "-s", help="Path to CSV directory, download JSON, or manifest JSON"),
    profile: str = typer.Option(..., "--profile", "-p", help="Snowflake profile name from ~/.claude/snowflake-profiles.json"),
    database: str = typer.Option(..., "--database", "-d", help="Target Snowflake database"),
    schema: str = typer.Option(..., "--schema", help="Target Snowflake schema"),
    if_exists: str = typer.Option("error", "--if-exists", help="Action when table exists: error|skip|replace"),
    warehouse: Optional[str] = typer.Option(None, "--warehouse", "-w", help="Warehouse (default: from profile)"),
    role: Optional[str] = typer.Option(None, "--role", "-r", help="Role (default: from profile)"),
    generate_sample: bool = typer.Option(False, "--generate-sample", help="Generate synthetic data for schema-only sources"),
    rows: int = typer.Option(100, "--rows", help="Rows to generate (with --generate-sample)"),
) -> None:
    """Load CSV data into Snowflake tables."""
    if if_exists not in ("error", "skip", "replace"):
        raise SystemExit("--if-exists must be one of: error, skip, replace")

    sf_profile = load_snowflake_profile(profile)
    wh = warehouse or sf_profile.get("default_warehouse", "")
    rl = role or sf_profile.get("default_role", "")

    if not wh:
        raise SystemExit("No warehouse specified. Use --warehouse or set default_warehouse in profile.")

    source_path = Path(source)
    inferred = infer_schema(source_path)

    csv_dir = source_path if source_path.is_dir() else source_path.parent

    if inferred["source_type"] == "schema_only":
        if not generate_sample:
            raise SystemExit(
                "Source is schema-only (no data files). "
                "Use --generate-sample to generate synthetic data, or provide CSVs."
            )
        import tempfile
        gen_dir = Path(tempfile.mkdtemp(prefix="ts_load_gen_"))
        for tbl in inferred["tables"]:
            generate_csv(tbl, rows=rows, output_dir=gen_dir)
        csv_dir = gen_dir
        for tbl in inferred["tables"]:
            tbl["file"] = f"{tbl['table_name']}.csv"
            tbl["has_data"] = True

    method = sf_profile.get("method", "python")
    if method == "cli":
        table_results = _load_via_cli(sf_profile, inferred["tables"], database,
                                       schema, wh, rl, if_exists, csv_dir)
    else:
        table_results = _load_via_python(sf_profile, inferred["tables"], database,
                                          schema, wh, rl, if_exists, csv_dir)

    output = {
        "database": database,
        "schema": schema,
        "profile": profile,
        "tables": table_results,
    }
    print(json.dumps(output, indent=2))
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python -m pytest tools/ts-cli/tests/test_load.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run the full ts-cli test suite for regressions**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python -m pytest tools/ts-cli/tests/ -v`
Expected: All existing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add tools/ts-cli/ts_cli/commands/load.py tools/ts-cli/tests/test_load.py
git commit -m "feat(ts-cli): add ts load snowflake command — warehouse loading via profile"
```

---

### Task 4: ts-cli version bump, README, and CHANGELOG

**Files:**
- Modify: `tools/ts-cli/ts_cli/__init__.py:1`
- Modify: `tools/ts-cli/pyproject.toml:7`
- Modify: `tools/ts-cli/CLAUDE.md`
- Modify: `tools/ts-cli/README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: completed CLI commands from Tasks 1–3
- Produces: updated version, documented commands in README

- [ ] **Step 1: Bump version in both files**

Read the current version from `tools/ts-cli/ts_cli/__init__.py` (currently `0.14.0`). Bump MINOR → `0.15.0`.

Edit `tools/ts-cli/ts_cli/__init__.py`:
```python
__version__ = "0.15.0"
```

Edit `tools/ts-cli/pyproject.toml` line 7:
```
version = "0.15.0"
```

Edit `tools/ts-cli/CLAUDE.md`, update the version reference line:
```
Current version: **0.15.0**. Run `python tools/validate/check_version_sync.py` to verify.
```

- [ ] **Step 2: Add ts load commands to README.md**

Read `tools/ts-cli/README.md` and find the command documentation section. Add after the last command group (likely `ts tableau`):

```markdown
## `ts load` — Source data loading

### `ts load infer`

Infer table schemas from source data (CSV directory, Tableau download JSON, or manifest).

```
ts load infer --source <path>
```

**Options:**

| Flag | Description |
|---|---|
| `--source`, `-s` | Path to CSV directory, Tableau download JSON, or manifest JSON (required) |

**Output:** JSON with `source_type` and `tables[]` array containing `table_name`, `row_count`, and `columns[]` with `name`, `db_column_name`, `inferred_type`.

### `ts load generate`

Generate synthetic sample data from a schema definition.

```
ts load generate --source schema.json --rows 500 --output ./generated/
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--source`, `-s` | — | Path to schema JSON or `ts load infer` output (required) |
| `--rows`, `-r` | `100` | Number of rows per table |
| `--output`, `-o` | `.` | Directory to write generated CSV files |

**Output:** JSON array of `{table_name, rows, file}` per generated table.

### `ts load snowflake`

Load CSV data into Snowflake tables. Auth via Snowflake profile (`~/.claude/snowflake-profiles.json`).

```
ts load snowflake --source ./csvs/ --profile Production \
    --database AGENT_SKILLS --schema SALES
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--source`, `-s` | — | Path to CSV directory, download JSON, or manifest (required) |
| `--profile`, `-p` | — | Snowflake profile name (required) |
| `--database`, `-d` | — | Target database (required) |
| `--schema` | — | Target schema (required) |
| `--if-exists` | `error` | Action when table exists: `error`, `skip`, `replace` |
| `--warehouse`, `-w` | from profile | Snowflake warehouse override |
| `--role`, `-r` | from profile | Snowflake role override |
| `--generate-sample` | `false` | Generate synthetic data for schema-only sources |
| `--rows` | `100` | Rows to generate (with `--generate-sample`) |

**Output:** JSON with `database`, `schema`, `profile`, and `tables[]` array containing `table_name`, `status`, `rows_loaded`, `columns`, `source_file`.
```

- [ ] **Step 3: Add CHANGELOG.md entry**

Read the top of `CHANGELOG.md`. Add a new dated section at the top (below the header):

```markdown
## 2026-06-26
- feat: add `ts load` CLI command group — schema inference, synthetic data generation, Snowflake loading
- chore: bump ts-cli to v0.15.0
```

- [ ] **Step 4: Verify version sync**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python tools/validate/check_version_sync.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/__init__.py tools/ts-cli/pyproject.toml tools/ts-cli/CLAUDE.md tools/ts-cli/README.md CHANGELOG.md
git commit -m "chore(ts-cli): bump to v0.15.0, document ts load commands"
```

---

### Task 5: SKILL.md and skill references

**Files:**
- Create: `agents/cli/ts-load-source-data/SKILL.md`
- Create: `agents/cli/ts-load-source-data/references/open-items.md`

**Interfaces:**
- Consumes: CLI commands `ts load infer`, `ts load generate`, `ts load snowflake` from Tasks 1–3
- Produces: interactive skill usable via `/ts-load-source-data`

- [ ] **Step 1: Create the SKILL.md**

Create `agents/cli/ts-load-source-data/SKILL.md`:

```markdown
---
name: ts-load-source-data
description: Load source data (CSV, Tableau download, manifest) into a warehouse. Infers schema, generates synthetic data for schema-only sources, and provisions tables. Snowflake supported; Databricks planned.
---

# Load Source Data

Load CSV data into a warehouse for ThoughtSpot to connect to. Supports four input
modes: CSV directory, Tableau Cloud download output, manifest JSON, and schema-only
with synthetic data generation.

Ask one question at a time for **dependent** decisions. Batch independent questions.

---

## References

| File | Purpose |
|---|---|
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure — for understanding the downstream ThoughtSpot objects |
| [references/open-items.md](references/open-items.md) | Known issues and verification items |

---

## Prerequisites

- Snowflake profile configured — run `/ts-profile-snowflake` if not
- `ts` CLI installed: `pip install -e tools/ts-cli` (v0.15.0+)
- For `method:python` profiles: `pip install snowflake-connector-python`
- For `method:cli` profiles: `snow` CLI installed and configured
- Source data accessible on disk (CSV files, download output, or manifest JSON)

---

## Step 0 — Overview

On skill invocation, display this plan:

---
**ts-load-source-data** — load source data into a warehouse for ThoughtSpot.

### Input modes

  **1  CSV directory** — a folder of `.csv` files, one table per file
  **2  Tableau download** — output JSON from `ts tableau download`
  **3  Manifest JSON** — explicit schema + data file paths
  **4  Schema only** — column definitions without data → generate synthetic sample data

### Steps

  1.  Identify source data (path + auto-detect mode) ........ you provide
  2.  Select target warehouse (Snowflake) ................... auto (v1)
  3.  Select Snowflake profile .............................. you choose
  4.  Specify target location (database, schema) ............ you provide
  5.  Schema review (inferred types, confirm/override) ...... you confirm
  6.  Load data ............................................. auto
  7.  Summary + next steps .................................. auto

---

## Step 1 — Identify Source Data

Ask: "Provide the path to your source data — a directory of CSV files, a JSON file
from `ts tableau download`, or a manifest JSON."

Run `ts load infer --source <path>` to auto-detect and display:

```
Source type: {csv_dir | tableau_download | manifest | schema_only}
Tables found: {N}
```

If `schema_only`:
```
No data files found — this is a schema-only source.
Would you like to generate synthetic sample data? (Y/n)
If yes, how many rows per table? [100]:
```

---

## Step 2 — Select Target Warehouse

v1 supports Snowflake only. Display:

```
Target warehouse: Snowflake
```

When Databricks support is added, prompt: `Load into Snowflake or Databricks?`

---

## Step 3 — Select Snowflake Profile

Read `~/.claude/snowflake-profiles.json`. Show:

```
Snowflake profiles:

  1. {name}  —  {method_label}  —  {account_or_connection}
  2. {name}  —  {method_label}  —  {account_or_connection}

Select a profile (enter number or name):
```

For `method_label`: `method: python` + `auth: key_pair` → `python / key pair`,
`method: python` + `auth: password` → `python / password`, `method: cli` → `Snowflake CLI`.

---

## Step 4 — Specify Target Location

Ask: "Target database name:" and "Target schema name:"

Offer defaults if available from source metadata (e.g., Tableau download may have
the datasource name as a schema hint).

---

## Step 5 — Schema Review

Display the inferred schema from Step 1 as a table:

```
Table: {TABLE_NAME}  ({row_count} rows from {file})

  #   Column Name         DB Column Name      Inferred Type
  1   Row ID              ROW_ID              INTEGER
  2   Order Date          ORDER_DATE          DATE
  3   Sales               SALES               FLOAT
  4   Customer Name       CUSTOMER_NAME       VARCHAR(384)

Type overrides? Enter column # and new type (e.g. "1 VARCHAR(20)"), or confirm (Y):
```

Repeat for each table. Save the confirmed schema as a manifest JSON for reproducibility.

If schema-only + user accepted synthetic data in Step 1, run `ts load generate` here
with the confirmed schema.

---

## Step 6 — Load Data

Run `ts load snowflake` with the confirmed schema:

```bash
ts load snowflake --source <path> --profile <name> \
    --database <DB> --schema <SCH> --if-exists error
```

Show progress per table:

```
Loading into {DB}.{SCH}...
  DUNDERMIFFLINSALESTABLE    42 rows    ✓ created
  CUSTOMERSTABLE            150 rows    ✓ created
```

---

## Step 7 — Summary

Display the load result:

```
Load complete.

  Database: {DB}
  Schema:   {SCH}
  Profile:  {profile_name}

  Tables loaded:
    {TABLE_NAME}   {rows} rows   {columns} columns

Next steps:
  • Create a ThoughtSpot connection to {DB}.{SCH}
    → /ts-object-connection-create (when available)
  • Build ThoughtSpot objects over these tables
    → /ts-convert-from-tableau (if migrating from Tableau)
```

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-06-26 | Initial release — Snowflake loading with schema inference and synthetic data generation |
```

- [ ] **Step 2: Create open-items.md**

Create `agents/cli/ts-load-source-data/references/open-items.md`:

```markdown
# Open Items — ts-load-source-data

Verification items tracked during development. See the
[repo convention](../../../../CLAUDE.md) for the open-items pattern.

---

## #1 — snow stage copy path format — UNVERIFIED

The `snow stage copy` command may require different path formats depending on
the snow CLI version. Need to verify the exact syntax for uploading to a table
stage (`@%table_name`) vs a named stage.

**Test:** `snow stage copy ./test.csv @DB.SCH.%TABLE_NAME -c <connection>`

---

## #2 — COPY INTO with quoted fields — UNVERIFIED

Verify that `FIELD_OPTIONALLY_ENCLOSED_BY='"'` correctly handles CSV files with
quoted fields containing commas (the DunderMifflin "First Aid Kit, Office Size"
pattern from the Tableau migration).

**Test:** Load a CSV with quoted-comma fields and verify row counts match.

---

## #3 — CREATE DATABASE IF NOT EXISTS permissions — UNVERIFIED

The Snowflake role used may not have `CREATE DATABASE` privileges. Need to verify
behaviour when the database already exists vs when it needs to be created, and
document the required role permissions.
```

- [ ] **Step 3: Commit**

```bash
git add agents/cli/ts-load-source-data/SKILL.md agents/cli/ts-load-source-data/references/open-items.md
git commit -m "feat: add ts-load-source-data SKILL.md and open-items"
```

---

### Task 6: Repo convention updates (naming, coverage, smoke test, README, SETUP)

**Files:**
- Modify: `.claude/rules/skill-naming.md`
- Modify: `tools/validate/check_skill_naming.py:31-64`
- Modify: `tools/validate/check_runtime_coverage.py:36-74`
- Create: `tools/smoke-tests/smoke_ts_load_source_data.py`
- Modify: `README.md`
- Modify: `agents/cli/SETUP.md`

**Interfaces:**
- Consumes: SKILL.md from Task 5, CLI commands from Tasks 1–3
- Produces: passing validators, documented skill in README/SETUP

- [ ] **Step 1: Add ts-load-* family to skill-naming.md**

Read `.claude/rules/skill-naming.md`. Add a new row to the family table (after row 8, `ts-audit`):

```markdown
| 9 | `ts-load-*` | `ts-load-{specifier}` | Load source data into a warehouse. Specifier describes the data domain or purpose. | `ts-load-source-data` |
```

Also add a new section to the "How to choose a family" decision tree, before "None of the above match":

```markdown
### 9. Does the skill load or provision data in an external warehouse?

→ **`ts-load-*`**. Pattern: `ts-load-{specifier}`.

This family is for skills that take source data (CSV, manifest, schema definitions)
and load it into a warehouse (Snowflake, Databricks, etc.) so that ThoughtSpot can
connect to it. Distinct from `ts-setup-*` (which installs procedures/infrastructure)
and `ts-convert-*` (which converts between platform schemas).
```

Renumber the existing "None of the above match" from 9 to 10.

- [ ] **Step 2: Add ts-load-* pattern to check_skill_naming.py**

Edit `tools/validate/check_skill_naming.py`. Add after the `ts-audit` entry (line 63):

```python
    "ts-load-*": (
        re.compile(r"ts-load-[a-z][a-z0-9]*(-[a-z][a-z0-9]*)*"),
        "data loading: ts-load-{specifier}",
    ),
```

- [ ] **Step 3: Add ts-load-source-data to EXPECTED_DIVERGENCES**

Edit `tools/validate/check_runtime_coverage.py`. Add after the `ts-profile-tableau` entry (line 73):

```python
    ("ts-load-source-data", "coco-snowsight"):
        "Warehouse loading requires shell access and external tool orchestration; not supported in Snowsight stored-proc runtime",
```

- [ ] **Step 4: Create the smoke test**

Create `tools/smoke-tests/smoke_ts_load_source_data.py`:

```python
#!/usr/bin/env python3
"""
smoke_ts_load_source_data.py — smoke test for ts-load-source-data.

Verifies the load workflow offline (no live Snowflake connection needed):
  1.  ts load infer against a CSV directory
  2.  ts load infer against a Tableau download JSON
  3.  ts load infer against a schema-only manifest
  4.  ts load generate from a schema
  5.  Verify generated CSV structure and row counts

Usage:
    python tools/smoke-tests/smoke_ts_load_source_data.py
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import SmokeTestResult, SkipStep  # noqa: E402


def run_ts_load(args: list[str]) -> dict | list:
    """Run a ts load command and return parsed JSON."""
    cmd = ["ts", "load"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ts load {' '.join(args)} failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout)


def main():
    print("smoke_ts_load_source_data")
    print("=" * 40)
    r = SmokeTestResult()

    with tempfile.TemporaryDirectory(prefix="smoke_load_") as tmpdir:
        tmp = Path(tmpdir)

        # --- Step 1: Infer from CSV directory ---
        csv_dir = tmp / "csvs"
        csv_dir.mkdir()
        (csv_dir / "sales.csv").write_text("id,amount,order_date\n1,9.99,2024-01-15\n2,19.50,2024-02-20\n")
        (csv_dir / "customers.csv").write_text("cust_id,name,email\n1,Alice,a@b.com\n2,Bob,b@c.com\n")

        def step_infer_csv_dir():
            result = run_ts_load(["infer", "--source", str(csv_dir)])
            assert result["source_type"] == "csv_dir", f"Expected csv_dir, got {result['source_type']}"
            assert len(result["tables"]) == 2, f"Expected 2 tables, got {len(result['tables'])}"
            return result

        ok, infer_result = r.step("1. Infer from CSV directory", step_infer_csv_dir)

        # --- Step 2: Infer from Tableau download JSON ---
        download_json = tmp / "download.json"
        download_json.write_text(json.dumps({
            "tdsx_path": "/tmp/test.tdsx",
            "extracted_dir": str(csv_dir),
            "files": ["sales.csv"],
            "data_files": [
                {"name": "sales.csv", "path": str(csv_dir / "sales.csv"),
                 "type": "csv", "validation": {"total_lines": 3, "header_columns": 3, "corrupt_lines": []}}
            ],
        }))

        def step_infer_tableau():
            result = run_ts_load(["infer", "--source", str(download_json)])
            assert result["source_type"] == "tableau_download"
            return result

        r.step("2. Infer from Tableau download JSON", step_infer_tableau)

        # --- Step 3: Infer from schema-only manifest ---
        schema_json = tmp / "schema.json"
        schema_json.write_text(json.dumps({
            "source": "manual",
            "tables": [{"table_name": "DEMO", "columns": [
                {"name": "id", "db_column_name": "ID", "type": "INTEGER"},
                {"name": "value", "db_column_name": "VALUE", "type": "FLOAT"},
            ]}],
        }))

        def step_infer_schema_only():
            result = run_ts_load(["infer", "--source", str(schema_json)])
            assert result["source_type"] == "schema_only"
            return result

        r.step("3. Infer from schema-only manifest", step_infer_schema_only)

        # --- Step 4: Generate from schema ---
        gen_dir = tmp / "generated"

        def step_generate():
            result = run_ts_load(["generate", "--source", str(schema_json),
                                  "--rows", "50", "--output", str(gen_dir)])
            assert len(result) == 1
            assert result[0]["rows"] == 50
            gen_file = gen_dir / "DEMO.csv"
            assert gen_file.exists(), f"Generated file not found: {gen_file}"
            return result

        r.step("4. Generate synthetic data", step_generate)

        # --- Step 5: Verify generated CSV ---
        def step_verify_csv():
            gen_file = gen_dir / "DEMO.csv"
            with open(gen_file, newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
                assert header == ["ID", "VALUE"], f"Unexpected header: {header}"
                rows = list(reader)
                assert len(rows) == 50, f"Expected 50 rows, got {len(rows)}"
            return True

        r.step("5. Verify generated CSV structure", step_verify_csv)

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Add skill to README.md skills table**

Read `README.md`. Find the "ThoughtSpot Objects" section. Add a new section **before** "Connection Profiles":

```markdown
**Data Loading** — load source data into warehouses for ThoughtSpot

| Skill | What it does |
|---|---|
| [`ts-load-source-data`](agents/cli/ts-load-source-data/SKILL.md) | Load CSV data into Snowflake (or generate synthetic data from schema definitions) for ThoughtSpot to connect to |
```

- [ ] **Step 6: Add symlink to SETUP.md**

Read `agents/cli/SETUP.md`. Add to both the Cortex Code CLI section and the Claude Code section:

Cortex Code CLI section (after the last `ln -s` line in that block):
```bash
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-load-source-data \
      ~/.snowflake/cortex/skills/ts-load-source-data
```

Claude Code section (after the last `ln -s` line in that block):
```bash
ln -s ~/thoughtspot-agent-skills/agents/cli/ts-load-source-data \
      ~/.claude/skills/ts-load-source-data
```

- [ ] **Step 7: Run all validators**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python3 tools/validate/check_skill_naming.py --root . && python3 tools/validate/check_runtime_coverage.py --root . && echo "All validators pass"`
Expected: Both validators PASS

- [ ] **Step 8: Run the smoke test**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python tools/smoke-tests/smoke_ts_load_source_data.py`
Expected: All 5 steps PASS

- [ ] **Step 9: Commit**

```bash
git add .claude/rules/skill-naming.md tools/validate/check_skill_naming.py \
    tools/validate/check_runtime_coverage.py tools/smoke-tests/smoke_ts_load_source_data.py \
    README.md agents/cli/SETUP.md
git commit -m "chore: add ts-load-* skill family, runtime coverage, smoke test, README, SETUP"
```

---

### Task 7: Backlog update and final verification

**Files:**
- Modify: `docs/backlog.md`

**Interfaces:**
- Consumes: all previous tasks
- Produces: updated backlog, verified full test suite

- [ ] **Step 1: Update BL-010 in backlog.md**

Read `docs/backlog.md` and find the BL-010 entry. Update its status to reflect v1 completion:

Add at the end of the BL-010 section:

```markdown
**Status (2026-06-26):** v1 shipped — Snowflake loading (both `method:python` and
`method:cli`), schema inference, synthetic data generation, four input modes.
Databricks loading deferred to v2.
```

- [ ] **Step 2: Run the full ts-cli test suite**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python -m pytest tools/ts-cli/tests/ -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 3: Run all validators**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && for v in tools/validate/check_*.py; do echo "--- $v ---"; python3 "$v" --root .; done`
Expected: All validators PASS

- [ ] **Step 4: Commit**

```bash
git add docs/backlog.md
git commit -m "docs: update BL-010 status — v1 shipped"
```

- [ ] **Step 5: Verify all commits are clean**

Run: `git log --oneline feat/ts-load-source-data ^main`
Expected: 7 commits (one per task) + the spec commit from brainstorming
