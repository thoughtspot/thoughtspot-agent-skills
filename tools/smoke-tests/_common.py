"""
_common.py — shared utilities for smoke tests.

Handles:
  - ThoughtSpot profile resolution (via ts CLI subprocess calls)
  - Snowflake connection loading (from ~/.claude/snowflake-profiles.json)
  - Consistent PASS/FAIL/SKIP step reporting
  - Cleanup registries
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Step reporter
# ---------------------------------------------------------------------------

PASS = "\033[32m[PASS]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"
SKIP = "\033[33m[SKIP]\033[0m"
INFO = "      "


class SmokeTestResult:
    def __init__(self):
        self.failures: list[str] = []
        self.skipped: list[str] = []

    def step(self, label: str, fn: Callable, *args, **kwargs) -> tuple[bool, Any]:
        """Run a step, print result, accumulate failures."""
        print(f"  {label}...", end=" ", flush=True)
        try:
            result = fn(*args, **kwargs)
            print(PASS)
            return True, result
        except SkipStep as e:
            print(f"{SKIP}  {e}")
            self.skipped.append(label)
            return False, None
        except Exception as e:
            print(f"{FAIL}  {e}")
            self.failures.append(f"{label}: {e}")
            return False, None

    def info(self, msg: str) -> None:
        print(f"{INFO}{msg}")

    def passed(self) -> bool:
        return len(self.failures) == 0

    def summary(self) -> int:
        print()
        if self.failures:
            print(f"  {len(self.failures)} step(s) failed:")
            for f in self.failures:
                print(f"    {FAIL} {f}")
            return 1
        if self.skipped:
            print(f"  {len(self.skipped)} step(s) skipped.")
        print("  All required steps passed.")
        return 0


class SkipStep(Exception):
    """Raise to skip a step without failing the test."""
    pass


# ---------------------------------------------------------------------------
# ThoughtSpot CLI helpers
# ---------------------------------------------------------------------------

def run_ts(args: list[str], profile: str) -> dict | list:
    """
    Run a ts CLI command and return parsed JSON.
    Raises RuntimeError on non-zero exit.
    """
    cmd = ["ts"] + args + ["--profile", profile]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ts {' '.join(args)} failed:\n{result.stderr.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"ts {' '.join(args)} returned non-JSON output:\n{result.stdout[:200]}"
        ) from e


def ts_auth_check(profile: str) -> dict:
    """Verify ts CLI auth works. Returns whoami dict."""
    data = run_ts(["auth", "whoami"], profile)
    if not isinstance(data, dict):
        raise RuntimeError("Expected JSON object from ts auth whoami")
    return data


# ---------------------------------------------------------------------------
# Snowflake connection helpers
# ---------------------------------------------------------------------------

_SF_PROFILES_PATH = Path.home() / ".claude" / "snowflake-profiles.json"


def load_sf_profile(profile_name: str) -> dict:
    """
    Load a Snowflake profile from ~/.claude/snowflake-profiles.json.

    Supports both the list format and the wrapped {'profiles': [...]} format
    written by the snowflake-profile-setup skill.
    """
    if not _SF_PROFILES_PATH.exists():
        raise RuntimeError(
            f"No Snowflake profiles file found at {_SF_PROFILES_PATH}. "
            "Run /snowflake-profile-setup to create a profile."
        )

    raw = json.loads(_SF_PROFILES_PATH.read_text(encoding="utf-8"))

    if isinstance(raw, dict) and "profiles" in raw:
        profiles = raw["profiles"]
    elif isinstance(raw, list):
        profiles = raw
    else:
        raise RuntimeError(f"Unexpected format in {_SF_PROFILES_PATH}")

    for p in profiles:
        if p.get("name") == profile_name:
            return p

    available = [p.get("name") for p in profiles]
    raise RuntimeError(
        f"Snowflake profile '{profile_name}' not found. "
        f"Available profiles: {available}"
    )


def get_snow_cmd(profile: dict) -> str:
    """Return the snow CLI command path stored in a profile, defaulting to 'snow'."""
    return profile.get("snow_cmd") or "snow"


def snow_json(snow_cmd: str, cli_connection: str, query: str) -> list[dict]:
    """
    Execute a SQL query via the Snowflake CLI and return the result as a list of dicts.
    Uses JSON output format for reliable parsing.
    """
    result = subprocess.run(
        [snow_cmd, "sql", "-c", cli_connection, "--format", "json", "-q", query],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"snow sql failed:\n{result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"snow sql returned non-JSON:\n{result.stdout[:300]}"
        ) from e


def snow_exec(snow_cmd: str, cli_connection: str, sql: str) -> None:
    """
    Execute one or more SQL statements via the Snowflake CLI.
    Use for DDL/DML where output is not needed.
    """
    result = subprocess.run(
        [snow_cmd, "sql", "-c", cli_connection, "-q", sql],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"snow sql failed:\n{result.stderr.strip() or result.stdout.strip()}"
        )


def snow_file(snow_cmd: str, cli_connection: str, sql_file: str) -> None:
    """Execute SQL from a file via the Snowflake CLI."""
    result = subprocess.run(
        [snow_cmd, "sql", "-c", cli_connection, "-f", sql_file],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"snow sql -f {sql_file} failed:\n{result.stderr.strip() or result.stdout.strip()}"
        )


def sf_connect_python(profile: dict) -> Any:
    """
    Return a snowflake.connector connection for a 'python' method profile.
    Falls back if snowflake-connector-python is not installed.
    """
    try:
        import snowflake.connector
    except ImportError:
        raise RuntimeError(
            "snowflake-connector-python is required for Python-method Snowflake profiles. "
            "Install with: pip install snowflake-connector-python"
        )

    kwargs = {
        "account": profile["account"],
        "user": profile["user"],
        "warehouse": profile.get("warehouse"),
        "role": profile.get("role"),
        "database": profile.get("database"),
        "schema": profile.get("schema"),
    }

    # Resolve credential from env var
    import os
    cred_env = profile.get("password_env") or profile.get("token_env") or profile.get("secret_key_env")
    if cred_env:
        cred_value = os.environ.get(cred_env)
        if not cred_value:
            raise RuntimeError(
                f"Environment variable '{cred_env}' is not set. "
                "Check your ~/.zshenv export and ensure it is sourced."
            )
        if profile.get("password_env"):
            kwargs["password"] = cred_value
        elif profile.get("token_env"):
            kwargs["token"] = cred_value
        elif profile.get("secret_key_env"):
            kwargs["private_key_path"] = profile.get("private_key_path")
            kwargs["private_key_passphrase"] = cred_value

    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    return snowflake.connector.connect(**kwargs)
