"""Shared I/O helpers for ts-cli command modules.

Stdlib only — no ThoughtSpot/platform deps.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def load_json_file(path: str | Path, label: str, *, expect_dict: bool = False) -> Any:
    """Read and parse a JSON file, raising SystemExit on error.

    Args:
        path: File path (str or Path).
        label: Human-readable label for error messages (e.g. "--parsed", "bundle").
        expect_dict: If True, also validate the parsed value is a dict.

    Returns:
        Parsed JSON value.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON in {label} ({path}): {exc}") from exc
    if expect_dict and not isinstance(data, dict):
        raise TypeError(f"{label} must be a JSON object: {path}")
    return data


def _clean_error_message(msg: str) -> str:
    """Strip HTML tags, collapse whitespace, and cap at ~1000 chars."""
    cleaned = _HTML_TAG_RE.sub(" ", msg or "")
    cleaned = " ".join(cleaned.split())
    return cleaned[:1000]


def _extract_status_error(import_result: list) -> Optional[str]:
    """Return a cleaned error message if the import response carries an in-band
    ERROR status. Returns None for OK status or unrecognized shape."""
    if not import_result or not isinstance(import_result, list):
        return None
    first = import_result[0]
    if not isinstance(first, dict):
        return None
    status = (first.get("response") or {}).get("status") or {}
    if status.get("status_code") != "ERROR":
        return None
    return _clean_error_message(status.get("error_message", ""))


def run_tml_import(
    profile: str, doc: dict, *,
    policy: str = "PARTIAL",
    no_create_new: bool = False,
    label: str | None = None,
) -> tuple[str, Optional[str], Optional[str]]:
    """Run ``ts tml import`` via subprocess.

    Returns:
        (status, guid, error) where status is "imported" or "failed".
    """
    from ts_cli.tml_common import extract_imported_guid

    model_tml_str = json.dumps(doc)
    cmd = (f"source ~/.zshenv && ts tml import --policy {shlex.quote(policy)} "
           f"--profile {shlex.quote(profile)}")
    if no_create_new:
        cmd += " --no-create-new"

    if label:
        print(f"  Running {label}...", file=sys.stderr)

    completed = subprocess.run(
        ["bash", "-c", cmd],
        input=json.dumps([model_tml_str]), capture_output=True, text=True)
    stderr_tail = (completed.stderr or "")[-500:]

    try:
        import_result = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        import_result = None

    if import_result is not None:
        status_error = _extract_status_error(import_result)
        if status_error is not None:
            return "failed", None, status_error

    if completed.returncode != 0:
        return "failed", None, stderr_tail

    if import_result is None:
        tail = (completed.stdout or "")[-500:]
        return "failed", None, f"import response unparseable — response tail: {tail}"

    model_guid = extract_imported_guid(import_result)
    if model_guid is None:
        tail = (completed.stdout or "")[-500:]
        return "failed", None, (
            f"import OK but no GUID found — response tail: {tail}")
    return "imported", model_guid, None
