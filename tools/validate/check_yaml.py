#!/usr/bin/env python3
"""
check_yaml.py — validate all fenced YAML code blocks in .md files parse without error.

Extracts ```yaml ... ``` blocks from schema, mapping, and worked-example files
and attempts yaml.safe_load() on each. Reports file, block start line, and parse error.

Usage:
    python tools/validate/check_yaml.py
    python tools/validate/check_yaml.py --root /path/to/repo
    python tools/validate/check_yaml.py --path agents/shared/schemas/thoughtspot-table-tml.md
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML")
    sys.exit(1)

FENCE_START = re.compile(r'^```ya?ml\s*$', re.IGNORECASE)
FENCE_END = re.compile(r'^```\s*$')


def extract_yaml_blocks(file_path: Path) -> list[tuple[int, str]]:
    """Extract (start_line, block_content) for each ```yaml block in the file."""
    blocks = []
    lines = file_path.read_text(encoding="utf-8").splitlines()
    in_block = False
    block_start = 0
    block_lines: list[str] = []

    for i, line in enumerate(lines, 1):
        if not in_block:
            if FENCE_START.match(line):
                in_block = True
                block_start = i + 1
                block_lines = []
        else:
            if FENCE_END.match(line):
                in_block = False
                blocks.append((block_start, "\n".join(block_lines)))
                block_lines = []
            else:
                block_lines.append(line)

    return blocks


def check_file(file_path: Path, repo_root: Path) -> list[tuple[int, str]]:
    """Return list of (line_num, error_message) for blocks that fail yaml parsing."""
    errors = []
    for start_line, content in extract_yaml_blocks(file_path):
        try:
            # Use safe_load_all to handle multi-document YAML (e.g., frontmatter examples
            # that start with --- separators). Consume the generator to trigger any parse errors.
            list(yaml.safe_load_all(content))
        except yaml.YAMLError as e:
            errors.append((start_line, str(e).splitlines()[0]))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate YAML code blocks in .md files.")
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    parser.add_argument("--path", help="Check a single file instead of scanning the repo")
    parser.add_argument("--staged", action="store_true",
                        help="Only check .md files staged in git (for use in pre-commit hook)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    skip_dirs = {".git", "__pycache__", ".venv", "venv", "dist", "build", "node_modules"}

    if args.path:
        target = Path(args.path)
        if not target.is_absolute():
            target = repo_root / target
        md_files = [target]
    elif args.staged:
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, cwd=repo_root
        )
        staged = [repo_root / f for f in result.stdout.splitlines() if f.endswith(".md")]
        md_files = [f for f in staged if f.exists()]
    else:
        # Full repo scan — focus on reference/schema/mapping files
        md_files = sorted(
            repo_root.glob("agents/shared/**/*.md")
        ) + sorted(
            repo_root.glob("agents/claude/**/*.md")
        ) + sorted(
            repo_root.glob("agents/coco/**/*.md")
        )
        md_files = [f for f in md_files if not any(p in f.parts for p in skip_dirs)]

    total_errors = 0
    files_checked = 0
    files_with_blocks = 0

    for md_file in md_files:
        blocks = extract_yaml_blocks(md_file)
        if not blocks:
            continue
        files_with_blocks += 1
        files_checked += 1
        errors = check_file(md_file, repo_root)
        rel = md_file.relative_to(repo_root)
        if errors:
            for line_num, msg in errors:
                print(f"FAIL  {rel}:{line_num}  →  {msg}")
                total_errors += 1
        else:
            print(f"PASS  {rel}  ({len(blocks)} block(s))")

    print()
    print(f"Checked {files_with_blocks} file(s) with YAML blocks.")
    if total_errors:
        print(f"{total_errors} YAML parse error(s) found.")
        return 1
    else:
        print("All YAML blocks parse cleanly.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
