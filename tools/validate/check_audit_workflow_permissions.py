#!/usr/bin/env python3
"""
check_audit_workflow_permissions.py — the audit sweep can actually run unattended.

Background (audit finding 18.1). `.claude/workflows/repo-audit.js` instructs every
external-angle finder to research against live vendor docs: WebSearch, WebFetch,
and the two read-only SpotterCode MCP tools. None of them was in
`.claude/settings.json` `permissions.allow`, so a 7- or 14-agent sweep stopped on
interactive permission prompts — one per agent. The rubric's whole premise is a
sweep you kick off and read later (`.claude/rules/repo-audit.md`), and that premise
was broken by config, not by the workflow.

The fix widened the allow-list. This check stops it silently narrowing again — and,
more importantly, stops it going stale. The recurrence path is concrete: add a
platform to the workflow's `PLATFORMS` table (the rubric documents that as a
one-row change) and its docs domain is not allowed, so that finder alone blocks
while every other angle runs. Nothing else in the repo reads either file for this.

Four rules:

  1. Every `mcp__<server>__<tool>` named in the workflow is allowed. These are
     spelled out in the prompt text the finder is told to load, so they are
     greppable and exact.
  2. `WebSearch` is allowed if the workflow tells any finder to use it.
  3. Every platform whose `research:` text mentions WebFetch has its docs domain
     allowed, via PLATFORM_DOMAINS below. A platform missing from that map is a
     FAILURE, not a skip — the map is the thing a new platform must update, and a
     silent skip would defeat the check exactly as a missed edit defeated the
     rubric's angle-9 agent (see repo-audit.md).
  4. `mcp__SpotterCode__execute-thoughtspot-code` is NOT allowed. It executes code
     against a live instance; no audit finder needs it, and a code-execution tool
     should not slip into a committed, team-wide allow-list without a reviewer
     seeing it. If it is ever genuinely needed, delete this rule deliberately.

Exit codes:
  0 — all rules pass
  1 — at least one violation
  2 — the check could not run (missing file, unparseable JSON); NOT a pass

Run manually:
    python3 tools/validate/check_audit_workflow_permissions.py --root .
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WORKFLOW_REL = ".claude/workflows/repo-audit.js"
SETTINGS_REL = ".claude/settings.json"

# Docs host per platform key in the workflow's PLATFORMS table. A platform that
# researches via WebFetch and is absent here fails rule 3 — deliberately, so adding
# a platform forces the permission decision rather than deferring it to a blocked run.
PLATFORM_DOMAINS = {
    "snowflake": "docs.snowflake.com",
    "databricks": "docs.databricks.com",
    "tableau": "help.tableau.com",
}

# Read-only by design; see rule 4.
FORBIDDEN_TOOLS = ("mcp__SpotterCode__execute-thoughtspot-code",)

MCP_RE = re.compile(r"mcp__[A-Za-z0-9_]+__[A-Za-z0-9_-]+")
# Non-greedy pair capture: each PLATFORMS entry is `key: '<k>', label: ...` then
# `research: '<text>'`. DOTALL because the two sit on separate lines.
PLATFORM_RE = re.compile(r"key:\s*'([a-z0-9-]+)'.*?research:\s*'(.*?)'", re.S)
WEBFETCH_DOMAIN_RE = re.compile(r"^WebFetch\(domain:([^)]+)\)$")


def check(root: Path) -> list[str]:
    wf_path, settings_path = root / WORKFLOW_REL, root / SETTINGS_REL
    for p in (wf_path, settings_path):
        if not p.exists():
            raise FileNotFoundError(f"{p.relative_to(root)} not found")

    workflow = wf_path.read_text(encoding="utf-8")
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    allow = list((settings.get("permissions") or {}).get("allow") or [])
    allow_set = set(allow)
    allowed_domains = {
        m.group(1) for m in (WEBFETCH_DOMAIN_RE.match(a) for a in allow) if m
    }

    failures: list[str] = []

    # Rule 1 — MCP tools named in the workflow.
    for tool in sorted(set(MCP_RE.findall(workflow))):
        if tool in FORBIDDEN_TOOLS:
            continue  # rule 4 owns this one
        if tool not in allow_set:
            failures.append(
                f"`{WORKFLOW_REL}` tells a finder to use `{tool}`, which is not in "
                f"`{SETTINGS_REL}` permissions.allow — that agent will stop on a prompt."
            )

    # Rule 2 — WebSearch.
    if "WebSearch" in workflow and "WebSearch" not in allow_set:
        failures.append(
            f"`{WORKFLOW_REL}` references WebSearch but it is not allowed in "
            f"`{SETTINGS_REL}`."
        )

    # Rule 3 — a docs domain per WebFetch-researching platform.
    for key, research in PLATFORM_RE.findall(workflow):
        if "WebFetch" not in research:
            continue
        domain = PLATFORM_DOMAINS.get(key)
        if domain is None:
            failures.append(
                f"Platform `{key}` researches via WebFetch but has no entry in "
                f"PLATFORM_DOMAINS in this checker. Add its docs host here AND a "
                f"`WebFetch(domain:...)` rule in {SETTINGS_REL}, or that finder alone "
                f"blocks while every other angle runs."
            )
        elif domain not in allowed_domains:
            failures.append(
                f"Platform `{key}` researches via WebFetch against `{domain}`, which is "
                f"not allowed. Add `WebFetch(domain:{domain})` to {SETTINGS_REL}."
            )

    # Rule 4 — the code-execution tool stays out.
    for tool in FORBIDDEN_TOOLS:
        if tool in allow_set:
            failures.append(
                f"`{tool}` is in {SETTINGS_REL} permissions.allow. It executes code "
                f"against a live instance and no audit finder needs it. Remove it — or, "
                f"if it is genuinely required, remove this rule from the checker so the "
                f"decision is visible in review."
            )

    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repository root")
    args = ap.parse_args()

    try:
        failures = check(Path(args.root).resolve())
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if failures:
        print("Audit-workflow permissions FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("Audit-workflow permissions clean: every researched tool is pre-approved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
