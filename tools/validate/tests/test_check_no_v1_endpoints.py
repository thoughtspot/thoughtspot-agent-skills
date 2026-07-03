"""Unit tests for check_no_v1_endpoints — AST-based v1 endpoint guard.

The key behaviours: flag a real v1 path baked into code, but NOT a docstring
mention or a test-file negative assertion (the false-positives a raw grep hits).
"""
import check_no_v1_endpoints as nv


def _scan_src(tmp_path, src, name="mod.py"):
    f = tmp_path / name
    f.write_text(src, encoding="utf-8")
    return nv.scan_file(f)


def test_flags_v1_path_in_call(tmp_path):
    src = 'def f(c):\n    return c.post("/tspublic/v1/connection/fetchConnection")\n'
    hits = _scan_src(tmp_path, src)
    assert len(hits) == 1
    assert hits[0][0] == 2  # line number


def test_flags_v1_path_in_assignment(tmp_path):
    src = 'URL = "/tspublic/v1/session/login"\n'
    hits = _scan_src(tmp_path, src)
    assert len(hits) == 1


def test_module_docstring_mention_is_ignored(tmp_path):
    src = '"""This module no longer uses /tspublic/v1/ anything."""\nX = 1\n'
    assert _scan_src(tmp_path, src) == []


def test_function_docstring_mention_is_ignored(tmp_path):
    src = (
        "def g():\n"
        '    """Migrated off /tspublic/v1/connection/fetchConnection to v2."""\n'
        "    return 1\n"
    )
    assert _scan_src(tmp_path, src) == []


def test_clean_file_with_v2_only(tmp_path):
    src = 'def f(c):\n    return c.post("/api/rest/2.0/connection/search")\n'
    assert _scan_src(tmp_path, src) == []


def test_file_without_marker_short_circuits(tmp_path):
    assert _scan_src(tmp_path, "x = 1\n") == []


def test_syntax_error_is_swallowed(tmp_path):
    # Contains the marker but is unparseable — not this validator's job to flag syntax.
    assert _scan_src(tmp_path, 'def (:\n  "/tspublic/v1/x"\n') == []


def test_test_files_are_excluded(tmp_path):
    assert nv._is_test_file(tmp_path / "test_thing.py")
    assert nv._is_test_file(tmp_path / "tests" / "thing.py")
    assert not nv._is_test_file(tmp_path / "thing.py")


def test_validate_dir_is_excluded(tmp_path):
    from pathlib import Path
    assert nv._is_excluded(Path("tools/validate/check_no_v1_endpoints.py"))
    assert not nv._is_excluded(Path("tools/ts-cli/ts_cli/client.py"))


# --- Deprecated-v2 endpoint denylist (2026-07 audit finding 13.1) ----------------


def test_flags_bare_deprecated_batch_endpoint(tmp_path):
    src = (
        'def f(c):\n'
        '    return c.post("/api/rest/2.0/template/variables/update-values")\n'
    )
    hits = _scan_src(tmp_path, src)
    assert len(hits) == 1
    assert hits[0][0] == 2


def test_does_not_flag_per_identifier_form(tmp_path):
    # The current, correct form — a real identifier segment between "variables/"
    # and "update-values". Must NOT match the bare-batch-path denylist entry.
    src = (
        'def f(c, identifier):\n'
        '    return c.post(f"/api/rest/2.0/template/variables/{identifier}/update-values")\n'
    )
    assert _scan_src(tmp_path, src) == []


def test_does_not_flag_fstring_quote_variant(tmp_path):
    # The real ts_cli shape: f"/api/rest/2.0/template/variables/{quote(variable, safe='')}/update-values"
    src = (
        "from urllib.parse import quote\n"
        "def f(c, variable):\n"
        "    return c.post(\n"
        "        f\"/api/rest/2.0/template/variables/{quote(variable, safe='')}/update-values\"\n"
        "    )\n"
    )
    assert _scan_src(tmp_path, src) == []


def test_deprecated_v2_docstring_mention_is_ignored(tmp_path):
    src = (
        "def f():\n"
        '    """Replaces the deprecated batch\n'
        "    POST /api/rest/2.0/template/variables/update-values endpoint.\n"
        '    """\n'
        "    return 1\n"
    )
    assert _scan_src(tmp_path, src) == []


def test_deprecated_v2_fast_path_short_circuits(tmp_path):
    assert _scan_src(tmp_path, "x = 1\n") == []
