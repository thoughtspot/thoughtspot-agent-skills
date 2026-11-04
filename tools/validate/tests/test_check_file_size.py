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


# ── BL-503: the audit report's JavaScript ───────────────────────────────────

REPORT = "tools/ts-cli/ts_cli/audit/report"


def _js(tmp_path, rel, body_lines, functions=()):
    """A JS file: each (name, length) in `functions` is a top-level `function` whose
    closing `}` is at column 0, `length` lines in all; then `body_lines` filler lines."""
    lines = []
    for name, length in functions:
        lines.append(f"function {name}(a){{")
        lines += ["  var x = '{';  /* a brace in a string */"] * (length - 2)
        lines.append("}")
    lines += ["// x"] * body_lines
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rel


def _run(tmp_path, monkeypatch, ratchet=None, func_ratchet=None):
    monkeypatch.setattr(fs, "RATCHET", ratchet or {})
    monkeypatch.setattr(fs, "JS_FUNCTION_RATCHET", func_ratchet or {})
    monkeypatch.setattr(sys, "argv", ["check_file_size.py", "--root", str(tmp_path)])
    return fs.main()


def test_report_js_over_the_hard_fail_fails(tmp_path, capsys, monkeypatch):
    _js(tmp_path, f"{REPORT}/views/huge.js", fs.HARD_FAIL + 1)
    assert _run(tmp_path, monkeypatch) == 1
    assert "huge.js" in capsys.readouterr().out


def test_report_js_over_the_soft_warn_warns(tmp_path, capsys, monkeypatch):
    _js(tmp_path, f"{REPORT}/views/big.js", fs.SOFT_WARN + 1)
    assert _run(tmp_path, monkeypatch) == 0
    assert "WARN  file size" in capsys.readouterr().out


def test_a_ratcheted_report_js_that_grew_fails(tmp_path, capsys, monkeypatch):
    rel = _js(tmp_path, f"{REPORT}/views/objectmap.js", 600)
    assert _run(tmp_path, monkeypatch, ratchet={rel: (590, "BL-503")}) == 1
    assert "GREW" in capsys.readouterr().out


def test_a_long_js_function_fails_and_a_warn_length_one_warns(tmp_path, capsys, monkeypatch):
    _js(tmp_path, f"{REPORT}/views/v.js", 0,
        functions=[("buildLong", fs.JS_FUNCTION_FAIL + 1), ("buildMid", fs.JS_FUNCTION_WARN + 1),
                   ("small", 10)])
    assert _run(tmp_path, monkeypatch) == 1
    out = capsys.readouterr().out
    assert "buildLong" in out and f"{fs.JS_FUNCTION_FAIL + 1} lines" in out
    assert "buildMid" in out and "small" not in out


def test_a_ratcheted_js_function_may_not_grow(tmp_path, capsys, monkeypatch):
    rel = _js(tmp_path, f"{REPORT}/views/v.js", 0, functions=[("buildBig", 300)])
    assert _run(tmp_path, monkeypatch, func_ratchet={(rel, "buildBig"): (300, "BL-503")}) == 0
    assert _run(tmp_path, monkeypatch, func_ratchet={(rel, "buildBig"): (290, "BL-503")}) == 1
    assert "buildBig" in capsys.readouterr().out


def test_js_function_lengths_reads_top_level_functions_only():
    text = "\n".join([
        "function outer(){",
        "  function inner(){",
        "    return '}';",
        "  }",
        "  return 1;",
        "}",
        "var a = 1;",
        "async function later(){ return 2; }",
        "function unclosed(){",
        "  x();",
    ])
    assert fs.js_function_lengths(text) == [("outer", 1, 6), ("later", 8, 1),
                                             ("unclosed", 9, 2)]


def test_the_real_js_function_ratchet_matches_the_real_files():
    repo_root = Path(__file__).resolve().parents[3]
    for (rel, name), (recorded, _ref) in fs.JS_FUNCTION_RATCHET.items():
        lengths = dict((n, ln) for n, _s, ln in
                       fs.js_function_lengths((repo_root / rel).read_text(encoding="utf-8")))
        assert name in lengths and lengths[name] <= recorded, (rel, name, lengths.get(name))
