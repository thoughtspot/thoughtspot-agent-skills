"""Unit tests for ts tableau validate (T5) — proofread, classification, attempt tracking, lock registry."""
import json
import os
import tempfile

import yaml

from ts_cli.commands.tableau_validate import (
    classify_error,
    run_proofread,
    parse_validation_response,
    run_validate,
    reset_attempts,
    build_payload,
    build_file_index,
    HARD_CAP,
    _load_state,
    _load_lock_registry,
    _build_dependency_map,
    _LOCK_REGISTRY_FILE,
    _LIMITATIONS_FILE,
)


# ── Error classification ────────────────────────────────────────────────────

def test_classify_14537_locked_by_default():
    assert classify_error(14537, "some permission error") == "locked"


def test_classify_14537_fixable_invalid_identifier():
    msg = (
        "SQL query execution failed: SELECT WRONG_COL FROM T. "
        "Error: SQL compilation error: error line 1 at position 7\n"
        "invalid identifier 'WRONG_COL'. <br/>"
    )
    assert classify_error(14537, msg) == "fixable"


def test_classify_locked_by_code_14540():
    assert classify_error(14540, "cascade error") == "locked"


def test_classify_locked_by_code_14516():
    assert classify_error(14516, "another error") == "locked"


def test_classify_warning_id_null():
    result = classify_error(None, "Table with id null not found. Matching with db/schema/dbTable")
    assert result == "warning"


def test_classify_fixable_default():
    result = classify_error(None, "column not found in connection")
    assert result == "fixable"


def test_classify_locked_by_pattern_lookup():
    result = classify_error(None, "formula contains LOOKUP(SUM([X]), -1)")
    assert result == "locked"


def test_classify_locked_by_pattern_qualify():
    result = classify_error(None, "SQL contains QUALIFY ROW_NUMBER()")
    assert result == "locked"


# ── Local proofread ──────────────────────────────────────────────────────────

def _write_tml(tmpdir, filename, content):
    path = os.path.join(tmpdir, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


def test_proofread_catches_full_outer():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "test.model.tml", yaml.dump({
            "model": {
                "name": "Test",
                "model_tables": [
                    {"name": "A", "joins": [{"with": "B", "type": "FULL_OUTER"}]},
                ],
            }
        }))
        errors = run_proofread(tmpdir)
        assert any(e["check_id"] == "full_outer" for e in errors)


def test_proofread_catches_int_not_int64():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "test.table.tml", "table:\n  name: T\n  columns:\n  - name: x\n    data_type: INT\n")
        errors = run_proofread(tmpdir)
        assert any(e["check_id"] == "int_not_int64" for e in errors)


def test_proofread_allows_int64():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "test.table.tml", "table:\n  name: T\n  columns:\n  - name: x\n    data_type: INT64\n")
        errors = run_proofread(tmpdir)
        assert not any(e["check_id"] == "int_not_int64" for e in errors)


def test_proofread_catches_case_when_in_model():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "test.model.tml", yaml.dump({
            "model": {
                "name": "Test",
                "formulas": [{"id": "f1", "name": "F1", "expr": "CASE WHEN [x] > 1 THEN 'a' END"}],
            }
        }))
        errors = run_proofread(tmpdir)
        assert any(e["check_id"] == "case_when_in_formula" for e in errors)


def test_proofread_catches_fqn_in_model():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "test.model.tml", "model:\n  name: T\n  model_tables:\n  - name: A\n    fqn: abc123\n")
        errors = run_proofread(tmpdir)
        assert any(e["check_id"] == "fqn_in_model_tables" for e in errors)


def test_proofread_catches_missing_db_column_properties():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "test.table.tml", yaml.dump({
            "table": {
                "name": "T",
                "columns": [{"name": "col1", "data_type": "VARCHAR"}],
            }
        }))
        errors = run_proofread(tmpdir)
        assert any(e["check_id"] == "missing_db_column_properties" for e in errors)


def test_proofread_passes_clean_table():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "test.table.tml", yaml.dump({
            "table": {
                "name": "T",
                "columns": [{
                    "name": "col1",
                    "data_type": "INT64",
                    "db_column_name": "col1",
                    "db_column_properties": {"data_type": "INT64"},
                }],
            }
        }))
        errors = run_proofread(tmpdir)
        assert errors == []


# ── Parse API response ───────────────────────────────────────────────────────

def test_parse_response_ok_returns_empty():
    resp = [{"response": {"status": {"status_code": "OK"}}}]
    errors = parse_validation_response(resp)
    assert errors == []


def test_parse_response_error_classified():
    resp = [
        {"request_index": 0, "response": {"status": {
            "status_code": "ERROR",
            "error_message": "connection not found for name 'BadConn'",
        }}}
    ]
    errors = parse_validation_response(resp)
    assert len(errors) == 1
    assert errors[0]["classification"] == "fixable"
    assert errors[0]["status"] == "ERROR"


