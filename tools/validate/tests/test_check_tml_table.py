"""Negative-case tests for check_tml.validate_table_tml.

This function is the automated guard for the CLAUDE.md "Critical TML invariants" —
rules CLAUDE.md says "come from real import failures — violating them causes silent
errors or rejected imports". It emits ~14 distinct errors and, before this file, not
one of them had a test (2026-08-26 audit, finding 6.3).

`test_check_tml.py` covers `validate_model_tml` only (I4/I5).
`test_check_tml_enums.py` covers aggregation/data_type/join enums, and *includes*
`db_column_name` in its fixtures as scaffolding without ever asserting that its
absence is flagged. The known-bad fixture `tests/fixtures/bad_tml.md` is a `model:`
document, so it never reaches the table path at all.

Consequence: inverting any one of these ~14 conditions left the entire repo test
suite green while the gate went dark. Each test below inverts exactly one condition
from a valid baseline, so a regression names the invariant it broke.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_tml  # noqa: E402


def _valid_column(name="REGION", **over):
    col = {
        "name": name,
        "db_column_name": name,
        "properties": {"column_type": "ATTRIBUTE"},
        "db_column_properties": {"data_type": "VARCHAR"},
    }
    col.update(over)
    return col


def _table(**over):
    """A table document that must validate cleanly, so each test can break one thing."""
    inner = {
        "name": "FACT_ORDERS",
        "db": "AGENT_SKILLS",
        "schema": "PUBLIC",
        "db_table": "FACT_ORDERS",
        "connection": {"name": "My Snowflake"},
        "columns": [_valid_column()],
    }
    inner.update(over)
    return {"table": inner}


def test_baseline_is_valid():
    """Guards the tests below: if the baseline itself errors, every assertion is
    vacuous because it would pass on the wrong error."""
    assert check_tml.validate_table_tml(_table()) == []


# ── connection block ────────────────────────────────────────────────────────

def test_connection_fqn_is_flagged():
    """CLAUDE.md: connection in table TML is `name:` only — never `fqn:`."""
    errors = check_tml.validate_table_tml(
        _table(connection={"name": "My Snowflake", "fqn": "abc-123"}))
    assert any("fqn" in e for e in errors), errors


def test_connection_missing_name_is_flagged():
    errors = check_tml.validate_table_tml(_table(connection={}))
    assert any("connection.name is required" in e for e in errors), errors


def test_connection_absent_is_flagged():
    t = _table()
    del t["table"]["connection"]
    errors = check_tml.validate_table_tml(t)
    assert any("connection is required" in e for e in errors), errors


def test_connection_not_a_mapping_is_flagged():
    errors = check_tml.validate_table_tml(_table(connection="My Snowflake"))
    assert any("must be a mapping" in e for e in errors), errors


# ── required top-level fields ───────────────────────────────────────────────

def test_each_required_field_is_flagged_when_missing():
    for field in ("name", "db", "schema", "db_table"):
        t = _table()
        del t["table"][field]
        errors = check_tml.validate_table_tml(t)
        assert any(f"table.{field} is required" in e for e in errors), (field, errors)


# ── columns ─────────────────────────────────────────────────────────────────

def test_missing_db_column_name_is_flagged():
    """CLAUDE.md: always include db_column_name, even when it equals name."""
    col = _valid_column()
    del col["db_column_name"]
    errors = check_tml.validate_table_tml(_table(columns=[col]))
    assert any("db_column_name" in e for e in errors), errors


def test_column_type_at_column_root_is_flagged():
    """It must be nested under properties:, not at the column root."""
    errors = check_tml.validate_table_tml(
        _table(columns=[_valid_column(column_type="ATTRIBUTE")]))
    assert any("column root" in e for e in errors), errors


def test_missing_db_column_properties_is_flagged():
    col = _valid_column()
    del col["db_column_properties"]
    errors = check_tml.validate_table_tml(_table(columns=[col]))
    assert any("db_column_properties" in e for e in errors), errors


def test_missing_properties_column_type_is_flagged():
    errors = check_tml.validate_table_tml(
        _table(columns=[_valid_column(properties={})]))
    assert any("properties.column_type" in e for e in errors), errors


def test_invalid_column_type_value_is_flagged():
    errors = check_tml.validate_table_tml(
        _table(columns=[_valid_column(properties={"column_type": "DIMENSION"})]))
    assert any("is invalid" in e for e in errors), errors


def test_non_string_column_type_is_flagged():
    errors = check_tml.validate_table_tml(
        _table(columns=[_valid_column(properties={"column_type": ["ATTRIBUTE"]})]))
    assert any("must be a string" in e for e in errors), errors


def test_empty_columns_is_flagged():
    errors = check_tml.validate_table_tml(_table(columns=[]))
    assert any("at least one entry" in e for e in errors), errors


def test_column_not_a_mapping_is_flagged():
    errors = check_tml.validate_table_tml(_table(columns=["REGION"]))
    assert any("must be a mapping" in e for e in errors), errors


# ── db_column_properties.data_type ──────────────────────────────────────────

def test_sql_data_type_is_flagged_with_the_ts_equivalent():
    """TEXT/TINYINT/NUMERIC are SQL-only; TS wants VARCHAR/BOOL/DOUBLE.

    Note `INTEGER` is NOT one of them: it sits in TS_DATA_TYPES and validates
    cleanly, even though this check's own error message reads "e.g. INT64 not
    INTEGER". Message and type sets disagree; the sets are what actually gates,
    so the message is the thing that is wrong. Left alone here — a wording fix
    is not a test's job — but asserted below so the behaviour is pinned.
    """
    errors = check_tml.validate_table_tml(
        _table(columns=[_valid_column(db_column_properties={"data_type": "TEXT"})]))
    assert any("is a SQL type" in e for e in errors), errors


def test_integer_data_type_is_accepted_despite_the_error_message():
    """Pins the surprise above so a future reader does not "fix" the wrong half."""
    errors = check_tml.validate_table_tml(
        _table(columns=[_valid_column(db_column_properties={"data_type": "INTEGER"})]))
    assert errors == [], errors


def test_unknown_data_type_is_flagged():
    errors = check_tml.validate_table_tml(
        _table(columns=[_valid_column(db_column_properties={"data_type": "BLOB"})]))
    assert any("not a valid ThoughtSpot data type" in e for e in errors), errors


# ── joins_with ──────────────────────────────────────────────────────────────

def test_empty_joins_with_list_is_flagged():
    """An empty list must be omitted entirely — it can fail import on some versions."""
    errors = check_tml.validate_table_tml(_table(joins_with=[]))
    assert any("empty list" in e for e in errors), errors


def test_omitted_joins_with_is_fine():
    assert check_tml.validate_table_tml(_table()) == []


def test_full_outer_join_type_is_flagged():
    """FULL_OUTER is rejected in table context too (live-verified 2026-07-30)."""
    errors = check_tml.validate_table_tml(
        _table(joins_with=[{"name": "J1", "type": "FULL_OUTER"}]))
    assert errors, "FULL_OUTER should be rejected"


def test_valid_join_type_passes():
    errors = check_tml.validate_table_tml(
        _table(joins_with=[{"name": "J1", "type": "LEFT_OUTER"}]))
    assert errors == [], errors
