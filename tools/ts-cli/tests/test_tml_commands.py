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

from ts_cli.cli import app


# `runner` for stdout-JSON assertions; `msg_runner` for anything a manual
# print(file=sys.stderr) emits, which the separated runner silently drops.
from runners import msg_runner, runner  # noqa: E402  (BL-139: one definition, see runners.py)


def _all_output(result):
    """Return combined stdout+stderr, compatible with all Click versions."""
    try:
        return (result.stdout or "") + (result.stderr or "")
    except ValueError:
        return result.output or ""


# ---------------------------------------------------------------------------
# ts tml export --type FEEDBACK
#
# Why: the ThoughtSpot API returns HTTP 400 when a model GUID is passed with
# type=FEEDBACK. Without an early guard, the CLI propagated that as an
# unhandled HTTPError with a confusing traceback.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ts tml export --include-obj-id / --include-obj-id-ref / --no-guid
#
# Why: repoint operations need obj_id references to avoid VERSION_CONFLICT
# (error 14009) on some TS builds. The flags must reach the API request body
# as export_options, and must be absent when not set (older builds may reject
# unknown keys).
# ---------------------------------------------------------------------------

class TestExportObjIdFlags:
    def _get_export_params(self):
        import inspect
        from ts_cli.commands.tml import export_tml
        return inspect.signature(export_tml).parameters

    def test_include_obj_id_param_exists(self):
        assert "include_obj_id" in self._get_export_params()

    def test_include_obj_id_ref_param_exists(self):
        assert "include_obj_id_ref" in self._get_export_params()

    def test_include_guid_param_exists(self):
        assert "include_guid" in self._get_export_params()

    def test_include_guid_defaults_true(self):
        p = self._get_export_params()["include_guid"]
        default = p.default
        if hasattr(default, "default"):
            default = default.default
        assert default is True

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_no_flags_omits_export_options(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            {"edoc": "", "info": {"name": "x"}}
        ]
        mock_client_cls.return_value = mock_client
        runner.invoke(app, ["tml", "export", "abc-123"])
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json", {})
        assert "export_options" not in body

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_include_obj_id_sets_export_option(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            {"edoc": "", "info": {"name": "x"}}
        ]
        mock_client_cls.return_value = mock_client
        runner.invoke(app, ["tml", "export", "abc-123", "--include-obj-id"])
        body = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1]["json"]
        assert body["export_options"]["include_obj_id"] is True

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_include_obj_id_ref_sets_export_option(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            {"edoc": "", "info": {"name": "x"}}
        ]
        mock_client_cls.return_value = mock_client
        runner.invoke(app, ["tml", "export", "abc-123", "--include-obj-id-ref"])
        body = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1]["json"]
        assert body["export_options"]["include_obj_id_ref"] is True

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_no_guid_sets_export_option(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            {"edoc": "", "info": {"name": "x"}}
        ]
        mock_client_cls.return_value = mock_client
        runner.invoke(app, ["tml", "export", "abc-123", "--no-guid"])
        body = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1]["json"]
        assert body["export_options"]["include_guid"] is False

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_multiple_flags_combine(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            {"edoc": "", "info": {"name": "x"}}
        ]
        mock_client_cls.return_value = mock_client
        runner.invoke(app, [
            "tml", "export", "abc-123",
            "--include-obj-id", "--include-obj-id-ref", "--no-guid",
        ])
        body = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1]["json"]
        opts = body["export_options"]
        assert opts["include_obj_id"] is True
        assert opts["include_obj_id_ref"] is True
        assert opts["include_guid"] is False


class TestExportTypeFeedbackGuard:
    def test_feedback_exits_with_nonzero(self):
        result = runner.invoke(app, ["tml", "export", "some-guid", "--type", "FEEDBACK"])
        assert result.exit_code != 0

    def test_feedback_error_message_mentions_dependent_objects(self):
        """User must know how to find the correct GUID."""
        result = runner.invoke(app, ["tml", "export", "some-guid", "--type", "FEEDBACK"])
        output = _all_output(result)
        assert "dependents" in output.lower()

    def test_feedback_error_message_mentions_guid(self):
        """User must understand they need the feedback object's own GUID."""
        result = runner.invoke(app, ["tml", "export", "some-guid", "--type", "FEEDBACK"])
        output = _all_output(result)
        assert "guid" in output.lower()

    def test_other_type_does_not_exit_early(self):
        """--type LOGICAL_TABLE should reach the client (and fail on missing profile, not on type)."""
        result = runner.invoke(app, ["tml", "export", "some-guid", "--type", "LOGICAL_TABLE"])
        output = _all_output(result)
        # Should fail on missing profile, not on type
        assert "FEEDBACK" not in output
        assert "feedback" not in output.lower()

    def test_feedback_case_insensitive(self):
        """Guard must fire for 'feedback' and 'Feedback' too, not just 'FEEDBACK'."""
        for variant in ("feedback", "Feedback", "FEEDBACK"):
            result = runner.invoke(app, ["tml", "export", "some-guid", "--type", variant])
            assert result.exit_code != 0, f"Expected non-zero exit for --type {variant}"


