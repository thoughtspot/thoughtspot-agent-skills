#!/usr/bin/env python3
"""
check_skill_flag_usage.py — fail if a SKILL.md documents a `ts <group> <command>
... --<flag>` invocation whose flag doesn't exist on the registered typer command.

2026-07-03 audit finding 11.1: from-snowflake-sv and from-databricks-mv both
instructed a `ts tml import --file` flag that didn't exist at the time (`import_tml`
was stdin-JSON-array only) — the documented command failed outright with an
unknown-option error. `--file`/`--dir` have since been added (ts-cli v0.27.0), which
makes the historical bug's specific case pass today, but nothing stopped a similar
drift from recurring on the next flag rename or removal. This validator introspects
the *actual* typer command tree and cross-checks every flag a SKILL.md tells an
executor to pass.

Design (deliberately conservative — this is the most heuristic-prone validator in the
harvest; false failures on doc phrasing would be worse than a missed doc bug):

  - Only lines that, after joining backslash line-continuations within a fenced code
    block, contain a segment starting with the bare word `ts ` (optionally after a
    `&&`, `;`, or `|` chain separator) are considered. Prose mentions of `ts` elsewhere
    are never touched.
  - The segment's first two whitespace-separated tokens are read as `<group>
    <command>`. If that pair isn't a real registered (group, command) — a typo'd
    command name, a placeholder like `ts {group} {command}`, or documented-but-not-yet-
    shipped syntax — the segment is skipped entirely. Verifying *command* names is a
    different, fuzzier problem (a doc can legitimately preview an unshipped command);
    this validator only cross-checks *flags* on commands it can unambiguously identify.
  - Only `--long-form` flags are extracted (never short forms like `-p`, which are far
    more likely to collide with an unrelated dash-prefixed token).
  - `--help` is always considered valid (every typer/click command accepts it even though
    it isn't a declared param).
  - `{placeholder}` values are never mistaken for flags — the extraction regex only
    matches tokens starting with `--`.

Requires: the ts-cli package importable (typer and ts_cli itself; click is NOT
imported directly — typer 0.26+ dropped it). This
validator inserts `<root>/tools/ts-cli` onto sys.path itself, so it's runnable
standalone with just `--root` — no external PYTHONPATH needed. If typer/click aren't
installed at all, it SKIPS (exit 0) rather than hard-failing an environment that
simply hasn't set up the ts-cli dev dependencies (mirrors check_module_health.py's
soft-skip on a missing `radon`).

Exit codes:
  0 — every extracted `--flag` on a recognized (group, command) exists (or SKIPped)
  1 — at least one documented flag doesn't exist on the real command

Run manually:
    python3 tools/validate/check_skill_flag_usage.py --root .
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCAN_ROOTS = ("agents/cli", "agents/claude")

# Populated by build_flag_map on import failure so the SKIP line can say WHICH
# module was missing — "typer not importable" and "ts_cli's own deps not
# installed" need different fixes and were indistinguishable before.
_IMPORT_ERROR = ""

# Global — accepted on every command even though it's not a declared param.
ALWAYS_VALID_FLAGS = {"--help"}

FENCE_RE = re.compile(r'^```')
# A `ts <group> <command>` invocation at the start of a chain segment.
TS_INVOCATION_RE = re.compile(r'^ts\s+(\S+)\s+(\S+)(.*)$')
FLAG_RE = re.compile(r'--[a-zA-Z][\w-]*')
CHAIN_SPLIT_RE = re.compile(r'&&|\|\||\||;')


def build_flag_map(root: Path) -> dict[tuple[str, str], set[str]] | None:
    """Introspect ts_cli.cli's typer command tree.

    Returns {(group, command): {"--flag", "-f", ...}} — both opts and secondary
    (`--no-x`) forms — or None if ts_cli/typer/click can't be imported (soft-skip
    signal to main()).
    """
    ts_cli_path = str(root / "tools" / "ts-cli")
    if ts_cli_path not in sys.path:
        sys.path.insert(0, ts_cli_path)
    global _IMPORT_ERROR
    try:
        import typer
        from ts_cli.cli import app as root_app
    except ImportError as exc:
        _IMPORT_ERROR = str(exc)
        return None

    # Duck-typed on purpose — NOT isinstance(click.Group)/isinstance(click.Option).
    # typer 0.26+ dropped its click dependency and vendored the command layer
    # (TyperGroup/TyperCommand/TyperOption), so `import click` fails on a fresh
    # resolution while older environments still have click-backed typer. Both expose
    # the same shape: groups have `.commands` (dict), commands have `.params`, and
    # option params have `param_type_name == "option"` with `.opts`/`.secondary_opts`.
    root_cmd = typer.main.get_command(root_app)
    flag_map: dict[tuple[str, str], set[str]] = {}
    for group_name, group_cmd in getattr(root_cmd, "commands", {}).items():
        subcommands = getattr(group_cmd, "commands", None)
        if not subcommands:
            continue
        for cmd_name, cmd in subcommands.items():
            flags: set[str] = set()
            for param in getattr(cmd, "params", []):
                if getattr(param, "param_type_name", "") == "option":
                    flags.update(getattr(param, "opts", []))
                    flags.update(getattr(param, "secondary_opts", []))
            flag_map[(group_name, cmd_name)] = flags
    return flag_map


def _iter_fenced_blocks(text: str) -> list[list[tuple[int, str]]]:
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    in_block = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if FENCE_RE.match(line.strip()):
            if in_block:
                blocks.append(current)
                current = []
                in_block = False
            else:
                in_block = True
            continue
        if in_block:
            current.append((lineno, line))
    return blocks


def _join_continuations(numbered_lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Join backslash-continued physical lines into one logical line, keyed by the
    line number the logical line started on."""
    logical: list[tuple[int, str]] = []
    start_lineno: int | None = None
    parts: list[str] = []
    for lineno, text in numbered_lines:
        if start_lineno is None:
            start_lineno = lineno
        stripped = text.rstrip()
        if stripped.endswith("\\"):
            parts.append(stripped[:-1].strip())
            continue
        parts.append(text.strip())
        logical.append((start_lineno, " ".join(p for p in parts if p)))
        start_lineno = None
        parts = []
    if parts:
        logical.append((start_lineno or 0, " ".join(p for p in parts if p)))
    return logical


