"""ts load — source data loading commands for warehouse provisioning."""
from __future__ import annotations

import codecs
import csv as csv_mod
import io
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


def _resolve_data_path(named: str, base_dir: Path, what: str,
                       require: bool = True) -> Optional[Path]:
    """The absolute path of a data file a source JSON names.

    An absolute path is used as is. A relative one is looked for next to the JSON and in the
    working directory: if exactly one of those holds a file, it is used; if both do and they
    are different files, the source is refused as ambiguous. (BL-550 re-review: the two
    loaders used to resolve the same name to different files.) A file found in neither place
    is refused when `require`, else None — `ts load generate` and `--generate-sample` read
    no source rows, so they do not need it."""
    rel = Path(named)
    candidates = [rel] if rel.is_absolute() else [base_dir / rel, Path.cwd() / rel]
    found: list[Path] = []
    for c in candidates:
        if c.is_file() and c.resolve() not in found:
            found.append(c.resolve())
    if len(found) > 1:
        raise SystemExit(f"{what}: data file {named} is ambiguous — both {found[0]} and "
                         f"{found[1]} exist. Give its absolute path.")
    if found:
        return found[0]
    if not require:
        return None
    raise SystemExit(f"{what}: data file {named} not found "
                     f"(looked next to the source JSON, {base_dir}, and in the working directory).")


def detect_source(path: Path, require_data: bool = True) -> tuple[str, list[dict]]:
    """Auto-detect source type and return normalised file info list.

    Returns (source_type, file_infos) where source_type is one of:
      csv_dir, tableau_download, manifest, schema_only
    Every `csv_path` is absolute (`_resolve_data_path`). With `require_data=False`, a data
    file that is missing is treated as absent rather than refused.
    """
    if path.is_dir():
        csv_files = sorted(path.glob("*.csv"))
        if not csv_files:
            raise SystemExit(f"No .csv files found in {path}")
        file_infos = []
        for f in csv_files:
            table_name = sanitise_name(f.stem)
            file_infos.append({"csv_path": f.resolve(), "table_name": table_name})
        return "csv_dir", file_infos

    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))

        if "data_files" in data:
            file_infos = []
            for df in data["data_files"]:
                if df.get("type") != "csv":
                    continue
                csv_path = _resolve_data_path(df["path"], path.parent, f"{path.name}")
                table_name = sanitise_name(csv_path.stem)
                file_infos.append({"csv_path": csv_path, "table_name": table_name})
            if not file_infos:
                raise SystemExit("No CSV data_files found in Tableau download output")
            return "tableau_download", file_infos

        if "tables" in data:
            return _detect_tables_source(data["tables"], path.parent, require_data)

    raise SystemExit(f"Cannot detect source type for {path}. "
                     "Provide a CSV directory, Tableau download JSON, or manifest JSON.")


def _table_data_path(t: dict, base_dir: Path, require: bool = True) -> Optional[Path]:
    """The CSV a `tables[]` entry names, or None for a schema-only table.

    Two shapes name one: a manifest's `data_file`, and `ts load infer` output fed back as a
    source — `file` with `has_data: true` (output from before `data_file` was added). Paths
    resolve by `_resolve_data_path`; a missing one is refused when `require`, never read as
    schema-only (BL-550)."""
    named = t.get("data_file") or (t.get("file") if t.get("has_data") else None)
    if not named:
        return None
    return _resolve_data_path(named, base_dir, f"Table {t.get('table_name')}", require)


def _detect_tables_source(tables: list[dict], base_dir: Path = Path("."),
                          require_data: bool = True) -> tuple[str, list[dict]]:
    """Normalise a `{"tables": [...]}` manifest into (source_type, file_infos).

    `manifest` when any table names a data file (see `_table_data_path`); otherwise
    `schema_only` (synthetic generation). Per-table `columns` and optional `rows` are
    carried through.
    """
    paths = [_table_data_path(t, base_dir, require_data) for t in tables]
    has_data = any(paths)
    file_infos = []
    for t, data_path in zip(tables, paths):
        info: dict[str, Any] = {"table_name": t["table_name"], "columns": t.get("columns", [])}
        if data_path is not None:
            info["csv_path"] = data_path
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
    # Only true/false text is BOOLEAN; an all-0/1 column stays INTEGER (BL-550 re-review:
    # flags, counts and ids of 0/1 were typed BOOLEAN and could not be summed).
    bool_vals = {"true", "false"}

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


