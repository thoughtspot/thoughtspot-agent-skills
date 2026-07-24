"""Command-layer tests for `ts alias` (ts_cli.commands.alias).

Covers the whole-branch-review fixes for ts-object-model-alias:

- C1: `_run_ai_batches` reshapes translation dicts ({column, locale, alias,
  description, org, group}) into the {name, description} shape
  `build_translation_prompt` expects, instead of KeyError'ing on `c["name"]`.
- I1: `--groups` (like `--orgs`) is rejected with `--source ai`.
- I2: `--source ai` without `--locales` fails with a clear error, not a
  confusing "Invalid locale(s): " (empty) message from `validate_locales`.
- I3: `--translator cortex` without `--sf-profile` fails cleanly (SystemExit),
  both when called directly and via the AI-overlay path
  (`_maybe_ai_overlay` -> `_run_ai_batches` -> `_translate_with_retry` ->
  `_call_llm`), instead of an AttributeError from calling `.execute()` on a
  `None` cursor.

No live ThoughtSpot, Snowflake, or LLM connection required — `_call_llm` is
monkeypatched wherever an AI response would otherwise be needed.
"""
import json

import pytest
from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.commands import alias as alias_cmd

# Default CliRunner() mixes stdout+stderr into one flushed stream (matches
# the pattern used by the other `ts alias`-adjacent tests in this suite,
# e.g. test_cli_agentql_alias.py / test_metadata_delete.py). A plain
# `print(..., file=sys.stderr)` is never explicitly flushed by Click, so
# with `mix_stderr=False` (a separate, never-flushed stderr buffer) the
# error text would be silently lost from the captured result.
runner = CliRunner()


def _combined_output(result) -> str:
    return result.output


# ---------------------------------------------------------------------------
# I1 — --orgs / --groups rejected with --source ai
# ---------------------------------------------------------------------------

def test_translate_ai_rejects_orgs():
    result = runner.invoke(app, [
        "alias", "translate", "--source", "ai",
        "--locales", "de-DE", "--orgs", "Org 1",
    ])
    assert result.exit_code == 1
    out = _combined_output(result)
    assert "--orgs" in out
    assert "not valid with --source ai" in out


def test_translate_ai_rejects_groups():
    result = runner.invoke(app, [
        "alias", "translate", "--source", "ai",
        "--locales", "de-DE", "--groups", "Group 1",
    ])
    assert result.exit_code == 1
    out = _combined_output(result)
    assert "--groups" in out
    assert "not valid with --source ai" in out


def test_translate_file_source_allows_groups():
    """--groups is still valid for non-ai sources — the guard is ai-specific."""
    result = runner.invoke(app, [
        "alias", "translate", "--source", "file",
        "--groups", "Group 1",
    ], input=json.dumps({"model": {}, "columns": []}))
    # Fails for a different, unrelated reason (--csv missing), not the ai guard.
    assert result.exit_code == 1
    out = _combined_output(result)
    assert "not valid with --source ai" not in out
    assert "--csv required" in out


# ---------------------------------------------------------------------------
# I2 — --locales required for --source ai
# ---------------------------------------------------------------------------

def test_translate_ai_requires_locales():
    result = runner.invoke(app, ["alias", "translate", "--source", "ai"])
    assert result.exit_code == 1
    out = _combined_output(result)
    assert "--locales is required for --source ai" in out
    # Must not fall through to the confusing empty-locale validate_locales error.
    assert "Invalid locale(s):" not in out


def test_translate_ai_with_locales_passes_the_guard(monkeypatch):
    """Sanity check: the new guard doesn't block a valid --locales value."""
    monkeypatch.setattr(
        alias_cmd, "_translate_ai_source",
        lambda model_columns, locales, translator, api_key_env, sf_profile: [],
    )
    result = runner.invoke(app, [
        "alias", "translate", "--source", "ai", "--locales", "de-DE",
    ], input=json.dumps({"model": {}, "columns": []}))
    assert result.exit_code == 0, _combined_output(result)


# ---------------------------------------------------------------------------
# I3 — cortex translator without --sf-profile fails cleanly
# ---------------------------------------------------------------------------

