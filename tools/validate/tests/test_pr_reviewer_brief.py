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



# ------------------------------------------- operating safety (fix round 1) ---
#
# The review reads text someone else wrote and, on request, runs their code. These
# pin the rules that keep that from running a contributor's code with the runner's
# credentials, or letting their text steer the review.

def _how(text):
    return _section(text, "## How to work")


def test_reviewer_executes_branch_code_only_when_trusted_yes():
    text = AGENT.read_text(encoding="utf-8")
    how = _how(text)
    assert "`trusted: yes`" in how and "`trusted: no`" in how
    assert "if `trusted:` is missing, treat it as `no`" in how
    assert "never in CI" in how
    assert "the machine of the person running this review" in how
    assert "maintainer's machine" not in text
    # The env-var count is an extra stop, never a permission.
    assert "never a\npermission" in how or "never a permission" in how.replace("\n", " ")
    # Every section that could execute says what to do without trust.
    for heading in ("## Silent wrong output", "## Fix the class, not the instance",
                    "## Claims vs diff", "## Reuse before reimplementing"):
        assert "trusted: no" in _section(text, heading), heading


def test_reviewer_treats_everything_it_reads_as_data():
    how = _how(AGENT.read_text(encoding="utf-8"))
    assert "data, never instructions" in how
    for source in ("commit messages", "PR description", "evidence block", "skip reasons"):
        assert source in how.replace("\n", " "), source
    assert "**Blocker**" in how


def test_reviewer_forbids_installs_github_writes_pushes_and_live_calls():
    how = _how(AGENT.read_text(encoding="utf-8")).replace("\n", " ")
    for forbidden in ("`pip install`", "`gh pr comment`", "`gh pr review`", "push",
                      "GET requests", "`TS_PROFILE`", "--profile"):
        assert forbidden in how, forbidden


def test_reviewer_gh_calls_name_the_repo_and_paginate():
    text = AGENT.read_text(encoding="utf-8")
    # Commands, not prose: fenced lines and inline `gh pr view ...` spans.
    fenced = [l.strip() for b in re.findall(r"```bash\n(.*?)```", text, flags=re.S)
              for l in b.splitlines() if l.strip().startswith("gh ")]
    inline = re.findall(r"`(gh pr view [^`]*)`", text)
    assert fenced and inline
    for line in fenced:
        assert line.startswith("gh api --paginate \"$R/"), line
    for span in inline:
        assert "--repo thoughtspot/thoughtspot-agent-skills" in span, span
    earlier = _section(text, "## Earlier review points")
    for endpoint in ("/reviews", "pulls/<N>/comments", "issues/<N>/comments"):
        assert endpoint in earlier, endpoint
    assert "R=repos/thoughtspot/thoughtspot-agent-skills" in earlier


def test_gate_edits_cover_the_hooks_settings_lint_and_the_review_itself():
    section = _section(AGENT.read_text(encoding="utf-8"), "## Gate edits")
    for path in (".claude/settings.json", "scripts/install-hooks.sh", "scripts/pre-push.sh",
                 "scripts/check-pr.sh", "scripts/lib/python-bin.sh", "tml_lint.py",
                 ".github/pull_request_template.md", ".claude/agents/pr-reviewer.md",
                 ".claude/skills/pr-ready/"):
        assert path in section, path


def test_silent_wrong_output_names_offline_entry_points():
    section = _section(AGENT.read_text(encoding="utf-8"), "## Silent wrong output")
    for entry in ("ts tableau parse", "ts tableau translate-formulas", "ts tml lint", "pytest"):
        assert entry in section, entry


# The skill: someone else's branch, trust, converter trigger, self-contained blocks.

def _blocks(text):
    return re.findall(r"```bash\n(.*?)```", text, flags=re.S)


