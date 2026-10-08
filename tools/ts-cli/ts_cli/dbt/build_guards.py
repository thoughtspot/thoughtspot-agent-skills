"""Guards for ts-convert-to-dbt Case A (``build_dbt_export``) against losing a
table, a column or a Model property without saying so.

Split out of dbt_build_export.py under the file-size gate. Each helper answers
one PR #506 review finding where the generator used to drop something silently:

- :func:`assign_model_names` — dbt model names that cannot collide (two Tables
  that snake-case to one name used to lose one `.sql` file and duplicate the
  schema.yml entry), including the base staging model a role-play alias selects
  from when its physical Table appears in the Model ONLY through aliases.
- :func:`drop_duplicate_db_columns` — two Model columns on one physical column
  used to blend their ts_* meta into one schema.yml entry.
- :func:`report_model_level_properties` — Model description/parameters/filters
  were ignored with no report (:func:`unmapped_label` is how the command prints
  such a column-less entry).
- :func:`rls_rules_dest` — `ts dbt-export build-model --rls-out` wrote to a path
  built from a model `alias:`, so `../../x` escaped the output directory.

Pure functions, no I/O (`rls_rules_dest` resolves a path, it writes nothing).
"""
from __future__ import annotations

from pathlib import Path

from ..tml_model_parse import to_snake


def stg_name(table_name: str) -> str:
    """Return the staging model name, avoiding double stg_ prefix."""
    snake = to_snake(table_name)
    return snake if snake.startswith("stg_") else f"stg_{snake}"


def _wanted_model_names(
    mt_order: list[str], mt_phys: dict[str, str], overrides: dict[str, str],
) -> list[tuple[str, str, bool]]:
    """(key, preferred dbt name, fixed?) in model_tables order.

    Keys are node keys, plus — after them — the PHYSICAL name of any Table that
    appears only through role-play aliases: its alias passthroughs
    `ref('stg_<table>')`, so that staging model has to be generated too or dbt
    cannot compile the project (PR #506 review). `fixed` marks a name adopted
    from an existing project (Case B), which must not be renamed.
    """
    wanted: list[tuple[str, str, bool]] = []
    for node_key in mt_order:
        physical = mt_phys.get(node_key, node_key)
        if node_key != physical:
            wanted.append((node_key, f"dim_{to_snake(node_key)}", False))
        elif overrides.get(physical):
            wanted.append((node_key, overrides[physical], True))
        else:
            wanted.append((node_key, stg_name(physical), False))
    seen = set(mt_order)
    for node_key in mt_order:
        physical = mt_phys.get(node_key, node_key)
        if physical in seen:
            continue
        seen.add(physical)
        adopted = overrides.get(physical)
        wanted.append((physical, adopted or stg_name(physical), bool(adopted)))
    return wanted


def _reserve_fixed_names(wanted: list[tuple[str, str, bool]]) -> dict[str, str]:
    """Adopted names, refusing two Tables adopting one model — neither can be
    renamed (the file already exists), and keeping both writes one model twice."""
    owner: dict[str, str] = {}
    for key, name, fixed in wanted:
        if not fixed:
            continue
        if name.lower() in owner and owner[name.lower()] != key:
            raise SystemExit(
                f"dbt model name collision: Tables {owner[name.lower()]!r} and {key!r} "
                f"both map to the existing model {name!r}. One dbt model cannot back "
                "two ThoughtSpot Tables — rename one of the existing models, or "
                "remove one Table from the Model.")
        owner[name.lower()] = key
    return owner


def assign_model_names(
    mt_order: list[str], mt_phys: dict[str, str],
    overrides: "dict[str, str] | None" = None,
) -> tuple[dict[str, str], list[dict]]:
    """Map every node key (table or role-play alias) — and the physical Table
    behind a role-play-only alias — to a UNIQUE dbt model name.

    `to_snake` is lossy: `Sales Data` and `SALES_DATA` both become
    `stg_sales_data`, which used to write one `.sql` file over the other and
    put two identical `name:` entries in schema.yml (PR #506 review). The first
    Table in model_tables order keeps the plain name; each later one gets `_2`,
    `_3`, ... Every downstream consumer (sql files, schema.yml, aliases,
    relationship and constraint refs, semantic models) reads this one dict, so
    the disambiguated name is used everywhere. Names compare case-insensitively
    because a `.sql` file name does on the default macOS/Windows filesystems.

    Returns (names, renamed) — `renamed` lists each disambiguation as
    {"table", "model", "wanted"} so the caller can report it.
    """
    wanted = _wanted_model_names(mt_order, mt_phys, overrides or {})
    taken = set(_reserve_fixed_names(wanted))
    names: dict[str, str] = {}
    renamed: list[dict] = []
    for key, name, fixed in wanted:
        if fixed:
            names[key] = name
            continue
        candidate, n = name, 2
        while candidate.lower() in taken:
            candidate, n = f"{name}_{n}", n + 1
        taken.add(candidate.lower())
        names[key] = candidate
        if candidate != name:
            renamed.append({"table": key, "model": candidate, "wanted": name})
    return names, renamed


