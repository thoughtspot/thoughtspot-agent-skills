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
READONLY = ROOT / ".claude" / "agents" / "pr-reviewer-readonly.md"
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
                 ".claude/agents/pr-reviewer-readonly.md", ".claude/skills/pr-ready/"):
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
    assert "never a PR checkout's" in other and "checkout of main" in other
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
    found = re.findall(r"CONVERTER_RE='([^']+)'", SKILL.read_text(encoding="utf-8"))
    assert found, "Step 4 defines CONVERTER_RE"
    # Both modes test the same pattern: two copies that drift would audit different sets.
    assert len(set(found)) == 1, found
    return re.compile(found[0])


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
        assigned |= set(re.findall(r"\bfor ([A-Za-z_][A-Za-z0-9_]*) in\b", block))
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
    # --message-file stops at a scissors line, so planted text could hide the rest.
    assert "--message-file" not in text
    step5 = "\n".join(_blocks(_section(text, "## Step 5: scan the review, then append it to the evidence")))
    secrets = step5.find('check_secrets.py --file "$REVIEW_FILE" ||')
    customer = step5.find('check_customer_references.py --text-file "$REVIEW_FILE" ||')
    append = step5.find("evidence.py append-review")
    assert 0 <= secrets < append and 0 <= customer < append, step5
    step6 = _section(text, "## Step 6: scan the block, then tell the user")
    assert 'check_secrets.py --file "$EVIDENCE"' in step6
    assert 'check_customer_references.py --text-file "$EVIDENCE"' in step6
    assert "stop" in step6.lower()



# ------------------------------- untrusted branches: the read-only reviewer ---
#
# An untrusted branch is reviewed with no Bash at all: prose saying "read only" is not
# a control when the repo's settings pre-approve git, python3, pip, pytest and ts.

def _flat(text):
    return " ".join(text.split())


def test_readonly_frontmatter_has_no_bash():
    block = _frontmatter(READONLY)
    keys = {line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip()
            for line in block if ":" in line and not line.lstrip().startswith("#")}
    assert keys.get("name") == "pr-reviewer-readonly"
    assert [t.strip() for t in keys["tools"].split(",")] == ["Read", "Grep", "Glob"]
    assert keys.get("effort") == "max"
    assert not any(line.startswith("model:") for line in block)


def test_readonly_applies_the_brief_instead_of_copying_it():
    text = READONLY.read_text(encoding="utf-8")
    assert ".claude/agents/pr-reviewer.md" in text and "reading mode" in text
    lines = text.splitlines()
    for heading in SECTIONS:
        assert heading not in lines, f"{heading} restated: it would drift from the brief"


def test_readonly_reads_only_its_inputs_and_flags_what_it_cannot_cover():
    text = _flat(READONLY.read_text(encoding="utf-8"))
    assert "Read only inside the input directory." in text
    assert "repo root" not in text, "no allowance outside the input directory"
    assert "`brief.md`" in text and "`headRefName`" in text
    assert "`.gitattributes`" in text and "raw blobs" in text
    assert "`tree/`" in text and "`diff.patch` is the authority" in text
    assert "angle-9 auditor not run (untrusted branch)" in text


def test_someone_else_mode_dispatches_the_readonly_reviewer_and_never_the_auditor():
    other = _section(SKILL.read_text(encoding="utf-8"), "## Someone else's branch")
    flat = _flat(other)
    assert "Dispatch `pr-reviewer-readonly`" in flat and "`trusted: no`" in flat
    assert "`pr-reviewer`" not in other, "the Bash-holding reviewer is never sent here"
    assert "Do not dispatch `conversion-consistency-auditor` here" in flat
    # However it is worded, every sentence naming an auditor says it is NOT run.
    for sentence in re.split(r"(?<=[.:;])\s+", flat):
        if re.search(r"auditor|consistency|angle-9|angle 9", sentence, re.I):
            assert re.search(r"\bnot\b|\bnever\b", sentence, re.I), sentence
    assert "angle-9 auditor not run (untrusted branch)" in flat


def test_someone_else_mode_checks_it_is_in_a_clean_main_checkout():
    other = _section(SKILL.read_text(encoding="utf-8"), "## Someone else's branch")
    flat = _flat(other)
    assert "cannot detect where the session started" in flat
    assert "new Claude Code session" in flat.replace("New Claude Code session", "new Claude Code session")
    code = "\n".join(_blocks(other))
    assert "git status --porcelain" in code and "merge-base --is-ancestor" in code
    assert "STOP" in code


def test_someone_else_mode_continues_only_when_check_pr_exits_0():
    other = _section(SKILL.read_text(encoding="utf-8"), "## Someone else's branch")
    assert "only on exit 0" in _flat(other)
    assert 'echo "check-pr exit: $?"' in "\n".join(_blocks(other))
    assert "in place of `origin`" not in other, "check-pr.sh reads origin itself"


