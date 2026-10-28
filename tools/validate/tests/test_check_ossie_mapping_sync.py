"""The Ossie function mapping here, versus the one the converter actually ships.

Two hand-maintained accounts of one ruleset in two repositories, with nothing
comparing them since the converter was donated to the ASF.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_MODULE = pathlib.Path(__file__).resolve().parents[1] / "check_ossie_mapping_sync.py"
_spec = importlib.util.spec_from_file_location("_ossie_mapping_sync", _MODULE)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

HEADER = "| Construct | Class | Rendering | Note |\n|---|---|---|---|\n"


@pytest.fixture(autouse=True)
def _no_machine_checkout(monkeypatch):
    # find_upstream also searches CONVENTIONAL and $OSSIE_ROOT, which are real paths on a
    # developer machine; a real ../ossie checkout made the "missing" cases find it.
    monkeypatch.setattr(mod, "CONVENTIONAL", ())
    monkeypatch.delenv("OSSIE_ROOT", raising=False)


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
    @pytest.mark.parametrize("layout", mod.UPSTREAM_CANDIDATES)
    def test_an_explicit_root_wins_in_either_repo_layout(self, tmp_path, layout):
        # Both are live: `thoughtspot/docs/...` is apache/ossie-converters as
        # of the 2026-10-21 split, and `converters/thoughtspot/docs/...` still
        # resolves against a checkout that predates it.
        doc = tmp_path / layout
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
        relative = mod.UPSTREAM_CANDIDATES[0]
        (root / relative).parent.mkdir(parents=True)
        _doc((root / relative).parent, "expression-mapping.md", rows)
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
        out = capsys.readouterr().out
        assert "Skipping" in out
        # run_checks.classify() reads a line starting `SKIP` as "did not compare";
        # without one, a run that compared nothing would report PASS.
        assert any(line.startswith("SKIP ") for line in out.splitlines())

    def test_a_missing_doc_of_ours_fails(self, tmp_path, monkeypatch, capsys):
        # OURS lives in this repo; its absence is a broken repo or a bad --root,
        # not an optional prerequisite, so it must not read as a pass.
        up = self._upstream(tmp_path, [("SUM(expr)", "direct")])
        assert self._run(monkeypatch, tmp_path / "empty", up, True) == 1
        out = capsys.readouterr().out
        assert any(line.startswith("FAIL") for line in out.splitlines())
        assert mod.OURS in out

    def test_a_presence_gap_alone_never_fails(self, tmp_path, monkeypatch, capsys):
        # The two spell operators differently (`!=` vs `a != b`), so a presence
        # gap is naming convention, not drift. It is context, never a defect.
        repo = self._repo(tmp_path, [("a != b", "direct")])
        up = self._upstream(tmp_path, [("!=", "direct")])
        assert self._run(monkeypatch, repo, up, True) == 0
        assert "only here" in capsys.readouterr().out


class TestKnownDivergences:
    """A deliberate, evidenced divergence must not make the gate cry wolf on
    every run -- that is how a gate stops being read. But an allowlist that
    silences anything beyond its entries is worse than no gate at all, so each
    of these pins one half of that bargain.
    """

    _run = TestMain._run
    _repo = staticmethod(TestMain._repo)
    _upstream = staticmethod(TestMain._upstream)

    def test_a_listed_divergence_passes_and_is_reported(
        self, tmp_path, monkeypatch, capsys,
    ):
        monkeypatch.setattr(
            mod, "KNOWN_DIVERGENCES", {"str LIKE pattern": ("passthrough", "direct")}
        )
        repo = self._repo(tmp_path, [("str LIKE pattern", "passthrough")])
        up = self._upstream(tmp_path, [("str LIKE pattern", "direct")])
        assert self._run(monkeypatch, repo, up, True) == 0
        out = capsys.readouterr().out
        assert "Known divergence" in out and "str LIKE pattern" in out
        assert "disagrees" not in out

    def test_an_unlisted_disagreement_still_fails(self, tmp_path, monkeypatch, capsys):
        # The allowlist must exempt its entries and nothing else.
        monkeypatch.setattr(
            mod, "KNOWN_DIVERGENCES", {"str LIKE pattern": ("passthrough", "direct")}
        )
        repo = self._repo(
            tmp_path, [("str LIKE pattern", "passthrough"), ("SUM(expr)", "direct")]
        )
        up = self._upstream(
            tmp_path, [("str LIKE pattern", "direct"), ("SUM(expr)", "passthrough")]
        )
        assert self._run(monkeypatch, repo, up, True) == 1
        assert "SUM(expr)" in capsys.readouterr().out

    def test_a_divergence_listed_the_wrong_way_round_still_fails(
        self, tmp_path, monkeypatch, capsys,
    ):
        # An entry exempts one specific (ours, theirs) pair. If upstream
        # re-decides and the pair inverts, that is a new fact, not the one
        # that was signed off.
        monkeypatch.setattr(
            mod, "KNOWN_DIVERGENCES", {"str LIKE pattern": ("passthrough", "direct")}
        )
        repo = self._repo(tmp_path, [("str LIKE pattern", "direct")])
        up = self._upstream(tmp_path, [("str LIKE pattern", "passthrough")])
        assert self._run(monkeypatch, repo, up, True) == 1
        assert "disagrees" in capsys.readouterr().out

    def test_an_entry_that_no_longer_diverges_is_reported_as_stale(
        self, tmp_path, monkeypatch, capsys,
    ):
        # Upstream adopted our reading. The exemption now shields nothing and
        # should go, or it will silently cover some future disagreement.
        monkeypatch.setattr(
            mod, "KNOWN_DIVERGENCES", {"str LIKE pattern": ("passthrough", "direct")}
        )
        repo = self._repo(tmp_path, [("str LIKE pattern", "passthrough")])
        up = self._upstream(tmp_path, [("str LIKE pattern", "passthrough")])
        assert self._run(monkeypatch, repo, up, True) == 0
        assert "no longer describe" in capsys.readouterr().out

    def test_the_shipped_entries_name_real_constructs(self):
        # A typo in a construct name would make an entry exempt nothing while
        # looking like it does. Every key must appear in our own mapping doc.
        ours = mod.classifications(
            pathlib.Path(__file__).resolve().parents[3] / mod.OURS
        )
        unknown = sorted(set(mod.KNOWN_DIVERGENCES) - set(ours))
        assert not unknown, f"KNOWN_DIVERGENCES names constructs {mod.OURS} does not: {unknown}"
