"""ts load databricks — provisions table(s) in a Databricks catalog.schema and loads them.

Attaches `databricks` to `load.app` (the publish_planning.py pattern), split from load.py
under the file-size gate. A table with a data file gets that file's own rows; synthetic
rows are inserted only for a schema-only table or with --generate-sample, and each such
table is named on stderr (BL-550 — until 0.212.0 every table got synthetic rows while the
command reported `loaded … (N rows)`). Execution goes through the `databricks` CLI via the
SQL Statement Execution API (the token lives in ~/.databrickscfg, never here). The SQL
builders and the CSV row reader are pure and unit-tested.
"""
from __future__ import annotations

import csv as csv_mod
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

import typer

from ts_cli.commands.load import (
    app, detect_source, generate_csv, infer_schema, sanitise_name,
)

_DBX_PROFILES_PATH = Path.home() / ".claude" / "databricks-profiles.json"


def _load_dbx_profile(profile_name: str) -> dict:
    from ts_cli.profile_ops import get_profile, load_platform_profiles
    profile = get_profile("databricks", profile_name, path=_DBX_PROFILES_PATH)
    if profile is not None:
        return profile
    available = [p.get("name") for p in load_platform_profiles("databricks", path=_DBX_PROFILES_PATH)]
    if not available:
        raise SystemExit(f"No Databricks profiles file at {_DBX_PROFILES_PATH}. "
                         "Run /ts-profile-databricks or create it.")
    raise SystemExit(f"Databricks profile '{profile_name}' not found. "
                     f"Available: {[p.get('name') for p in available]}")


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


# A numeric literal: digits with an optional sign, decimal point and exponent. Anything
# else in a BIGINT/DOUBLE column is refused rather than spliced into the SQL raw, where
# `2024-01-02` would evaluate as arithmetic (2021) and arbitrary text would be injected.
_NUMERIC_LITERAL_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_BOOL_TRUE = ("true", "1", "yes", "t", "y")
_BOOL_FALSE = ("false", "0", "no", "f", "n")


def _dbx_quote(val: str) -> str:
    """Body of a Databricks SQL string literal. Databricks escapes with a backslash:
    a doubled quote is NOT an escape there — `'O''Brien'` is two adjacent literals that
    concatenate to `OBrien` (live-verified on DBSQL 2026.35, 2026-11-08, BL-550)."""
    return str(val).replace("\\", "\\\\").replace("'", "\\'")


def _sql_literal(val: str, dtype: str) -> str:
    """One CSV cell → a Databricks SQL literal for its column type. An empty cell is NULL.
    Raises ValueError for a value that is not a valid literal of a numeric or BOOLEAN type."""
    if val is None or val == "":
        return "NULL"
    if dtype in ("BIGINT", "DOUBLE"):
        v = str(val).strip()
        if not _NUMERIC_LITERAL_RE.fullmatch(v):
            raise ValueError(f"{val!r} is not a {dtype} value")
        return v
    if dtype == "BOOLEAN":
        v = str(val).strip().lower()
        if v in _BOOL_TRUE:
            return "true"
        if v in _BOOL_FALSE:
            return "false"
        raise ValueError(f"{val!r} is not a BOOLEAN value")
    if dtype == "DATE":
        return f"DATE'{_dbx_quote(str(val).strip())}'"
    if dtype == "TIMESTAMP":
        return f"TIMESTAMP'{_dbx_quote(str(val).strip())}'"
    return f"'{_dbx_quote(val)}'"


def _dbx_row_tuple(row: list, columns: list, dtypes: list) -> str:
    """One row → `(lit, lit, ...)`. A ValueError names the offending column."""
    lits = []
    for v, c, t in zip(row, columns, dtypes):
        try:
            lits.append(_sql_literal(v, t))
        except ValueError as e:
            raise ValueError(f"column `{_col_name(c)}`: {e}") from None
    return "(" + ", ".join(lits) + ")"


def _dbx_insert_prefix(fqtn: str, columns: list) -> str:
    collist = ", ".join(f"`{_col_name(c)}`" for c in columns)
    return f"INSERT INTO {fqtn} ({collist}) VALUES "


def build_dbx_insert_sql(fqtn: str, columns: list, rows: list) -> str:
    """INSERT ... VALUES for a batch of rows (row = list of stringified cell values)."""
    dtypes = [dbx_type(_col_type(c)) for c in columns]
    tuples = ", ".join(_dbx_row_tuple(r, columns, dtypes) for r in rows)
    return _dbx_insert_prefix(fqtn, columns) + tuples


# Byte ceiling for one INSERT statement. Deliberately far below the Statement Execution
# API's own limit: it only ever splits a batch into smaller statements, so a wide CSV row
# set cannot produce one statement too large to send. `--batch` still caps the row count.
_DBX_MAX_STATEMENT_BYTES = 1 << 20


