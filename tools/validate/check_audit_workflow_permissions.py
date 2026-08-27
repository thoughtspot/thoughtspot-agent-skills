#!/usr/bin/env python3
"""
check_audit_workflow_permissions.py — the audit sweep can actually run unattended.

Background (audit finding 18.1). `.claude/workflows/repo-audit.js` instructs the
external-angle finders to research against live vendor docs: WebSearch, WebFetch, and
the two read-only SpotterCode MCP tools. None was in `.claude/settings.json`
`permissions.allow`, so the external finders blocked on their first research call —
one prompt per distinct tool and host. The rubric's premise
(`.claude/rules/repo-audit.md`) is a sweep you start and read later; that premise was
broken by config, not by the workflow.

This checker stops the allow-list drifting back out of step with the workflow. Nothing
else in the repo reads both files.

Six rules:

  1. Every `mcp__<server>__<tool>` named in the workflow is allowed.
  2. `WebSearch` is allowed if the workflow tells any finder to use it.
  3. Every platform in `PLATFORMS` that researches via WebFetch has its docs host
     allowed, via PLATFORM_DOMAINS below. A platform missing from that map is a
     FAILURE, not a skip.
  4. `mcp__SpotterCode__execute-thoughtspot-code` is in `permissions.deny`. It runs
     code against a live instance and no finder needs it. `deny` rather than
     "absent from allow" because deny beats allow from EVERY scope — as an
     absence-check this rule was satisfiable by a local settings file allowing it.
  5. Every host named in a non-`PLATFORMS` WebFetch instruction is allowed. Angle
     18's `HARNESS_PROMPT` is the live case; the rule reads hosts out of the text
     rather than asserting a constant, because a constant is blind to a new one.
  6. Nothing required is in `permissions.deny` or `permissions.ask`. Both produce
     exactly the prompt this gate exists to prevent, and reading `allow` alone made
     a tool listed in both report clean.

Two lessons from review are worth keeping visible, because both were live defects:

  * **Read the sibling finding first.** The first version allowed `docs.claude.com`
    and `docs.anthropic.com` for angle 18. Both are pure cross-host redirectors to
    `platform.claude.com`, and WebFetch hands a cross-host redirect back to the
    caller — so the grant bought nothing. Finding **18.3** of the same audit report
    said so explicitly ("Replace with `code.claude.com` + `platform.claude.com`.
    Pairs with 18.1.") and was not read.
  * **A tolerant regex over source is a false pass.** Rule 3 first required
    single-quoted `key:`/`research:`. Double-quoting the research string on the
    ALREADY-SHIPPED tableau entry, with its domain removed from the allow-list,
    passed. Entries are now parsed one object at a time, any quote style, and the
    count is asserted against the number of objects in the block — a shape this
    file cannot read fails instead of silently thinning the set.

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
# researches via WebFetch and is absent here fails rule 3 — deliberately, so adding a
# platform forces the permission decision instead of deferring it to a blocked run.
PLATFORM_DOMAINS = {
    "snowflake": "docs.snowflake.com",
    "databricks": "docs.databricks.com",
    "tableau": "help.tableau.com",
}

FORBIDDEN_TOOL = "mcp__SpotterCode__execute-thoughtspot-code"

# Hosts rule 5 must find for angle 18's prompt, which names no URL literally. Keyed by a
# phrase in the instruction so a REWORDED prompt stops matching and fails loudly rather
# than passing on a stale constant. platform.claude.com is the one that serves content;
# the other two only redirect to it (finding 18.3) and are entry points, not evidence.
TEXT_HOST_HINTS = {
    "Anthropic model documentation": ("platform.claude.com",),
    "Claude Code docs": ("code.claude.com",),
}

MCP_RE = re.compile(r"mcp__[A-Za-z0-9_]+__[A-Za-z0-9_-]+")
PLATFORMS_BLOCK_RE = re.compile(r"const PLATFORMS\s*=\s*\[(.*?)^\]", re.S | re.M)
# One entry per `{ ... }` object, so a key can never pair with a neighbour's research text.
ENTRY_RE = re.compile(r"\{(.*?)\}", re.S)
KEY_RE = re.compile(r"""\bkey:\s*['"`]([A-Za-z0-9_-]+)['"`]""")
RESEARCH_RE = re.compile(r"""\bresearch:\s*['"`](.*?)['"`]""", re.S)
WEBFETCH_DOMAIN_RE = re.compile(r"^WebFetch\(domain:([^)]+)\)$")
# Hosts written as URLs. Deliberately NOT bare dotted words — this file is JavaScript, so
# `p.key`, `args.scope` and `pyproject.toml` all match a bare-hostname pattern and produced
# eleven false failures on the first cut. A prompt that names a fetch target writes a URL.
HOST_IN_URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")


def _rules(settings: dict, key: str) -> list[str]:
    return list((settings.get("permissions") or {}).get(key) or [])


def _domains(rules: list[str]) -> set[str]:
    return {m.group(1) for m in (WEBFETCH_DOMAIN_RE.match(r) for r in rules) if m}


