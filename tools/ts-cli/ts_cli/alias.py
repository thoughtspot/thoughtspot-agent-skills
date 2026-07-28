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
        alias_entry: dict[str, Any] = {}
        if t.get("alias"):
            alias_entry["alias"] = t["alias"]
        alias_entry["description"] = t.get("description") or ""
        col_map[col][loc][org][grp] = alias_entry

    columns: list[dict] = []
    for col_name in col_map:
        locales: list[dict] = []
        for loc_name, orgs in col_map[col_name].items():
            org_list: list[dict] = []
            for org_name, groups in orgs.items():
                group_list = [
                    {"name": grp_name, "entries": [entry]}
                    for grp_name, entry in groups.items()
                ]
                org_list.append({"name": org_name, "groups": group_list})
            locales.append({"name": loc_name, "orgs": org_list})
        columns.append({"name": col_name, "locales": locales})
    return columns


# The group name that scopes an alias to EVERY user in the Org.
WILDCARD_GROUP = "TS_WILDCARD_ALL"


def _overlap_problem(col: str, locale: str, org: str, groups: list[str]) -> str | None:
    """The message for one (column, locale, org), or None if the scopes are unambiguous."""
    specific = sorted(g for g in groups if g and g != WILDCARD_GROUP)
    if WILDCARD_GROUP not in groups or not specific:
        return None
    return (f"{col} / {locale} / {org}: {WILDCARD_GROUP} overlaps with "
            f"{', '.join(specific)}. A user in either group matches two pathways, so they "
            f"would see the BASE column name rather than any alias -- even though the "
            f"aliases agree. Keep {WILDCARD_GROUP} for Org-wide scope, or use group scopes "
            f"alone, but never both for one column")


def find_scope_overlaps(columns: list[dict]) -> list[str]:
    """(column, locale, org) triples where a user could match TWO alias pathways.

    **An ambiguous alias resolves to the BASE column name** -- a user who matches both a
    `TS_WILDCARD_ALL` entry and an entry for a group they belong to sees the underlying
    column (`STRING_1`), not either alias. **Identical alias values do not help**: two
    pathways is two pathways.

    Worth refusing rather than warning about, because nothing else catches it. Every entry
    is individually valid, the import returns `status_code: OK`, and the alias export looks
    correct. The only symptom is tenants seeing generic column names, which reads as a
    broken migration rather than an alias-scope collision.

    There is no legitimate wildcard-plus-group combination: since the platform falls back
    to the base name, that pairing never produces what the author intended.
    """
    problems: list[str] = []
    for col in columns or []:
        for locale in (col.get("locales") or []):
            for org in (locale.get("orgs") or []):
                groups = [g.get("name") for g in (org.get("groups") or [])
                          if (g.get("entries") or [])]
                problem = _overlap_problem(col.get("name"), locale.get("name"),
                                           org.get("name"), groups)
                if problem:
                    problems.append(problem)
    return problems


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
                    entries = group.get("entries") or [group]
                    for entry in entries:
                        key = (col_name, loc_name, org_name, grp_name)
                        flat[key] = {
                            "alias": entry.get("alias", ""),
                            "description": entry.get("description"),
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


def _make_obj_id(name: str, guid: str) -> str:
    """Build the ThoughtSpot obj_id format: NAME-first8chars."""
    short = guid.split("-")[0] if "-" in guid else guid[:8]
    return f"{name}-{short}"


def build_alias_tml(
    model_name: str,
    model_fqn: str,
    columns: list[dict],
) -> str:
    obj_id = _make_obj_id(model_name, model_fqn)
    doc: dict[str, Any] = {
        "column_alias": {
            "model": {"name": model_name, "obj_id": obj_id},
            "columns": columns,
        }
    }
    return yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)


def build_alias_csv(columns: list[dict]) -> str:
    """Flatten the columns structure into ThoughtSpot's CSV upload format."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(["Column", "locale", "alias", "description", "org_name", "group_name"])
    flat = _flatten_columns(columns)
    for (col, loc, org, grp), entry in sorted(flat.items()):
        writer.writerow([
            col, loc,
            entry.get("alias", ""),
            entry.get("description") or "",
            org, grp,
        ])
    return output.getvalue()


def estimate_tml_size(tml_yaml: str) -> int:
    return len(tml_yaml.encode("utf-8"))


def _is_alias_doc(info_type: str, filename: str) -> bool:
    return "COLUMN_ALIAS" in info_type or "alias" in filename


def _extract_alias_data(parsed: dict) -> tuple[dict, str | None]:
    alias_data = parsed.get("column_alias") or {}
    existing_aliases = {"columns": alias_data.get("columns") or []}
    model_ref = alias_data.get("model") or {}
    return existing_aliases, model_ref.get("fqn") or model_ref.get("obj_id")


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
