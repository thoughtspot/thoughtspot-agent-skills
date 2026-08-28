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


def _shared_emitter(tmp_path, body):
    """Write a fake ts_cli/model_builder.py so delegation can be exercised."""
    pkg = tmp_path / "tools" / "ts-cli" / "ts_cli"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "model_builder.py").write_text(body)
    return tmp_path


# --- B1: the shared-emitter route (the hole that failed domo on a helper it runs) ---

_DELEGATING = ("from ts_cli.model_builder import build_model_tml\n"
               "formulas = []\n"
               "def assemble():\n    return build_model_tml()\n")


def test_delegation_credits_the_helper_the_emitter_applies(tmp_path):
    """Requirement B must see through `build_model_tml`.

    This is the exact shape that failed #440 in CI for `fix_double_aggregation` —
    a helper the shared emitter demonstrably applies on the converter's behalf.
    """
    root = _repo(tmp_path, "fake", _DELEGATING)
    _shared_emitter(root, "def build_model_tml():\n"
                          "    expr = fix_double_aggregation(expr, {})\n"
                          "    expr = resolve_name_collisions(expr, {})\n")
    result = _run(root)
    assert result.returncode == 0, result.stdout


def test_delegation_credits_only_helpers_the_emitter_actually_calls(tmp_path):
    """An unused import in the emitter must NOT be credited to its callers.

    `model_builder` really does import `resolve_name_collisions` without calling it,
    so "delegation satisfies both helpers" would assert a guarantee that does not
    exist. A call is the evidence; an import is not.
    """
    root = _repo(tmp_path, "fake", _DELEGATING)
    _shared_emitter(root, "from ts_cli.formula_common import resolve_name_collisions\n"
                          "def build_model_tml():\n"
                          "    return fix_double_aggregation(expr, {})\n")
    result = _run(root)
    assert result.returncode == 1
    assert "resolve_name_collisions" in result.stdout
    # ...and the one it does call must not be re-reported.
    assert "must use formula_common.fix_double_aggregation" not in result.stdout


def test_a_local_build_model_tml_is_not_delegation(tmp_path):
    """The powerbi / sisense shape: same symbol NAME, defined locally.

    A name-presence test would exempt two converters that do not delegate at all,
    which is why the signal is the import of the shared symbol.
    """
    src = ("formulas = []\n"
           "def build_model_tml():\n    return {}\n"
           "model_tml = build_model_tml()\n")
    result = _run(_repo(tmp_path, "fake", src))
    assert result.returncode == 1
    assert "does not delegate" in result.stdout


# --- B2: prose must not satisfy a requirement ---

def test_a_comment_does_not_satisfy_a_helper_requirement(tmp_path):
    """The live false PASS: a comment saying the helper is NOT used, passing the check.

    Read as evidence of presence, a statement of absence is worse than silence.
    """
    src = ("formulas = []\n"
           "# We deliberately do not call resolve_name_collisions here, because it\n"
           "# drops the colliding column. See naming.py.\n"
           "# fix_double_aggregation is likewise handled elsewhere.\n")
    result = _run(_repo(tmp_path, "fake", src))
    assert result.returncode == 1
    assert "resolve_name_collisions" in result.stdout
    assert "fix_double_aggregation" in result.stdout


def test_a_docstring_does_not_satisfy_a_helper_requirement(tmp_path):
    """Same hole via a docstring / string literal rather than a `#` comment."""
    src = ('"""This module intentionally avoids resolve_name_collisions and\n'
           'fix_double_aggregation; see the design note."""\n'
           "formulas = []\n")
    result = _run(_repo(tmp_path, "fake", src))
    assert result.returncode == 1


def test_requirement_a_still_reads_string_literals(tmp_path):
    """Stripping strings for requirement B must not blind requirement A.

    A's mappings live INSIDE string literals, so it reads the raw text. Without this
    the B2 fix would have silently disabled the validator's primary rule.
    """
    src = _HELPERS + 'FUNCTION_MAP = {"UPPER": "upper"}\n'
    result = _run(_repo(tmp_path, "fake", src))
    assert result.returncode == 1
    assert "not a" in result.stdout.lower() and "upper" in result.stdout


# --- the divergence table must not carry entries nothing consults ---

def test_an_unreachable_divergence_key_is_reported(monkeypatch):
    """Three such entries shipped with this validator and were counted as outstanding.

    An exemption nothing consults reads as a decision and gets cited as precedent,
    so a dead key must fail rather than sit in the table.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("ccp", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    dead = ("tableau", "wrap_passthrough_calls")
    monkeypatch.setitem(mod.EXPECTED_DIVERGENCES, dead, "commentary, not a key")

    # Assert on the KEY, not on the message prose: the guidance text names every
    # consultable helper, so a substring test matches the advice rather than the
    # finding. (The first cut of this test did exactly that and passed vacuously.)
    def reported(keys):
        problems = mod._unreachable_divergences()
        return {k for k in keys if any(repr(k) in p for p in problems)}

    assert reported([dead]) == {dead}

    # A well-formed key of each consultable shape must NOT be reported.
    good = [("qlik", "emits:upper"), ("qlik", "fix_double_aggregation")]
    for key in good:
        monkeypatch.setitem(mod.EXPECTED_DIVERGENCES, key, "ok")
    assert reported(good) == set()


def test_real_repo_passes(tmp_path):
    """The live tree must be clean, so a genuine regression is the only red."""
    repo_root = Path(__file__).resolve().parents[3]
    result = _run(repo_root)
    assert result.returncode == 0, result.stdout
