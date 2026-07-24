"""AI translation prompt building, response parsing, and locale config resolution.

Prompt building and response parsing are pure functions.
API calls (Claude, Cortex) are thin I/O wrappers called from commands/alias.py.
"""
from __future__ import annotations

import json
import re
from typing import Any

import yaml

from ts_cli.alias import _WILDCARD

_CORTEX_MODEL = "llama3.1-70b"


def build_translation_prompt(
    columns: list[dict],
    target_locale: str,
    source_context: str | None = None,
) -> str:
    """Build the LLM prompt asking for column name/description translations.

    Returns a plain-text prompt instructing the model to return a JSON array
    of {name, alias, description} objects for the given locale.
    """
    col_data = [
        {"name": c["name"], "description": c.get("description") or ""}
        for c in columns
    ]
    context_line = ""
    if source_context:
        context_line = f"\nAdditional context: {source_context}\n"

    return (
        f"Translate the following column names and descriptions to locale "
        f"{target_locale}. Return a JSON array of objects with keys: "
        f"\"name\" (original column name, unchanged), \"alias\" (translated "
        f"display name), \"description\" (translated description, or null if "
        f"the original is empty).\n"
        f"{context_line}\n"
        f"Columns:\n{json.dumps(col_data, indent=2)}\n\n"
        f"Important:\n"
        f"- Return ONLY the JSON array, no markdown fences or extra text\n"
        f"- Keep the original \"name\" field exactly as-is — do not translate it\n"
        f"- Translate the \"alias\" to be a natural, business-friendly "
        f"display name in {target_locale}\n"
        f"- Return exactly {len(col_data)} objects in the same order"
    )


def _strip_markdown_fences(text: str) -> str:
    """Strip a ```json ... ``` (or bare ``` ... ```) fence wrapping a response."""
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return text


def parse_translation_response(
    response_text: str,
    expected_columns: list[str],
    target_locale: str,
    org: str,
    group: str,
) -> list[dict]:
    """Validate and normalize a raw LLM response into translation dicts.

    Raises ValueError if the response is not a JSON array, has the wrong
    number of entries, or references a column name that wasn't asked for.
    """
    text = _strip_markdown_fences(response_text.strip())

    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")

    if len(data) != len(expected_columns):
        raise ValueError(
            f"Expected {len(expected_columns)} translations, got {len(data)}"
        )

    expected_set = set(expected_columns)
    results: list[dict] = []
    for entry in data:
        name = entry.get("name", "")
        if name not in expected_set:
            raise ValueError(f"Unknown column in response: {name!r}")
        results.append({
            "column": name,
            "locale": target_locale,
            "alias": entry.get("alias", ""),
            "description": entry.get("description"),
            "org": org,
            "group": group,
        })
    return results


def build_cortex_sql(prompt: str) -> str:
    """Wrap a prompt in a Snowflake Cortex COMPLETE() SQL statement."""
    escaped = prompt.replace("'", "''")
    return f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{_CORTEX_MODEL}', '{escaped}')"


def _resolve_locale_config_from_yaml(config_path: str) -> dict[str, list[str]]:
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    result: dict[str, list[str]] = {}
    if cfg.get("default"):
        result["*"] = cfg["default"]
    for org_name, locales in (cfg.get("orgs") or {}).items():
        result[org_name] = locales
    return result


def _resolve_locale_config_from_table(
    config_table: str,
    sf_cursor: Any,
) -> dict[str, list[str]]:
    sf_cursor.execute(f"SELECT org_name, locale FROM {config_table}")
    result: dict[str, list[str]] = {}
    for row in sf_cursor.fetchall():
        org = row[0] or "*"
        locale = row[1]
        result.setdefault(org, []).append(locale)
    return result


def resolve_locale_config(
    ai_locales: list[str] | None,
    config_path: str | None,
    config_table: str | None,
    sf_cursor: Any | None,
) -> dict[str, list[str]]:
    """Resolve the {org_name: [locale_codes]} config from whichever source is set.

    Precedence: an explicit --ai-locales flag list, then a YAML config file,
    then a Snowflake config table. Returns {} if none are provided.
    """
    if ai_locales:
        return {"*": list(ai_locales)}

    if config_path:
        return _resolve_locale_config_from_yaml(config_path)

    if config_table and sf_cursor:
        return _resolve_locale_config_from_table(config_table, sf_cursor)

    return {}


def get_org_locales(
    org_name: str,
    locale_config: dict[str, list[str]],
) -> list[str]:
    """Look up the locales configured for org_name, falling back to the '*' default."""
    if org_name in locale_config:
        return locale_config[org_name]
    return locale_config.get("*", [])


def group_translations_for_ai(
    translations: list[dict],
    locale_config: dict[str, list[str]],
) -> list[tuple[str, str, list[dict]]]:
    """Group translations by org, then fan each org out across its configured locales.

    Returns a list of (org, locale, columns_to_translate) batches — one batch
    per (org, locale) pair that needs an AI translation call.
    """
    org_columns: dict[str, list[dict]] = {}
    for t in translations:
        org = t.get("org", _WILDCARD)
        org_columns.setdefault(org, []).append(t)

    batches: list[tuple[str, str, list[dict]]] = []
    for org, cols in org_columns.items():
        locales = get_org_locales(org, locale_config)
        for locale in locales:
            batches.append((org, locale, cols))
    return batches
