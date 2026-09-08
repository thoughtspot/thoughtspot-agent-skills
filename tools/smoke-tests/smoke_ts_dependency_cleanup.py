#!/usr/bin/env python3
"""
smoke_ts_dependency_cleanup.py — live smoke test for ts-dependency-cleanup.

The skill drives the v1 `/dependency/*` family directly over HTTP with a
session-login cookie (there is no `ts dependency` CLI surface for these
endpoints — see the skill's open item #6), so this test exercises the same
raw calls the skill makes rather than a CLI.

  1.  v1 session login              — POST session/login -> cookie jar, then
      session/info to confirm the cookie is usable.
  2.  Read-only lookups (ops 2-6)   — NON-destructive, always run. Confirms the
      GET verb, the JSON-array `id` form, and the documented response shape,
      including the two distinct empty forms: `{"<guid>":{}}` (0 dependents)
      vs `{}` (GUID is not of the endpoint's type).
  3.  Op 7 (pinboard)               — asserts the KNOWN-BROKEN 500. This step
      passes when the endpoint fails; if it ever returns 200 the skill's status
      table is stale and should be updated (open item #11).
  4.  Op 8 preview                  — NON-destructive. `apply_changes=false`
      against --column-guid. Validates the 200 shape (`dependents` + `csv`) and
      reports the cascade size. A `400 METADATA_ERROR` is recorded as a normal
      business-rule refusal, not a test failure (open item #18).
  5.  Op 8 apply                    — DESTRUCTIVE and IRREVERSIBLE. Gated behind
      --run-delete (default OFF). When skipped, nothing is deleted. When set,
      it diffs the applied set against the Step 4 preview to catch the
      under-reporting documented in open item #19.
  6.  Cleanup                       — deletes the cookie jar (a live credential).

Operation 9 (purge) is deliberately NOT exercised: its scope is unverified and
may be instance-wide over everything soft-deleted (open item #8). A smoke test
must not be the thing that finds out.

Safety tiers: Steps 1-4 and 6 never modify data and always run. Step 5 is the
only destructive leg and requires an explicit opt-in flag.

Usage:
    python tools/smoke-tests/smoke_ts_dependency_cleanup.py \
        --ts-profile dot133 \
        --column-guid <logical-column-guid> \
        [--pinboard-guid <guid>]     # optional: exercises the op-7 500 assertion
        [--run-delete]               # DESTRUCTIVE opt-in, default OFF

Credentials: the profile in ~/.claude/thoughtspot-profiles.json names an env var
(`password_env`); the secret itself lives in the OS keychain and must already be
exported into the calling shell. This test never prints it.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROFILES = Path.home() / ".claude" / "thoughtspot-profiles.json"
GUID_LEN = 36


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}")
    sys.exit(1)


def _load_profile(name: str) -> dict:
    if not PROFILES.exists():
        _fail(f"no profile store at {PROFILES} — run /ts-profile-thoughtspot")
    data = json.loads(PROFILES.read_text())
    profiles = data if isinstance(data, list) else [data]
    for p in profiles:
        if p.get("name") == name:
            return p
    names = ", ".join(str(p.get("name")) for p in profiles)
    _fail(f"profile {name!r} not found. Available: {names}")
    return {}


def _curl(args: list[str], verify_ssl: bool) -> tuple[int, str]:
    """Run curl, returning (http_status, body). Never echoes credentials."""
    cmd = ["curl", "-sS", "-w", "\n%{http_code}"]
    if not verify_ssl:
        cmd.append("-k")
    cmd += args
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return 0, res.stderr.strip()
    out = res.stdout.rsplit("\n", 1)
    body = out[0] if len(out) == 2 else ""
    try:
        status = int(out[-1].strip())
    except ValueError:
        status = 0
    return status, body


def run_smoke_test(profile_name: str, column_guid: str, pinboard_guid: str | None,
                   run_delete: bool) -> None:
    prof = _load_profile(profile_name)
    base = prof["base_url"].rstrip("/")
    verify = bool(prof.get("verify_ssl", True))
    v1 = f"{base}/callosum/v1/tspublic/v1"
    dep = f"{base}/callosum/v1/dependency"

    env_var = prof.get("password_env")
    if not env_var:
        _fail(f"profile {profile_name!r} has no password_env")
    secret = os.environ.get(env_var)
    if not secret:
        _fail(f"{env_var} is not exported in this shell — export it first")

    print("ts-dependency-cleanup smoke test")
    print(f"  profile:      {profile_name}")
    print(f"  base_url:     {base}")
    print(f"  verify_ssl:   {verify}")
    print(f"  column guid:  {column_guid}")
    print(f"  delete leg:   {'ENABLED (--run-delete)' if run_delete else 'SKIPPED (opt-in, not set)'}")

    jar = Path(tempfile.mkdtemp(prefix="ts_smoke_")) / "cookies.txt"
    try:
        # --- Step 1: login -------------------------------------------------
        print("\nStep 1  v1 session login")
        status, _ = _curl(["-c", str(jar), "-o", "/dev/null", "-X", "POST",
                           f"{v1}/session/login",
                           "--data-urlencode", f"username={prof['username']}",
                           "--data-urlencode", f"password={secret}",
                           "--data-urlencode", "rememberme=true"], verify)
        if status not in (200, 204):
            _fail(f"login returned {status} (expected 200/204)")
        jar.chmod(0o600)
        status, _ = _curl(["-b", str(jar), "-o", "/dev/null", f"{v1}/session/info"], verify)
        if status != 200:
            _fail(f"session/info returned {status} — cookie unusable")
        print("  PASS  logged in, cookie verified")

        # --- Step 2: read-only lookups -------------------------------------
        print("\nStep 2  read-only lookups (ops 2-6)")
        id_arg = json.dumps([column_guid])
        shape_seen = False
        for ep in ("logicalcolumn", "logicaltable", "logicalrelationship",
                   "physicalcolumn", "physicaltable"):
            status, body = _curl(["-b", str(jar), "-G", f"{v1}/dependency/{ep}",
                                  "--data-urlencode", f"id={id_arg}"], verify)
            if status != 200:
                _fail(f"{ep} returned {status} (expected 200)")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                _fail(f"{ep} returned unparseable JSON")
            if column_guid in parsed:
                n = sum(len(v) for v in parsed[column_guid].values())
                print(f"  PASS  {ep:22} 200, guid resolved, {n} dependent(s)")
                shape_seen = True
            elif parsed == {}:
                print(f"  PASS  {ep:22} 200, {{}} = wrong type for this endpoint")
            else:
                _fail(f"{ep} returned an undocumented shape: {list(parsed)[:3]}")
        if not shape_seen:
            _fail("no endpoint resolved the guid — is --column-guid a logical column?")

        # --- Step 3: op 7 known-broken -------------------------------------
        print("\nStep 3  op 7 (pinboard) — asserting KNOWN-BROKEN 500")
        if pinboard_guid:
            status, _ = _curl(["-b", str(jar), "-G", f"{v1}/dependency/pinboard",
                               "--data-urlencode", f"id={json.dumps([pinboard_guid])}"], verify)
            if status == 500:
                print("  PASS  500 as documented (open item #11)")
            else:
                print(f"  WARN  returned {status}, not 500 — the skill's status table "
                      "may be STALE; re-verify open item #11")
        else:
            print("  SKIP  no --pinboard-guid given")

        # --- Step 4: op 8 preview (non-destructive) ------------------------
        print("\nStep 4  op 8 preview (apply_changes=false) — non-destructive")
        preview_args = ["-b", str(jar), "-X", "POST", f"{dep}/delete-with-dependents",
                        "--data-urlencode", "type=LOGICAL_COLUMN",
                        "--data-urlencode", f"id={id_arg}",
                        "--data-urlencode", "operation_type=DELETE_OBJECT_CASCADE",
                        "--data-urlencode", "apply_changes=false"]
        status, body = _curl(preview_args, verify)
        preview_ids: set[str] = set()
        if status == 200:
            parsed = json.loads(body)
            if "dependents" not in parsed or "csv" not in parsed:
                _fail("200 preview missing 'dependents' or 'csv' key")
            objs = parsed["dependents"].get(column_guid, [])
            preview_ids = {o["id"] for o in objs}
            print(f"  PASS  200, cascade = {len(preview_ids)} object(s), csv present")
        elif status == 400 and "METADATA_ERROR" in body:
            detail = json.loads(body).get("details", "").replace("\n", " ")
            print(f"  PASS  400 business-rule refusal (normal — open item #18): {detail[:120]}")
            if run_delete:
                print("  NOTE  --run-delete is moot: the API refuses this column")
                run_delete = False
        else:
            _fail(f"preview returned {status}: {body[:200]}")

        # --- Step 5: op 8 apply (DESTRUCTIVE, opt-in) ----------------------
        print("\nStep 5  op 8 apply (apply_changes=true) — DESTRUCTIVE")
        if not run_delete:
            print("  SKIP  --run-delete not set; nothing was deleted")
        else:
            apply_args = preview_args[:-1] + ["apply_changes=true"]
            status, body = _curl(apply_args, verify)
            if status != 200:
                _fail(f"apply returned {status}: {body[:200]}")
            objs = json.loads(body)["dependents"].get(column_guid, [])
            applied_ids = {o["id"] for o in objs}
            print(f"  PASS  200, deleted {len(applied_ids)} object(s)")
            for o in sorted(objs, key=lambda x: (x.get("type", ""), x.get("name") or "")):
                print(f"          {o.get('type'):22} {o.get('name')}  {o.get('id')}")
            extra = applied_ids - preview_ids
            if extra:
                print(f"  WARN  {len(extra)} object(s) deleted that the preview did not "
                      f"list — open item #19 regression:")
                for g in sorted(extra):
                    print(f"          {g}")
            status, body = _curl(["-b", str(jar), "-G", f"{v1}/dependency/logicalcolumn",
                                  "--data-urlencode", f"id={id_arg}"], verify)
            if json.loads(body).get(column_guid) not in ({}, None):
                _fail("post-delete lookup still reports dependents")
            print("  PASS  post-delete lookup confirms the column is gone")

        print("\nSmoke test PASSED")
    finally:
        # --- Step 6: cleanup ----------------------------------------------
        if jar.exists():
            jar.unlink()
        try:
            jar.parent.rmdir()
        except OSError:
            pass
        print("Step 6  cookie jar deleted")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ts-profile", required=True)
    ap.add_argument("--column-guid", required=True,
                    help="a LOGICAL_COLUMN guid (36 chars)")
    ap.add_argument("--pinboard-guid", help="optional: exercises the op-7 500 assertion")
    ap.add_argument("--run-delete", action="store_true",
                    help="DESTRUCTIVE: actually apply the cascade delete")
    args = ap.parse_args()
    if len(args.column_guid) != GUID_LEN:
        _fail(f"--column-guid must be {GUID_LEN} chars, got {len(args.column_guid)}")
    run_smoke_test(args.ts_profile, args.column_guid, args.pinboard_guid, args.run_delete)


if __name__ == "__main__":
    main()