def drop_duplicate_db_columns(entries: list[dict], unmapped_props: list[dict]) -> list[dict]:
    """Keep the FIRST Model column per (table, physical column); report the rest.

    dbt has one `columns:` entry per physical column, so a second Model column
    on the same one (`Amount` SUM and `Avg Amount` AVERAGE, both on AMT) used to
    blend its ts_* meta into the first — the wrong aggregation, synonyms and
    display name, silently (PR #506 review). The first keeps its meta unchanged;
    each later one is reported in `unmapped_properties`, and is left out of the
    returned list so build_info's dimension/metric counts describe what was
    actually written.
    """
    first: dict[tuple[str, str], str] = {}
    kept: list[dict] = []
    for e in entries:
        key = (e["table"], e["db_col"])
        if key not in first:
            first[key] = e["display_name"]
            kept.append(e)
            continue
        unmapped_props.append({
            "column": e["display_name"], "property": "duplicate_db_column",
            "value": e["db_col"],
            "reason": f"shares db column {e['db_col']} with '{first[key]}'; dbt has one "
                      "entry per physical column — add it back as a ts_formula "
                      "column if needed",
        })
    return kept


_MODEL_LEVEL_REASONS = {
    "description": "dbt has no Model-wide description — each dbt model "
                   "describes one table, so the ThoughtSpot Model's own "
                   "description has nowhere to go",
    "parameters": "dbt has no Model-wide equivalent of ThoughtSpot parameters; "
                  "re-create them on the Model after the resync",
    "filters": "dbt has no Model-wide equivalent of a ThoughtSpot Model filter; "
               "re-create them on the Model after the resync",
}


def report_model_level_properties(model: dict, unmapped_props: list[dict]) -> None:
    """Report the Model-level properties the scaffold cannot carry.

    Everything this generator writes is per dbt model (one per Table), so the
    ThoughtSpot Model's own description, parameters and filters used to vanish
    with no report (PR #506 review). Value is the count for a list, a short
    excerpt for the description.
    """
    for prop, reason in _MODEL_LEVEL_REASONS.items():
        value = model.get(prop)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (list, tuple, dict)):
            shown = len(value)
        else:
            text = str(value).strip()
            shown = text if len(text) <= 80 else text[:77] + "..."
        unmapped_props.append({
            "column": None, "property": f"model.{prop}", "value": shown,
            "reason": reason,
        })


def unmapped_label(up: dict) -> str:
    """What an unmapped_properties entry is ON: a column, the Model itself
    (`model.*`, column None), or else a join (named by its value)."""
    col = up.get("column")
    if col:
        return f"'{col}'"
    if str(up.get("property", "")).startswith("model."):
        return "the Model"
    return f"join '{up.get('value')}'"


def rls_rules_dest(rls_dir: Path, table_name: str) -> Path:
    """`<rls_dir>/<table_name>_rls_rules.json`, refused if it would land outside
    `rls_dir`. The name comes from a model's `alias:` in a schema.yml this
    command did not write, so `alias: ../../escaped` would otherwise write
    wherever it points (PR #506 review)."""
    name = str(table_name)
    bad = (not name or name in (".", "..") or ".." in name
           or "/" in name or "\\" in name or "\x00" in name)
    dest = rls_dir / f"{name}_rls_rules.json"
    if not bad:
        root = rls_dir.resolve()
        bad = dest.resolve().parent != root
    if bad:
        raise SystemExit(
            f"Refusing to write ts_rls_rules for model/alias {name!r}: the name "
            f"is not a plain file name and would write outside --rls-out "
            f"({rls_dir}). Give the model a plain `alias:` (no path separators "
            "or '..') and re-run.")
    return dest


def merge_source_block(existing_sources: list, fresh_src: dict, new_entries: list,
                        sources_path: Path) -> None:
    """Add `new_entries` to the existing block at the same (database, schema) —
    compared case-insensitively, as the warehouse does — or append a new block.

    A new block that would reuse an existing source NAME at a different location
    is refused: dbt rejects duplicate source names, so writing it would break the
    project (PR #506 review: `db`/`DB` used to produce exactly that).
    """
    def loc(src: dict) -> tuple:
        return (str(src.get("database") or "").upper(), str(src.get("schema") or "").upper())

    match = next((s for s in existing_sources if loc(s) == loc(fresh_src)), None)
    if match is not None:
        known = {str(t.get("name", "")).upper() for t in match.get("tables") or []
                 if isinstance(t, dict)}
        match.setdefault("tables", []).extend(
            t for t in new_entries if str(t.get("name", "")).upper() not in known)
        return
    if any(s.get("name") == fresh_src.get("name") for s in existing_sources):
        raise SystemExit(
            f"Refusing to write {sources_path}: source '{fresh_src.get('name')}' already "
            f"exists for a different location, and these new tables live in "
            f"{fresh_src.get('database')}.{fresh_src.get('schema')}. dbt rejects duplicate "
            "source names — add a source block for that location by hand, or re-run "
            "with a --source-name that is not already in use.")
    existing_sources.append({**fresh_src, "tables": new_entries})
