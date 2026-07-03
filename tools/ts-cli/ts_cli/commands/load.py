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
        return max(0, sum(1 for _ in f) - 1)


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

    if any(w in lower for w in ("name", "customer")) and "INTEGER" not in col_type and "FLOAT" not in col_type:
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
