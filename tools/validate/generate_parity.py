#!/usr/bin/env python3
"""Emit the PARITY.md skill matrix from the filesystem.

Run with --check to diff against the committed file.
Run with no args to print the generated matrix to stdout.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIMES = {
    "cli": lambda: {p.parent.name for p in (ROOT / "agents/cli").glob("*/SKILL.md")},
    "claude": lambda: {p.parent.name for p in (ROOT / "agents/claude").glob("*/SKILL.md")},
    "coco-snowsight": lambda: {p.parent.name for p in (ROOT / "agents/coco-snowsight").glob("*/SKILL.md")},
}


def matrix():
    cols = list(RUNTIMES)
    present = {rt: f() for rt, f in RUNTIMES.items()}
    skills = sorted(set().union(*present.values()))
    lines = [
        "| Skill | " + " | ".join(cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    for s in skills:
        lines.append(
            "| " + s + " | "
            + " | ".join("Y" if s in present[c] else "—" for c in cols)
            + " |"
        )
    return "\n".join(lines)


def check():
    parity = ROOT / "agents/PARITY.md"
    if not parity.exists():
        print("FAIL: agents/PARITY.md does not exist")
        return 1

    committed = parity.read_text()
    generated = matrix()

    # Extract just the data rows (skip header) for comparison
    gen_rows = set(generated.splitlines()[2:])
    missing = [r for r in gen_rows if r not in committed]
    extra = []
    # Find rows in committed matrix that shouldn't be there
    in_matrix = False
    for line in committed.splitlines():
        if line.startswith("| Skill |"):
            in_matrix = True
            continue
        if in_matrix and line.startswith("|---"):
            continue
        if in_matrix and line.startswith("| "):
            if line not in gen_rows:
                extra.append(line)
        elif in_matrix:
            in_matrix = False

    if missing or extra:
        print("FAIL: PARITY.md matrix is stale — regenerate with:")
        print("  python3 tools/validate/generate_parity.py > /tmp/matrix.txt")
        if missing:
            print("\nMissing rows:")
            for r in missing:
                print(f"  {r}")
        if extra:
            print("\nExtra/wrong rows:")
            for r in extra:
                print(f"  {r}")
        return 1

    print("PASS parity matrix")
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    else:
        print(matrix())
