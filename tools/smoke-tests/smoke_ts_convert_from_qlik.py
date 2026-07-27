#!/usr/bin/env python3
"""
smoke_ts_convert_from_qlik.py — offline smoke test for ts-convert-from-qlik.

Runs the full `ts qlik` pipeline over a bundled `.qvf` fixture and asserts real
TML + a mapping.json are produced and lint clean:
  1. `ts qlik parse`         — .qvf -> inventory JSON
  2. `ts qlik build-model`   — -> Table TML(s) + Model TML + mapping.json
  3. `ts tml lint`           — pre-import invariant lint (offline, no connection)
  4. `ts qlik build-liveboard` — -> tabbed Liveboard TML (one tab per Qlik sheet)

Does NOT require a live ThoughtSpot or Qlik connection — uses the offline `.qvf`
path over a bundled fixture. The live modes (`--mode qlik-cloud|engine`) need a
real Qlik tenant/engine and are covered by mocked unit tests + open-items #6.

Usage:
    python tools/smoke-tests/smoke_ts_convert_from_qlik.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = REPO_ROOT / "tools" / "ts-cli" / "tests" / "fixtures" / "qlik" / "SqliteApp.qvf"


def _run_ts(args: list[str]) -> subprocess.CompletedProcess:
    """Run a `ts` CLI command, inheriting PATH (the offline path needs no creds)."""
    return subprocess.run(["ts", *args], capture_output=True, text=True, timeout=120)


def _check(res: subprocess.CompletedProcess, what: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(f"{what} failed (exit {res.returncode}): "
                           f"{res.stderr.strip() or res.stdout.strip()}")


def main() -> int:
    r = SmokeTestResult()
    print("\nSmoke test: ts-convert-from-qlik (offline .qvf path)\n")

    if not FIXTURE.is_file():
        print(f"SKIP — fixture not found: {FIXTURE}")
        return 0

    with tempfile.TemporaryDirectory(prefix="smoke_ts_qlik_") as tmp:
        tmp_path = Path(tmp)
        inv = tmp_path / "inv.json"
        out = tmp_path / "out"

        def _parse():
            res = _run_ts(["qlik", "parse", str(FIXTURE), "-o", str(inv)])
            _check(res, "ts qlik parse")
            assert inv.is_file(), "parse produced no inventory JSON"
            return json.loads(res.stdout or "{}")

        ok, counts = r.step("ts qlik parse (offline .qvf)", _parse)
        if not ok:
            return r.summary()
        r.info(f"counts: {json.dumps(counts)}")

        def _build_model():
            res = _run_ts(["qlik", "build-model", str(FIXTURE),
                           "-c", "SMOKE_CONN", "--db", "DB", "--schema", "PUBLIC",
                           "--model-name", "SMOKE_QLIK", "-o", str(out)])
            _check(res, "ts qlik build-model")
            names = {p.name for p in out.glob("*.tml")}
            assert any(n.startswith("table.") for n in names), f"no table TML in {names}"
            assert any(n.startswith("model.") for n in names), f"no model TML in {names}"
            assert (out / "mapping.json").is_file(), "no mapping.json produced"
            return sorted(names)

        ok, names = r.step("ts qlik build-model -> Table+Model TML + mapping.json", _build_model)
        if not ok:
            return r.summary()
        r.info(f"TML: {names}")

        def _lint():
            tmls = sorted(out.glob("*.tml"))
            _check(_run_ts(["tml", "lint", "--dir", str(out)]), "ts tml lint")
            return len(tmls)

        ok, n = r.step("ts tml lint (offline invariant check)", _lint)
        if ok:
            r.info(f"linted {n} TML file(s) clean")

        def _build_lb():
            res = _run_ts(["qlik", "build-liveboard", str(FIXTURE),
                           "--model-name", "SMOKE_QLIK", "-o", str(out)])
            _check(res, "ts qlik build-liveboard")
            return [p.name for p in out.glob("liveboard.*.tml")]

        ok, lbs = r.step("ts qlik build-liveboard -> Liveboard TML", _build_lb)
        if ok:
            r.info(f"liveboard: {lbs or '(fixture has no sheets — no tabs emitted)'}")

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
