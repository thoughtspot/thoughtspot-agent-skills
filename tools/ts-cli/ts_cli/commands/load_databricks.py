"""ts load databricks — provisions table(s) in a Databricks catalog.schema and loads them.

Attaches `databricks` to `load.app` (the publish_planning.py pattern), split from load.py
under the file-size gate. A table with a data file gets that file's own rows; synthetic
rows are inserted only with --generate-sample, and each such table is named on stderr
(BL-550 — until 0.212.0 every table got synthetic rows while the command reported
`loaded … (N rows)`). Execution goes through the `databricks` CLI via the SQL Statement
Execution API (the token lives in ~/.databrickscfg, never here). The SQL builders and the
CSV row reader are pure and unit-tested.

Two phases. PLANNING reads every CSV, checks every value against its column type and
renders every statement, so a value Databricks would refuse (a decimal in a BIGINT column,
a 30th of February) stops the run before anything is created. EXECUTION then sends the
statements; what can still fail there (permissions, a warehouse error, an appended-to
table whose columns differ) is reported with the tables and rows already written.
"""
from __future__ import annotations

import csv as csv_mod
import io
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Optional

import typer

from ts_cli.commands.load import app, generate_csv, infer_schema, read_csv_text, sanitise_name
from ts_cli.sql_literal_shapes import is_calendar_date, is_iso_timestamp

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
                     f"Available: {', '.join(str(n) for n in available)}")


def dbx_ident(name: str) -> str:
    """A backtick-quoted Databricks identifier; a backtick inside the name is doubled."""
    return "`" + str(name).replace("`", "``") + "`"


def dbx_fqtn(catalog: str, schema: str, table: str) -> str:
    return ".".join(dbx_ident(p) for p in (catalog, schema, table))


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
        m = re.search(r"\(\s*[0-9]+\s*,\s*([0-9]+)\s*\)", t)
        return "DOUBLE" if (m and int(m.group(1)) > 0) else "BIGINT"
    if t.startswith(("INT", "BIGINT", "SMALLINT", "TINYINT")):
        return "BIGINT"
    return "STRING"


def _col_name(col: dict) -> str:
    return col.get("db_column_name") or col.get("name") or ""


def _col_type(col: dict) -> str:
    return col.get("inferred_type") or col.get("type") or "STRING"


def _col_dbx_type(col: dict) -> str:
    """The column's Databricks type: one planning chose (`dbx_type` key), else mapped."""
    return col.get("dbx_type") or dbx_type(_col_type(col))


def build_dbx_create_sql(fqtn: str, columns: list, replace: bool = False,
                         if_not_exists: bool = True) -> str:
    """CREATE TABLE DDL. Backtick-quotes identifiers and enables Delta **column mapping**
    so source column names with spaces/special chars (e.g. `Order Date`, `Order Id`) are
    preserved 1:1 — Delta otherwise rejects them (DELTA_INVALID_CHARACTERS_IN_COLUMN_NAMES).
    `replace=True` uses CREATE OR REPLACE (drops+recreates to change the schema of an
    already-provisioned table); `if_not_exists=False` a plain CREATE TABLE, which fails on
    an existing table. Live-verified on ps-internal 2026-07-16."""
    if replace:
        verb = "CREATE OR REPLACE TABLE"
    else:
        verb = "CREATE TABLE IF NOT EXISTS" if if_not_exists else "CREATE TABLE"
    cols = ",\n  ".join(f"{dbx_ident(_col_name(c))} {_col_dbx_type(c)}" for c in columns)
    return (f"{verb} {fqtn} (\n  {cols}\n) USING DELTA\n"
            "TBLPROPERTIES ('delta.columnMapping.mode' = 'name', "
            "'delta.minReaderVersion' = '2', 'delta.minWriterVersion' = '5')")


# ASCII digits only — `\d` also matches other scripts' digits. A BIGINT takes an integer and
# nothing else: inference samples the first 1000 rows, so a later `1.5` must be refused, not
# truncated by the warehouse. Anything else in a numeric column is refused rather than
# spliced raw, where `2024-01-02` would evaluate as arithmetic and text would be injected.
_BIGINT_RE = re.compile(r"[+-]?[0-9]+")
_BIGINT_MIN, _BIGINT_MAX = -(2 ** 63), 2 ** 63 - 1
# A Snowflake INTEGER is NUMBER(38,0). A value outside BIGINT moves its column to
# DECIMAL(38,0), which holds it exactly: CAST(9223372036854775808 AS BIGINT) silently wraps
# to -9223372036854775808 on DBSQL 2026.35 (live-verified 2026-11-08), so BIGINT would not.
_DECIMAL_38_0 = "DECIMAL(38,0)"
_DOUBLE_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_BOOL_TRUE = ("true", "1", "yes", "t", "y")
_BOOL_FALSE = ("false", "0", "no", "f", "n")


