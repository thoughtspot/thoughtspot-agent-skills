"""Tests for generate_quality_gates.py parsing logic."""
from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import checks
from generate_quality_gates import (
    collect_gates,
    strip_volatile,
    _collect_comment,
    _extract_docstring,
    _find_trigger,
    _humanise_trigger,
    _parse_ci,
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


# ---------------------------------------------------------------------------
# strip_volatile — BL-192
# ---------------------------------------------------------------------------

class TestParseCi:
    def test_warn_flag_marks_ci_only_check_soft(self, tmp_path):
        f = tmp_path / "validate.yml"
        f.write_text(dedent('''\
            steps:
              - run: |
                  python3 tools/validate/check_pr_size.py --root . --base origin/main --warn
                  python3 tools/validate/check_secrets.py --root . --all || rc=1
        '''))
        modes = {e["validator"]: e["mode"] for e in _parse_ci(f)}
        assert modes == {"check_pr_size.py": "soft", "check_secrets.py": "gate"}



# ---------------------------------------------------------------------------
# _parse_ci reading the check list through run_checks.py
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_CI_CALL = "python3 tools/validate/run_checks.py --context ci --base origin/main"
RUNNER_SMOKES_CALL = "python3 tools/validate/run_checks.py --smokes"

# The catalog's (validator, mode) pairs. Captured 2026-10-28 from the
# explicit-lines workflow (one `python3 tools/validate/X.py ... || rc=1` per
# validator) just before CI switched to run_checks.py, and unchanged by that
# switch. A deliberate second copy: a change to the gate set (a gate added,
# dropped or re-moded, in checks.py, pre-commit.sh or the workflow) updates this
# literal in the same PR.
EXPECTED_GATES = {
    ("_pip_audit", "gate"),
    ("_pytest_ci", "gate"),
    ("check_agentql_quest.py", "gate"),
    ("check_audit_catalog.py", "gate"),
    ("check_audit_freshness.py", "soft"),
    ("check_audit_workflow_permissions.py", "gate"),
    ("check_backlog_integrity.py", "gate"),
    ("check_ci_gate_coverage.py", "gate"),
    ("check_consistency.py", "gate"),
    ("check_converter_parity.py", "gate"),
    ("check_coverage_matrix.py", "gate"),
    ("check_customer_references.py", "gate"),
    ("check_file_size.py", "gate"),
    ("check_formula_catalog.py", "gate"),
    ("check_harness_routing.py", "gate"),
    ("check_i7_gate.py", "gate"),
    ("check_internal_imports.py", "gate"),
    ("check_lint_invariant_list.py", "gate"),
    ("check_mapping_code_sync.py", "gate"),
    ("check_mapping_currency.py", "soft"),
    ("check_mirror_sync.py", "gate"),
    ("check_module_health.py", "gate"),
    ("check_no_inline_requests.py", "gate"),
    ("check_no_inline_tml_gate.py", "gate"),
    ("check_no_v1_endpoints.py", "gate"),
    ("check_open_item_citations.py", "gate"),
    ("check_open_items.py", "soft"),
    ("check_orphan_references.py", "gate"),
    ("check_ossie_mapping_sync.py", "gate"),
    ("check_pagination_convention.py", "gate"),
    ("check_patterns.py", "gate"),
    ("check_pr_size.py", "soft"),
    ("check_python_redefinitions.py", "gate"),
    ("check_references.py", "gate"),
    ("check_repo_hygiene.py", "gate"),
    ("check_runtime_coverage.py", "gate"),
    ("check_secrets.py", "gate"),
    ("check_skill_cli_usage.py", "gate"),
    ("check_skill_context_cost.py", "gate"),
    ("check_skill_flag_usage.py", "gate"),
    ("check_skill_naming.py", "gate"),
    ("check_skill_versions.py", "gate"),
    ("check_slash_command_refs.py", "gate"),
    ("check_smoke_tests.py", "gate"),
    ("check_sv_yaml.py", "gate"),
    ("check_tml.py", "gate"),
    ("check_version_sync.py", "gate"),
    ("check_yaml.py", "gate"),
    ("generate_agentql_offline.py", "gate"),
    ("generate_open_items_index.py", "gate"),
    ("generate_parity.py", "gate"),
    ("generate_quality_gates.py", "gate"),
    ("suggest_dependency_types.py", "soft"),
    ("suggest_repo_changelog.py", "gate"),
    ("suggest_skill_version.py", "soft"),
    ("unit tests (databricks)", "gate"),
    ("unit tests (erd)", "gate"),
    ("unit tests (ts-cli)", "gate"),
}


def _step_lines(workflow: dict, name: str) -> list[str]:
    steps = [s for s in workflow["jobs"]["suite"]["steps"] if s.get("name") == name]
    assert len(steps) == 1, f"expected one step named {name!r}"
    return [ln.strip() for ln in steps[0]["run"].splitlines() if ln.strip() and not ln.strip().startswith("#")]


def test_catalog_gate_set():
    # The snapshot is only evidence about the runner path while CI uses it.
    wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8"))
    assert RUNNER_CI_CALL in _step_lines(wf, "Run validators (full-repo mode)")
    assert RUNNER_SMOKES_CALL in _step_lines(wf, "Run credential-free smoke suites")

    gates = collect_gates(REPO_ROOT)
    pairs = {(v, info["mode"]) for v, info in gates.items()}
    assert pairs - EXPECTED_GATES == set(), (
        "gate set changed (added or re-moded) — update EXPECTED_GATES deliberately")
    assert EXPECTED_GATES - pairs == set(), (
        "gate set changed (dropped or re-moded) — update EXPECTED_GATES deliberately")
    # Every listed check is recorded as running in CI, not just present via pre-commit.
    not_ci = sorted(c.script for c in checks.CHECKS if not gates[c.script]["ci"])
    assert not_ci == [], f"checks the catalog no longer marks as CI: {not_ci}"


class TestParseCiRunner:
    def _parse(self, tmp_path, run_line):
        f = tmp_path / "validate.yml"
        f.write_text(f"steps:\n  - run: |\n      {run_line}\n")
        return _parse_ci(f)

    def test_ci_runner_line_expands_to_one_entry_per_check(self, tmp_path):
        entries = self._parse(tmp_path, RUNNER_CI_CALL)
        assert [e["validator"] for e in entries] == [c.script for c in checks.CHECKS]
        for e, c in zip(entries, checks.CHECKS):
            assert set(e) == {"validator", "comment", "mode"}
            assert e["mode"] == ("gate" if c.hard else "soft"), c.id

    def test_soft_check_is_soft(self, tmp_path):
        modes = {e["validator"]: e["mode"] for e in self._parse(tmp_path, RUNNER_CI_CALL)}
        assert modes["generate_quality_gates.py"] == "soft"

    def test_smoke_runner_line_is_not_a_catalog_row(self, tmp_path):
        assert self._parse(tmp_path, RUNNER_SMOKES_CALL) == []

    @pytest.mark.parametrize("line", [
        "python3 tools/validate/run_checks.py --context local",
        "python3 tools/validate/run_checks.py --context ci --base origin/main --only secrets",
        "python3 tools/validate/run_checks.py --context ci --base origin/main || true",
    ])
    def test_unrecognised_runner_form_fails_loud(self, tmp_path, line):
        # Expanding any other form to the full list would claim gates it does not run.
        with pytest.raises(ValueError, match="run_checks.py"):
            self._parse(tmp_path, line)


class TestStripVolatile:
    """The catalog embeds a git-log date per validator, so its rendered form is a
    function of repo HISTORY, not repo CONTENTS. A byte-exact --check therefore
    failed on branches that changed nothing relevant (confirmed on PR #421: local
    --check passed, CI failed, and the entire diff was one date flipping for
    check_tml.py, which that PR never touched).

    These tests pin the property BL-192 asked for: a catalog generated at commit A
    must still pass --check at commit B when B differs only by an unrelated
    validator's history.
    """

    HEADER = "| # | Gate | Description | When it runs | Why it exists | Mode | Last modified |"
    SEP = "|---|---|---|---|---|---|---|"

    def _row(self, n, label, mode="gate", date="2026-06-13"):
        return f"| {n} | `{label}` | desc | always (pre-commit) | why | {mode} | {date} |"

    def test_date_difference_alone_is_not_stale(self):
        """The exact PR #421 failure: one row's date moved, nothing else."""
        a = "\n".join([self.HEADER, self.SEP, self._row(1, "TML structure", date="2026-06-13")])
        b = "\n".join([self.HEADER, self.SEP, self._row(1, "TML structure", date="2026-07-30")])

        assert a != b, "fixtures must actually differ, or this test proves nothing"
        assert strip_volatile(a) == strip_volatile(b)

    def test_soft_row_date_difference_is_not_stale(self):
        """Warn-only rows render as `soft`; their dates are just as volatile."""
        a = "\n".join([self.HEADER, self.SEP, self._row(1, "pr size", mode="soft", date="unknown")])
        b = "\n".join([self.HEADER, self.SEP, self._row(1, "pr size", mode="soft", date="2026-10-08")])
        assert strip_volatile(a) == strip_volatile(b)

    def test_structural_difference_is_still_stale(self):
        """The gate must keep doing its real job — finding 7.1's actual intent."""
        a = "\n".join([self.HEADER, self.SEP, self._row(1, "TML structure")])
        b = "\n".join([self.HEADER, self.SEP, self._row(1, "backlog integrity")])

        assert strip_volatile(a) != strip_volatile(b)

    def test_added_gate_row_is_still_stale(self):
        a = "\n".join([self.HEADER, self.SEP, self._row(1, "secrets")])
        b = "\n".join([self.HEADER, self.SEP, self._row(1, "secrets"), self._row(2, "new gate")])

        assert strip_volatile(a) != strip_volatile(b)

    def test_mode_change_is_still_stale(self):
        """A gate downgraded to a nudge is exactly what must not slip through."""
        a = "\n".join([self.HEADER, self.SEP, self._row(1, "open items", mode="gate")])
        b = "\n".join([self.HEADER, self.SEP, self._row(1, "open items", mode="nudge")])

        assert strip_volatile(a) != strip_volatile(b)

    def test_prose_tables_pass_through_untouched(self):
        """The document also holds non-gate tables (enforcement model, audit
        checklist). If those were normalised too, a real edit to them would stop
        being gated."""
        prose = "| **CI (`validate.yml`)** | **Hard gate** — branch protection requires it |"

        assert strip_volatile(prose) == prose

    def test_non_table_lines_pass_through_untouched(self):
        text = "# Quality Gates Catalog\n\nAuto-generated. Do not edit manually.\n"

        assert strip_volatile(text) == text

    def test_nudge_and_report_rows_are_normalised_too(self):
        for mode in ("nudge", "report"):
            a = "\n".join([self.HEADER, self.SEP, self._row(1, "x", mode=mode, date="2026-01-01")])
            b = "\n".join([self.HEADER, self.SEP, self._row(1, "x", mode=mode, date="2026-09-09")])

            assert strip_volatile(a) == strip_volatile(b), f"mode={mode} not normalised"
