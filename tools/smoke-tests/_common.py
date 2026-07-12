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
            "Run /ts-profile-snowflake to create a profile."
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


def snow_json_file(snow_cmd: str, cli_connection: str, sql: str) -> list[dict]:
    """
    Like snow_json but writes SQL to a temp file and uses -f instead of -q.
    Required for SQL that embeds multiline content (e.g. YAML in CALL statements)
    where shell quoting via -q is unreliable.

    Note: the snow CLI's --format json swallows EXPRESSION_ERROR messages from CALL
    statements (returns empty stdout+stderr with RC=1). When that happens we re-run
    without --format json to recover the actual error text for the exception message.
    """
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as f:
        f.write(sql)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [snow_cmd, "sql", "-c", cli_connection, "--format", "json", "-f", tmp_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            error_detail = result.stderr.strip() or result.stdout.strip()
            if not error_detail:
                # --format json silently drops CALL/EXPRESSION_ERROR messages.
                # Re-run without --format json to recover the human-readable error.
                fallback = subprocess.run(
                    [snow_cmd, "sql", "-c", cli_connection, "-f", tmp_path],
                    capture_output=True, text=True,
                )
                error_detail = fallback.stderr.strip() or fallback.stdout.strip()
                # Trim the echoed SQL from the output — keep only from "exception" onwards
                for marker in ("Exception message:", "exception of type", "SQL compilation error"):
                    idx = error_detail.lower().find(marker.lower())
                    if idx != -1:
                        error_detail = error_detail[idx:].strip()
                        break
                if not error_detail:
                    error_detail = "(no error detail available — try running with snow sql --debug)"
            raise RuntimeError(f"snow sql failed:\n{error_detail}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"snow sql returned non-JSON:\n{result.stdout[:300]}"
            ) from e
    finally:
        os.unlink(tmp_path)


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


def ts_snowflake_exec(
    sf_profile: str,
    *,
    file: str | Path | None = None,
    query: str | None = None,
    variables: dict[str, str] | None = None,
) -> dict:
    """
    Run `ts snowflake exec` (ts-cli >= 0.48.0) and return its parsed JSON stdout.

    This is the same runtime path the ts-recipe-formula-*-snowflake skills use to
    deploy and verify their UDFs, so the smoke tests exercise the real command
    (and the single-source `references/*.sql` templates) rather than a
    re-implemented `snow sql` deploy. Works with both `python` and `cli` profile
    methods. Raises RuntimeError on non-zero exit or non-JSON output.
    """
    cmd = ["ts", "snowflake", "exec", "--sf-profile", sf_profile]
    if file is not None:
        cmd += ["-f", str(file)]
    if query is not None:
        cmd += ["-q", query]
    for k, v in (variables or {}).items():
        cmd += ["--var", f"{k}={v}"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ts snowflake exec failed:\n{result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"ts snowflake exec returned non-JSON:\n{result.stdout[:300]}"
        ) from e


def ts_snowflake_scalar(sf_profile: str, query: str) -> Any:
    """Run a single-query `ts snowflake exec -q` and return the first column of the
    first row (the top-level `rows` convenience field)."""
    data = ts_snowflake_exec(sf_profile, query=query)
    rows = data.get("rows", [])
    if not rows:
        raise RuntimeError(f"Query returned no rows: {query}")
    return list(rows[0].values())[0]


def ts_snowflake_drop_udfs(sf_profile: str, signatures: list[str]) -> None:
    """
    Best-effort `DROP FUNCTION IF EXISTS` for each fully-qualified signature
    (e.g. `DB.SCHEMA.my_udf(TIMESTAMP, TIMESTAMP)`), via `ts snowflake exec`.
    Failures are swallowed — this is cleanup, not a test assertion.
    """
    for sig in signatures:
        try:
            ts_snowflake_exec(sf_profile, query=f"DROP FUNCTION IF EXISTS {sig}")
        except Exception:
            pass  # best-effort cleanup


def recipe_arg_parser(description: str):
    """
    Build the argparse.ArgumentParser shared by every ts-recipe-formula-*-snowflake
    smoke test: --sf-profile/--sf-target-db/--sf-target-schema (required),
    --ts-profile (accepted but ignored — runner compatibility), --no-cleanup.
    """
    import argparse
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--sf-profile", required=True,
                        help="Snowflake CLI profile name from ~/.claude/snowflake-profiles.json")
    parser.add_argument("--sf-target-db", required=True,
                        help="Snowflake database to create UDFs in")
    parser.add_argument("--sf-target-schema", required=True,
                        help="Snowflake schema to create UDFs in")
    parser.add_argument("--ts-profile", default=None,
                        help="Ignored — accepted for runner compatibility")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Skip the DROP FUNCTION cleanup step")
    return parser


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


# ---------------------------------------------------------------------------
# Databricks connection helpers
# ---------------------------------------------------------------------------

_DBX_PROFILES_PATH = Path.home() / ".claude" / "databricks-profiles.json"


def load_dbx_profile(profile_name: str) -> dict:
    """Load a Databricks profile from ~/.claude/databricks-profiles.json."""
    if not _DBX_PROFILES_PATH.exists():
        raise RuntimeError(
            f"No Databricks profiles file found at {_DBX_PROFILES_PATH}. "
            "Run /ts-profile-databricks to create a profile."
        )

    profiles = json.loads(_DBX_PROFILES_PATH.read_text(encoding="utf-8"))
    if isinstance(profiles, dict) and "profiles" in profiles:
        profiles = profiles["profiles"]

    for p in profiles:
        if p.get("name") == profile_name:
            return p

    available = [p.get("name") for p in profiles]
    raise RuntimeError(
        f"Databricks profile '{profile_name}' not found. "
        f"Available profiles: {available}"
    )


def get_dbx_warehouse_id(profile: dict) -> str:
    """Extract the warehouse ID from a Databricks profile's sql_warehouse_http_path."""
    path = profile.get("sql_warehouse_http_path", "")
    if not path:
        raise RuntimeError("Profile has no sql_warehouse_http_path configured")
    return path.rstrip("/").split("/")[-1]


# Databricks statement-execution states (Statement Execution API). Any state
# not in this terminal set (i.e. PENDING, RUNNING) must keep polling — treating
# only PENDING as "keep polling" let a RUNNING initial response return early
# with empty results, and treating only SUCCEEDED/FAILED as "stop polling" let
# CANCELED/CLOSED burn the full timeout before erroring (audit 4.8, recurrence
# of a prior-audit finding).
_DBX_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELED", "CLOSED"}


def _raise_if_unsuccessful(data: dict) -> None:
    """Raise if a terminal statement-execution state indicates non-success."""
    status = data.get("status", {})
    state = status.get("state")
    if state == "FAILED":
        err = status.get("error", {}).get("message", "unknown error")
        raise RuntimeError(f"SQL statement failed: {err}")
    if state in ("CANCELED", "CLOSED"):
        raise RuntimeError(f"SQL statement ended in state {state} without succeeding")


def databricks_sql(dbx_profile_name: str, statement: str) -> dict:
    """
    Execute a SQL statement via the Databricks SQL Statement Execution API.
    Returns the full response dict. Raises RuntimeError on CLI failure.

    Polls while the statement is in a non-terminal state (PENDING, RUNNING) —
    the synchronous POST can return before the statement finishes even within
    its wait_timeout window. Stops as soon as a terminal state (SUCCEEDED,
    FAILED, CANCELED, CLOSED) is observed instead of only recognizing PENDING
    on entry (which let a RUNNING initial response return early with empty
    results) and only recognizing SUCCEEDED/FAILED while polling (which let
    CANCELED/CLOSED burn the full timeout before erroring).
    """
    profile = load_dbx_profile(dbx_profile_name)
    wh_id = get_dbx_warehouse_id(profile)
    cli_profile = profile["dbx_profile"]

    payload = json.dumps({
        "warehouse_id": wh_id,
        "statement": statement,
        "wait_timeout": "50s",
    })

    result = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/sql/statements",
         "--profile", cli_profile, "--json", payload],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"databricks api post failed:\n{result.stderr.strip() or result.stdout.strip()}"
        )

    data = json.loads(result.stdout)
    state = data.get("status", {}).get("state")

    if state not in _DBX_TERMINAL_STATES:
        import time
        stmt_id = data.get("statement_id")
        for _ in range(12):
            time.sleep(5)
            poll = subprocess.run(
                ["databricks", "api", "get",
                 f"/api/2.0/sql/statements/{stmt_id}",
                 "--profile", cli_profile],
                capture_output=True, text=True,
            )
            if poll.returncode != 0:
                raise RuntimeError(f"Poll failed:\n{poll.stderr.strip()}")
            data = json.loads(poll.stdout)
            state = data.get("status", {}).get("state")
            if state in _DBX_TERMINAL_STATES:
                break
        else:
            raise RuntimeError("SQL statement timed out after 60s")

    _raise_if_unsuccessful(data)
    return data


def dbx_sql_rows(dbx_profile_name: str, statement: str) -> list[list]:
    """Execute SQL and return just the data_array rows."""
    data = databricks_sql(dbx_profile_name, statement)
    return data.get("result", {}).get("data_array", [])
