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


def known_map(tmp_path):
    """Name -> [dirs], as main() builds it: one name can exist in several runtimes."""
    known = {}
    for d in c.skill_dirs(tmp_path):
        known.setdefault(d.name, []).append(d)
    return known


def run(tmp_path):
    skills = c.skill_dirs(tmp_path)
    known = known_map(tmp_path)
    out = [p for s in skills for p in c.check_skill(s, tmp_path, known)]
    for f in c.shared_files(tmp_path):
        out.extend(c.check_shared(f, tmp_path, known))
    return out


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


# ── regression: spellings the first regex missed (hid 15 live pointers) ─────

def test_dot_md_spelling_is_caught(tmp_path):
    """`open-items.md #11` — the first cut required whitespace straight after `items`."""
    skill(tmp_path, "ts-object-model-coach",
          {"SKILL.md": "see open-items.md #11 for detail\n"}, items=[4])
    assert len(run(tmp_path)) == 1


def test_markdown_link_spelling_is_caught(tmp_path):
    skill(tmp_path, "ts-object-model-coach",
          {"SKILL.md": "see [open-items.md #12](references/open-items.md)\n"}, items=[4])
    assert len(run(tmp_path)) == 1


def test_underscore_spelling_is_caught(tmp_path):
    skill(tmp_path, "ts-x", {"SKILL.md": "open_item #7\n"}, items=[1])
    assert len(run(tmp_path)) == 1


def test_dot_md_spelling_resolves_when_real(tmp_path):
    skill(tmp_path, "ts-object-model-coach",
          {"SKILL.md": "see open-items.md #4 for detail\n"}, items=[4])
    assert run(tmp_path) == []


# ── the bare markdown-link form (path resolves, item does not) ──────────────

def test_bare_link_form_is_caught(tmp_path):
    """`[#17](open-items.md)` — check_references passes it; the item is absent."""
    skill(tmp_path, "ts-object-model-coach",
          {"SKILL.md": "deferred, see [#17](references/open-items.md)\n"}, items=[4])
    problems = run(tmp_path)
    assert len(problems) == 1 and "#17 does not exist" in problems[0]


def test_bare_link_form_resolves_when_real(tmp_path):
    skill(tmp_path, "ts-object-model-coach",
          {"SKILL.md": "see [#4](references/open-items.md)\n"}, items=[4])
    assert run(tmp_path) == []


def test_link_to_some_other_file_is_not_a_citation(tmp_path):
    """`[#4](dependency-types.md)` is a section anchor, not an open-item pointer."""
    skill(tmp_path, "ts-x", {"SKILL.md": "see [row #4](references/dependency-types.md)\n"},
          items=[1])
    assert run(tmp_path) == []


def test_both_forms_on_one_line_report_once_each(tmp_path):
    skill(tmp_path, "ts-x",
          {"SKILL.md": "open-item #8 and [#9](references/open-items.md)\n"}, items=[1])
    assert len(run(tmp_path)) == 2


# ── agents/shared/ has no owning skill (the pre-commit trigger matches it) ──

def shared_file(tmp_path, body, name="schemas/x.md"):
    p = tmp_path / "agents" / "shared" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_shared_file_citation_must_name_a_skill(tmp_path):
    skill(tmp_path, "ts-x", {"SKILL.md": "x\n"}, items=[3])
    p = shared_file(tmp_path, "required on every entry (open-items #12).\n")
    known = known_map(tmp_path)
    problems = c.check_shared(p, tmp_path, known)
    assert len(problems) == 1 and "names no skill" in problems[0]


def test_shared_file_citation_naming_a_skill_resolves(tmp_path):
    skill(tmp_path, "ts-object-answer-promote", {"SKILL.md": "x\n"}, items=[3])
    p = shared_file(tmp_path, "see open-items.md #3 in ts-object-answer-promote for this\n")
    known = known_map(tmp_path)
    assert c.check_shared(p, tmp_path, known) == []


def test_shared_file_citation_naming_a_skill_that_lacks_it_fails(tmp_path):
    skill(tmp_path, "ts-object-answer-promote", {"SKILL.md": "x\n"}, items=[3])
    p = shared_file(tmp_path, "see open-item #99 in ts-object-answer-promote\n")
    known = known_map(tmp_path)
    problems = c.check_shared(p, tmp_path, known)
    assert len(problems) == 1 and "has no open-item #99" in problems[0]