# ---------------------------------------------------------------------------
# ts tml export --parse: null-edoc guard (BL-189)
#
# Why: a FORBIDDEN or OBJECT_INVALID_STATE object in the export response comes back
# with an empty/absent `edoc` -- exactly what an object returns when the export is
# refused (census, 2026-07-30, docs/reviews/2026-07-30-tml-census.md). `yaml.safe_load("")`
# returns None, and the old code fed that straight into `detect_tml_type`, which raised
# an unhandled `TypeError: argument of type 'NoneType' is not iterable` from `key in
# parsed` -- aborting the WHOLE batch over one inaccessible GUID. The fix skips (and
# reports on stderr) any item whose edoc is falsy, so the rest of the batch still parses.
# ---------------------------------------------------------------------------

def _forbidden_export_item(guid="ts-service-resources-guid", name="TS: Service Resources"):
    """Mirrors the real FORBIDDEN response shape recorded in the 2026-07-30 census:
    edoc is empty and info.status carries the reason -- same info.status.status_code
    shape already relied on in ts_cli/commands/publish_planning.py:61.
    """
    return {
        "edoc": "",
        "info": {
            "id": guid,
            "name": name,
            "type": "worksheet",
            "status": {
                "status_code": "ERROR",
                "error_message": "Cannot download TML due to lack of access to objects",
            },
        },
    }


def _good_export_item(guid="abc-123", name="Good Model"):
    return {
        "edoc": f"guid: {guid}\nmodel:\n  name: {name}\n",
        "info": {"id": guid, "name": name, "type": "model"},
    }


