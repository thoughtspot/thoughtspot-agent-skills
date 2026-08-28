"""Tests for check_mapping_code_sync — the doc/code agreement gate.

The regressions here are historical, not hypothetical:

* ``sv_sql.py`` emitted the six BL-171 string functions for three CLI versions
  *after* the mapping rows were corrected. Nothing compared the two sides.
* The first cut of this validator flagged all six Qlik and all three PowerBI
  pass-through **markers** as disproved emissions — they are legitimate, because the
  package routes them to ``sql_*_op``. ``test_routed_marker_*`` pins that.
* ``check_converter_parity`` shipped with a comment satisfying a requirement, so
  ``test_*_does_not_count`` pins that prose can neither satisfy nor trip this one.
"""
import subprocess
import sys
from pathlib import Path

VALIDATOR = Path(__file__).resolve().parents[1] / "check_mapping_code_sync.py"

# Two disproved names and one valid one, in the catalog's own table shape.
_CATALOG = """# ThoughtSpot formula patterns

| Function | Example | Notes |
|---|---|---|
| `strpos` | `strpos ( [x] , 'v' )` | Valid. |
| ~~`upper`~~ | — | **Does not exist** (BL-170). |
| ~~`trim`~~ | — | **Does not exist** (BL-171). |
"""


def _repo(tmp_path, platform, code_src, doc_text="# rules\n", *, doc_dir=None):
    """Fake repo: one converter skill, one code file, one mapping doc."""
    skill = tmp_path / "agents" / "cli" / f"ts-convert-from-{platform}"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("x")

    pkg = tmp_path / "tools" / "ts-cli" / "ts_cli" / platform.replace("-", "_")
    pkg.mkdir(parents=True)
    (pkg / "functions.py").write_text(code_src)

    schemas = tmp_path / "agents" / "shared" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "thoughtspot-formula-patterns.md").write_text(_CATALOG)

    if doc_dir is not False:
        docs = tmp_path / "agents" / "shared" / "mappings" / (doc_dir or platform)
        docs.mkdir(parents=True)
        (docs / f"{platform}-formula-translation.md").write_text(doc_text)
    return tmp_path


def _run(root, *extra):
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(root), *extra],
        capture_output=True, text=True)


# --- requirement A: a disproved name must not be emitted ---------------------

def test_bare_disproved_emission_fails():
    """The BL-171 shape: `{"UPPER": "upper"}` with no pass-through anywhere."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = _repo(Path(td), "fake", 'M = {"UPPER": "upper", "TRIM": "trim"}\n')
        r = _run(root)
        assert r.returncode == 1
        assert "`upper`" in r.stderr and "`trim`" in r.stderr
        assert "error_code 14516" in r.stderr


def test_routed_marker_is_not_flagged(tmp_path):
    """Qlik/PowerBI: the name is an intermediate marker, then routed to sql_*_op.

    Flagging this made the validator unusable in the converters that already do the
    right thing — nine false positives on the real tree.
    """
    src = ('FUNCTION_MAP = {"UPPER": "upper", "TRIM": "trim"}\n'
           'PASSTHROUGH_MAP = {\n'
           '    "upper": ("sql_string_op", "UPPER({0})", 1),\n'
           '    "trim": ("sql_string_op", "TRIM({0})", 1),\n'
           '}\n')
    r = _run(_repo(tmp_path, "fake", src))
    assert r.returncode == 0, r.stderr


def test_a_comment_does_not_count_as_an_emission(tmp_path):
    """`sv_sql.py:245` names all six BL-171 functions to explain their ABSENCE.

    A scan that read prose would fail on the very comment documenting the fix.
    """
    src = ('# BL-171: UPPER/TRIM deliberately do NOT live here — neither "upper"\n'
           '# nor "trim" exists as a ThoughtSpot function.\n'
           'M = {"CONCAT": "concat"}\n')
    r = _run(_repo(tmp_path, "fake", src))
    assert r.returncode == 0, r.stderr


def test_a_docstring_does_not_count_as_an_emission(tmp_path):
    src = ('"""Translator. Note that upper and trim are not TS functions."""\n'
           'M = {"CONCAT": "concat"}\n')
    r = _run(_repo(tmp_path, "fake", src))
    assert r.returncode == 0, r.stderr


def test_disproved_name_inside_a_tuple_value_is_caught(tmp_path):
    """`_ARG_SWAP`-shaped maps hold `(ts_name, arity)`, not a bare string."""
    r = _run(_repo(tmp_path, "fake", 'M = {"LOCATE": ("upper", 2)}\n'))
    assert r.returncode == 1
    assert "`upper`" in r.stderr


# --- requirement B: a translated construct should be documented (soft) ------

def test_undocumented_source_construct_warns_but_does_not_fail(tmp_path):
    """The ZEROIFNULL/LOCATE case: code translates it, no doc row exists.

    Soft, because the CoCo runtime reading only the doc is a coverage gap rather
    than a wrong formula.
    """
    root = _repo(tmp_path, "fake", 'M = {"ZEROIFNULL": "strpos"}\n',
                 doc_text="# rules\nNothing here.\n")
    r = _run(root, "--warnings")
    assert r.returncode == 0, r.stderr
    assert "ZEROIFNULL" in r.stderr
    assert "no fake mapping doc mentions" in r.stderr


def test_a_documented_construct_does_not_warn(tmp_path):
    root = _repo(tmp_path, "fake", 'M = {"ZEROIFNULL": "strpos"}\n',
                 doc_text="| `strpos ( [x] )` | `ZEROIFNULL(x)` |\n")
    r = _run(root, "--warnings")
    assert r.returncode == 0, r.stderr
    assert "ZEROIFNULL" not in r.stderr


def test_warnings_are_hidden_without_the_flag(tmp_path):
    """A soft finding must not print by default, or pre-commit output becomes noise."""
    root = _repo(tmp_path, "fake", 'M = {"ZEROIFNULL": "strpos"}\n')
    r = _run(root)
    assert r.returncode == 0
    assert "ZEROIFNULL" not in r.stderr
    assert "soft finding" in r.stdout


# --- scope: nothing may be silently skipped ---------------------------------

def test_missing_mapping_dir_fails_loudly(tmp_path):
    """A converter with a translator but no docs must fail, not pass unchecked.

    This is the pre-BL-110 failure mode: a missed edit reporting PASS.
    """
    root = _repo(tmp_path, "fake", 'M = {"CONCAT": "concat"}\n', doc_dir=False)
    r = _run(root)
    assert r.returncode == 1
    assert "PLATFORM_DOC_OVERRIDES" in r.stderr


def test_ts_prefixed_doc_dir_resolves(tmp_path):
    """`ts-<platform>/` is the other half of the naming convention."""
    root = _repo(tmp_path, "fake", 'M = {"CONCAT": "concat"}\n', doc_dir="ts-fake")
    r = _run(root)
    assert r.returncode == 0, r.stderr


def test_real_repo_passes(tmp_path):
    """The live tree must be clean, so a genuine regression is the only red."""
    repo_root = Path(__file__).resolve().parents[3]
    r = _run(repo_root)
    assert r.returncode == 0, r.stderr
