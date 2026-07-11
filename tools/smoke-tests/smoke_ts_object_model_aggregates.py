#!/usr/bin/env python3
"""
smoke_ts_object_model_aggregates.py — live smoke test for ts-object-model-aggregates.

Non-destructive end-to-end: drives the full `ts aggregate` pipeline the skill uses
(signatures -> recommend -> profile --emit-sql -> generate) against a real Model,
asserting the on-disk/stdout contract at each stage, WITHOUT ever registering a
table, importing TML, or touching the warehouse. `ts aggregate generate` itself
never imports (see its docstring) and needs no warehouse credentials for a
`ctas`-materialization run — the only network calls anywhere in this test are the
read-only `ts auth whoami`, `ts metadata search`, and the TML `export` calls
`signatures` and the tables-dir helper make.

Steps:
  1.  ThoughtSpot auth (ts auth whoami)
  2.  Resolve target Model (ts metadata search --subtype WORKSHEET)
  3.  ts aggregate signatures --model <guid> --out <tmp> — assert signatures.jsonl
      exists and the summary JSON parses with the expected keys
  4.  Export each model_tables Table TML into <tmp>/tables/ (same approach the
      skill's Step 3 uses) — required by profile/generate's --tables-dir
  5.  ts aggregate recommend --dir <tmp> — assert candidates.json is written and
      the stdout JSON has the expected shape (mode/selected/curve/candidates)
  6.  ts aggregate profile --dir <tmp> --tables-dir <tmp>/tables --emit-sql <path>
      (manual mode — no warehouse creds needed) — assert the emitted script
      contains a `__base__` statement
  7.  ts aggregate generate --dir <tmp> --candidate <id> --materialization ctas
      --out-dir <tmp>/gen — assert all five artifact files exist. Tries each
      candidate in turn (a candidate whose SQL isn't deterministically buildable
      is a real, reportable finding, not test flakiness) until one succeeds or
      the list is exhausted.
  8.  Cleanup — removes the temp working directory unless --no-cleanup is passed.

No imports, no table registration, no warehouse DDL execution, no TML mutation of
anything live. Safe to run repeatedly against the same Model.

Usage:
    python tools/smoke-tests/smoke_ts_object_model_aggregates.py \\
        --ts-profile production \\
        --model-guid  abc123...    \\          # preferred — stable, unambiguous
        [--model-name "Retail Sales"]         # alternative — resolved to GUID at runtime
        [--no-cleanup]

Provide exactly one of --model-guid or --model-name.
The specified Model must exist in ThoughtSpot and have at least one dependent
Answer/Liveboard with a parseable search_query for recommend to produce candidates
(zero candidates is tolerated — asserted as ">= 0", not "> 0" — see Step 5).
Credentials are read via the ts CLI profile (handles auth and token caching).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import SmokeTestResult, run_ts, ts_auth_check  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover — surfaced as a clear FAIL, not a traceback
    yaml = None


# ---------------------------------------------------------------------------
# ts CLI helpers
# ---------------------------------------------------------------------------

def _run_ts_capture(args: list[str], profile: str) -> tuple[dict | list, str]:
    """Run a `ts` subcommand and return (parsed_stdout_json, stderr_text).

    Like `_common.run_ts` but also returns stderr — several `ts aggregate` steps
    put useful diagnostics (skipped candidates, export failures) on stderr that
    are worth surfacing in `result.info()` without treating them as failures.
    """
    cmd = ["ts"] + args + ["--profile", profile]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ts {' '.join(args)} failed (exit {result.returncode}):\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"ts {' '.join(args)} returned non-JSON stdout:\n{result.stdout[:300]}"
        ) from e
    return parsed, result.stderr


def _export_table_tmls(workdir: Path, model_guid: str, profile: str) -> Path:
    """Export each `model_tables` entry's Table TML into <workdir>/tables/,
    mirroring the skill's Step 3 sub-step. Required by `profile`/`generate`'s
    --tables-dir (keyed by the table's exact, case-sensitive `name:`).
    """
    if yaml is None:
        raise RuntimeError("pyyaml is required for this smoke test: pip install pyyaml")

    model_tml = yaml.safe_load((workdir / "model.tml.yaml").read_text())
    model_tables = model_tml["model"]["model_tables"]
    if not model_tables:
        raise RuntimeError("Model has no model_tables — nothing to export.")

    tables_dir = workdir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    for entry in model_tables:
        table_name, table_fqn = entry["name"], entry.get("fqn")
        if not table_fqn:
            raise RuntimeError(
                f"model_tables entry '{table_name}' has no fqn — cannot export its Table TML."
            )
        cmd = ["ts", "tml", "export", table_fqn, "--profile", profile, "--fqn", "--parse"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"ts tml export {table_fqn} (table '{table_name}') failed: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        body = json.loads(result.stdout)
        table_section = body[0]["tml"]["table"]
        (tables_dir / f"{table_name}.tml.yaml").write_text(
            yaml.dump({"table": table_section}, default_flow_style=False, allow_unicode=True)
        )

    return tables_dir


def _root_connection_name(tables_dir: Path, model_guid: str) -> str:
    """Pull the root table's connection display name out of the exported Table
    TMLs — used as a realistic --connection-name for the non-executing `generate`
    step (no live connection lookup needed; generate never validates it over the
    network)."""
    for f in sorted(tables_dir.glob("*.tml.yaml")):
        doc = yaml.safe_load(f.read_text())
        name = doc.get("table", {}).get("connection", {}).get("name")
        if name:
            return name
    return "SMOKETEST_CONNECTION"


# ---------------------------------------------------------------------------
# Main smoke test
# ---------------------------------------------------------------------------

def run_smoke_test(ts_profile: str, model_name: str | None, model_guid: str | None,
                   no_cleanup: bool) -> int:
    result = SmokeTestResult()
    workdir: Path | None = None

    print("=" * 60)
    print("Smoke test: ts-object-model-aggregates")
    print("=" * 60)
    print(f"  ThoughtSpot profile:  {ts_profile}")
    if model_guid:
        print(f"  Target model GUID:    {model_guid}")
    else:
        print(f"  Target model name:    {model_name}")
    print()

    # ── Step 1: Auth ──────────────────────────────────────────────────────
    ok, whoami = result.step(
        "ThoughtSpot auth (ts auth whoami)",
        ts_auth_check, ts_profile,
    )
    if ok:
        result.info(f"Authenticated as: {whoami.get('userName', '?')}")
    if not ok:
        return result.summary()

    # ── Step 2: Resolve model GUID ────────────────────────────────────────
    if model_guid:
        ok, search_results = result.step(
            f"Verify model GUID {model_guid[:8]}...",
            run_ts, ["metadata", "search", "--subtype", "WORKSHEET",
                     "--guid", model_guid], ts_profile,
        )
        if not ok:
            return result.summary()
        if not search_results:
            print(f"  FAIL  No model found with GUID '{model_guid}'. Check --model-guid.")
            return 1
        model_display_name = search_results[0].get("metadata_name", model_guid)
    else:
        ok, search_results = result.step(
            f"Locate model '{model_name}'",
            run_ts, ["metadata", "search", "--subtype", "WORKSHEET",
                     "--name", model_name], ts_profile,
        )
        if not ok:
            return result.summary()
        if not search_results:
            print(f"  FAIL  No model named '{model_name}' found. Check --model-name.")
            return 1
        model_guid = search_results[0]["metadata_id"]
        model_display_name = search_results[0].get("metadata_name", model_name)

    result.info(f"Model GUID: {model_guid}  ({model_display_name})")

    workdir = Path(tempfile.mkdtemp(prefix="smoke_ts_agg_"))

    # ── Step 3: ts aggregate signatures (non-destructive — read-only exports) ─
    def _run_signatures():
        parsed, stderr = _run_ts_capture(
            ["aggregate", "signatures", "--model", model_guid,
             "--profile", ts_profile, "--out", str(workdir)],
            ts_profile,
        )
        required = {"model_guid", "signatures", "full", "partial",
                    "dependents", "export_failures"}
        missing = required - set(parsed.keys())
        if missing:
            raise RuntimeError(f"signatures summary missing expected keys: {missing}")
        if not (workdir / "signatures.jsonl").is_file():
            raise RuntimeError("signatures.jsonl was not written")
        if not (workdir / "model.tml.yaml").is_file():
            raise RuntimeError("model.tml.yaml was not written")
        last_line = stderr.strip().splitlines()[-1] if stderr.strip() else "(no stderr)"
        return parsed, last_line

    ok, sig_out = result.step(
        "ts aggregate signatures (export Model + dependents, parse signatures)",
        _run_signatures,
    )
    if not ok:
        _cleanup(workdir, no_cleanup, result)
        return result.summary()
    sig_summary, sig_stderr = sig_out
    result.info(
        f"{sig_summary['signatures']} signature(s): {sig_summary['full']} full, "
        f"{sig_summary['partial']} partial, from {sig_summary['dependents']} "
        f"dependent(s) ({sig_summary['export_failures']} export failure(s))"
    )
    result.info(f"CLI stderr: {sig_stderr}")

    # ── Step 4: export each model_tables Table TML (required by profile/generate) ─
    ok, tables_dir = result.step(
        "Export model_tables Table TML into <tmp>/tables/",
        _export_table_tmls, workdir, model_guid, ts_profile,
    )
    if not ok:
        _cleanup(workdir, no_cleanup, result)
        return result.summary()
    result.info(f"Tables dir: {tables_dir}")

    # ── Step 5: ts aggregate recommend (pure — reads workdir, no network) ────
    def _run_recommend():
        parsed, _stderr = _run_ts_capture(
            ["aggregate", "recommend", "--dir", str(workdir)], ts_profile,
        )
        required = {"mode", "selected", "curve", "candidates", "excluded_unprofiled"}
        missing = required - set(parsed.keys())
        if missing:
            raise RuntimeError(f"recommend result missing expected keys: {missing}")
        if parsed["candidates"] < 0:
            raise RuntimeError("candidates count is negative — impossible")
        if not (workdir / "candidates.json").is_file():
            raise RuntimeError("candidates.json was not written")
        return parsed

    ok, rec_out = result.step(
        "ts aggregate recommend (candidate generation + greedy ranking)",
        _run_recommend,
    )
    if not ok:
        _cleanup(workdir, no_cleanup, result)
        return result.summary()
    result.info(
        f"mode={rec_out['mode']}  candidates={rec_out['candidates']}  "
        f"selected={len(rec_out['selected'])}"
    )
    candidates_payload = json.loads((workdir / "candidates.json").read_text())
    candidate_ids = [c["id"] for c in candidates_payload.get("candidates", [])]

    # ── Step 6: ts aggregate profile --emit-sql (manual mode — no warehouse creds) ─
    def _run_profile_emit_sql():
        emit_path = workdir / "profile.sql"
        parsed, _stderr = _run_ts_capture(
            ["aggregate", "profile", "--dir", str(workdir),
             "--tables-dir", str(tables_dir), "--emit-sql", str(emit_path)],
            ts_profile,
        )
        if "emitted" not in parsed:
            raise RuntimeError(f"profile --emit-sql result missing 'emitted': {parsed}")
        if not emit_path.is_file():
            raise RuntimeError("profile.sql was not written")
        script = emit_path.read_text()
        if "__base__" not in script:
            raise RuntimeError("emitted profiling script does not contain a __base__ statement")
        return parsed, script

    ok, profile_out = result.step(
        "ts aggregate profile --emit-sql (manual mode, no warehouse creds)",
        _run_profile_emit_sql,
    )
    if not ok:
        _cleanup(workdir, no_cleanup, result)
        return result.summary()
    profile_summary, _script = profile_out
    result.info(f"Emitted {profile_summary['emitted']} statement(s), "
                f"{len(profile_summary.get('skipped') or [])} skipped")

    # ── Step 7: ts aggregate generate (never imports; ctas needs no --warehouse) ─
    def _run_generate():
        if not candidate_ids:
            raise RuntimeError(
                "recommend produced zero candidates — nothing to generate. "
                "Pick a Model with dependent Answers/Liveboards that share "
                "repeated grouping shapes."
            )
        connection_name = _root_connection_name(tables_dir, model_guid)
        gen_dir = workdir / "gen"
        errors = []
        for cid in candidate_ids:
            out_dir = gen_dir / cid
            cmd = ["ts", "aggregate", "generate",
                   "--dir", str(workdir), "--candidate", cid,
                   "--model-guid", model_guid, "--tables-dir", str(tables_dir),
                   "--db", "SMOKETEST_DB", "--schema", "SMOKETEST_SCHEMA",
                   "--connection-name", connection_name,
                   "--profile", ts_profile, "--materialization", "ctas",
                   "--out-dir", str(out_dir)]
            result_proc = subprocess.run(cmd, capture_output=True, text=True)
            if result_proc.returncode != 0:
                errors.append(f"{cid}: {result_proc.stderr.strip()[:200]}")
                continue
            expected = {"ddl.sql", "table_spec.json", "table.tml.yaml",
                        "agg_model.tml.yaml", "primary_patched.tml.yaml"}
            present = {p.name for p in out_dir.iterdir()} if out_dir.is_dir() else set()
            missing = expected - present
            if missing:
                errors.append(f"{cid}: generate exited 0 but files missing: {missing}")
                continue
            return cid, out_dir
        raise RuntimeError(
            f"No candidate could be generated (tried {len(candidate_ids)}): "
            + "; ".join(errors)
        )

    ok, gen_out = result.step(
        "ts aggregate generate (DDL + Table/Model TML + association patch, no import)",
        _run_generate,
    )
    if ok:
        gen_cid, gen_out_dir = gen_out
        result.info(f"Generated candidate '{gen_cid}' -> {gen_out_dir} (5/5 files present)")

    # ── Step 8: Cleanup ───────────────────────────────────────────────────
    _cleanup(workdir, no_cleanup, result)

    return result.summary()


def _cleanup(workdir: Path | None, no_cleanup: bool, result: SmokeTestResult) -> None:
    if workdir is None:
        return
    if no_cleanup:
        result.info(f"--no-cleanup: working directory preserved at {workdir}")
        return
    shutil.rmtree(workdir, ignore_errors=True)
    result.info(f"Working directory cleaned up: {workdir}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live smoke test for ts-object-model-aggregates"
    )
    parser.add_argument("--ts-profile", required=True,
                        help="ThoughtSpot profile name (from ts-profile-thoughtspot setup)")
    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument("--model-guid",
                          help="GUID of the ThoughtSpot Model (preferred — stable, unambiguous)")
    id_group.add_argument("--model-name",
                          help="Display name of the ThoughtSpot Model (resolved to GUID at runtime)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Keep the working directory after the test for inspection")
    args = parser.parse_args()

    return run_smoke_test(
        ts_profile=args.ts_profile,
        model_name=args.model_name,
        model_guid=args.model_guid,
        no_cleanup=args.no_cleanup,
    )


if __name__ == "__main__":
    sys.exit(main())
