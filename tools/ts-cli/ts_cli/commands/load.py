"""ts load — source data loading commands for warehouse provisioning."""
from __future__ import annotations

import csv as csv_mod
import json
import math
import re
import subprocess
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
            return _detect_tables_source(data["tables"])

    raise SystemExit(f"Cannot detect source type for {path}. "
                     "Provide a CSV directory, Tableau download JSON, or manifest JSON.")


def _detect_tables_source(tables: list[dict]) -> tuple[str, list[dict]]:
    """Normalise a `{"tables": [...]}` manifest into (source_type, file_infos).

    `manifest` when any table has a `data_file` (load its CSV); otherwise `schema_only`
    (synthetic generation). Per-table `columns` and optional `rows` are carried through.
    """
    has_data = any(t.get("data_file") for t in tables)
    file_infos = []
    for t in tables:
        info: dict[str, Any] = {"table_name": t["table_name"], "columns": t.get("columns", [])}
        if has_data and t.get("data_file"):
            info["csv_path"] = Path(t["data_file"])
        if t.get("rows") is not None:
            info["rows"] = t["rows"]
        file_infos.append(info)
    return ("manifest" if has_data else "schema_only"), file_infos


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
        return max(0, sum(1 for _ in f) - 1)


def infer_schema(source_path: Path) -> dict:
    """Top-level inference: detect source, infer types, return full JSON output."""
    source_type, file_infos = detect_source(source_path)

    tables = []
    for info in file_infos:
        if source_type == "schema_only":
            entry = {
                "table_name": info["table_name"],
                "row_count": 0,
                "columns": info.get("columns", []),
                "has_data": False,
            }
            if info.get("rows") is not None:
                entry["rows"] = info["rows"]
            tables.append(entry)
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


def _is_int_type(col_type: str) -> bool:
    """True for integer-family types across dialects: INTEGER/INT/BIGINT/… and
    NUMBER/NUMERIC/DECIMAL with zero (or absent) scale."""
    t = (col_type or "").upper()
    if any(k in t for k in ("INTEGER", "BIGINT", "SMALLINT", "TINYINT", "INT64", "INT32")) or \
            re.search(r"\bINT\b", t):
        return True
    if any(k in t for k in ("NUMBER", "NUMERIC", "DECIMAL")):
        m = re.search(r"\(\s*\d+\s*,\s*(\d+)\s*\)", t)
        return not (m and int(m.group(1)) > 0)   # scale 0 / no scale → integer
    return False


def _is_float_type(col_type: str) -> bool:
    """True for real-number types: FLOAT/DOUBLE/REAL and NUMBER/DECIMAL with scale > 0."""
    t = (col_type or "").upper()
    if any(k in t for k in ("FLOAT", "DOUBLE", "REAL", "FLOAT64")):
        return True
    if any(k in t for k in ("NUMBER", "NUMERIC", "DECIMAL")):
        m = re.search(r"\(\s*\d+\s*,\s*(\d+)\s*\)", t)
        return bool(m and int(m.group(1)) > 0)
    return False


def _explicit_generator(col: dict, rng):
    """Generator from an explicit spec on the column, or None to fall back to heuristics.

    - `values: [...]`  → pick uniformly from the set (categorical alignment: a formula that
      tests `[behavior] = 'speeding'` only produces non-zero rows if 'speeding' is emitted).
    - `min`/`max`      → uniform numeric in range (threshold alignment: a grade formula
      `[ki] > 5` needs values that straddle 5 to yield both PASS and FAIL).
    Used by the synthetic-data manifest derived from a Tableau model's formulas.
    """
    vals = col.get("values")
    if vals:
        return lambda: str(rng.choice(vals))
    if "min" in col and "max" in col:
        lo, hi = col["min"], col["max"]
        col_type = col.get("inferred_type", col.get("type", ""))
        if _is_float_type(col_type):
            return lambda: f"{rng.uniform(float(lo), float(hi)):.2f}"
        return lambda: str(rng.randint(int(lo), int(hi)))
    return None


