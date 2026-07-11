#!/usr/bin/env python3
"""
smoke_ts_dependency_manager.py — live smoke test for ts-dependency-manager.

Rewired (audit finding 6.1) onto the real BL-083 command surface — skill v1.3.0/1.4.0
wired ts-dependency-manager Steps 7/9/11 to `ts dependency backup` / `apply-change` /
`rollback`, but this smoke test used to hand-roll its own backup dir + manifest and do
a no-op `ts tml import` round-trip instead of calling any of those subcommands. A
regression in the actual backup assembly, apply-change ordering, or ROOT-first
rollback would have passed silently. It now drives the three subcommands directly:

  1.  ThoughtSpot auth (ts auth whoami)
  2.  Find target model by name/GUID (ts metadata search --subtype WORKSHEET)
  3.  ts dependency backup            — NON-destructive; builds a REMOVE plan for the
      target model (source only, unless --fix-guid/--delete-guid are given), pipes it
      to `ts dependency backup` on stdin, and validates the returned manifest JSON and
      the backup directory it wrote to disk.
  4.  ts dependency apply-change      — DESTRUCTIVE. Gated behind an explicit opt-in
      flag, --run-apply-change (default OFF). Without the flag this step is SKIPPED,
      not run. When set, it builds a minimal REMOVE plan against the Step 3 backup_dir
      and validates the results JSON shape.
  5.  ts dependency rollback --only updates — restores the Step 3 backup's
      update-in-place entries (source + any --fix-guid) by re-importing the backed-up
      TML unchanged. This is an idempotent no-op when nothing was actually changed
      (i.e. when Step 4 was skipped), and is the safe way to exercise the rollback
      command surface every run.
  6.  Cleanup — removes the backup directory unless --no-cleanup is passed.

Safety tiers: Steps 3 and 5 are non-destructive/idempotent and always run. Step 4 is
the one destructive leg and requires an explicit opt-in flag — this smoke test does
not touch live data unless the caller passes --run-apply-change.

The test does NOT perform RENAME — that operation is not supported by the
ts-dependency-manager skill (see SKILL.md for rationale).

Usage:
    python tools/smoke-tests/smoke_ts_dependency_manager.py \\
        --ts-profile production \\
        --model-guid  abc123...   \\           # preferred — stable, unambiguous
        [--model-name "Retail Sales"]          # alternative — resolved to GUID at runtime
        [--fix-guid <guid>]                    # optional: include a dependent in the backup
        [--delete-guid <guid>]                 # optional: include a delete-candidate in the backup
        [--run-apply-change --apply-change-columns "Some Column,Other Column"] \\
        [--no-cleanup]

Provide exactly one of --model-guid or --model-name.
The specified model must exist in ThoughtSpot.
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

from _common import SmokeTestResult, SkipStep, ts_auth_check, run_ts  # noqa: E402


# ---------------------------------------------------------------------------
# Pure plan-builders — no I/O, unit-tested in
# tools/ts-cli/tests/test_smoke_ts_dependency_manager_plan.py
# ---------------------------------------------------------------------------

def _build_remove_plan(source: dict, fix: list | None = None,
                       delete: list | None = None, out_dir: str = "/tmp") -> dict:
    """Build a REMOVE plan JSON for `ts dependency backup` (pure — no I/O, no network).

    Matches the stdin shape `ts_cli.commands.dependency.backup_cmd` reads:
    `{"operation", "source", "fix", "delete", "out_dir"}`. `fix`/`delete` default to
    `[]` (a safe backup scoped to just the source object); `out_dir` defaults to
    `"/tmp"` matching the CLI's own default.
    """
    return {
        "operation": "REMOVE",
        "source": source,
        "fix": list(fix or []),
        "delete": list(delete or []),
        "out_dir": out_dir,
    }


def _build_apply_change_plan(source: dict, backup_dir: str, columns_to_remove: list,
                             fix: list | None = None, delete: list | None = None) -> dict:
    """Build a minimal REMOVE plan JSON for `ts dependency apply-change` (pure — no I/O).

    Matches what `ts_cli.commands.dependency_apply.apply_change_cmd` validates:
    `operation`, `source.guid`, a `backup_dir` (required — that's how rollback stays
    possible), and — for REMOVE — a non-empty `columns_to_remove`.
    """
    return {
        "operation": "REMOVE",
        "backup_dir": backup_dir,
        "source": source,
        "columns_to_remove": list(columns_to_remove),
        "fix": list(fix or []),
        "delete": list(delete or []),
    }


# ---------------------------------------------------------------------------
# ts CLI stdin helper — `ts dependency backup` / `apply-change` read a plan on stdin
# ---------------------------------------------------------------------------

def _run_ts_stdin(args: list[str], profile: str, payload: dict) -> tuple:
    """Run a `ts` subcommand that reads a JSON plan on stdin, returning
    `(parsed_stdout_json, stderr_text)`. Raises RuntimeError on non-zero exit or
    non-JSON stdout. Mirrors `_common.run_ts` but adds the stdin payload that
    `ts dependency backup`/`apply-change` require.
    """
    cmd = ["ts"] + args + ["--profile", profile]
    result = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)
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


# ---------------------------------------------------------------------------
# Main smoke test
# ---------------------------------------------------------------------------

def run_smoke_test(ts_profile: str, model_name: str | None, model_guid: str | None,
                   fix_guid: str | None, delete_guid: str | None,
                   run_apply_change: bool, apply_change_columns: list,
                   no_cleanup: bool) -> int:
    result = SmokeTestResult()
    backup_dir: Path | None = None

    print("=" * 60)
    print("Smoke test: ts-dependency-manager")
    print("=" * 60)
    print(f"  ThoughtSpot profile:  {ts_profile}")
    if model_guid:
        print(f"  Target model GUID:    {model_guid}")
    else:
        print(f"  Target model name:    {model_name}")
    if fix_guid:
        print(f"  Fix entry GUID:       {fix_guid}")
    if delete_guid:
        print(f"  Delete entry GUID:    {delete_guid}")
    print(f"  apply-change:         {'ENABLED (--run-apply-change)' if run_apply_change else 'SKIPPED (opt-in, not set)'}")
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
        # GUID provided directly — verify it exists and get the display name
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
    source = {"guid": model_guid, "type": "MODEL", "name": model_display_name}
    fix_list = [{"guid": fix_guid, "type": "ANSWER", "name": fix_guid}] if fix_guid else []
    delete_list = [{"guid": delete_guid, "type": "LIVEBOARD", "name": delete_guid}] if delete_guid else []

    # ── Step 3: ts dependency backup (non-destructive) ───────────────────
    def _run_backup():
        plan = _build_remove_plan(source, fix=fix_list, delete=delete_list,
                                  out_dir=tempfile.gettempdir())
        manifest, stderr = _run_ts_stdin(["dependency", "backup"], ts_profile, plan)

        if not isinstance(manifest, dict):
            raise RuntimeError(f"Expected a manifest JSON object, got: {type(manifest).__name__}")
        required = {"source_object", "objects", "operation"}
        missing = required - set(manifest.keys())
        if missing:
            raise RuntimeError(f"Manifest missing expected keys: {missing}")

        objects = manifest.get("objects") or []
        if not objects:
            raise RuntimeError("Manifest has no backed-up objects (expected at least the source).")

        dir_path = Path(objects[0]["backup_file"]).parent
        if not dir_path.is_dir():
            raise RuntimeError(f"Backup directory reported by manifest does not exist: {dir_path}")
        if not (dir_path / "manifest.json").is_file():
            raise RuntimeError(f"manifest.json not found in backup dir: {dir_path}")
        for obj in objects:
            bf = Path(obj["backup_file"])
            if not bf.is_file():
                raise RuntimeError(f"Backed-up TML file missing on disk: {bf}")

        last_line = stderr.strip().splitlines()[-1] if stderr.strip() else "(no stderr)"
        result.info(f"CLI stderr: {last_line}")
        return manifest, dir_path

    ok, backup_out = result.step(
        "ts dependency backup (non-destructive export + manifest)", _run_backup,
    )
    if not ok:
        return result.summary()
    manifest, backup_dir = backup_out
    result.info(f"Backup dir: {backup_dir}  ({len(manifest['objects'])} object(s) backed up)")

    # ── Step 4: ts dependency apply-change (DESTRUCTIVE — opt-in only) ───
    def _run_apply_change():
        if not run_apply_change:
            raise SkipStep(
                "apply-change is destructive — pass --run-apply-change to exercise it"
            )
        plan = _build_apply_change_plan(
            source, backup_dir=str(backup_dir), columns_to_remove=apply_change_columns,
        )
        parsed, _stderr = _run_ts_stdin(["dependency", "apply-change"], ts_profile, plan)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Expected a results JSON object, got: {type(parsed).__name__}")
        required = {"operation", "source", "succeeded", "failed"}
        missing = required - set(parsed.keys())
        if missing:
            raise RuntimeError(f"apply-change result missing expected keys: {missing}")
        return parsed

    ok, apply_result = result.step(
        "ts dependency apply-change (DESTRUCTIVE — opt-in via --run-apply-change)",
        _run_apply_change,
    )
    if ok and apply_result:
        result.info(
            f"apply-change: {len(apply_result.get('succeeded') or [])} succeeded, "
            f"{len(apply_result.get('failed') or [])} failed, "
            f"{len(apply_result.get('deleted') or [])} deleted"
        )

    # ── Step 5: ts dependency rollback --only updates (idempotent no-op) ─
    def _run_rollback_updates():
        parsed = run_ts(
            ["dependency", "rollback", "--backup-dir", str(backup_dir), "--only", "updates"],
            ts_profile,
        )
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Expected a results JSON object, got: {type(parsed).__name__}")
        required = {"succeeded", "failed", "new_guids"}
        missing = required - set(parsed.keys())
        if missing:
            raise RuntimeError(f"rollback result missing expected keys: {missing}")
        failed = parsed.get("failed") or []
        if failed:
            raise RuntimeError(f"rollback --only updates reported {len(failed)} failure(s): {failed}")
        return parsed

    ok, rollback_result = result.step(
        "ts dependency rollback --only updates (idempotent no-op restore)",
        _run_rollback_updates,
    )
    if ok:
        result.info(
            f"Rollback restored {len(rollback_result.get('succeeded') or [])} object(s), 0 failures"
        )

    # ── Step 6: Cleanup ───────────────────────────────────────────────────
    if not no_cleanup and backup_dir and backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)
        result.info(f"Backup directory cleaned up: {backup_dir}")
    elif no_cleanup and backup_dir:
        result.info(f"--no-cleanup: backup preserved at {backup_dir}")

    return result.summary()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live smoke test for ts-dependency-manager"
    )
    parser.add_argument("--ts-profile", required=True,
                        help="ThoughtSpot profile name (from ts-profile-thoughtspot setup)")
    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument("--model-guid",
                          help="GUID of the ThoughtSpot model (preferred — stable, unambiguous)")
    id_group.add_argument("--model-name",
                          help="Display name of the ThoughtSpot model (resolved to GUID at runtime)")
    parser.add_argument("--fix-guid",
                        help="Optional: GUID of a dependent object (e.g. an Answer) to include "
                             "in the backup plan's 'fix' list.")
    parser.add_argument("--delete-guid",
                        help="Optional: GUID of a dependent object (e.g. a Liveboard) to include "
                             "in the backup plan's 'delete' list.")
    parser.add_argument("--run-apply-change", action="store_true",
                        help="Opt in to running the DESTRUCTIVE `ts dependency apply-change` leg. "
                             "Default OFF — without this flag the step is skipped, not run.")
    parser.add_argument("--apply-change-columns",
                        help="Comma-separated source column name(s) to remove via apply-change. "
                             "Required (non-empty) when --run-apply-change is set; ignored otherwise.")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Keep backup directory after test for inspection")
    args = parser.parse_args()

    apply_change_columns = [c.strip() for c in (args.apply_change_columns or "").split(",") if c.strip()]
    if args.run_apply_change and not apply_change_columns:
        parser.error(
            "--apply-change-columns is required (non-empty, comma-separated) when "
            "--run-apply-change is set."
        )

    return run_smoke_test(
        ts_profile=args.ts_profile,
        model_name=args.model_name,
        model_guid=args.model_guid,
        fix_guid=args.fix_guid,
        delete_guid=args.delete_guid,
        run_apply_change=args.run_apply_change,
        apply_change_columns=apply_change_columns,
        no_cleanup=args.no_cleanup,
    )


if __name__ == "__main__":
    sys.exit(main())
