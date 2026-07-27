"""Tests for generate_open_items_index.py parsing logic."""
from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pytest

# Add validate dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generate_open_items_index import (
    _extract_needs,
    _extract_title,
    _normalise_status,
    parse_open_items,
)


# ---------------------------------------------------------------------------
# _normalise_status
# ---------------------------------------------------------------------------

class TestNormaliseStatus:
    def test_open(self):
        assert _normalise_status("Title — OPEN") == "OPEN"

    def test_verified(self):
        assert _normalise_status("Title — VERIFIED") == "VERIFIED"

    def test_verified_with_date(self):
        assert _normalise_status("Title — VERIFIED 2026-07-01") == "VERIFIED"

    def test_verified_via_mcp(self):
        assert _normalise_status("Title — VERIFIED via MCP 2026-07-22") == "VERIFIED"

    def test_spec_verified(self):
        assert _normalise_status("Title — SPEC-VERIFIED via MCP 2026-07-22") == "SPEC-VERIFIED"

    def test_deferred(self):
        assert _normalise_status("Title — DEFERRED") == "DEFERRED"

    def test_fixed(self):
        assert _normalise_status("Title — FIXED 2026-07-08") == "FIXED"

    def test_open_known_limitation(self):
        assert _normalise_status("Title — OPEN (known limitation)") == "OPEN"

    def test_unverified(self):
        assert _normalise_status("Title — UNVERIFIED") == "UNVERIFIED"

    def test_not_implemented(self):
        assert _normalise_status("Title — NOT IMPLEMENTED (LOW)") == "NOT IMPLEMENTED"

    def test_to_verify(self):
        assert _normalise_status("Title — TO VERIFY") == "TO VERIFY"

    def test_no_status_defaults_open(self):
        assert _normalise_status("Some title with no status marker") == "OPEN"

    def test_status_word_in_title_not_matched(self):
        """Status words in the title (before last em-dash) must not be picked up."""
        assert _normalise_status("Verified TS formula — OPEN") == "OPEN"

    def test_confirmed_in_title_not_matched(self):
        assert _normalise_status("Confirmed behaviour X — DEFERRED") == "DEFERRED"

    def test_implemented_with_date(self):
        assert _normalise_status("Title — IMPLEMENTED 2026-07-12") == "IMPLEMENTED"

    def test_partially_implemented(self):
        assert _normalise_status("Title — PARTIALLY IMPLEMENTED (LOW)") == "PARTIALLY IMPLEMENTED"

    def test_wired(self):
        assert _normalise_status("Title — WIRED; import bugs FIXED") == "WIRED"


# ---------------------------------------------------------------------------
# _extract_title
# ---------------------------------------------------------------------------

class TestExtractTitle:
    def test_simple(self):
        assert _extract_title("Some title — OPEN") == "Some title"

    def test_with_backticks(self):
        assert _extract_title("`sql_view` tables — OPEN") == "`sql_view` tables"

    def test_multiple_dashes(self):
        assert _extract_title("Title — subtitle — VERIFIED") == "Title"

    def test_no_dash(self):
        assert _extract_title("Just a title") == "Just a title"


# ---------------------------------------------------------------------------
# _extract_needs
# ---------------------------------------------------------------------------

class TestExtractNeeds:
    def test_single_tag(self):
        assert _extract_needs("Title — OPEN [needs: live-ts]") == ["live-ts"]

    def test_multiple_tags(self):
        assert _extract_needs("Title — OPEN [needs: live-ts, mcp-check]") == [
            "live-ts", "mcp-check"
        ]

    def test_no_tag(self):
        assert _extract_needs("Title — OPEN") == []

    def test_case_insensitive(self):
        assert _extract_needs("Title — OPEN [Needs: Live-TS]") == ["Live-TS"]


# ---------------------------------------------------------------------------
# parse_open_items — dedup and full parse
# ---------------------------------------------------------------------------

class TestParseOpenItems:
    def test_basic_parse(self, tmp_path):
        f = tmp_path / "open-items.md"
        f.write_text(dedent("""\
            # Open Items

            ## #1 — Widget support — OPEN

            Description here.

            ## #2 — Gadget fix — VERIFIED 2026-07-01

            Fixed it.
        """))
        items = parse_open_items(f)
        assert len(items) == 2
        assert items[0]["num"] == 1
        assert items[0]["status"] == "OPEN"
        assert items[0]["title"] == "Widget support"
        assert items[1]["num"] == 2
        assert items[1]["status"] == "VERIFIED"

    def test_dedup_keeps_most_resolved(self, tmp_path):
        f = tmp_path / "open-items.md"
        f.write_text(dedent("""\
            # Phase 1

            ### #1 — Bulk search — VERIFIED

            Confirmed working.

            # Phase 2

            ### #1 — Bulk search — UNVERIFIED

            Not yet tested on build X.
        """))
        items = parse_open_items(f)
        assert len(items) == 1
        assert items[0]["status"] == "VERIFIED"

    def test_historical_skipped(self, tmp_path):
        f = tmp_path / "open-items.md"
        f.write_text(dedent("""\
            ## #5 — Feature X — VERIFIED 2026-07-13

            Confirmed.

            ## #5 (historical) — original OPEN text

            Old text here.
        """))
        items = parse_open_items(f)
        assert len(items) == 1
        assert items[0]["status"] == "VERIFIED"

    def test_needs_tag_parsed(self, tmp_path):
        f = tmp_path / "open-items.md"
        f.write_text(dedent("""\
            ## #3 — Live test needed — OPEN [needs: live-ts]

            Needs a live instance.
        """))
        items = parse_open_items(f)
        assert items[0]["needs"] == ["live-ts"]

    def test_triple_hash_headers(self, tmp_path):
        f = tmp_path / "open-items.md"
        f.write_text(dedent("""\
            ### #7 — Column security — UNVERIFIED

            Test pending.
        """))
        items = parse_open_items(f)
        assert len(items) == 1
        assert items[0]["num"] == 7
        assert items[0]["status"] == "UNVERIFIED"

    def test_empty_file(self, tmp_path):
        f = tmp_path / "open-items.md"
        f.write_text("# Open Items\n\nNo items yet.\n")
        items = parse_open_items(f)
        assert items == []

    def test_status_in_title_not_misclassified(self, tmp_path):
        f = tmp_path / "open-items.md"
        f.write_text(dedent("""\
            ## #13 — Verified TS growth formula — OPEN

            Still needs live test.
        """))
        items = parse_open_items(f)
        assert len(items) == 1
        assert items[0]["status"] == "OPEN"
        assert "Verified TS growth formula" in items[0]["title"]
