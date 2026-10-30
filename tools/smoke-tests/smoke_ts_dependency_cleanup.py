#!/usr/bin/env python3
"""
smoke_ts_dependency_cleanup.py — live smoke test for ts-dependency-cleanup.

The skill drives the v1 `/dependency/*` family directly over HTTP with a
session-login cookie (there is no `ts dependency` CLI surface for these
endpoints — see the skill's "Why raw REST" section and open item #6), so this
test exercises the same raw calls the skill makes. Operation 8's backup and
rollback go through `ts dependency backup` / `rollback`, exactly as in the skill.

  1.  v1 session login              — POST session/login (password on stdin)
      -> cookie jar, then session/info to confirm the cookie is usable.
  2.  Read-only lookups (ops 2-6)   — NON-destructive, always run. Confirms the
      GET verb, the JSON-array `id` form, and the documented response shape,
      including the two distinct empty forms: `{"<guid>":{}}` (0 dependents)
      vs `{}` (GUID is not of the endpoint's type).
  3.  Op 7 (pinboard)               — asserts the KNOWN-BROKEN 500. This step
      passes when the endpoint fails; if it ever returns 200 the skill's status
      table is stale and should be updated (open item #11).
  4.  Op 8 preview                  — NON-destructive. `apply_changes=false`
      against --column-guid. Validates the 200 shape (`dependents` + `csv`) and
      reports the cascade size. Asserts open item #19's property: every object
      the op-2 lookup reports must be in the preview (the lookup under-reports).
      A `400 METADATA_ERROR` is recorded as a normal business-rule refusal, not
      a test failure (open item #18).
  5.  Op 8 apply                    — DESTRUCTIVE and IRREVERSIBLE on the server.
      Gated behind --run-delete (default OFF), which must be run BY HAND:
        * run_smoke_tests.py refuses to pass it, so it cannot fire from a gate,
          and argparse abbreviations are off, so `--run-d` cannot sneak past;
        * --source-guid / --source-type (the column's owning Table or Model)
          are required, because the backup needs them;
        * the preview cascade must be <= --max-cascade (default 3);
        * `ts dependency backup` must succeed (SKILL.md 8b);
        * a re-run of the preview must match the backup exactly (SKILL.md 8d);
        * stdin must be a TTY and the operator must type DELETE.
      Then it records the applied CSV durably, fails on any object deleted
      without a backup, and confirms the lookup is now empty.
  6.  Op 8 rollback                 — --run-rollback (needs --run-delete).
      `ts dependency rollback` on the step-5 backup. Fails on a non-zero exit or
      any `failed[]` entry, then exports every restored object and fails if
      one still names a GUID that was deleted (open item #20: the GUID remap).
  7.  Cleanup                       — logs the session out and deletes the
      cookie jar (a live credential).

Purge is deliberately NOT exercised and is not part of the skill: its scope is
unverified and may be instance-wide over everything soft-deleted (open item #8).

Safety tiers: Steps 1-4 and 7 never modify data and always run. Steps 5 and 6
are the only writing legs, and both are manual-only.

Usage:
    python tools/smoke-tests/smoke_ts_dependency_cleanup.py \
        --ts-profile <profile> \
        --column-guid <logical-column-guid> \
        [--pinboard-guid <guid>]     # optional: exercises the op-7 500 assertion
        [--run-delete --source-guid <owning-table-or-model-guid> --source-type TABLE|MODEL]
        [--run-rollback]             # restore the step-5 backup and verify it
        [--max-cascade N]            # refuse --run-delete above N objects (default 3)

Credentials: the profile in ~/.claude/thoughtspot-profiles.json names an env var
(`password_env`); the secret itself lives in the OS keychain and must already be
exported into the calling shell. This test never prints it and never puts it on
a command line.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROFILES = Path.home() / ".claude" / "thoughtspot-profiles.json"
GUID_LEN = 36
DEFAULT_MAX_CASCADE = 3
CURL_TIMEOUT = ["--connect-timeout", "15", "--max-time", "120"]
# Durable, outside the repo: the applied CSV and the backup are the record of an
# irreversible delete.
RECORD_DIR = Path.home() / ".ts-dependency-cleanup" / "smoke-deletes"

# Preview dependentType (or LOGICAL_TABLE subtype) -> backup plan type (SKILL.md 8b).
BACKUP_TYPE = {
    "PINBOARD_ANSWER_BOOK": "LIVEBOARD",
    "QUESTION_ANSWER_BOOK": "ANSWER",
    "WORKSHEET": "MODEL",
    "SQL_VIEW": "SQL_VIEW",
    "AGGR_WORKSHEET": "VIEW",
    "ONE_TO_ONE_LOGICAL": "TABLE",
}


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


def _curl(args: list[str], verify_ssl: bool, stdin: str | None = None,
          timeout: list[str] = CURL_TIMEOUT) -> tuple[int, str]:
    """Run curl, returning (http_status, body). Never echoes credentials; a secret
    goes in through `stdin`, never through `args`."""
    cmd = ["curl", "-sS", "-w", "\n%{http_code}", *timeout]
    if not verify_ssl:
        cmd.append("-k")
    cmd += args
    res = subprocess.run(cmd, capture_output=True, text=True, input=stdin)
    if res.returncode != 0:
        return 0, res.stderr.strip()
    out = res.stdout.rsplit("\n", 1)
    body = out[0] if len(out) == 2 else ""
    try:
        status = int(out[-1].strip())
    except ValueError:
        status = 0
    return status, body


def _ts(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["ts", *args], capture_output=True, text=True, input=stdin)


def _ids(objs: list) -> set[str]:
    return {o["id"] for o in objs if isinstance(o, dict) and o.get("id")}


def _lookup_ids(parsed: dict, guid: str) -> set[str]:
    """Flatten an op 1-6 response ({guid: {BUCKET: [header, ...]}}) to dependent ids."""
    out: set[str] = set()
    for bucket in (parsed.get(guid) or {}).values():
        out |= _ids(bucket)
    return out


def _backup_type(obj: dict) -> str:
    t = obj.get("type", "")
    if t == "LOGICAL_TABLE":
        t = obj.get("type_subtype") or obj.get("subType") or ""
    if t not in BACKUP_TYPE:
        _fail(f"unrecognised dependent type {obj.get('type')}/{t} for {obj.get('id')} — "
              "SKILL.md 8b says stop; extend BACKUP_TYPE only after checking it")
    return BACKUP_TYPE[t]


def _column_details(jar: Path, v1: str, id_arg: str, verify: bool) -> tuple[int, bool]:
    """(status, has_storables) for the column's metadata/details (open item #23)."""
    status, body = _curl(["-b", str(jar), "-G", f"{v1}/metadata/details",
                          "--data-urlencode", "type=LOGICAL_COLUMN",
                          "--data-urlencode", f"id={id_arg}"], verify)
    return status, status == 200 and bool(json.loads(body or "{}").get("storables"))