def check(root: Path) -> list[str]:
    wf_path, settings_path = root / WORKFLOW_REL, root / SETTINGS_REL
    for p in (wf_path, settings_path):
        if not p.exists():
            raise FileNotFoundError(f"{p.relative_to(root)} not found")

    workflow = wf_path.read_text(encoding="utf-8")
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    allow, deny, ask = (_rules(settings, k) for k in ("allow", "deny", "ask"))
    allow_set, deny_set, ask_set = set(allow), set(deny), set(ask)
    allowed_domains, denied_domains = _domains(allow), _domains(deny) | _domains(ask)
    # A bare `WebFetch` grant covers every host — a legitimate broadening that must not
    # be reported as six missing domains.
    fetch_all = "WebFetch" in allow_set

    failures: list[str] = []

    def require(rule: str, why: str) -> None:
        """Rules 1, 2 and 6 for a single permission string."""
        if rule not in allow_set:
            failures.append(f"{why} `{rule}` is not in {SETTINGS_REL} permissions.allow.")
        if rule in deny_set:
            failures.append(f"{why} `{rule}` is in permissions.**deny**, which beats allow.")
        if rule in ask_set:
            failures.append(f"{why} `{rule}` is in permissions.**ask**, so it still prompts.")

    def require_domain(host: str, why: str) -> None:
        if not fetch_all and host not in allowed_domains:
            failures.append(f"{why} `WebFetch(domain:{host})` is not allowed.")
        if host in denied_domains:
            failures.append(f"{why} `{host}` is denied or ask-listed, so it still prompts.")

    # Rule 1 — MCP tools named in the workflow.
    for tool in sorted(set(MCP_RE.findall(workflow))):
        if tool == FORBIDDEN_TOOL:
            continue  # rule 4 owns it
        require(tool, f"The workflow tells a finder to use")

    # Rule 2 — WebSearch.
    if "WebSearch" in workflow:
        require("WebSearch", "The workflow references WebSearch, but")

    # Rule 3 — a docs host per WebFetch-researching platform.
    block = PLATFORMS_BLOCK_RE.search(workflow)
    if block is None:
        failures.append(
            f"Could not locate `const PLATFORMS = [ ... ]` in {WORKFLOW_REL}. Rule 3 "
            f"cannot run, and a checker that passes because it could not parse is worse "
            f"than no checker — fix the pattern or the file."
        )
        platforms_block, entries = "", []
    else:
        platforms_block = block.group(1)
        objects = ENTRY_RE.findall(platforms_block)
        entries = [
            (KEY_RE.search(o), RESEARCH_RE.search(o)) for o in objects
        ]
        unreadable = [i for i, (k, r) in enumerate(entries) if k is None or r is None]
        if unreadable:
            failures.append(
                f"{len(unreadable)} of {len(objects)} PLATFORMS entries have no readable "
                f"`key:`/`research:` pair (indexes {unreadable}). Rule 3 would skip them "
                f"silently, so it fails instead. Check quoting — a template literal or a "
                f"reordered key is the usual cause."
            )
        for k, r in entries:
            if k is None or r is None:
                continue
            key, research = k.group(1), r.group(1)
            if "WebFetch" not in research:
                continue
            host = PLATFORM_DOMAINS.get(key)
            if host is None:
                failures.append(
                    f"Platform `{key}` researches via WebFetch but has no entry in "
                    f"PLATFORM_DOMAINS in this checker. Add its docs host here AND a "
                    f"`WebFetch(domain:...)` rule in {SETTINGS_REL}, or that finder alone "
                    f"blocks while every other angle runs."
                )
            else:
                require_domain(host, f"Platform `{key}` fetches `{host}`, but")

    # Rule 4 — the code-execution tool is denied, not merely unlisted.
    if FORBIDDEN_TOOL not in deny_set:
        failures.append(
            f"`{FORBIDDEN_TOOL}` is not in {SETTINGS_REL} permissions.**deny**. It executes "
            f"code against a live instance and no audit finder needs it; deny (not absence "
            f"from allow) is what holds when another settings scope allows it. If it is "
            f"genuinely required, remove this rule so the decision is visible in review."
        )
    if FORBIDDEN_TOOL in allow_set:
        failures.append(f"`{FORBIDDEN_TOOL}` is in permissions.allow. Remove it.")

    # Rule 5 — hosts named outside PLATFORMS (angle 18's harness prompt).
    if block is not None:
        outside = workflow[: block.start(1)] + workflow[block.end(1) :]
    else:
        outside = workflow
    if "WebFetch" in outside:
        for phrase, hosts in TEXT_HOST_HINTS.items():
            if phrase not in outside:
                failures.append(
                    f"The non-PLATFORMS WebFetch instruction no longer contains "
                    f"\"{phrase}\", so this checker can no longer tell which hosts it "
                    f"needs. Re-derive them and update TEXT_HOST_HINTS."
                )
                continue
            for host in hosts:
                require_domain(host, f"A finder fetches \"{phrase}\" at `{host}`, but")
        # Any host written as a URL in a non-platform instruction must also be allowed.
        # This is what makes rule 5 non-vacuous for a host nobody has thought of yet: a
        # new finder pointed at a new docs site fails here rather than mid-sweep.
        for host in sorted(set(HOST_IN_URL_RE.findall(outside))):
            if host in allowed_domains or fetch_all:
                continue
            failures.append(
                f"A non-PLATFORMS instruction names the URL host `{host}`, which is not "
                f"allowed. Add `WebFetch(domain:{host})` to {SETTINGS_REL}, or drop the URL."
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
        for f in dict.fromkeys(failures):
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("Audit-workflow permissions clean: every researched tool and host is pre-approved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
