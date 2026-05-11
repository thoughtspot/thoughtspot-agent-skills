#!/usr/bin/env python3
"""
smoke_ts_variable_timezone.py — live smoke test for ts-variable-timezone.

Verifies the timezone variable workflow against a real ThoughtSpot instance:
  1.  ThoughtSpot auth (ts auth whoami)
  2.  Search — confirm ts_user_timezone variable exists on the cluster
  3.  Set at org level (REPLACE) — Pacific/Honolulu on the target org
  4.  Verify set — search confirms the value appears
  5.  Remove (REMOVE) — clean up the test assignment
  6.  Verify remove — search confirms values array is empty

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
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import SmokeTestResult, SkipStep, ts_auth_check  # noqa: E402

TEST_TIMEZONE = "Pacific/Honolulu"
VARIABLE_NAME = "ts_user_timezone"


# ---------------------------------------------------------------------------
# REST API helper
# ---------------------------------------------------------------------------

def _get_token(ts_profile: str) -> str:
    result = subprocess.run(
        ["bash", "-c", f"source ~/.zshenv && ts auth token --profile {ts_profile}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ts auth token failed: {result.stderr.strip()}")
    token = result.stdout.strip()
    if not token:
        raise RuntimeError("ts auth token returned empty token")
    return token


def _api(base_url: str, token: str, path: str, body: dict,
         verify_ssl: bool = True) -> tuple[int, dict | list | None]:
    """POST to the REST API, return (http_status_code, parsed_body)."""
    verify_flag = [] if verify_ssl else ["-k"]
    result = subprocess.run(
        ["curl", "-s", *verify_flag, "-X", "POST",
         f"{base_url}{path}",
         "-H", "Accept: application/json",
         "-H", "Content-Type: application/json",
         "-H", f"Authorization: Bearer {token}",
         "--data-raw", json.dumps(body),
         "-w", "\n__STATUS__%{http_code}"],
        capture_output=True, text=True,
    )
    raw = result.stdout
    if "__STATUS__" not in raw:
        raise RuntimeError(f"Unexpected curl output: {raw[:200]}")
    body_part, status_part = raw.rsplit("__STATUS__", 1)
    status_code = int(status_part.strip())
    parsed = json.loads(body_part.strip()) if body_part.strip() else None
    return status_code, parsed


def _get_base_url(ts_profile: str) -> tuple[str, bool]:
    """Read base_url and verify_ssl from ~/.claude/thoughtspot-profiles.json."""
    profiles_path = Path.home() / ".claude" / "thoughtspot-profiles.json"
    if not profiles_path.exists():
        raise RuntimeError(f"No profiles file at {profiles_path}")
    data = json.loads(profiles_path.read_text())
    profiles = data.get("profiles", data) if isinstance(data, dict) else data
    for p in profiles:
        if p.get("name") == ts_profile:
            url = p["base_url"].rstrip("/")
            verify_ssl = p.get("verify_ssl", True)
            return url, verify_ssl
    raise RuntimeError(f"Profile '{ts_profile}' not found in {profiles_path}")


# ---------------------------------------------------------------------------
# Smoke test steps
# ---------------------------------------------------------------------------

def _step_auth(ts_profile: str) -> dict:
    return ts_auth_check(ts_profile)


def _step_search_variable(base_url: str, token: str, verify_ssl: bool) -> list:
    status, body = _api(base_url, token, "/api/rest/2.0/template/variables/search", {
        "record_offset": 0,
        "record_size": 10,
        "response_content": "METADATA_AND_VALUES",
        "variable_details": [{"identifier": VARIABLE_NAME}],
    }, verify_ssl)
    if status != 200:
        raise RuntimeError(f"Search returned HTTP {status}: {body}")
    if not body or not isinstance(body, list):
        raise RuntimeError(f"Unexpected search response: {body}")
    if body[0].get("name") != VARIABLE_NAME:
        raise SkipStep(
            f"{VARIABLE_NAME} not found on this cluster — "
            "ask your ThoughtSpot admin to create the variable"
        )
    return body[0].get("values", [])


def _step_set(base_url: str, token: str, verify_ssl: bool, org_name: str) -> None:
    status, body = _api(base_url, token, "/api/rest/2.0/template/variables/update-values", {
        "variable_assignment": [{
            "variable_identifier": VARIABLE_NAME,
            "variable_values": [TEST_TIMEZONE],
            "operation": "REPLACE",
        }],
        "variable_value_scope": [{"org_identifier": org_name}],
    }, verify_ssl)
    if status != 204:
        raise RuntimeError(f"Set returned HTTP {status}: {body}")


def _step_verify_set(base_url: str, token: str, verify_ssl: bool, org_name: str) -> None:
    status, body = _api(base_url, token, "/api/rest/2.0/template/variables/search", {
        "record_offset": 0,
        "record_size": 10,
        "response_content": "METADATA_AND_VALUES",
        "variable_details": [{"identifier": VARIABLE_NAME}],
    }, verify_ssl)
    if status != 200:
        raise RuntimeError(f"Verify-set search returned HTTP {status}")
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


def _step_remove(base_url: str, token: str, verify_ssl: bool, org_name: str) -> None:
    status, body = _api(base_url, token, "/api/rest/2.0/template/variables/update-values", {
        "variable_assignment": [{
            "variable_identifier": VARIABLE_NAME,
            "variable_values": [TEST_TIMEZONE],
            "operation": "REMOVE",
        }],
        "variable_value_scope": [{"org_identifier": org_name}],
    }, verify_ssl)
    if status != 204:
        raise RuntimeError(f"Remove returned HTTP {status}: {body}")


def _step_verify_remove(base_url: str, token: str, verify_ssl: bool, org_name: str) -> None:
    status, body = _api(base_url, token, "/api/rest/2.0/template/variables/search", {
        "record_offset": 0,
        "record_size": 10,
        "response_content": "METADATA_AND_VALUES",
        "variable_details": [{"identifier": VARIABLE_NAME}],
    }, verify_ssl)
    if status != 200:
        raise RuntimeError(f"Verify-remove search returned HTTP {status}")
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

    base_url, verify_ssl = _get_base_url(ts_profile)
    token = _get_token(ts_profile)

    ok, _ = r.step(
        f"Search — {VARIABLE_NAME} exists on cluster",
        _step_search_variable, base_url, token, verify_ssl,
    )
    if not ok:
        return r.summary()

    # Refresh token before mutations
    token = _get_token(ts_profile)

    set_ok, _ = r.step(
        f"Set {VARIABLE_NAME} = {TEST_TIMEZONE} (org level, org={org_name})",
        _step_set, base_url, token, verify_ssl, org_name,
    )

    if set_ok:
        token = _get_token(ts_profile)
        r.step(
            "Verify — value appears in search response",
            _step_verify_set, base_url, token, verify_ssl, org_name,
        )

    if not no_cleanup and set_ok:
        token = _get_token(ts_profile)
        remove_ok, _ = r.step(
            f"Remove — clean up test assignment",
            _step_remove, base_url, token, verify_ssl, org_name,
        )
        if remove_ok:
            token = _get_token(ts_profile)
            r.step(
                "Verify — value absent after remove",
                _step_verify_remove, base_url, token, verify_ssl, org_name,
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
