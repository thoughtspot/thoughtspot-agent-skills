"""Pure helpers behind `ts model promote-formula` (no I/O).

Codifies the mechanical formula-promotion merge from
ts-object-answer-promote Steps 8-10 (BL-066): duplicate detection,
column-reference mapping, column_type inference, and Model TML merge.

All functions operate on parsed TML dicts (the shape `ts tml export --parse`
produces). No HTTP, no filesystem, no subprocess — pure dict transforms
that are fast to unit-test.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Optional

from ts_cli.spotql_ops import classify_expr
from ts_cli.tml_common import dump_tml_yaml

_REF_RE = re.compile(r"\[([^\]]+)\]")


def extract_answer_formulas(answer_tml: dict) -> dict[str, Any]:
    """Extract formulas, parameters, and data source info from an Answer TML.

    Returns::

        {
            "formulas":   [{"name", "id", "expr", "was_auto_generated"}, ...],
            "parameters": [{"name", "data_type", ...}, ...],
            "data_source_guid": str | None,
            "data_source_name": str | None,
        }
    """
    answer = answer_tml.get("answer", {})
    formulas = answer.get("formulas", [])
    parameters = answer.get("parameters", [])
    tables_section = answer.get("tables", [])

    out_formulas = []
    for f in formulas:
        out_formulas.append({
            "name": f["name"],
            "id": f.get("id", ""),
            "expr": f.get("expr", ""),
            "was_auto_generated": f.get("was_auto_generated", False),
        })

    return {
        "formulas": out_formulas,
        "parameters": parameters,
        "data_source_guid": tables_section[0].get("fqn") if tables_section else None,
        "data_source_name": tables_section[0].get("name") if tables_section else None,
    }


def detect_duplicates(
    formulas: list[dict],
    model_tml: dict,
    policy: str = "skip",
) -> dict[str, list[dict]]:
    """Classify formulas as add / skip / overwrite against the model.

    ``policy`` controls what happens when a formula name already exists in the
    model:

    - ``"skip"`` (default) — leave the existing model formula, don't promote
    - ``"overwrite"`` — replace the existing model formula with the answer version

    Returns::

        {
            "to_add":      [formula dicts with no name collision],
            "skipped":     [formula dicts skipped due to duplicate name],
            "to_overwrite": [formula dicts that will replace existing entries],
        }
    """
    model = model_tml.get("model", model_tml)
    existing_names = {f["name"] for f in model.get("formulas", [])}

    to_add = []
    skipped = []
    to_overwrite = []

    for f in formulas:
        if f["name"] in existing_names:
            if policy == "overwrite":
                to_overwrite.append(f)
            else:
                skipped.append(f)
        else:
            to_add.append(f)

    return {"to_add": to_add, "skipped": skipped, "to_overwrite": to_overwrite}


def detect_param_duplicates(
    params: list[dict],
    model_tml: dict,
    policy: str = "skip",
) -> dict[str, list[dict]]:
    """Classify parameters as add / skip / overwrite against the model."""
    model = model_tml.get("model", model_tml)
    existing_names = {p["name"] for p in model.get("parameters", [])}

    to_add = []
    skipped = []
    to_overwrite = []

    for p in params:
        if p["name"] in existing_names:
            if policy == "overwrite":
                to_overwrite.append(p)
            else:
                skipped.append(p)
        else:
            to_add.append(p)

    return {"to_add": to_add, "skipped": skipped, "to_overwrite": to_overwrite}


def _extract_refs(expr: str) -> list[str]:
    """Return all [token] references from a formula expression."""
    return _REF_RE.findall(expr)


def map_references(
    formulas: list[dict],
    model_tml: dict,
    *,
    promoting_names: Optional[set[str]] = None,
    promoting_ids: Optional[set[str]] = None,
) -> list[dict]:
    """Resolve [token] refs in each formula against the target model.

    For each formula, produces a dict with the rewritten expression and any
    unresolved references::

        {
            "name": str,
            "original_expr": str,
            "rewritten_expr": str,
            "rewrites": {old: new, ...},
            "unresolved": ["token", ...],
        }

    Reference classification (matches SKILL.md Step 9):

    - **Class A** — another formula (being promoted or already in model): keep as-is
    - **Class B** — explicit ``TABLE::column``: validate table name, keep as-is
    - **Class C** — bare name: resolve via ``col_by_name`` to ``TABLE::COLUMN_ID``
    """
    model = model_tml.get("model", model_tml)
    existing_formulas = model.get("formulas", [])
    existing_columns = model.get("columns", [])
    model_tables = model.get("model_tables", [])
    existing_params = model.get("parameters", [])

    formula_names_in_model = {f["name"] for f in existing_formulas}
    formula_ids_in_model = {f["id"] for f in existing_formulas}
    param_names_in_model = {p["name"] for p in existing_params}

    if promoting_names is None:
        promoting_names = {f["name"] for f in formulas}
    if promoting_ids is None:
        promoting_ids = {f.get("id", "") for f in formulas}

    col_by_name: dict[str, dict] = {}
    for c in existing_columns:
        col_by_name[c["name"]] = c

    valid_table_names = {t["name"] for t in model_tables}
    for t in model_tables:
        if t.get("alias"):
            valid_table_names.add(t["alias"])

    results = []
    for f in formulas:
        expr = f.get("expr", "")
        rewrites: dict[str, str] = {}
        unresolved: list[str] = []

        for token in _extract_refs(expr):
            if "::" in token:
                table_part, _ = token.split("::", 1)
                if table_part not in valid_table_names:
                    unresolved.append(token)
            elif (
                token in formula_names_in_model
                or token in formula_ids_in_model
                or token in promoting_names
                or token in promoting_ids
                or token in param_names_in_model
            ):
                pass
            else:
                match = col_by_name.get(token)
                if match and "column_id" in match:
                    rewrites[f"[{token}]"] = f"[{match['column_id']}]"
                else:
                    unresolved.append(token)

        rewritten = expr
        for old, new in rewrites.items():
            rewritten = rewritten.replace(old, new)

        results.append({
            "name": f["name"],
            "original_expr": expr,
            "rewritten_expr": rewritten,
            "rewrites": rewrites,
            "unresolved": unresolved,
        })

    return results


def _make_formula_id(name: str, existing_ids: set[str]) -> str:
    """Generate a formula ID following the ``formula_{name}`` convention."""
    fid = f"formula_{name}"
    if fid in existing_ids:
        fid = f"formula_{name}_promoted"
    return fid


def _build_model_param_entry(answer_param: dict) -> dict:
    """Build a model-level parameter entry from an answer parameter."""
    entry: dict[str, Any] = {
        "name": answer_param["name"],
        "data_type": answer_param["data_type"],
    }
    if answer_param.get("description"):
        entry["description"] = answer_param["description"]
    if "default_value" in answer_param:
        entry["default_value"] = answer_param["default_value"]
    elif "dynamic_default_date" in answer_param:
        entry["dynamic_default_date"] = answer_param["dynamic_default_date"]
    if "list_config" in answer_param:
        entry["list_config"] = answer_param["list_config"]
    return entry


def build_merged_model(
    model_tml: dict,
    formulas_to_add: list[dict],
    formulas_to_overwrite: list[dict],
    ref_map: list[dict],
    *,
    params_to_add: Optional[list[dict]] = None,
    params_to_overwrite: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Build the merged Model TML with promoted formulas.

    Returns::

        {
            "merged_tml": dict,         # the full updated TML dict
            "merged_yaml": str,         # serialized YAML ready for import
            "added": [{"name", "column_type", "aggregation", "expr", "formula_id"}],
            "overwritten": [{"name", ...}],
            "params_added": [{"name", "data_type"}],
            "params_overwritten": [{"name", "data_type"}],
        }
    """
    params_to_add = params_to_add or []
    params_to_overwrite = params_to_overwrite or []

    updated = copy.deepcopy(model_tml)
    m = updated.get("model", updated)

    existing_formula_ids = {f["id"] for f in m.get("formulas", [])}

    ref_by_name = {r["name"]: r for r in ref_map}

    overwrite_names = {f["name"] for f in formulas_to_overwrite}
    if overwrite_names:
        m["formulas"] = [
            x for x in m.get("formulas", [])
            if x.get("name") not in overwrite_names
        ]
        m["columns"] = [
            x for x in m.get("columns", [])
            if x.get("name") not in overwrite_names
        ]

    all_formulas = formulas_to_add + formulas_to_overwrite
    added_report: list[dict] = []

    new_formula_entries = []
    new_column_entries = []

    for f in all_formulas:
        ref_info = ref_by_name.get(f["name"])
        expr = ref_info["rewritten_expr"] if ref_info else f.get("expr", "")

        fid = _make_formula_id(f["name"], existing_formula_ids)
        existing_formula_ids.add(fid)

        classification = classify_expr(expr)
        column_type = classification["column_type"]
        aggregation = classification["aggregation"]

        new_formula_entries.append({
            "id": fid,
            "name": f["name"],
            "expr": expr,
        })

        col_entry: dict[str, Any] = {
            "name": f["name"],
            "formula_id": fid,
            "properties": {"column_type": column_type},
        }
        if aggregation:
            col_entry["properties"]["aggregation"] = aggregation
        new_column_entries.append(col_entry)

        added_report.append({
            "name": f["name"],
            "column_type": column_type,
            "aggregation": aggregation,
            "expr": expr,
            "formula_id": fid,
        })

    m.setdefault("formulas", []).extend(new_formula_entries)
    m.setdefault("columns", []).extend(new_column_entries)

    overwrite_param_names = {p["name"] for p in params_to_overwrite}
    if overwrite_param_names:
        m["parameters"] = [
            x for x in m.get("parameters", [])
            if x.get("name") not in overwrite_param_names
        ]

    all_params = params_to_add + params_to_overwrite
    params_added_report: list[dict] = []
    params_overwritten_report: list[dict] = []

    if all_params:
        new_param_entries = [_build_model_param_entry(p) for p in all_params]
        m.setdefault("parameters", []).extend(new_param_entries)

        for p in params_to_add:
            params_added_report.append({"name": p["name"], "data_type": p.get("data_type", "")})
        for p in params_to_overwrite:
            params_overwritten_report.append({"name": p["name"], "data_type": p.get("data_type", "")})

    overwritten_report = [
        r for r in added_report if r["name"] in overwrite_names
    ]
    truly_added_report = [
        r for r in added_report if r["name"] not in overwrite_names
    ]

    guid = model_tml.get("guid", updated.get("guid"))
    merged_yaml = dump_tml_yaml(updated)
    if guid and not merged_yaml.strip().startswith("guid:"):
        merged_yaml = f"guid: {guid}\n" + merged_yaml

    return {
        "merged_tml": updated,
        "merged_yaml": merged_yaml,
        "added": truly_added_report,
        "overwritten": overwritten_report,
        "params_added": params_added_report,
        "params_overwritten": params_overwritten_report,
    }


