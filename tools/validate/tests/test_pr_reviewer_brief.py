"""Tests for the `pr-reviewer` agent brief and the `pr-ready` skill (spec C2).

Both are prose an agent follows, so what can be pinned is their shape: the brief
keeps every area spec C2 lists (a dropped heading is a review area nobody checks
any more), it stays a review gate in the routing sense (`effort: max`, no model
pin, a `tools:` grant that admits Bash can mutate), and the skill keeps the order
that makes its output evidence — the CI-superset run first, stop on failure, the
reviewer on the diff, the converter auditor when converters change — and never
posts on its own.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AGENT = ROOT / ".claude" / "agents" / "pr-reviewer.md"
SKILL = ROOT / ".claude" / "skills" / "pr-ready" / "SKILL.md"
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"

SECTIONS = [
    "## Silent wrong output",
    "## Fix the class, not the instance",
    "## Claims vs diff",
    "## Reuse before reimplementing",
    "## Earlier review points",
    "## Destructive paths",
    "## Security basics",
    "## Gate edits",
    "## Output format",
]


def _frontmatter(path: Path) -> list:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---", f"{path} has no frontmatter"
    end = lines.index("---", 1)
    return lines[1:end]


def _section(text: str, heading: str) -> str:
    return text.split(heading + "\n", 1)[1].split("\n## ", 1)[0]


def _fenced(text: str) -> str:
    """Everything inside ``` blocks: the commands the skill tells an agent to run."""
    return "\n".join(re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.S))


# --------------------------------------------------------------- the agent ---

def test_reviewer_has_required_sections():
    text = AGENT.read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    for heading in SECTIONS:
        assert heading in headings, f"missing {heading!r}"
    # The output format closes the brief, so it is what the agent reads last.
    assert headings[-1] == "## Output format", headings


def test_reviewer_frontmatter():
    block = _frontmatter(AGENT)
    keys = {line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip()
            for line in block if ":" in line and not line.lstrip().startswith("#")}
    assert keys.get("name") == "pr-reviewer"
    assert keys.get("effort") == "max", "a review gate runs at max effort (model-routing.md)"
    assert keys.get("tools"), "a reporter declares its grant (model-routing.md)"
    assert "Bash" in keys["tools"] and "Edit" not in keys["tools"] and "Write" not in keys["tools"]
    assert not any(line.startswith("model:") for line in block), "no model pin"
    comments = " ".join(line for line in block if line.lstrip().startswith("#"))
    assert "Bash can mutate" in comments, "the grant narrows, it does not close"


def test_reviewer_description_says_refute_against_upstream_main():
    desc = next(line for line in _frontmatter(AGENT) if line.startswith("description:"))
    assert "refute" in desc.lower() and "upstream main" in desc


def test_silent_wrong_output_is_local_only_and_never_with_untrusted_text_and_secrets():
    section = _section(AGENT.read_text(encoding="utf-8"), "## Silent wrong output").lower()
    assert "locally only" in section
    assert "untrusted" in section and "secrets" in section


def test_every_section_says_what_to_check_and_what_evidence_to_report():
    text = AGENT.read_text(encoding="utf-8")
    for heading in SECTIONS[:-1]:
        section = _section(text, heading)
        assert "**What to check.**" in section, heading
        assert "**Evidence to report.**" in section, heading


def test_output_format_ranks_findings_and_closes_with_what_was_checked():
    section = _section(AGENT.read_text(encoding="utf-8"), "## Output format")
    for rank in ("### Blocker", "### Should-fix", "### Nit"):
        assert rank in section
    assert "file:line" in section and "what was tried" in section.lower()
    assert "What I checked and found nothing" in section


def test_reviewer_defaults_to_a_problem_when_uncertain():
    assert "this is a problem" in AGENT.read_text(encoding="utf-8")


def test_reviewer_cites_past_prs_by_number_only():
    # Public repo: a past example is `#NNN`, never a person's or customer's name.
    text = AGENT.read_text(encoding="utf-8")
    assert re.search(r"#\d{3}", text), "past examples are cited by PR number"
    assert "@" not in text.replace("Co-Authored-By", ""), "no handles in the brief"


# --------------------------------------------------------------- the skill ---

def test_skill_invokes_pr_ready_and_reviewer():
    text = SKILL.read_text(encoding="utf-8")
    assert "scripts/pr-ready.sh" in text
    assert "pr-reviewer" in text
    assert "conversion-consistency-auditor" in text
    assert "check_converter_parity.py" in text


def test_skill_frontmatter_names_it_and_says_when_to_use_it():
    block = _frontmatter(SKILL)
    assert "name: pr-ready" in block
    desc = next(line for line in block if line.startswith("description:")).lower()
    assert "before opening" in desc and "self-merg" in desc


def test_skill_steps_run_in_order():
    # The procedure, not the description that names the parts up front.
    text = SKILL.read_text(encoding="utf-8").split("## Step 1", 1)[1]
    order = ["bash scripts/pr-ready.sh --no-review", "pr-reviewer",
             "conversion-consistency-auditor", "append-review"]
    positions = [text.find(marker) for marker in order]
    assert all(p >= 0 for p in positions), dict(zip(order, positions))
    assert positions == sorted(positions), dict(zip(order, positions))


def test_skill_stops_when_pr_ready_fails():
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "exits non-zero" in text and "stop" in text


def test_skill_never_posts_on_its_own():
    text = SKILL.read_text(encoding="utf-8")
    assert "--post" not in _fenced(text), "posting is the user's choice, never a step"
    assert "never" in _section(text, "## Posting").lower()


def test_skill_is_advisory_and_run_before_self_merge():
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "advisory" in text and "self-merg" in text


def test_skill_reads_the_diff_range_from_the_evidence():
    # The base is what pr-ready resolved and fetched, never re-derived here.
    assert "tools/validate/evidence.py range" in _fenced(SKILL.read_text(encoding="utf-8"))


def test_codeowners_covers_the_reviewer_and_the_skill():
    owners = CODEOWNERS.read_text(encoding="utf-8")
    assert re.search(r"^/\.claude/agents/pr-reviewer\.md\s+@", owners, re.M)
    assert re.search(r"^/\.claude/skills/pr-ready/\s+@", owners, re.M)
