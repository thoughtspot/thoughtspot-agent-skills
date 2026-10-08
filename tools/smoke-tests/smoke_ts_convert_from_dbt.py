#!/usr/bin/env python3
"""
smoke_ts_convert_from_dbt.py — offline smoke test for ts-convert-from-dbt.

Exercises every step of the skill that does NOT need a live ThoughtSpot or dbt
Cloud connection, against a bundled compiled-manifest fixture:

  1. `ts dbt list-models --manifest`  — Step 5, the --model-tables array
  2. `ts dbt inspect --manifest`      — Step 8-pre, the Path N / Path Y decision
  3. artifact packing                 — `--file target/` -> upload-ready ZIP
  4. the same two reads from a ZIP    — the dbt Core (ZIP_FILE) path

What it deliberately does not cover: `ts dbt create`/`generate-tml`/
`generate-sync-tml` (they import objects into a real ThoughtSpot Org) and
`ts dbt build-model`/`trigger-job` (dbt Cloud API). Those need a live instance
and are tracked in references/open-items.md — this test is the offline floor,
not a claim that the whole skill is verified.

Usage:
    python tools/smoke-tests/smoke_ts_convert_from_dbt.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TARGET = REPO_ROOT / "tools" / "ts-cli" / "tests" / "fixtures" / "dbt" / "target"
MODEL_PATH = "models/staging/barbershop"


def _run_ts(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(["ts", *args], capture_output=True, text=True, timeout=120)


def _check(res: subprocess.CompletedProcess, what: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(f"{what} failed (exit {res.returncode}): "
                           f"{res.stderr.strip() or res.stdout.strip()}")


def main() -> int:
    r = SmokeTestResult()
    print("\nSmoke test: ts-convert-from-dbt (offline manifest path)\n")

    if not (TARGET / "manifest.json").is_file():
        print(f"SKIP — fixture not found: {TARGET}")
        return 0

    def _list_models():
        res = _run_ts(["dbt", "list-models", "--manifest", str(TARGET)])
        _check(res, "ts dbt list-models --manifest")
        groups = {g["model_path"]: g for g in json.loads(res.stdout)}
        g = groups.get(MODEL_PATH)
        assert g, f"{MODEL_PATH} not in {sorted(groups)}"
        # The ALIAS, not the file name. `stg_appointments` materialises as
        # APPOINTMENTS, and that is the only name ThoughtSpot matches --
        # emitting the file name 400s the whole generate-tml call.
        assert g["tables"] == ["APPOINTMENTS", "BARBERS"], \
            f"expected materialised aliases, got {g['tables']}"
        # An exact-dirname scan: the sibling barbershop_archive is its own group.
        assert f"{MODEL_PATH}_archive" in groups, "sibling directory not grouped separately"
        assert "OLD" not in g["tables"], "sibling directory leaked into this one"
        return g["tables"]

    ok, tables = r.step("ts dbt list-models --manifest -> --model-tables JSON", _list_models)
    if not ok:
        return r.summary()
    r.info(f"tables: {tables}")

    def _inspect():
        res = _run_ts(["dbt", "inspect", "--manifest", str(TARGET),
                       "--model-path", MODEL_PATH])
        _check(res, "ts dbt inspect")
        rep = json.loads(res.stdout)
        assert rep["recommended_path"] == "Y", \
            f"expected Path Y, got {rep['recommended_path']}: {rep['reasons']}"
        # Each signal that forces Y must be reported, not just the verdict.
        assert len(rep["ts_join_tests"]) == 1, \
            f"ts_join_* scan found {len(rep['ts_join_tests'])}, expected 1"
        assert rep["rls_models"] == ["stg_appointments"], \
            f"ts_rls_rules models: {rep['rls_models']}"
        # A plain relationships test with no ts_join_* meta is NOT a join
        # declaration -- counting it would invent joins the author never asked for.
        join = rep["ts_join_tests"][0]
        assert join["meta"]["ts_join_name"] == "appointment_to_barber"
        assert {m["table"] for m in rep["models"]} == {"APPOINTMENTS", "BARBERS"}
        return rep["recommended_path"], rep["reasons"]

    ok, got = r.step("ts dbt inspect --manifest -> Path N/Y decision", _inspect)
    if ok:
        r.info(f"path {got[0]}: {got[1][0]}")

    with tempfile.TemporaryDirectory(prefix="smoke_ts_from_dbt_") as tmp:
        def _pack():
            """`--file target/` must build the archive: zipping manifest +
            catalog by hand used to be a documented user prerequisite."""
            sys.path.insert(0, str(REPO_ROOT / "tools" / "ts-cli"))
            from ts_cli.dbt.artifacts import resolve_artifact_zip

            zpath = resolve_artifact_zip(str(TARGET))
            with zipfile.ZipFile(zpath) as zf:
                names = sorted(zf.namelist())
            # Flat at the archive root -- the layout ThoughtSpot's "a ZIP
            # containing manifest.json and catalog.json" implies.
            assert names == ["catalog.json", "manifest.json"], f"archive holds {names}"
            assert zpath.stat().st_mode & 0o077 == 0, "archive is group/world readable"
            return zpath

        ok, zpath = r.step("--file target/ -> upload-ready ZIP", _pack)
        if not ok:
            return r.summary()
        r.info(f"{zpath.name} ({zpath.stat().st_size} bytes)")

        def _reads_from_zip():
            """The ZIP_FILE path: the same two reads, straight out of the archive."""
            res = _run_ts(["dbt", "list-models", "--manifest", str(zpath)])
            _check(res, "ts dbt list-models --manifest <zip>")
            groups = {g["model_path"]: g for g in json.loads(res.stdout)}
            assert groups[MODEL_PATH]["tables"] == ["APPOINTMENTS", "BARBERS"]

            res = _run_ts(["dbt", "inspect", "--manifest", str(zpath),
                           "--model-path", MODEL_PATH])
            _check(res, "ts dbt inspect --manifest <zip>")
            assert json.loads(res.stdout)["recommended_path"] == "Y"
            return True

        ok, _ = r.step("both reads work straight from the ZIP", _reads_from_zip)
        if ok:
            r.info("dbt Core path needs no profile, token or network")

        def _missing_catalog_refused():
            """`dbt compile` writes only the manifest. ThoughtSpot types
            columns from catalog.json, so a manifest-only archive imports
            SUCCESSFULLY with no column types -- it has to be refused here."""
            from ts_cli.dbt.artifacts import resolve_artifact_zip

            partial = Path(tmp) / "compile_only"
            partial.mkdir()
            (partial / "manifest.json").write_text(
                (TARGET / "manifest.json").read_text())
            try:
                resolve_artifact_zip(str(partial))
            except SystemExit as exc:
                assert "dbt docs generate" in str(exc), f"unhelpful refusal: {exc}"
                return str(exc).split(".")[0]
            raise AssertionError("a manifest-only project was NOT refused")

        ok, msg = r.step("manifest without catalog.json is refused", _missing_catalog_refused)
        if ok:
            r.info(msg)

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