def read_csv_text(csv_path: Path, encoding: str = "utf-8") -> str:
    """A CSV's text, decoded strictly. UTF-8 is read as utf-8-sig, so a byte-order mark never
    reaches the first header name. A byte that does not decode is refused, naming the file,
    line and byte offset, instead of being replaced with U+FFFD (BL-550 review)."""
    try:
        name = codecs.lookup(encoding).name
    except LookupError:
        raise SystemExit(f"Unknown encoding {encoding!r}.") from None
    raw = Path(csv_path).read_bytes()
    # The BOM is cut here, not by the utf-8-sig codec, whose error offsets then count from
    # after the BOM and name the wrong byte.
    skip = len(codecs.BOM_UTF8) if name == "utf-8" and raw.startswith(codecs.BOM_UTF8) else 0
    try:
        return raw[skip:].decode(encoding)
    except UnicodeDecodeError as e:
        at = e.start + skip
        line = raw.count(b"\n", 0, at) + 1
        raise SystemExit(
            f"{csv_path}: line {line}, byte offset {at}: 0x{raw[at]:02X} is not valid "
            f"{encoding}. If the file uses another encoding, pass it with --encoding to "
            f"ts load infer or ts load databricks (for example cp1252); ts load snowflake "
            f"reads UTF-8 only, so convert the file first.") from None


def infer_column_types(csv_path: Path, max_rows: int = 1000,
                       encoding: Optional[str] = "utf-8") -> list[dict]:
    """Infer column types from a CSV file by scanning sample rows.

    Returns a list of dicts with keys: name, db_column_name, inferred_type. The file is
    decoded strictly (`read_csv_text`), so a column name in another encoding is refused, or
    read correctly with `encoding`, never replaced with U+FFFD.
    """
    with io.StringIO(read_csv_text(csv_path, encoding or "utf-8"), newline="") as f:
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


def infer_schema(source_path: Path, encoding: Optional[str] = "utf-8",
                 require_data: bool = True) -> dict:
    """Top-level inference: detect source, infer types, return full JSON output.

    Each table with data carries `data_file`, the absolute path of its CSV, so the output
    can be fed back as `--source` (after a schema review) from any working directory and
    still load that CSV's rows. `encoding` is passed to `infer_column_types`;
    `require_data=False` lets a manifest name data files that are missing (see
    `detect_source`)."""
    source_type, file_infos = detect_source(source_path, require_data)

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
            entry = {
                "file": csv_path.name if csv_path else None,
                "table_name": info["table_name"],
                "row_count": row_count,
                "columns": info["columns"],
                "has_data": csv_path is not None,
            }
            if csv_path is not None:
                entry["data_file"] = str(csv_path)
            tables.append(entry)
            continue

        csv_path = info.get("csv_path")
        if csv_path is None:
            raise SystemExit(f"Table {info['table_name']}: no data file and no columns.")
        columns = infer_column_types(csv_path, encoding=encoding)
        row_count = _count_csv_rows(csv_path)
        tables.append({
            "file": csv_path.name,
            "data_file": str(csv_path),
            "table_name": info["table_name"],
            "row_count": row_count,
            "columns": columns,
            "has_data": True,
        })

    return {"source_type": source_type, "tables": tables}


@app.command()
def infer(
    source: str = typer.Option(..., "--source", "-s", help="Path to CSV directory, download JSON, or manifest JSON"),
    encoding: str = typer.Option("utf-8", "--encoding",
                                 help="CSV text encoding, decoded strictly (e.g. cp1252)"),
) -> None:
    """Infer table schemas from source data."""
    result = infer_schema(Path(source), encoding=encoding)
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


def _type_class(col_type: str) -> str:
    """bool | timestamp | date | int | float | string — the column TYPE decides first."""
    t = (col_type or "").upper()
    if "BOOL" in t:
        return "bool"
    if t.startswith("TIMESTAMP") or "DATETIME" in t:
        return "timestamp"
    if t.startswith("DATE"):
        return "date"
    if _is_int_type(t):
        return "int"
    if _is_float_type(t):
        return "float"
    return "string"