def build_dbx_insert_batches(fqtn: str, columns: list, rows, batch: int,
                             max_bytes: int = _DBX_MAX_STATEMENT_BYTES) -> list[str]:
    """All INSERT statements for `rows`: at most `batch` rows and about `max_bytes` each.

    Every row is rendered before anything is returned, so a value that is not a valid
    literal fails here — before the table is created or any row is inserted — with its
    1-based data-row number. One row larger than `max_bytes` still gets its own statement."""
    dtypes = [dbx_type(_col_type(c)) for c in columns]
    prefix = _dbx_insert_prefix(fqtn, columns)
    statements: list[str] = []
    tuples: list[str] = []
    size = len(prefix.encode("utf-8"))
    for i, row in enumerate(rows, 1):
        try:
            t = _dbx_row_tuple(row, columns, dtypes)
        except ValueError as e:
            raise ValueError(f"data row {i}, {e}") from None
        t_bytes = len(t.encode("utf-8")) + 2   # + ", "
        if tuples and (len(tuples) >= batch or size + t_bytes > max_bytes):
            statements.append(prefix + ", ".join(tuples))
            tuples, size = [], len(prefix.encode("utf-8"))
        tuples.append(t)
        size += t_bytes
    if tuples:
        statements.append(prefix + ", ".join(tuples))
    return statements


def _header_index(header: list, columns: list, csv_name: str) -> list[int]:
    """For each schema column, the header position its values come from.

    Matched by name (the header cell, or its sanitised form, equal to the column's `name`
    or `db_column_name`), so a manifest listing columns in another order still lands each
    value in its own column. When the names do not all match, a header of the same width
    is taken positionally, as Snowflake's COPY INTO does; any other shape is refused."""
    by_key: dict[str, int] = {}
    for idx, h in enumerate(header):
        for key in (h.strip(), sanitise_name(h)):
            by_key.setdefault(key, idx)
    index = [next((by_key[k] for k in (c.get("name"), c.get("db_column_name"))
                   if k and k in by_key), None) for c in columns]
    if None not in index and len(set(index)) == len(index):
        return index
    if len(header) == len(columns):
        return list(range(len(columns)))
    raise SystemExit(f"{csv_name}: header has {len(header)} columns and the schema has "
                     f"{len(columns)}, and their names do not match.")


def _read_csv_rows(csv_path: Path, columns: list) -> list[list[str]]:
    """A CSV's data rows, each re-ordered to match `columns` (see `_header_index`).

    Blank lines are skipped; a short row's missing cells become NULL; a row with extra
    non-empty cells beyond the header is refused rather than silently truncated."""
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv_mod.reader(f)
        header = next(reader, None)
        if header is None:
            raise SystemExit(f"CSV file {csv_path} is empty (no header row)")
        index = _header_index(header, columns, csv_path.name)
        width = len(header)
        rows = []
        for line_no, row in enumerate(reader, 2):
            if not row or (len(row) == 1 and width > 1 and not row[0].strip()):
                continue   # a blank (or whitespace-only) line, not an all-NULL row
            if len(row) > width and any(cell.strip() for cell in row[width:]):
                raise SystemExit(f"{csv_path.name} line {line_no}: {len(row)} cells, "
                                 f"header has {width}.")
            rows.append([row[i] if i < len(row) else "" for i in index])
    return rows


def _csv_paths_by_table(source_path: Path) -> dict[str, Path]:
    """table_name → the CSV `infer_schema` read for it (empty for a schema-only source)."""
    _, file_infos = detect_source(source_path)
    return {i["table_name"]: i["csv_path"] for i in file_infos if i.get("csv_path")}


def _dbx_exec(cli_profile: str, warehouse_id: str, statement: str) -> dict:
    """Run one SQL statement via the Databricks Statement Execution API (databricks CLI).

    The request body goes through a 0600 temp file (`--json @file`), not argv: an INSERT
    batch of real rows can exceed the per-argument limit (128 KiB on Linux). It holds row
    data only — the credential stays with the CLI profile."""
    import os
    import tempfile
    import time
    payload = json.dumps({"warehouse_id": warehouse_id, "statement": statement,
                          "wait_timeout": "50s"})
    fd, body_path = tempfile.mkstemp(prefix="ts_dbx_stmt_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        r = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements",
                            "--profile", cli_profile, "--json", f"@{body_path}"],
                           capture_output=True, text=True)
    finally:
        os.unlink(body_path)
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