def _dbx_quote(val: str) -> str:
    """Body of a Databricks SQL string literal. Databricks escapes with a backslash:
    a doubled quote is NOT an escape there — `'O''Brien'` is two adjacent literals that
    concatenate to `OBrien` (live-verified on DBSQL 2026.35, 2026-11-08, BL-550)."""
    return str(val).replace("\\", "\\\\").replace("'", "\\'")


def _is_bigint(v: str) -> bool:
    return bool(_BIGINT_RE.fullmatch(v)) and _BIGINT_MIN <= int(v) <= _BIGINT_MAX


def _is_decimal_38_0(v: str) -> bool:
    return bool(_BIGINT_RE.fullmatch(v)) and len(v.lstrip("+-")) <= 38


def _is_double(v: str) -> bool:
    return bool(_DOUBLE_RE.fullmatch(v)) and math.isfinite(float(v))


# Databricks type → (does this stripped, non-blank value fit it?, its literal).
_TYPED_LITERALS = {
    "BIGINT": (_is_bigint, lambda v: v),
    _DECIMAL_38_0: (_is_decimal_38_0, lambda v: v),
    "DOUBLE": (_is_double, lambda v: v),
    "BOOLEAN": (lambda v: v.lower() in _BOOL_TRUE + _BOOL_FALSE,
                lambda v: "true" if v.lower() in _BOOL_TRUE else "false"),
    "DATE": (is_calendar_date, lambda v: f"DATE'{v}'"),
    "TIMESTAMP": (is_iso_timestamp, lambda v: f"TIMESTAMP'{v}'"),
}


def _typed_literal(v: str, dtype: str) -> str:
    """A non-blank, stripped value of a non-STRING column → its literal, or ValueError."""
    fits, render = _TYPED_LITERALS.get(dtype, (None, None))
    if fits is not None and fits(v):
        return render(v)
    raise ValueError(f"{v!r} is not a {dtype} value")


def _sql_literal(val: str, dtype: str) -> str:
    """One CSV cell → a Databricks SQL literal for its column type. An empty cell is NULL,
    and so is a whitespace-only cell in a non-STRING column. Raises ValueError for a value
    that is not valid for its type, so it fails at planning, not mid-load."""
    if val is None or val == "":
        return "NULL"
    if dtype == "STRING":
        return f"'{_dbx_quote(val)}'"
    v = str(val).strip()
    return "NULL" if v == "" else _typed_literal(v, dtype)


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
    collist = ", ".join(dbx_ident(_col_name(c)) for c in columns)
    return f"INSERT INTO {fqtn} ({collist}) VALUES "


def build_dbx_insert_sql(fqtn: str, columns: list, rows: list) -> str:
    """INSERT ... VALUES for a batch of rows (row = list of stringified cell values)."""
    dtypes = [_col_dbx_type(c) for c in columns]
    tuples = ", ".join(_dbx_row_tuple(r, columns, dtypes) for r in rows)
    return _dbx_insert_prefix(fqtn, columns) + tuples


# Byte ceiling for one INSERT statement. Deliberately far below the Statement Execution
# API's own limit: it only ever splits a batch into smaller statements, so a wide CSV row
# set cannot produce one statement too large to send. `--batch` still caps the row count.
_DBX_MAX_STATEMENT_BYTES = 1 << 20


def _render_batches(fqtn: str, columns: list, rows, batch: int,
                    max_bytes: int = _DBX_MAX_STATEMENT_BYTES) -> list[tuple[str, int]]:
    """(statement, row count) pairs: at most `batch` rows and about `max_bytes` each.

    Every row is rendered before anything is returned, so a value that is not a valid
    literal fails here with its 1-based data-row number. One row larger than `max_bytes`
    still gets its own statement."""
    dtypes = [_col_dbx_type(c) for c in columns]
    prefix = _dbx_insert_prefix(fqtn, columns)
    prefix_bytes = len(prefix.encode("utf-8"))
    out: list[tuple[str, int]] = []
    tuples: list[str] = []
    size = prefix_bytes
    for i, row in enumerate(rows, 1):
        try:
            t = _dbx_row_tuple(row, columns, dtypes)
        except ValueError as e:
            raise ValueError(f"data row {i}, {e}") from None
        t_bytes = len(t.encode("utf-8")) + 2   # + ", "
        if tuples and (len(tuples) >= batch or size + t_bytes > max_bytes):
            out.append((prefix + ", ".join(tuples), len(tuples)))
            tuples, size = [], prefix_bytes
        tuples.append(t)
        size += t_bytes
    if tuples:
        out.append((prefix + ", ".join(tuples), len(tuples)))
    return out


