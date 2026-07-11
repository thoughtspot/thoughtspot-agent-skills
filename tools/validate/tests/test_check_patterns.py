"""Unit tests for check_patterns.py Check 6 — the superseded stdin JSON-array
`ts tml import`/`lint` wrapper (audit finding 5.1).

Covers: the wrapper IS flagged (single-line and split-across-lines forms, including
the real `| source ~/.zshenv && ts tml import` shape that motivated the migration),
the `--file`/`--dir` replacement is NOT flagged, and the references/ carve-out.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import check_patterns as cp

VALIDATE = Path(__file__).resolve().parents[1]


def _run(root: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATE / "check_patterns.py"), "--root", str(root), *extra_args],
        capture_output=True, text=True,
    )


def _git_init_and_add(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


# --- Unit tests for check_stdin_tml_import_wrapper() -----------------------------

def test_flags_single_line_payload_then_pipe():
    f_lines = [
        'python3 -c "',
        "import json, pathlib, sys",
        "print(json.dumps([pathlib.Path(f).read_text() for f in files]))",
        '" "${files[@]}" | ts tml import --policy VALIDATE_ONLY --profile {name}',
    ]
    _write_and_check(f_lines, expect_hits=1)


def test_flags_split_wrapper_with_source_zshenv_pipe():
    # The real Step 9a/9b bug: piped through `source ~/.zshenv &&` before `ts tml import`
    # — the broken form this migration removed. Check 6 must still catch it if it
    # ever reappears, since the fingerprint tolerates whatever sits between `|` and `ts`.
    f_lines = [
        'python3 -c "import json,pathlib; print(json.dumps([pathlib.Path(\'{run_dir}/after/model.tml\').read_text()]))" \\',
        "  | source ~/.zshenv && ts tml import \\",
        '  --profile "{profile_name}" --policy ALL_OR_NONE --no-create-new',
    ]
    _write_and_check(f_lines, expect_hits=1)


def test_flags_ts_tml_lint_variant():
    f_lines = [
        'python3 -c "import json,pathlib; print(json.dumps([pathlib.Path(\'<file>\').read_text()]))" | ts tml lint',
    ]
    _write_and_check(f_lines, expect_hits=1)


def test_does_not_flag_file_and_dir_usage():
    f_lines = [
        "ts tml lint  --dir {output_dir} --order tableau",
        "ts tml import --dir {output_dir} --order tableau --policy VALIDATE_ONLY --profile {name}",
        "ts tml import --file {output_dir}/{dashboard_name}.liveboard.tml --policy PARTIAL --create-new --profile {name}",
    ]
    _write_and_check(f_lines, expect_hits=0)


def test_does_not_flag_unrelated_json_dumps():
    # Real pre-existing line from ts-object-model-coach — json.dumps without
    # read_text() must not trip the fingerprint.
    f_lines = [
        "forbidden_cache_path.write_text(json.dumps(forbidden_cache, indent=2))",
    ]
    _write_and_check(f_lines, expect_hits=0)


def test_does_not_flag_dumps_far_from_tml_import():
    # json.dumps(...read_text...) followed by an unrelated `ts tml import` mention
    # well outside the line window must not be flagged as a single wrapper.
    f_lines = (
        ["print(json.dumps([pathlib.Path(f).read_text() for f in files]))"]
        + ["filler line"] * 10
        + ["ts tml import --file x.tml --profile p"]
    )
    _write_and_check(f_lines, expect_hits=0)


def _write_and_check(lines: list[str], expect_hits: int) -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "SKILL.md"
        f.write_text("\n".join(lines) + "\n")
        hits = cp.check_stdin_tml_import_wrapper(f)
        assert len(hits) == expect_hits, hits


# --- End-to-end tests via main() (SKILL.md file selection + carve-outs) ----------

WRAPPER_SNIPPET = (
    "---\nname: ts-bad\n---\n\n"
    "## Step X\n\n"
    "```bash\n"
    'python3 -c "\n'
    "import json, pathlib, sys\n"
    "print(json.dumps([pathlib.Path(f).read_text() for f in files]))\n"
    '" "${files[@]}" | ts tml import --policy VALIDATE_ONLY --profile {name}\n'
    "```\n"
)

CLEAN_SNIPPET = (
    "---\nname: ts-good\n---\n\n"
    "## Step X\n\n"
    "```bash\n"
    "ts tml import --dir {output_dir} --order tableau --policy VALIDATE_ONLY --profile {name}\n"
    "```\n"
)


def test_main_flags_wrapper_in_skill_md(tmp_path):
    skill_dir = tmp_path / "agents" / "cli" / "ts-bad"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(WRAPPER_SNIPPET)
    _git_init_and_add(tmp_path)

    res = _run(tmp_path)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "stdin-json-array-tml-import" in res.stdout


def test_main_does_not_flag_file_dir_skill_md(tmp_path):
    skill_dir = tmp_path / "agents" / "cli" / "ts-good"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(CLEAN_SNIPPET)
    _git_init_and_add(tmp_path)

    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "stdin-json-array-tml-import" not in res.stdout


def test_main_carves_out_references_dir(tmp_path):
    # references/ files are self-contained open-items test scripts (ts-cli.md) —
    # Check 6 must not scan them (mirrors Check 5's requests.* carve-out).
    skill_dir = tmp_path / "agents" / "cli" / "ts-bad"
    refs_dir = skill_dir / "references"
    refs_dir.mkdir(parents=True)
    # A clean SKILL.md is required for the skill to be "discovered" at all, but the
    # violation lives only in references/open-items.md.
    (skill_dir / "SKILL.md").write_text(CLEAN_SNIPPET)
    (refs_dir / "open-items.md").write_text(WRAPPER_SNIPPET)
    _git_init_and_add(tmp_path)

    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "stdin-json-array-tml-import" not in res.stdout


def test_main_carves_out_coco_snowsight(tmp_path):
    # CoCo has no `ts` CLI available — check_patterns only scans agents/cli and
    # agents/claude, never agents/coco-snowsight.
    skill_dir = tmp_path / "agents" / "coco-snowsight" / "ts-bad"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(WRAPPER_SNIPPET)
    _git_init_and_add(tmp_path)

    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "stdin-json-array-tml-import" not in res.stdout


def test_main_flags_wrapper_in_shared_reference_doc(tmp_path):
    # BL-117: Check 6 also gates agents/shared/**/*.md — the converters inherit the
    # wrapper from a shared reference doc, so it must be caught there too.
    shared_dir = tmp_path / "agents" / "shared" / "schemas"
    shared_dir.mkdir(parents=True)
    (shared_dir / "ts-tml-import-gate.md").write_text(WRAPPER_SNIPPET)
    _git_init_and_add(tmp_path)

    res = _run(tmp_path)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "stdin-json-array-tml-import" in res.stdout


def test_main_does_not_scan_generated_databricks_shared_copy(tmp_path):
    # agents/databricks/shared/ is a generated copy that regenerates from
    # agents/shared/ on deploy — it sits outside the agents/shared/** glob, so a
    # wrapper there is never flagged (fixing the source is what matters).
    dbx_dir = tmp_path / "agents" / "databricks" / "shared" / "schemas"
    dbx_dir.mkdir(parents=True)
    (dbx_dir / "ts-tml-import-gate.md").write_text(WRAPPER_SNIPPET)
    _git_init_and_add(tmp_path)

    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "stdin-json-array-tml-import" not in res.stdout
