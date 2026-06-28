"""Unit tests for check_skill_cli_usage — inline Python TML assembly guard."""
import check_skill_cli_usage as c


def test_flags_python_heredoc_with_formulas():
    assert c.HEREDOC_RE.search("python3 <<'EOF'")
    assert c.HEREDOC_RE.search("python3 -")


def test_formula_assembly_pattern():
    assert c.FORMULA_ASSEMBLY_RE.search('formulas[]: ...')
    assert c.FORMULA_ASSEMBLY_RE.search('"formulas": [')
    assert c.FORMULA_ASSEMBLY_RE.search('formula_id: f_1')


def test_does_not_flag_read_wrappers():
    assert c.READ_WRAPPER_RE.search('python3 -c "import json,pathlib;print(json.dumps(...))"')
    assert c.READ_WRAPPER_RE.search('python3 -c "import pathlib; ...')


def test_does_not_flag_build_model_reference():
    assert not c.HEREDOC_RE.search("ts tableau build-model --existing-guid {guid}")


def test_scan_file_catches_inline_assembly(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text(
        'Step 7 Phase 2:\n'
        '```bash\n'
        "python3 <<'EOF'\n"
        'import json, sys\n'
        'model = json.load(open("model.tml.yaml"))\n'
        'model["model"]["formulas"] = [{"id": "f_1", "formula_id": "f_1"}]\n'
        'EOF\n'
        'ts tml import model.tml.yaml\n'
        '```\n'
    )
    hits = c.scan_file(f)
    assert len(hits) == 1


def test_scan_file_clean_with_build_model(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text(
        'Step 7 Phase 2:\n'
        '```bash\n'
        'ts tableau build-model --twb-file x.twb --existing-guid abc --profile p\n'
        '```\n'
        'The command handles formulas[] internally.\n'
    )
    assert c.scan_file(f) == []


def test_scan_file_ignores_read_wrapper(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text(
        'Read the model:\n'
        '```bash\n'
        'python3 -c "import json,pathlib;print(json.dumps(...))" # reads formulas[]\n'
        '```\n'
    )
    assert c.scan_file(f) == []
