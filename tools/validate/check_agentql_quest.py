#!/usr/bin/env python3
"""
check_agentql_quest.py — AgentQL Quest still matches the captured lesson SQL it is built from.

The game is built by tools/quest/build.py from its pack (tools/quest/packs/agentql/: content.yaml,
pack.yaml, strings.yaml) plus the committed
agents/cli/ts-object-model-agentql-query/references/lesson-sql.md. A recapture can move the
generated SQL out from under an encounter, so that a "who put this line here?" question points at
a line that changed or no longer exists — the game would then teach something the SQL no longer
shows. This runs the build's own validation (`build.py --check`) and fails on any drift: a missing
or rejected case, AgentQL changed beyond layout, an `sql` line no longer present exactly, an
`sql_count` that no longer holds, a capture header naming a Model the AgentQL doesn't query, a row
cap or null guard credited to anyone but ThoughtSpot by a who point, a published fantasy name, or built data that
no longer fits the pack's generated quest.schema.json (from tools/quest/schema/core.json).

Lives here, as a thin wrapper, so the gate is catalogued with the other validators in
docs/quality-gates.md; the logic stays beside the tool it guards.

Usage:
    python3 tools/validate/check_agentql_quest.py --root .
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="repo root")
    args = ap.parse_args()

    build_py = Path(args.root).resolve() / "tools" / "quest" / "build.py"
    spec = importlib.util.spec_from_file_location("agentql_quest_build", build_py)
    if spec is None or spec.loader is None:
        print(f"FAIL  cannot load {build_py}")
        return 1
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main(["--check"])


if __name__ == "__main__":
    sys.exit(main())