def test_parse_response_locked_code():
    resp = [
        {"request_index": 0, "response": {"status": {
            "status_code": "ERROR",
            "error_message": "Error code 14537: SQL execution failed",
        }}}
    ]
    errors = parse_validation_response(resp)
    assert len(errors) == 1
    assert errors[0]["classification"] == "locked"
    assert errors[0]["error_code"] == 14537


def test_parse_response_warning_id_null():
    resp = [
        {"request_index": 0, "response": {"status": {
            "status_code": "WARNING",
            "error_message": "Table with id null not found. Matching with db/schema/dbTable",
        }}}
    ]
    errors = parse_validation_response(resp)
    assert len(errors) == 1
    assert errors[0]["classification"] == "warning"


# ── Attempt tracking ─────────────────────────────────────────────────────────

def test_attempt_counter_increments():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "clean.table.tml", yaml.dump({
            "table": {"name": "T", "columns": [
                {"name": "c", "data_type": "INT64", "db_column_name": "c",
                 "db_column_properties": {"data_type": "INT64"}}
            ]}
        }))
        r1 = run_validate(tmpdir)
        assert r1["attempt"] == 1
        r2 = run_validate(tmpdir)
        assert r2["attempt"] == 2


def test_reset_clears_counter():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "clean.table.tml", yaml.dump({
            "table": {"name": "T", "columns": [
                {"name": "c", "data_type": "INT64", "db_column_name": "c",
                 "db_column_properties": {"data_type": "INT64"}}
            ]}
        }))
        run_validate(tmpdir)
        run_validate(tmpdir)
        reset_attempts(tmpdir)
        r = run_validate(tmpdir)
        assert r["attempt"] == 1


def test_exhausted_at_hard_cap():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "clean.table.tml", yaml.dump({
            "table": {"name": "T", "columns": [
                {"name": "c", "data_type": "INT64", "db_column_name": "c",
                 "db_column_properties": {"data_type": "INT64"}}
            ]}
        }))
        state = {"attempt": HARD_CAP - 1, "history": []}
        from ts_cli.commands.tableau_validate import _save_state
        _save_state(tmpdir, state)
        r = run_validate(tmpdir)
        assert r["exhausted"] is True
        assert r["attempt"] == HARD_CAP


# ── Build payload ────────────────────────────────────────────────────────────

def test_build_payload_ordering():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "b.model.tml", "model:\n  name: M\n")
        _write_tml(tmpdir, "a.table.tml", "table:\n  name: T\n")
        _write_tml(tmpdir, "c.sql_view.tml", "sql_view:\n  name: SV\n")

        payload = build_payload(tmpdir)
        assert len(payload) == 3
        assert "table:" in payload[0]
        assert "sql_view:" in payload[1]
        assert "model:" in payload[2]


def test_build_payload_guid_detection():
    """Validate that payload strings contain guid: when TMLs have GUIDs pinned."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "t.table.tml",
                   "guid: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\ntable:\n  name: T\n")
        payload = build_payload(tmpdir)
        assert any("guid:" in s for s in payload)

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "t.table.tml", "table:\n  name: T\n")
        payload = build_payload(tmpdir)
        assert not any("guid:" in s for s in payload)


def test_build_file_index_ordering():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "b.model.tml", "model:\n  name: M\n")
        _write_tml(tmpdir, "a.table.tml", "table:\n  name: T\n")
        _write_tml(tmpdir, "c.sql_view.tml", "sql_view:\n  name: SV\n")

        idx = build_file_index(tmpdir)
        assert idx == ["a.table.tml", "c.sql_view.tml", "b.model.tml"]


# ── run_validate orchestrator ────────────────────────────────────────────────

def test_run_validate_valid_with_ok_response():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "t.table.tml", yaml.dump({
            "table": {"name": "T", "columns": [
                {"name": "c", "data_type": "INT64", "db_column_name": "c",
                 "db_column_properties": {"data_type": "INT64"}}
            ]}
        }))
        api_resp = [{"response": {"status": {"status_code": "OK"}}}]
        r = run_validate(tmpdir, api_response=api_resp)
        assert r["status"] == "VALID"
        assert r["locked_summary"]["count"] == 0


def test_run_validate_invalid_with_fixable_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "t.table.tml", yaml.dump({
            "table": {"name": "T", "columns": [
                {"name": "c", "data_type": "INT64", "db_column_name": "c",
                 "db_column_properties": {"data_type": "INT64"}}
            ]}
        }))
        api_resp = [{"request_index": 0, "response": {"status": {
            "status_code": "ERROR",
            "error_message": "connection not found",
        }}}]
        r = run_validate(tmpdir, api_response=api_resp)
        assert r["status"] == "INVALID"
        assert len(r["fixable"]) == 1
        assert "locked" not in r, "locked details must not appear in output"
        assert r["locked_summary"]["count"] == 0


def test_run_validate_proofread_fail_blocks_without_api():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "bad.table.tml", "table:\n  name: T\n  columns:\n  - name: x\n    data_type: INT\n")
        r = run_validate(tmpdir)
        assert r["status"] == "PROOFREAD_FAIL"
        assert len(r["fixable"]) >= 1
        assert r["locked_summary"]["count"] == 0


# ── Lock registry ───────────────────────────────────────────────────────────

def test_locked_error_registered_and_hidden():
    """Locked errors go to the registry and MIGRATION_LIMITATIONS.md, not to output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "sv.sql_view.tml", yaml.dump({
            "sql_view": {"name": "SV", "sql_query": "SELECT 1",
                         "sql_view_columns": [{"name": "c"}]}
        }))
        api_resp = [{"request_index": 0, "response": {"status": {
            "status_code": "ERROR",
            "error_message": "Error code 14537: SQL execution failed",
        }}}]
        r = run_validate(tmpdir, api_response=api_resp)

        assert r["locked_summary"]["count"] == 1
        assert "sv.sql_view.tml" in r["locked_summary"]["files"]
        assert "locked" not in r, "locked array must not appear in output"

        registry = _load_lock_registry(tmpdir)
        assert "sv.sql_view.tml" in registry["locked_objects"]
        assert registry["locked_objects"]["sv.sql_view.tml"]["error_code"] == 14537

        limitations_path = os.path.join(tmpdir, _LIMITATIONS_FILE)
        assert os.path.exists(limitations_path)
        content = open(limitations_path).read()
        assert "14537" in content


