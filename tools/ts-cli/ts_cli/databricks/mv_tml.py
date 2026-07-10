"""Table TML assembly and TML-invariant validation for Databricks conversions.

Pure functions: dicts in, dicts out. No I/O, no network, stdlib only —
Genie-vendorable (BL-063 PR 5).

Type mapping is agents/shared/mappings/ts-databricks/ts-from-databricks-rules.md
(§Data Type Mapping) encoded as data — extend doc and map together, never one alone.
"""
from __future__ import annotations

_DBX_TYPE_MAP = {
    "string": "VARCHAR", "varchar": "VARCHAR", "char": "VARCHAR",
    "bigint": "INT64", "int": "INT64", "smallint": "INT64", "tinyint": "INT64",
    "double": "DOUBLE", "float": "DOUBLE", "decimal": "DOUBLE",
    "boolean": "BOOL",
    "date": "DATE",
    "timestamp": "DATETIME", "timestamp_ntz": "DATETIME",
}
_DBX_OMIT_TYPES = {"binary", "array", "map", "struct"}
_NUMERIC_TS_TYPES = {"INT64", "DOUBLE"}


def map_dbx_type(dbx_type: str) -> str | None:
    base = dbx_type.strip().lower().split("(")[0].split("<")[0].strip()
    if base in _DBX_OMIT_TYPES:
        return None
    if base in _DBX_TYPE_MAP:
        return _DBX_TYPE_MAP[base]
    raise ValueError(
        f"unmapped Databricks type '{dbx_type}' — no ThoughtSpot data_type in "
        f"ts-from-databricks-rules.md (Data Type Mapping); extend the doc and "
        f"_DBX_TYPE_MAP together")


def build_table_tml(alias_info: dict, connection_name: str) -> tuple[dict, list[str]]:
    for field in ("name", "db", "schema", "db_table", "columns"):
        if not alias_info.get(field):
            raise ValueError(
                f"table entry '{alias_info.get('name', '?')}' with create: true "
                f"requires '{field}'")
    notes: list[str] = []
    columns = []
    for col in alias_info["columns"]:
        dbx_type = col.get("dbx_type")
        if not dbx_type:
            raise ValueError(
                f"table '{alias_info['name']}' column "
                f"'{col.get('name', '?')}' is missing 'dbx_type'")
        ts_type = map_dbx_type(dbx_type)
        if ts_type is None:
            notes.append(
                f"column '{col['name']}' omitted: Databricks type "
                f"'{dbx_type}' is not supported in ThoughtSpot")
            continue
        column_type = col.get("column_type") or (
            "MEASURE" if ts_type in _NUMERIC_TS_TYPES else "ATTRIBUTE")
        props = {"column_type": column_type}
        if column_type == "MEASURE":
            props["aggregation"] = col.get("aggregation") or "SUM"
        columns.append({
            "name": col["name"],
            "db_column_name": col["name"],
            "properties": props,
            "db_column_properties": {"data_type": ts_type},
        })
    table = {
        "name": alias_info["name"],
        "db": alias_info["db"],
        "schema": alias_info["schema"],
        "db_table": alias_info["db_table"],
        "connection": {"name": connection_name},
        "columns": columns,
    }
    return {"table": table}, notes


def validate_tml_invariants(doc: dict) -> list[str]:
    """The two hard invariants ts_cli.tml_lint.lint_tml does NOT check.

    Everything else (guid nesting, formula_id pairing, aggregation in
    formulas[], I4/I5/I8) belongs to lint_tml — call both.
    """
    findings: list[str] = []
    table = doc.get("table")
    if isinstance(table, dict):
        for col in table.get("columns") or []:
            if not col.get("db_column_name"):
                findings.append(
                    f"table column '{col.get('name', '?')}' is missing "
                    f"db_column_name (required even when equal to name)")
        conn = table.get("connection")
        if isinstance(conn, dict) and "fqn" in conn:
            findings.append(
                "connection block must contain name: only — remove fqn: "
                "(fqn inside connection: causes silent import failures)")
    return findings