def scan_text(
    text: str, flag_map: dict[tuple[str, str], set[str]]
) -> list[tuple[int, str, str, str]]:
    """Return (lineno, group, command, flag) for each documented flag that doesn't
    exist on the real (group, command). Empty list = clean."""
    findings: list[tuple[int, str, str, str]] = []
    for block in _iter_fenced_blocks(text):
        for lineno, logical in _join_continuations(block):
            for segment in CHAIN_SPLIT_RE.split(logical):
                seg = segment.strip()
                m = TS_INVOCATION_RE.match(seg)
                if not m:
                    continue
                group, command, tail = m.group(1), m.group(2), m.group(3)
                key = (group, command)
                if key not in flag_map:
                    continue  # unknown/typo'd/not-yet-shipped — out of scope here
                valid_flags = flag_map[key] | ALWAYS_VALID_FLAGS
                for flag in FLAG_RE.findall(tail):
                    if flag not in valid_flags:
                        findings.append((lineno, group, command, flag))
    return findings


def iter_skill_md_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for scan_root in SCAN_ROOTS:
        base = root / scan_root
        if base.is_dir():
            files.extend(sorted(base.rglob("SKILL.md")))
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    flag_map = build_flag_map(root)
    if flag_map is None:
        print("SKIP  flag cross-check: typer/ts_cli not importable "
              f"({_IMPORT_ERROR}) "
              "(`pip install -e tools/ts-cli`); this validator needs the CLI's own "
              "command tree to cross-check flags against.")
        return 0

    failures: list[str] = []
    scanned = 0
    for path in iter_skill_md_files(root):
        rel = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        scanned += 1
        for lineno, group, command, flag in scan_text(text, flag_map):
            failures.append(
                f"  ✗ {rel}:{lineno}: `ts {group} {command} ... {flag}` — {flag} is "
                f"not a registered option on `ts {group} {command}`"
            )

    if failures:
        print(f"\n{len(failures)} undocumented/incorrect flag reference(s) found:\n")
        print("\n".join(failures))
        print()
        print("Run `ts <group> <command> --help` to see the real option list, or")
        print("check tools/ts-cli/ts_cli/commands/<group>.py directly, then fix the")
        print("SKILL.md (PATCH bump + changelog entry).")
        return 1

    print(f"All ts CLI flag references resolve in {scanned} SKILL.md file(s) "
          f"({len(flag_map)} known command(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