def build_dbx_insert_batches(fqtn: str, columns: list, rows, batch: int,
                             max_bytes: int = _DBX_MAX_STATEMENT_BYTES) -> list[str]:
    """All INSERT statements for `rows` (see `_render_batches`)."""
    return [sql for sql, _ in _render_batches(fqtn, columns, rows, batch, max_bytes)]


_HEADER_PASSES = (
    ("exact", lambda x: x.strip()),
    ("case-insensitive", lambda x: x.strip().casefold()),
    ("sanitised", sanitise_name),
)


def _match_headers(header: list, columns: list, csv_name: str) -> list:
    """Each column's header position by name, or None. Three passes, each over headers no
    earlier pass took: exact names, then case-insensitive, then the sanitised forms of both
    sides (`Order Date` = `Order  Date`). So one header's sanitised form can never shadow
    another header's exact name (`Customer ID` vs `CUSTOMER_ID`). Two free headers equal
    under one pass for one column are refused as ambiguous."""
    index: list = [None] * len(columns)
    taken: set = set()
    for label, key in _HEADER_PASSES:
        for pos, c in enumerate(columns):
            if index[pos] is not None:
                continue
            wanted = {key(k) for k in (c.get("name"), c.get("db_column_name")) if k} - {""}
            hits = [i for i, h in enumerate(header) if i not in taken and key(h) in wanted]
            if len(hits) > 1:
                raise SystemExit(f"{csv_name}: column {c.get('name') or _col_name(c)!r} matches "
                                 f"{len(hits)} headers ({label}): "
                                 f"{', '.join(repr(header[i]) for i in hits)}.")
            if hits:
                index[pos] = hits[0]
                taken.add(hits[0])
    return index


def _header_index(header: list, columns: list, csv_name: str) -> list[int]:
    """For each schema column, the header position its values come from.

    Matched by name (`_match_headers`), so a manifest listing columns in another order still
    lands each value in its own column. When some names do not match, a header of the same
    width is taken positionally, as Snowflake's COPY INTO does — but only if every name that
    DID match sits at its own position. A match that contradicts its position (Cost found
    where Revenue would be read) is refused, never silently swapped."""
    index = _match_headers(header, columns, csv_name)
    if None not in index:
        return index
    if len(header) != len(columns):
        raise SystemExit(f"{csv_name}: header has {len(header)} columns and the schema has "
                         f"{len(columns)}, and their names do not match.")
    clashes = [f"{columns[pos].get('name') or _col_name(columns[pos])} "
               f"(header position {idx + 1}, schema position {pos + 1})"
               for pos, idx in enumerate(index) if idx is not None and idx != pos]
    if clashes:
        raise SystemExit(f"{csv_name}: not every header name matches the schema, and these "
                         f"that do sit at a different position: {'; '.join(clashes)}. Fix the "
                         "header or the schema's column order.")
    return list(range(len(columns)))


def _widen_out_of_range_integers(columns: list, rows: list) -> list:
    """Columns whose BIGINT would not hold every value become DECIMAL(38,0) (see
    `_DECIMAL_38_0`). Returns new column dicts; values that are not integers are left for
    `_sql_literal` to refuse."""
    out = []
    for pos, c in enumerate(columns):
        if _col_dbx_type(c) == "BIGINT" and any(
                _BIGINT_RE.fullmatch(v := r[pos].strip()) and not _BIGINT_MIN <= int(v) <= _BIGINT_MAX
                for r in rows if r[pos].strip()):
            c = {**c, "dbx_type": _DECIMAL_38_0}
        out.append(c)
    return out


