#!/usr/bin/env python3
"""
smoke_ts_object_liveboard_chart_builder.py — smoke test for ts-object-liveboard-chart-builder.

Verifies the offline half of the pipeline on the bundled worked example
(liveboards/amuzing-chart-samples):
  1. The sibling ts-object-answer-chart-builder skill is found (scripts/chart-skill.mjs)
  2. liveboard-pack.mjs packs every tile in the spec into validate blocks
  3. Every block is syntactically valid JavaScript for the MCP sandbox
  4. The sandbox code (scripts/patch.js) run against a mock `ts` merges into a
     Liveboard it does not fully own: native charts, notes, other custom charts,
     a chart pinned from an answer, a user's copy of a skill tile, tiles of
     another Liveboard, tabs, filters, parameters, style and the name survive;
     a failed search, an untabbed Liveboard, an ownership conflict, tiles to
     adopt and a missing backup refuse the commit; a loss on import fails the
     round trip (_liveboard_patch_mock.mjs)

Does NOT require a live ThoughtSpot instance: the blocks are built, not sent.
Pasting them into execute-thoughtspot-code and cluster-shot.mjs need a cluster
and are covered by the live run described in the SKILL.md.

Usage:
    python tools/smoke-tests/smoke_ts_object_liveboard_chart_builder.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "agents" / "cli" / "ts-object-liveboard-chart-builder"
EXAMPLE = SKILL_DIR / "liveboards" / "amuzing-chart-samples"
PACK = SKILL_DIR / "scripts" / "liveboard-pack.mjs"
BLOCK_SEP = re.compile(r"^=====.*$", re.M)
MOCK = Path(__file__).parent / "_liveboard_patch_mock.mjs"


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
    if found != "ts-object-answer-chart-builder":
        raise AssertionError(f"resolved chart skill {found!r}")
    return p.stdout.strip()


def step_pack(out: Path, td: str) -> tuple[int, str]:
    spec = json.loads((EXAMPLE / "liveboard.spec.json").read_text())
    # The committed example carries placeholder guids; OFFLINE lets the pack build blocks that are never sent.
    p = subprocess.run(["node", str(PACK), "--liveboard", str(EXAMPLE), "--validate", "--all"],
                       capture_output=True, text=True, timeout=180,
                       env={**os.environ, "LIVEBOARD_PACK_OFFLINE": "1", "XDG_CACHE_HOME": td})
    if p.returncode != 0:
        raise AssertionError(f"liveboard-pack exited {p.returncode}: {p.stderr.strip()[-400:]}")
    # A commit never gets the offline pass: placeholder guids are refused.
    c = subprocess.run(["node", str(PACK), "--liveboard", str(EXAMPLE), "--commit", "--all"],
                       capture_output=True, text=True, timeout=180,
                       env={**os.environ, "LIVEBOARD_PACK_OFFLINE": "1", "XDG_CACHE_HOME": td})
    if c.returncode != 2:
        raise AssertionError(f"--commit with placeholder guids exited {c.returncode}, expected 2")
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


def step_merge_keeps_unowned(td: str) -> str:
    p = subprocess.run(["node", str(MOCK), str(SKILL_DIR), td],
                       capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        raise AssertionError(f"mock run exited {p.returncode}: {p.stderr.strip()[-400:]}")
    r = json.loads(p.stdout.strip().splitlines()[-1])
    if not r["ok"]:
        raise AssertionError("; ".join(r["failures"]))
    s = r["summary"]
    return f"replaced {s['replaced']}, kept {s['kept']}, removed {s.get('removed', [])}"


def main() -> int:
    print("smoke_ts_object_liveboard_chart_builder — offline pack of the worked example")
    print()

    r = SmokeTestResult()

    ok, _ = r.step("node on PATH", step_node_present)
    if not ok:
        return r.summary()

    ok, where = r.step("find sibling ts-object-answer-chart-builder", step_find_chart_skill)
    if not ok:
        return r.summary()
    r.info(where)

    with tempfile.TemporaryDirectory(prefix="ts_object_liveboard_smoke_") as td:
        out = Path(td) / "blocks.txt"
        ok, packed = r.step("pack the worked example (validate, --all)", step_pack, out, td)
        if ok:
            r.info(packed[1])
            ok, n = r.step("every block parses as sandbox code", step_blocks_parse, out, td)
            if ok:
                r.info(f"{n} block(s) parsed")
        ok, merged = r.step("patch merges into a Liveboard it does not own", step_merge_keeps_unowned, td)
        if ok:
            r.info(merged)

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
