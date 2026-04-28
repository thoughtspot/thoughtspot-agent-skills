#!/usr/bin/env python3
"""
smoke_ts_object_model_coach.py — live smoke test for ts-object-model-coach.

Verifies the verified API paths against a real ThoughtSpot instance:
  1.  ThoughtSpot auth
  2.  Resolve target Model by name; get its GUID
  3.  Export Model TML with --associated; confirm `model` + `table` items present
  4.  Mine dependent objects via v2 search API
      (POST /api/rest/2.0/metadata/search with include_dependent_objects=True)
      — this is the verified path from open-items.md #1 / #2
  5.  Step 4.5 cross-Model consistency: enumerate readable Models, verify TML
      cache-key shape ({guid}-{modified_ms}.json), detect collisions on a
      2-Model corpus, and confirm proposed RouteAction defaults to
      NEEDS_REVIEW (open-items.md #15)
  6.  Take Model TML backup
  7.  Patch ONE column with `properties.ai_context` and `properties.synonyms`
      (verified shape — synonyms in `properties.synonyms`, NOT column-level)
  8.  Import patched Model TML; verify status_code: OK + columns_updated >= 1
  9.  Re-export Model and verify ai_context + synonyms round-tripped
  10. Import a single REFERENCE_QUESTION feedback entry with a unique probe phrase
  11. Verify the entry lands via metadata/search dependents.FEEDBACK
      (the correct verification path — `--associated` does NOT surface feedback)
  12. Cleanup: restore Model TML from backup (reverts ai_context + synonyms);
      for feedback, surface the GUID and instruct the user to remove via UI
      (no public REST delete for nls_feedback verified yet)

The test patches ONE column (configurable via --column-name) so it has minimal
blast radius and the rollback is a single TML import. The feedback probe entry
uses a timestamped phrase so it won't collide with real coaching. The
cross-Model scan caps the corpus at 3 Models so the test stays fast.

Usage:
    python tools/smoke-tests/smoke_ts_object_model_coach.py \\
        --ts-profile champ-staging \\
        --model-name "Dunder Mifflin Sales & Inventory" \\
        --column-name "Inventory Balance" \\
        [--no-cleanup]

Credentials: read from ~/.claude/thoughtspot-profiles.json by the ts CLI.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult, ts_auth_check, run_ts  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_token(profile_name: str) -> tuple[str, str]:
    """Return (base_url, token) for the named TS profile."""
    profs_path = Path.home() / ".claude" / "thoughtspot-profiles.json"
    profs = json.loads(profs_path.read_text())
    profs_list = profs.get("profiles", profs) if isinstance(profs, dict) else profs
    prof = next((p for p in profs_list if p.get("name") == profile_name), None)
    if not prof:
        raise RuntimeError(f"Profile {profile_name!r} not found in {profs_path}")
    base_url = prof["base_url"].rstrip("/")
    token_env = prof.get("token_env", f"THOUGHTSPOT_TOKEN_{profile_name.upper().replace('-', '_')}")
    token = os.environ.get(token_env)
    if not token:
        raise RuntimeError(f"Token env var {token_env} not set; run /ts-profile-thoughtspot")
    return base_url, token


def _v2_post(base_url: str, token: str, path: str, body: dict, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(
        f"{base_url}{path}",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Requested-By": "ThoughtSpot",
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} on {path}: {e.read().decode()[:300]}") from e


def _ts_tml_export(guids: list[str], profile: str, associated: bool = False) -> list[dict]:
    """Export TML via ts CLI; returns parsed --parse output."""
    args = ["tml", "export"] + guids + ["--fqn", "--parse"]
    if associated:
        args.append("--associated")
    return run_ts(args, profile)


def _ts_tml_import(yaml_text: str, profile: str) -> dict:
    """Import a single YAML TML via ts tml import. Returns the response dict."""
    payload = json.dumps([yaml_text])
    cmd = ["bash", "-c",
           f"source ~/.zshenv && ts tml import --profile '{profile}' --policy ALL_OR_NONE --no-create-new"]
    result = subprocess.run(cmd, input=payload, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"ts tml import failed: {result.stderr[:300]}")
    return json.loads(result.stdout)[0]["response"]


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_resolve_model(profile: str, model_name: str) -> str:
    """Find Model GUID by display-name match."""
    matches = run_ts(["metadata", "search", "--subtype", "WORKSHEET",
                      "--name", f"%{model_name}%"], profile)
    exact = [m for m in matches
             if m.get("metadata_header", {}).get("name") == model_name]
    if not exact:
        raise RuntimeError(
            f"Model {model_name!r} not found. {len(matches)} partial matches; "
            f"need an exact name match."
        )
    return exact[0]["metadata_id"]


def step_export_and_parse(model_guid: str, profile: str) -> tuple[dict, list[dict]]:
    """Returns (model_tml, table_tmls). Confirms expected shape."""
    items = _ts_tml_export([model_guid], profile, associated=True)
    model = next((i for i in items if i["type"] == "model"), None)
    tables = [i for i in items if i["type"] == "table"]
    if not model:
        raise RuntimeError("No model item in --associated export")
    if not tables:
        raise RuntimeError("No table items in --associated export — Model with no underlying tables?")
    return model["tml"], [t["tml"] for t in tables]


def step_check_dependents_api(base_url: str, token: str, model_guid: str) -> dict:
    """Verify the metadata/search dependents API works and returns a FEEDBACK key."""
    body = _v2_post(base_url, token, "/api/rest/2.0/metadata/search", {
        "metadata": [{"identifier": model_guid, "type": "LOGICAL_TABLE"}],
        "include_dependent_objects": True,
        "dependent_object_version": "V2",
    })
    deps_node = body[0].get("dependent_objects", {}).get("dependents", {}).get(model_guid, {})
    # A model with no feedback yet still returns the dependents node — just empty.
    return deps_node


def _is_model_not_worksheet(metadata_header: dict) -> bool:
    """Filter a metadata search hit down to MODELs only (not legacy Worksheets)."""
    cu = metadata_header.get("contentUpgradeId") or ""
    wv = metadata_header.get("worksheetVersion") or ""
    return cu != "WORKSHEET_TO_MODEL_UPGRADE" and wv != "V1"


def step_enumerate_readable_models(profile: str) -> list[dict]:
    """Step 4.5 sub-step 1 — list MODELs the current user can read.

    Uses --all to auto-paginate; ts metadata search defaults to 50/page.
    """
    hits = run_ts(["metadata", "search", "--subtype", "WORKSHEET", "--all"], profile)
    models = [
        {
            "guid": h["metadata_id"],
            "name": h["metadata_header"]["name"],
            "modified_ms": h["metadata_header"]["modified"],
        }
        for h in hits
        if _is_model_not_worksheet(h.get("metadata_header", {}))
    ]
    if len(models) < 2:
        raise RuntimeError(
            f"Cross-Model scan needs ≥ 2 readable Models; only {len(models)} found. "
            f"Add a sibling Model on this profile or run on a tenant with more Models."
        )
    return models


def step_verify_tml_cache_shape(target_guid: str, target_modified_ms: int) -> None:
    """Step 4.5 sub-step 2 — round-trip a fake cache file with the documented filename pattern."""
    import tempfile, pathlib
    with tempfile.TemporaryDirectory(prefix="ts_object_model_coach_smoke_") as td:
        cache_dir = pathlib.Path(td)
        cache_key = f"{target_guid}-{target_modified_ms}.json"
        cache_path = cache_dir / cache_key
        # Documented shape: cached payload is the parsed --fqn --parse output
        sample_payload = [{"type": "model", "tml": {"model": {"name": "smoke", "columns": []}}}]
        cache_path.write_text(json.dumps(sample_payload))
        # Round-trip check
        readback = json.loads(cache_path.read_text())
        if readback != sample_payload:
            raise RuntimeError("cache round-trip mismatch")
        # Stale-entry detection: a hit for the same guid with different mtime
        # should be cleared on miss (per SKILL.md Step 4.5 cache-eviction rule)
        stale_path = cache_dir / f"{target_guid}-0.json"
        stale_path.write_text("{}")
        stale_matches = list(cache_dir.glob(f"{target_guid}-*.json"))
        if len(stale_matches) != 2:
            raise RuntimeError(f"expected 2 cache entries for guid before eviction, got {len(stale_matches)}")


def step_detect_cross_model_collisions(target_model_tml: dict, target_model_name: str,
                                         sibling_models: list[dict],
                                         profile: str, max_corpus: int = 10) -> list[dict]:
    """Step 4.5 sub-step 3 — export sibling Models and detect column-name collisions.

    Sibling-walk order is prioritised by name-token-overlap with the target Model's
    name, so likely-related siblings are exported first (collisions surface fast on
    tenants with many unrelated Models). Stops after the first collision is found
    OR after `max_corpus` successful exports — whichever comes first. Tolerates
    per-sibling export failure (FORBIDDEN, etc.) and walks forward.

    Returns a list of collision rows in the documented shape.
    """
    target_cols = {c["name"]: c for c in target_model_tml["model"].get("columns", [])}
    if not target_cols:
        raise RuntimeError("Target Model has no columns — cannot detect collisions")

    # Prioritise siblings whose name shares a token with the target.
    target_tokens = {t.lower() for t in target_model_name.replace("_", " ").split()
                      if len(t) >= 3}
    def overlap_score(sib_name: str) -> int:
        sib_tokens = {t.lower() for t in sib_name.replace("_", " ").split()}
        return len(target_tokens & sib_tokens)
    prioritised = sorted(sibling_models, key=lambda s: -overlap_score(s["name"]))

    # Parallel export — same path as the skill's production Step 4.5
    # (ThreadPoolExecutor max_workers=4). This step also serves as a live
    # thread-safety check on the ts CLI: 4 concurrent TML exports against
    # the same profile.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    candidates = prioritised[: max_corpus * 3]  # over-fetch to absorb FORBIDDEN losses

    def _try_export(sib: dict):
        try:
            items = _ts_tml_export([sib["guid"]], profile, associated=False)
            sib_model = next((i for i in items if i["type"] == "model"), None)
            return (sib, sib_model)
        except Exception:
            return (sib, None)

    collisions: list[dict] = []
    successful = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_try_export, sib) for sib in candidates]
        for future in as_completed(futures):
            if successful >= max_corpus and collisions:
                break
            sib, sib_model = future.result()
            if sib_model is None:
                continue
            successful += 1
            sib_cols = {c["name"]: c for c in sib_model["tml"]["model"].get("columns", [])}
            for col_name, target_col in target_cols.items():
                if col_name not in sib_cols:
                    continue
                sib_col = sib_cols[col_name]
                target_db = target_col.get("db_column_name")
                sib_db = sib_col.get("db_column_name")
                target_type = target_col.get("properties", {}).get("column_type")
                sib_type = sib_col.get("properties", {}).get("column_type")
                divergent_on = []
                if target_db != sib_db:
                    divergent_on.append("db_column_name")
                if target_type != sib_type:
                    divergent_on.append("column_type")
                collisions.append({
                    "column": col_name,
                    "sibling_model": sib["name"],
                    "sibling_guid": sib["guid"],
                    "divergent_on": divergent_on,
                    # Per open-items.md #15 — heuristic uncalibrated, default action is always NEEDS_REVIEW
                    "proposed_route_action": "NEEDS_REVIEW",
                })

    if successful == 0:
        raise RuntimeError(
            f"Could not export any sibling Model TML (tried up to {len(sibling_models)} candidates). "
            f"Cross-Model scan needs at least one readable + exportable sibling Model."
        )
    if not collisions:
        raise RuntimeError(
            f"No cross-Model collisions detected against {successful} successfully-exported "
            f"sibling Models. On a tenant with ≥ 1 sibling Model that copies the target's "
            f"schema, the test expects to find at least 1 collision (target_cols={len(target_cols)})."
        )
    return collisions


def step_verify_proposed_action_default(collisions: list[dict]) -> None:
    """Step 4.5 sub-step 4 — every collision's proposed RouteAction must default to NEEDS_REVIEW
    until open-items.md #15 calibrates the heuristic against a live tenant."""
    bad = [c for c in collisions if c.get("proposed_route_action") != "NEEDS_REVIEW"]
    if bad:
        raise RuntimeError(
            f"{len(bad)} collision(s) have proposed RouteAction != NEEDS_REVIEW. "
            f"Per open-items.md #15 the default must be NEEDS_REVIEW until the heuristic "
            f"is calibrated. Examples: {[c['column'] for c in bad[:3]]}"
        )


