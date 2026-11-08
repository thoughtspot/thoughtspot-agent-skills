#!/usr/bin/env python3
"""
check_skill_flag_usage.py — fail if a SKILL.md documents a `ts <group> <command>
... --<flag>` invocation whose flag doesn't exist on the registered typer command,
or one that passes more positional arguments than the command declares.

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

Positional arguments (BL-545). `ts-convert-from-powerbi` and `-qlik` ran
`ts tml lint out/*.tml` and `ts tml import out/*.table.tml …`; neither command
declares a positional argument, so both exited 2 and neither converter had a lint
gate. Every flag on those lines was real, so the flag check above passed them. The
second check walks the same segments with the command's own signature:

  - The segment is tokenised shell-style (`shlex`, quotes honoured, `# comments`
    dropped). A segment containing `$(` or a backtick, or one `shlex` cannot parse,
    is skipped: its tokens are not what the shell will see.
  - A known option consumes its value token(s) unless it is a flag (`is_flag`/
    `count`) or written `--opt=value`. The brackets of an optional group
    (`[--model-fqn <guid>]`) or a choice (`{--x|--no-x}`, which the chain split
    has already cut at the `|`) are stripped first.
  - An option the command does NOT declare stops the walk: its arity is unknown, so
    the next token may be its value. The flag check already reports it.
  - `…`/`...`, `&`, and a redirection (`>`, `2>&1`, `<`, but not a `<placeholder>`)
    end the argument list. `--` makes everything after it positional.
  - Every other token is positional. The command's limit is the sum of its declared
    arguments' `nargs`; a variadic argument (`nargs=-1`, e.g. `ts tml export GUIDS…`)
    has none. More positionals than the limit is a finding.

Requires: the ts-cli package importable (typer and ts_cli itself; click is NOT
imported directly — typer 0.26+ dropped it). This
validator inserts `<root>/tools/ts-cli` onto sys.path itself, so it's runnable
standalone with just `--root` — no external PYTHONPATH needed. If typer/click aren't
installed at all, it SKIPS (exit 0) rather than hard-failing an environment that
simply hasn't set up the ts-cli dev dependencies (mirrors check_module_health.py's
soft-skip on a missing `radon`).

Exit codes:
  0 — every extracted `--flag` on a recognized (group, command) exists, and no
      recognized invocation passes surplus positional arguments (or SKIPped)
  1 — at least one documented flag doesn't exist on the real command, or an
      invocation passes positional arguments the command does not declare

Run manually:
    python3 tools/validate/check_skill_flag_usage.py --root .
"""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from _dirs import ALL_RUNTIME_PATHS

SCAN_ROOTS = ALL_RUNTIME_PATHS

# Populated by build_flag_map on import failure so the SKIP line can say WHICH
# module was missing — "typer not importable" and "ts_cli's own deps not
# installed" need different fixes and were indistinguishable before.
_IMPORT_ERROR = ""

# Global — accepted on every command even though it's not a declared param.
ALWAYS_VALID_FLAGS = {"--help"}

FENCE_RE = re.compile(r'^```')
# A `ts <group> <command>` invocation at the start of a chain segment.
# Capture every token after `ts` and let the matcher walk the command tree, rather
# than assuming a fixed `ts <group> <command>` depth. `ts security column-rules get` is
# three levels deep -- see `_walk_commands`.
TS_INVOCATION_RE = re.compile(r'^ts\s+(.*)$')
FLAG_RE = re.compile(r'--[a-zA-Z][\w-]*')
CHAIN_SPLIT_RE = re.compile(r'&&|\|\||\||;')

# Deepest command nesting to consider when matching a documented invocation
# against the real tree. `ts security column-rules get` is 3; the bound just
# stops a long argument list being probed token by token.
_MAX_DEPTH = 4


@dataclass(frozen=True)
class CommandSpec:
    """What a leaf command accepts, read from its typer signature.

    `flags` is every option spelling (opts and secondary `--no-x` forms);
    `value_opts` maps each spelling that takes a value to how many tokens it
    consumes; `max_positional` is the most positional arguments it takes, or None
    when one argument is variadic."""
    flags: frozenset
    value_opts: frozenset
    max_positional: int | None
    value_nargs: tuple = ()  # ((spelling, nargs), ...) only where nargs > 1

    def nargs_of(self, opt: str) -> int:
        return dict(self.value_nargs).get(opt, 1)


