"""Unit tests for check_open_item_citations — dangling `open-item #N` references."""
import check_open_item_citations as c


def skill(tmp_path, name, files, items=None, runtime="cli"):
    """Build one skill dir; `items` is the list of item numbers its open-items.md has."""
    d = tmp_path / "agents" / runtime / name
    (d / "references").mkdir(parents=True)
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    if items is not None:
        body = "# Open Items\n\n" + "".join(
            f"## #{n} — something — OPEN\n\nbody\n\n" for n in items)
        (d / "references" / "open-items.md").write_text(body, encoding="utf-8")
    return d


def run(tmp_path):
    skills = c.skill_dirs(tmp_path)
    known = {s.name: s for s in skills}
    return [p for s in skills for p in c.check_skill(s, tmp_path, known)]


def test_resolving_citation_passes(tmp_path):
    skill(tmp_path, "ts-convert-from-x",
          {"SKILL.md": "See open-item #3 for detail.\n"}, items=[3, 4])
    assert run(tmp_path) == []


def test_dangling_citation_fails_and_lists_real_items(tmp_path):
    skill(tmp_path, "ts-convert-from-x",
          {"SKILL.md": "See open-item #10 for detail.\n"}, items=[2, 3])
    problems = run(tmp_path)
    assert len(problems) == 1
    assert "open-item #10 does not exist" in problems[0]
    assert "#2, #3" in problems[0]
    assert "SKILL.md:1" in problems[0]


def test_all_three_citation_spellings_are_caught(tmp_path):
    skill(tmp_path, "ts-convert-from-x",
          {"SKILL.md": "open-item #10\nopen items #11\nOpen Item #12\n"}, items=[1])
    assert len(run(tmp_path)) == 3


def test_citation_naming_another_skill_resolves_there(tmp_path):
    skill(tmp_path, "ts-dependency-manager", {"SKILL.md": "x\n"}, items=[9])
    skill(tmp_path, "ts-object-model-aggregates",
          {"SKILL.md": "retrieval is ts-dependency-manager open-item #9 (unverified)\n"},
          items=[1])
    assert run(tmp_path) == []


def test_citation_naming_another_skill_still_fails_when_absent_there(tmp_path):
    skill(tmp_path, "ts-dependency-manager", {"SKILL.md": "x\n"}, items=[9])
    skill(tmp_path, "ts-object-model-aggregates",
          {"SKILL.md": "see ts-dependency-manager open-item #77 for this\n"}, items=[1])
    problems = run(tmp_path)
    assert len(problems) == 1
    assert "ts-dependency-manager has no open-item #77" in problems[0]


def test_open_items_file_may_cross_reference_its_own_neighbours(tmp_path):
    """An item body citing a sibling item is normal; only the number must be real."""
    d = skill(tmp_path, "ts-convert-from-x", {"SKILL.md": "x\n"}, items=[1, 2])
    f = d / "references" / "open-items.md"
    f.write_text(f.read_text() + "\nsee open-item #999 (this file is exempt)\n")
    assert run(tmp_path) == []


def test_citation_in_skill_with_no_open_items_file_fails(tmp_path):
    skill(tmp_path, "ts-convert-from-x", {"SKILL.md": "see open-item #1\n"}, items=None)
    problems = run(tmp_path)
    assert len(problems) == 1
    assert "has no references/open-items.md" in problems[0]


def test_python_files_are_scanned(tmp_path):
    skill(tmp_path, "ts-object-model-erd",
          {"build_erd.py": "# blocked by open-item #42\n"}, items=[1])
    assert len(run(tmp_path)) == 1


def test_three_level_headings_count_as_items(tmp_path):
    """ts-audit numbers its items with ###; those must resolve, not dangle."""
    d = skill(tmp_path, "ts-audit", {"SKILL.md": "see open-item #5\n"}, items=None)
    (d / "references" / "open-items.md").write_text(
        "# Open\n\n### #5 — deep heading — OPEN\n\nbody\n", encoding="utf-8")
    assert run(tmp_path) == []


def test_empty_scope_is_a_failure(tmp_path, capsys, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "argv", ["x", "--root", str(tmp_path)])
    assert c.main() == 1
    assert "layout moved" in capsys.readouterr().out


def test_changelog_section_is_not_scanned(tmp_path):
    """A row recording a fixed dangling citation must not re-trip the gate."""
    skill(tmp_path, "ts-convert-from-x",
          {"SKILL.md": "Body cites open-item #1.\n\n## Changelog\n\n"
                       "| 1.0.1 | fixed a citation to open-items #4 which never existed |\n"},
          items=[1])
    assert run(tmp_path) == []


def test_body_citation_still_caught_when_a_changelog_exists(tmp_path):
    skill(tmp_path, "ts-convert-from-x",
          {"SKILL.md": "Body cites open-item #99.\n\n## Changelog\n\n| 1.0.0 | x |\n"},
          items=[1])
    assert len(run(tmp_path)) == 1
