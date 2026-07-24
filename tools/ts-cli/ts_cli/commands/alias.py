"""ts alias — column alias management commands.

Thin I/O wrappers around the pure logic in ``ts_cli.alias`` (merge/CSV/TML
assembly) and ``ts_cli.alias_translate`` (AI prompt building/response parsing/
locale config resolution). The four commands compose into a pipeline:

    ts alias export | ts alias translate | ts alias build | ts alias import
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Column alias management commands.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")

_SIZE_WARN_BYTES = 20 * 1024 * 1024   # 20 MB
_SIZE_LIMIT_BYTES = 25 * 1024 * 1024  # 25 MB
_ASYNC_THRESHOLD_BYTES = 5 * 1024 * 1024  # 5 MB

_CLAUDE_MODEL = "claude-sonnet-4-20250514"

_ALIAS_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS TS_COLUMN_ALIASES (\n"
    "    model_name    VARCHAR NOT NULL,\n"
    "    column_name   VARCHAR NOT NULL,\n"
    "    locale        VARCHAR NOT NULL,\n"
    "    alias         VARCHAR NOT NULL,\n"
    "    description   VARCHAR,\n"
    "    org_name      VARCHAR DEFAULT 'TS_WILDCARD_ALL',\n"
    "    group_name    VARCHAR DEFAULT 'TS_WILDCARD_ALL',\n"
    "    updated_at    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),\n"
    "    PRIMARY KEY (model_name, column_name, locale, org_name, group_name)\n"
    ");\n\n"
    "CREATE TABLE IF NOT EXISTS TS_ALIAS_LOCALES (\n"
    "    org_name      VARCHAR DEFAULT '*',\n"
    "    locale        VARCHAR NOT NULL,\n"
    "    PRIMARY KEY (org_name, locale)\n"
    ");"
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _read_json_envelope(input_file: Optional[str]) -> dict:
    """Read a JSON envelope from --input, or stdin if not given."""
    if input_file:
        return json.loads(Path(input_file).read_text())
    return json.loads(sys.stdin.read())


def _get_sf_cursor(sf_profile: Optional[str]):
    """Get a Snowflake cursor via the standard profile mechanism."""
    if not sf_profile:
        return None
    from ts_cli.commands.load import load_snowflake_profile, _connect_python
    profile = load_snowflake_profile(sf_profile)
    wh = profile.get("default_warehouse", "")
    rl = profile.get("default_role", "")
    conn = _connect_python(profile, wh, rl)
    return conn.cursor()


def _call_llm(prompt: str, translator: str, api_key_env: str,
              sf_profile: Optional[str]) -> str:
    """Call the configured LLM backend (Snowflake Cortex or Claude) and return raw text."""
    if translator == "cortex":
        if not sf_profile:
            print("Error: --sf-profile required for cortex translator", file=sys.stderr)
            raise SystemExit(1)
        from ts_cli.alias_translate import build_cortex_sql
        cursor = _get_sf_cursor(sf_profile)
        cursor.execute(build_cortex_sql(prompt))
        return cursor.fetchone()[0]

    import os
    import anthropic
    api_key = os.environ.get(api_key_env)
    if not api_key:
        print(f"Error: {api_key_env} not set", file=sys.stderr)
        raise SystemExit(1)
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _translate_with_retry(
    prompt: str, col_names: list[str], locale: str, org: str, group: str,
    translator: str, api_key_env: str, sf_profile: Optional[str],
) -> list[dict]:
    """Call the LLM and parse its response, retrying once with a stricter
    prompt if the first response is malformed (wrong shape/count/column)."""
    from ts_cli.alias_translate import parse_translation_response

    response_text = _call_llm(prompt, translator, api_key_env, sf_profile)
    try:
        return parse_translation_response(response_text, col_names, locale, org, group)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Warning: malformed AI response for org={org} locale={locale}, "
              f"retrying: {e}", file=sys.stderr)
        retry_prompt = prompt + (
            "\n\nYour previous response was malformed. "
            "Return ONLY a valid JSON array — no markdown, no commentary."
        )
        response_text = _call_llm(retry_prompt, translator, api_key_env, sf_profile)
        return parse_translation_response(response_text, col_names, locale, org, group)


def _maybe_ai_overlay(
    translations: list[dict],
    ai_locales: Optional[str],
    locale_config: Optional[str],
    locale_config_table: Optional[str],
    sf_profile: Optional[str],
    translator: str,
    api_key_env: str,
    sf_cursor: Any = None,
) -> list[dict]:
    """Optionally layer an AI locale translation on top of file/db-sourced
    aliases (use case 3: tenant + locale). Returns only the new AI-generated
    translations — the caller extends its own translations list with these.

    `sf_cursor`, when provided (the db source already has one open), is
    reused instead of opening a second Snowflake connection.
    """
    from ts_cli.alias import _WILDCARD
    from ts_cli.alias_translate import resolve_locale_config, group_translations_for_ai

    ai_locale_list = (ai_locales or "").split(",") if ai_locales else None
    cursor = sf_cursor
    if cursor is None and locale_config_table and sf_profile:
        cursor = _get_sf_cursor(sf_profile)
    locale_cfg = resolve_locale_config(ai_locale_list, locale_config, locale_config_table, cursor)
    if not locale_cfg:
        return []

    base_translations = [t for t in translations if t["locale"] == _WILDCARD]
    batches = group_translations_for_ai(base_translations, locale_cfg)
    return _run_ai_batches(batches, translator, api_key_env, sf_profile)


def _run_ai_batches(
    batches: list[tuple[str, str, list[dict]]],
    translator: str,
    api_key_env: str,
    sf_profile: Optional[str],
) -> list[dict]:
    """Run AI translation for a list of (org, locale, columns) batches."""
    from ts_cli.alias import _WILDCARD
    from ts_cli.alias_translate import build_translation_prompt

    results: list[dict] = []
    total = len(batches)
    for i, (org, locale, cols) in enumerate(batches, 1):
        print(f"Translating: org={org}, locale={locale} "
              f"({i}/{total}, {len(cols)} columns)", file=sys.stderr)

        prompt_cols = [
            {"name": c.get("alias") or c.get("column", ""),
             "description": c.get("description") or ""}
            for c in cols
        ]
        prompt = build_translation_prompt(
            prompt_cols, locale,
            source_context=f"These are column aliases for org '{org}'"
                           if org != _WILDCARD else None,
        )
        col_names = [c.get("column", c.get("name", "")) for c in cols]
        group = cols[0].get("group", _WILDCARD)
        results.extend(_translate_with_retry(
            prompt, col_names, locale, org, group,
            translator, api_key_env, sf_profile,
        ))
    return results


# ---------------------------------------------------------------------------
# ts alias translate — per-source helpers
# ---------------------------------------------------------------------------

def _translate_ai_source(
    model_columns: list[dict],
    locales: Optional[str],
    translator: str,
    api_key_env: str,
    sf_profile: Optional[str],
) -> list[dict]:
    """Handle `--source ai`: translate every model column for each requested locale."""
    from ts_cli.alias import validate_locales, _WILDCARD
    from ts_cli.alias_translate import build_translation_prompt

    if translator == "cortex" and not sf_profile:
        print("Error: --sf-profile required for cortex translator", file=sys.stderr)
        raise SystemExit(1)

    locale_list = validate_locales((locales or "").split(","))
    col_names = [c["name"] for c in model_columns]

    translations: list[dict] = []
    for loc in locale_list:
        prompt = build_translation_prompt(model_columns, loc)
        translations.extend(_translate_with_retry(
            prompt, col_names, loc, _WILDCARD, _WILDCARD,
            translator, api_key_env, sf_profile,
        ))
    return translations


def _filter_translations(
    translations: list[dict],
    locales: Optional[str],
    orgs: Optional[str],
    groups: Optional[str],
) -> list[dict]:
    """Apply optional --locales/--orgs/--groups filters (file source), always
    keeping wildcard-scoped entries regardless of the filter."""
    from ts_cli.alias import validate_locales, _WILDCARD

    if locales:
        locale_filter = set(validate_locales(locales.split(",")))
        translations = [t for t in translations
                        if t["locale"] in locale_filter or t["locale"] == _WILDCARD]
    if orgs:
        org_filter = set(orgs.split(","))
        translations = [t for t in translations
                        if t["org"] in org_filter or t["org"] == _WILDCARD]
    if groups:
        group_filter = set(groups.split(","))
        translations = [t for t in translations
                        if t["group"] in group_filter or t["group"] == _WILDCARD]
    return translations


def _translate_file_source(
    csv_path: Optional[str],
    model_name: str,
    locales: Optional[str],
    orgs: Optional[str],
    groups: Optional[str],
    ai_locales: Optional[str],
    locale_config: Optional[str],
    locale_config_table: Optional[str],
    sf_profile: Optional[str],
    translator: str,
    api_key_env: str,
) -> list[dict]:
    """Handle `--source file`: parse CSV aliases, filter, then optional AI overlay."""
    from ts_cli.alias import parse_csv_aliases

    if not csv_path:
        print("Error: --csv required for --source file", file=sys.stderr)
        raise SystemExit(1)

    csv_text = Path(csv_path).read_text()
    translations = parse_csv_aliases(csv_text, model_name=model_name)
    translations = _filter_translations(translations, locales, orgs, groups)
    translations.extend(_maybe_ai_overlay(
        translations, ai_locales, locale_config, locale_config_table,
        sf_profile, translator, api_key_env,
    ))
    return translations


def _build_db_query(
    table: str,
    model_name: str,
    locales: Optional[str],
    orgs: Optional[str],
    groups: Optional[str],
) -> tuple[str, list]:
    """Build the parameterized SELECT for --source db, applying optional filters."""
    from ts_cli.alias import validate_locales

    query = (f"SELECT column_name, locale, alias, description, "
             f"org_name, group_name FROM {table} "
             f"WHERE model_name = %s")
    params: list = [model_name]
    filters: list[str] = []

    if locales:
        locale_list = validate_locales(locales.split(","))
        placeholders = ",".join(["%s"] * len(locale_list))
        filters.append(f"locale IN ({placeholders})")
        params.extend(locale_list)
    if orgs:
        org_list = orgs.split(",")
        placeholders = ",".join(["%s"] * len(org_list))
        filters.append(f"org_name IN ({placeholders})")
        params.extend(org_list)
    if groups:
        group_list = groups.split(",")
        placeholders = ",".join(["%s"] * len(group_list))
        filters.append(f"group_name IN ({placeholders})")
        params.extend(group_list)
    if filters:
        query += " AND " + " AND ".join(filters)
    return query, params


def _translate_db_source(
    sf_profile: Optional[str],
    table: Optional[str],
    model_name: str,
    locales: Optional[str],
    orgs: Optional[str],
    groups: Optional[str],
    ai_locales: Optional[str],
    locale_config: Optional[str],
    locale_config_table: Optional[str],
    translator: str,
    api_key_env: str,
) -> list[dict]:
    """Handle `--source db`: query a Snowflake alias table, then optional AI overlay."""
    from ts_cli.alias import _WILDCARD

    if not sf_profile or not table:
        print("Error: --sf-profile and --table required for --source db",
              file=sys.stderr)
        raise SystemExit(1)

    cursor = _get_sf_cursor(sf_profile)
    query, params = _build_db_query(table, model_name, locales, orgs, groups)
    cursor.execute(query, params)

    translations = [
        {"column": row[0], "locale": row[1] or _WILDCARD, "alias": row[2],
         "description": row[3], "org": row[4] or _WILDCARD, "group": row[5] or _WILDCARD}
        for row in cursor.fetchall()
    ]
    if not translations:
        applied = f"model_name={model_name!r}"
        if orgs:
            applied += f", orgs={orgs}"
        print(f"Error: No rows in {table} for {applied}", file=sys.stderr)
        raise SystemExit(1)

    translations.extend(_maybe_ai_overlay(
        translations, ai_locales, locale_config, locale_config_table,
        sf_profile, translator, api_key_env, sf_cursor=cursor,
    ))
    return translations


# ---------------------------------------------------------------------------
# ts alias export
# ---------------------------------------------------------------------------

@app.command("export")
def export_cmd(
    model: str = typer.Option(..., "--model", help="Model GUID"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Export model columns and existing aliases.

    Calls the TML export API with export_with_column_aliases: true.
    Output: JSON envelope with model info, columns, and existing aliases.

    Examples:

    \b
      ts alias export --model <guid> -p prod
      ts alias export --model <guid> -p prod | ts alias translate --source ai --locales de-DE
    """
    from ts_cli.alias import parse_export_response

    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post("/api/rest/2.0/metadata/tml/export", json={
        "metadata": [{"identifier": model, "type": "LOGICAL_TABLE"}],
        "export_associated": True,
        "export_fqn": True,
        "edoc_format": "YAML",
        "export_options": {"export_with_column_aliases": True},
    })

    edocs = resp.json() or []
    result = parse_export_response(edocs)
    print(json.dumps(result))


