"""Unit tests for _merge_tables() in ts_cli/commands/connections.py.

Tests verify the merge strategy:
  - Existing tables are preserved unchanged
  - New tables are inserted into the correct database/schema
  - New databases and schemas are created if missing
  - Duplicate column names are not added twice
No live ThoughtSpot connection required.
"""
from ts_cli.commands.connections import _merge_tables


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_fetch_response(databases: list) -> dict:
    """Wrap a databases list in the fetchConnection response shape."""
    return {"dataWarehouseInfo": {"databases": databases}}


def make_db(name: str, schemas: list) -> dict:
    return {"name": name, "isAutoCreated": False, "schemas": schemas}


def make_schema(name: str, tables: list) -> dict:
    return {"name": name, "tables": tables}


def make_existing_table(name: str, columns: list, table_type: str = "TABLE") -> dict:
    return {
        "name": name,
        "type": table_type,
        "selected": True,
        "linked": True,
        "columns": [{"name": c, "type": "VARCHAR", "selected": True, "isLinkedActive": True}
                    for c in columns],
    }


def make_new_table_entry(db: str, schema: str, table: str, columns: list,
                          table_type: str = "TABLE") -> dict:
    return {
        "db": db,
        "schema": schema,
        "table": table,
        "type": table_type,
        "columns": [{"name": c, "type": "VARCHAR"} for c in columns],
    }


# ---------------------------------------------------------------------------
# Empty fetch response (first run / v1 unavailable)
# ---------------------------------------------------------------------------

class TestEmptyFetch:
    def test_new_table_into_empty_hierarchy(self):
        result = _merge_tables({}, [
            make_new_table_entry("MY_DB", "MY_SCHEMA", "MY_TABLE", ["ID", "NAME"]),
        ])
        assert len(result) == 1
        db = result[0]
        assert db["name"] == "MY_DB"
        schema = db["schemas"][0]
        assert schema["name"] == "MY_SCHEMA"
        table = schema["tables"][0]
        assert table["name"] == "MY_TABLE"
        assert table["selected"] is True
        assert table["linked"] is True
        col_names = [c["name"] for c in table["columns"]]
        assert col_names == ["ID", "NAME"]

    def test_multiple_tables_multiple_schemas(self):
        new_tables = [
            make_new_table_entry("DB", "SCHEMA_A", "TABLE_1", ["ID"]),
            make_new_table_entry("DB", "SCHEMA_B", "TABLE_2", ["ID"]),
        ]
        result = _merge_tables({}, new_tables)
        assert len(result) == 1  # one DB
        schema_names = {s["name"] for s in result[0]["schemas"]}
        assert "SCHEMA_A" in schema_names
        assert "SCHEMA_B" in schema_names


# ---------------------------------------------------------------------------
# Existing tables are preserved unchanged
# ---------------------------------------------------------------------------

class TestPreservesExisting:
    def test_existing_table_not_modified(self):
        fetch = make_fetch_response([
            make_db("DB", [
                make_schema("SCH", [
                    make_existing_table("EXISTING_TABLE", ["COL_A", "COL_B"]),
                ])
            ])
        ])
        result = _merge_tables(fetch, [
            make_new_table_entry("DB", "SCH", "NEW_TABLE", ["COL_X"]),
        ])
        db = result[0]
        schema = db["schemas"][0]
        table_names = {t["name"] for t in schema["tables"]}
        assert "EXISTING_TABLE" in table_names
        assert "NEW_TABLE" in table_names

    def test_existing_table_columns_preserved(self):
        fetch = make_fetch_response([
            make_db("DB", [
                make_schema("SCH", [
                    make_existing_table("T", ["OLD_COL"]),
                ])
            ])
        ])
        result = _merge_tables(fetch, [
            make_new_table_entry("DB", "SCH", "NEW_TABLE", ["NEW_COL"]),
        ])
        schema = result[0]["schemas"][0]
        existing = next(t for t in schema["tables"] if t["name"] == "T")
        col_names = [c["name"] for c in existing["columns"]]
        assert col_names == ["OLD_COL"]


# ---------------------------------------------------------------------------
# New columns appended to existing tables (no duplicates)
# ---------------------------------------------------------------------------

class TestColumnMerge:
    def test_new_columns_appended(self):
        fetch = make_fetch_response([
            make_db("DB", [
                make_schema("SCH", [
                    make_existing_table("T", ["COL_A"]),
                ])
            ])
        ])
        result = _merge_tables(fetch, [
            make_new_table_entry("DB", "SCH", "T", ["COL_A", "COL_B"]),
        ])
        schema = result[0]["schemas"][0]
        table = schema["tables"][0]
        col_names = [c["name"] for c in table["columns"]]
        assert "COL_A" in col_names
        assert "COL_B" in col_names

    def test_duplicate_columns_not_added(self):
        fetch = make_fetch_response([
            make_db("DB", [
                make_schema("SCH", [
                    make_existing_table("T", ["COL_A", "COL_B"]),
                ])
            ])
        ])
        # Try to add COL_A again
        result = _merge_tables(fetch, [
            make_new_table_entry("DB", "SCH", "T", ["COL_A"]),
        ])
        schema = result[0]["schemas"][0]
        table = schema["tables"][0]
        col_names = [c["name"] for c in table["columns"]]
        assert col_names.count("COL_A") == 1, "COL_A must not be duplicated"


# ---------------------------------------------------------------------------
# New database / schema creation
# ---------------------------------------------------------------------------

class TestHierarchyCreation:
    def test_new_schema_in_existing_db(self):
        fetch = make_fetch_response([
            make_db("DB", [
                make_schema("EXISTING_SCH", [
                    make_existing_table("T", ["ID"]),
                ])
            ])
        ])
        result = _merge_tables(fetch, [
            make_new_table_entry("DB", "NEW_SCH", "NEW_TABLE", ["ID"]),
        ])
        schema_names = {s["name"] for s in result[0]["schemas"]}
        assert "EXISTING_SCH" in schema_names
        assert "NEW_SCH" in schema_names

    def test_new_database_created(self):
        fetch = make_fetch_response([
            make_db("DB_A", [make_schema("SCH", [make_existing_table("T", ["ID"])])]),
        ])
        result = _merge_tables(fetch, [
            make_new_table_entry("DB_B", "SCH", "NEW_TABLE", ["ID"]),
        ])
        db_names = {db["name"] for db in result}
        assert "DB_A" in db_names
        assert "DB_B" in db_names


# ---------------------------------------------------------------------------
# Column flags on new tables
# ---------------------------------------------------------------------------

class TestNewTableFlags:
    def test_new_table_columns_have_required_flags(self):
        result = _merge_tables({}, [
            make_new_table_entry("DB", "SCH", "T", ["COL"]),
        ])
        col = result[0]["schemas"][0]["tables"][0]["columns"][0]
        assert col["selected"] is True
        assert col["isLinkedActive"] is True

    def test_new_table_has_selected_and_linked(self):
        result = _merge_tables({}, [
            make_new_table_entry("DB", "SCH", "T", ["COL"]),
        ])
        table = result[0]["schemas"][0]["tables"][0]
        assert table["selected"] is True
        assert table["linked"] is True
