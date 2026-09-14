"""ts-convert-to-dbt Case B — diff a dbt project's schema.yml against a fresh
Case A regeneration (`ts dbt-export diff`/`sync`).

Mirrors the `ts snowflake diff` "Mode C" pattern (`snowflake_ops.py`
`compute_change_set`): diff two flattened column maps and report the
change-set rather than structurally merging two YAML documents. The same
parser (`parse_schema_yaml_columns`) is applied to both the EXISTING
project's `models/schema.yml` text and a freshly-generated `schema.yml`'s
text (from `dbt_build_export.build_dbt_export`), so both sides of the diff
are produced by one code path and cannot drift from each other's shape.

Scoped to the PRIMARY artifact only (`models/schema.yml` — `ts_*` meta tags,
column `description` text + `relationships` tests). `models/semantic_models.yml` (the secondary,
not-live-verified MetricFlow artifact — see
agents/cli/ts-convert-to-dbt/references/open-items.md #2) is out of scope
for this diff; see open-items.md #4's Case B note.

Table-level new/removed detection (which dbt models exist on disk vs. which
the fresh generation would produce) is NOT this module's job — a table can
have no schema.yml entry at all (dbt_build_export.py's `_build_schema_docs`
skips a table with no classified columns/joins) while still needing a `.sql`
file, so table existence must be read from the project's `.sql` files, an
I/O concern that belongs in the command layer (commands/dbt_export.py).
This module only diffs columns for tables present in both inputs.

Pure functions, no I/O.
"""
from __future__ import annotations

import yaml


def _first_relationships_test(col: dict) -> "dict | None":
    """The first `relationships` entry in `data_tests:` (or the older
    `tests:` alias — dbt accepts both list-key names, see open-items.md #1),
    or `None` if the column has no relationships test."""
    tests = col.get("data_tests") or col.get("tests") or []
    for test in tests:
        if isinstance(test, dict) and "relationships" in test:
            return test["relationships"]
    return None


def _parse_column_entry(col: dict) -> "tuple[str, dict] | None":
    """One `columns[]` entry -> `(name, {"meta": ..., "relationship": ...})`,
    or `None` if `col` isn't a usable column doc (malformed/nameless)."""
    if not isinstance(col, dict) or not col.get("name"):
        return None
    meta = ((col.get("config") or {}).get("meta")) or {}
    # ts_column_exclude columns are deliberately absent from the ThoughtSpot
    # Model, so they must not read as "removed"/"changed" against it.
    from ts_cli.dbt_build_export import is_column_excluded
    if is_column_excluded(meta):
        return None
    return col["name"], {
        "meta": meta,
        "relationship": _first_relationships_test(col),
        "description": str(col.get("description") or ""),
    }


def _parse_model_columns(model: dict) -> dict[str, dict]:
    parsed = (_parse_column_entry(col) for col in model.get("columns") or [])
    return dict(entry for entry in parsed if entry is not None)


def parse_schema_yaml_columns(schema_yaml_text: str) -> dict[str, dict[str, dict]]:
    """Parse a dbt `schema.yml` document into a diffable column map.

    Returns `{model_name: {db_col: {"meta": {...ts_* tags...},
    "relationship": {...} | None, "description": str}}}`. `meta` is
    `columns[].config.meta` (or `{}` if absent); `description` is the
    column's `description:` text (`""` if absent).

    Blank/whitespace-only/malformed input returns `{}` rather than raising —
    a project that has no schema.yml yet (or one this parser can't make
    sense of) is simply "nothing tracked yet", not an error.
    """
    if not schema_yaml_text or not schema_yaml_text.strip():
        return {}
    try:
        doc = yaml.safe_load(schema_yaml_text)
    except yaml.YAMLError:
        return {}
    if not isinstance(doc, dict):
        return {}

    return {
        model["name"]: _parse_model_columns(model)
        for model in doc.get("models") or []
        if isinstance(model, dict) and model.get("name")
    }


