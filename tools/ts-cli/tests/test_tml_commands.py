"""Unit tests for ts tml command defaults and guards.

Tests cover behaviour that previously caused silent production failures:
  1. ts tml export --type FEEDBACK: must exit with a clear message, not raise HTTP 400
  2. ts tml import create_new default: must be False (--no-create-new) to prevent
     silent duplicate creation when importing TML with an existing GUID
  3. ts profiles list --snowflake: must list profiles from snowflake-profiles.json

These are regression tests — each pin was written because the alternative caused
a real incident. Do not remove without understanding the consequence.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ts_cli.cli import app


runner = CliRunner(mix_stderr=False)


# ---------------------------------------------------------------------------
# ts tml export --type FEEDBACK
#
# Why: the ThoughtSpot API returns HTTP 400 when a model GUID is passed with
# type=FEEDBACK. Without an early guard, the CLI propagated that as an
# unhandled HTTPError with a confusing traceback.
# ---------------------------------------------------------------------------

class TestExportTypeFeedbackGuard:
    def test_feedback_exits_with_nonzero(self):
        result = runner.invoke(app, ["tml", "export", "some-guid", "--type", "FEEDBACK"])
        assert result.exit_code != 0

    def test_feedback_error_message_mentions_dependent_objects(self):
        """User must know how to find the correct GUID."""
        result = runner.invoke(app, ["tml", "export", "some-guid", "--type", "FEEDBACK"])
        output = (result.stdout or "") + (result.stderr or "")
        assert "dependents" in output.lower()

    def test_feedback_error_message_mentions_guid(self):
        """User must understand they need the feedback object's own GUID."""
        result = runner.invoke(app, ["tml", "export", "some-guid", "--type", "FEEDBACK"])
        output = (result.stdout or "") + (result.stderr or "")
        assert "guid" in output.lower()

    def test_other_type_does_not_exit_early(self):
        """--type LOGICAL_TABLE should reach the client (and fail on missing profile, not on type)."""
        result = runner.invoke(app, ["tml", "export", "some-guid", "--type", "LOGICAL_TABLE"])
        output = (result.stdout or "") + (result.stderr or "")
        # Should fail on missing profile, not on type
        assert "FEEDBACK" not in output
        assert "feedback" not in output.lower()

    def test_feedback_case_insensitive(self):
        """Guard must fire for 'feedback' and 'Feedback' too, not just 'FEEDBACK'."""
        for variant in ("feedback", "Feedback", "FEEDBACK"):
            result = runner.invoke(app, ["tml", "export", "some-guid", "--type", variant])
            assert result.exit_code != 0, f"Expected non-zero exit for --type {variant}"


# ---------------------------------------------------------------------------
# ts tml import create_new default
#
# Why: the default was previously True (--create-new). When a skill imported TML
# with an existing GUID, ThoughtSpot silently created a duplicate with a new GUID
# rather than updating the original. The fix changes the default to False so that
# the safe path (update existing) is what you get without explicit opt-in.
# ---------------------------------------------------------------------------

class TestImportCreateNewDefault:
    def _get_import_command_defaults(self):
        """Inspect the import command's parameters to read the create_new default."""
        import inspect
        from ts_cli.commands.tml import import_tml
        sig = inspect.signature(import_tml)
        return sig.parameters

    def test_create_new_default_is_false(self):
        """create_new must default to False — silently creating duplicates is a data-loss risk."""
        params = self._get_import_command_defaults()
        assert "create_new" in params
        # Typer wraps the default inside OptionInfo; unwrap it.
        default = params["create_new"].default
        # For typer.Option the default value is the first positional arg
        if hasattr(default, "default"):
            actual_default = default.default
        else:
            actual_default = default
        assert actual_default is False, (
            f"create_new default must be False (--no-create-new). Got: {actual_default!r}. "
            "A True default causes ThoughtSpot to silently create a duplicate object when "
            "importing TML with an existing GUID."
        )

    def test_help_text_warns_about_duplicate_risk(self):
        """Help text must warn about the duplicate-creation risk with --create-new."""
        result = runner.invoke(app, ["tml", "import", "--help"])
        assert "duplicate" in result.stdout.lower(), (
            "import --help must mention 'duplicate' so operators understand the risk of --create-new"
        )