def _read_csv_rows(csv_path: Path, columns: list, encoding: str = "utf-8") -> list[list[str]]:
    """A CSV's data rows, each re-ordered to match `columns` (see `_header_index`).

    Decoded strictly (`read_csv_text`). A blank line is skipped when the CSV has more than
    one column; in a one-column CSV it is a NULL value. A short row's missing cells become
    NULL; a row with extra non-empty cells beyond the header is refused."""
    reader = csv_mod.reader(io.StringIO(read_csv_text(csv_path, encoding), newline=""))
    header = next(reader, None)
    if header is None:
        raise SystemExit(f"CSV file {csv_path} is empty (no header row)")
    index = _header_index(header, columns, csv_path.name)
    width = len(header)
    rows = []
    for row in reader:
        if width > 1 and (not row or (len(row) == 1 and not row[0].strip())):
            continue
        if len(row) > width and any(cell.strip() for cell in row[width:]):
            raise SystemExit(f"{csv_path.name} line {reader.line_num}: {len(row)} cells, "
                             f"header has {width}.")
        rows.append([row[i] if i < len(row) else "" for i in index])
    return rows


def _check_names(tables: list) -> None:
    """Refuse, before anything runs, names Databricks would collide on. Identifiers are
    case-insensitive there, so `order-items.csv` and `order_items.csv` (both ORDER_ITEMS)
    are one table, and `Order Id` / `order_id` one column."""
    seen: dict[str, str] = {}
    for t in tables:
        if not sanitise_name(t["table_name"]):
            raise SystemExit(f"{t.get('file') or 'A table'}: its table name "
                             f"{t['table_name']!r} has no letters or digits. Rename it.")
        key = t["table_name"].lower()
        if key in seen:
            raise SystemExit(f"Two tables both load as {t['table_name']}: "
                             f"{seen[key]} and {t.get('file') or t['table_name']}. Rename one.")
        seen[key] = t.get("file") or t["table_name"]
        cols: dict[str, str] = {}
        for c in t["columns"]:
            name = _col_name(c)
            if not name.strip():
                raise SystemExit(f"Table {t['table_name']}: a column has no name.")
            if name.lower() in cols:
                raise SystemExit(f"Table {t['table_name']}: columns {cols[name.lower()]!r} and "
                                 f"{c.get('name') or name!r} both load as {name}. Rename one.")
            cols[name.lower()] = c.get("name") or name


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


def _existing_tables(cli_profile: str, warehouse_id: str, catalog: str, schema: str,
                     wanted: list) -> list:
    """Which of `wanted` already exist as tables in catalog.schema (case-insensitive).

    `SHOW TABLES` returns [database, tableName, isTemporary] with names lower-cased
    (live-verified 2026-11-08); a temporary view does not block CREATE TABLE. A result
    split into chunks is refused rather than read partly."""
    data = _dbx_exec(cli_profile, warehouse_id,
                     f"SHOW TABLES IN {dbx_ident(catalog)}.{dbx_ident(schema)}")
    result = data.get("result") or {}
    if result.get("next_chunk_index") is not None:
        raise SystemExit(f"{catalog}.{schema} lists too many tables to check whether "
                         f"{', '.join(wanted)} already exist. Check them yourself, then re-run "
                         "with --if-exists append (keeps existing rows) or --if-exists replace "
                         "(drops them), or load into a schema with fewer tables.")
    have = {str(r[1]).lower() for r in result.get("data_array") or []
            if len(r) > 2 and str(r[2]).lower() != "true"}
    return [w for w in wanted if w.lower() in have]


def _plan_dbx_table(tbl: dict, fqtn: str, generate_sample: bool, rows: int, seed: int,
                    batch: int, gen_dir: Path, encoding: str = "utf-8") -> dict:
    """Decide where one table's rows come from and render its INSERT statements.

    Source rows from the table's own `data_file` (carried out of inference, never looked
    up by name); synthetic rows only with `--generate-sample`. Nothing is executed."""
    name, cols = tbl["table_name"], tbl["columns"]
    if generate_sample:
        n = int(tbl.get("rows", rows))   # a table may pin its own row count in the manifest
        csv_path = generate_csv(tbl, rows=n, output_dir=gen_dir, seed=seed)
        data_rows = _read_csv_rows(csv_path, cols)
    else:
        if not tbl.get("data_file"):
            # Never fall back to synthetic rows for a table that should have data: BL-550.
            raise SystemExit(f"{name}: no data file resolved for this table. Nothing was loaded.")
        csv_path = Path(tbl["data_file"])
        data_rows = _read_csv_rows(csv_path, cols, encoding)
    cols = _widen_out_of_range_integers(cols, data_rows)
    try:
        batches = _render_batches(fqtn, cols, data_rows, batch)
    except ValueError as e:
        raise SystemExit(f"{csv_path.name}: {e}. Nothing was loaded.") from None
    return {"name": name, "cols": cols, "batches": batches, "row_count": len(data_rows),
            "synthetic": generate_sample, "file": None if generate_sample else str(csv_path)}