def _pick_generator(col_name: str, col_type: str, rng):
    """Return a generator function for a column based on name and type patterns."""
    lower = col_name.lower()

    if ("id" in lower or "key" in lower) and _is_int_type(col_type):
        counter = [0]
        def gen_seq():
            counter[0] += 1
            return str(counter[0])
        return gen_seq

    if "email" in lower:
        def gen_email():
            return f"user_{rng.randint(1, 9999)}@example.com"
        return gen_email

    if any(w in lower for w in ("name", "customer")) and not _is_int_type(col_type) and not _is_float_type(col_type):
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

    if "BOOL" in col_type.upper():   # matches BOOL and BOOLEAN
        def gen_bool():
            return rng.choice(["true", "false"])
        return gen_bool
    if _is_int_type(col_type):
        def gen_int():
            return str(rng.randint(1, 1000))
        return gen_int
    if _is_float_type(col_type):
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
        generators.append(_explicit_generator(col, rng)
                          or _pick_generator(col_name, col_type, rng))

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
        # A table may pin its own row count (e.g. a fleet-grain dimension wants 1 row so a
        # KPI shows one clean value, while its driver-grain fact wants many for a Top-N).
        n = int(tbl.get("rows", rows))
        csv_path = generate_csv(tbl, rows=n, output_dir=output_dir, seed=seed)
        results.append({
            "table_name": tbl["table_name"],
            "rows": n,
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
            match = re.search(r"(\d+)", row_result.stdout)
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
            "Install it with the snowflake extra:\n"
            "  pip install 'thoughtspot-cli[snowflake]'\n"
            "If ts was installed as an isolated uv tool, inject it into that env:\n"
            "  uv tool install thoughtspot-cli --with snowflake-connector-python"
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


# ---------------------------------------------------------------------------
# Databricks loader (ts load databricks) — provisions tables + synthetic data
# into a Databricks catalog.schema via the SQL Statement Execution API, so a
# ThoughtSpot Databricks connection can bind a model over them. Mirrors the
# Snowflake loader; execution goes through the `databricks` CLI (token lives in
# ~/.databrickscfg, never here). Pure SQL-builders below are unit-tested.
# ---------------------------------------------------------------------------

_DBX_PROFILES_PATH = Path.home() / ".claude" / "databricks-profiles.json"


def _load_dbx_profile(profile_name: str) -> dict:
    if not _DBX_PROFILES_PATH.exists():
        raise SystemExit(f"No Databricks profiles file at {_DBX_PROFILES_PATH}. "
                         "Run /ts-profile-databricks or create it.")
    data = json.loads(_DBX_PROFILES_PATH.read_text(encoding="utf-8"))
    profiles = data.get("profiles", data) if isinstance(data, dict) else data
    items = profiles if isinstance(profiles, list) else list(profiles.values())
    for p in items:
        if p.get("name") == profile_name:
            return p
    raise SystemExit(f"Databricks profile '{profile_name}' not found. "
                     f"Available: {[p.get('name') for p in items]}")


def dbx_type(src_type: str) -> str:
    """Map an inferred (Snowflake-ish) column type → a Databricks SQL type."""
    t = (src_type or "STRING").upper().strip()
    if t.startswith(("VARCHAR", "CHAR", "STRING", "TEXT")):
        return "STRING"
    if t.startswith("BOOL"):
        return "BOOLEAN"
    if t.startswith("DATE"):
        return "DATE"
    if t.startswith(("TIMESTAMP", "DATETIME")):
        return "TIMESTAMP"
    if t.startswith(("FLOAT", "DOUBLE", "REAL")):
        return "DOUBLE"
    if t.startswith(("NUMBER", "NUMERIC", "DECIMAL")):
        m = re.search(r"\(\s*\d+\s*,\s*(\d+)\s*\)", t)
        return "DOUBLE" if (m and int(m.group(1)) > 0) else "BIGINT"
    if t.startswith(("INT", "BIGINT", "SMALLINT", "TINYINT")):
        return "BIGINT"
    return "STRING"


def _col_name(col: dict) -> str:
    return col.get("db_column_name") or col.get("name") or ""


def _col_type(col: dict) -> str:
    return col.get("inferred_type") or col.get("type") or "STRING"


def build_dbx_create_sql(fqtn: str, columns: list, replace: bool = False) -> str:
    """CREATE TABLE DDL. Backtick-quotes identifiers and enables Delta **column mapping**
    so source column names with spaces/special chars (e.g. `Order Date`, `Order Id`) are
    preserved 1:1 — Delta otherwise rejects them (DELTA_INVALID_CHARACTERS_IN_COLUMN_NAMES).
    `replace=True` uses CREATE OR REPLACE (drops+recreates to change the schema of an
    already-provisioned table). Live-verified on ps-internal 2026-07-16."""
    verb = "CREATE OR REPLACE TABLE" if replace else "CREATE TABLE IF NOT EXISTS"
    cols = ",\n  ".join(f"`{_col_name(c)}` {dbx_type(_col_type(c))}" for c in columns)
    return (f"{verb} {fqtn} (\n  {cols}\n) USING DELTA\n"
            "TBLPROPERTIES ('delta.columnMapping.mode' = 'name', "
            "'delta.minReaderVersion' = '2', 'delta.minWriterVersion' = '5')")


def _sql_literal(val: str, dtype: str) -> str:
    if val is None or val == "":
        return "NULL"
    if dtype in ("BIGINT", "DOUBLE"):
        return str(val)
    if dtype == "BOOLEAN":
        return "true" if str(val).strip().lower() in ("true", "1", "yes", "t") else "false"
    if dtype == "DATE":
        return f"DATE'{val}'"
    if dtype == "TIMESTAMP":
        return f"TIMESTAMP'{val}'"
    return "'" + str(val).replace("\\", "\\\\").replace("'", "''") + "'"


def build_dbx_insert_sql(fqtn: str, columns: list, rows: list) -> str:
    """INSERT ... VALUES for a batch of rows (row = list of stringified cell values)."""
    dtypes = [dbx_type(_col_type(c)) for c in columns]
    collist = ", ".join(f"`{_col_name(c)}`" for c in columns)
    tuples = ", ".join("(" + ", ".join(_sql_literal(v, t) for v, t in zip(r, dtypes)) + ")"
                       for r in rows)
    return f"INSERT INTO {fqtn} ({collist}) VALUES {tuples}"


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _dbx_exec(cli_profile: str, warehouse_id: str, statement: str) -> dict:
    """Run one SQL statement via the Databricks Statement Execution API (databricks CLI)."""
    import time
    payload = json.dumps({"warehouse_id": warehouse_id, "statement": statement,
                          "wait_timeout": "50s"})
    r = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements",
                        "--profile", cli_profile, "--json", payload],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"databricks api post failed:\n{r.stderr.strip() or r.stdout.strip()}")
    data = json.loads(r.stdout)
    state = data.get("status", {}).get("state")
    stmt_id = data.get("statement_id")
    while state not in ("SUCCEEDED", "FAILED", "CANCELED", "CLOSED"):
        time.sleep(2)
        r2 = subprocess.run(["databricks", "api", "get",
                             f"/api/2.0/sql/statements/{stmt_id}", "--profile", cli_profile],
                            capture_output=True, text=True)
        data = json.loads(r2.stdout)
        state = data.get("status", {}).get("state")
    if state != "SUCCEEDED":
        msg = data.get("status", {}).get("error", {}).get("message", state)
        raise SystemExit(f"Databricks SQL failed ({state}): {msg}")
    return data


