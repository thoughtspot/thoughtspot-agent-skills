"""check_references must validate references/*.md and docs/**/*.md links, not just
SKILL.md (audit finding 1.4) — and must resolve links relative to each file's OWN
directory rather than misapplying the SKILL.md-depth-sensitive prefix maps to a
references/*.md file (one level deeper) or a docs/*.md file (outside agents/ entirely).
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_references  # noqa: E402

CHECKER = Path(__file__).resolve().parents[1] / "check_references.py"


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def _run_checker(repo):
    return subprocess.run(
        ["python3", str(CHECKER), "--root", str(repo)],
        cwd=repo, capture_output=True, text=True,
    )


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "agents" / "cli" / "ts-x" / "references").mkdir(parents=True)
    (repo / "docs" / "audit").mkdir(parents=True)
    (repo / "docs" / "superpowers").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "t")
    return repo


# ── direct unit tests for _file_class / resolve_path (no git needed) ──────────


def test_file_class_skill_md_is_skill(tmp_path):
    p = tmp_path / "agents" / "cli" / "ts-x" / "SKILL.md"
    assert check_references._file_class(p, tmp_path) == "skill"


def test_file_class_references_md_is_reference(tmp_path):
    p = tmp_path / "agents" / "cli" / "ts-x" / "references" / "foo.md"
    assert check_references._file_class(p, tmp_path) == "reference"


def test_file_class_docs_md_is_doc(tmp_path):
    p = tmp_path / "docs" / "foo.md"
    assert check_references._file_class(p, tmp_path) == "doc"


def test_reference_file_resolves_relative_link_from_its_own_depth(tmp_path):
    # agents/cli/ts-x/references/note.md sits ONE level deeper than SKILL.md.
    # A correctly-authored relative link accounts for that extra level.
    (tmp_path / "agents" / "shared").mkdir(parents=True)
    (tmp_path / "agents" / "shared" / "target.md").write_text("x\n")
    ref_file = tmp_path / "agents" / "cli" / "ts-x" / "references" / "note.md"
    ref_file.parent.mkdir(parents=True)
    resolved = check_references.resolve_path("../../../shared/target.md", ref_file, tmp_path)
    assert resolved == (tmp_path / "agents" / "shared" / "target.md").resolve()


def test_reference_file_does_not_get_coco_prefix_map_applied(tmp_path):
    # A CoCo SKILL.md at agents/coco-snowsight/ts-y/SKILL.md correctly reaches
    # agents/shared/ with "../../shared/..." (COCO_PREFIX_MAP). A references/*.md
    # file one level deeper must NOT have that same shorthand silently remapped —
    # doing so would misresolve (or falsely validate) a link that is actually wrong
    # for its depth. Here "../../shared/target.md" from the deeper references/ file
    # must resolve via plain relative resolution (not the prefix map), landing
    # somewhere other than agents/shared/target.md.
    (tmp_path / "agents" / "shared").mkdir(parents=True)
    (tmp_path / "agents" / "shared" / "target.md").write_text("x\n")
    ref_file = tmp_path / "agents" / "coco-snowsight" / "ts-y" / "references" / "note.md"
    ref_file.parent.mkdir(parents=True)
    resolved = check_references.resolve_path("../../shared/target.md", ref_file, tmp_path)
    # Plain relative resolution (NOT the COCO_PREFIX_MAP substitution) — two levels
    # up from references/ lands at agents/coco-snowsight/, not agents/.
    assert resolved != (tmp_path / "agents" / "shared" / "target.md").resolve()
    assert resolved == (tmp_path / "agents" / "coco-snowsight" / "shared" / "target.md").resolve()


def test_doc_file_resolves_relative_to_its_own_directory(tmp_path):
    (tmp_path / "agents" / "shared").mkdir(parents=True)
    (tmp_path / "agents" / "shared" / "target.md").write_text("x\n")
    doc_file = tmp_path / "docs" / "some-doc.md"
    doc_file.parent.mkdir(parents=True)
    resolved = check_references.resolve_path("../agents/shared/target.md", doc_file, tmp_path)
    assert resolved == (tmp_path / "agents" / "shared" / "target.md").resolve()


def test_doc_file_claude_prefix_map_still_applies(tmp_path):
    # The ~/.claude/... shorthand is absolute-style (not depth-sensitive), so it's
    # safe — and expected — to still apply outside SKILL.md.
    (tmp_path / "agents" / "shared" / "schemas").mkdir(parents=True)
    (tmp_path / "agents" / "shared" / "schemas" / "x.md").write_text("x\n")
    doc_file = tmp_path / "docs" / "some-doc.md"
    doc_file.parent.mkdir(parents=True)
    resolved = check_references.resolve_path("~/.claude/shared/schemas/x.md", doc_file, tmp_path)
    assert resolved == (tmp_path / "agents" / "shared" / "schemas" / "x.md").resolve()


# ── end-to-end CLI tests (real git repo, matches test_references_untracked.py) ─


def test_references_md_valid_link_passes(tmp_path):
    repo = _make_repo(tmp_path)
    skill_dir = repo / "agents" / "cli" / "ts-x"
    (skill_dir / "SKILL.md").write_text("See references/note.md\n")
    (skill_dir / "references" / "note.md").write_text("See [sibling](sibling.md).\n")
    (skill_dir / "references" / "sibling.md").write_text("body\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    res = _run_checker(repo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "PASS  agents/cli/ts-x/references/note.md" in res.stdout


def test_references_md_broken_link_is_flagged(tmp_path):
    repo = _make_repo(tmp_path)
    skill_dir = repo / "agents" / "cli" / "ts-x"
    (skill_dir / "SKILL.md").write_text("See references/note.md\n")
    (skill_dir / "references" / "note.md").write_text("See [ghost](does-not-exist.md).\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    res = _run_checker(repo)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "FAIL  agents/cli/ts-x/references/note.md" in res.stdout


def test_docs_md_valid_link_passes(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "docs" / "good.md").write_text("See [backlog](backlog.md).\n")
    (repo / "docs" / "backlog.md").write_text("body\n")
    (repo / "agents" / "cli" / "ts-x" / "SKILL.md").write_text("stub\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    res = _run_checker(repo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "PASS  docs/good.md" in res.stdout


def test_docs_md_broken_link_is_flagged(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "docs" / "bad.md").write_text("See [ghost](nonexistent.md).\n")
    (repo / "agents" / "cli" / "ts-x" / "SKILL.md").write_text("stub\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    res = _run_checker(repo)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "FAIL  docs/bad.md" in res.stdout


def test_docs_audit_is_excluded(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "docs" / "audit" / "2026-01-01-full.md").write_text(
        "See [ghost](nonexistent.md).\n"
    )
    (repo / "agents" / "cli" / "ts-x" / "SKILL.md").write_text("stub\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    res = _run_checker(repo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "docs/audit" not in res.stdout


def test_docs_superpowers_is_excluded(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "docs" / "superpowers" / "plans.md").write_text(
        "See [ghost](nonexistent.md).\n"
    )
    (repo / "agents" / "cli" / "ts-x" / "SKILL.md").write_text("stub\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    res = _run_checker(repo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "docs/superpowers" not in res.stdout


def test_docs_backlog_archive_is_excluded(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "docs" / "backlog-archive.md").write_text("See [ghost](nonexistent.md).\n")
    (repo / "agents" / "cli" / "ts-x" / "SKILL.md").write_text("stub\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    res = _run_checker(repo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "backlog-archive" not in res.stdout