def test_locked_persists_across_attempts():
    """Once locked, the file stays locked even if the error changes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "sv.sql_view.tml", yaml.dump({
            "sql_view": {"name": "SV", "sql_query": "SELECT 1",
                         "sql_view_columns": [{"name": "c"}]}
        }))
        # Attempt 1: locked error
        api_resp_1 = [{"request_index": 0, "response": {"status": {
            "status_code": "ERROR",
            "error_message": "Error code 14537: SQL execution failed",
        }}}]
        run_validate(tmpdir, api_response=api_resp_1)

        # Attempt 2: same file now returns a different error
        api_resp_2 = [{"request_index": 0, "response": {"status": {
            "status_code": "ERROR",
            "error_message": "column X not found",
        }}}]
        r2 = run_validate(tmpdir, api_response=api_resp_2)

        assert r2["locked_summary"]["count"] == 1
        assert len(r2["fixable"]) == 0, "error on locked file must not appear as fixable"


def test_cascade_detection():
    """Model depending on a locked sql_view has its errors reclassified as locked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "sv.sql_view.tml", yaml.dump({
            "sql_view": {"name": "SV", "sql_query": "SELECT 1",
                         "sql_view_columns": [{"name": "c"}]}
        }))
        _write_tml(tmpdir, "m.model.tml", yaml.dump({
            "model": {"name": "M", "model_tables": [{"name": "SV"}],
                      "columns": [{"name": "c", "column_id": "SV::c"}]}
        }))

        # Attempt 1: sql_view is locked
        api_resp_1 = [
            {"request_index": 0, "response": {"status": {
                "status_code": "ERROR",
                "error_message": "Error code 14537: SQL failed",
            }}},
            {"request_index": 1, "response": {"status": {"status_code": "OK"}}},
        ]
        run_validate(tmpdir, api_response=api_resp_1)

        # Attempt 2: model now has a fixable-looking error — but it depends on locked SV
        api_resp_2 = [
            {"request_index": 0, "response": {"status": {"status_code": "OK"}}},
            {"request_index": 1, "response": {"status": {
                "status_code": "ERROR",
                "error_message": "no matches for table SV",
            }}},
        ]
        r2 = run_validate(tmpdir, api_response=api_resp_2)

        assert len(r2["fixable"]) == 0, "cascade error must not appear as fixable"
        assert r2["locked_summary"]["count"] >= 1


def test_reset_clears_lock_registry():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "sv.sql_view.tml", yaml.dump({
            "sql_view": {"name": "SV", "sql_query": "SELECT 1",
                         "sql_view_columns": [{"name": "c"}]}
        }))
        api_resp = [{"request_index": 0, "response": {"status": {
            "status_code": "ERROR",
            "error_message": "Error code 14537: SQL failed",
        }}}]
        run_validate(tmpdir, api_response=api_resp)
        assert os.path.exists(os.path.join(tmpdir, _LOCK_REGISTRY_FILE))

        reset_attempts(tmpdir)
        assert not os.path.exists(os.path.join(tmpdir, _LOCK_REGISTRY_FILE))
        assert not os.path.exists(os.path.join(tmpdir, _LIMITATIONS_FILE))


# ── Dependency map ──────────────────────────────────────────────────────────

def test_build_dependency_map():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_tml(tmpdir, "m.model.tml", yaml.dump({
            "model": {"name": "M", "model_tables": [
                {"name": "TableA"}, {"name": "SV_Orders"},
            ]}
        }))
        deps = _build_dependency_map(tmpdir)
        assert deps["m.model.tml"] == ["TableA", "SV_Orders"]
