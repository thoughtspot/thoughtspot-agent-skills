"""check_harness_routing.py — delegated agents keep to the routing requirements.

History. This validator originally enforced sync between agent frontmatter and a
hand-maintained "Current assignments" table in `.claude/rules/model-routing.md`
(assertions: agent-named-in-table, declared-tier-matches-table). Those were dropped
on 2026-08-27: the table was a second hand-maintained copy of facts the frontmatter
already carries, plus a gate whose main job was keeping the copies equal — double
bookkeeping, and a merge-conflict funnel when concurrent sessions each edit an
agent. The reviewable justification now lives beside the pin itself.

What this asserts, per agent under `.claude/agents/`:

1. **No Haiku pin.** `model-routing.md` records that the subagent-driven-development
   policy rejects Haiku for delegated work (the governing policy in
   `~/.claude/CLAUDE.md` records why). This exact regression shipped once and sat
   unnoticed until a manual sweep (2026-08-26 audit, finding 18.3/18.4). Inline
   frontmatter comments are stripped before the comparison, so `model: haiku  # x`
   cannot slip past (a fixture-verified evasion in this validator's first rewrite,
   caught by refute review 2026-08-28).
2. **A `model:` pin carries its reason.** The rule: a pin "needs a reason the effort
   dial cannot serve". Mechanically: a frontmatter `model:` value other than
   `inherit` requires a `# reason:` comment inside the same frontmatter block — its
   own line or inline on the pin — so the justification is reviewable where the pin
   is and travels with it. Deliberate looseness, admitted: the comment may sit
   anywhere in the frontmatter and is not checked for being ABOUT the pin; at the
   current agent count that is a review job, not a parse job.

Deliberately NOT asserted: `effort:` values. The harness schema-validates agent
frontmatter itself, and with the assignments table gone there is no second copy for
an effort value to disagree with.

The rule file itself must exist — the requirements these checks enforce are stated
there, and a validator pointing at a deleted rule is enforcing prose nobody can read.

Exit codes:
  0 — every agent conforms
  1 — a forbidden or unjustified pin, or the rule file is missing

Run manually:
    python3 tools/validate/check_harness_routing.py --root .
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

AGENTS_DIR = ".claude/agents"
ROUTING_RULE = ".claude/rules/model-routing.md"

# The rule's own words: a pin is the exception, and Haiku is out for delegated work.
FORBIDDEN_MODEL_PINS = {"haiku"}

_FM_KEY_RE = re.compile(r"^(?P<key>[a-zA-Z_]+)\s*:\s*(?P<value>.*?)\s*$")
_REASON_RE = re.compile(r"#\s*reason\s*:", re.IGNORECASE)  # own line or inline


def frontmatter_lines(path: Path) -> list[str]:
    """Raw lines of the `---`-delimited frontmatter block (exclusive of fences).

    Deliberately not a YAML parse: these files carry `#` comment lines inside the
    frontmatter (the `tools:` grants from 18.6, and now `# reason:` beside pins),
    and both the keys and the comments matter here.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    block: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        block.append(line)
    return block


def parse_frontmatter(block: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in block:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _FM_KEY_RE.match(line)
        if m:
            # YAML treats ` #` as a comment; strip it or `model: haiku  # x`
            # evades the forbidden-pin comparison (refute review, 2026-08-28).
            out[m.group("key")] = m.group("value").split(" #", 1)[0].strip()
    return out


def check(root: Path) -> list[str]:
    failures: list[str] = []
    agents_dir = root / AGENTS_DIR
    rule_path = root / ROUTING_RULE

    if not agents_dir.is_dir():
        return failures                      # no agents to check
    if not rule_path.is_file():
        return [f"{ROUTING_RULE} is missing — it states the requirements this check enforces."]

    for agent_file in sorted(agents_dir.glob("*.md")):
        name = agent_file.stem
        block = frontmatter_lines(agent_file)
        fm = parse_frontmatter(block)
        model = (fm.get("model") or "").strip().strip("\"'").lower()
        has_reason = any(_REASON_RE.search(ln) for ln in block)

        if model in FORBIDDEN_MODEL_PINS:
            failures.append(
                f"{name}: `model: {model}` is forbidden for a delegated agent. "
                f"{ROUTING_RULE} records that the subagent-driven-development policy "
                f"rejects Haiku for delegated work (~/.claude/CLAUDE.md records why). "
                f"Use `effort: low` on the session model instead."
            )

        if model and model != "inherit" and not has_reason:
            failures.append(
                f"{name}: pinned to `model: {model}` with no `# reason:` comment in the "
                f"frontmatter. {ROUTING_RULE} requires a pin to have \"a reason the "
                f"effort dial cannot serve\", written beside the pin — add the comment, "
                f"or drop the pin for `effort:`."
            )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--verbose", action="store_true", help="List every agent checked")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    failures = check(root)

    if args.verbose:
        for agent_file in sorted((root / AGENTS_DIR).glob("*.md")):
            block = frontmatter_lines(agent_file)
            fm = parse_frontmatter(block)
            print(f"  {agent_file.stem}: model={fm.get('model', '(inherit)')} "
                  f"effort={fm.get('effort', '(session)')} "
                  f"tools={'yes' if fm.get('tools') else 'no'} "
                  f"reason={'yes' if any(_REASON_RE.search(ln) for ln in block) else 'no'}")

    if failures:
        print("FAIL  harness routing — agent pins violate model-routing.md's requirements:")
        for f in failures:
            print(f"  - {f}")
        return 1

    n = len(list((root / AGENTS_DIR).glob("*.md")))
    print(f"PASS  harness routing: {n} agent(s) conform (no Haiku pins; every pin carries its reason).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
