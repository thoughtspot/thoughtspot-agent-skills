"""Pure builders: warehouse SQL, ThoughtSpot TML and AgentQL statements for one run.

No I/O here, so every string a run sends anywhere is unit-tested.

Naming. Every object a run creates carries the run stamp, so a run can never collide
with — or clean up — an object it did not create:

- warehouse table   ``ZZ_FIDELITY_<FIXTURE>_<stamp>``
- ThoughtSpot Table ``ZZ_FIDELITY_<FIXTURE>_<stamp>_TABLE_DELETE_ME``
- ThoughtSpot Model ``ZZ_FIDELITY_<FIXTURE>_<stamp>_DELETE_ME``
"""
from __future__ import annotations

import re
import secrets
import time
from typing import Any, Optional

PREFIX = "ZZ_FIDELITY_"
SUFFIX = "_DELETE_ME"
ORPHAN_PATTERN = f"{PREFIX}%{SUFFIX}"


IDENT = re.compile(r"^[A-Z_][A-Z0-9_$]*$")

# Warehouses a fixture can be loaded into. ``snowflake`` is the default (M0, M1);
# ``databricks`` is M2. The dialect decides literal syntax, session statements and how a
# table's existence is checked — nothing else in a run depends on it.
WAREHOUSES = ("snowflake", "databricks")


def warehouse_of(fixture: dict) -> str:
    wh = fixture.get("warehouse", "snowflake")
    if wh not in WAREHOUSES:
        raise ValueError(f"fixture warehouse must be one of {WAREHOUSES}, got {wh!r}")
    return wh


def wh_type(col: dict) -> str:
    """A column's warehouse type: ``wh_type``, or the M0/M1 spelling ``sf_type``."""
    return col.get("wh_type") or col["sf_type"]


def run_stamp(now: Optional[float] = None, suffix: Optional[str] = None) -> str:
    """UTC timestamp plus a random suffix, so two runs started in the same second (or a
    stale object from an earlier run) can never share a name with this run's objects."""
    ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now if now is not None else time.time()))
    return f"{ts}_{suffix if suffix is not None else secrets.token_hex(3).upper()}"


def check_identifier(value: str, what: str) -> str:
    """Database / schema names are interpolated into SQL, so only plain unquoted
    Snowflake identifiers are accepted."""
    if not IDENT.fullmatch(value or ""):
        raise ValueError(f"{what} {value!r} must match {IDENT.pattern} (plain upper-case identifier)")
    return value


def object_names(fixture_name: str, stamp: str) -> dict[str, str]:
    base = f"{PREFIX}{re.sub(r'[^A-Za-z0-9]', '_', fixture_name).upper()}_{stamp}"
    return {"warehouse_table": base, "ts_table": f"{base}_TABLE{SUFFIX}",
            "ts_model": f"{base}{SUFFIX}"}


def formula_name(case_id: str) -> str:
    return "f_" + re.sub(r"[^A-Za-z0-9]", "_", case_id)


# -- warehouse SQL --------------------------------------------------------------------

def sql_literal(value: Any, sf_type: str, dialect: str = "snowflake") -> str:
    if value is None:
        return "NULL"
    t = sf_type.upper()
    if t.startswith(("VARCHAR", "STRING", "TEXT", "CHAR")):
        body = str(value).replace("\\", "\\\\")
        # Databricks reads a backslash escape inside '...'; Snowflake doubles the quote.
        body = body.replace("'", "\\'") if dialect == "databricks" else body.replace("'", "''")
        return "'" + body + "'"
    if t == "DATE":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
            raise ValueError(f"DATE value must be YYYY-MM-DD, got {value!r}")
        return f"'{value}'::DATE"
    if t.startswith("TIMESTAMP"):
        # 'YYYY-MM-DD HH:MM:SS[.fff]' plus, for TIMESTAMP_TZ, an offset (' +05:30').
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?(?: [+-]\d{2}:\d{2})?",
                            str(value)):
            raise ValueError(f"{sf_type} value must be 'YYYY-MM-DD HH:MM:SS[ +HH:MM]', "
                             f"got {value!r}")
        return f"'{value}'::{t}"
    if t.startswith("BOOLEAN"):
        return "TRUE" if value else "FALSE"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{sf_type} value must be a number, got {value!r}")
    return repr(value)