def _require_ts_version(minimum: tuple[int, ...] = (0, 192, 0)) -> None:
    """Step 6's rollback needs 0.192.0's GUID remap: check before anything is deleted."""
    res = subprocess.run(["ts", "--version"], capture_output=True, text=True)
    try:
        have = tuple(int(x) for x in res.stdout.strip().split("."))
    except ValueError:
        have = ()
    if res.returncode != 0 or have < minimum:
        _fail(f"ts {res.stdout.strip() or '(no --version)'} is older than "
              f"{'.'.join(map(str, minimum))}; nothing was deleted")


def _take_backup(profile: str, source_guid: str, source_type: str, objs: list) -> Path:
    plan = {
        "operation": "REMOVE",
        "source": {"guid": source_guid, "type": source_type, "name": "smoke source"},
        "source_deleted": False,
        "delete": [{"guid": o["id"], "type": _backup_type(o), "name": o.get("name") or o["id"]}
                   for o in objs],
        "out_dir": str(RECORD_DIR),
    }
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    res = _ts(["dependency", "backup", "--profile", profile], stdin=json.dumps(plan))
    if res.returncode != 0:
        _fail(f"ts dependency backup failed — nothing was deleted: {res.stderr.strip()[-300:]}")
    manifest = json.loads(res.stdout)
    if len(manifest["objects"]) != 1 + len(objs):
        _fail(f"backup holds {len(manifest['objects'])} entries, expected {1 + len(objs)}")
    return Path(manifest["objects"][0]["backup_file"]).parent


def _verify_rollback(profile: str, backup_dir: Path) -> None:
    res = _ts(["dependency", "rollback", "--backup-dir", str(backup_dir), "--profile", profile])
    try:
        result = json.loads(res.stdout)
    except json.JSONDecodeError:
        _fail(f"rollback printed no JSON (exit {res.returncode}): {res.stderr.strip()[-300:]}")
    if res.returncode != 0 or result.get("failed"):
        _fail(f"rollback exit {res.returncode}, failed: {result.get('failed')}")
    new_guids = result.get("new_guids") or {}
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    deleted = {o["guid"] for o in manifest["objects"] if o["intent"] == "DELETE"}
    if set(new_guids) != deleted:
        _fail(f"rollback re-created {len(new_guids)} object(s), backup holds {len(deleted)}")
    print(f"  PASS  rollback exit 0, {len(new_guids)} object(s) re-created")
    for old, new in sorted(new_guids.items()):
        exp = _ts(["tml", "export", new, "--fqn", "--profile", profile])
        if exp.returncode != 0:
            _fail(f"restored object {new} (was {old}) cannot be exported")
        stale = sorted(g for g in deleted if g in exp.stdout)
        if stale:
            _fail(f"restored {new} still references deleted GUID(s) {stale} — remap failed")
    print("  PASS  every restored object exports and names only live GUIDs (#20)")