# ---------------------------------------------------------------------------
# ts profiles list --snowflake
#
# Why: previously there was no CLI path to list Snowflake profiles. The skill
# had to tell users to cat the JSON file directly, which is fragile.
# ---------------------------------------------------------------------------

class TestProfilesListSnowflake:
    def _make_sf_profiles_file(self, tmp_path: Path) -> Path:
        profiles = {
            "profiles": [
                {
                    "name": "ThoughtSpot Partner (AP)",
                    "method": "python",
                    "account": "thoughtspot_partner.ap-southeast-2",
                    "username": "APJPOC",
                    "auth": "key_pair",
                    "default_warehouse": "SE_DEMO_WH",
                    "default_role": "SE_ROLE",
                },
                {
                    "name": "thoughtspot_partner.ap-southeast-2",
                    "method": "cli",
                    "cli_connection": "thoughtspot_partner.ap-southeast-2",
                    "default_warehouse": "",
                    "default_role": "",
                },
            ]
        }
        p = tmp_path / "snowflake-profiles.json"
        p.write_text(json.dumps(profiles))
        return p

    def test_snowflake_flag_lists_profiles(self, tmp_path):
        sf_path = self._make_sf_profiles_file(tmp_path)
        with patch("ts_cli.commands.profiles.SNOWFLAKE_PROFILES_PATH", sf_path):
            result = runner.invoke(app, ["profiles", "list", "--snowflake"])
        assert result.exit_code == 0
        assert "ThoughtSpot Partner (AP)" in result.stdout
        assert "thoughtspot_partner.ap-southeast-2" in result.stdout

    def test_snowflake_shows_account(self, tmp_path):
        sf_path = self._make_sf_profiles_file(tmp_path)
        with patch("ts_cli.commands.profiles.SNOWFLAKE_PROFILES_PATH", sf_path):
            result = runner.invoke(app, ["profiles", "list", "--snowflake"])
        assert "thoughtspot_partner.ap-southeast-2" in result.stdout

    def test_snowflake_shows_warehouse(self, tmp_path):
        sf_path = self._make_sf_profiles_file(tmp_path)
        with patch("ts_cli.commands.profiles.SNOWFLAKE_PROFILES_PATH", sf_path):
            result = runner.invoke(app, ["profiles", "list", "--snowflake"])
        assert "SE_DEMO_WH" in result.stdout

    def test_snowflake_missing_file_exits_nonzero(self, tmp_path):
        missing = tmp_path / "no-such-file.json"
        with patch("ts_cli.commands.profiles.SNOWFLAKE_PROFILES_PATH", missing):
            result = runner.invoke(app, ["profiles", "list", "--snowflake"])
        assert result.exit_code != 0

    def test_no_snowflake_flag_does_not_read_sf_profiles(self, tmp_path):
        """Without --snowflake, the command should not touch snowflake-profiles.json."""
        sf_path = self._make_sf_profiles_file(tmp_path)
        ts_path = tmp_path / "thoughtspot-profiles.json"
        ts_path.write_text(json.dumps([{
            "name": "prod",
            "base_url": "https://example.thoughtspot.cloud",
            "username": "user@example.com",
            "token_env": "TS_TOKEN_PROD",
        }]))
        with patch("ts_cli.commands.profiles.SNOWFLAKE_PROFILES_PATH", sf_path), \
             patch("ts_cli.client.PROFILES_PATH", ts_path), \
             patch("ts_cli.commands.profiles.PROFILES_PATH", ts_path):
            result = runner.invoke(app, ["profiles", "list"])
        assert "SE_DEMO_WH" not in result.stdout  # Snowflake detail must not appear
        assert "prod" in result.stdout
