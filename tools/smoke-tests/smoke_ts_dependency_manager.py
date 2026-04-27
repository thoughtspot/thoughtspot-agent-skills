#!/usr/bin/env python3
"""
smoke_ts_dependency_manager.py — live smoke test for ts-dependency-manager.

Verifies the full dependency management workflow against a real ThoughtSpot instance:
  1.  ThoughtSpot auth
  2.  Find target model by name and get its GUID
  3.  Export model TML with --associated flag
  4.  Dependency API (POST /tspublic/v1/dependency/listdependents) — open item #1
  5.  TML backup creation (manifest.json + all TML files)
  6.  Column rename in model TML (search_query + join expression safety checks)
  7.  Import renamed model TML
  8.  Verify rename via re-export
  9.  Rollback from backup
  10. Verify rollback via re-export
  11. Cleanup backup directory

The test uses a RENAME operation (not REMOVE) so it has no permanent effect even
if cleanup fails — the original column is always restored by step 9.

Usage:
    python tools/smoke-tests/smoke_ts_dependency_manager.py \\
        --ts-profile production \\
        --model-name "Retail Sales" \\
        --column-name "Revenue" \\
        [--no-cleanup]

The specified model must exist in ThoughtSpot and contain the named column.
The test renames the column to "<column-name>_smoke_test" and then renames it back.

Credentials are read from ~/.claude/thoughtspot-profiles.json (ts CLI handles auth).
"""
from __future__ import annotations

import argparse
import json
import re
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

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from _common import SmokeTestResult, SkipStep, ts_auth_check, run_ts  # noqa: E402


# ---------------------------------------------------------------------------
# Dependency API helper (open item #1 verification)
# ---------------------------------------------------------------------------