def run_smoke_test(profile_name: str, column_guid: str, pinboard_guid: str | None,
                   run_delete: bool, max_cascade: int = DEFAULT_MAX_CASCADE,
                   source_guid: str | None = None, source_type: str | None = None,
                   run_rollback: bool = False) -> None:
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
    print(f"  rollback leg: {'ENABLED (--run-rollback)' if run_rollback else 'SKIPPED'}")

    jar = Path(tempfile.mkdtemp(prefix="ts_smoke_")) / "cookies.txt"
    logged_in = False
    try:
        # --- Step 1: login -------------------------------------------------
        print("\nStep 1  v1 session login")
        status, _ = _curl(["-c", str(jar), "-o", "/dev/null", "-X", "POST",
                           f"{v1}/session/login",
                           "--data-urlencode", f"username={prof['username']}",
                           "--data-urlencode", "password@-",
                           "--data-urlencode", "rememberme=false"], verify, stdin=secret)
        if status not in (200, 204):
            _fail(f"login returned {status} (expected 200/204)")
        logged_in = True
        jar.chmod(0o600)
        status, _ = _curl(["-b", str(jar), "-o", "/dev/null", f"{v1}/session/info"], verify)
        if status != 200:
            _fail(f"session/info returned {status} — cookie unusable")
        print("  PASS  logged in, cookie verified")

        # --- Step 2: read-only lookups -------------------------------------
        print("\nStep 2  read-only lookups (ops 2-6)")
        id_arg = json.dumps([column_guid])
        shape_seen = False
        lookup_ids: set[str] = set()
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
                if ep == "logicalcolumn":
                    lookup_ids = _lookup_ids(parsed, column_guid)
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
        preview_objs: list = []
        preview_ids: set[str] = set()
        if status == 200:
            parsed = json.loads(body)
            if "dependents" not in parsed or "csv" not in parsed:
                _fail("200 preview missing 'dependents' or 'csv' key")
            preview_objs = parsed["dependents"].get(column_guid, [])
            preview_ids = _ids(preview_objs)
            print(f"  PASS  200, cascade = {len(preview_ids)} object(s), csv present")
            # Open item #19: the lookup under-reports, so the preview must CONTAIN it.
            missing = lookup_ids - preview_ids
            if missing:
                _fail(f"preview omits {len(missing)} object(s) the op-2 lookup reports "
                      f"(open item #19 inverted): {sorted(missing)}")
            print(f"  PASS  #19 lookup {len(lookup_ids)} ⊆ preview {len(preview_ids)} "
                  f"— the lookup is not a blast radius")
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
        if run_delete and len(preview_ids) > max_cascade:
            print(f"  REFUSE  preview cascade is {len(preview_ids)} object(s), over "
                  f"--max-cascade {max_cascade}; nothing was deleted")
            run_delete = False
        if run_delete and not sys.stdin.isatty():
            print("  REFUSE  --run-delete needs an interactive terminal for the typed "
                  "DELETE confirmation; nothing was deleted")
            run_delete = False
        backup_dir: Path | None = None
        if run_delete:
            _require_ts_version()
            # Positive control for the post-delete check: a live column must show
            # `storables`, or an absent one later proves nothing (open item #23).
            status, live = _column_details(jar, v1, id_arg, verify)
            if not live:
                _fail(f"control: metadata/details for the live column returned {status} "
                      "without `storables`, so the post-delete check cannot be trusted "
                      "(open item #23); nothing was deleted")
            print("  PASS  control: metadata/details shows the live column")
            backup_dir = _take_backup(profile_name, source_guid, source_type, preview_objs)
            print(f"  PASS  backup written to {backup_dir}")
            print(f"  About to IRREVERSIBLY delete {len(preview_ids)} object(s) plus "
                  f"column {column_guid}:")
            for g in sorted(preview_ids):
                print(f"          {g}")
            if input("  Type DELETE to apply, anything else to cancel: ") != "DELETE":
                print("  CANCELLED  nothing was deleted")
                run_delete = False
        if run_delete:
            # SKILL.md 8c -> 8d: re-check after the typed confirmation, immediately before
            # applying, so the cascade cannot grow while the operator types.
            status, body = _curl(preview_args, verify)
            recheck = _ids(json.loads(body)["dependents"].get(column_guid, [])) \
                if status == 200 else None
            if recheck != preview_ids:
                _fail(f"re-check does not match the backup (status {status}); nothing "
                      f"was deleted. Not backed up: {sorted((recheck or set()) - preview_ids)}")
            print("  PASS  pre-apply re-check matches the backup")
        if not run_delete:
            print("  SKIP  delete leg not run; nothing was deleted")
        else:
            apply_args = preview_args[:-1] + ["apply_changes=true"]
            status, body = _curl(apply_args, verify,
                                 timeout=["--connect-timeout", "15", "--max-time", "600"])
            if status != 200:
                _fail(f"apply returned {status} — state UNKNOWN, do not re-send; re-run "
                      f"the preview to see what was deleted. Backup: {backup_dir}. {body[:200]}")
            applied = json.loads(body)
            record = RECORD_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{column_guid}.csv"
            record.write_text(applied.get("csv", ""))
            print(f"  RECORD  applied CSV kept at {record}")
            objs = applied["dependents"].get(column_guid, [])
            applied_ids = _ids(objs)
            print(f"  PASS  200, deleted {len(applied_ids)} object(s)")
            for o in sorted(objs, key=lambda x: (x.get("type", ""), x.get("name") or "")):
                print(f"          {o.get('type'):22} {o.get('name')}  {o.get('id')}")
            unbacked = applied_ids - preview_ids
            if unbacked:
                _fail(f"{len(unbacked)} object(s) deleted WITHOUT a backup: {sorted(unbacked)}")
            status, body = _curl(["-b", str(jar), "-G", f"{v1}/dependency/logicalcolumn",
                                  "--data-urlencode", f"id={id_arg}"], verify)
            if json.loads(body).get(column_guid) not in ({}, None):
                _fail("post-delete lookup still reports dependents")
            print("  PASS  post-delete lookup reports no dependents")
            # An empty lookup reads the same for a column that is gone and for one that
            # survived with no dependents left, so it cannot prove the delete. The
            # column's own details can, against the control taken before the delete.
            status, still = _column_details(jar, v1, id_arg, verify)
            if still:
                _fail("the column still exists after the delete (partial delete)")
            if status != 200:
                print(f"  WARN  metadata/details returned {status}; could not confirm the "
                      "column itself is gone — record this under open item #23")
            else:
                print("  PASS  metadata/details no longer shows the column (record the "
                      "response under open item #23)")

        # --- Step 6: rollback (opt-in, needs step 5) -----------------------
        print("\nStep 6  ts dependency rollback of the step-5 backup")
        if run_rollback and run_delete and backup_dir is not None:
            _verify_rollback(profile_name, backup_dir)
        else:
            print("  SKIP  rollback leg not run")

        print("\nSmoke test PASSED")
    finally:
        # --- Step 7: cleanup ----------------------------------------------
        if logged_in and jar.exists():
            _curl(["-b", str(jar), "-o", "/dev/null", "-X", "POST", f"{v1}/session/logout"],
                  verify)
        if jar.exists():
            jar.unlink()
        try:
            jar.parent.rmdir()
        except OSError:
            pass
        print("Step 7  session logged out, cookie jar deleted")


