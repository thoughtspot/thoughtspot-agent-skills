"""Unit tests for check_orphan_references — the "cited by anything else in the
repo, or allowlisted by basename" guard (audit finding 1.1).

Key behaviours: an uncited references/*.md is flagged; one linked from a sibling
SKILL.md (or any other tracked-extension file) is not; open-items.md is exempt
by basename even when nothing links it; a fully clean tree exits 0.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_orphan_references as ck  # noqa: E402


def _make_skill(root: Path, runtime: str, skill: str) -> Path:
    skill_dir = root / "agents" / runtime / skill
    (skill_dir / "references").mkdir(parents=True)
    return skill_dir


def test_uncited_reference_file_is_flagged(tmp_path):
    skill_dir = _make_skill(tmp_path, "cli", "ts-x")
    (skill_dir / "references" / "orphan.md").write_text("nobody links me\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("no links here at all\n", encoding="utf-8")

    orphans, info = ck.check(tmp_path)
    assert any("orphan.md" in msg for msg in orphans)
    assert not any("orphan.md" in msg and msg.startswith("PASS") for msg in info)


def test_cited_reference_file_from_sibling_skill_md_is_not_flagged(tmp_path):
    skill_dir = _make_skill(tmp_path, "cli", "ts-y")
    (skill_dir / "references" / "used.md").write_text("real content\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "See [the reference](references/used.md) for details.\n", encoding="utf-8"
    )

    orphans, info = ck.check(tmp_path)
    assert orphans == []
    assert any(msg.startswith("PASS") and "used.md" in msg for msg in info)


def test_cited_by_full_repo_relative_path_is_not_flagged(tmp_path):
    skill_dir = _make_skill(tmp_path, "cli", "ts-z")
    (skill_dir / "references" / "check-catalog.md").write_text("body\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "Full path: agents/cli/ts-z/references/check-catalog.md\n", encoding="utf-8"
    )

    orphans, info = ck.check(tmp_path)
    assert orphans == []
    assert any("check-catalog.md" in msg and msg.startswith("PASS") for msg in info)


def test_uncited_open_items_is_allowlisted_not_flagged(tmp_path):
    skill_dir = _make_skill(tmp_path, "cli", "ts-w")
    (skill_dir / "references" / "open-items.md").write_text("tracking doc\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("no links to open-items here\n", encoding="utf-8")

    orphans, info = ck.check(tmp_path)
    assert orphans == []
    assert any(msg.startswith("SKIP") and "open-items.md" in msg for msg in info)


def test_direct_references_dir_under_runtime_root_is_scanned(tmp_path):
    # Mirrors agents/claude/references/direct-api-auth.md — a references/ dir
    # sitting directly under the runtime root, not nested under a skill dir.
    refs_dir = tmp_path / "agents" / "claude" / "references"
    refs_dir.mkdir(parents=True)
    (refs_dir / "direct-api-auth.md").write_text("body\n", encoding="utf-8")

    other_skill = _make_skill(tmp_path, "claude", "ts-profile-snowflake")
    (other_skill / "SKILL.md").write_text(
        "[direct-api-auth.md](../references/direct-api-auth.md)\n", encoding="utf-8"
    )

    orphans, info = ck.check(tmp_path)
    assert orphans == []
    assert any("direct-api-auth.md" in msg and msg.startswith("PASS") for msg in info)


def test_clean_tree_exits_zero(tmp_path):
    skill_dir = _make_skill(tmp_path, "cli", "ts-clean")
    (skill_dir / "references" / "clean.md").write_text("body\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "[clean](references/clean.md)\n", encoding="utf-8"
    )

    result = subprocess.run(
        [sys.executable, ck.__file__, "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_orphan_tree_exits_nonzero(tmp_path):
    skill_dir = _make_skill(tmp_path, "cli", "ts-dirty")
    (skill_dir / "references" / "dead.md").write_text("body\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("nothing links dead.md\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, ck.__file__, "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "dead.md" in result.stdout


def test_excluded_dirs_are_not_scanned_for_reference_files(tmp_path):
    # A references/*.md under an excluded dir name (e.g. a vendored copy under
    # node_modules) must not surface as a reference file to check at all.
    vendored = tmp_path / "agents" / "cli" / "ts-v" / "node_modules" / "pkg" / "references"
    vendored.mkdir(parents=True)
    (vendored / "vendored.md").write_text("body\n", encoding="utf-8")

    refs = ck.find_reference_files(tmp_path)
    assert not any("vendored.md" in str(p) for p in refs)