def fq(database: str, schema: str, table: str) -> str:
    for v, what in ((database, "database"), (schema, "schema"), (table, "table")):
        check_identifier(v, what)
    return f"{database}.{schema}.{table}"


def create_table_sql(fixture: dict, fq_table: str) -> str:
    """CREATE TABLE (never OR REPLACE: a name clash must fail, not clobber)."""
    cols = ",\n  ".join(f"{c['name']} {wh_type(c)}" for c in fixture["columns"])
    return f"CREATE TABLE {fq_table} (\n  {cols}\n)"


def insert_rows_sql(fixture: dict, fq_table: str) -> str:
    cols = fixture["columns"]
    dialect = warehouse_of(fixture)
    names = ", ".join(c["name"] for c in cols)
    rows = ",\n  ".join(
        "(" + ", ".join(sql_literal(r.get(c["name"]), wh_type(c), dialect) for c in cols) + ")"
        for r in fixture["rows"])
    return f"INSERT INTO {fq_table} ({names}) VALUES\n  {rows}"


# Databricks SQL-warehouse session parameters the harness may set. A SQL warehouse accepts
# only a short allowlist (ANSI_MODE, TIMEZONE, …); anything else is an authoring error.
DATABRICKS_SESSION = {"ANSI_MODE": "ansi_mode", "TIMEZONE": "timezone",
                      "LEGACY_TIME_PARSER_POLICY": "legacy_time_parser_policy"}


def session_sql(fixture: dict) -> list[str]:
    dialect = warehouse_of(fixture)
    out = []
    for k, v in (fixture.get("session") or {}).items():
        if not re.fullmatch(r"[A-Z_]+", k):
            raise ValueError(f"bad session parameter name {k!r}")
        if dialect == "databricks":
            if k not in DATABRICKS_SESSION:
                raise ValueError(f"Databricks session parameter {k!r} is not one of "
                                 f"{sorted(DATABRICKS_SESSION)}")
            if isinstance(v, bool):
                val = "true" if v else "false"
            elif isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_/+:-]+", v):
                val = "'" + v + "'"
            else:
                raise ValueError(f"session parameter {k} must be a boolean or a plain "
                                 f"string, got {v!r}")
            # The time zone has its own statement: `SET timezone = 'UTC'` is rejected by a SQL
            # warehouse ("Unsupported configuration", observed 2026-10-07).
            out.append(f"SET TIME ZONE {val}" if k == "TIMEZONE"
                       else f"SET {DATABRICKS_SESSION[k]} = {val}")
            continue
        if isinstance(v, str):
            val = "'" + v.replace("\\", "\\\\").replace("'", "''") + "'"
        elif isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"session parameter {k} must be a string or an integer, got {v!r}")
        else:
            val = str(v)
        out.append(f"ALTER SESSION SET {k} = {val}")
    return out


def session_readback_sql(fixture: dict) -> list[tuple[str, str]]:
    """(parameter, statement) pairs that read back each pinned session value, so the run
    header records what the warehouse actually ran under, not what was asked for."""
    if warehouse_of(fixture) == "databricks":
        return [(k, f"SET {DATABRICKS_SESSION[k]}") for k in (fixture.get("session") or {})]
    return [(k, f"SHOW PARAMETERS LIKE '{k}' IN SESSION") for k in (fixture.get("session") or {})]


def oracle_sql(case: dict, fixture: dict, fq_table: str, only_key: Any = None) -> str:
    """The source formula evaluated in the warehouse, keyed like the ThoughtSpot query."""
    expr = case["source_formula"]
    if case["role"] == "aggregate":
        k = case["group_by"]
        where = f" WHERE {k} = {sql_literal(only_key, _sf_type(fixture, k), warehouse_of(fixture))}" \
            if only_key is not None else ""
        return f"SELECT {k} AS K, ({expr}) AS V FROM {fq_table}{where} GROUP BY {k} ORDER BY {k}"
    k = fixture["key"]
    where = f" WHERE {k} = {sql_literal(only_key, _sf_type(fixture, k), warehouse_of(fixture))}" \
        if only_key is not None else ""
    return f"SELECT {k} AS K, ({expr}) AS V FROM {fq_table}{where} ORDER BY {k}"