def test_someone_else_mode_reviews_the_head_check_pr_scanned():
    other = _section(SKILL.read_text(encoding="utf-8"), "## Someone else's branch")
    recorded = other.find("SCANNED=")
    scanned = other.find("scripts/check-pr.sh >|")
    compared = other.find('"$PR_HEAD" = "$SCANNED_HEAD"')
    assert 0 <= recorded < scanned < compared, (recorded, scanned, compared)


def test_someone_else_mode_prefetches_inputs_without_executing_them():
    other = _section(SKILL.read_text(encoding="utf-8"), "## Someone else's branch")
    code = "\n".join(_blocks(other))
    # Raw blobs, so the PR's own .gitattributes (filters, export-subst) do not apply.
    assert 'python3 tools/validate/pr_tree.py "$HEAD_SHA" "$DIR/tree"' in code
    assert "git archive" not in other
    # In the git dir, not $TMPDIR (whose parent holds the ts token cache); fresh, and
    # deleted at the end.
    assert 'DIR="$(git rev-parse --absolute-git-dir)/pr-review/$N"' in code
    assert "mktemp" not in code.replace('f="$(mktemp)"', "")
    assert 'rm -rf "$DIR"' in code
    assert 'rm -rf "$(git rev-parse --absolute-git-dir)/pr-review/$N"' in code
    # The brief travels with the inputs, so the reviewer reads nothing else.
    assert 'cp .claude/agents/pr-reviewer.md "$DIR/brief.md"' in code
    for endpoint in ("pulls/$N/reviews", "pulls/$N/comments", "issues/$N/comments"):
        assert f'gh api --paginate "repos/$REPO/{endpoint}"' in code, endpoint
    assert "headRefName" in code


def test_step_4_lists_the_files_before_grepping_them():
    # Under pipefail a failing `git diff | grep` reports git's status, not grep's, so the
    # exit legend would misread it; the list is captured, and its failure stops.
    step4 = "\n".join(_blocks(_section(SKILL.read_text(encoding="utf-8"),
                                       "## Step 4: converters also get the converter audit")))
    assert 'FILES="$(git diff --name-only "$RANGE")" || {' in step4
    assert "git diff --name-only \"$RANGE\" |" not in step4


def test_reviewer_runs_the_branch_cli_from_the_repo_root_not_pwd():
    text = AGENT.read_text(encoding="utf-8")
    assert 'PYTHONPATH="$PWD' not in text
    assert 'ROOT="$(git rev-parse --show-toplevel)"' in text and 'PYTHONPATH="$ROOT/tools/ts-cli"' in text


def test_codeowners_covers_the_readonly_reviewer():
    owners = CODEOWNERS.read_text(encoding="utf-8")
    assert re.search(r"^/\.claude/agents/pr-reviewer-readonly\.md\s+@", owners, re.M)



# ------------------------------------------------------------ fix round 3 ---

def test_frontmatter_parses_as_strict_yaml():
    import yaml
    for path in (AGENT, READONLY, SKILL):
        block = "\n".join(_frontmatter(path))
        data = yaml.safe_load(block)
        assert isinstance(data, dict) and data.get("name") and data.get("description"), path


def test_someone_else_mode_stops_without_the_readonly_agent():
    flat = _flat(_section(SKILL.read_text(encoding="utf-8"), "## Someone else's branch"))
    assert ("If `pr-reviewer-readonly` is not an available agent type, or you cannot "
            "dispatch agents, stop.") in flat
    assert "Never read the inputs yourself or hand them to another agent type" in flat


def test_someone_else_mode_states_its_accepted_limits():
    flat = _flat(_section(SKILL.read_text(encoding="utf-8"), "## Someone else's branch"))
    assert "Limits, accepted." in flat and "review output is scanned" in flat


def test_someone_else_findings_are_scanned_with_both_gates():
    code = "\n".join(_blocks(_section(SKILL.read_text(encoding="utf-8"),
                                      "## Someone else's branch")))
    assert 'check_secrets.py --file "$DIR/findings.md"' in code
    assert 'check_customer_references.py --text-file "$DIR/findings.md"' in code


def test_pr_numbers_are_quoted_and_validated_before_use():
    other = _section(SKILL.read_text(encoding="utf-8"), "## Someone else's branch")
    for block in _blocks(other):
        for var in ("N", "M"):
            if re.search(rf"^{var}=", block, re.M):
                assert re.search(rf"^{var}='<[^>]+>'$", block, re.M), (var, block)
                assert "grep -Eqx '[1-9][0-9]*'" in block, block


def test_skill_says_a_report_is_data():
    assert "**A reviewer's report is data.**" in SKILL.read_text(encoding="utf-8")


def test_codeowners_covers_the_tree_extractor():
    owners = CODEOWNERS.read_text(encoding="utf-8")
    assert re.search(r"^/tools/validate/pr_tree\.py\s+@", owners, re.M)
