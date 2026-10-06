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


# --- requirement D: function-valued dispatch maps declare their emissions (#572) -----

_D_CODE = ('def _f(name, args, resolver):\n    return ""\n\n'
           'EXACT_FORM_CALLS = {"LOCATE": _f}\n')
_D_DOC = "| `LOCATE(sub, s)` | `strpos ( s , sub )`, or `sql_string_op` when … |\n"


def test_dispatch_map_without_emits_fails(tmp_path):
    """The blind spot itself: handlers are function references, so A and B see nothing."""
    r = _run(_repo(tmp_path, "fake", _D_CODE, _D_DOC))
    assert r.returncode == 1 and "EXACT_FORM_EMITS" in r.stderr, r.stderr


def test_declared_emits_matching_the_doc_pass(tmp_path):
    src = _D_CODE + 'EXACT_FORM_EMITS = {"LOCATE": ("strpos", "sql_string_op")}\n'
    r = _run(_repo(tmp_path, "fake", src, _D_DOC))
    assert r.returncode == 0, r.stderr


def test_emits_keys_must_equal_the_dispatch_keys(tmp_path):
    src = (_D_CODE.replace('{"LOCATE": _f}', '{"LOCATE": _f, "INSTR": _f}')
           + 'EXACT_FORM_EMITS = {"LOCATE": ("strpos",)}\n')
    r = _run(_repo(tmp_path, "fake", src, _D_DOC + "| `INSTR(s, sub)` | `strpos` |\n"))
    assert r.returncode == 1 and "keys differ" in r.stderr and "INSTR" in r.stderr


def test_construct_without_a_doc_row_fails(tmp_path):
    src = _D_CODE + 'EXACT_FORM_EMITS = {"LOCATE": ("strpos",)}\n'
    r = _run(_repo(tmp_path, "fake", src, "# rules\nnothing here\n"))
    assert r.returncode == 1 and "no mapping doc line names `LOCATE(`" in r.stderr


def test_emitted_name_the_doc_row_omits_fails(tmp_path):
    """Code and doc disagree: the handler can pass through, the row never says so."""
    src = _D_CODE + 'EXACT_FORM_EMITS = {"LOCATE": ("strpos", "sql_double_op")}\n'
    r = _run(_repo(tmp_path, "fake", src, _D_DOC))
    assert r.returncode == 1 and "can emit `sql_double_op`" in r.stderr


def test_declared_disproved_name_fails(tmp_path):
    src = _D_CODE + 'EXACT_FORM_EMITS = {"LOCATE": ("upper",)}\n'
    r = _run(_repo(tmp_path, "fake", src, "| `LOCATE(x)` | `upper` |\n"))
    assert r.returncode == 1 and "NOT a ThoughtSpot function" in r.stderr


def test_real_exact_form_module_mutations_fail(tmp_path):
    """Mutation test on the real sv_sql_exact.py and the real Snowflake docs and catalog:
    unmutated it passes; adding an undocumented handler, or a name the doc row does not
    carry, fails."""
    repo_root = Path(__file__).resolve().parents[3]
    real_src = (repo_root / "tools/ts-cli/ts_cli/sv_sql_exact.py").read_text()
    docs = repo_root / "agents/shared/mappings/ts-snowflake"
    doc = "\n".join(p.read_text() for p in sorted(docs.glob("*.md")))
    catalog = (repo_root / "agents/shared/schemas/thoughtspot-formula-patterns.md").read_text()

    def run(src, name):
        root = _repo(tmp_path / name, "fake", src, doc)
        (root / "agents/shared/schemas/thoughtspot-formula-patterns.md").write_text(catalog)
        return _run(root)

    assert run(real_src, "clean").returncode == 0
    added = real_src.replace('"MONTHS_BETWEEN": call_months_between}',
                             '"MONTHS_BETWEEN": call_months_between, "NO_SUCH_FN": call_substr}')
    added = added.replace('"MONTHS_BETWEEN": ("sql_double_op",)}',
                          '"MONTHS_BETWEEN": ("sql_double_op",), "NO_SUCH_FN": ("substr",)}')
    assert added != real_src
    r = run(added, "added")
    assert r.returncode == 1 and "`NO_SUCH_FN(`" in r.stderr, r.stderr
    # (Not diff_months: the MONTHS_BETWEEN rows mention it to say it is wrong — D checks
    # mention, not endorsement, which is the limit of a text check.)
    widened = real_src.replace('"MONTHS_BETWEEN": ("sql_double_op",)}',
                               '"MONTHS_BETWEEN": ("sql_double_op", "add_days")}')
    assert widened != real_src
    r = run(widened, "widened")
    assert r.returncode == 1 and "can emit `add_days`" in r.stderr, r.stderr