# ── lookback is bidirectional; nearest name wins ────────────────────────────

def test_skill_named_after_the_citation_is_honoured(tmp_path):
    """`see open-item #9 in ts-dependency-manager` — backward-only missed this."""
    skill(tmp_path, "ts-dependency-manager", {"SKILL.md": "x\n"}, items=[9])
    skill(tmp_path, "ts-object-model-aggregates",
          {"SKILL.md": "see open-item #9 in ts-dependency-manager for detail\n"}, items=[1])
    assert run(tmp_path) == []


def test_nearest_skill_name_wins_over_a_farther_one(tmp_path):
    skill(tmp_path, "ts-security-columns", {"SKILL.md": "x\n"}, items=[1])
    skill(tmp_path, "ts-dependency-manager", {"SKILL.md": "x\n"}, items=[9])
    skill(tmp_path, "ts-object-model-aggregates",
          {"SKILL.md": "Choosing the mechanism is ts-security-columns' job. "
                       "Retrieval is ts-dependency-manager open-item #9.\n"}, items=[1])
    assert run(tmp_path) == []


# ── spellings that survived the second tightening (B1) ─────────────────────

def test_backtick_before_hash_is_caught(tmp_path):
    """``open-items.md`` #12`` — a backtick between the token and the number."""
    skill(tmp_path, "ts-x", {"SKILL.md": "verified — see `open-items.md` #12\n"}, items=[1])
    assert len(run(tmp_path)) == 1


def test_link_close_paren_before_hash_is_caught(tmp_path):
    """`](open-items.md) #16` — the number falls outside the link label."""
    skill(tmp_path, "ts-x",
          {"SKILL.md": "lives in [`open-items.md`](open-items.md) #16 and runs\n"}, items=[1])
    assert len(run(tmp_path)) == 1


def test_path_qualified_backtick_form_is_caught(tmp_path):
    skill(tmp_path, "ts-object-model-coach", {"SKILL.md": "x\n"}, items=[4])
    p = shared_file(tmp_path, "see `ts-object-model-coach/references/open-items.md` #12\n")
    known = known_map(tmp_path)
    problems = c.check_shared(p, tmp_path, known)
    assert len(problems) == 1 and "has no open-item #12" in problems[0]


# ── cross-runtime name collision (B2) ──────────────────────────────────────

def test_same_name_in_two_runtimes_resolves_against_the_copy_that_has_items(tmp_path):
    """cli and coco both carry ts-convert-from-snowflake-sv; only cli has open-items."""
    skill(tmp_path, "ts-convert-from-snowflake-sv", {"SKILL.md": "x\n"},
          items=[2, 3, 4, 5], runtime="cli")
    skill(tmp_path, "ts-convert-from-snowflake-sv", {"SKILL.md": "x\n"},
          items=None, runtime="coco-snowsight")
    p = shared_file(tmp_path, "See ts-convert-from-snowflake-sv open-item #3 for the finding.\n")
    known = known_map(tmp_path)
    assert c.check_shared(p, tmp_path, known) == []


def test_same_name_in_two_runtimes_still_fails_on_a_real_dangler(tmp_path):
    skill(tmp_path, "ts-convert-from-snowflake-sv", {"SKILL.md": "x\n"},
          items=[2, 3], runtime="cli")
    skill(tmp_path, "ts-convert-from-snowflake-sv", {"SKILL.md": "x\n"},
          items=None, runtime="coco-snowsight")
    p = shared_file(tmp_path, "See ts-convert-from-snowflake-sv open-item #99.\n")
    known = known_map(tmp_path)
    problems = c.check_shared(p, tmp_path, known)
    assert len(problems) == 1 and "has no open-item #99" in problems[0]


def test_shared_citation_reports_once_not_twice(tmp_path):
    """check_shared deduped on offset, so one citation printed twice."""
    skill(tmp_path, "ts-object-model-coach", {"SKILL.md": "x\n"}, items=[4])
    p = shared_file(tmp_path, "see [open-items.md #12](open-items.md) in ts-object-model-coach\n")
    known = known_map(tmp_path)
    assert len(c.check_shared(p, tmp_path, known)) == 1
