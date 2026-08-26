"""Tests for check_converter_parity — the BL-217 gate.

The regression these encode is not hypothetical. The FIRST cut of this validator
asserted "emits `sql_*_op` -> must import wrap_passthrough_calls" and **passed on
PR #440's pre-review tree**, because that converter emitted no pass-through at all:
an absence-triggered rule cannot detect an absence. `test_forbidden_*` pins the
corrected, output-shaped rule; `test_routed_marker_is_not_flagged` pins the Qlik /
PowerBI shape it must NOT flag, which is what makes the rule usable at all.
"""
import subprocess
import sys
from pathlib import Path

VALIDATOR = Path(__file__).resolve().parents[1] / "check_converter_parity.py"


def _repo(tmp_path, platform, functions_src, *, skill=True):
    """Build a minimal fake repo with one converter."""
    if skill:
        (tmp_path / "agents" / "cli" / f"ts-convert-from-{platform}").mkdir(parents=True)
        (tmp_path / "agents" / "cli" / f"ts-convert-from-{platform}" / "SKILL.md").write_text("x")
    pkg = tmp_path / "tools" / "ts-cli" / "ts_cli" / platform.replace("-", "_")
    pkg.mkdir(parents=True)
    (pkg / "functions.py").write_text(functions_src)
    return tmp_path


def _run(root):
    return subprocess.run([sys.executable, str(VALIDATOR), "--root", str(root)],
                          capture_output=True, text=True)


# A converter that also emits formulas must carry the formula helpers; include them
# in the baseline so requirement B never masks a requirement-A assertion.
_HELPERS = ("from ts_cli.formula_common import (resolve_name_collisions, "
            "fix_double_aggregation)\nformulas = []\n")


def test_forbidden_bare_name_is_flagged(tmp_path):
    """#440's exact shape: `\"upper\": \"upper\"` with no pass-through anywhere."""
    root = _repo(tmp_path, "fake", _HELPERS + 'FUNCTION_MAP = {"upper": "upper"}\n')
    result = _run(root)
    assert result.returncode == 1
    assert "not a ThoughtSpot function" in result.stdout.lower() or \
           "NOT a ThoughtSpot function" in result.stdout
    assert "`upper`" in result.stdout


def test_every_disproved_name_is_covered(tmp_path):
    """All six BL-170/BL-171 names, not just the two the PR happened to hit."""
    for fn in ("upper", "lower", "trim", "ltrim", "rtrim", "replace"):
        root = _repo(tmp_path / fn, "fake", _HELPERS + f'M = {{"src": "{fn}"}}\n')
        result = _run(root)
        assert result.returncode == 1, f"{fn} was not flagged"
        assert f"`{fn}`" in result.stdout


def test_routed_marker_is_not_flagged(tmp_path):
    """The Qlik / PowerBI shape: the name is mapped, then routed to sql_string_op.

    This is correct and must pass, otherwise the rule is unusable in the very
    converters that already do the right thing.
    """
    src = _HELPERS + (
        'FUNCTION_MAP = {"upper": "upper", "trim": "trim"}\n'
        'PASSTHROUGH_MAP = {\n'
        '    "upper": ("sql_string_op", "UPPER({0})", 1),\n'
        '    "trim": ("sql_string_op", "TRIM({0})", 1),\n'
        '}\n')
    result = _run(_repo(tmp_path, "fake", src))
    assert result.returncode == 0, result.stdout


def test_formula_emission_requires_the_shared_helpers(tmp_path):
    """#440's second regression — colliding formula ids drop BOTH formulas."""
    root = _repo(tmp_path, "fake", 'formulas = []\nFUNCTION_MAP = {"src": "sum"}\n')
    result = _run(root)
    assert result.returncode == 1
    assert "resolve_name_collisions" in result.stdout
    assert "fix_double_aggregation" in result.stdout


def test_no_formula_emission_skips_the_helper_requirement(tmp_path):
    """A converter that emits no formulas must not be forced to import them."""
    result = _run(_repo(tmp_path, "fake", 'FUNCTION_MAP = {"src": "sum"}\n'))
    assert result.returncode == 0, result.stdout


def test_unresolvable_platform_fails_loudly(tmp_path):
    """A new converter must never be SILENTLY skipped — the pre-BL-110 failure mode.

    Skill present, no package, no override: the validator must fail and say what to
    add, rather than pass with the converter unchecked.
    """
    (tmp_path / "agents" / "cli" / "ts-convert-from-newthing").mkdir(parents=True)
    (tmp_path / "agents" / "cli" / "ts-convert-from-newthing" / "SKILL.md").write_text("x")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "PLATFORM_CODE_OVERRIDES" in result.stdout
    assert "newthing" in result.stdout


def test_both_directions_collapse_to_one_platform(tmp_path):
    """to-/from- are one platform and one code location, checked once."""
    root = _repo(tmp_path, "fake", _HELPERS + 'M = {"src": "sum"}\n')
    (root / "agents" / "cli" / "ts-convert-to-fake").mkdir(parents=True)
    (root / "agents" / "cli" / "ts-convert-to-fake" / "SKILL.md").write_text("x")
    result = _run(root)
    assert result.returncode == 0, result.stdout
    assert "1 converter platform(s)" in result.stdout


def test_real_repo_passes(tmp_path):
    """The live tree must be clean, so a genuine regression is the only red."""
    repo_root = Path(__file__).resolve().parents[3]
    result = _run(repo_root)
    assert result.returncode == 0, result.stdout
