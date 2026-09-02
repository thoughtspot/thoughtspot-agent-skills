"""Tests for check_lint_invariant_list.py.

The validator exists because `ts tml lint`'s rule set was hand-restated in ~11
places and drifted twice — I14 for weeks, then I15 across eight sites when BL-232
landed. Neither changed behaviour (every caller runs `lint_tml`, which runs every
rule), but a skill understating the gate invites a reader to hand-write a check
that already exists.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD = Path(__file__).resolve().parents[1] / "check_lint_invariant_list.py"
_spec = importlib.util.spec_from_file_location("cliv", _MOD)
cliv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cliv)


CANON = """\
\"\"\"Pre-import TML linter.

Most of these (I1/I2/I4/I5) are invariants VALIDATE_ONLY does NOT catch — a
meaningful SUBSET statement, which must not be mistaken for the full list.

CANONICAL-RULE-SET: {ruleset}
\"\"\"


def lint_tml(data):
    findings = []
    findings.append(f"I1: formula has no paired column")
    findings.append(f"I2: aggregation under formulas[]")
    findings.append(f"I15: column-root key inside properties")
    return findings
"""


def _repo(tmp_path: Path, ruleset: str, extra: dict[str, str] | None = None) -> Path:
    root = tmp_path / "repo"
    canon = root / "tools" / "ts-cli" / "ts_cli"
    canon.mkdir(parents=True)
    (canon / "tml_lint.py").write_text(CANON.format(ruleset=ruleset), encoding="utf-8")
    for rel, text in (extra or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def _run(root: Path) -> int:
    import sys
    argv = sys.argv
    sys.argv = ["check", "--root", str(root)]
    try:
        return cliv.main()
    finally:
        sys.argv = argv


class TestCorrectness:
    def test_marker_matching_the_emitted_rules_passes(self, tmp_path):
        assert _run(_repo(tmp_path, "I1/I2/I15")) == 0

    def test_marker_omitting_an_emitted_rule_fails(self, tmp_path):
        """The BL-232 shape: I15 lands in the code, the list is not updated."""
        assert _run(_repo(tmp_path, "I1/I2")) == 1

    def test_marker_claiming_an_unemitted_rule_fails(self, tmp_path):
        assert _run(_repo(tmp_path, "I1/I2/I15/I99")) == 1

    def test_missing_marker_fails_rather_than_silently_passing(self, tmp_path):
        root = _repo(tmp_path, "I1/I2/I15")
        f = root / "tools" / "ts-cli" / "ts_cli" / "tml_lint.py"
        f.write_text(f.read_text().replace("CANONICAL-RULE-SET: I1/I2/I15", "(none)"),
                     encoding="utf-8")
        assert _run(root) == 1

    def test_subset_prose_in_the_canonical_file_is_not_flagged(self, tmp_path):
        """`(I1/I2/I4/I5)` as 'most of these' is correct prose, not a stale list.
        Requiring every enumeration in the file to be complete flagged it — which
        is why the marker is explicit rather than inferred."""
        assert _run(_repo(tmp_path, "I1/I2/I15")) == 0


class TestSingularity:
    def test_a_restatement_in_live_prose_fails(self, tmp_path):
        root = _repo(tmp_path, "I1/I2/I15",
                     {"agents/cli/x/SKILL.md": "gate covers I1/I2/I4/I5/I8/I12/I13\n"})
        assert _run(root) == 1

    def test_a_short_cross_reference_is_allowed(self, tmp_path):
        """Naming two or three specific rules is a cross-reference, not a copy —
        mv_tml.py's "I4/I5/I8 belong to lint_tml" is legitimate."""
        root = _repo(tmp_path, "I1/I2/I15",
                     {"agents/cli/x/SKILL.md": "I4/I5/I8 belong to lint_tml\n"})
        assert _run(root) == 0

    def test_a_dated_changelog_row_is_allowed(self, tmp_path):
        """A changelog row states what was true on its date; rewriting it would
        falsify the record."""
        root = _repo(tmp_path, "I1/I2/I15", {
            "agents/cli/x/SKILL.md":
                "| 1.6.0 | 2026-06-12 | Add gate (I1/I2/I4/I5/I8/I12/I13) |\n"})
        assert _run(root) == 0

    def test_historical_paths_are_exempt(self, tmp_path):
        root = _repo(tmp_path, "I1/I2/I15", {
            "docs/audit/2026-06-17-full.md": "covered I1/I2/I4/I5/I8/I12/I13\n",
            "CHANGELOG.md": "gate covers I1/I2/I4/I5/I8/I12/I13\n",
            "agents/cli/x/references/open-items.md": "I1/I2/I4/I5/I8 today\n",
        })
        assert _run(root) == 0
