#!/usr/bin/env python3
"""
generate_quality_gates.py — auto-generate docs/quality-gates.md from the repo's
actual quality infrastructure.

Sources of truth (never manually maintained — always scraped):
  1. scripts/pre-commit.sh — what runs locally, trigger conditions, inline comments
  2. .github/workflows/validate.yml — what runs in CI
  3. Validator docstrings — what each check does
  4. git log — when each validator was last modified / last had a meaningful change

The generated doc answers: what gates exist, what they check, when they run,
why they were added, and when they last changed. The audit uses it to review
whether gates are still the right gates.

Usage:
    python tools/validate/generate_quality_gates.py              # generate
    python tools/validate/generate_quality_gates.py --check       # exit 1 if stale
    python tools/validate/generate_quality_gates.py --root /path
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Pre-commit.sh parser
# ---------------------------------------------------------------------------

def _parse_precommit(path: Path) -> list[dict]:
    """Extract check entries from pre-commit.sh.

    Each entry has: label, command, trigger (file pattern), comment (lines
    above the block), validator (the .py file), mode (gate or soft).
    """
    text = path.read_text(encoding="utf-8")
    entries: list[dict] = []

    # Match run_check "label" "command" lines
    check_re = re.compile(
        r'run_check\s+"([^"]+)"\s+"([^"]+)"'
    )
    # Match run_pytest "label" paths
    pytest_re = re.compile(
        r'run_pytest\s+"([^"]+)"\s+(.*)'
    )

    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()

        m = check_re.search(stripped)
        if not m:
            m_pytest = pytest_re.search(stripped)
            if m_pytest:
                label = m_pytest.group(1)
                paths = m_pytest.group(2).strip()
                comment = _collect_comment(lines, i)
                trigger = _find_trigger(lines, i)
                entries.append({
                    "label": label,
                    "command": f"pytest {paths}",
                    "validator": None,
                    "trigger": trigger,
                    "comment": comment,
                    "mode": "gate",
                    "source": "pre-commit",
                })
            continue

        label = m.group(1)
        command = m.group(2)
        comment = _collect_comment(lines, i)
        trigger = _find_trigger(lines, i)

        # Extract validator filename
        validator = None
        vm = re.search(r'tools/validate/(\S+\.py)', command)
        if vm:
            validator = vm.group(1)

        mode = "soft" if "--warn" in command or "|| true" in stripped else "gate"

        entries.append({
            "label": label,
            "command": command,
            "validator": validator,
            "trigger": trigger,
            "comment": comment,
            "mode": mode,
            "source": "pre-commit",
        })

    # Also pick up non-run_check validators (soft nudges that run directly)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('"$PYTHON_BIN"') and "run_check" not in stripped:
            vm = re.search(r'tools/validate/(\S+\.py)', stripped)
            if vm and vm.group(1) not in {e["validator"] for e in entries}:
                comment = _collect_comment(lines, i)
                trigger = _find_trigger(lines, i)
                entries.append({
                    "label": vm.group(1).replace("check_", "").replace(".py", "").replace("_", " "),
                    "command": stripped.strip('"'),
                    "validator": vm.group(1),
                    "trigger": trigger,
                    "comment": comment,
                    "mode": "soft",
                    "source": "pre-commit",
                })

    return entries


def _collect_comment(lines: list[str], check_line: int) -> str:
    """Collect the comment block above a check line."""
    comments = []
    j = check_line - 1
    while j >= 0:
        stripped = lines[j].strip()
        if stripped.startswith("#"):
            comments.insert(0, stripped.lstrip("# ").strip())
            j -= 1
        elif stripped == "":
            j -= 1
        elif stripped.startswith("if ") or stripped.startswith("fi"):
            j -= 1
        else:
            break
    return " ".join(comments).strip()


def _find_trigger(lines: list[str], check_line: int) -> str:
    """Find the if-condition (trigger pattern) for a check.

    Walks upward, skipping comments, blanks, sibling checks, and closed
    if-fi blocks (nesting-aware). Returns "always" when no enclosing if is found.
    """
    j = check_line - 1
    depth = 0
    while j >= 0:
        stripped = lines[j].strip()

        if stripped == "fi":
            depth += 1
            j -= 1
            continue

        if stripped.startswith("if "):
            if depth > 0:
                depth -= 1
                j -= 1
                continue
            m = re.search(r"grep -qE?\s+'([^']+)'", stripped)
            if m:
                return m.group(1)
            return stripped

        if depth > 0:
            j -= 1
            continue

        if stripped in ("", "then") or stripped.startswith("#"):
            j -= 1
            continue
        if stripped.startswith("run_check ") or stripped.startswith("run_pytest "):
            j -= 1
            continue
        if stripped.startswith('"$PYTHON_BIN"'):
            j -= 1
            continue

        break
    return "always"


# ---------------------------------------------------------------------------
# CI workflow parser
# ---------------------------------------------------------------------------

def _parse_ci(path: Path) -> list[dict]:
    """Extract validators from the CI workflow YAML."""
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    entries = []

    for line in text.splitlines():
        stripped = line.strip()

        # python3 tools/validate/check_*.py lines
        if stripped.startswith("python3 tools/validate/"):
            vm = re.search(r'tools/validate/(\S+\.py)', stripped)
            if not vm:
                continue

            validator = vm.group(1)
            comment = ""
            cm = re.search(r'#\s*(.+)', stripped)
            if cm:
                comment = cm.group(1).strip()

            entries.append({
                "validator": validator,
                "comment": comment,
            })
            continue

        # pytest invocations
        if stripped.startswith("pytest "):
            entries.append({
                "validator": "_pytest_ci",
                "comment": "Unit and validator tests",
            })
            continue

        # pip-audit (standalone or as YAML run: value)
        if stripped in ("pip-audit", "run: pip-audit"):
            entries.append({
                "validator": "_pip_audit",
                "comment": "Dependency vulnerability scan against PyPI/OSV advisory database",
            })

    return entries


# ---------------------------------------------------------------------------
# Docstring extractor
# ---------------------------------------------------------------------------

def _extract_docstring(path: Path) -> str:
    """Extract the first paragraph of a Python module's docstring."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""

    m = re.search(r'"""(.*?)"""', text, re.DOTALL)
    if not m:
        m = re.search(r"'''(.*?)'''", text, re.DOTALL)
    if not m:
        return ""

    doc = m.group(1).strip()
    # First paragraph only
    paragraphs = re.split(r'\n\s*\n', doc)
    first = paragraphs[0] if paragraphs else doc
    # Collapse to single line
    return " ".join(first.split())


