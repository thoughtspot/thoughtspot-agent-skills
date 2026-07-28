"""Unit tests for check_skill_context_cost — SKILL.md estimated-token gate.

Key behaviours: pass small skills, warn between SOFT_WARN and HARD_FAIL,
fail above HARD_FAIL unless allowlisted (allowlisted still warns).
"""
import check_skill_context_cost as cc


def _make_skill(tmp_path, runtime, name, est_tokens):
    d = tmp_path / "agents" / runtime / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("x" * (est_tokens * cc.CHARS_PER_TOKEN), encoding="utf-8")
    return f"agents/{runtime}/{name}/SKILL.md"


def test_small_skill_passes(tmp_path, capsys):
    _make_skill(tmp_path, "cli", "ts-audit", 5_000)
    assert cc.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "0 warning(s)" in out


def test_oversized_skill_warns_but_passes(tmp_path, capsys):
    _make_skill(tmp_path, "cli", "ts-audit", cc.SOFT_WARN + 1_000)
    assert cc.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "WARN" in out and "BL-128" in out


def test_huge_skill_fails(tmp_path, capsys):
    _make_skill(tmp_path, "cli", "ts-audit", cc.HARD_FAIL + 1_000)
    assert cc.main(["--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out


def test_allowlisted_huge_skill_passes(tmp_path, monkeypatch, capsys):
    rel = _make_skill(tmp_path, "cli", "ts-convert-from-tableau", cc.HARD_FAIL + 1_000)
    monkeypatch.setitem(cc.ALLOWLIST, rel, "BL-128")
    assert cc.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "WARN" in out  # still soft-warns


def test_scans_all_runtimes(tmp_path, capsys):
    _make_skill(tmp_path, "cli", "ts-audit", 1_000)
    _make_skill(tmp_path, "claude", "ts-profile-snowflake", 1_000)
    _make_skill(tmp_path, "coco-snowsight", "ts-setup-sv", 1_000)
    assert cc.main(["--root", str(tmp_path)]) == 0
    assert "3 skill(s) checked" in capsys.readouterr().out


def test_non_skill_markdown_ignored(tmp_path, capsys):
    d = tmp_path / "agents" / "cli" / "ts-audit" / "references"
    d.mkdir(parents=True)
    (d / "open-items.md").write_text("x" * (cc.HARD_FAIL * cc.CHARS_PER_TOKEN * 2))
    assert cc.main(["--root", str(tmp_path)]) == 0
    assert "0 skill(s) checked" in capsys.readouterr().out
