#!/usr/bin/env python3
"""
run_smoke_tests.py — run smoke tests for a list of skills.

Called by scripts/pre-push.sh. Reads skill names from stdin (one per line),
resolves their smoke test paths, and runs each one. Exits non-zero if any
test fails; skipped tests (needs config) do not cause failure.

Configuration:
  Copy tools/smoke-tests/smoke-config.local.json.example to
  tools/smoke-tests/smoke-config.local.json and fill in your values.
  This file is gitignored — it holds machine-specific args like model names
  and Snowflake connection details.

Profile resolution (first match wins):
  1. "default_ts_profile" in smoke-config.local.json
  2. TS_PROFILE environment variable
  3. First profile in ~/.claude/thoughtspot-profiles.json

Usage:
    echo "ts-variable-timezone" | python3 tools/validate/run_smoke_tests.py
    python3 tools/validate/run_smoke_tests.py --skills ts-variable-timezone
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

# Skills exempt from smoke tests (mirrors check_smoke_tests.py ALLOWLIST)
ALLOWLIST = {
    "ts-profile-thoughtspot",
    "ts-profile-snowflake",
    "ts-object-answer-promote",
}

# Skills whose smoke test file uses a non-default name
NAME_ALIASES: dict[str, str] = {
    "ts-convert-to-snowflake-sv":   "tools/smoke-tests/smoke_ts_to_snowflake.py",
    "ts-convert-from-snowflake-sv": "tools/smoke-tests/smoke_ts_from_snowflake.py",
    "ts-object-model-builder":      "tools/smoke-tests/smoke_ts_model_builder.py",
}

# Skills that need extra required args beyond --ts-profile.
# These must come from smoke-config.local.json; skills are skipped with a warning if absent.
# Use --model-guid (not --model-name) for stable, unambiguous model identification.
# Note: --column-name is optional for ts-object-model-coach (auto-selects first MEASURE column).
REQUIRED_EXTRA_ARGS: dict[str, list[str]] = {
    "ts-dependency-manager":        ["--model-guid"],
    "ts-object-model-coach":        ["--model-guid"],
    "ts-convert-to-snowflake-sv":   ["--sf-profile", "--sf-target-db", "--sf-target-schema"],
    "ts-convert-from-snowflake-sv": ["--sf-profile", "--sv-fqn"],
}

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"


def _load_config() -> dict:
    config_path = REPO_ROOT / "tools" / "smoke-tests" / "smoke-config.local.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


def _resolve_profile(config: dict) -> str | None:
    if config.get("default_ts_profile"):
        return config["default_ts_profile"]
    if os.environ.get("TS_PROFILE"):
        return os.environ["TS_PROFILE"]
    profiles_path = Path.home() / ".claude" / "thoughtspot-profiles.json"
    if profiles_path.exists():
        data = json.loads(profiles_path.read_text())
        profiles = data.get("profiles", data) if isinstance(data, dict) else data
        if profiles:
            return profiles[0]["name"]
    return None


def _smoke_test_path(skill: str) -> Path | None:
    if skill in NAME_ALIASES:
        p = REPO_ROOT / NAME_ALIASES[skill]
    else:
        p = REPO_ROOT / "tools" / "smoke-tests" / f"smoke_{skill.replace('-', '_')}.py"
    return p if p.exists() else None


def run(skills: list[str]) -> int:
    config = _load_config()
    profile = _resolve_profile(config)
    skill_configs = config.get("skills", {})

    failures: list[str] = []
    skipped: list[str] = []

    col = 42

    for skill in skills:
        label = f"  {skill}"

        if skill in ALLOWLIST:
            print(f"{label:<{col}} {SKIP}  (allowlisted — no smoke test required)")
            continue

        smoke_path = _smoke_test_path(skill)
        if smoke_path is None:
            print(f"{label:<{col}} {SKIP}  (no smoke test found)")
            skipped.append(skill)
            continue

        if not profile:
            print(f"{label:<{col}} {SKIP}  (no ThoughtSpot profile configured — "
                  f"set default_ts_profile in smoke-config.local.json or TS_PROFILE env var)")
            skipped.append(skill)
            continue

        # Build the argument list
        extra_required = REQUIRED_EXTRA_ARGS.get(skill, [])
        skill_cfg = skill_configs.get(skill, {})
        extra_args = skill_cfg.get("extra_args", [])

        # Per-skill profile overrides the default
        skill_profile = skill_cfg.get("ts_profile", profile)

        # Check all required extras are covered
        missing = [a for a in extra_required if a not in extra_args]
        if missing:
            print(f"{label:<{col}} {SKIP}  (needs {', '.join(missing)} — "
                  f"add to tools/smoke-tests/smoke-config.local.json)")
            skipped.append(skill)
            continue

        cmd = ["bash", "-c",
               f"source ~/.zshenv && python3 {smoke_path} "
               f"--ts-profile {skill_profile} {' '.join(extra_args)}"]

        print(f"{label:<{col}} ", end="", flush=True)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(PASS)
        else:
            print(FAIL)
            for line in result.stdout.splitlines():
                print(f"    {line}")
            if result.stderr.strip():
                for line in result.stderr.splitlines():
                    print(f"    {line}")
            failures.append(skill)

    if skipped:
        print(f"\n  {len(skipped)} skill(s) skipped — "
              f"configure in tools/smoke-tests/smoke-config.local.json to enable.")

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills", nargs="*", default=None,
                        help="Skill names to test. If omitted, reads from stdin.")
    args = parser.parse_args()

    if args.skills is not None:
        skills = args.skills
    else:
        skills = [line.strip() for line in sys.stdin if line.strip()]

    if not skills:
        return 0

    return run(skills)


if __name__ == "__main__":
    sys.exit(main())
