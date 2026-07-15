"""Unit tests for the ALLOWLIST BL-reference gate in check_smoke_tests.py (audit 6.3).

The two-bucket rule (`.claude/rules/repo-audit.md`) says every audit finding must exit to
either a permanent validator or a dated backlog item. `ts-convert-from-looker`'s ALLOWLIST
entry violated this — a non-credential-setup smoke-test exemption with no `BL-NNN`
reference. `check_allowlist_bl_references()` re-parses this validator's own source (the
runtime `set` literal drops trailing `# ...` comments) and fails any non-credential entry
whose comment doesn't cite a dated backlog item. Credential-setup skills (`ts-profile-*`)
are exempt — they have no API mutation flow to defer.

These tests feed the checking function synthetic ALLOWLIST-block source strings rather
than mutating the real file, per the function's `source_text: str` signature.
"""
from pathlib import Path

import check_smoke_tests

REPO = Path(__file__).resolve().parents[3]


def _source(allowlist_body: str) -> str:
    """Wrap a bare ALLOWLIST literal body in a minimal, ast-parseable module source."""
    return f"ALLOWLIST = {{\n{allowlist_body}\n}}\n"


def test_non_credential_entry_without_bl_reference_fails():
    source = _source(
        '    "ts-convert-from-looker",   # community contribution PR #201 — no ref\n'
    )
    failures, info = check_smoke_tests.check_allowlist_bl_references(source)

    assert not info
    assert len(failures) == 1
    assert "ts-convert-from-looker" in failures[0]
    assert "FAIL" in failures[0]


def test_same_entry_with_bl_reference_passes():
    source = _source(
        '    "ts-convert-from-looker",   # smoke test deferred — BL-123 (filed 2026-07-11)\n'
    )
    failures, info = check_smoke_tests.check_allowlist_bl_references(source)

    assert not failures
    assert len(info) == 1
    assert "PASS" in info[0]
    assert "ts-convert-from-looker" in info[0]
    assert "BL-123" in info[0]


def test_profile_prefix_entry_without_bl_reference_passes_credential_exemption():
    # ts-profile-* is the credential-setup exemption — no BL-NNN required, and this must
    # hold for a name NOT in the current four (BL requirement is prefix-based, not a
    # hardcoded name list — a future ts-profile-bigquery is covered automatically).
    source = _source(
        '    "ts-profile-bigquery",   # interactive credential setup\n'
    )
    failures, info = check_smoke_tests.check_allowlist_bl_references(source)

    assert not failures
    assert len(info) == 1
    assert "PASS" in info[0]
    assert "credential-setup exemption" in info[0]


def test_mixed_block_reports_only_the_missing_entry():
    source = _source(
        '    "ts-profile-thoughtspot",   # interactive credential setup\n'
        '    "ts-object-answer-promote", # legacy gap; BL-076 (filed 2026-07-03)\n'
        '    "ts-convert-from-tableau",  # requires fixture; no ref here\n'
    )
    failures, info = check_smoke_tests.check_allowlist_bl_references(source)

    assert len(failures) == 1
    assert "ts-convert-from-tableau" in failures[0]
    assert len(info) == 2
    passed_skills = {line.split()[1] for line in info}
    assert passed_skills == {"ts-profile-thoughtspot", "ts-object-answer-promote"}


def test_real_file_passes_the_gate():
    """Integration check: the actual check_smoke_tests.py ALLOWLIST (post Part A fix,
    BL-115 added to ts-convert-from-looker) must satisfy its own rule with zero failures."""
    self_source = (REPO / "tools" / "validate" / "check_smoke_tests.py").read_text(
        encoding="utf-8"
    )
    failures, info = check_smoke_tests.check_allowlist_bl_references(self_source)

    assert not failures, failures
    # Every current ALLOWLIST member should show up as a PASS line.
    assert len(info) == len(check_smoke_tests.ALLOWLIST)


def test_main_exits_zero_for_the_real_repo(capsys):
    """End-to-end: main() runs both the smoke-test-presence check and the new BL-reference
    gate against the real repo and must exit 0 (Part D — confirms the new check runs
    inside the existing entry point, not a separate function nobody calls)."""
    import sys

    argv = sys.argv
    sys.argv = ["check_smoke_tests.py", "--root", str(REPO)]
    try:
        exit_code = check_smoke_tests.main()
    finally:
        sys.argv = argv

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "BL-NNN reference" in out