def _sf_type(fixture: dict, col: str) -> str:
    return next(wh_type(c) for c in fixture["columns"] if c["name"] == col)


def key_values(case: dict, fixture: dict) -> list[Any]:
    k = case["group_by"] if case["role"] == "aggregate" else fixture["key"]
    vals = {r.get(k) for r in fixture["rows"]}
    return sorted(vals, key=lambda v: (v is None, not isinstance(v, (int, float)),
                                       v if isinstance(v, (int, float)) else 0, str(v)))


# -- ThoughtSpot TML ---------------------------------------------------------------

def table_tml(fixture: dict, names: dict, connection: str, database: str, schema: str) -> dict:
    cols = []
    for c in fixture["columns"]:
        props: dict[str, Any] = {"column_type": c["column_type"]}
        if c["column_type"] == "MEASURE":
            props["aggregation"] = "SUM"
        cols.append({"name": c["name"], "db_column_name": c["name"], "properties": props,
                     "db_column_properties": {"data_type": c["ts_type"]}})
    db_table = names["warehouse_table"]
    if warehouse_of(fixture) == "databricks":
        # Unity Catalog stores catalog, schema and table names in lower case; register them
        # as the catalog spells them (the connection's existing tables do the same).
        database, schema, db_table = database.lower(), schema.lower(), db_table.lower()
    return {"table": {"name": names["ts_table"], "db": database, "schema": schema,
                      "db_table": db_table,
                      "connection": {"name": connection}, "columns": cols}}


def column_context(fixture: dict, ts_table: str) -> list[dict]:
    """``--columns`` for the translator: the fixture's columns on the run's Table."""
    return [{"source": c["name"], "table": ts_table, "column": c["name"],
             "data_type": c["ts_type"], "column_type": c["column_type"],
             "key": c["name"] == fixture["key"]} for c in fixture["columns"]]


def model_tml(fixture: dict, names: dict, formulas: list[tuple[str, str, str]]) -> dict:
    """A Model over the one Table: every physical column plus ``formulas`` (name, expr, role).

    ``formulas[]`` and ``columns[]`` entries come from the translator's own
    ``formula_tml_entries`` so the harness emits exactly what ``ts formula translate`` does.
    """
    from ts_cli.formula_translate.engine import formula_tml_entries

    t = names["ts_table"]
    cols: list[dict] = []
    for c in fixture["columns"]:
        props: dict[str, Any] = {"column_type": c["column_type"]}
        if c["column_type"] == "MEASURE":
            props["aggregation"] = "SUM"
        cols.append({"name": c["name"], "column_id": f"{t}::{c['name']}", "properties": props})
    fdefs = []
    for name, expr, role in formulas:
        f, col = formula_tml_entries(name, expr, role)
        fdefs.append(f)
        cols.append(col)
    model: dict[str, Any] = {"name": names["ts_model"],
                             "description": "Scratch Model made by tools/formula-fidelity. "
                                            "Safe to delete.",
                             "model_tables": [{"name": t}], "columns": cols}
    if fdefs:
        model["formulas"] = fdefs
    return {"model": model}


# -- AgentQL -----------------------------------------------------------------------

def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def agentql_statement(model: str, fname: str, key_col: str, role: str,
                      wrapper: Optional[str], only_key: Any = None, limit: int = 1000) -> str:
    """One formula and one key column, nothing else (the 2026-10-06 GROUP BY trap)."""
    k = f'"t1".{_q(key_col)}'
    f = f'"t1".{_q(fname)}'
    where = ""
    if only_key is not None:
        lit = str(only_key) if isinstance(only_key, (int, float)) and not isinstance(only_key, bool) \
            else "'" + str(only_key).replace("'", "''") + "'"
        where = f" WHERE {k} = {lit}"
    if role == "aggregate":
        sel = f'SELECT {k} AS "k", {wrapper or "AGG"}({f}) AS "v" FROM {_q(model)} AS "t1"'
        return f"{sel}{where} GROUP BY {k} LIMIT {int(limit)}"
    sel = f'SELECT {k} AS "k", {f} AS "v" FROM {_q(model)} AS "t1"'
    return f"{sel}{where} GROUP BY {k}, {f} LIMIT {int(limit)}"
