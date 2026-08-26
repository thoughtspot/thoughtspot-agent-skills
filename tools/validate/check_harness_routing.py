"""check_harness_routing.py — every subagent's tier must match model-routing.md.

`CLAUDE.md` makes it an obligation that a new agent or workflow stage is tiered per
`.claude/rules/model-routing.md` **and recorded in that rule's table**. Nothing
enforced it: a grep for `.claude/agents`, `model-routing` or `.claude/workflows`
across `tools/validate/`, `scripts/` and `.github/workflows/` returned **zero
files**, so neither pre-commit nor CI read harness config at all (2026-08-26 audit,
finding 18.4).

That is precisely how the previous angle-18 finding survived: `consistency-checker`
carried a `model: haiku` pin that contradicted the rule's own "effort over model"
corollary *and* the user's no-Haiku-for-delegated-work policy, and it sat in the tree
until a manual sweep noticed. An obligation with no check is a preference.

What this asserts, per agent under `.claude/agents/`:

1. **It is named in the routing table.** An agent absent from
   "Current assignments" is untiered — the specific thing CLAUDE.md forbids.
2. **A `model:` pin is justified.** The rule states a pin "needs a reason the effort
   dial cannot serve", so a pinned agent must have its reason recorded in the table.
3. **No Haiku pin.** The rule records that the subagent-driven-development policy
   "rejects Haiku for delegated work outright". This is the exact regression that
   went unnoticed before.
4. **The declared tier matches the table.** A `model:`/`effort:` value that disagrees
   with what the table says about that agent is drift in one direction or the other.

Read-only agents additionally need a `tools:` grant, but that is a separate concern
(finding 18.6) and lives in the rule's prose rather than a parseable table, so it is
deliberately not asserted here.

Exit codes:
  0 — every agent is tiered and agrees with the table
  1 — an agent is untiered, disagrees, or carries an unjustified/forbidden pin

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


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Frontmatter key/values from a `---`-delimited agent file.

    Deliberately not a YAML parse: these files carry `#` comment lines inside the
    frontmatter (see the `tools:` grants added for 18.6) and only flat scalars
    matter here.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _FM_KEY_RE.match(line)
        if m:
            out[m.group("key")] = m.group("value")
    return out


def routing_assignments(rule_text: str) -> str:
    """The routing TABLE's rows only, lowercased for substring checks.

    Deliberately NOT the whole file. Matching the whole document made the check
    disarmable by ordinary prose: the 18.5 rewrite (same day) introduced a bare
    `effort: high` into the rules-of-thumb text, and assertion 4 ("the declared tier
    matches the table") silently stopped firing for `effort: high` — A/B verified. A
    gate that any nearby sentence can satisfy is not a gate.

    Restricting to table rows keeps the check honest: an agent's tier must be recorded
    in the assignments TABLE, which is what CLAUDE.md actually requires. Prose may
    discuss `effort: high` freely without vouching for any agent.
    """
    rows = [ln for ln in rule_text.splitlines() if ln.lstrip().startswith("|")]
    return "\n".join(rows).lower()


def check(root: Path) -> list[str]:
    failures: list[str] = []
    agents_dir = root / AGENTS_DIR
    rule_path = root / ROUTING_RULE

    if not agents_dir.is_dir():
        return failures                      # no agents to check
    if not rule_path.is_file():
        return [f"{ROUTING_RULE} is missing — CLAUDE.md requires tiers be recorded there."]

    rule_text = rule_path.read_text(encoding="utf-8")
    assignments = routing_assignments(rule_text)

    for agent_file in sorted(agents_dir.glob("*.md")):
        name = agent_file.stem
        fm = parse_frontmatter(agent_file)
        model = (fm.get("model") or "").strip().strip("\"'").lower()
        effort = (fm.get("effort") or "").strip().strip("\"'").lower()

        if name.lower() not in assignments:
            failures.append(
                f"{name}: not named in {ROUTING_RULE}'s assignments. CLAUDE.md requires a "
                f"new agent be tiered per that rule AND recorded in its table — an agent "
                f"absent from it is untiered."
            )
            continue

        if model in FORBIDDEN_MODEL_PINS:
            failures.append(
                f"{name}: `model: {model}` is forbidden for a delegated agent. "
                f"{ROUTING_RULE} records that the subagent-driven-development policy "
                f"rejects Haiku for delegated work, and that Haiku forfeits the effort "
                f"dial rather than being an alternative route to the same saving. Use "
                f"`effort: low` on the session model instead."
            )

        if model and model != "inherit":
            # The rule: "a `model:` pin needs a reason the effort dial cannot serve."
            # Require the pin to be visible in the table so the reason is reviewable.
            if f"{name.lower()}: {model}" not in assignments and f"`{name.lower()}: {model}`" not in assignments:
                failures.append(
                    f"{name}: pinned to `model: {model}`, but {ROUTING_RULE} does not record "
                    f"that pin. The rule requires a pin to have \"a reason the effort dial "
                    f"cannot serve\" — record the pin and its reason, or drop it for "
                    f"`effort:`."
                )

        if effort and f"effort: {effort}" not in assignments:
            failures.append(
                f"{name}: declares `effort: {effort}`, which {ROUTING_RULE} does not record. "
                f"Update the rule's assignments so the table and the frontmatter agree."
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
            fm = parse_frontmatter(agent_file)
            print(f"  {agent_file.stem}: model={fm.get('model', '(inherit)')} "
                  f"effort={fm.get('effort', '(session)')} "
                  f"tools={'yes' if fm.get('tools') else 'no'}")

    if failures:
        print("FAIL  harness routing — agent tiers disagree with model-routing.md:")
        for f in failures:
            print(f"  - {f}")
        return 1

    n = len(list((root / AGENTS_DIR).glob("*.md")))
    print(f"PASS  harness routing: {n} agent(s) tiered and recorded in model-routing.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