def _resolve_if_exists(if_exists: Optional[str], replace: bool) -> str:
    if if_exists not in (None, "error", "append", "replace"):
        raise SystemExit("--if-exists must be one of: error, append, replace")
    if replace and if_exists not in (None, "replace"):
        raise SystemExit(f"--replace conflicts with --if-exists {if_exists}.")
    return "replace" if replace else (if_exists or "error")


def _delta_version(cli_profile: str, warehouse_id: str, fqtn: str) -> Optional[str]:
    """The table's current Delta version (`DESCRIBE HISTORY … LIMIT 1` puts it first,
    live-verified 2026-11-08), recorded before appending so a failure can name the version
    to restore. None when it cannot be read; the advice then points at the history."""
    try:
        rows = (_dbx_exec(cli_profile, warehouse_id, f"DESCRIBE HISTORY {fqtn} LIMIT 1")
                .get("result") or {}).get("data_array") or []
        return str(rows[0][0]) if rows and rows[0] else None
    except (SystemExit, Exception):
        return None


def _recovery_advice(p: dict, cat: str, sch: str) -> str:
    """How to undo one table's part of a failed load. A table this run created can simply
    be reloaded with --if-exists replace. A table that existed before an append must NOT
    be: replace would drop the rows it held before the load."""
    name = f"{cat}.{sch}.{p['table']}"
    if not p.get("pre_existing"):
        return (f"{name}: created by this run, {p['inserted']} of {p['of']} rows inserted — "
                "re-run with --if-exists replace to reload it.")
    if p["inserted"] == 0:
        return (f"{name}: existed before this run and no rows were appended, so it is "
                "unchanged. Do not re-run with --if-exists replace: it would drop its rows.")
    fq = dbx_fqtn(cat, sch, p["table"])
    if p.get("version") is not None:
        undo = f"RESTORE TABLE {fq} TO VERSION AS OF {p['version']}"
    else:
        undo = f"find the version before this load with DESCRIBE HISTORY {fq}, then RESTORE TABLE"
    return (f"{name}: existed before this run; {p['inserted']} of {p['of']} rows were appended. "
            f"To undo, {undo}, or DELETE the appended rows. Do not re-run with "
            "--if-exists replace: it would drop the rows that were there before.")


def _report_partial(progress: list, cat: str, sch: str) -> None:
    """After an execution failure: what is already in Databricks, and how to recover."""
    if not progress:
        typer.echo("  Load stopped before any table was written.", err=True)
        return
    typer.echo("  Load stopped part-way. Already written:", err=True)
    for p in progress:
        typer.echo(f"    {_recovery_advice(p, cat, sch)}", err=True)


def _execute(plans: list, cli_profile: str, warehouse_id: str, cat: str, sch: str,
             mode: str, pre_existing: frozenset = frozenset()) -> list:
    results, progress = [], []
    try:
        for plan in plans:
            name = plan["name"]
            fqtn = dbx_fqtn(cat, sch, name)
            if plan["synthetic"]:
                typer.echo(f"  NOTICE: {cat}.{sch}.{name} gets {plan['row_count']} SYNTHETIC "
                           "rows (--generate-sample), not source data.", err=True)
            existed = mode == "append" and name.lower() in pre_existing
            version = _delta_version(cli_profile, warehouse_id, fqtn) if existed else None
            _dbx_exec(cli_profile, warehouse_id, build_dbx_create_sql(
                fqtn, plan["cols"], replace=(mode == "replace"),
                if_not_exists=(mode == "append")))
            entry = {"table": name, "inserted": 0, "of": plan["row_count"],
                     "pre_existing": existed, "version": version}
            progress.append(entry)
            for sql, n in plan["batches"]:
                _dbx_exec(cli_profile, warehouse_id, sql)
                entry["inserted"] += n
            kind = "synthetic" if plan["synthetic"] else "source"
            results.append({"table": f"{cat}.{sch}.{name}", "rows": entry["inserted"],
                            "data": kind, "source_file": plan["file"]})
            typer.echo(f"  loaded {cat}.{sch}.{name} ({entry['inserted']} {kind} rows)", err=True)
    except (SystemExit, Exception):
        _report_partial(progress, cat, sch)
        raise
    return results


