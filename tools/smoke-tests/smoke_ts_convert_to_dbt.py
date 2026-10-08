#!/usr/bin/env python3
"""
smoke_ts_convert_to_dbt.py — offline smoke test for ts-convert-to-dbt.

Runs the whole `ts dbt-export` pipeline over bundled Model + Table TML fixtures
and asserts a real dbt project comes out, that re-diffing it is a no-op, and
that it round-trips back to a Model TML:

  1. `ts dbt-export build`        — Model+Table TML -> dbt project (Case A)
  2. re-`diff` the generated project — MUST be empty (the idempotence check)
  3. `ts dbt-export sync --dry-run`  — MUST write nothing
  4. `ts dbt-export build-model`     — schema.yml -> unified Model TML
  5. `ts tml lint`                   — pre-import invariants on that TML

Step 2 is the one that earns its keep. `build` and `diff` are separate code
paths over the same generator, so "generate a project, then diff the Model
against it" has exactly one correct answer — no new tables, no changed tables.
Any drift between what `build` writes and what `diff` expects to read shows up
here as a non-empty change-set, and nothing else in the suite catches it.

Does NOT require a live ThoughtSpot connection — `ts dbt-export` is an offline
file transform throughout. Getting the generated project back INTO ThoughtSpot
is ts-convert-from-dbt's job.

Usage:
    python tools/smoke-tests/smoke_ts_convert_to_dbt.py
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
FIXTURES = REPO_ROOT / "tools" / "ts-cli" / "tests" / "fixtures" / "dbt"

PROJECT = "barbershop"
SOURCE = "warehouse"


def _run_ts(args: list) -> subprocess.CompletedProcess:
    """Run a `ts` command. The offline path needs no credentials."""
    return subprocess.run(["ts", *args], capture_output=True, text=True, timeout=120)


def _check(res: subprocess.CompletedProcess, what: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(f"{what} failed (exit {res.returncode}): "
                           f"{res.stderr.strip() or res.stdout.strip()}")


def _case_b_args(project_dir: Path) -> list:
    return ["--model", str(FIXTURES / "model.json"),
            "--tables-dir", str(FIXTURES),
            "--project-name", PROJECT, "--source-name", SOURCE,
            "--project-dir", str(project_dir)]


def main() -> int:
    r = SmokeTestResult()
    print("\nSmoke test: ts-convert-to-dbt (offline TML -> dbt project)\n")

    if not (FIXTURES / "model.json").is_file():
        print(f"SKIP — fixtures not found: {FIXTURES}")
        return 0

    with tempfile.TemporaryDirectory(prefix="smoke_ts_to_dbt_") as tmp:
        proj = Path(tmp) / "barbershop_dbt"

        def _build():
            res = _run_ts(["dbt-export", "build",
                           "--model", str(FIXTURES / "model.json"),
                           "--tables-dir", str(FIXTURES),
                           "--project-name", PROJECT, "--source-name", SOURCE,
                           "--output-dir", str(proj)])
            _check(res, "ts dbt-export build")
            schema = proj / "models" / "schema.yml"
            assert schema.is_file(), "no models/schema.yml generated"
            text = schema.read_text()
            # The tags that make the project round-trippable at all.
            for tag in ("ts_column_type", "ts_aggregation", "ts_synonym",
                        "ts_join_name", "ts_rls_rules", "ts_formula"):
                assert tag in text, f"{tag} missing from schema.yml"
            # Nested blocks, not flat values -- the shape ThoughtSpot documents.
            assert "ts_currency_type" in text and "from_isocode" in text, \
                "ts_currency_type not emitted as a nested type: block"
            assert "ts_geo_config" in text and "latitude" in text, \
                "ts_geo_config not emitted as a nested type: block"
            sql = sorted(p.name for p in proj.rglob("*.sql"))
            assert sql, "no .sql models generated"
            return json.loads(res.stdout)

        ok, summary = r.step("ts dbt-export build -> dbt project", _build)
        if not ok:
            return r.summary()
        r.info(f"{summary['files_written']} file(s), {summary['tables']} table(s), "
               f"{summary['metrics']} metric(s)")

        def _diff_is_empty():
            res = _run_ts(["dbt-export", "diff", *_case_b_args(proj)])
            _check(res, "ts dbt-export diff")
            d = json.loads(res.stdout)
            # Regenerating into the project `build` just wrote must find nothing
            # to do. A non-empty result means build and diff disagree.
            for key in ("new_tables", "removed_tables", "new_source_tables",
                        "removed_source_tables"):
                assert not d[key], f"{key} non-empty on a freshly built project: {d[key]}"
            assert not d["changed_tables"], \
                f"changed_tables non-empty on a freshly built project: {list(d['changed_tables'])}"
            return d

        ok, _ = r.step("re-diff the generated project is a no-op", _diff_is_empty)
        if ok:
            r.info("build and diff agree — no drift between writer and reader")

        def _dry_run_writes_nothing():
            before = {p: p.read_bytes() for p in sorted(proj.rglob("*")) if p.is_file()}
            res = _run_ts(["dbt-export", "sync", "--dry-run", "--update-metadata",
                           "--format", "md", *_case_b_args(proj)])
            _check(res, "ts dbt-export sync --dry-run")
            after = {p: p.read_bytes() for p in sorted(proj.rglob("*")) if p.is_file()}
            assert before == after, "--dry-run modified the project"
            assert "change-set" in res.stdout, "markdown report not rendered"
            return len(before)

        ok, n = r.step("ts dbt-export sync --dry-run writes nothing", _dry_run_writes_nothing)
        if ok:
            r.info(f"{n} project file(s) byte-identical after the dry run")

        out_tml = Path(tmp) / "model_roundtrip.json"

        def _build_model():
            res = _run_ts(["dbt-export", "build-model",
                           "--schema-yml", str(proj / "models" / "schema.yml"),
                           "--model-name", "BARBERSHOP_OPERATIONS",
                           "--model-guid", "smoke-test-guid",
                           "--rls-out", str(Path(tmp) / "rls"),
                           "--output", str(out_tml)])
            _check(res, "ts dbt-export build-model")
            tml = json.loads(out_tml.read_text())
            # guid at the document ROOT -- nested under model: is rejected.
            assert tml.get("guid") == "smoke-test-guid", "guid not at document root"
            assert list(tml)[0] == "guid", "guid must be the first key"
            model = tml["model"]
            # IDENTITY MUST SURVIVE. `stg_appointments` carries
            # `alias: APPOINTMENTS`, so dbt materialises it under the name
            # ThoughtSpot already knows and a resync lands on the SAME Table.
            # Drop the alias and this comes back as STG_APPOINTMENTS: a
            # duplicate Table, the Model repointed at the copy, and the
            # original left holding every dependent it had.
            names = {t["name"] for t in model["model_tables"]}
            assert names == {"APPOINTMENTS", "BARBERS"}, \
                f"round trip renamed the tables: {names}"
            joins = [j for t in model["model_tables"] for j in t.get("joins") or []]
            assert len(joins) == 1, f"expected 1 join, got {len(joins)}"
            assert joins[0]["name"] == "appointment_to_barber", \
                f"round trip renamed the join: {joins[0]['name']}"
            assert "STG_" not in joins[0]["on"], \
                f"join points at staging relations: {joins[0]['on']}"
            assert model.get("formulas"), "formula lost on the return leg"
            # ts_display_name carries the human labels, so a column comes back
            # as "Barber Id", not the physical BARBER_ID.
            col_names = {c["name"] for c in model["columns"]}
            assert "Barber Id" in col_names, \
                f"display names lost on the return leg: {sorted(col_names)}"
            # RLS lives on the Table TML, so a Model-only command writes it out
            # -- keyed on the aliased Table name, not the dbt model name.
            rls = sorted(p.name for p in (Path(tmp) / "rls").glob("*.json"))
            assert rls == ["APPOINTMENTS_rls_rules.json"], f"rls files: {rls}"
            return len(model["columns"]), joins[0]["name"], rls

        ok, got = r.step("ts dbt-export build-model -> Model TML (round trip)", _build_model)
        if ok:
            r.info(f"{got[0]} column(s), join {got[1]!r}, rls written: {got[2]}")

        def _lint():
            _check(_run_ts(["tml", "lint", "--file", str(out_tml)]), "ts tml lint")
            return out_tml.name

        ok, name = r.step("ts tml lint (offline invariant check)", _lint)
        if ok:
            r.info(f"{name} passes pre-import invariants")

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
