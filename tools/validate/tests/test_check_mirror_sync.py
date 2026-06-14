"""Tests for check_mirror_sync.py functions."""
import textwrap
from pathlib import Path

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_mirror_sync as cms


def test_parse_marker_present(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text("# Title\n<!-- synced-from: agents/cli/foo/SKILL.md @ v1.2.3 on 2026-06-13 -->\n")
    result = cms.parse_marker(f)
    assert result == ("agents/cli/foo/SKILL.md", "1.2.3")


def test_parse_marker_absent(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text("# Title\nNo marker here.\n")
    assert cms.parse_marker(f) is None


def test_top_changelog_version(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text(textwrap.dedent("""\
        ## Changelog
        | Version | Date | Summary |
        |---|---|---|
        | 2.1.0 | 2026-06-13 | Latest |
        | 2.0.0 | 2026-06-01 | Major |
    """))
    assert cms.top_changelog_version(f) == "2.1.0"


def test_top_changelog_no_semver(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text("# Title\nNo changelog here.\n")
    assert cms.top_changelog_version(f) is None


def test_parse_version():
    assert cms.parse_version("1.2.3") == (1, 2, 3)
    assert cms.parse_version("2.0.0") > cms.parse_version("1.9.9")
    assert cms.parse_version("1.0.0") == cms.parse_version("1.0.0")


def test_load_sync_debt(tmp_path, monkeypatch):
    debt = tmp_path / "SYNC-DEBT.md"
    debt.write_text(textwrap.dedent("""\
        # Mirror sync debt
        | Mirror | At | CLI now | Gap | Decision |
        |---|---|---|---|---|
        | agents/coco-snowsight/foo/SKILL.md | v1.0.0 | v2.0.0 | big gap | sync |
    """))
    monkeypatch.setattr(cms, "ROOT", tmp_path)
    (tmp_path / "agents").mkdir()
    debt.rename(tmp_path / "agents" / "SYNC-DEBT.md")
    paths = cms.load_sync_debt()
    assert "agents/coco-snowsight/foo/SKILL.md" in paths


def test_load_sync_debt_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cms, "ROOT", tmp_path)
    assert cms.load_sync_debt() == set()