# ---------------------------------------------------------------------------
# Git history
# ---------------------------------------------------------------------------

def _last_modified(path: Path, repo_root: Path) -> str:
    """Get the date a file was last modified (git log)."""
    rel = str(path.relative_to(repo_root))
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%as", "--", rel],
            capture_output=True, text=True, timeout=5,
            cwd=str(repo_root),
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate_catalog(repo_root: Path) -> str:
    """Generate the quality gates catalog."""
    precommit_path = repo_root / "scripts" / "pre-commit.sh"
    ci_path = repo_root / ".github" / "workflows" / "validate.yml"
    validate_dir = repo_root / "tools" / "validate"

    pc_entries = _parse_precommit(precommit_path)
    ci_entries = _parse_ci(ci_path)

    # Build a set of all validators
    all_validators: dict[str, dict] = {}

    for entry in pc_entries:
        v = entry.get("validator")
        if v:
            all_validators.setdefault(v, {
                "label": entry["label"],
                "pre_commit": True,
                "ci": False,
                "trigger": entry["trigger"],
                "comment": entry["comment"],
                "mode": entry["mode"],
            })
        else:
            key = entry["label"]
            all_validators.setdefault(key, {
                "label": entry["label"],
                "pre_commit": True,
                "ci": False,
                "trigger": entry["trigger"],
                "comment": entry["comment"],
                "mode": entry["mode"],
            })

    ci_synthetic_labels = {
        "_pytest_ci": "unit tests (CI)",
        "_pip_audit": "pip-audit",
    }

    for entry in ci_entries:
        v = entry["validator"]
        if v.startswith("_"):
            label = ci_synthetic_labels.get(v, v.lstrip("_"))
            all_validators[v] = {
                "label": label,
                "pre_commit": v == "_pytest_ci",
                "ci": True,
                "trigger": "every PR",
                "comment": entry.get("comment", ""),
                "mode": "gate",
            }
            continue
        if v in all_validators:
            all_validators[v]["ci"] = True
        else:
            all_validators[v] = {
                "label": v.replace("check_", "").replace(".py", "").replace("_", " "),
                "pre_commit": False,
                "ci": True,
                "trigger": "every PR",
                "comment": entry.get("comment", ""),
                "mode": "gate",
            }

    # Enrich with docstrings and git dates
    for v, info in all_validators.items():
        vpath = validate_dir / v if v.endswith(".py") else None
        if vpath and vpath.exists():
            info["docstring"] = _extract_docstring(vpath)
            info["last_modified"] = _last_modified(vpath, repo_root)
        else:
            info["docstring"] = ""
            info["last_modified"] = ""

    # Build markdown
    lines = [
        "# Quality Gates Catalog",
        "",
        "Auto-generated by `tools/validate/generate_quality_gates.py`.",
        "Re-run to refresh. Do not edit manually.",
        "",
        "## How to use this catalog",
        "",
        "- **New contributors:** read the Description and Why columns to understand",
        "  what each gate catches and the incident that motivated it.",
        "- **Audit (angle 7):** review the Last Modified column to find gates that",
        "  haven't changed in 6+ months — are they still catching real issues, or",
        "  checking something that no longer happens?",
        "- **Adding a gate:** add the validator, wire it into `pre-commit.sh` and/or",
        "  `validate.yml`, then re-run this generator.",
        "",
        f"**{len(all_validators)} gates** across pre-commit and CI.",
        "",
    ]

    # Summary table
    pc_count = sum(1 for v in all_validators.values() if v["pre_commit"])
    ci_count = sum(1 for v in all_validators.values() if v["ci"])
    both = sum(1 for v in all_validators.values() if v["pre_commit"] and v["ci"])
    pc_only = pc_count - both
    ci_only = ci_count - both

    lines.extend([
        f"| Runs in | Count |",
        f"|---|---|",
        f"| Pre-commit + CI | {both} |",
        f"| Pre-commit only | {pc_only} |",
        f"| CI only | {ci_only} |",
        "",
        "## Gates",
        "",
        "| # | Gate | Description | When it runs | Why it exists | Mode | Last modified |",
        "|---|---|---|---|---|---|---|",
    ])

    for i, (v, info) in enumerate(sorted(all_validators.items()), 1):
        label = info["label"]
        desc = info["docstring"][:120] + "..." if len(info.get("docstring", "")) > 120 else info.get("docstring", "")
        desc = desc.replace("|", "\\|").replace("\n", " ")

        trigger = info["trigger"]
        if trigger == "always":
            when = "Every commit"
        elif "\\." in trigger or "\\(" in trigger:
            when = _humanise_trigger(trigger)
        else:
            when = _humanise_trigger(trigger)

        where = []
        if info["pre_commit"]:
            where.append("pre-commit")
        if info["ci"]:
            where.append("CI")
        when_full = f"{when} ({', '.join(where)})"

        why = info["comment"][:150] if info.get("comment") else ""
        why = why.replace("|", "\\|")

        mode = info["mode"]
        last_mod = info.get("last_modified", "")

        lines.append(
            f"| {i} | `{label}` | {desc} | {when_full} | {why} | {mode} | {last_mod} |"
        )

    lines.append("")

    # Enforcement model section (audit finding 7.3)
    lines.extend([
        "## Enforcement model",
        "",
        "Gates run in two environments with deliberately different strictness:",
        "",
        "| Environment | Behaviour | Rationale |",
        "|---|---|---|",
        "| **Pre-commit (local)** | Hard gate — blocks the commit on failure | "
        "The author is present and can fix immediately; fast feedback prevents bad commits from reaching the remote |",
        "| **CI (`validate.yml`)** | Runs the same checks but **cannot block a merge on its own** — "
        "branch protection requires the `validate` status check to pass, yet `--admin` merges bypass it | "
        "CI is the safety net, not the primary gate; the tradeoff avoids blocking contributors who lack local tooling |",
        "",
        "This means enforcement is **inverted from most repos** (which gate hard in CI "
        "and soft locally). The accepted tradeoff: a contributor who commits with "
        "`--no-verify` can push code that fails CI, but cannot merge to `main` without "
        "`--admin` — and `--admin` merges are limited to maintainers who are expected "
        "to have run pre-commit locally.",
        "",
    ])

    # Audit review section
    lines.extend([
        "## Audit review checklist (angle 7)",
        "",
        "When reviewing gates during an audit, ask:",
        "",
        "1. **Still catching real issues?** Check git log for the validator — if it",
        "   hasn't changed in 6+ months and the comment references a specific incident,",
        "   is that class of bug still possible?",
        "2. **Bypassed without consequence?** Are there `--no-verify` commits that",
        "   should have been caught? (`git log --all --grep='no-verify'`)",
        "3. **Gaps?** Did any recent bug slip past all gates? Should a new gate exist?",
        "4. **Redundant?** Do two gates check overlapping things? Can one subsume the other?",
        "5. **Right mode?** Should a soft nudge become a hard gate, or vice versa?",
        "",
        "Route findings to: a validator PR (preferred) or a dated `BL-NNN` backlog item.",
        "",
    ])

    # Stale docs section
    lines.extend([
        "## Stale docs check",
        "",
        "Design docs, proposals, and audit reports in `docs/` should carry a status header:",
        "",
        "```markdown",
        "<!-- status: IMPLEMENTED (PR #180) -->",
        "<!-- status: SUPERSEDED by docs/design-v2.md -->",
        "<!-- status: ACTIVE -->",
        "```",
        "",
        "The audit flags docs without a status or untouched for 6+ months.",
        "",
    ])

    return "\n".join(lines)