class TestExportParseNullEdocGuard:
    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_forbidden_item_does_not_crash_the_batch(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            _good_export_item(), _forbidden_export_item(),
        ]
        mock_client_cls.return_value = mock_client
        result = runner.invoke(
            app, ["tml", "export", "abc-123", "ts-service-resources-guid", "--parse"]
        )
        # A clean `raise SystemExit(1)` (the expected skip-and-report signal) is not a
        # crash -- only an unhandled TypeError/AttributeError etc. is the regression.
        assert not isinstance(result.exception, (TypeError, AttributeError)), repr(result.exception)

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_good_item_still_parsed_and_present_in_output(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            _good_export_item(), _forbidden_export_item(),
        ]
        mock_client_cls.return_value = mock_client
        result = runner.invoke(
            app, ["tml", "export", "abc-123", "ts-service-resources-guid", "--parse"]
        )
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["type"] == "model"
        assert data[0]["guid"] == "abc-123"

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_forbidden_item_omitted_from_stdout(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            _good_export_item(), _forbidden_export_item(),
        ]
        mock_client_cls.return_value = mock_client
        result = runner.invoke(
            app, ["tml", "export", "abc-123", "ts-service-resources-guid", "--parse"]
        )
        data = json.loads(result.stdout)
        guids = [d["guid"] for d in data]
        assert "ts-service-resources-guid" not in guids

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_stderr_warning_names_guid_and_reason(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            _good_export_item(), _forbidden_export_item(),
        ]
        mock_client_cls.return_value = mock_client
        result = msg_runner.invoke(
            app, ["tml", "export", "abc-123", "ts-service-resources-guid", "--parse"]
        )
        assert "ts-service-resources-guid" in result.output
        assert "TS: Service Resources" in result.output
        assert "Cannot download TML due to lack of access to objects" in result.output

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_exit_code_nonzero_when_an_item_is_skipped(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            _good_export_item(), _forbidden_export_item(),
        ]
        mock_client_cls.return_value = mock_client
        result = runner.invoke(
            app, ["tml", "export", "abc-123", "ts-service-resources-guid", "--parse"]
        )
        assert result.exit_code == 1

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_exit_code_zero_when_nothing_skipped(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [_good_export_item()]
        mock_client_cls.return_value = mock_client
        result = runner.invoke(app, ["tml", "export", "abc-123", "--parse"])
        assert result.exit_code == 0

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_all_items_forbidden_yields_empty_array_not_a_crash(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [_forbidden_export_item()]
        mock_client_cls.return_value = mock_client
        result = runner.invoke(
            app, ["tml", "export", "ts-service-resources-guid", "--parse"]
        )
        assert not isinstance(result.exception, (TypeError, AttributeError)), repr(result.exception)
        assert json.loads(result.stdout) == []
        assert result.exit_code == 1

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_none_edoc_value_also_skipped_not_crashed(self, mock_resolve, mock_client_cls):
        """The API may send an explicit JSON null rather than an empty string --
        both must be treated as 'no content', not just the empty-string case."""
        item = _forbidden_export_item()
        item["edoc"] = None
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [_good_export_item(), item]
        mock_client_cls.return_value = mock_client
        result = runner.invoke(
            app, ["tml", "export", "abc-123", "ts-service-resources-guid", "--parse"]
        )
        assert not isinstance(result.exception, (TypeError, AttributeError)), repr(result.exception)
        data = json.loads(result.stdout)
        assert len(data) == 1


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

    def _patch_sf_path(self, sf_path):
        """Patch the snowflake path in profile_ops.PROFILE_PATHS."""
        import ts_cli.profile_ops as _po
        original = _po.PROFILE_PATHS.copy()
        patched = {**original, "snowflake": sf_path}
        return patch.object(_po, "PROFILE_PATHS", patched)

    def test_snowflake_flag_lists_profiles(self, tmp_path):
        sf_path = self._make_sf_profiles_file(tmp_path)
        with self._patch_sf_path(sf_path):
            result = runner.invoke(app, ["profiles", "list", "--snowflake"])
        assert result.exit_code == 0
        assert "ThoughtSpot Partner (AP)" in result.stdout
        assert "thoughtspot_partner.ap-southeast-2" in result.stdout

    def test_snowflake_shows_account(self, tmp_path):
        sf_path = self._make_sf_profiles_file(tmp_path)
        with self._patch_sf_path(sf_path):
            result = runner.invoke(app, ["profiles", "list", "--snowflake"])
        assert "thoughtspot_partner.ap-southeast-2" in result.stdout

    def test_snowflake_shows_warehouse(self, tmp_path):
        sf_path = self._make_sf_profiles_file(tmp_path)
        with self._patch_sf_path(sf_path):
            result = runner.invoke(app, ["profiles", "list", "--snowflake"])
        assert "SE_DEMO_WH" in result.stdout

    def test_snowflake_missing_file_exits_nonzero(self, tmp_path):
        missing = tmp_path / "no-such-file.json"
        with self._patch_sf_path(missing):
            result = runner.invoke(app, ["profiles", "list", "--snowflake"])
        assert result.exit_code != 0

    def test_no_snowflake_flag_does_not_read_sf_profiles(self, tmp_path):
        """Without --snowflake, the command should not touch snowflake-profiles.json."""
        import ts_cli.profile_ops as _po
        sf_path = self._make_sf_profiles_file(tmp_path)
        ts_path = tmp_path / "thoughtspot-profiles.json"
        ts_path.write_text(json.dumps([{
            "name": "prod",
            "base_url": "https://example.thoughtspot.cloud",
            "username": "user@example.com",
            "token_env": "TS_TOKEN_PROD",
        }]))
        patched = {**_po.PROFILE_PATHS, "snowflake": sf_path, "thoughtspot": ts_path}
        with self._patch_sf_path(sf_path), \
             patch("ts_cli.client.PROFILES_PATH", ts_path), \
             patch("ts_cli.commands.profiles.PROFILES_PATH", ts_path), \
             patch.object(_po, "PROFILE_PATHS", patched):
            result = runner.invoke(app, ["profiles", "list"])
        assert "SE_DEMO_WH" not in result.stdout  # Snowflake detail must not appear
        assert "prod" in result.stdout


# ---------------------------------------------------------------------------
# ts tml export --split-dir
#
# Why: `ts dbt-export build|diff|sync` read `--model model.json` + `--tables-dir`,
# so ts-convert-to-dbt Step 3 had the LLM run an inline Python loop to split the
# --parse array into files. The whole export array passed through context purely
# to be re-emitted verbatim; for a 40-table Model that is the single largest
# payload in the run. This is that loop, codified.
# ---------------------------------------------------------------------------

def _table_export_item(name, guid=None):
    guid = guid or f"guid-{name.lower()}"
    return {
        "edoc": f"guid: {guid}\ntable:\n  name: {name}\n",
        "info": {"id": guid, "name": name, "type": "table"},
    }


class TestExportSplitDir:
    def _invoke(self, mock_client_cls, items, tmp_path, extra=()):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = items
        mock_client_cls.return_value = mock_client
        return runner.invoke(app, [
            "tml", "export", "abc-123", "--associated",
            "--split-dir", str(tmp_path), *extra])

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_writes_the_layout_dbt_export_reads(self, _resolve, mock_client_cls, tmp_path):
        out = tmp_path / "export"
        result = self._invoke(
            mock_client_cls,
            [_good_export_item(), _table_export_item("BARBERS"),
             _table_export_item("APPOINTMENTS")],
            out)
        assert result.exit_code == 0, result.output
        assert (out / "model.json").is_file()
        assert (out / "table_BARBERS.json").is_file()
        assert (out / "table_APPOINTMENTS.json").is_file()

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_each_file_is_the_unwrapped_tml_dict(self, _resolve, mock_client_cls, tmp_path):
        """`ts dbt-export build --model` expects `{"model": {...}}`, NOT the
        `{type, guid, tml, info}` envelope `--parse` returns."""
        out = tmp_path / "export"
        self._invoke(mock_client_cls, [_good_export_item(), _table_export_item("BARBERS")], out)
        model = json.loads((out / "model.json").read_text())
        assert set(model) == {"guid", "model"}
        assert model["model"]["name"] == "Good Model"
        table = json.loads((out / "table_BARBERS.json").read_text())
        assert table["table"]["name"] == "BARBERS"

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_stdout_is_a_manifest_not_the_whole_export(self, _resolve, mock_client_cls, tmp_path):
        """The point of the flag: the payload goes to disk, and only the list of
        filenames comes back through the caller's context."""
        out = tmp_path / "export"
        result = self._invoke(
            mock_client_cls, [_good_export_item(), _table_export_item("BARBERS")], out)
        payload = json.loads(result.stdout)
        assert payload["split_dir"] == str(out)
        assert sorted(payload["written"]) == ["model.json", "table_BARBERS.json"]
        assert "Good Model" not in result.stdout

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_creates_the_directory(self, _resolve, mock_client_cls, tmp_path):
        out = tmp_path / "does" / "not" / "exist"
        result = self._invoke(mock_client_cls, [_good_export_item()], out)
        assert result.exit_code == 0, result.output
        assert (out / "model.json").is_file()

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_same_named_tables_do_not_overwrite_each_other(
            self, _resolve, mock_client_cls, tmp_path):
        """An Org can hold two Tables with one name (a raw source table beside
        the dbt view). A silent overwrite drops one from the generated project
        with no diagnostic anywhere."""
        out = tmp_path / "export"
        self._invoke(mock_client_cls, [
            _table_export_item("BARBERS", guid="g-1"),
            _table_export_item("BARBERS", guid="g-2"),
        ], out)
        written = sorted(p.name for p in out.iterdir())
        assert len(written) == 2, written
        guids = {json.loads((out / n).read_text())["guid"] for n in written}
        assert guids == {"g-1", "g-2"}

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_implies_parse_without_the_flag(self, _resolve, mock_client_cls, tmp_path):
        """--split-dir has to parse the edocs to know a model from a table, so
        it must not silently no-op when --parse was not also passed."""
        out = tmp_path / "export"
        result = self._invoke(mock_client_cls, [_good_export_item()], out)
        assert result.exit_code == 0, result.output
        assert (out / "model.json").is_file()

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_inaccessible_item_is_skipped_and_exits_1(
            self, _resolve, mock_client_cls, tmp_path):
        """Same contract as --parse: the good items are still written, and the
        non-zero exit is the signal that something was dropped."""
        out = tmp_path / "export"
        result = self._invoke(
            mock_client_cls, [_good_export_item(), _forbidden_export_item()], out)
        assert result.exit_code == 1
        assert (out / "model.json").is_file()
        assert len(list(out.iterdir())) == 1
