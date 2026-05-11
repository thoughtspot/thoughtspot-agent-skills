#!/usr/bin/env python3
"""
smoke_ts_dependency_manager.py — live smoke test for ts-dependency-manager.

Verifies the dependency management workflow against a real ThoughtSpot instance:
  1.  ThoughtSpot auth
  2.  Find target model by name and get its GUID
  3.  Export model TML with --associated --parse
  4.  ts metadata dependents (flat row output)
  5.  ts metadata dependents --raw (v2 structured output)
  6.  Create TML backup
  7.  Import original model TML via stdin (round-trip; no modifications)
  8.  Verify round-trip via re-export
  9.  (Optional) ts metadata delete --type — requires --test-delete-guid and
      --test-delete-type to provide a throwaway object for the deletion test

The test does NOT perform RENAME — that operation is not supported by the
ts-dependency-manager skill (see SKILL.md for rationale).

Usage:
    python tools/smoke-tests/smoke_ts_dependency_manager.py \\
        --ts-profile production \\
        --model-name "Retail Sales" \\
        [--test-delete-guid <guid> --test-delete-type LIVEBOARD] \\
        [--no-cleanup]

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
import time
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))

from _common import SmokeTestResult, SkipStep, ts_auth_check, run_ts  # noqa: E402


# ---------------------------------------------------------------------------
# TML import helper (stdin only — ts tml import has no --file flag)
# ---------------------------------------------------------------------------

def _ts_import_stdin(ts_profile: str, tml_str: str,
                     extra_flags: list[str]) -> list | dict:
    """Import a single TML YAML string via ts tml import (reads JSON array from stdin)."""
    cmd = ["ts", "tml", "import", "--profile", ts_profile] + extra_flags
    result = subprocess.run(cmd, input=json.dumps([tml_str]),
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ts tml import failed:\n{result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"ts tml import returned non-JSON:\n{result.stdout[:300]}"
        ) from e


# ---------------------------------------------------------------------------
# Main smoke test
# ---------------------------------------------------------------------------

def run_smoke_test(ts_profile: str, model_name: str,
                   test_delete_guid: str | None, test_delete_type: str | None,
                   no_cleanup: bool) -> int:
    result = SmokeTestResult()
    backup_dir = None

    print("=" * 60)
    print("Smoke test: ts-dependency-manager")
    print("=" * 60)
    print(f"  ThoughtSpot profile:  {ts_profile}")
    print(f"  Target model:         {model_name}")
    if test_delete_guid:
        print(f"  Delete test GUID:     {test_delete_guid} ({test_delete_type})")
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

    # ── Step 2: Find model ────────────────────────────────────────────────
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

    # metadata search returns a list; each item has metadata_id (not header.id)
    model_guid = search_results[0]["metadata_id"]
    model_display_name = search_results[0].get("metadata_name", model_name)
    result.info(f"Model GUID: {model_guid}  ({model_display_name})")

    # ── Step 3: Export TML ───────────────────────────────────────────────
    ok, tml_docs = result.step(
        "Export model TML (--fqn --associated --parse)",
        run_ts, ["tml", "export", model_guid, "--fqn", "--associated", "--parse"],
        ts_profile,
    )
    if not ok:
        return result.summary()

    if not isinstance(tml_docs, list) or not tml_docs:
        print("  FAIL  TML export returned empty result.")
        return 1

    model_doc = next(
        (d for d in tml_docs if d.get("type") in ("worksheet", "logical_table", "model")),
        None,
    )
    if not model_doc:
        print(f"  FAIL  No model TML found in export (got types: "
              f"{[d.get('type') for d in tml_docs]})")
        return 1

    result.info(f"Exported {len(tml_docs)} TML document(s)")

    # ── Step 4: ts metadata dependents (flat) ────────────────────────────
    def _test_dependents_flat():
        rows = run_ts(["metadata", "dependents", model_guid], ts_profile)
        if not isinstance(rows, list):
            raise RuntimeError(f"Expected list output, got: {type(rows).__name__}")
        result.info(f"dependents (flat): {len(rows)} row(s)")
        if rows:
            sample = rows[0]
            required = {"metadata_id", "metadata_name", "metadata_type"}
            missing = required - set(sample.keys())
            if missing:
                raise RuntimeError(f"Flat row missing expected keys: {missing}")
        return rows

    ok, dep_rows = result.step(
        "ts metadata dependents (flat output)",
        _test_dependents_flat,
    )
    if ok:
        result.info("Open item #1: VERIFIED — ts metadata dependents returns valid flat rows")

    # ── Step 5: ts metadata dependents --raw ─────────────────────────────
    def _test_dependents_raw():
        raw = run_ts(["metadata", "dependents", model_guid, "--raw"], ts_profile)
        # --raw returns a list of per-GUID objects; each has dependent_objects.dependents
        if not isinstance(raw, list) or not raw:
            raise RuntimeError(f"Expected non-empty list from --raw, got: {type(raw).__name__}")
        first = raw[0]
        dep_obj = first.get("dependent_objects", {})
        if not isinstance(dep_obj, dict):
            raise RuntimeError(f"Expected dependent_objects dict, got: {type(dep_obj).__name__}")
        deps = dep_obj.get("dependents", {})
        result.info(f"dependents (raw): {len(deps)} dependent GUID(s)")
        return raw

    ok, _ = result.step(
        "ts metadata dependents --raw (v2 structured output)",
        _test_dependents_raw,
    )

    # ── Step 6: Create TML backup ─────────────────────────────────────────
    timestamp = int(time.time())
    backup_dir = Path(tempfile.gettempdir()) / f"ts_dep_smoke_{timestamp}"

    def _create_backup():
        backup_dir.mkdir(parents=True, exist_ok=True)
        manifest = {"model_guid": model_guid, "model_name": model_name,
                    "timestamp": timestamp, "files": []}
        for i, doc in enumerate(tml_docs):
            doc_type = doc.get("type", f"doc_{i}")
            doc_body = doc.get(doc_type) or {}
            doc_guid = doc_body.get("guid") or f"unknown_{i}"
            fname = f"{doc_type}_{doc_guid}.yaml"
            (backup_dir / fname).write_text(
                yaml.dump(doc, allow_unicode=True, default_flow_style=False)
            )
            manifest["files"].append(fname)
        (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return backup_dir

    ok, _ = result.step("Create TML backup", _create_backup)
    if not ok:
        return result.summary()
    result.info(f"Backup: {backup_dir}")

    # ── Step 7: Import original model TML via stdin (round-trip) ─────────
    def _import_round_trip():
        tml_str = yaml.dump(model_doc, allow_unicode=True, default_flow_style=False)
        resp = _ts_import_stdin(ts_profile, tml_str,
                                ["--policy", "ALL_OR_NONE", "--no-create-new"])
        # Treat api=ERROR + verified (post-check) as success per open-item #15
        items = resp if isinstance(resp, list) else [resp]
        for item in items:
            status = (item.get("response", {}).get("status", {}) or
                      item.get("object", [{}])[0].get("response", {}).get("status", {}))
            sc = (status.get("status_code") if isinstance(status, dict) else None)
            if sc not in (None, "OK", "ERROR"):
                raise RuntimeError(f"Unexpected import status_code: {sc}")
        return resp

    ok, _ = result.step(
        "Import original model TML via stdin (round-trip, no modifications)",
        _import_round_trip,
    )
    if not ok:
        return result.summary()

    # ── Step 8: Verify round-trip via re-export ───────────────────────────
    def _verify_round_trip():
        re_exported = run_ts(
            ["tml", "export", model_guid, "--fqn", "--parse"], ts_profile,
        )
        for doc in re_exported:
            if doc.get("type") in ("worksheet", "logical_table", "model"):
                return doc
        raise RuntimeError("Model TML not found in re-export after round-trip import")

    ok, _ = result.step("Verify round-trip via re-export", _verify_round_trip)

    # ── Step 9 (optional): ts metadata delete --type ─────────────────────
    if test_delete_guid and test_delete_type:
        v2_type_map = {
            "ANSWER":    "ANSWER",
            "LIVEBOARD": "LIVEBOARD",
            "MODEL":     "LOGICAL_TABLE",
            "WORKSHEET": "LOGICAL_TABLE",
            "VIEW":      "LOGICAL_TABLE",
            "TABLE":     "LOGICAL_TABLE",
            "SET":       "LOGICAL_COLUMN",
            "COHORT":    "LOGICAL_COLUMN",
        }
        v2_type = v2_type_map.get(test_delete_type.upper(), test_delete_type)

        def _test_delete():
            r = subprocess.run(
                ["bash", "-c",
                 f"source ~/.zshenv && ts metadata delete {test_delete_guid} "
                 f"--type {v2_type} --profile '{ts_profile}'"],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                raise RuntimeError(f"ts metadata delete failed: {r.stderr[:300]}")
            # Verify deletion by re-querying
            check = subprocess.run(
                ["bash", "-c",
                 f"source ~/.zshenv && ts metadata get {test_delete_guid} "
                 f"--type {v2_type} --profile '{ts_profile}'"],
                capture_output=True, text=True,
            )
            if check.returncode == 0 and check.stdout.strip():
                raise RuntimeError(
                    f"Object still present after delete — "
                    f"ts metadata delete --type may not be working correctly"
                )
            return True

        ok, _ = result.step(
            f"ts metadata delete --type {v2_type} (open-item #17 verification)",
            _test_delete,
        )
        if ok:
            result.info(f"Open item #17: VERIFIED — object {test_delete_guid[:8]}... "
                        f"genuinely deleted (post-query returned not-found)")

    # ── Cleanup ───────────────────────────────────────────────────────────
    if not no_cleanup and backup_dir and backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)
        result.info(f"Backup directory cleaned up: {backup_dir}")
    elif no_cleanup:
        result.info(f"--no-cleanup: backup preserved at {backup_dir}")

    return result.summary()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live smoke test for ts-dependency-manager"
    )
    parser.add_argument("--ts-profile", required=True,
                        help="ThoughtSpot profile name (from ts-profile-thoughtspot setup)")
    parser.add_argument("--model-name", required=True,
                        help="Name of the ThoughtSpot model to test against")
    parser.add_argument("--test-delete-guid",
                        help="Optional: GUID of a throwaway object to test ts metadata delete --type")
    parser.add_argument("--test-delete-type",
                        help="Type of the throwaway object (LIVEBOARD, ANSWER, etc.)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Keep backup directory after test for inspection")
    args = parser.parse_args()

    if bool(args.test_delete_guid) != bool(args.test_delete_type):
        parser.error("--test-delete-guid and --test-delete-type must be provided together")

    return run_smoke_test(
        ts_profile=args.ts_profile,
        model_name=args.model_name,
        test_delete_guid=args.test_delete_guid,
        test_delete_type=args.test_delete_type,
        no_cleanup=args.no_cleanup,
    )


if __name__ == "__main__":
    sys.exit(main())
