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

# Mirrors the real file's shape: a PLATFORMS array, then an ANGLES list that also uses
# `key:` (the rule-3 mis-pair risk), then a harness prompt that fetches outside PLATFORMS.
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

    const ANGLES = [
      { key: 'dead-files', n: 1, prompt: 'Find legacy/dead files. Use git + grep.' },
    ]

    const HARNESS_PROMPT = [
      'Use WebSearch / WebFetch against the official Claude Code docs and Anthropic model documentation.',
    ].join('\\n')
"""

# platform.claude.com is the host that SERVES the model docs; docs.claude.com and
# docs.anthropic.com only redirect to it cross-host (finding 18.3), so they are entry
# points rather than evidence and rule 5 does not assert them.
HARNESS_ALLOW = [
    "WebFetch(domain:code.claude.com)",
    "WebFetch(domain:platform.claude.com)",
]

BASE_ALLOW = [
    "WebSearch",
    "WebFetch(domain:docs.snowflake.com)",
    *HARNESS_ALLOW,
    "mcp__SpotterCode__get-rest-api-reference",
    "mcp__SpotterCode__get-developer-docs-reference",
]


def _repo(tmp_path, workflow=WORKFLOW, allow=None, deny=None, ask=None):
    (tmp_path / ".claude" / "workflows").mkdir(parents=True)
    (tmp_path / ".claude" / "workflows" / "repo-audit.js").write_text(
        textwrap.dedent(workflow), encoding="utf-8")
    perms = {"allow": BASE_ALLOW if allow is None else allow}
    perms["deny"] = ["mcp__SpotterCode__execute-thoughtspot-code"] if deny is None else deny
    if ask is not None:
        perms["ask"] = ask
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": perms}), encoding="utf-8")
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
    assert "permissions.allow" in r.stderr


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


def test_code_execution_tool_in_allow_is_rejected(tmp_path):
    r = _run(_repo(tmp_path, allow=BASE_ALLOW + ["mcp__SpotterCode__execute-thoughtspot-code"]))
    assert r.returncode == 1
    assert "permissions.allow" in r.stderr


def test_missing_deny_entry_is_caught(tmp_path):
    """Rule 4 is presence-of-deny, not absence-from-allow.

    As an absence check it was satisfiable by another settings scope allowing the tool;
    `deny` beats `allow` from every scope, so that is where the guarantee lives.
    """
    r = _run(_repo(tmp_path, deny=[]))
    assert r.returncode == 1
    assert "permissions.**deny**" in r.stderr


def test_execute_tool_named_in_workflow_is_not_demanded(tmp_path):
    """Rule 1 must not require the forbidden tool just because the text mentions it."""
    # Indented to match WORKFLOW's base indent — an unindented append defeats
    # textwrap.dedent, leaving the array closer indented so the block regex (rightly)
    # refuses to parse.
    wf = WORKFLOW + "    // never: mcp__SpotterCode__execute-thoughtspot-code\n"
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


def test_harness_docs_domain_missing_is_caught(tmp_path):
    """Rule 5. Angle 18 fetches outside PLATFORMS, so rule 3 never sees it.

    This is the gap the review found: the three domains were in the allow-list with
    nothing asserting they stayed there.
    """
    allow = [a for a in BASE_ALLOW if a not in HARNESS_ALLOW]
    r = _run(_repo(tmp_path, allow=allow))
    assert r.returncode == 1
    assert "platform.claude.com" in r.stderr
    assert "code.claude.com" in r.stderr


def test_partial_harness_domains_is_caught(tmp_path):
    """The finding-18.3 case: the serving host missing while an entry point is present."""
    allow = [a for a in BASE_ALLOW if "platform.claude.com" not in a]
    r = _run(_repo(tmp_path, allow=allow))
    assert r.returncode == 1
    assert "platform.claude.com" in r.stderr


def test_angles_key_does_not_manufacture_a_platform(tmp_path):
    """`key: 'dead-files'` sits outside PLATFORMS and must never pair with a research: text."""
    r = _run(_repo(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "dead-files" not in r.stderr


def test_missing_platforms_block_fails_rather_than_passing(tmp_path):
    """A checker that goes green because it could not parse is the failure mode."""
    wf = WORKFLOW.replace("const PLATFORMS = [", "const RENAMED = [")
    r = _run(_repo(tmp_path, workflow=wf))
    assert r.returncode == 1
    assert "could not parse" in r.stderr or "Could not locate" in r.stderr


# --- rule 6: deny / ask are as blocking as a missing allow ------------------------

def test_required_tool_in_deny_is_caught(tmp_path):
    """Listed in BOTH allow and deny previously reported clean."""
    r = _run(_repo(tmp_path, deny=["mcp__SpotterCode__execute-thoughtspot-code", "WebSearch"]))
    assert r.returncode == 1
    assert "beats allow" in r.stderr


def test_required_domain_in_ask_is_caught(tmp_path):
    r = _run(_repo(tmp_path, ask=["WebFetch(domain:docs.snowflake.com)"]))
    assert r.returncode == 1
    assert "still prompts" in r.stderr


# --- rule 3: quote styles and unreadable entries ----------------------------------

def test_double_quoted_research_on_a_shipped_platform_is_still_checked(tmp_path):
    """The false pass the review found: one quote change hid a real missing domain."""
    wf = WORKFLOW.replace(
        "research: 'Use WebSearch / WebFetch against current Snowflake docs.',",
        'research: "Use WebSearch / WebFetch against current Snowflake docs.",')
    allow = [a for a in BASE_ALLOW if "snowflake" not in a]
    r = _run(_repo(tmp_path, workflow=wf, allow=allow))
    assert r.returncode == 1
    assert "docs.snowflake.com" in r.stderr


def test_template_literal_research_is_read(tmp_path):
    wf = WORKFLOW.replace(
        "research: 'Use WebSearch / WebFetch against current Snowflake docs.',",
        "research: `Use WebSearch / WebFetch against current Snowflake docs.`,")
    allow = [a for a in BASE_ALLOW if "snowflake" not in a]
    r = _run(_repo(tmp_path, workflow=wf, allow=allow))
    assert r.returncode == 1
    assert "docs.snowflake.com" in r.stderr


def test_unreadable_entry_fails_rather_than_thinning_the_set(tmp_path):
    wf = WORKFLOW.replace("        key: 'snowflake', label: 'Snowflake',\n", "        label: 'Snowflake',\n")
    r = _run(_repo(tmp_path, workflow=wf))
    assert r.returncode == 1
    assert "no readable" in r.stderr


# --- rule 5: hosts, not a constant ------------------------------------------------

def test_new_url_host_outside_platforms_is_caught(tmp_path):
    wf = WORKFLOW + "    const X = ['Use WebFetch against https://docs.getdbt.com/reference'].join('x')\n"
    r = _run(_repo(tmp_path, workflow=wf))
    assert r.returncode == 1
    assert "docs.getdbt.com" in r.stderr


def test_reworded_harness_prompt_fails_loudly(tmp_path):
    """A constant cannot notice a reword, so the phrase itself is asserted."""
    wf = WORKFLOW.replace("Anthropic model documentation", "the model lineup page")
    r = _run(_repo(tmp_path, workflow=wf))
    assert r.returncode == 1
    assert "TEXT_HOST_HINTS" in r.stderr


def test_js_property_access_is_not_read_as_a_host(tmp_path):
    """`p.key` / `args.scope` / `pyproject.toml` are not hosts (11 false failures once)."""
    wf = WORKFLOW + "    const f = PLATFORMS.map(p => p.key + args.scope + 'pyproject.toml')\n"
    r = _run(_repo(tmp_path, workflow=wf))
    assert r.returncode == 0, r.stderr


# --- legitimate broadening --------------------------------------------------------

def test_bare_webfetch_satisfies_every_domain(tmp_path):
    """A maintainer who drops domain-scoping must not get a red gate listing the rules
    they deliberately superseded."""
    allow = [a for a in BASE_ALLOW if not a.startswith("WebFetch(")] + ["WebFetch"]
    r = _run(_repo(tmp_path, allow=allow))
    assert r.returncode == 0, r.stderr
