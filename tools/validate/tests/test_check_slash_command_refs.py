"""Unit tests for check_slash_command_refs — dangling /ts-<skill> mention guard.

Key behaviours: match a genuine slash-command mention (backtick/space/paren before
the slash); do NOT match file paths, relative links, or `~/.claude/skills/...`
paths (word char, `.`, `/`, or `#` before the slash); resolve names against real
tracked skill directories; allowlisted planned-skill names never fail.
"""
import check_slash_command_refs as sc


def test_matches_backtick_wrapped_mention():
    hits = sc.find_mentions("Use `/ts-audit` to scan the instance.")
    assert hits == [(1, "ts-audit")]


def test_matches_mention_after_space():
    hits = sc.find_mentions("See the /ts-dependency-manager skill for this.")
    assert hits == [(1, "ts-dependency-manager")]


def test_matches_mention_in_parens():
    hits = sc.find_mentions("(/ts-object-model-coach) does AI context review.")
    assert hits == [(1, "ts-object-model-coach")]


def test_does_not_match_relative_path():
    text = "See [Step 5](../ts-object-answer-promote/SKILL.md) for details."
    assert sc.find_mentions(text) == []


def test_does_not_match_repo_path():
    text = "Symlink agents/cli/ts-audit into ~/.claude/skills/ts-audit."
    assert sc.find_mentions(text) == []


def test_does_not_match_home_dir_skills_path():
    text = "ln -s ~/thoughtspot-agent-skills/agents/cli/ts-variable-timezone \\\n" \
           "      ~/.claude/skills/ts-variable-timezone"
    assert sc.find_mentions(text) == []


def test_does_not_match_markdown_anchor():
    text = "See [the audit skill](#ts-audit) below."
    assert sc.find_mentions(text) == []


def test_matches_at_start_of_line():
    hits = sc.find_mentions("/ts-audit is the entry point.")
    assert hits == [(1, "ts-audit")]


def test_line_numbers_are_1_indexed_and_multiline():
    text = "line one\nline two mentions `/ts-audit` here\nline three"
    hits = sc.find_mentions(text)
    assert hits == [(2, "ts-audit")]


def test_known_skill_names_reads_tracked_skill_dirs(tmp_path):
    (tmp_path / "agents" / "cli" / "ts-audit").mkdir(parents=True)
    (tmp_path / "agents" / "cli" / "ts-audit" / "SKILL.md").write_text("x", encoding="utf-8")
    (tmp_path / "agents" / "cli" / "ts-untracked").mkdir(parents=True)
    (tmp_path / "agents" / "cli" / "ts-untracked" / "SKILL.md").write_text("x", encoding="utf-8")
    tracked = {"agents/cli/ts-audit/SKILL.md"}  # ts-untracked deliberately absent
    names = sc._known_skill_names(tmp_path, tracked)
    assert names == {"ts-audit"}


def test_allowlisted_planned_skill_is_in_allowlist():
    assert "ts-object-model-builder" in sc.ALLOWLIST