def main() -> None:
    # allow_abbrev=False: `--run-d` must not resolve to --run-delete, because the
    # runner's refusal matches the full flag name (PR #666 review).
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ts-profile", required=True)
    ap.add_argument("--column-guid", required=True,
                    help="a LOGICAL_COLUMN guid (36 chars)")
    ap.add_argument("--pinboard-guid", help="optional: exercises the op-7 500 assertion")
    ap.add_argument("--run-delete", action="store_true",
                    help="DESTRUCTIVE: back up, then actually apply the cascade delete "
                         "(manual runs only; needs a TTY and a typed DELETE)")
    ap.add_argument("--source-guid", help="with --run-delete: the Table or Model that owns "
                                          "the column (the backup's source)")
    ap.add_argument("--source-type", choices=("TABLE", "MODEL"),
                    help="with --run-delete: the type of --source-guid")
    ap.add_argument("--run-rollback", action="store_true",
                    help="with --run-delete: restore the backup and verify the restore")
    ap.add_argument("--max-cascade", type=int, default=DEFAULT_MAX_CASCADE,
                    help=f"refuse --run-delete when the preview lists more than this "
                         f"many objects (default {DEFAULT_MAX_CASCADE})")
    args = ap.parse_args()
    if len(args.column_guid) != GUID_LEN:
        _fail(f"--column-guid must be {GUID_LEN} chars, got {len(args.column_guid)}")
    if args.run_delete and not (args.source_guid and args.source_type):
        _fail("--run-delete needs --source-guid and --source-type: the backup cannot be "
              "taken without the column's owning object")
    if args.run_rollback and not args.run_delete:
        _fail("--run-rollback restores the --run-delete backup; pass both")
    run_smoke_test(args.ts_profile, args.column_guid, args.pinboard_guid, args.run_delete,
                   args.max_cascade, args.source_guid, args.source_type, args.run_rollback)


if __name__ == "__main__":
    main()
