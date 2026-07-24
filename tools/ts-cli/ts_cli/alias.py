"""Column alias merge, TML assembly, CSV parsing, and locale validation.

Pure functions — no I/O. Used by commands/alias.py.
"""
from __future__ import annotations

import csv
import io
import sys
from typing import Any

import yaml

SUPPORTED_LOCALES: frozenset[str] = frozenset({
    "da-DK", "de-DE", "de-CH", "en-AU", "en-CA", "en-DE", "en-IN", "en-NZ",
    "en-GB", "en-US", "es-ES", "es-US", "es-MX", "fr-CA", "fr-FR", "ja-JP",
    "ko-KR", "it-IT", "nb-NO", "nl-NL", "pt-BR", "pt-PT", "ru-RU", "fi-FI",
    "sv-SE", "zh-CN", "zh-HANT",
})

_WILDCARD = "TS_WILDCARD_ALL"


def validate_locales(locales: list[str]) -> list[str]:
    invalid = [loc for loc in locales if loc not in SUPPORTED_LOCALES]
    if invalid:
        sorted_valid = sorted(SUPPORTED_LOCALES)
        print(f"Invalid locale(s): {', '.join(invalid)}\n"
              f"Valid locales: {', '.join(sorted_valid)}", file=sys.stderr)
        raise SystemExit(1)
    return locales


def _csv_row_to_translation(row: dict, model_name: str | None) -> dict | None:
    """Convert a single CSV row into a translation dict, or None to skip it."""
    if model_name and row.get("model_name") and row["model_name"] != model_name:
        return None
    alias_val = (row.get("alias") or "").strip()
    desc_val = (row.get("description") or "").strip()
    if not alias_val and not desc_val:
        return None
    return {
        "column": row["column_name"].strip(),
        "locale": (row.get("locale") or "").strip() or _WILDCARD,
        "alias": alias_val,
        "description": desc_val or None,
        "org": (row.get("org_name") or "").strip() or _WILDCARD,
        "group": (row.get("group_name") or "").strip() or _WILDCARD,
    }


def parse_csv_aliases(
    csv_text: str,
    model_name: str | None = None,
) -> list[dict]:
    reader = csv.DictReader(io.StringIO(csv_text))
    rows: list[dict] = []
    for row in reader:
        translation = _csv_row_to_translation(row, model_name)
        if translation is not None:
            rows.append(translation)
    return rows


def translations_to_columns(translations: list[dict]) -> list[dict]:
    col_map: dict[str, dict[str, dict[str, dict[str, dict]]]] = {}
    for t in translations:
        col = t["column"]
        loc = t["locale"]
        org = t["org"]
        grp = t["group"]
        col_map.setdefault(col, {})
        col_map[col].setdefault(loc, {})
        col_map[col][loc].setdefault(org, {})
        entry: dict[str, Any] = {"name": grp}
        if t.get("alias"):
            entry["alias"] = t["alias"]
        if t.get("description"):
            entry["description"] = t["description"]
        col_map[col][loc][org][grp] = entry

    columns: list[dict] = []
    for col_name in col_map:
        locales: list[dict] = []
        for loc_name, orgs in col_map[col_name].items():
            org_list: list[dict] = []
            for org_name, groups in orgs.items():
                group_list = list(groups.values())
                org_list.append({"name": org_name, "groups": group_list})
            locales.append({"name": loc_name, "orgs": org_list})
        columns.append({"name": col_name, "locales": locales})
    return columns


def _flatten_columns(columns: list[dict]) -> dict[tuple, dict]:
    flat: dict[tuple, dict] = {}
    for col in columns:
        col_name = col["name"]
        for locale in (col.get("locales") or []):
            loc_name = locale["name"]
            for org in (locale.get("orgs") or []):
                org_name = org["name"]
                for group in (org.get("groups") or []):
                    grp_name = group["name"]
                    key = (col_name, loc_name, org_name, grp_name)
                    flat[key] = {
                        "alias": group.get("alias", ""),
                        "description": group.get("description"),
                    }
    return flat


def merge_aliases(
    existing_columns: list[dict],
    new_columns: list[dict],
) -> list[dict]:
    existing_flat = _flatten_columns(existing_columns)
    new_flat = _flatten_columns(new_columns)
    merged_flat = {**existing_flat, **new_flat}

    all_translations: list[dict] = []
    for (col, loc, org, grp), entry in merged_flat.items():
        all_translations.append({
            "column": col, "locale": loc, "org": org, "group": grp,
            "alias": entry.get("alias", ""),
            "description": entry.get("description"),
        })
    return translations_to_columns(all_translations)


def build_alias_tml(
    model_name: str,
    model_fqn: str,
    columns: list[dict],
) -> str:
    doc: dict[str, Any] = {
        "column_alias": {
            "model": {"name": model_name, "fqn": model_fqn},
            "columns": columns,
        }
    }
    return yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)


def estimate_tml_size(tml_yaml: str) -> int:
    return len(tml_yaml.encode("utf-8"))


def _is_alias_doc(info_type: str, filename: str) -> bool:
    return "COLUMN_ALIAS" in info_type or "alias" in filename


def _extract_alias_data(parsed: dict) -> tuple[dict, str | None]:
    alias_data = parsed.get("column_alias") or {}
    existing_aliases = {"columns": alias_data.get("columns") or []}
    model_ref = alias_data.get("model") or {}
    return existing_aliases, model_ref.get("fqn")


def _extract_model_data(parsed: dict, info: dict) -> tuple[dict, list[dict]]:
    model_data = parsed.get("model") or {}
    partial_info = {
        "guid": info.get("id"),
        "name": model_data.get("name") or info.get("name"),
    }
    columns = [
        {
            "name": col.get("name"),
            "description": col.get("description") or "",
            "type": col.get("column_type") or "ATTRIBUTE",
        }
        for col in (model_data.get("columns") or [])
    ]
    return partial_info, columns


def parse_export_response(edocs: list[dict]) -> dict:
    model_info: dict[str, Any] = {"guid": None, "name": None, "fqn": None}
    columns: list[dict] = []
    existing_aliases: dict | None = None

    for doc in edocs:
        info = doc.get("info") or {}
        edoc_str = doc.get("edoc") or ""
        if not edoc_str:
            continue
        parsed = yaml.safe_load(edoc_str) or {}
        info_type = (info.get("type") or "").upper()
        filename = (info.get("filename") or "").lower()

        if _is_alias_doc(info_type, filename):
            existing_aliases, fqn = _extract_alias_data(parsed)
            if fqn:
                model_info["fqn"] = fqn
        elif info_type in ("LOGICAL_TABLE", "MODEL"):
            partial_info, doc_columns = _extract_model_data(parsed, info)
            model_info["guid"] = partial_info["guid"]
            model_info["name"] = partial_info["name"]
            columns.extend(doc_columns)

    return {
        "model": model_info,
        "columns": columns,
        "existing_aliases": existing_aliases,
    }