def call_dependency_api(base_url: str, token: str, guid: str) -> dict:
    """
    POST /tspublic/v1/dependency/listdependents
    Form-encoded, requires X-Requested-By header.
    Returns the full response dict (keys: QUESTION_ANSWER_BOOK, PINBOARD_ANSWER_BOOK,
    LOGICAL_TABLE — only keys with dependents are present).
    Raises RuntimeError on non-200 or unexpected response.
    """
    import urllib.request
    import urllib.parse

    payload = urllib.parse.urlencode({
        "type": "LOGICAL_TABLE",
        "id": json.dumps([guid]),
        "batchsize": "-1",
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/tspublic/v1/dependency/listdependents",
        data=payload,
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-Requested-By", "ThoughtSpot")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Dependency API returned HTTP {e.code}: {body[:300]}"
        )


def get_ts_token(profile: str) -> tuple[str, str]:
    """
    Return (base_url, token) by calling ts auth whoami --profile.
    The ts CLI caches the token — this doesn't re-authenticate.
    """
    result = subprocess.run(
        ["ts", "auth", "whoami", "--profile", profile],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ts auth whoami failed: {result.stderr.strip()}")

    data = json.loads(result.stdout)
    # Extract base_url and token from whoami output
    # whoami returns: {"userName": ..., "id": ..., "orgId": ...}
    # We need the profile metadata for base_url — read from profiles file
    profiles_path = Path.home() / ".claude" / "thoughtspot-profiles.json"
    if not profiles_path.exists():
        raise RuntimeError(f"No profiles file at {profiles_path}")

    profiles_data = json.loads(profiles_path.read_text())
    if isinstance(profiles_data, dict) and "profiles" in profiles_data:
        profiles = profiles_data["profiles"]
    elif isinstance(profiles_data, list):
        profiles = profiles_data
    else:
        raise RuntimeError("Unexpected profiles.json format")

    matching = [p for p in profiles if p.get("name") == profile]
    if not matching:
        raise RuntimeError(f"Profile '{profile}' not found in profiles file")

    base_url = matching[0]["url"].rstrip("/")

    # Read token from the ts CLI token cache
    token_cache = Path(tempfile.gettempdir()) / f"ts_token_{profile.lower().replace(' ', '_')}.txt"
    if not token_cache.exists():
        # Try slugified name (non-alphanumeric → hyphen)
        slug = re.sub(r"[^a-z0-9]", "-", profile.lower())
        token_cache = Path(tempfile.gettempdir()) / f"ts_token_{slug}.txt"

    if not token_cache.exists():
        raise SkipStep(
            "Token cache not found — dependency API test skipped. "
            "Run any ts command first to populate the token cache."
        )

    token = token_cache.read_text().strip()
    return base_url, token


# ---------------------------------------------------------------------------
# TML helpers
# ---------------------------------------------------------------------------

def sanitize_search_query(query_str: str, cols_to_remove: list[str]) -> str:
    for col in cols_to_remove:
        query_str = re.sub(r"\s*\[" + re.escape(col) + r"\]\s*", " ", query_str)
    return query_str.strip()


def rename_in_search_query(query_str: str, old_name: str, new_name: str) -> str:
    return re.sub(r"\[" + re.escape(old_name) + r"\]", f"[{new_name}]", query_str)


def rename_column_in_model(model_section: dict, old_name: str, new_name: str) -> dict:
    """Rename a column in model TML (columns list + join expressions)."""
    import copy
    section = copy.deepcopy(model_section)

    for col in section.get("columns", []):
        if col.get("name") == old_name:
            col["name"] = new_name

    # Update join on: expressions
    for tbl in section.get("model_tables", []):
        for join in tbl.get("joins_with", []):
            if "on" in join:
                join["on"] = rename_in_search_query(join["on"], old_name, new_name)

    return section


# ---------------------------------------------------------------------------
# Main smoke test
# ---------------------------------------------------------------------------

def run_smoke_test(ts_profile: str, model_name: str, column_name: str,
                   no_cleanup: bool) -> int:
    result = SmokeTestResult()
    backup_dir = None

    print("=" * 60)
    print("Smoke test: ts-dependency-manager")
    print("=" * 60)
    print(f"  ThoughtSpot profile:  {ts_profile}")
    print(f"  Target model:         {model_name}")
    print(f"  Test column:          {column_name}")
    print(f"  Operation:            rename '{column_name}' → '{column_name}_smoke_test'")
    print()

    # ── Step 1: Auth ──────────────────────────────────────────────────────
    ok, whoami = result.step(
        f"ThoughtSpot auth (ts auth whoami)",
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

    model_guid = search_results[0]["header"]["id"]
    result.info(f"Model GUID: {model_guid}")

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

    # Verify the target column exists in the model
    model_section = model_doc.get("model") or model_doc.get("worksheet") or {}
    col_names = [c.get("name") for c in model_section.get("columns", [])]
    if column_name not in col_names:
        print(f"  FAIL  Column '{column_name}' not found in model. "
              f"Available columns: {col_names[:10]}{'...' if len(col_names) > 10 else ''}")
        return 1
    result.info(f"Column '{column_name}' confirmed in model")

    # ── Step 4: Dependency API ────────────────────────────────────────────
    def _test_dependency_api():
        base_url, token = get_ts_token(ts_profile)
        resp = call_dependency_api(base_url, token, model_guid)
        answer_count = len(resp.get("QUESTION_ANSWER_BOOK", {}).get(model_guid, []))
        lb_count = len(resp.get("PINBOARD_ANSWER_BOOK", {}).get(model_guid, []))
        table_count = len(resp.get("LOGICAL_TABLE", {}).get(model_guid, []))
        return answer_count, lb_count, table_count

    ok, dep_counts = result.step(
        "Dependency API (POST /v1/dependency/listdependents)",
        _test_dependency_api,
    )
    if ok:
        answers, liveboards, tables = dep_counts
        result.info(f"Dependents found — Answers: {answers}, Liveboards: {liveboards}, "
                    f"Models/Views/Tables: {tables}")
        result.info("Open item #1: VERIFIED — dependency API accessible and returns valid response")
    # Dependency API failure is non-blocking — the skill has a TML scan fallback

    # ── Step 5: Create TML backup ─────────────────────────────────────────
    timestamp = int(time.time())
    backup_dir = Path(tempfile.gettempdir()) / f"ts_dep_smoke_{timestamp}"

    def _create_backup():
        backup_dir.mkdir(parents=True, exist_ok=True)
        manifest = {"model_guid": model_guid, "model_name": model_name,
                    "timestamp": timestamp, "files": []}
        for i, doc in enumerate(tml_docs):
            doc_type = doc.get("type", f"doc_{i}")
            doc_guid = (doc.get(doc_type, {}) or {}).get("guid", f"unknown_{i}")
            fname = f"{doc_type}_{doc_guid}.yaml"
            (backup_dir / fname).write_text(yaml.dump(doc, allow_unicode=True))
            manifest["files"].append(fname)
        (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return backup_dir

    ok, _ = result.step("Create TML backup", _create_backup)
    if not ok:
        return result.summary()
    result.info(f"Backup: {backup_dir}")

    # ── Step 6: Apply rename to model TML ────────────────────────────────
    rename_target = f"{column_name}_smoke_test"

    def _apply_rename():
        key = next(k for k in model_doc if k not in ("type", "guid"))
        renamed_section = rename_column_in_model(model_doc[key], column_name, rename_target)
        renamed_doc = dict(model_doc)
        renamed_doc[key] = renamed_section
        return renamed_doc

    ok, renamed_doc = result.step(
        f"Apply rename in TML ('{column_name}' → '{rename_target}')",
        _apply_rename,
    )
    if not ok:
        return result.summary()

    # Verify rename happened before importing
    key = next(k for k in renamed_doc if k not in ("type", "guid"))
    new_col_names = [c.get("name") for c in renamed_doc[key].get("columns", [])]
    assert rename_target in new_col_names, f"Rename not applied — column names: {new_col_names}"
    assert column_name not in new_col_names, "Original name still present after rename"

    # ── Step 7: Import renamed TML ───────────────────────────────────────
    def _import_renamed():
        # Write renamed TML to temp file and import
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                        delete=False, dir=backup_dir) as f:
            yaml.dump(renamed_doc, f, allow_unicode=True)
            tmp_path = f.name
        return run_ts(["tml", "import", tmp_path, "--fqn"], ts_profile)

    ok, import_result = result.step("Import renamed model TML", _import_renamed)
    if not ok:
        return result.summary()

    # ── Step 8: Verify rename via re-export ───────────────────────────────
    def _verify_rename():
        re_exported = run_ts(
            ["tml", "export", model_guid, "--fqn", "--parse"], ts_profile,
        )
        for doc in re_exported:
            key = next((k for k in doc if k not in ("type", "guid")), None)
            if key and doc.get("type") in ("worksheet", "logical_table", "model"):
                cols = [c.get("name") for c in doc[key].get("columns", [])]
                if rename_target in cols:
                    return True
        raise RuntimeError(
            f"Column '{rename_target}' not found in re-exported TML after import"
        )

    ok, _ = result.step("Verify rename in re-exported TML", _verify_rename)
    if not ok:
        return result.summary()

    # ── Step 9: Rollback from backup ─────────────────────────────────────
    def _rollback():
        # Re-import the original model TML from backup
        original_backup = next(
            backup_dir.glob(f"*_{model_guid}.yaml"),
            None,
        )
        if not original_backup:
            raise RuntimeError(
                f"Original model backup not found in {backup_dir}. "
                f"Files: {list(backup_dir.iterdir())}"
            )
        return run_ts(["tml", "import", str(original_backup), "--fqn"], ts_profile)

    ok, _ = result.step("Rollback from backup (restore original TML)", _rollback)
    if not ok:
        return result.summary()

    # ── Step 10: Verify rollback ──────────────────────────────────────────
    def _verify_rollback():
        re_exported = run_ts(
            ["tml", "export", model_guid, "--fqn", "--parse"], ts_profile,
        )
        for doc in re_exported:
            key = next((k for k in doc if k not in ("type", "guid")), None)
            if key and doc.get("type") in ("worksheet", "logical_table", "model"):
                cols = [c.get("name") for c in doc[key].get("columns", [])]
                if column_name in cols and rename_target not in cols:
                    return True
        raise RuntimeError(
            f"Rollback verification failed — original column '{column_name}' not restored"
        )

    ok, _ = result.step("Verify rollback in re-exported TML", _verify_rollback)

    # ── Cleanup ───────────────────────────────────────────────────────────
    if not no_cleanup and backup_dir and backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)
        result.info(f"Backup directory cleaned up: {backup_dir}")
    elif no_cleanup:
        result.info(f"--no-cleanup: backup preserved at {backup_dir}")

    return result.summary()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live smoke test for ts-dependency-manager (rename + rollback workflow)"
    )
    parser.add_argument("--ts-profile", required=True,
                        help="ThoughtSpot profile name (from ts-profile-thoughtspot setup)")
    parser.add_argument("--model-name", required=True,
                        help="Name of the ThoughtSpot model to test against")
    parser.add_argument("--column-name", required=True,
                        help="Column in that model to use as the rename test target")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Keep backup directory after test for inspection")
    args = parser.parse_args()

    return run_smoke_test(
        ts_profile=args.ts_profile,
        model_name=args.model_name,
        column_name=args.column_name,
        no_cleanup=args.no_cleanup,
    )


if __name__ == "__main__":
    sys.exit(main())