def _gen_seq():
    counter = [0]
    def gen():
        counter[0] += 1
        return str(counter[0])
    return gen


def _gen_date(rng, with_time: bool):
    def gen():
        d = f"{rng.randint(2023, 2025)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        if not with_time:
            return d
        return f"{d} {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}"
    return gen


def _numeric_generator(lower: str, kind: str, rng):
    if kind == "int":
        if "id" in lower or "key" in lower:
            return _gen_seq()
        if any(w in lower for w in ("quantity", "count", "qty")):
            return lambda: str(rng.randint(1, 100))
        return lambda: str(rng.randint(1, 1000))
    if any(w in lower for w in ("price", "amount", "cost", "sales", "revenue")):
        return lambda: f"{rng.uniform(1, 10000):.2f}"
    if any(w in lower for w in ("percent", "ratio", "rate")):
        return lambda: f"{rng.uniform(0, 1):.4f}"
    return lambda: f"{rng.uniform(0, 1000):.2f}"


def _string_generator(lower: str, rng):
    """Name-driven values for a text column (the only class where a name can choose freely).
    The first rule whose keyword appears in the name wins, in this order."""
    rules = (
        (("email",), lambda: lambda: f"user_{rng.randint(1, 9999)}@example.com"),
        (("name", "customer"), lambda: lambda: f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"),
        (("date", "_at", "_on"), lambda: _gen_date(rng, with_time=False)),
        (("price", "amount", "cost", "sales", "revenue"), lambda: lambda: f"{rng.uniform(1, 10000):.2f}"),
        (("quantity", "count", "qty"), lambda: lambda: str(rng.randint(1, 100))),
        (("status", "state", "type", "category"), lambda: lambda: rng.choice(_STATUSES)),
        (("city",), lambda: lambda: rng.choice(_CITIES)),
        (("region",), lambda: lambda: rng.choice(_REGIONS)),
        (("phone",), lambda: lambda: f"555-{rng.randint(0, 9999):04d}"),
        (("percent", "ratio", "rate"), lambda: lambda: f"{rng.uniform(0, 1):.4f}"),
    )
    for words, make in rules:
        if any(w in lower for w in words):
            return make()
    counter = [0]
    def gen_default():
        counter[0] += 1
        return f"val_{counter[0]:05d}"
    return gen_default


def _pick_generator(col_name: str, col_type: str, rng):
    """Return a generator function for a column: its TYPE first, then its name.

    The type decides the kind of value, so a name can never produce a value the column cannot
    hold (`has_email BOOLEAN` used to get an email address, `update_count BIGINT` a date);
    within a type, the name picks a realistic shape (sequential ids, money, quantities)."""
    lower = col_name.lower()
    kind = _type_class(col_type)
    if kind == "bool":
        return lambda: rng.choice(["true", "false"])
    if kind in ("date", "timestamp"):
        return _gen_date(rng, with_time=(kind == "timestamp"))
    if kind in ("int", "float"):
        return _numeric_generator(lower, kind, rng)
    return _string_generator(lower, rng)


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
    schema = infer_schema(source_path, require_data=False)   # no source rows are read
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


def get_sf_cursor(sf_profile: Optional[str]):
    """Snowflake cursor via the standard profile mechanism.

    The one implementation shared by every command that reads a governance table
    (`ts alias --source db`, `ts publish --source db`). Returns None when no
    profile is given, so callers can treat "no Snowflake configured" uniformly.
    """
    if not sf_profile:
        return None
    profile = load_snowflake_profile(sf_profile)
    conn = _connect_python(profile, profile.get("default_warehouse", ""),
                           profile.get("default_role", ""))
    return conn.cursor()


def load_snowflake_profile(profile_name: str) -> dict:
    """Load a Snowflake profile by name, raising SystemExit if not found."""
    from ts_cli.profile_ops import get_profile, load_platform_profiles
    profile = get_profile("snowflake", profile_name, path=SF_PROFILES_PATH)
    if profile is not None:
        return profile
    available = [p.get("name") for p in load_platform_profiles("snowflake", path=SF_PROFILES_PATH)]
    if not available:
        raise SystemExit(
            f"No Snowflake profiles found at {SF_PROFILES_PATH}.\n"
            "Run /ts-profile-snowflake to create one."
        )
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

        csv_path = _sf_csv_path(tbl, csv_dir)
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

            csv_path = _sf_csv_path(tbl, csv_dir)
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


def _sf_csv_path(tbl: dict, csv_dir: Path) -> Path:
    """The CSV a Snowflake load reads for one table: its resolved `data_file`, the same file
    `ts load databricks` reads (BL-550 re-review), else `csv_dir / file`. That fallback is
    unchanged, including its TypeError on a mixed manifest's table with no data file
    (`file: None`), which is a known, separately tracked defect."""
    if tbl.get("data_file"):
        return Path(tbl["data_file"])
    return csv_dir / tbl.get("file", f"{tbl['table_name']}.csv")


def _refuse_unreadable_data(tables: list, csv_dir: Path) -> None:
    """A table with data whose CSV cannot be read would be created empty with no error, so
    refuse it instead (BL-550 review)."""
    unreadable = [t["table_name"] for t in tables
                  if t.get("has_data") and not _sf_csv_path(t, csv_dir).is_file()]
    if unreadable:
        raise SystemExit(f"Table(s) {', '.join(unreadable)}: data file not found.")


def _sf_synthesise(tables: list, rows: int) -> None:
    """--generate-sample: every table gets synthetic rows, whatever data files the source
    names — the same meaning as `ts load databricks --generate-sample` (BL-550 re-review).
    A table may pin its own row count with `rows`. Each table is named on stderr."""
    import tempfile
    gen_dir = Path(tempfile.mkdtemp(prefix="ts_load_gen_"))
    for tbl in tables:
        n = int(tbl.get("rows", rows))
        csv_path = generate_csv(tbl, rows=n, output_dir=gen_dir)
        tbl.update(file=csv_path.name, data_file=str(csv_path), has_data=True)
        typer.echo(f"  NOTICE: {tbl['table_name']} gets {n} SYNTHETIC rows "
                   "(--generate-sample), not source data.", err=True)


@app.command()
def snowflake(
    source: str = typer.Option(..., "--source", "-s", help="Path to CSV directory, download JSON, or manifest JSON"),
    profile: str = typer.Option(..., "--profile", "-p", help="Snowflake profile name from ~/.claude/snowflake-profiles.json"),
    database: str = typer.Option(..., "--database", "-d", help="Target Snowflake database"),
    schema: str = typer.Option(..., "--schema", help="Target Snowflake schema"),
    if_exists: str = typer.Option("error", "--if-exists", help="Action when table exists: error|skip|replace"),
    warehouse: Optional[str] = typer.Option(None, "--warehouse", "-w", help="Warehouse (default: from profile)"),
    role: Optional[str] = typer.Option(None, "--role", "-r", help="Role (default: from profile)"),
    generate_sample: bool = typer.Option(
        False, "--generate-sample",
        help="Insert synthetic rows for every table (required for a schema-only source)"),
    rows: int = typer.Option(100, "--rows", help="Rows to generate per table (with --generate-sample)"),
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
    inferred = infer_schema(source_path, require_data=not generate_sample)

    csv_dir = source_path if source_path.is_dir() else source_path.parent
    if generate_sample:
        _sf_synthesise(inferred["tables"], rows)
    elif inferred["source_type"] == "schema_only":
        raise SystemExit(
            "Source is schema-only (no data files). "
            "Use --generate-sample to generate synthetic data, or provide CSVs."
        )
    _refuse_unreadable_data(inferred["tables"], csv_dir)

    method = sf_profile.get("method", "python")
    if method == "cli":
        table_results = _load_via_cli(sf_profile, inferred["tables"], database,
                                       schema, wh, rl, if_exists, csv_dir)
    else:
        table_results = _load_via_python(sf_profile, inferred["tables"], database,
                                          schema, wh, rl, if_exists, csv_dir)

    for r in table_results:          # source or synthetic rows, as ts load databricks reports
        r["data"] = "synthetic" if generate_sample else "source"
        if generate_sample:
            r["source_file"] = None
    output = {
        "database": database,
        "schema": schema,
        "profile": profile,
        "tables": table_results,
    }
    print(json.dumps(output, indent=2))