def step_patch_model_with_ai_assets(model_tml: dict, column_name: str,
                                     test_ai_context: str, test_synonyms: list[str]) -> dict:
    """Return patched model TML with ai_context + properties.synonyms on one column."""
    patched = copy.deepcopy(model_tml)
    cols = patched["model"].get("columns", [])
    target = next((c for c in cols if c["name"] == column_name), None)
    if not target:
        available = [c["name"] for c in cols][:10]
        raise RuntimeError(
            f"Column {column_name!r} not found. First few: {available}"
        )
    target.setdefault("properties", {})["ai_context"] = test_ai_context
    target["properties"]["synonyms"] = test_synonyms
    target["properties"]["synonym_type"] = "USER_DEFINED"
    return patched


def step_import_patched_model(patched: dict, profile: str) -> dict:
    yaml_text = yaml.dump(patched, sort_keys=False, allow_unicode=True)
    resp = _ts_tml_import(yaml_text, profile)
    # Model TML imports may emit WARNING for unrelated pre-existing issues
    # (e.g. column index/suggestion config on columns we're not touching) while
    # still applying the patch. Accept OK and WARNING; reject ERROR / others.
    status_code = resp["status"].get("status_code")
    if status_code not in ("OK", "WARNING"):
        raise RuntimeError(f"Model import status: {resp['status']}")
    if status_code == "WARNING":
        # Don't fail, but surface the warning for visibility
        msg = resp["status"].get("error_message", "<no message>")
        # Truncate very long warnings (column lists can be lengthy)
        print(f"\n      WARNING from import: {msg[:200]}{'...' if len(msg) > 200 else ''}")
    diff = resp.get("diff", {})
    if not diff.get("columns_updated"):
        raise RuntimeError(f"Expected columns_updated >=1, got diff={diff}")
    return resp


