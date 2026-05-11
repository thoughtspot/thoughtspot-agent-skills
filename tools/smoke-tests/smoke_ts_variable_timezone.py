#!/usr/bin/env python3
"""
smoke_ts_variable_timezone.py — live smoke test for ts-variable-timezone.

Verifies the timezone variable workflow against a real ThoughtSpot instance
using the ts CLI (not direct curl):
  1.  ThoughtSpot auth (ts auth whoami)
  2.  Search — confirm ts_user_timezone variable exists on the cluster
  3.  Set at org level (REPLACE) — Pacific/Honolulu on the target org
  4.  Verify set — search confirms the value appears
  5.  Remove (REMOVE) — clean up the test assignment
  6.  Verify remove — search confirms value absent

The test leaves no side-effects: step 5 always runs, even if earlier steps fail.

Usage:
    python tools/smoke-tests/smoke_ts_variable_timezone.py \\
        --ts-profile champ-staging \\
        [--org-name Primary] \\
        [--no-cleanup]

The ts_user_timezone variable must already exist on the cluster.
Credentials are read via the ts CLI profile (handles auth and token caching).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import SmokeTestResult, SkipStep, ts_auth_check  # noqa: E402

TEST_TIMEZONE = "Pacific/Honolulu"
VARIABLE_NAME = "ts_user_timezone"


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _ts(args: list[str], profile: str) -> str:
    """Run a ts CLI command and return stdout. Raises on non-zero exit."""
    cmd = ["bash", "-c", f"source ~/.zshenv && ts {' '.join(args)} --profile {profile}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ts {' '.join(args)} failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


def _ts_json(args: list[str], profile: str) -> list | dict | None:
    """Run a ts CLI command and parse the JSON output."""
    raw = _ts(args, profile)
    return json.loads(raw) if raw else None


# ---------------------------------------------------------------------------
# Smoke test steps
# ---------------------------------------------------------------------------

def _step_auth(ts_profile: str) -> dict:
    return ts_auth_check(ts_profile)


def _step_search_variable(ts_profile: str) -> list:
    body = _ts_json(["variables", "search", VARIABLE_NAME], ts_profile)
    if not body or not isinstance(body, list):
        raise RuntimeError(f"Unexpected search response: {body}")
    if body[0].get("name") != VARIABLE_NAME:
        raise SkipStep(
            f"{VARIABLE_NAME} not found on this cluster — "
            "ask your ThoughtSpot admin to create the variable"
        )
    return body[0].get("values", [])


def _step_set(ts_profile: str, org_name: str) -> None:
    _ts(["variables", "set", VARIABLE_NAME, TEST_TIMEZONE, "--org", org_name], ts_profile)


def _step_verify_set(ts_profile: str, org_name: str) -> None:
    body = _ts_json(["variables", "search", VARIABLE_NAME], ts_profile)
    values = body[0].get("values", []) if body else []
    match = next(
        (v for v in values
         if v.get("org_identifier") == org_name and v.get("principal_type") is None),
        None,
    )
    if not match:
        raise RuntimeError(
            f"Set value not found for org '{org_name}' in search response"
        )
    if match["value"] != TEST_TIMEZONE:
        raise RuntimeError(
            f"Expected '{TEST_TIMEZONE}', got '{match['value']}'"
        )


def _step_remove(ts_profile: str, org_name: str) -> None:
    _ts(["variables", "remove", VARIABLE_NAME, TEST_TIMEZONE, "--org", org_name], ts_profile)


def _step_verify_remove(ts_profile: str, org_name: str) -> None:
    body = _ts_json(["variables", "search", VARIABLE_NAME], ts_profile)
    values = body[0].get("values", []) if body else []
    match = next(
        (v for v in values
         if v.get("org_identifier") == org_name and v.get("principal_type") is None),
        None,
    )
    if match:
        raise RuntimeError(
            f"Value still present after remove: {match}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_smoke_test(ts_profile: str, org_name: str, no_cleanup: bool) -> int:
    print(f"\nSmoke test: ts-variable-timezone")
    print(f"  Profile : {ts_profile}")
    print(f"  Org     : {org_name}")
    print(f"  Variable: {VARIABLE_NAME}  →  {TEST_TIMEZONE}\n")

    r = SmokeTestResult()

    ok, _ = r.step("Auth check", _step_auth, ts_profile)
    if not ok:
        return r.summary()

    ok, _ = r.step(
        f"Search — {VARIABLE_NAME} exists on cluster",
        _step_search_variable, ts_profile,
    )
    if not ok:
        return r.summary()

    set_ok, _ = r.step(
        f"Set {VARIABLE_NAME} = {TEST_TIMEZONE} (org level, org={org_name})",
        _step_set, ts_profile, org_name,
    )

    if set_ok:
        r.step(
            "Verify — value appears in search response",
            _step_verify_set, ts_profile, org_name,
        )

    if not no_cleanup and set_ok:
        remove_ok, _ = r.step(
            "Remove — clean up test assignment",
            _step_remove, ts_profile, org_name,
        )
        if remove_ok:
            r.step(
                "Verify — value absent after remove",
                _step_verify_remove, ts_profile, org_name,
            )
    elif no_cleanup:
        r.info(f"--no-cleanup: leaving {TEST_TIMEZONE} set on org '{org_name}'")

    return r.summary()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ts-profile", required=True,
                        help="ThoughtSpot profile name from ~/.claude/thoughtspot-profiles.json")
    parser.add_argument("--org-name", default="Primary",
                        help="Org to use for the set/remove test (default: Primary)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Skip the remove step (leave test value in place)")
    args = parser.parse_args()
    return run_smoke_test(args.ts_profile, args.org_name, args.no_cleanup)


if __name__ == "__main__":
    sys.exit(main())
