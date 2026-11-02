#!/usr/bin/env python3
"""
smoke_ts_object_answer_chart_builder.py — smoke test for ts-object-answer-chart-builder.

Verifies the offline preview loop end-to-end:
  1. The doctor (helpers/env.mjs) resolves every path from the skill folder
  2. Every library chart ships its three files and a README
  3. The bundled fixture chart renders headless through the `viz` stub, with
     live data and with zero rows, and without console errors
  4. The answer write path (helpers/answer-patch.js) runs against a mock `ts` in
     _answer_patch_mock.mjs: a new answer, an update that keeps the user's
     column order and chart state, a round trip that catches their loss, and
     backups of an older state refused

Does NOT require a live ThoughtSpot instance. The user's own chart library
(~/.cache/ts-charts/library) is kept out with a temporary XDG_CACHE_HOME.
Step 3 needs the helpers' Playwright and Chromium. Locally it is skipped when
they are missing; in CI (CI or SMOKE_REQUIRE_BROWSER set) that is a failure:
    npm ci --prefix agents/cli/ts-object-answer-chart-builder/helpers
    npm exec --prefix agents/cli/ts-object-answer-chart-builder/helpers -- playwright install --with-deps chromium

Usage:
    python tools/smoke-tests/smoke_ts_object_answer_chart_builder.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import SkipStep, SmokeTestResult  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "agents" / "cli" / "ts-object-answer-chart-builder"
HELPERS = SKILL_DIR / "helpers"
FIXTURE = HELPERS / "fixtures" / "smoke"
MOCK = Path(__file__).parent / "_answer_patch_mock.mjs"
# CI must render in a real browser: there a missing Playwright is a failure, not a skip.
REQUIRE_BROWSER = bool(os.environ.get("SMOKE_REQUIRE_BROWSER") or os.environ.get("CI"))


def _node(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["node", *args], capture_output=True, text=True, timeout=180,
                          env={**os.environ, **(env or {})})


def _fields(stdout: str) -> dict[str, str]:
    """env.mjs and snap.mjs print one `key: value` per line."""
    out = {}
    for line in stdout.splitlines():
        key, sep, value = line.partition(": ")
        if sep:
            out[key.strip()] = value.strip()
    return out


def step_node_present():
    if shutil.which("node") is None:
        raise RuntimeError("node is not on PATH; the helpers are Node scripts")


def step_doctor(home: str) -> dict[str, str]:
    p = _node([str(HELPERS / "env.mjs"), "smoke", "--no-probe"], {"TS_CHART_HOME": home, "XDG_CACHE_HOME": str(Path(home) / "cache")})
    f = _fields(p.stdout)
    if Path(f.get("skill", "")).resolve() != SKILL_DIR.resolve():
        raise AssertionError(f"doctor resolved skill to {f.get('skill')!r}, expected {SKILL_DIR}")
    if Path(f.get("run-dir", "")) != Path(home) / "runs" / "smoke":
        raise AssertionError(f"doctor resolved run-dir to {f.get('run-dir')!r}")
    return f


def step_library_complete() -> int:
    slugs = [d for d in (SKILL_DIR / "library").iterdir() if d.is_dir() and not d.name.startswith("_")]
    if not slugs:
        raise AssertionError("library/ has no charts")
    for d in slugs:
        missing = [n for n in ("chart.html", "chart.css", "chart.js", "README.md") if not (d / n).is_file()]
        if missing:
            raise AssertionError(f"library/{d.name} is missing {', '.join(missing)}")
    for n in ("core.js", "core.css"):
        if not (SKILL_DIR / "library" / "_shared" / n).is_file():
            raise AssertionError(f"library/_shared/{n} is missing")
    return len(slugs)


def step_render(doctor: dict[str, str], home: str, attempt: str, data: str | None) -> str:
    if doctor.get("deps") != "ok":
        if REQUIRE_BROWSER:
            raise AssertionError(f"helpers deps missing in CI — {doctor.get('fix', 'run npm ci in helpers/')}")
        raise SkipStep(f"helpers deps missing — {doctor.get('fix', 'run npm install in helpers/')}")
    run_dir = Path(home) / "runs" / "smoke"
    if not run_dir.exists():
        shutil.copytree(FIXTURE, run_dir)
    args = [str(HELPERS / "snap.mjs"), "smoke", attempt] + ([f"--data={data}"] if data else [])
    p = _node(args, {"TS_CHART_HOME": home, "TS_CHART_HEADLESS": "1", "XDG_CACHE_HOME": str(Path(home) / "cache")})
    f = _fields(p.stdout)
    if p.returncode != 0:
        raise AssertionError(f"snap.mjs exited {p.returncode}: {p.stderr.strip()[-400:]}")
    if not f.get("status", "").startswith("[ok]"):
        raise AssertionError(f"preview status {f.get('status')!r}")
    if f.get("console-errors") != "none":
        raise AssertionError(f"console errors: {f.get('console-errors')}")
    if not Path(f.get("png", "")).is_file():
        raise AssertionError("no screenshot written")
    return f["status"]


def step_mock_write_path() -> int:
    p = subprocess.run(["node", str(MOCK)], capture_output=True, text=True, timeout=300)
    lines = [l for l in p.stdout.splitlines() if l.startswith(("PASS ", "FAIL "))]
    if p.returncode != 0 or not lines:
        raise AssertionError("; ".join(l for l in lines if l.startswith("FAIL ")) or p.stderr.strip()[-400:])
    return len(lines)


def main() -> int:
    print("smoke_ts_object_answer_chart_builder — offline preview loop")
    print()

    r = SmokeTestResult()

    ok, _ = r.step("node on PATH", step_node_present)
    if not ok:
        return r.summary()

    ok, n = r.step("library charts complete", step_library_complete)
    if ok:
        r.info(f"{n} library chart(s)")

    with tempfile.TemporaryDirectory(prefix="ts_custom_charts_smoke_") as home:
        ok, doctor = r.step("doctor resolves paths", step_doctor, home)
        if ok:
            ok, status = r.step("render fixture, live data", step_render, doctor, home, "01", None)
            if ok:
                r.info(status)
            r.step("render fixture, zero rows", step_render, doctor, home, "02", "empty")

    ok, n = r.step("answer write path against a mock ts", step_mock_write_path)
    if ok:
        r.info(f"{n} scenario(s) passed")

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
