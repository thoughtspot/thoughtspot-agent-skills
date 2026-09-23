"""Unit tests for check_no_inline_requests.

The module had no test file before 2026-09-22; these arrived with the
finding-5.5 widening that brought skill-local `.py` into scope.
"""
# ── skill-local .py files (audit finding 5.5) ───────────────────────────────

def test_py_file_is_scanned_whole_not_just_fences(tmp_path):
    """A .py file has no fences; before 5.5 it was skipped entirely."""
    import check_no_inline_requests as m
    f = tmp_path / "build_erd.py"
    f.write_text("import requests\n\nresp = requests.post(url, json=body)\n")
    hits = m.scan_file(f)
    assert len(hits) == 2
    assert hits[0][0] == 1 and "import requests" in hits[0][1]
    assert hits[1][0] == 3 and "requests.post" in hits[1][1]


def test_clean_py_file_passes(tmp_path):
    import check_no_inline_requests as m
    f = tmp_path / "build_erd.py"
    f.write_text("import json\nfrom pathlib import Path\n\nprint(json.dumps({}))\n")
    assert m.scan_file(f) == []


def test_iter_skill_files_collects_both_suffixes(tmp_path):
    import check_no_inline_requests as m
    d = tmp_path / "agents" / "cli" / "ts-object-model-erd"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("doc\n")
    (d / "build_erd.py").write_text("code\n")
    (d / "notes.txt").write_text("ignored\n")
    names = {p.name for p in m.iter_skill_files(tmp_path)}
    assert names == {"SKILL.md", "build_erd.py"}
