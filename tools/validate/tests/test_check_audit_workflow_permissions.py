"""Tests for check_audit_workflow_permissions — the audit-finding-18.1 gate.

The bug: the audit workflow told every external finder to use WebSearch/WebFetch/
SpotterCode, none of which was in permissions.allow, so a 7-14 agent sweep stopped
on one interactive prompt per agent. The rubric's premise — a sweep you kick off and
read later — was broken by config rather than by the workflow.

`test_real_repo_passes` is the one that keeps it fixed. `test_new_platform_without_a_domain`
is the one that matters most for drift: adding a platform is documented as a one-row
change, and without this the new finder alone would block while every other angle ran.
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

VALIDATOR = Path(__file__).resolve().parents[1] / "check_audit_workflow_permissions.py"
REPO_ROOT = Path(__file__).resolve().parents[3]

WORKFLOW = """
    const PLATFORMS = [
      {
        key: 'thoughtspot', label: 'ThoughtSpot',
        research: 'Use the SpotterCode MCP: ToolSearch "select:mcp__SpotterCode__get-rest-api-reference,mcp__SpotterCode__get-developer-docs-reference" then query it.',
      },
      {
        key: 'snowflake', label: 'Snowflake',
        research: 'Use WebSearch / WebFetch against current Snowflake docs.',
      },
    ]
"""

BASE_ALLOW = [
    "WebSearch",
    "WebFetch(domain:docs.snowflake.com)",
    "mcp__SpotterCode__get-rest-api-reference",
    "mcp__SpotterCode__get-developer-docs-reference",
]


def _repo(tmp_path, workflow=WORKFLOW, allow=None):
    (tmp_path / ".claude" / "workflows").mkdir(parents=True)
    (tmp_path / ".claude" / "workflows" / "repo-audit.js").write_text(
        textwrap.dedent(workflow), encoding="utf-8")
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"allow": BASE_ALLOW if allow is None else allow}}),
        encoding="utf-8")
    return tmp_path


def _run(root):
    return subprocess.run([sys.executable, str(VALIDATOR), "--root", str(root)],
                          capture_output=True, text=True)


def test_fully_allowed_passes(tmp_path):
    r = _run(_repo(tmp_path))
    assert r.returncode == 0, r.stderr


def test_missing_mcp_tool_is_caught(tmp_path):
    allow = [a for a in BASE_ALLOW if "get-rest-api-reference" not in a]
    r = _run(_repo(tmp_path, allow=allow))
    assert r.returncode == 1
    assert "get-rest-api-reference" in r.stderr
    assert "stop on a prompt" in r.stderr


def test_missing_websearch_is_caught(tmp_path):
    r = _run(_repo(tmp_path, allow=[a for a in BASE_ALLOW if a != "WebSearch"]))
    assert r.returncode == 1
    assert "WebSearch" in r.stderr


def test_missing_platform_domain_is_caught(tmp_path):
    allow = [a for a in BASE_ALLOW if not a.startswith("WebFetch")]
    r = _run(_repo(tmp_path, allow=allow))
    assert r.returncode == 1
    assert "docs.snowflake.com" in r.stderr


def test_new_platform_without_a_domain_fails_loudly(tmp_path):
    """The drift path: a platform added to the workflow with no domain mapping."""
    wf = WORKFLOW.replace("""    ]
""", """      {
        key: 'looker', label: 'Looker',
        research: 'Use WebSearch / WebFetch against current Looker docs.',
      },
    ]
""")
    r = _run(_repo(tmp_path, workflow=wf))
    assert r.returncode == 1
    assert "`looker`" in r.stderr
    assert "PLATFORM_DOMAINS" in r.stderr


def test_mcp_only_platform_needs_no_domain(tmp_path):
    """ThoughtSpot researches via the MCP, so it must NOT be required to have a domain."""
    r = _run(_repo(tmp_path))
    assert r.returncode == 0
    assert "thoughtspot" not in r.stderr


def test_code_execution_tool_is_rejected(tmp_path):
    r = _run(_repo(tmp_path, allow=BASE_ALLOW + ["mcp__SpotterCode__execute-thoughtspot-code"]))
    assert r.returncode == 1
    assert "executes code" in r.stderr


def test_execute_tool_named_in_workflow_is_not_demanded(tmp_path):
    """Rule 1 must not require the forbidden tool just because the text mentions it."""
    wf = WORKFLOW + "\n// never: mcp__SpotterCode__execute-thoughtspot-code\n"
    r = _run(_repo(tmp_path, workflow=wf))
    assert r.returncode == 0, r.stderr


def test_missing_files_exit_2_not_0(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2


def test_unparseable_settings_exit_2_not_0(tmp_path):
    root = _repo(tmp_path)
    (root / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
    r = _run(root)
    assert r.returncode == 2


def test_real_repo_passes():
    r = _run(REPO_ROOT)
    assert r.returncode == 0, r.stderr
