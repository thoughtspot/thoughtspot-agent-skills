"""check_skill_versions: changelog rows must run strictly newest-first (BL-381)."""
from check_skill_versions import check_skill

HEAD = "---\nname: ts-demo\n---\n\n# Demo\n\n## Changelog\n\n| Version | Date | Summary |\n|---|---|---|\n"


def _skill(tmp_path, *versions):
    f = tmp_path / "SKILL.md"
    f.write_text(HEAD + "".join(f"| {v} | 2026-10-07 | change |\n" for v in versions))
    return f


def test_descending_rows_pass(tmp_path):
    assert check_skill(_skill(tmp_path, "1.10.0", "1.9.1", "1.9.0", "1.0.0")) == []


def test_lower_version_on_top_fails(tmp_path):
    errs = check_skill(_skill(tmp_path, "1.0.8", "1.1.0", "1.0.7"))
    assert len(errs) == 1 and "v1.0.8 sits above v1.1.0" in errs[0]


def test_duplicate_version_fails(tmp_path):
    errs = check_skill(_skill(tmp_path, "1.1.0", "1.1.0"))
    assert errs and "out of order" in errs[0]


def test_compares_numerically_not_as_text(tmp_path):
    assert check_skill(_skill(tmp_path, "1.10.0", "1.9.0")) == []