def build_flag_map(root: Path) -> dict[tuple[str, str], set[str]] | None:
    """Introspect ts_cli.cli's typer command tree.

    Returns {(group, command): {"--flag", "-f", ...}} — both opts and secondary
    (`--no-x`) forms — or None if ts_cli/typer/click can't be imported (soft-skip
    signal to main()).
    """
    command_map = build_command_map(root)
    if command_map is None:
        return None
    return {key: set(spec.flags) for key, spec in command_map.items()}


def build_command_map(root: Path) -> dict[tuple[str, ...], CommandSpec] | None:
    """Introspect ts_cli.cli's typer command tree into a CommandSpec per leaf
    command, keyed by its full path from `ts`. None if ts_cli/typer can't be
    imported (soft-skip signal to main())."""
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
    command_map: dict[tuple[str, ...], CommandSpec] = {}
    _walk_commands(root_cmd, (), command_map)
    return command_map


def _walk_commands(cmd, path: tuple[str, ...],
                   command_map: dict[tuple[str, ...], CommandSpec]) -> None:
    """Record every LEAF command's signature, keyed by its full path from `ts`.

    Recursive rather than two levels deep, because command groups nest arbitrarily:
    `ts security column-rules get` is three levels, and a flat (group, command) walk
    resolved it to the `column-rules` GROUP -- whose only option is `--help` -- so every
    real flag on every subcommand read as unregistered. That shipped undetected in
    PR #347 because no SKILL.md referenced those commands until ts-security-columns.

    Groups are not recorded themselves: a bare `ts security column-rules --help` needs no
    cross-check, and recording it would let a group's `--help` mask a subcommand typo.
    """
    subcommands = getattr(cmd, "commands", None)
    if subcommands:
        for name, sub in subcommands.items():
            _walk_commands(sub, path + (name,), command_map)
        return
    if not path:
        return
    flags: set[str] = set()
    value_opts: set[str] = set()
    value_nargs: list[tuple[str, int]] = []
    max_positional: int | None = 0
    for param in getattr(cmd, "params", []):
        kind = getattr(param, "param_type_name", "")
        if kind == "option":
            opts = list(getattr(param, "opts", []))
            flags.update(opts)
            flags.update(getattr(param, "secondary_opts", []))
            if not (getattr(param, "is_flag", False) or getattr(param, "count", False)):
                value_opts.update(opts)
                nargs = getattr(param, "nargs", 1) or 1
                if nargs > 1:
                    value_nargs.extend((o, nargs) for o in opts)
        elif kind == "argument":
            nargs = getattr(param, "nargs", 1)
            if nargs is None or nargs < 0 or max_positional is None:
                max_positional = None
            else:
                max_positional += nargs
    command_map[path] = CommandSpec(frozenset(flags), frozenset(value_opts),
                                    max_positional, tuple(value_nargs))


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


def _iter_invocations(text: str, known):
    """Yield (lineno, key, tail) for each `ts <command path> <tail>` segment in a
    fenced block whose command path is in `known`. Shared by both checks so they
    can never disagree about which lines are invocations."""
    for block in _iter_fenced_blocks(text):
        for lineno, logical in _join_continuations(block):
            for segment in CHAIN_SPLIT_RE.split(logical):
                seg = segment.strip()
                m = TS_INVOCATION_RE.match(seg)
                if not m:
                    continue
                tokens = m.group(1).split()
                # Longest matching command path wins, so a three-level command is not
                # mistaken for its two-level parent group.
                key: tuple[str, ...] | None = None
                for depth in range(min(len(tokens), _MAX_DEPTH), 0, -1):
                    candidate = tuple(tokens[:depth])
                    if candidate in known:
                        key = candidate
                        break
                if key is None:
                    continue  # unknown/typo'd/not-yet-shipped — out of scope here
                yield lineno, key, " ".join(tokens[len(key):])


