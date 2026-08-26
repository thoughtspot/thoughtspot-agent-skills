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


def test_ratcheted_huge_skill_passes_at_or_below_its_recorded_size(tmp_path, monkeypatch, capsys):
    """A ratchet entry exempts the HARD_FAIL, but only up to the recorded size."""
    size = cc.HARD_FAIL + 1_000
    rel = _make_skill(tmp_path, "cli", "ts-convert-from-tableau", size)
    tokens = cc._est_tokens(str(tmp_path / rel))
    monkeypatch.setitem(cc.RATCHET, rel, (tokens, "BL-128"))
    assert cc.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "WARN" in out  # still soft-warns


def test_ratcheted_skill_that_grew_fails(tmp_path, monkeypatch, capsys):
    """The point of the change (audit 4.3): an allowlist recorded a backlog id, so an
    exempt file could grow without bound while the gate said PASS."""
    rel = _make_skill(tmp_path, "cli", "ts-convert-from-tableau", cc.HARD_FAIL + 1_000)
    tokens = cc._est_tokens(str(tmp_path / rel))
    monkeypatch.setitem(cc.RATCHET, rel, (tokens - 500, "BL-128"))
    assert cc.main(["--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "GREW" in out and "BL-128" in out


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