def _humanise_trigger(pattern: str) -> str:
    """Convert a grep pattern to a human-readable trigger description."""
    if not pattern or pattern == "always":
        return "Every commit"

    p = pattern

    if "open-items" in p:
        return "Open-items files staged"
    if "ts-convert-" in p:
        return "Convert skill or validator staged"
    if "SKILL" in p and "smoke-tests" in p:
        return "Skill or smoke-test files staged"
    if "SKILL" in p and "skill-naming" in p:
        return "Skill files or naming rule staged"
    if "SKILL" in p and "runtime-coverage" in p:
        return "Skill files or coverage rule staged"
    if "SKILL" in p and "PARITY" in p:
        return "Skill files or PARITY.md staged"
    if "SKILL" in p and "commands/" in p:
        return "Skill docs or ts-cli commands staged"
    if "SKILL" in p:
        return "Skill files staged"
    if "coco-snowsight" in p and "SYNC-DEBT" in p:
        return "CoCo mirrors or SYNC-DEBT.md staged"
    if "ts-cli/ts_cli" in p and "\\.py" in p:
        return "ts-cli Python source staged"
    if "shared/(mappings|schemas)" in p:
        return "Shared mappings/schemas staged"
    if "pre-commit" in p or ("validate/" in p and "quality-gates" in p):
        return "Validators or pre-commit infrastructure staged"
    if "\\.py" in p and "\\.md" not in p:
        return "Python files staged"
    if "agents/" in p and "\\.md" in p:
        return "Agent docs staged"
    if "references/" in p:
        return "Reference files staged"
    if "\\.md" in p:
        return "Markdown files staged"

    readable = pattern.replace("\\.", ".").replace("\\(", "(").replace("\\)", ")")
    return f"Pattern: `{readable[:60]}`"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate quality gates catalog."
    )
    parser.add_argument("--root", default=".", help="Repo root")
    parser.add_argument("--check", action="store_true",
                        help="Exit 1 if the catalog is stale.")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    out_path = repo_root / "docs" / "quality-gates.md"
    new_content = generate_catalog(repo_root)

    if args.check:
        if not out_path.exists():
            print("FAIL  docs/quality-gates.md does not exist. "
                  "Run: python3 tools/validate/generate_quality_gates.py")
            return 1
        existing = out_path.read_text(encoding="utf-8")
        if existing != new_content:
            print("FAIL  docs/quality-gates.md is stale. "
                  "Run: python3 tools/validate/generate_quality_gates.py")
            return 1
        print("PASS  docs/quality-gates.md is up to date")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(new_content, encoding="utf-8")
    print(f"Generated {out_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