def _dbx_target(profile: str, catalog: Optional[str], schema: Optional[str]) -> tuple:
    """(cli_profile, warehouse_id, catalog, schema) from the profile and the overrides."""
    prof = _load_dbx_profile(profile)
    http_path = prof.get("sql_warehouse_http_path", "")
    if not http_path:
        raise SystemExit("Profile has no sql_warehouse_http_path.")
    cat = catalog or prof.get("catalog")
    sch = schema or prof.get("schema")
    if not cat or not sch:
        raise SystemExit("catalog and schema required (profile or --catalog/--schema).")
    return prof.get("dbx_profile") or profile, http_path.rstrip("/").split("/")[-1], cat, sch


def _refuse_tables_without_data(tables: list, generate_sample: bool) -> None:
    """A table with no data file is refused unless synthetic rows were asked for — the same
    answer `ts load snowflake` gives a schema-only source."""
    no_data = [t["table_name"] for t in tables if not t.get("has_data")]
    if no_data and not generate_sample:
        raise SystemExit(f"No data file for {', '.join(no_data)}. Use --generate-sample to "
                         "insert synthetic rows, or provide CSVs.")


@app.command()
def databricks(
    source: str = typer.Option(..., "--source", "-s",
                               help="CSV dir, Tableau download JSON, manifest JSON, or `ts load infer` output"),
    profile: str = typer.Option(..., "--profile", "-p", help="Databricks profile name"),
    catalog: Optional[str] = typer.Option(None, "--catalog", help="Override profile catalog"),
    schema: Optional[str] = typer.Option(None, "--schema", help="Override profile schema"),
    generate_sample: bool = typer.Option(
        False, "--generate-sample",
        help="Insert synthetic rows for every table (required for a table with no data file)"),
    rows: int = typer.Option(100, "--rows", "-r", help="Synthetic rows per table (with --generate-sample)"),
    seed: int = typer.Option(42, "--seed", help="Deterministic synthetic-data seed"),
    batch: int = typer.Option(200, "--batch", help="Max rows per INSERT statement"),
    if_exists: Optional[str] = typer.Option(
        None, "--if-exists", help="When a table exists: error (default) | append | replace"),
    replace: bool = typer.Option(False, "--replace", help="Alias for --if-exists replace"),
    encoding: str = typer.Option("utf-8", "--encoding",
                                 help="CSV text encoding, decoded strictly (e.g. cp1252)"),
) -> None:
    """Provision table(s) in a Databricks catalog.schema and load their rows.

    Infers the schema from --source, then CREATE TABLE + batched INSERT via the Databricks
    SQL Statement Execution API (the `databricks` CLI; the token stays in ~/.databrickscfg).
    A table with a data file gets that file's own rows. A table without one is refused
    unless --generate-sample, which inserts synthetic rows for every table and names each
    on stderr. Before anything is created, every value is checked against its column type
    and colliding names and (by default) existing tables are refused; a failure while
    executing prints what was written and how to undo it. The Databricks half of
    ts-load-source-data.
    """
    import tempfile
    if batch < 1:
        raise SystemExit("--batch must be at least 1.")
    mode = _resolve_if_exists(if_exists, replace)
    cli_profile, warehouse_id, cat, sch = _dbx_target(profile, catalog, schema)
    # --generate-sample reads no source rows, so a data file need not exist (BL-550 re-review).
    tables = infer_schema(Path(source), encoding=encoding,
                          require_data=not generate_sample)["tables"]
    _check_names(tables)
    _refuse_tables_without_data(tables, generate_sample)
    with tempfile.TemporaryDirectory(prefix="dbxload_") as gen_dir:
        plans = [_plan_dbx_table(tbl, dbx_fqtn(cat, sch, tbl["table_name"]), generate_sample,
                                 rows, seed, batch, Path(gen_dir), encoding)
                 for tbl in tables]

    _dbx_exec(cli_profile, warehouse_id,
              f"CREATE SCHEMA IF NOT EXISTS {dbx_ident(cat)}.{dbx_ident(sch)}")
    clash: list = []
    if mode in ("error", "append"):
        clash = _existing_tables(cli_profile, warehouse_id, cat, sch, [p["name"] for p in plans])
        if clash and mode == "error":
            raise SystemExit(f"Table(s) already exist in {cat}.{sch}: {', '.join(clash)}. "
                             "Use --if-exists append or --if-exists replace. Nothing was loaded.")
    results = _execute(plans, cli_profile, warehouse_id, cat, sch, mode,
                       frozenset(c.lower() for c in clash))
    print(json.dumps({"loaded": results, "catalog": cat, "schema": sch,
                      "warehouse_id": warehouse_id}, indent=2))
