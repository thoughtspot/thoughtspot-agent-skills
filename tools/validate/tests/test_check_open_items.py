"""Unit tests for check_open_items — header styles + unresolved-status detection.

Regression guard for the audit finding that the validator only matched `## Item N`
headers and so silently ignored 6 of 7 open-items files (which use `## #N`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_open_items  # noqa: E402


def _write(tmp_path: Path, body: str) -> Path:
    f = tmp_path / "open-items.md"
    f.write_text(body, encoding="utf-8")
    return f


def test_hash_n_header_with_needs_verification_is_flagged(tmp_path):
    # `## #N` style — the format the old regex missed entirely.
    f = _write(tmp_path, "# Open Items\n\n## #5 — Answer TML import — NEEDS VERIFICATION\n\nblah\n")
    res = check_open_items.check_open_items_file(f)
    assert len(res) == 1
    assert res[0][0].startswith("#5")
    assert "NEEDS VERIFICATION" in res[0][1]


def test_item_n_header_with_untested_is_flagged(tmp_path):
    # `## Item N` + `**Status:** UNTESTED` — the one format the old regex caught.
    f = _write(tmp_path, "## Item 4 — Embedded answers\n\n**Status:** UNTESTED\n")
    res = check_open_items.check_open_items_file(f)
    assert len(res) == 1 and "UNTESTED" in res[0][1]


def test_bare_not_implemented_marker_is_flagged(tmp_path):
    # No decision qualifier (no LOW/WONT-FIX/DEFERRED/Workaround) — a genuine gap.
    f = _write(tmp_path, "## #2 — Custom instructions — NOT IMPLEMENTED\n\nno TS equivalent\n")
    res = check_open_items.check_open_items_file(f)
    assert len(res) == 1 and res[0][1] == "Status: NOT IMPLEMENTED"


def test_not_implemented_with_low_qualifier_is_resolved(tmp_path):
    # Regression guard for the audit finding (PR #210 / 2026-07-11 sweep): a
    # `NOT IMPLEMENTED (LOW)` item with a documented Workaround is a deliberate
    # non-goal, not an unresolved gap — mirrors from-snowflake-sv items #2-#5.
    f = _write(
        tmp_path,
        "## #2 — Custom instructions mapping — NOT IMPLEMENTED (LOW)\n\n"
        "The skill does not parse or map custom instructions.\n\n"
        "**Workaround:** run another skill to fill the gap.\n\n"
        "Status: NOT IMPLEMENTED — LOW priority (post-conversion coaching covers the gap)\n",
    )
    res = check_open_items.check_open_items_file(f)
    assert res == []


def test_not_implemented_with_only_low_qualifier_is_resolved(tmp_path):
    # The `(LOW)` qualifier alone (no Workaround line) is sufficient on its own —
    # the qualifiers are OR'd, not required in combination.
    f = _write(tmp_path, "## #6 — Some corner case — NOT IMPLEMENTED (LOW)\n\nno TS equivalent\n")
    res = check_open_items.check_open_items_file(f)
    assert res == []


def test_not_implemented_with_only_workaround_is_resolved(tmp_path):
    # A documented Workaround alone (no LOW/WONT-FIX/DEFERRED tag) is also sufficient.
    f = _write(
        tmp_path,
        "## #7 — Another gap — NOT IMPLEMENTED\n\n"
        "**Workaround:** do the equivalent thing manually.\n",
    )
    res = check_open_items.check_open_items_file(f)
    assert res == []


def test_not_implemented_with_wontfix_or_deferred_is_resolved(tmp_path):
    f = _write(
        tmp_path,
        "## #8 — Wont-fix case — NOT IMPLEMENTED, WONT-FIX\n\nsuperseded by another approach.\n\n"
        "## #9 — Deferred case — NOT IMPLEMENTED (DEFERRED to a future release)\n\nfuture work.\n",
    )
    res = check_open_items.check_open_items_file(f)
    assert res == []


def test_placeholder_is_flagged(tmp_path):
    f = _write(tmp_path, "## #3 — Something\n\nFinding: [Record result here]\n")
    res = check_open_items.check_open_items_file(f)
    assert len(res) == 1 and res[0][1] == "Finding not recorded"


def test_verified_and_open_items_are_not_flagged(tmp_path):
    # VERIFIED → resolved. Plain OPEN/DEFERRED → deliberately-tracked, not a
    # shipped-unverified-assumption violation, so not flagged.
    f = _write(
        tmp_path,
        "## #1 — Done thing — VERIFIED 2026-06-12\n\nconfirmed\n\n"
        "## #2 — Tracked enhancement — OPEN\n\ndeferred feature\n",
    )
    res = check_open_items.check_open_items_file(f)
    assert res == []


def test_marker_not_matched_as_substring(tmp_path):
    # "UNVERIFIED" must not match inside a larger word; a clean section is empty.
    f = _write(tmp_path, "## #9 — Notes\n\nThis is verified and shipped.\n")
    res = check_open_items.check_open_items_file(f)
    assert res == []