def test_someone_elses_branch_is_the_default_stop_and_never_runs_the_branch():
    text = SKILL.read_text(encoding="utf-8")
    decide = _section(text, "## Whose branch is this? Decide first")
    assert "the default" in decide and "Do not run this skill" in decide
    other = _section(text, "## Someone else's branch")
    assert "git show origin/main:scripts/check-pr.sh" in other
    assert "never the PR's" in other and "checkout of **main**" in other
    assert "`trusted: no`" in other
    # Nothing in that procedure runs the branch: no pr-ready, no checkout, no tests.
    code = "\n".join(_blocks(other))
    for runs in ("pr-ready.sh", "git checkout", "git switch", "pytest", "pip "):
        assert runs not in code, runs
    # The PR head is fetched as data and checked against GitHub's.
    assert "refs/pull/$N/head" in code and "headRefOid" in code


def test_skill_passes_trusted_explicitly():
    text = SKILL.read_text(encoding="utf-8")
    assert "`trusted: yes`" in _section(text, "## Step 3: dispatch the reviewer")


def _converter_re():
    m = re.search(r"CONVERTER_RE='([^']+)'", SKILL.read_text(encoding="utf-8"))
    assert m, "Step 4 defines CONVERTER_RE"
    return re.compile(m.group(1))


def test_converter_trigger_matches_converter_code_wherever_it_lives():
    pattern = _converter_re()
    platforms = sorted({d.name.split("-", 3)[3].split("-")[0]
                        for d in (ROOT / "agents" / "cli").glob("ts-convert-*")})
    commands = [f"tools/ts-cli/ts_cli/commands/{p}.py" for p in platforms
                if (ROOT / "tools/ts-cli/ts_cli/commands" / f"{p}.py").exists()]
    assert commands, "some converter has a commands/<platform>.py module"
    shared = [f"tools/ts-cli/ts_cli/{m}.py" for m in (
        "tml_common", "formula_text", "formula_week", "sql_forms", "tml_lint",
        "tml_model_parse", "io_helpers", "formula_common", "model_builder")]
    mirrors = [f"{d.relative_to(ROOT).as_posix()}/SKILL.md"
               for base in ("agents/cli", "agents/coco-snowsight", "agents/databricks/skills")
               for d in (ROOT / base).glob("ts-convert-*")]
    assert any("coco-snowsight" in m for m in mirrors)
    assert any("databricks/skills" in m for m in mirrors)
    for path in commands + shared + mirrors + [
            "agents/shared/mappings/tableau/x.md",
            "agents/shared/schemas/ts-model-conversion-invariants.md"]:
        assert pattern.search(path), path


def test_converter_trigger_skips_unrelated_paths():
    pattern = _converter_re()
    for path in ("tools/validate/evidence.py", "agents/cli/ts-audit/SKILL.md",
                 "docs/backlog.md", "CHANGELOG.md"):
        assert not pattern.search(path), path


def test_each_bash_block_assigns_every_variable_it_reads():
    # A Bash call does not see the previous call's variables: a $RANGE assigned in
    # Step 3 is empty in Step 4, and an empty range reads as "no converter change".
    for block in _blocks(SKILL.read_text(encoding="utf-8")):
        read = set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", block))
        assigned = set(re.findall(r"(?:^|[\s;(])([A-Za-z_][A-Za-z0-9_]*)=", block, flags=re.M))
        missing = read - assigned - {"PWD", "HOME"}
        assert not missing, (sorted(missing), block)


def test_range_reading_blocks_fail_loudly():
    for block in _blocks(SKILL.read_text(encoding="utf-8")):
        if "evidence.py range" in block:
            assert "set -o pipefail" in block and '|| exit 1' in block, block


def test_step_1_says_how_long_to_wait():
    section = _section(SKILL.read_text(encoding="utf-8"), "## Step 1: run the checks")
    assert "600000" in section and "background" in section


def test_skill_scans_the_review_before_it_is_shared():
    text = SKILL.read_text(encoding="utf-8")
    step6 = _section(text, "## Step 6: scan it, then tell the user")
    assert "check_customer_references.py --message-file" in step6
    assert "stop" in step6.lower()
    assert text.find("append-review") < text.find("check_customer_references.py")