def test_real_repo_passes(tmp_path):
    """The live tree must be clean, so a genuine regression is the only red."""
    repo_root = Path(__file__).resolve().parents[3]
    r = _run(repo_root)
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------
# Requirement C — the Excel / Sheets translator's rule table vs its maps (BL-339)
# ---------------------------------------------------------------------------

_EXCEL_MAP = """# Excel map

### Criteria strings

| `"*es*"` | `contains ( [T::x] , 'es' )` | |

## Math

| `SUM(number1, ...)` | direct | range: `sum ( [x] )` | |
| `ABS(x)` | direct | `abs ( [x] )` | |

<!-- translator-coverage:start -->
`ABS` `SUM`
<!-- translator-coverage:end -->
"""
_SHEETS_MAP = """# Sheets map

| `QUERY(data, query)` | structural | an Answer | |

<!-- translator-coverage:start -->
`QUERY`
<!-- translator-coverage:end -->
"""


def _rules(function_rules: str, sheets_rules: str = '{"QUERY": {"map": "sheets", "emits": ()}}',
           criteria: str = '("contains",)') -> str:
    return (f"FUNCTION_RULES = {function_rules}\nSHEETS_RULES = {sheets_rules}\n"
            f"CRITERIA_EMITS = {criteria}\n")


def _c_errors(rules_src, excel_map=_EXCEL_MAP, sheets_map=_SHEETS_MAP):
    import check_mapping_code_sync as m
    return m.excel_rule_errors(rules_src, {"excel": excel_map, "sheets": sheets_map},
                               valid={"sum", "abs", "contains"}, nonexistent={"nullif"},
                               extras=set())


_OK_RULES = ('{"SUM": {"map": "excel", "emits": ("sum",)}, '
             '"ABS": {"map": "excel", "emits": ("abs",)}}')


def test_excel_rules_agreeing_with_their_rows_pass():
    assert _c_errors(_rules(_OK_RULES)) == []


def test_excel_rule_emitting_a_name_its_row_does_not_say_fails():
    errs = _c_errors(_rules('{"SUM": {"map": "excel", "emits": ("sum", "abs")}, '
                            '"ABS": {"map": "excel", "emits": ("abs",)}}'))
    assert any("`SUM` row never mentions it" in e for e in errs)


def test_excel_rule_emitting_a_disproved_name_fails():
    errs = _c_errors(_rules('{"SUM": {"map": "excel", "emits": ("nullif",)}, '
                            '"ABS": {"map": "excel", "emits": ("abs",)}}'))
    assert any("NOT a ThoughtSpot function" in e for e in errs)


def test_excel_rule_for_an_unrowed_function_fails():
    errs = _c_errors(_rules(_OK_RULES[:-1] + ', "VLOOKUP": {"map": "excel", "emits": ()}}'))
    assert any("no `VLOOKUP(` row" in e for e in errs)


def test_coverage_list_must_equal_the_rule_keys():
    errs = _c_errors(_rules('{"SUM": {"map": "excel", "emits": ("sum",)}}'))
    assert any("listed but not translated ['ABS']" in e for e in errs)
    no_list = _EXCEL_MAP.split("<!-- translator-coverage:start -->")[0]
    assert any("no translator-coverage list" in e for e in _c_errors(_rules(_OK_RULES), no_list))


def test_criteria_emits_checked_against_the_criteria_table():
    errs = _c_errors(_rules(_OK_RULES, criteria='("contains", "strpos")'))
    assert any("CRITERIA_EMITS: `strpos`" in e for e in errs)


