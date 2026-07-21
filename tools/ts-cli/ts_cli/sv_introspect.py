"""Snowflake INFORMATION_SCHEMA → ThoughtSpot tables-spec + tables map.

Pure functions: dicts in, dicts out. No I/O, no network. The command layer
(commands/snowflake.py introspect_cmd) handles the Snowflake query and file
writes.

Codifies ts-convert-from-snowflake-sv Steps 6A–6C: type mapping, tables-spec
assembly for `ts tables create`, and column-gap detection against existing
ThoughtSpot table TMLs.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Snowflake type → ThoughtSpot data_type mapping
# ---------------------------------------------------------------------------
# Source: agents/shared/mappings/ts-snowflake/ts-from-snowflake-rules.md
# "Snowflake Type → ThoughtSpot Type" section.

_TEXT_TYPES = frozenset({"TEXT", "VARCHAR", "CHAR", "STRING"})
_INT_TYPES = frozenset({"INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "BYTEINT"})
_FLOAT_TYPES = frozenset({"FLOAT", "DOUBLE", "REAL", "FLOAT4", "FLOAT8"})
_TIMESTAMP_TYPES = frozenset({
    "DATETIME", "TIMESTAMP", "TIMESTAMP_NTZ", "TIMESTAMP_LTZ", "TIMESTAMP_TZ",
})
_SEMI_STRUCTURED_TYPES = frozenset({"VARIANT", "OBJECT", "ARRAY"})


def map_snowflake_type(
    data_type: str, numeric_scale: int | None = None,
) -> tuple[str, list[str]]:
    """Map a Snowflake column type to a ThoughtSpot data_type.

    Returns (ts_type, warnings) where warnings is a list of advisory strings
    (e.g. VARIANT mapped to VARCHAR — flag for review).
    """
    dt = data_type.upper().strip()
    warnings: list[str] = []

    if dt in _TEXT_TYPES:
        return "VARCHAR", warnings
    if dt in _INT_TYPES:
        return "INT64", warnings
    if dt in _FLOAT_TYPES:
        return "DOUBLE", warnings
    if dt == "BOOLEAN":
        return "BOOL", warnings
    if dt == "DATE":
        return "DATE", warnings
    if dt in _TIMESTAMP_TYPES:
        return "DATE_TIME", warnings

    if dt in ("NUMBER", "DECIMAL", "NUMERIC"):
        if numeric_scale is not None and numeric_scale > 0:
            return "DOUBLE", warnings
        return "INT64", warnings

    if dt in _SEMI_STRUCTURED_TYPES:
        warnings.append(f"{dt} mapped to VARCHAR — review for JSON handling")
        return "VARCHAR", warnings

    if dt == "BINARY" or dt == "VARBINARY":
        warnings.append(f"{dt} mapped to VARCHAR — binary data")
        return "VARCHAR", warnings

    warnings.append(f"unknown Snowflake type '{dt}' — defaulting to VARCHAR")
    return "VARCHAR", warnings


# ---------------------------------------------------------------------------
# Parse table FQNs from parsed SV
# ---------------------------------------------------------------------------

def _split_fqn(fqn: str) -> tuple[str, str, str]:
    """Split a dotted FQN into (database, schema, table).

    Handles quoted identifiers: DB."My Schema"."My Table" → (DB, My Schema, My Table).
    """
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    for ch in fqn:
        if ch == '"':
            in_quote = not in_quote
        elif ch == '.' and not in_quote:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))

    if len(parts) < 3:
        raise ValueError(f"FQN must have at least 3 parts (db.schema.table): '{fqn}'")
    return parts[-3], parts[-2], parts[-1]


def extract_table_locations(
    parsed: dict,
) -> list[dict]:
    """Extract (database, schema, table_name, alias) from parsed SV tables.

    Skips subquery-aliased tables (they don't exist in INFORMATION_SCHEMA).
    """
    results = []
    for t in parsed.get("tables") or []:
        if t.get("is_subquery"):
            continue
        fqn = t.get("fqn", "")
        if not fqn or fqn.count(".") < 2:
            continue
        db, schema, table_name = _split_fqn(fqn)
        results.append({
            "database": db, "schema": schema,
            "table_name": table_name, "alias": t.get("alias", table_name),
        })
    return results


def build_info_schema_query(locations: list[dict]) -> str:
    """Build INFORMATION_SCHEMA.COLUMNS query for the given table locations.

    Groups tables by (database, schema) and generates one query per group,
    UNIONed together.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for loc in locations:
        key = (loc["database"], loc["schema"])
        groups.setdefault(key, []).append(loc["table_name"])

    parts = []
    for (db, schema), table_names in groups.items():
        in_list = ", ".join(f"'{t}'" for t in table_names)
        parts.append(
            f"SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, "
            f"DATA_TYPE, NUMERIC_SCALE, ORDINAL_POSITION "
            f"FROM {db}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME IN ({in_list}) "
            f"ORDER BY TABLE_NAME, ORDINAL_POSITION"
        )
    return "\nUNION ALL\n".join(parts)


# ---------------------------------------------------------------------------
# Tables-spec assembly
# ---------------------------------------------------------------------------

def build_tables_spec(
    info_schema_rows: list[dict],
    locations: list[dict],
    connection_name: str,
) -> tuple[list[dict], list[str]]:
    """Build a tables-spec JSON array from INFORMATION_SCHEMA rows.

    Returns (specs, all_warnings) where specs is the array suitable for
    `ts tables create` (stdin JSON), and all_warnings is a flat list of
    type-mapping warnings.

    info_schema_rows: list of dicts with keys:
        TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME,
        DATA_TYPE, NUMERIC_SCALE, ORDINAL_POSITION
    """
    loc_map = {loc["table_name"]: loc for loc in locations}

    table_cols: dict[str, list[dict]] = {}
    table_meta: dict[str, dict] = {}
    all_warnings: list[str] = []

    for row in info_schema_rows:
        tname = row["TABLE_NAME"]
        if tname not in table_cols:
            table_cols[tname] = []
            table_meta[tname] = {
                "db": row.get("TABLE_CATALOG", ""),
                "schema": row.get("TABLE_SCHEMA", ""),
            }

        scale = row.get("NUMERIC_SCALE")
        if scale is not None:
            try:
                scale = int(scale)
            except (ValueError, TypeError):
                scale = None

        ts_type, warns = map_snowflake_type(row["DATA_TYPE"], scale)
        for w in warns:
            all_warnings.append(f"{tname}.{row['COLUMN_NAME']}: {w}")

        table_cols[tname].append({
            "name": row["COLUMN_NAME"],
            "data_type": ts_type,
        })

    specs = []
    for tname, cols in table_cols.items():
        meta = table_meta[tname]
        loc = loc_map.get(tname, {})
        specs.append({
            "name": tname,
            "db": meta["db"],
            "schema": meta["schema"],
            "db_table": tname,
            "connection_name": connection_name,
            "columns": cols,
        })

    return specs, all_warnings


# ---------------------------------------------------------------------------
# Tables map for build-model
# ---------------------------------------------------------------------------

def build_tables_map(locations: list[dict]) -> dict[str, dict]:
    """Build the alias→{name} map that `ts snowflake build-model --tables` expects.

    GUIDs are added later by the skill after `ts tables create` returns them.
    """
    return {
        loc["alias"]: {"name": loc["table_name"]}
        for loc in locations
    }


# ---------------------------------------------------------------------------
# Column gap detection
# ---------------------------------------------------------------------------

def _sv_referenced_columns(parsed: dict) -> dict[str, set[str]]:
    """Extract columns referenced by the SV per table alias."""
    by_table: dict[str, set[str]] = {}
    for section in ("dimensions", "metrics", "facts"):
        for entry in parsed.get(section) or []:
            table = entry.get("table")
            col = entry.get("column")
            if table and col:
                by_table.setdefault(table, set()).add(col)
    return by_table


def detect_column_gaps(
    parsed: dict,
    ts_columns_by_table: dict[str, list[str]],
) -> dict[str, dict]:
    """Compare SV-referenced columns against ThoughtSpot table columns.

    ts_columns_by_table: {alias: [col_name, ...]} from exported Table TMLs.

    Returns {alias: {status, missing, extra}} where:
      - status: "ok" | "gaps" | "not_found"
      - missing: columns in SV but not in TS table
      - extra: columns in TS table but not in SV (informational)
    """
    sv_cols = _sv_referenced_columns(parsed)
    report: dict[str, dict] = {}

    all_aliases = set(sv_cols) | set(ts_columns_by_table)
    for alias in sorted(all_aliases):
        sv_set = sv_cols.get(alias, set())
        ts_list = ts_columns_by_table.get(alias)
        if ts_list is None:
            report[alias] = {
                "status": "not_found",
                "missing": sorted(sv_set),
                "extra": [],
            }
            continue
        ts_set = set(ts_list)
        missing = sorted(sv_set - ts_set)
        extra = sorted(ts_set - sv_set)
        report[alias] = {
            "status": "gaps" if missing else "ok",
            "missing": missing,
            "extra": extra,
        }

    return report