@app.command()
def databricks(
    source: str = typer.Option(..., "--source", "-s",
                               help="Schema/manifest JSON (or CSV dir) describing the table(s)"),
    profile: str = typer.Option(..., "--profile", "-p", help="Databricks profile name"),
    catalog: Optional[str] = typer.Option(None, "--catalog", help="Override profile catalog"),
    schema: Optional[str] = typer.Option(None, "--schema", help="Override profile schema"),
    rows: int = typer.Option(100, "--rows", "-r", help="Synthetic rows per table"),
    seed: int = typer.Option(42, "--seed", help="Deterministic data seed"),
    batch: int = typer.Option(200, "--batch", help="Rows per INSERT statement"),
    replace: bool = typer.Option(False, "--replace", help="CREATE OR REPLACE (re-provision an existing table's schema)"),
) -> None:
    """Provision table(s) + synthetic data into a Databricks catalog.schema.

    Infers the schema from --source, generates deterministic synthetic rows, then
    CREATE TABLE + INSERT via the Databricks SQL Statement Execution API (the `databricks`
    CLI; the token stays in ~/.databrickscfg). Makes source data exist so a ThoughtSpot
    Databricks connection can bind a model — the Databricks half of ts-load-source-data.
    """
    import tempfile
    prof = _load_dbx_profile(profile)
    cli_profile = prof.get("dbx_profile") or profile
    http_path = prof.get("sql_warehouse_http_path", "")
    if not http_path:
        raise SystemExit("Profile has no sql_warehouse_http_path.")
    warehouse_id = http_path.rstrip("/").split("/")[-1]
    cat = catalog or prof.get("catalog")
    sch = schema or prof.get("schema")
    if not cat or not sch:
        raise SystemExit("catalog and schema required (profile or --catalog/--schema).")

    tables = infer_schema(Path(source))["tables"]
    out_dir = Path(tempfile.mkdtemp(prefix="dbxload_"))
    _dbx_exec(cli_profile, warehouse_id, f"CREATE SCHEMA IF NOT EXISTS `{cat}`.`{sch}`")

    results = []
    for tbl in tables:
        name = tbl["table_name"]
        cols = tbl["columns"]
        fqtn = f"`{cat}`.`{sch}`.`{name}`"
        _dbx_exec(cli_profile, warehouse_id, build_dbx_create_sql(fqtn, cols, replace=replace))
        n = int(tbl.get("rows", rows))   # a table may pin its own row count in the manifest
        csv_path = generate_csv(tbl, rows=n, output_dir=out_dir, seed=seed)
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv_mod.reader(f)
            next(reader, None)  # skip header
            data_rows = list(reader)
        for chunk in _chunks(data_rows, batch):
            _dbx_exec(cli_profile, warehouse_id, build_dbx_insert_sql(fqtn, cols, chunk))
        results.append({"table": f"{cat}.{sch}.{name}", "rows": len(data_rows)})
        typer.echo(f"  loaded {cat}.{sch}.{name} ({len(data_rows)} rows)", err=True)

    print(json.dumps({"loaded": results, "catalog": cat, "schema": sch,
                      "warehouse_id": warehouse_id}, indent=2))