def _plan_dbx_table(tbl: dict, fqtn: str, csv_paths: dict, generate_sample: bool,
                    rows: int, seed: int, batch: int, gen_dir: Path) -> dict:
    """Decide where one table's rows come from and render its INSERT statements.

    Source rows when the table has a data file; synthetic rows for a schema-only table or
    when `--generate-sample` asks for them. Nothing is executed here, so a bad value
    fails before any table is created."""
    name, cols = tbl["table_name"], tbl["columns"]
    synthetic = generate_sample or not tbl.get("has_data")
    if not synthetic and name not in csv_paths:
        # Never fall back to synthetic rows for a table that has data: that is BL-550.
        raise SystemExit(f"{name}: the source names a data file for this table, but no CSV "
                         "path resolved for it. Nothing was loaded.")
    if synthetic:
        n = int(tbl.get("rows", rows))   # a table may pin its own row count in the manifest
        csv_path = generate_csv(tbl, rows=n, output_dir=gen_dir, seed=seed)
    else:
        csv_path = csv_paths[name]
    data_rows = _read_csv_rows(csv_path, cols)
    try:
        statements = build_dbx_insert_batches(fqtn, cols, data_rows, batch)
    except ValueError as e:
        raise SystemExit(f"{csv_path.name}: {e}. Nothing was loaded.") from None
    return {"name": name, "cols": cols, "statements": statements, "row_count": len(data_rows),
            "synthetic": synthetic, "file": None if synthetic else str(csv_path)}


@app.command()
def databricks(
    source: str = typer.Option(..., "--source", "-s",
                               help="CSV dir, Tableau download JSON, or manifest/schema JSON"),
    profile: str = typer.Option(..., "--profile", "-p", help="Databricks profile name"),
    catalog: Optional[str] = typer.Option(None, "--catalog", help="Override profile catalog"),
    schema: Optional[str] = typer.Option(None, "--schema", help="Override profile schema"),
    generate_sample: bool = typer.Option(
        False, "--generate-sample",
        help="Insert synthetic rows even for tables that have a data file"),
    rows: int = typer.Option(100, "--rows", "-r",
                             help="Synthetic rows per table (schema-only tables, or with --generate-sample)"),
    seed: int = typer.Option(42, "--seed", help="Deterministic synthetic-data seed"),
    batch: int = typer.Option(200, "--batch", help="Max rows per INSERT statement"),
    replace: bool = typer.Option(False, "--replace", help="CREATE OR REPLACE (re-provision an existing table's schema)"),
) -> None:
    """Provision table(s) in a Databricks catalog.schema and load their rows.

    Infers the schema from --source, then CREATE TABLE + batched INSERT via the Databricks
    SQL Statement Execution API (the `databricks` CLI; the token stays in ~/.databrickscfg).
    A table with a data file gets that file's own rows. Synthetic rows are inserted only for
    a schema-only table, or for every table with --generate-sample, and each such table is
    named on stderr. The Databricks half of ts-load-source-data.
    """
    import tempfile
    if batch < 1:
        raise SystemExit("--batch must be at least 1.")
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

    source_path = Path(source)
    tables = infer_schema(source_path)["tables"]
    csv_paths = _csv_paths_by_table(source_path)
    with tempfile.TemporaryDirectory(prefix="dbxload_") as gen_dir:
        plans = [_plan_dbx_table(tbl, f"`{cat}`.`{sch}`.`{tbl['table_name']}`", csv_paths,
                                 generate_sample, rows, seed, batch, Path(gen_dir))
                 for tbl in tables]

    _dbx_exec(cli_profile, warehouse_id, f"CREATE SCHEMA IF NOT EXISTS `{cat}`.`{sch}`")
    results = []
    for plan in plans:
        name = plan["name"]
        fqtn = f"`{cat}`.`{sch}`.`{name}`"
        if plan["synthetic"]:
            why = "--generate-sample" if generate_sample else "no data file (schema-only)"
            typer.echo(f"  NOTICE: {cat}.{sch}.{name} gets {plan['row_count']} SYNTHETIC rows "
                       f"({why}), not source data.", err=True)
        _dbx_exec(cli_profile, warehouse_id, build_dbx_create_sql(fqtn, plan["cols"], replace=replace))
        for statement in plan["statements"]:
            _dbx_exec(cli_profile, warehouse_id, statement)
        kind = "synthetic" if plan["synthetic"] else "source"
        results.append({"table": f"{cat}.{sch}.{name}", "rows": plan["row_count"],
                        "data": kind, "source_file": plan["file"]})
        typer.echo(f"  loaded {cat}.{sch}.{name} ({plan['row_count']} {kind} rows)", err=True)

    print(json.dumps({"loaded": results, "catalog": cat, "schema": sch,
                      "warehouse_id": warehouse_id}, indent=2))
