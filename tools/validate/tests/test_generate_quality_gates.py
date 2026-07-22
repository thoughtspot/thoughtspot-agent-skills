"""Tests for generate_quality_gates.py parsing logic."""
from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generate_quality_gates import (
    _collect_comment,
    _extract_docstring,
    _find_trigger,
    _humanise_trigger,
    _parse_precommit,
)


# ---------------------------------------------------------------------------
# _find_trigger
# ---------------------------------------------------------------------------

class TestFindTrigger:
    def test_direct_enclosing_if(self):
        lines = [
            'if echo "$STAGED" | grep -qE \'\\.py$\'; then',
            '  run_check "module health" "tools/validate/check_module_health.py"',
        ]
        assert _find_trigger(lines, 1) == "\\.py$"

    def test_no_enclosing_if(self):
        lines = [
            'run_check "secrets" "tools/validate/check_secrets.py"',
        ]
        assert _find_trigger(lines, 0) == "always"

    def test_skips_closed_if_fi_block(self):
        lines = [
            'run_check "always_run" "..."',
            'if echo "$STAGED" | grep -q \'inner\'; then',
            '  run_check "inner" "..."',
            'fi',
            'run_check "after_block" "..."',
        ]
        assert _find_trigger(lines, 4) == "always"

    def test_sibling_check_in_same_block(self):
        lines = [
            'if echo "$STAGED" | grep -q \'open-items\'; then',
            '  run_check "open items" "..."',
            '  run_check "open items index" "..."',
        ]
        assert _find_trigger(lines, 2) == "open-items"

    def test_skips_comments_and_blanks(self):
        lines = [
            'if echo "$STAGED" | grep -qE \'SKILL\\.md\'; then',
            '  # Some comment',
            '',
            '  run_check "skill versions" "..."',
        ]
        assert _find_trigger(lines, 3) == "SKILL\\.md"

    def test_nested_blocks_skipped(self):
        lines = [
            'if echo "$STAGED" | grep -q \'outer\'; then',
            '  if echo "$STAGED" | grep -q \'inner\'; then',
            '    run_check "inner check" "..."',
            '  fi',
            '  run_check "outer check" "..."',
        ]
        assert _find_trigger(lines, 4) == "outer"


# ---------------------------------------------------------------------------
# _collect_comment
# ---------------------------------------------------------------------------

class TestCollectComment:
    def test_single_comment_line(self):
        lines = [
            '# This is the reason.',
            'run_check "test" "..."',
        ]
        assert _collect_comment(lines, 1) == "This is the reason."

    def test_multi_line_comment(self):
        lines = [
            '# First line.',
            '# Second line.',
            'run_check "test" "..."',
        ]
        assert _collect_comment(lines, 2) == "First line. Second line."

    def test_skips_blank_lines(self):
        lines = [
            '# Comment above blank.',
            '',
            'run_check "test" "..."',
        ]
        assert _collect_comment(lines, 2) == "Comment above blank."

    def test_no_comment(self):
        lines = [
            'some_other_code',
            'run_check "test" "..."',
        ]
        assert _collect_comment(lines, 1) == ""


# ---------------------------------------------------------------------------
# _extract_docstring
# ---------------------------------------------------------------------------

class TestExtractDocstring:
    def test_module_docstring(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(dedent('''\
            #!/usr/bin/env python3
            """
            check_foo.py — verify foo invariants.

            Extended description here.
            """
            import sys
        '''))
        result = _extract_docstring(f)
        assert result == "check_foo.py — verify foo invariants."

    def test_no_docstring(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("import sys\n")
        assert _extract_docstring(f) == ""

    def test_missing_file(self, tmp_path):
        assert _extract_docstring(tmp_path / "nonexistent.py") == ""

    def test_single_line_docstring(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text('"""Short docstring."""\nimport sys\n')
        assert _extract_docstring(f) == "Short docstring."


# ---------------------------------------------------------------------------
# _humanise_trigger
# ---------------------------------------------------------------------------

class TestHumaniseTrigger:
    def test_always(self):
        assert _humanise_trigger("always") == "Every commit"

    def test_empty(self):
        assert _humanise_trigger("") == "Every commit"

    def test_open_items(self):
        assert _humanise_trigger("open-items\\.md") == "Open-items files staged"

    def test_convert_skill(self):
        assert _humanise_trigger("(agents/cli/ts-convert-|tools/validate/check_coverage_matrix\\.py)") == "Convert skill or validator staged"

    def test_skill_files(self):
        assert _humanise_trigger("agents/(cli|claude)/.*/SKILL\\.md") == "Skill files staged"

    def test_python_files(self):
        assert _humanise_trigger("\\.py$") == "Python files staged"

    def test_markdown_files(self):
        assert _humanise_trigger("\\.md$") == "Markdown files staged"

    def test_ts_cli_source(self):
        assert _humanise_trigger("^tools/ts-cli/ts_cli/.*\\.py$") == "ts-cli Python source staged"

    def test_shared_mappings(self):
        assert _humanise_trigger("agents/shared/(mappings|schemas)/.*\\.md$") == "Shared mappings/schemas staged"


# ---------------------------------------------------------------------------
# _parse_precommit (integration)
# ---------------------------------------------------------------------------

class TestParsePrecommit:
    def test_extracts_run_check(self, tmp_path):
        f = tmp_path / "pre-commit.sh"
        f.write_text(dedent('''\
            #!/usr/bin/env bash
            PYTHON_BIN="python3"
            run_check() { echo "$1"; }

            # Secrets scanner
            run_check "secrets" "tools/validate/check_secrets.py --root ."
        '''))
        entries = _parse_precommit(f)
        assert len(entries) == 1
        assert entries[0]["label"] == "secrets"
        assert entries[0]["validator"] == "check_secrets.py"

    def test_conditional_check(self, tmp_path):
        f = tmp_path / "pre-commit.sh"
        f.write_text(dedent('''\
            #!/usr/bin/env bash
            # Line-count gate on staged ts_cli modules
            if echo "$STAGED" | grep -q '^tools/ts-cli/ts_cli/.*\\.py$'; then
              run_check "file size" "tools/validate/check_file_size.py --root ."
            fi
        '''))
        entries = _parse_precommit(f)
        assert len(entries) == 1
        assert entries[0]["trigger"] == "^tools/ts-cli/ts_cli/.*\\.py$"

    def test_soft_mode_detected(self, tmp_path):
        f = tmp_path / "pre-commit.sh"
        f.write_text(dedent('''\
            #!/usr/bin/env bash
            run_check "open items" "tools/validate/check_open_items.py --root . --warn"
        '''))
        entries = _parse_precommit(f)
        assert entries[0]["mode"] == "soft"

    def test_run_pytest(self, tmp_path):
        f = tmp_path / "pre-commit.sh"
        f.write_text(dedent('''\
            #!/usr/bin/env bash
            run_pytest() { echo "$1"; }

            if echo "$STAGED" | grep -q '\\.py$'; then
              run_pytest "unit tests (ts-cli)" tools/ts-cli/tests/
            fi
        '''))
        entries = _parse_precommit(f)
        assert len(entries) == 1
        assert entries[0]["label"] == "unit tests (ts-cli)"
        assert entries[0]["mode"] == "gate"