def scan_text(
    text: str, flag_map: dict[tuple[str, str], set[str]]
) -> list[tuple[int, str, str, str]]:
    """Return (lineno, group, command, flag) for each documented flag that doesn't
    exist on the real (group, command). Empty list = clean."""
    findings: list[tuple[int, str, str, str]] = []
    for lineno, key, tail in _iter_invocations(text, flag_map):
        valid_flags = flag_map[key] | ALWAYS_VALID_FLAGS
        for flag in FLAG_RE.findall(tail):
            if flag not in valid_flags:
                findings.append((lineno, " ".join(key[:-1]), key[-1], flag))
    return findings


# Tokens that end the argument list: an elided remainder, a background `&`, or a
# redirection. A `<placeholder>` is an argument, so `<` only counts when the token
# does not also end in `>`.
_ELLIPSES = {"...", "…"}
_REDIRECT_RE = re.compile(r"^(?:\d?>>?|&>|\d?>&\d)|^<(?!.*>$)")


def _positionals(tail: str, spec: CommandSpec) -> list[str] | None:
    """The positional tokens in an invocation's tail, or None when the tail cannot
    be read reliably (see the module docstring for each rule)."""
    if "$(" in tail or "`" in tail:
        return None
    try:
        tokens = shlex.split(tail, comments=True)
    except ValueError:
        return None
    positionals: list[str] = []
    options_ended = False
    i = 0
    while i < len(tokens):
        raw = tokens[i]
        tok = raw.lstrip("[{").rstrip("]}") if not options_ended else raw
        i += 1
        if not tok:
            continue
        if not options_ended:
            if tok in _ELLIPSES or tok == "&" or _REDIRECT_RE.match(tok):
                break
            if tok == "--":
                options_ended = True
                continue
            if tok.startswith("-") and tok != "-":
                name = tok.split("=", 1)[0]
                if name in ALWAYS_VALID_FLAGS:
                    continue
                if name not in spec.flags:
                    return None  # undeclared option, arity unknown: flag check reports it
                if name in spec.value_opts and "=" not in tok:
                    i += spec.nargs_of(name)
                continue
        positionals.append(raw)
    return positionals


def scan_positionals(
    text: str, command_map: dict[tuple[str, ...], CommandSpec]
) -> list[tuple[int, str, str, list[str], int]]:
    """Return (lineno, group, command, surplus_tokens, max_positional) for each
    invocation passing more positional arguments than the command declares.
    `surplus_tokens` is every positional token on the line. Empty list = clean."""
    findings: list[tuple[int, str, str, list[str], int]] = []
    for lineno, key, tail in _iter_invocations(text, command_map):
        spec = command_map[key]
        if spec.max_positional is None:
            continue
        positionals = _positionals(tail, spec)
        if positionals is not None and len(positionals) > spec.max_positional:
            findings.append((lineno, " ".join(key[:-1]), key[-1], positionals,
                             spec.max_positional))
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

    command_map = build_command_map(root)
    if command_map is None:
        print("SKIP  flag cross-check: typer/ts_cli not importable "
              f"({_IMPORT_ERROR}) "
              "(`pip install -e tools/ts-cli`); this validator needs the CLI's own "
              "command tree to cross-check flags against.")
        return 0

    flag_map = {key: set(spec.flags) for key, spec in command_map.items()}
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
        for lineno, group, command, extra, limit in scan_positionals(text, command_map):
            takes = "no positional arguments" if limit == 0 else f"at most {limit}"
            failures.append(
                f"  ✗ {rel}:{lineno}: `ts {group} {command}` is given "
                f"{len(extra)} positional argument(s) ({' '.join(extra)}) but takes "
                f"{takes} — pass them through the command's options"
            )

    if failures:
        print(f"\n{len(failures)} undocumented/incorrect flag or argument reference(s) found:\n")
        print("\n".join(failures))
        print()
        print("Run `ts <group> <command> --help` to see the real option list, or")
        print("check tools/ts-cli/ts_cli/commands/<group>.py directly, then fix the")
        print("SKILL.md (PATCH bump + changelog entry).")
        return 1

    print(f"All ts CLI flag and positional-argument references resolve in {scanned} "
          f"SKILL.md file(s) ({len(command_map)} known command(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