def test_coercion_emits_checked_against_the_coercion_table():
    """COERCION_EMITS (BL-352..355): each name must appear in the Excel map's implicit-type-
    coercion table and be a catalogued function."""
    table = "\n### Implicit type coercion\n\n| a text date | `abs` |\n\n## Next\n"
    with_table = _EXCEL_MAP.replace("<!-- translator-coverage:start -->",
                                    table + "<!-- translator-coverage:start -->")
    ok = _rules(_OK_RULES) + 'COERCION_EMITS = ("abs",)\n'
    assert _c_errors(ok, with_table) == []
    errs = _c_errors(_rules(_OK_RULES) + 'COERCION_EMITS = ("abs", "sum")\n', with_table)
    assert any("COERCION_EMITS: `sum` does not appear" in e for e in errs)
    errs = _c_errors(_rules(_OK_RULES) + 'COERCION_EMITS = ("nullif",)\n', with_table)
    assert any("COERCION_EMITS: `nullif` is not a catalogued" in e for e in errs)


def test_real_repo_passes_requirement_c():
    """The shipped rule table and the shipped maps agree (the gate the CI runs)."""
    import check_mapping_code_sync as m
    from check_formula_catalog import parse_catalog
    root = Path(__file__).resolve().parents[3]
    valid, nonexistent = parse_catalog((root / m.CATALOG_REL).read_text(encoding="utf-8"))
    errors, _warnings = m.check_excel(root, valid, nonexistent)
    assert errors == []


# ---------------------------------------------------------------------------
# Requirement C runs the handlers (PR #570 review L1): the four reviewer mutations
# ---------------------------------------------------------------------------

import shutil

import pytest

_REAL_ROOT = Path(__file__).resolve().parents[3]


def _excel_repo(tmp_path):
    """A copy of the shipped Excel translator, its maps and the catalog — nothing else."""
    shutil.copytree(_REAL_ROOT / "tools" / "ts-cli" / "ts_cli", tmp_path / "tools" / "ts-cli" / "ts_cli",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for rel in ("agents/shared/schemas/thoughtspot-formula-patterns.md",
                "docs/function-maps/ts-excel-function-mapping.md",
                "docs/function-maps/ts-sheets-function-mapping.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(_REAL_ROOT / rel, tmp_path / rel)
    (tmp_path / "agents" / "cli").mkdir(parents=True, exist_ok=True)
    return tmp_path / "tools" / "ts-cli" / "ts_cli" / "excel"


def _gate(root):
    return subprocess.run([sys.executable, str(VALIDATOR), "--root", str(root)],
                          capture_output=True, text=True)


def _mutate(path, old, new):
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))


def test_unmutated_copy_passes(tmp_path):
    _excel_repo(tmp_path)
    res = _gate(tmp_path)
    assert res.returncode == 0, res.stderr


@pytest.mark.parametrize("file,old,new,expect", [
    # 1. a handler emits a disproved name
    ("functions.py", '"ABS": _unary_fn("abs")', '"ABS": _unary_fn("nullif")', "NOT a ThoughtSpot"),
    # 2. a handler emits a catalogued name its rule never declared
    ("functions_text.py", 'T.call("strlen", tr.text(n.args[0]))',
     'T.call("strpos", tr.expr(n.args[0]))', "does not declare"),
    # 3. a rule's emits emptied while the handler still emits
    ("rules.py", '"SUM": {"map": "excel", "emits": ("sum",)}',
     '"SUM": {"map": "excel", "emits": ()}', "does not declare"),
    # 4. a disproved call spelled inside a string literal
    ("forward.py", 'BLANK_TRAP = (', '_BAD = "[a] / nullif ( [b] , 0 )"\nBLANK_TRAP = (',
     "string literal"),
])
def test_reviewer_mutations_fail(tmp_path, file, old, new, expect):
    excel = _excel_repo(tmp_path)
    _mutate(excel / file, old, new)
    res = _gate(tmp_path)
    assert res.returncode == 1 and expect in res.stderr, res.stderr[-2000:]