def find_param_dependencies(
    formulas: list[dict],
    answer_params: list[dict],
) -> list[dict]:
    """Identify answer parameters referenced by the selected formulas.

    Returns the subset of ``answer_params`` whose ``name`` appears as a
    ``[token]`` in any formula expression.
    """
    param_names = {p["name"] for p in answer_params}
    needed: dict[str, dict] = {}

    for f in formulas:
        for ref in _extract_refs(f.get("expr", "")):
            if ref in param_names:
                needed[ref] = next(p for p in answer_params if p["name"] == ref)

    return list(needed.values())


def find_formula_dependencies(
    selected: list[dict],
    all_answer_formulas: list[dict],
) -> list[dict]:
    """Find answer formulas referenced by selected formulas but not selected.

    Returns the unselected formulas that are dependencies.
    """
    all_ids = {f.get("id", ""): f for f in all_answer_formulas}
    all_names = {f["name"]: f for f in all_answer_formulas}
    selected_ids = {f.get("id", "") for f in selected}
    selected_names = {f["name"] for f in selected}

    deps: dict[str, dict] = {}
    for f in selected:
        for ref in _extract_refs(f.get("expr", "")):
            if ref in all_ids and ref not in selected_ids:
                deps[ref] = all_ids[ref]
            elif ref in all_names and ref not in selected_names:
                deps[ref] = all_names[ref]

    return list(deps.values())