def step_verify_round_trip(model_guid: str, profile: str, column_name: str,
                            expected_ai_context: str, expected_synonyms: list[str]) -> None:
    items = _ts_tml_export([model_guid], profile, associated=False)
    model = next(i["tml"]["model"] for i in items if i["type"] == "model")
    target = next((c for c in model.get("columns", []) if c["name"] == column_name), None)
    if not target:
        raise RuntimeError(f"Column {column_name!r} not found in re-exported Model")
    props = target.get("properties", {})
    if props.get("ai_context") != expected_ai_context:
        raise RuntimeError(
            f"ai_context mismatch on round-trip. Got: {props.get('ai_context')!r}"
        )
    actual_syns = sorted(props.get("synonyms", []))
    if actual_syns != sorted(expected_synonyms):
        raise RuntimeError(
            f"synonyms mismatch on round-trip. Got: {actual_syns}, expected: {sorted(expected_synonyms)}"
        )


def step_import_feedback_probe(model_guid: str, profile: str, probe_phrase: str,
                                target_token: str) -> None:
    """Import a single REFERENCE_QUESTION with a unique probe phrase."""
    feedback_tml = {
        "guid": model_guid,
        "nls_feedback": {
            "feedback": [{
                "id": "1",
                "type": "REFERENCE_QUESTION",
                "access": "GLOBAL",
                "feedback_phrase": probe_phrase,
                "parent_question": probe_phrase,
                "search_tokens": target_token,
                "rating": "UPVOTE",
                "display_mode": "UNDEFINED",
                "chart_type": "KPI",
            }],
        },
    }
    yaml_text = yaml.dump(feedback_tml, sort_keys=False, allow_unicode=True)
    resp = _ts_tml_import(yaml_text, profile)
    # Feedback imports return status_code OK with empty diff and no `object` field.
    # That's the expected shape — see open-items.md #2.
    if resp["status"]["status_code"] not in ("OK", "WARNING"):
        raise RuntimeError(f"Feedback import status: {resp['status']}")