# ---------------------------------------------------------------------------
# ts alias translate
# ---------------------------------------------------------------------------

@app.command("translate")
def translate_cmd(
    source: Optional[str] = typer.Option(None, "--source",
        help="Translation source: ai, file, or db (required unless --init-table)"),
    locales: Optional[str] = typer.Option(None, "--locales",
        help="Comma-separated locale codes (required for --source ai)"),
    orgs: Optional[str] = typer.Option(None, "--orgs",
        help="Comma-separated org names to filter (file/db only)"),
    groups: Optional[str] = typer.Option(None, "--groups",
        help="Comma-separated group names to filter (file/db only)"),
    input_file: Optional[str] = typer.Option(None, "--input",
        help="Input JSON file (default: stdin)"),
    translator: str = typer.Option("claude", "--translator",
        help="AI backend: claude or cortex"),
    api_key_env: str = typer.Option("ANTHROPIC_API_KEY", "--api-key-env",
        help="Env var name for Anthropic API key"),
    sf_profile: Optional[str] = typer.Option(None, "--sf-profile",
        help="Snowflake profile name"),
    table: Optional[str] = typer.Option(None, "--table",
        help="Snowflake table (source db)"),
    csv_path: Optional[str] = typer.Option(None, "--csv",
        help="CSV file path (source file)"),
    ai_locales: Optional[str] = typer.Option(None, "--ai-locales",
        help="Comma-separated locales for AI translation"),
    locale_config: Optional[str] = typer.Option(None, "--locale-config",
        help="YAML file for per-org locale config"),
    locale_config_table: Optional[str] = typer.Option(None, "--locale-config-table",
        help="Snowflake table for per-org locale config"),
    init_table: bool = typer.Option(False, "--init-table",
        help="Emit DDL for alias + locale tables, then exit"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Generate aliases from AI, file, or DB.

    Reads the export JSON envelope from stdin (or --input) and produces
    a translations JSON envelope to stdout.

    Examples:

    \b
      # AI translation
      ts alias export --model <guid> -p prod | ts alias translate --source ai --locales de-DE,fr-FR

      # From CSV
      ts alias export --model <guid> -p prod | ts alias translate --source file --csv aliases.csv

      # From Snowflake DB
      ts alias export --model <guid> -p prod | ts alias translate --source db --sf-profile sf --table DB.SCHEMA.TS_COLUMN_ALIASES

      # DDL for standard tables
      ts alias translate --init-table --sf-profile sf
    """
    if init_table:
        print(_ALIAS_TABLE_DDL)
        return

    if not source:
        print("Error: --source is required (ai, file, or db).", file=sys.stderr)
        raise SystemExit(1)

    if source == "ai" and (orgs or groups):
        bad_flag = "--orgs" if orgs else "--groups"
        print(f"Error: {bad_flag} is not valid with --source ai. "
              "AI translation is for language localization only. "
              "Use --source file or --source db for org/group aliases.",
              file=sys.stderr)
        raise SystemExit(1)

    if source == "ai" and not locales:
        print("Error: --locales is required for --source ai", file=sys.stderr)
        raise SystemExit(1)

    envelope = _read_json_envelope(input_file)
    model_info = envelope.get("model", {})
    model_name = model_info.get("name", "")
    model_columns = envelope.get("columns", [])
    existing_aliases = envelope.get("existing_aliases")

    if source == "ai":
        translations = _translate_ai_source(
            model_columns, locales, translator, api_key_env, sf_profile)
    elif source == "file":
        translations = _translate_file_source(
            csv_path, model_name, locales, orgs, groups,
            ai_locales, locale_config, locale_config_table,
            sf_profile, translator, api_key_env)
    elif source == "db":
        translations = _translate_db_source(
            sf_profile, table, model_name, locales, orgs, groups,
            ai_locales, locale_config, locale_config_table,
            translator, api_key_env)
    else:
        print(f"Error: Unknown source {source!r}. Use ai, file, or db.",
              file=sys.stderr)
        raise SystemExit(1)

    output = {
        "model": model_info,
        "translations": translations,
        "existing_aliases": existing_aliases,
    }
    print(json.dumps(output))


# ---------------------------------------------------------------------------
# ts alias build
# ---------------------------------------------------------------------------

@app.command("build")
def build_cmd(
    input_file: Optional[str] = typer.Option(None, "--input",
        help="Translations JSON file (default: stdin)"),
    merge: bool = typer.Option(False, "--merge",
        help="Merge new translations with existing aliases"),
) -> None:
    """Assemble column_alias TML YAML from translations.

    Reads the translations JSON envelope from stdin (or --input). With
    --merge, preserves existing aliases and only overwrites matching
    (column, locale, org, group) keys.

    Output: column_alias TML YAML to stdout. Emits tml_size_bytes to
    stderr. Warns when TML exceeds 20 MB; errors at 25 MB.

    Examples:

    \b
      ts alias translate ... | ts alias build
      ts alias translate ... | ts alias build --merge
      ts alias build --input translations.json --merge
    """
    from ts_cli.alias import (
        translations_to_columns, merge_aliases, build_alias_tml,
        estimate_tml_size,
    )

    envelope = _read_json_envelope(input_file)
    model_info = envelope.get("model", {})
    model_name = model_info.get("name", "")
    model_fqn = model_info.get("fqn", "")
    new_translations = envelope.get("translations", [])
    existing_aliases = envelope.get("existing_aliases")

    new_columns = translations_to_columns(new_translations)

    if merge and existing_aliases:
        existing_cols = existing_aliases.get("columns", [])
        final_columns = merge_aliases(existing_cols, new_columns)
    else:
        final_columns = new_columns

    tml_yaml = build_alias_tml(model_name, model_fqn, final_columns)
    size = estimate_tml_size(tml_yaml)

    if size > _SIZE_LIMIT_BYTES:
        print(f"Error: TML size ({size:,} bytes) exceeds the 25 MB platform "
              f"limit. Reduce locale coverage per org, split across multiple "
              f"Models, or wait for 26.10 delta load support.",
              file=sys.stderr)
        raise SystemExit(1)

    if size > _SIZE_WARN_BYTES:
        print(f"Warning: TML size ({size:,} bytes) is approaching the 25 MB "
              f"platform limit. Consider reducing scope.",
              file=sys.stderr)

    print(f"tml_size_bytes: {size}", file=sys.stderr)
    print(tml_yaml)


# ---------------------------------------------------------------------------
# ts alias import
# ---------------------------------------------------------------------------

def _extract_task_id(task_data: Any) -> Optional[str]:
    """Pull `task_id` out of the async-import response, whichever shape it took."""
    if isinstance(task_data, dict):
        return task_data.get("task_id")
    if isinstance(task_data, list) and task_data:
        first = task_data[0]
        return first.get("task_id") if isinstance(first, dict) else None
    return None


def _poll_async_import(client: ThoughtSpotClient, task_id: str) -> dict:
    """Poll .../tml/async/status until COMPLETED or FAILED, reporting progress
    to stderr. Backs off from 15s up to a 60s ceiling between polls."""
    poll_interval: float = 15
    while True:
        time.sleep(poll_interval)
        status_resp = client.post(
            "/api/rest/2.0/metadata/tml/async/status",
            json={"task_ids": [task_id], "include_import_response": True},
        )
        status_data = status_resp.json()
        status_list = status_data.get("status_list", [])
        if not status_list:
            print("Warning: empty status response, retrying...", file=sys.stderr)
            continue

        entry = status_list[0]
        task_status = entry.get("task_status", "")
        processed = entry.get("object_processed_count", 0)
        total = entry.get("total_object_count", 0)
        print(f"Status: {task_status} ({processed}/{total})", file=sys.stderr)

        if task_status == "COMPLETED":
            return entry
        if task_status == "FAILED":
            print(json.dumps(entry))
            raise SystemExit(1)

        poll_interval = min(poll_interval * 1.5, 60)


def _async_import(client: ThoughtSpotClient, tml_yaml: str, policy: str, size: int) -> None:
    """Submit the async import, then poll until it completes (or fails)."""
    print(f"Using async import ({size:,} bytes). "
          f"This may take 10-15 minutes for large payloads.", file=sys.stderr)
    resp = client.post(
        "/api/rest/2.0/metadata/tml/async/import",
        json={
            "metadata_tmls": [tml_yaml],
            "import_policy": policy,
            "create_new": False,
        },
    )
    task_data = resp.json()
    task_id = _extract_task_id(task_data)
    if not task_id:
        print(json.dumps(task_data))
        return

    print(f"Task ID: {task_id}", file=sys.stderr)
    result = _poll_async_import(client, task_id)
    print(json.dumps(result))


@app.command("import")
def import_cmd(
    model: str = typer.Option(..., "--model", help="Model GUID (for validation)"),
    profile: Optional[str] = _profile_option,
    file: Optional[str] = typer.Option(None, "--file",
        help="TML file path (default: stdin)"),
    dry_run: bool = typer.Option(False, "--dry-run",
        help="Validate without importing"),
) -> None:
    """Upload alias TML to ThoughtSpot.

    Reads column_alias TML YAML from stdin (or --file). Selects sync or
    async import based on payload size: <5 MB sync, 5-25 MB async (polls
    until complete, ~10-15 min for large payloads), >25 MB error.

    Examples:

    \b
      ts alias build ... | ts alias import --model <guid> -p prod
      ts alias import --model <guid> -p prod --file alias.yaml
      ts alias import --model <guid> -p prod --dry-run --file alias.yaml
    """
    tml_yaml = Path(file).read_text() if file else sys.stdin.read()
    size = len(tml_yaml.encode("utf-8"))
    policy = "VALIDATE_ONLY" if dry_run else "ALL_OR_NONE"

    if size > _SIZE_LIMIT_BYTES:
        print(f"Error: TML size ({size:,} bytes) exceeds 25 MB limit.",
              file=sys.stderr)
        raise SystemExit(1)

    client = ThoughtSpotClient(resolve_profile(profile))

    if size >= _ASYNC_THRESHOLD_BYTES and not dry_run:
        _async_import(client, tml_yaml, policy, size)
        return

    resp = client.post(
        "/api/rest/2.0/metadata/tml/import",
        json={
            "metadata_tmls": [tml_yaml],
            "import_policy": policy,
            "create_new": False,
        },
    )
    print(json.dumps(resp.json()))