def _owned_meta(meta: dict) -> dict:
    """The subset of a column's `meta` that `ts dbt-export build` can produce.

    A `ts_*` key outside `GENERATED_COLUMN_META_KEYS` (`ts_hidden`,
    `ts_calendar_type`, `ts_currency_type`, `ts_geo_config`,
    `ts_column_exclude`, or a tag from a newer ThoughtSpot) is hand-authored,
    and `sync --update-metadata` deliberately preserves it. Comparing it here
    would report a change sync then declines to apply — the same trap the
    `modified_description` guard below avoids. Non-`ts_*` keys are excluded for
    the same reason: another tool owns them.
    """
    from ts_cli.dbt_build_export import GENERATED_COLUMN_META_KEYS
    return {k: v for k, v in (meta or {}).items() if k in GENERATED_COLUMN_META_KEYS}


def _diff_column(col: str, cur_entry: dict, new_entry: dict, into: dict) -> None:
    """Compare one shared column's meta/description/relationship and append
    any difference onto the `modified_meta`/`modified_description`/
    `*_relationship` lists in `into`."""
    cur_meta = _owned_meta((cur_entry or {}).get("meta") or {})
    new_meta = _owned_meta((new_entry or {}).get("meta") or {})
    if cur_meta != new_meta:
        into["modified_meta"].append({"column": col, "current": cur_meta, "new": new_meta})

    # Mirrors what `sync --update-metadata` applies (commands/dbt_export.py
    # `_update_existing_schema_models`): a NON-EMPTY fresh description that
    # differs from the current one. A description cleared in ThoughtSpot (fresh
    # "") is neither applied nor reported -- the dbt text is kept, so it must
    # not show up here as a change that sync then silently ignores.
    cur_desc = (cur_entry or {}).get("description") or ""
    new_desc = (new_entry or {}).get("description") or ""
    if new_desc and new_desc != cur_desc:
        into["modified_description"].append(
            {"column": col, "current": cur_desc, "new": new_desc})

    cur_rel = (cur_entry or {}).get("relationship")
    new_rel = (new_entry or {}).get("relationship")
    if cur_rel == new_rel:
        return
    if cur_rel is None:
        into["new_relationship"].append(col)
    elif new_rel is None:
        into["removed_relationship"].append(col)
    else:
        into["modified_relationship"].append({"column": col, "current": cur_rel, "new": new_rel})


def _diff_table_columns(cur_cols: dict, new_cols: dict) -> "dict | None":
    """One shared model's column diff, or `None` if nothing differs."""
    cur_names = set(cur_cols.keys())
    new_names = set(new_cols.keys())

    result = {
        "new_columns": sorted(new_names - cur_names),
        "removed_columns": sorted(cur_names - new_names),
        "modified_meta": [],
        "modified_description": [],
        "new_relationship": [],
        "removed_relationship": [],
        "modified_relationship": [],
    }
    for col in sorted(cur_names & new_names):
        _diff_column(col, cur_cols.get(col), new_cols.get(col), result)

    has_diff = any(result[key] for key in (
        "new_columns", "removed_columns", "modified_meta", "modified_description",
        "new_relationship", "removed_relationship", "modified_relationship"))
    if not has_diff:
        return None
    result["new_relationship"] = sorted(result["new_relationship"])
    result["removed_relationship"] = sorted(result["removed_relationship"])
    return result


def compute_dbt_change_set(current: dict, new: dict) -> dict:
    """Diff two `parse_schema_yaml_columns()`-shaped maps.

    Only compares model names present in BOTH `current` and `new` — a model
    only on one side is a new/removed TABLE, which is the caller's concern
    (see module docstring), not a column-level change.

    Returns `{model_name: {new_columns, removed_columns,
    modified_meta: [{column, current, new}],
    modified_description: [{column, current, new}]  (non-empty new text only),
    new_relationship: [column, ...], removed_relationship: [column, ...],
    modified_relationship: [{column, current, new}]}}` for every shared
    model that has at least one difference. A model with no differences is
    omitted entirely, so an empty return means "nothing changed."
    """
    change_set: dict[str, dict] = {}
    for model_name in sorted(set(current.keys()) & set(new.keys())):
        diff = _diff_table_columns(current[model_name] or {}, new[model_name] or {})
        if diff is not None:
            change_set[model_name] = diff
    return change_set
