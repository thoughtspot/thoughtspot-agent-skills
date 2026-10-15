#!/usr/bin/env python3
"""
generate_agentql_offline.py — bundle the ts-object-model-agentql-query skill's
canonical reference library into ONE offline document:

    agents/cli/ts-object-model-agentql-query/references/agentql-offline.md

Why this exists
---------------
The skill's knowledge is split across SKILL.md + ~11 reference files so each stays
small and single-purpose. That is right for authoring, but a reader who wants to
*review everything* — or an agent that wants the whole grounding as context without
making live `ts agentql` calls (offline mode, lower token spend, no cluster) — needs
it in one place.

This generator produces that one place. The sources stay canonical; the bundle is a
derived artifact, regenerated from them, so there is exactly one source of truth and
no hand-maintained duplication. A `--check` run (pre-commit + CI) fails if the bundle
has drifted from the sources, the same guard the other generated docs use.

Usage:
    python tools/validate/generate_agentql_offline.py
    python tools/validate/generate_agentql_offline.py --root /path/to/repo
    python tools/validate/generate_agentql_offline.py --check   # exit 1 if bundle is stale
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SKILL_DIR = Path("agents/cli/ts-object-model-agentql-query")
OUTPUT = SKILL_DIR / "references" / "agentql-offline.md"

# Ordered reading list. SKILL.md first (the flow and the course entry), then the
# references in the order the skill's own References table presents them. The output
# file itself is NEVER a source, so regeneration is idempotent.
SOURCES: list[tuple[str, str]] = [
    ("SKILL.md", "The skill — flow, the Learn AgentQL course entry, the six-section output block"),
    ("references/architecture.md", "The why: what executes, and the value vs raw SQL"),
    ("references/agentql-rules.md", "The dialect rules that make a statement valid"),
    ("references/udf-reference.md", "The AgentQL UDF catalogue (dates, ranking, statistics)"),
    ("references/patterns.md", "Complex query shapes"),
    ("references/limitations.md", "What AgentQL can't do, and the silent-wrong traps"),
    ("references/snowflake-sv-backing.md", "Rules for Snowflake Semantic View-backed Models"),
    ("references/learning-path.md", "The guided course (Modules 0–7)"),
    ("references/beyond-tokens.md", "Worked examples: where AgentQL earns its keep, and where it can't"),
    ("references/use-cases.md", "Building on the skill: tutorial, agent, test suites"),
    ("references/integration.md", "Calling AgentQL directly: auth, endpoints, response parsing"),
    ("references/open-items.md", "Verification status of the API behaviour this skill relies on"),
]


def _strip_frontmatter(text: str) -> str:
    """Remove a leading YAML frontmatter block (SKILL.md carries one)."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5:].lstrip("\n")
    return text


def _demote_headings(text: str) -> str:
    """Push every ATX heading down one level so the bundle has a single H1 and each
    source sits under its own H2. A line that is all `#` is left alone; fenced code
    blocks are never touched."""
    out = []
    in_fence = False
    fence = ""
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence, fence = True, marker
            elif stripped.startswith(fence):
                in_fence, fence = False, ""
            out.append(line)
            continue
        if not in_fence:
            m = re.match(r"^(#{1,5})(\s+\S)", line)
            if m:
                line = "#" + line
        out.append(line)
    return "\n".join(out)


def generate(repo_root: Path) -> str:
    skill = repo_root / SKILL_DIR
    parts: list[str] = []

    header = [
        "<!-- GENERATED FILE — do not edit by hand.",
        "     Built by tools/validate/generate_agentql_offline.py from the files listed below.",
        "     Edit those sources, then regenerate:",
        "         python3 tools/validate/generate_agentql_offline.py",
        "-->",
        "",
        "# AgentQL — offline reference bundle",
        "",
        "This is the complete reference library for the **ts-object-model-agentql-query** skill,",
        "assembled into one document so it can be read offline, reviewed end to end, or handed to",
        "an agent as grounding **without making live `ts agentql` calls**. It is generated from the",
        "canonical sources — edit those, not this file.",
        "",
        "**Live vs offline.** Running the skill or the course *live* makes real `generate-sql` /",
        "`fetch-data` calls against a cluster (fresh SQL and rows, at the cost of tool round-trips).",
        "Running *offline* means working from this bundle: the AgentQL, the explanations and the",
        "captured SQL are all here, so no cluster and far fewer tokens are needed. The trade-off is",
        "that result *numbers* are not live — where a lesson's totals roll with the sample `date`",
        "formula, offline mode teaches the SQL and the behaviour, not a fresh figure.",
        "",
        "## Contents",
        "",
    ]
    for rel, desc in SOURCES:
        header.append(f"- **{rel}** — {desc}")
    parts.append("\n".join(header))

    for rel, desc in SOURCES:
        path = skill / rel
        if not path.exists():
            raise FileNotFoundError(f"offline bundle source missing: {SKILL_DIR / rel}")
        raw = path.read_text(encoding="utf-8")
        if rel == "SKILL.md":
            raw = _strip_frontmatter(raw)
        body = _demote_headings(raw.strip())
        section = (
            f"\n\n---\n\n"
            f"## Source: `{rel}`\n\n"
            f"> {desc}\n\n"
            f"{body}\n"
        )
        parts.append(section)

    return "".join(parts).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Bundle the AgentQL skill references into one offline doc.")
    parser.add_argument("--root", default=".", help="Repo root")
    parser.add_argument("--check", action="store_true", help="Exit 1 if the bundle is stale.")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    out_path = repo_root / OUTPUT
    new_content = generate(repo_root)

    if args.check:
        if not out_path.exists():
            print(f"FAIL  {OUTPUT} does not exist. "
                  f"Run: python3 tools/validate/generate_agentql_offline.py")
            return 1
        if out_path.read_text(encoding="utf-8") != new_content:
            print(f"FAIL  {OUTPUT} is stale. "
                  f"Run: python3 tools/validate/generate_agentql_offline.py")
            return 1
        print(f"PASS  {OUTPUT} is up to date")
        return 0

    out_path.write_text(new_content, encoding="utf-8")
    print(f"Generated {OUTPUT} ({len(new_content.splitlines())} lines from {len(SOURCES)} sources)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
