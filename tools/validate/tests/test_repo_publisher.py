"""The repo-publisher agent opens PRs with the template's body, evidence included.

`gh pr create --body "<summary + test plan>"` skipped `.github/pull_request_template.md`
entirely: no Evidence block, no live-evidence pointer, no dependency or Supersedes
sections, no confidentiality checkbox. So a PR the agent opened carried none of
what the pr-ready process asks every PR for. These pin the agent's Step 4 to the
template and to an evidence block that describes the head being published.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AGENT = ROOT / ".claude" / "agents" / "repo-publisher.md"
TEMPLATE = ROOT / ".github" / "pull_request_template.md"
STEP_4 = "### Step 4:"


def _step4() -> str:
    text = AGENT.read_text(encoding="utf-8")
    return text.split(STEP_4, 1)[1].split("\n### ", 1)[0]


def _code(text: str) -> str:
    return "\n".join(re.findall(r"```bash\n(.*?)```", text, flags=re.S))


def test_pr_body_is_the_filled_template_never_an_inline_body():
    text = AGENT.read_text(encoding="utf-8")
    creates = [line for line in _code(text).splitlines() if "gh pr create" in line]
    assert creates, "the agent no longer opens the PR?"
    for line in creates:
        assert "--body-file" in line and not re.search(r"--body(\s|=)", line), line
    step4 = _step4()
    assert ".github/pull_request_template.md" in step4
    assert "never edited" in step4.lower() or "as it is" in step4


def test_step_4_names_every_template_section():
    step4 = _step4()
    headings = [line[3:].strip() for line in TEMPLATE.read_text(encoding="utf-8").splitlines()
                if line.startswith("## ")]
    assert headings, "the template has no sections?"
    for heading in headings:
        assert heading in step4, heading


def test_step_4_checks_the_evidence_describes_this_head_before_pushing():
    step4 = _step4()
    code = _code(step4)
    assert "tools/validate/evidence.py range" in code
    assert "git rev-parse HEAD" in code
    assert "**READY**" in code or "READY" in code
    assert "DIRTY" in code
    # The block and the body are scanned before anything is public.
    assert 'check_secrets.py --file "$EVIDENCE"' in code
    assert 'check_customer_references.py --text-file "$EVIDENCE"' in code
    assert 'check_secrets.py --file "$BODY"' in code
    assert 'check_customer_references.py --text-file "$BODY"' in code
    assert code.index("evidence.py range") < code.index("git push")
    # It does not run the pr-ready skill or script on the user's behalf.
    assert "scripts/pr-ready.sh" not in code


def test_guardrails_forbid_a_hand_written_body():
    guardrails = AGENT.read_text(encoding="utf-8").split("## Guardrails", 1)[1]
    assert "--body" in guardrails and "pull_request_template.md" in guardrails
