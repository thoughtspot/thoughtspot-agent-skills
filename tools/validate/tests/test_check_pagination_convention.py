"""Unit tests for check_pagination_convention — AST-scoped record_size guard.

Key behaviours: flag a hard-capped literal with no pagination loop in its own
function; don't flag -1 (the "return everything" sentinel); don't flag a literal
fed through a Name (variable) rather than a Constant; don't flag a function that
has a `while` loop or a `record_offset` mutation in its own body; don't let a
literal in a nested helper "inherit" an outer function's while loop (or vice
versa) — each function is its own scope.
"""
import check_pagination_convention as pc


def _scan_src(tmp_path, src, name="mod.py"):
    f = tmp_path / name
    f.write_text(src, encoding="utf-8")
    return pc.scan_file(f)


def test_flags_hard_capped_literal_with_no_loop(tmp_path):
    src = (
        "def search(client):\n"
        "    return client.post('/x', json={'record_size': 50, 'record_offset': 0})\n"
    )
    hits = _scan_src(tmp_path, src)
    assert len(hits) == 1
    lineno, value, qualname = hits[0]
    assert value == 50
    assert qualname == "search"


def test_does_not_flag_unlimited_sentinel(tmp_path):
    src = (
        "def f(client):\n"
        "    return client.post('/x', json={'record_size': -1, 'record_offset': 0})\n"
    )
    assert _scan_src(tmp_path, src) == []


def test_does_not_flag_variable_fed_record_size(tmp_path):
    # The real ts-cli shape post-#173: record_size is a Name, not a Constant.
    src = (
        "def search(client):\n"
        "    page_size = 50\n"
        "    offset = 0\n"
        "    while True:\n"
        "        resp = client.post('/x', json={'record_size': page_size, "
        "'record_offset': offset})\n"
        "        page = resp.json()\n"
        "        if not page:\n"
        "            break\n"
        "        offset += page_size\n"
    )
    assert _scan_src(tmp_path, src) == []


def test_while_loop_in_same_function_clears_literal(tmp_path):
    src = (
        "def f(client):\n"
        "    payload = {'record_size': 50}\n"
        "    while True:\n"
        "        break\n"
        "    return payload\n"
    )
    assert _scan_src(tmp_path, src) == []


def test_record_offset_mutation_clears_literal(tmp_path):
    src = (
        "def f(client):\n"
        "    record_offset = 0\n"
        "    payload = {'record_size': 50}\n"
        "    record_offset += 50\n"
        "    return payload\n"
    )
    assert _scan_src(tmp_path, src) == []


def test_nested_helper_does_not_inherit_outer_while_loop(tmp_path):
    # The outer function loops, but the literal is hard-capped inside a nested
    # helper with no loop of its own — must still be flagged (own-scope only).
    src = (
        "def outer(client):\n"
        "    def _helper():\n"
        "        return {'record_size': 5}\n"
        "    while True:\n"
        "        _helper()\n"
        "        break\n"
    )
    hits = _scan_src(tmp_path, src)
    assert len(hits) == 1
    assert hits[0][2] == "outer._helper"


def test_keyword_argument_form_is_flagged(tmp_path):
    src = (
        "def f(client):\n"
        "    return client.search(record_size=5, record_offset=0)\n"
    )
    hits = _scan_src(tmp_path, src)
    assert len(hits) == 1
    assert hits[0][1] == 5


def test_module_level_literal_with_no_function_is_flagged(tmp_path):
    src = "PAYLOAD = {'record_size': 5}\n"
    hits = _scan_src(tmp_path, src)
    assert len(hits) == 1
    assert hits[0][2] == "<module>"


def test_file_without_marker_short_circuits(tmp_path):
    assert _scan_src(tmp_path, "x = 1\n") == []


def test_syntax_error_is_swallowed(tmp_path):
    assert _scan_src(tmp_path, "def (:\n  record_size = 5\n") == []


def test_main_allowlist_suppresses_known_functions(tmp_path):
    # Build a fake ts_cli/commands/metadata.py at the allowlisted qualname and
    # confirm main() exits 0 for it, but flags an unlisted sibling function.
    import subprocess
    import sys as _sys

    root = tmp_path
    commands_dir = root / "tools" / "ts-cli" / "ts_cli" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "metadata.py").write_text(
        "def get_object(client, guid):\n"
        "    return client.post('/x', json={'record_size': 1, 'record_offset': 0})\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [_sys.executable, pc.__file__, "--root", str(root)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_main_flags_unlisted_function(tmp_path):
    import subprocess
    import sys as _sys

    root = tmp_path
    commands_dir = root / "tools" / "ts-cli" / "ts_cli" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "bad_new_command.py").write_text(
        "def search(client):\n"
        "    return client.post('/x', json={'record_size': 50, 'record_offset': 0})\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [_sys.executable, pc.__file__, "--root", str(root)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "bad_new_command.py" in result.stdout