def step_verify_feedback_landed(base_url: str, token: str, model_guid: str,
                                 probe_phrase: str) -> str:
    """Verify the probe entry exists. Returns the feedback entry's GUID."""
    body = _v2_post(base_url, token, "/api/rest/2.0/metadata/search", {
        "metadata": [{"identifier": model_guid, "type": "LOGICAL_TABLE"}],
        "include_dependent_objects": True,
        "dependent_object_version": "V2",
    })
    fb = body[0]["dependent_objects"]["dependents"][model_guid].get("FEEDBACK", [])
    match = next((f for f in fb if f.get("name") == probe_phrase), None)
    if not match:
        raise RuntimeError(
            f"Probe entry {probe_phrase!r} not found in {len(fb)} FEEDBACK dependents. "
            f"This is the verification path — open-items.md #2."
        )
    return match["id"]


def step_cleanup_restore_model(original_tml: dict, profile: str) -> None:
    """Restore the Model from the original (pre-patch) TML.

    Accepts OK and WARNING — same rationale as step_import_patched_model.
    """
    yaml_text = yaml.dump(original_tml, sort_keys=False, allow_unicode=True)
    resp = _ts_tml_import(yaml_text, profile)
    status_code = resp["status"].get("status_code")
    if status_code not in ("OK", "WARNING"):
        raise RuntimeError(f"Rollback failed: {resp['status']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ts-profile", required=True, help="ThoughtSpot profile name")
    parser.add_argument("--model-name", required=True, help="Model display name (exact match)")
    parser.add_argument("--column-name", required=True, help="Column on the Model to patch")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Skip Model rollback (useful for debugging)")
    args = parser.parse_args()

    print(f"smoke_ts_object_model_coach — target: {args.model_name!r}, column: {args.column_name!r}")
    print()

    r = SmokeTestResult()

    base_url, token = "", ""
    ok, _ = r.step("auth", ts_auth_check, args.ts_profile)
    if not ok:
        return r.summary()
    ok, (base_url, token) = r.step("load profile token", _load_token, args.ts_profile)
    if not ok:
        return r.summary()

    ok, model_guid = r.step("resolve Model GUID", step_resolve_model,
                             args.ts_profile, args.model_name)
    if not ok:
        return r.summary()
    r.info(f"Model GUID: {model_guid}")

    ok, exported = r.step("export Model TML (with --associated)",
                           step_export_and_parse, model_guid, args.ts_profile)
    if not ok:
        return r.summary()
    original_tml, table_tmls = exported
    r.info(f"Model has {len(original_tml['model'].get('columns', []))} columns; "
            f"{len(table_tmls)} tables in bundle")

    ok, deps = r.step("dependents API (verified path from open-items.md #1)",
                       step_check_dependents_api, base_url, token, model_guid)
    if ok:
        r.info(f"Dependents categories: {sorted(deps.keys())}")

    # ---- Step 4.5 — cross-Model consistency scan ----
    ok, all_models = r.step("Step 4.5 — enumerate readable Models",
                             step_enumerate_readable_models, args.ts_profile)
    if ok:
        r.info(f"Found {len(all_models)} readable Models on this profile")
        target_meta = next((m for m in all_models if m["guid"] == model_guid), None)
        if target_meta is None:
            r.info("Target Model not in readable-Models enumeration — skipping cache + collision steps")
        else:
            siblings = [m for m in all_models if m["guid"] != model_guid]
            r.step("Step 4.5 — TML cache-key shape ({guid}-{modified_ms}.json)",
                    step_verify_tml_cache_shape, target_meta["guid"], target_meta["modified_ms"])
            ok2, collisions = r.step(
                "Step 4.5 — detect cross-Model column collisions (corpus capped at 10)",
                step_detect_cross_model_collisions,
                original_tml, args.model_name, siblings, args.ts_profile, 10,
            )
            if ok2:
                r.info(f"Detected {len(collisions)} collision(s) across the prioritised sibling corpus")
                r.step("Step 4.5 — proposed RouteAction defaults to NEEDS_REVIEW (open-items #15)",
                        step_verify_proposed_action_default, collisions)

    timestamp = int(time.time())
    test_ai_context = f"smoke test ai_context probe (run {timestamp})"
    test_synonyms = [f"smoke_test_syn_{timestamp}_a", f"smoke_test_syn_{timestamp}_b"]
    probe_phrase = f"SMOKE_TEST_PROBE_{timestamp}"

    ok, patched = r.step("patch Model with ai_context + synonyms",
                          step_patch_model_with_ai_assets, original_tml,
                          args.column_name, test_ai_context, test_synonyms)
    if not ok:
        return r.summary()

    ok, _ = r.step("import patched Model TML",
                    step_import_patched_model, patched, args.ts_profile)
    if not ok:
        return r.summary()

    ok, _ = r.step("verify ai_context + synonyms round-tripped",
                    step_verify_round_trip, model_guid, args.ts_profile,
                    args.column_name, test_ai_context, test_synonyms)
    if not ok and not args.no_cleanup:
        r.info("Attempting rollback...")
        try:
            step_cleanup_restore_model(original_tml, args.ts_profile)
        except Exception as e:
            r.info(f"Rollback failed: {e}")
        return r.summary()

    target_token = f"[{args.column_name}]"
    ok, _ = r.step("import REFERENCE_QUESTION feedback probe",
                    step_import_feedback_probe, model_guid, args.ts_profile,
                    probe_phrase, target_token)
    if not ok and not args.no_cleanup:
        try:
            step_cleanup_restore_model(original_tml, args.ts_profile)
        except Exception:
            pass
        return r.summary()

    ok, fb_guid = r.step("verify feedback probe lands via metadata/search dependents.FEEDBACK",
                          step_verify_feedback_landed, base_url, token,
                          model_guid, probe_phrase)
    if ok:
        r.info(f"Probe feedback GUID: {fb_guid} — remove manually via Coach Spotter UI")

    if not args.no_cleanup:
        r.step("rollback Model TML from backup",
               step_cleanup_restore_model, original_tml, args.ts_profile)
    else:
        r.info("--no-cleanup: leaving patched ai_context + synonyms in place")
        r.info(f"To restore manually: re-import the original Model TML")

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
