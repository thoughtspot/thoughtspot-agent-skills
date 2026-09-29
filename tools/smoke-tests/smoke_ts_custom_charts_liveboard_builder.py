#!/usr/bin/env python3
"""
smoke_ts_custom_charts_liveboard_builder.py — smoke test for ts-custom-charts-liveboard-builder.

Verifies the offline half of the pipeline on the bundled worked example
(liveboards/amuzing-chart-samples):
  1. The sibling ts-custom-charts-builder skill is found (scripts/chart-skill.mjs)
  2. liveboard-pack.mjs packs every tile in the spec into validate blocks
  3. Every block is syntactically valid JavaScript for the MCP sandbox

Does NOT require a live ThoughtSpot instance: the blocks are built, not sent.
Pasting them into execute-thoughtspot-code and cluster-shot.mjs need a cluster
and are covered by the live run described in the SKILL.md.

Usage:
    python tools/smoke-tests/smoke_ts_custom_charts_liveboard_builder.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "agents" / "cli" / "ts-custom-charts-liveboard-builder"
EXAMPLE = SKILL_DIR / "liveboards" / "amuzing-chart-samples"
PACK = SKILL_DIR / "scripts" / "liveboard-pack.mjs"
BLOCK_SEP = re.compile(r"^=====.*$", re.M)


def step_node_present():
    if shutil.which("node") is None:
        raise RuntimeError("node is not on PATH; the scripts are Node scripts")


def step_find_chart_skill() -> str:
    code = ('import("' + (SKILL_DIR / "scripts" / "chart-skill.mjs").as_uri() + '")'
            '.then(m => console.log(m.chartSkill()))')
    p = subprocess.run(["node", "--input-type=module", "-e", code],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise AssertionError(p.stderr.strip()[-400:])
    found = Path(p.stdout.strip()).name
    if found != "ts-custom-charts-builder":
        raise AssertionError(f"resolved chart skill {found!r}")
    return p.stdout.strip()


def step_pack(out: Path) -> tuple[int, str]:
    spec = json.loads((EXAMPLE / "liveboard.spec.json").read_text())
    p = subprocess.run(["node", str(PACK), "--liveboard", str(EXAMPLE), "--validate", "--all"],
                       capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        raise AssertionError(f"liveboard-pack exited {p.returncode}: {p.stderr.strip()[-400:]}")
    out.write_text(p.stdout)
    m = re.search(r"(\d+) tile\(s\) in (\d+) block\(s\)", p.stderr)
    if not m:
        raise AssertionError(f"no tile/block summary on stderr: {p.stderr.strip()[:300]}")
    if spec and isinstance(spec, dict) and "tiles" in spec and int(m.group(1)) != len(spec["tiles"]):
        raise AssertionError(f"packed {m.group(1)} tiles, spec has {len(spec['tiles'])}")
    return int(m.group(2)), m.group(0)


def step_blocks_parse(out: Path, td: str) -> int:
    blocks = [b.strip() for b in BLOCK_SEP.split(out.read_text()) if b.strip()]
    if not blocks:
        raise AssertionError("no blocks in liveboard-pack output")
    for i, b in enumerate(blocks, 1):
        f = Path(td) / f"block{i}.js"
        # The sandbox runs a block as an async function body.
        f.write_text("(async () => {\n" + b + "\n});\n")
        p = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            raise AssertionError(f"block {i} does not parse: {p.stderr.strip()[-300:]}")
    return len(blocks)


def main() -> int:
    print("smoke_ts_custom_charts_liveboard_builder — offline pack of the worked example")
    print()

    r = SmokeTestResult()

    ok, _ = r.step("node on PATH", step_node_present)
    if not ok:
        return r.summary()

    ok, where = r.step("find sibling ts-custom-charts-builder", step_find_chart_skill)
    if not ok:
        return r.summary()
    r.info(where)

    with tempfile.TemporaryDirectory(prefix="ts_custom_charts_lb_smoke_") as td:
        out = Path(td) / "blocks.txt"
        ok, packed = r.step("pack the worked example (validate, --all)", step_pack, out)
        if ok:
            r.info(packed[1])
            ok, n = r.step("every block parses as sandbox code", step_blocks_parse, out, td)
            if ok:
                r.info(f"{n} block(s) parsed")

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
