"""Tests for check_file_size's RATCHET (audit finding 4.3).

`check_file_size` had no test file at all, which is part of why the defect survived:
the gate stored `path -> backlog_id`, so an exempt module could grow without bound
while it reported PASS. `commands/tableau.py` was allowlisted at 1063 lines and
reached 1675 (+58%) green throughout.

These pin the ratchet semantics: growth past the recorded size fails, at-or-below
passes, and a non-ratcheted file still hits the plain hard fail.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_file_size as fs  # noqa: E402


def _module(tmp_path, rel, lines):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join("# x" for _ in range(lines)) + "\n", encoding="utf-8")
    return rel


def test_a_non_ratcheted_module_over_hard_fail_still_fails(tmp_path, capsys, monkeypatch):
    rel = _module(tmp_path, f"{fs.SCAN_ROOT}/big.py", fs.HARD_FAIL + 50)
    monkeypatch.setattr(fs, "RATCHET", {})
    monkeypatch.setattr(sys, "argv", ["check_file_size.py", "--root", str(tmp_path)])
    assert fs.main() == 1
    assert "FAIL" in capsys.readouterr().out
    assert rel


def test_a_ratcheted_module_at_its_recorded_size_passes(tmp_path, capsys, monkeypatch):
    n = fs.HARD_FAIL + 50
    rel = _module(tmp_path, f"{fs.SCAN_ROOT}/big.py", n)
    monkeypatch.setattr(fs, "RATCHET", {rel: (n, "BL-089")})
    monkeypatch.setattr(sys, "argv", ["check_file_size.py", "--root", str(tmp_path)])
    assert fs.main() == 0
    assert "WARN" in capsys.readouterr().out          # still soft-warns


def test_a_ratcheted_module_that_grew_fails(tmp_path, capsys, monkeypatch):
    """The whole point: an exemption is a debt ceiling, not a licence to grow."""
    n = fs.HARD_FAIL + 50
    rel = _module(tmp_path, f"{fs.SCAN_ROOT}/big.py", n)
    monkeypatch.setattr(fs, "RATCHET", {rel: (n - 10, "BL-089")})
    monkeypatch.setattr(sys, "argv", ["check_file_size.py", "--root", str(tmp_path)])
    assert fs.main() == 1
    out = capsys.readouterr().out
    assert "GREW" in out and "BL-089" in out and "+10" in out


def test_shrinking_below_the_recorded_size_is_free(tmp_path, capsys, monkeypatch):
    n = fs.HARD_FAIL + 50
    rel = _module(tmp_path, f"{fs.SCAN_ROOT}/big.py", n)
    monkeypatch.setattr(fs, "RATCHET", {rel: (n + 500, "BL-089")})
    monkeypatch.setattr(sys, "argv", ["check_file_size.py", "--root", str(tmp_path)])
    assert fs.main() == 0


def test_the_real_repo_entry_matches_the_real_file(tmp_path):
    """A stale recorded value would silently re-open the same hole."""
    repo_root = Path(__file__).resolve().parents[3]
    for rel, (recorded, _ref) in fs.RATCHET.items():
        actual = sum(1 for _ in (repo_root / rel).open(encoding="utf-8"))
        assert actual <= recorded, (
            f"{rel} is {actual} lines but RATCHET records {recorded} — the repo is "
            f"already over its own ceiling"
        )