def test_call_llm_cortex_without_sf_profile_errors_cleanly(capsys):
    with pytest.raises(SystemExit):
        alias_cmd._call_llm("prompt text", "cortex", "ANTHROPIC_API_KEY", None)
    captured = capsys.readouterr()
    assert "--sf-profile required for cortex translator" in captured.err


def test_run_ai_batches_cortex_without_sf_profile_errors_cleanly(capsys):
    """The AI-overlay path (_maybe_ai_overlay -> _run_ai_batches ->
    _translate_with_retry -> _call_llm) must raise the clean SystemExit,
    not an AttributeError from calling .execute() on a None cursor."""
    batches = [
        ("TS_WILDCARD_ALL", "de-DE", [
            {"column": "Revenue", "locale": "TS_WILDCARD_ALL", "alias": "",
             "description": "Total revenue", "org": "TS_WILDCARD_ALL",
             "group": "TS_WILDCARD_ALL"},
        ]),
    ]
    with pytest.raises(SystemExit):
        alias_cmd._run_ai_batches(batches, "cortex", "ANTHROPIC_API_KEY", None)
    captured = capsys.readouterr()
    assert "--sf-profile required for cortex translator" in captured.err


# ---------------------------------------------------------------------------
# C1 — _run_ai_batches reshapes translation dicts before prompt building
# ---------------------------------------------------------------------------

def test_run_ai_batches_reshapes_translation_dicts(monkeypatch):
    """cols in _run_ai_batches are translation dicts shaped like
    {column, locale, alias, description, org, group} — the shape produced by
    parse_csv_aliases / a DB query / group_translations_for_ai. These have no
    "name" key, so build_translation_prompt (which reads c["name"]) must be
    fed a reshaped {name, description} dict, not the raw translation dict."""
    captured_prompts = []

    def fake_call_llm(prompt, translator, api_key_env, sf_profile):
        captured_prompts.append(prompt)
        return json.dumps([
            {"name": "Revenue", "alias": "Umsatz", "description": "Gesamtumsatz"},
        ])

    monkeypatch.setattr(alias_cmd, "_call_llm", fake_call_llm)

    batches = [
        ("TS_WILDCARD_ALL", "de-DE", [
            {"column": "Revenue", "locale": "TS_WILDCARD_ALL", "alias": "",
             "description": "Total revenue", "org": "TS_WILDCARD_ALL",
             "group": "TS_WILDCARD_ALL"},
        ]),
    ]

    # Must not raise KeyError('name').
    results = alias_cmd._run_ai_batches(batches, "claude", "ANTHROPIC_API_KEY", None)

    assert results == [{
        "column": "Revenue", "locale": "de-DE", "alias": "Umsatz",
        "description": "Gesamtumsatz", "org": "TS_WILDCARD_ALL",
        "group": "TS_WILDCARD_ALL",
    }]
    # The prompt was built from the reshaped {name, description} dict (name
    # falls back to "column" since "alias" was empty here) — proving the
    # translation dict itself was never handed to build_translation_prompt.
    assert '"name": "Revenue"' in captured_prompts[0]
    assert '"description": "Total revenue"' in captured_prompts[0]


def test_run_ai_batches_multiple_columns_no_key_error(monkeypatch):
    """Regression guard for the exact use-case-3 shape: several translation
    dicts sharing one (org, locale) batch, none carrying a "name" key."""
    def fake_call_llm(prompt, translator, api_key_env, sf_profile):
        return json.dumps([
            {"name": "string_1", "alias": "Gebiet", "description": None},
            {"name": "string_2", "alias": "Umsatz", "description": None},
        ])

    monkeypatch.setattr(alias_cmd, "_call_llm", fake_call_llm)

    batches = [
        ("Org 1", "de-DE", [
            {"column": "string_1", "locale": "TS_WILDCARD_ALL", "alias": "",
             "description": None, "org": "Org 1", "group": "TS_WILDCARD_ALL"},
            {"column": "string_2", "locale": "TS_WILDCARD_ALL", "alias": "",
             "description": None, "org": "Org 1", "group": "TS_WILDCARD_ALL"},
        ]),
    ]

    results = alias_cmd._run_ai_batches(batches, "claude", "ANTHROPIC_API_KEY", None)
    assert len(results) == 2
    assert {r["column"] for r in results} == {"string_1", "string_2"}
    assert all(r["locale"] == "de-DE" and r["org"] == "Org 1" for r in results)
