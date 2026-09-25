"""The Ossie function mapping here, versus the one the converter actually ships.

Two hand-maintained accounts of one ruleset in two repositories, with nothing
comparing them since the converter was donated to the ASF.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_MODULE = pathlib.Path(__file__).resolve().parents[1] / "check_ossie_mapping_sync.py"
_spec = importlib.util.spec_from_file_location("_ossie_mapping_sync", _MODULE)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

HEADER = "| Construct | Class | Rendering | Note |\n|---|---|---|---|\n"


def _doc(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(HEADER + "".join(f"| `{c}` | {k} | x | y |\n" for c, k in rows), encoding="utf-8")
    return p


class TestClassifications:
    def test_rows_are_read(self, tmp_path):
        p = _doc(tmp_path, "m.md", [("SUM(expr)", "direct"), ("LAG(x)", "passthrough")])
        assert mod.classifications(p) == {"SUM(expr)": "direct", "LAG(x)": "passthrough"}

    def test_the_first_occurrence_wins(self, tmp_path):
        # Both documents repeat a few constructs in prose tables after the main
        # one; the main table comes first.
        p = _doc(tmp_path, "m.md", [("SUM(expr)", "direct"), ("SUM(expr)", "passthrough")])
        assert mod.classifications(p)["SUM(expr)"] == "direct"

    def test_a_row_with_no_classification_is_ignored(self, tmp_path):
        p = tmp_path / "m.md"
        p.write_text(HEADER + "| `Section heading` | 18 | 12 | 6 |\n", encoding="utf-8")
        assert mod.classifications(p) == {}


class TestFindUpstream:
    def test_an_explicit_root_wins(self, tmp_path):
        doc = tmp_path / mod.UPSTREAM
        doc.parent.mkdir(parents=True)
        doc.write_text(HEADER, encoding="utf-8")
        assert mod.find_upstream(str(tmp_path)) == doc

    def test_a_missing_checkout_is_none_not_an_error(self, tmp_path):
        # It must never turn "you have not cloned apache/ossie" into a failure.
        assert mod.find_upstream(str(tmp_path / "nope")) is None


class TestMain:
    @staticmethod
    def _repo(tmp_path, ours_rows):
        (tmp_path / "docs/ossie").mkdir(parents=True)
        _doc(tmp_path / "docs/ossie", "ts-ossie-function-mapping.md", ours_rows)
        return tmp_path

    @staticmethod
    def _upstream(tmp_path, rows):
        root = tmp_path / "ossie"
        (root / mod.UPSTREAM).parent.mkdir(parents=True)
        _doc((root / mod.UPSTREAM).parent, "expression-mapping.md", rows)
        return root

    def _run(self, monkeypatch, repo, ossie, check):
        argv = ["x", "--root", str(repo)]
        if ossie:
            argv += ["--ossie-root", str(ossie)]
        if check:
            argv.append("--check")
        monkeypatch.setattr(sys, "argv", argv)
        monkeypatch.delenv("OSSIE_ROOT", raising=False)
        return mod.main()

    def test_agreement_passes(self, tmp_path, monkeypatch, capsys):
        repo = self._repo(tmp_path, [("SUM(expr)", "direct")])
        up = self._upstream(tmp_path, [("SUM(expr)", "direct")])
        assert self._run(monkeypatch, repo, up, True) == 0
        assert "agrees" in capsys.readouterr().out

    def test_a_disagreement_fails_under_check(self, tmp_path, monkeypatch, capsys):
        # THE case. Our doc saying `direct` where the shipped converter says
        # `passthrough` tells a reader to write a native formula the converter
        # has established does not work.
        repo = self._repo(tmp_path, [("SUM(expr)", "direct")])
        up = self._upstream(tmp_path, [("SUM(expr)", "passthrough")])
        assert self._run(monkeypatch, repo, up, True) == 1
        out = capsys.readouterr().out
        assert "disagrees" in out and "SUM(expr)" in out

    def test_a_disagreement_only_warns_without_check(self, tmp_path, monkeypatch, capsys):
        repo = self._repo(tmp_path, [("SUM(expr)", "direct")])
        up = self._upstream(tmp_path, [("SUM(expr)", "passthrough")])
        assert self._run(monkeypatch, repo, up, False) == 0
        assert "disagrees" in capsys.readouterr().out

    def test_a_missing_upstream_skips_rather_than_failing(self, tmp_path, monkeypatch, capsys):
        repo = self._repo(tmp_path, [("SUM(expr)", "direct")])
        assert self._run(monkeypatch, repo, tmp_path / "nope", True) == 0
        assert "Skipping" in capsys.readouterr().out

    def test_a_presence_gap_alone_never_fails(self, tmp_path, monkeypatch, capsys):
        # The two spell operators differently (`!=` vs `a != b`), so a presence
        # gap is naming convention, not drift. It is context, never a defect.
        repo = self._repo(tmp_path, [("a != b", "direct")])
        up = self._upstream(tmp_path, [("!=", "direct")])
        assert self._run(monkeypatch, repo, up, True) == 0
        assert "only here" in capsys.readouterr().out
