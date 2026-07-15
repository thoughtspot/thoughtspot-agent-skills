"""
test_client_profiles.py — recurrence-guard tests for profile-file parsing
(audit findings 4.1 + 4.2, docs/audit/2026-07-11-full.md).

4.1 (bug, now fixed): resolve_profile()'s file-parsing fallback used to be
`profiles = raw if isinstance(raw, list) else list(raw.values())`, then
`profiles[0]["name"]`. On the current, documented profiles-file shape —
`{"profiles": [{...}, {...}]}` — `list(raw.values())` yields `[[{...}, {...}]]`:
a one-element list whose element IS the profiles list. `profiles[0]` is then
the inner list itself, and `profiles[0]["name"]` becomes `list["name"]`, which
raises `TypeError: list indices must be integers or slices, not str`. Any `ts`
command run without `--profile`/`TS_PROFILE` against a real
`~/.claude/thoughtspot-profiles.json` (which is wrapped) died with a raw
traceback.

4.2 (consolidation): `load_profiles()` already handled all three documented
shapes correctly. `resolve_profile()` now reuses it as the single file parser
instead of duplicating (and diverging from) that shape-handling logic.

These tests assert both functions across all three shapes, env/flag
precedence, and the two distinct SystemExit messages. The wrapped-format
`resolve_profile` cases below are the reproducer — they FAIL with the
TypeError above against the pre-fix code and must PASS after the fix.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import ts_cli.client as client_module
import ts_cli.profile_ops as profile_ops_module
from ts_cli.client import load_profiles, resolve_profile

PROFILE_A = {"name": "A", "base_url": "https://a.thoughtspot.cloud", "token_env": "TOK_A"}
PROFILE_B = {"name": "B", "base_url": "https://b.thoughtspot.cloud", "token_env": "TOK_B"}


def _write_profiles(path: Path, data) -> None:
    path.write_text(json.dumps(data))


@pytest.fixture(autouse=True)
def _clear_ts_profile_env(monkeypatch):
    """Every test here exercises env-var precedence explicitly — start clean."""
    monkeypatch.delenv("TS_PROFILE", raising=False)


@pytest.fixture
def profiles_path(tmp_path, monkeypatch) -> Path:
    """Point PROFILES_PATH at a temp file for the duration of the test."""
    path = tmp_path / "thoughtspot-profiles.json"
    monkeypatch.setattr(client_module, "PROFILES_PATH", path)
    patched = {**profile_ops_module.PROFILE_PATHS, "thoughtspot": path}
    monkeypatch.setattr(profile_ops_module, "PROFILE_PATHS", patched)
    return path


# ---------------------------------------------------------------------------
# The three documented file shapes
# ---------------------------------------------------------------------------

class TestWrappedFormat:
    """{"profiles": [...]} — the current, documented shape, and the 4.1 reproducer."""

    def test_load_profiles_returns_name_keyed_dict(self, profiles_path):
        _write_profiles(profiles_path, {"profiles": [PROFILE_A, PROFILE_B]})
        assert load_profiles() == {"A": PROFILE_A, "B": PROFILE_B}

    def test_resolve_profile_returns_first_profile_name(self, profiles_path):
        _write_profiles(profiles_path, {"profiles": [PROFILE_A, PROFILE_B]})
        assert resolve_profile(None) == "A"


class TestBareListFormat:
    """[...] — bare list shape."""

    def test_load_profiles_returns_name_keyed_dict(self, profiles_path):
        _write_profiles(profiles_path, [PROFILE_A, PROFILE_B])
        assert load_profiles() == {"A": PROFILE_A, "B": PROFILE_B}

    def test_resolve_profile_returns_first_profile_name(self, profiles_path):
        _write_profiles(profiles_path, [PROFILE_A, PROFILE_B])
        assert resolve_profile(None) == "A"


class TestNameKeyedFormat:
    """{"name": {...}, ...} — dict keyed by profile name."""

    def test_load_profiles_returns_name_keyed_dict(self, profiles_path):
        _write_profiles(profiles_path, {"A": PROFILE_A, "B": PROFILE_B})
        assert load_profiles() == {"A": PROFILE_A, "B": PROFILE_B}

    def test_resolve_profile_returns_first_profile_name(self, profiles_path):
        _write_profiles(profiles_path, {"A": PROFILE_A, "B": PROFILE_B})
        assert resolve_profile(None) == "A"


# ---------------------------------------------------------------------------
# Precedence: --profile > TS_PROFILE env > file
# ---------------------------------------------------------------------------

class TestPrecedence:
    def test_explicit_profile_wins_over_env(self, profiles_path, monkeypatch):
        monkeypatch.setenv("TS_PROFILE", "FromEnv")
        _write_profiles(profiles_path, {"profiles": [PROFILE_A]})
        assert resolve_profile("Explicit") == "Explicit"

    def test_env_wins_over_file(self, profiles_path, monkeypatch):
        monkeypatch.setenv("TS_PROFILE", "FromEnv")
        _write_profiles(profiles_path, {"profiles": [PROFILE_A]})
        assert resolve_profile(None) == "FromEnv"


# ---------------------------------------------------------------------------
# Missing / empty file — the two distinct SystemExit messages must survive
# the consolidation onto load_profiles() (which collapses both to `{}`).
# ---------------------------------------------------------------------------

class TestMissingAndEmptyFile:
    def test_missing_file_raises_with_missing_file_message(self, profiles_path):
        assert not profiles_path.exists()
        with pytest.raises(SystemExit) as exc_info:
            resolve_profile(None)
        msg = str(exc_info.value)
        assert "No profiles file found at" in msg
        assert str(profiles_path) in msg

    def test_empty_profiles_raises_with_empty_message(self, profiles_path):
        _write_profiles(profiles_path, {"profiles": []})
        with pytest.raises(SystemExit) as exc_info:
            resolve_profile(None)
        msg = str(exc_info.value)
        assert "No ThoughtSpot profiles configured" in msg
