"""Pure helper functions for `ts columns impact` (column dependency analysis).

No I/O, no network calls — everything that can be tested in isolation.
"""
from __future__ import annotations

# v2 dependent_objects bucket → human label
BUCKET_LABELS = {
    "QUESTION_ANSWER_BOOK": "ANSWER",
    "PINBOARD_ANSWER_BOOK": "LIVEBOARD",
    "LOGICAL_TABLE": "LOGICAL_TABLE",
}

SUBTYPE_LABELS = {
    "ONE_TO_ONE_LOGICAL": "TABLE",
    "WORKSHEET": "WORKSHEET",
    "PRIVATE_WORKSHEET": "PRIVATE_WORKSHEET",
    "USER_DEFINED": "USER_DEFINED",
    "AGGR_WORKSHEET": "VIEW (search-based)",
    "SQL_VIEW": "VIEW (SQL)",
    "": "MODEL",
}


def parse_dependents(dep_obj: dict) -> tuple[list[dict], bool]:
    """Flatten v2 dependent_objects into a list of dicts.

    Returns (dep_list, has_inaccessible).
    Each dep entry: {guid, name, type, raw_type}.
    """
    result = []
    inaccessible = dep_obj.get("hasInaccessibleDependents", False)
    for _src, buckets in (dep_obj.get("dependents") or {}).items():
        for bucket, items in buckets.items():
            label = BUCKET_LABELS.get(bucket, bucket)
            for item in (items or []):
                result.append({
                    "guid": item.get("id"),
                    "name": item.get("name"),
                    "type": label,
                    "raw_type": bucket,
                })
    return result, inaccessible


def apply_subtype_labels(
    dep_list: list[dict], subtype_map: dict[str, str]
) -> list[dict]:
    """Replace LOGICAL_TABLE type with a human-readable subtype label.

    `subtype_map` maps GUID -> raw subType string (from metadata/search).
    Returns a new list; input is not mutated.
    """
    result = []
    for d in dep_list:
        entry = dict(d)
        if d.get("raw_type") == "LOGICAL_TABLE":
            raw_sub = subtype_map.get(d["guid"], "")
            entry["type"] = SUBTYPE_LABELS.get(raw_sub, f"LOGICAL_TABLE/{raw_sub}")
        result.append(entry)
    return result


def find_broken_formulas(formulas: list[dict], physical_col: str) -> list[dict]:
    """Return formulas whose expression references physical_col (case-insensitive)."""
    target = physical_col.lower()
    return [f for f in formulas if target in (f.get("expr") or "").lower()]


def find_broken_rls(
    rls_rules: list[dict], rls_paths: list[dict], physical_col: str
) -> tuple[list[tuple[str, dict]], list[dict]]:
    """Return (broken_rule_pairs, broken_paths) for rules/paths referencing physical_col.

    broken_rule_pairs: list of ("expr", rule_dict) tuples.
    broken_paths: list of table_path dicts that include physical_col in their column list.
    """
    target = physical_col.lower()
    broken_rules = [
        ("expr", rule) for rule in rls_rules
        if target in (rule.get("expr") or "").lower()
    ]
    broken_paths = [
        p for p in rls_paths if physical_col in (p.get("column") or [])
    ]
    return broken_rules, broken_paths


def collect_affected_lb_ans_guids(
    dep_lists: list[list[dict]],
) -> tuple[set[str], set[str]]:
    """Extract affected Liveboard and Answer GUIDs from one or more dep_lists."""
    lb_guids: set[str] = set()
    ans_guids: set[str] = set()
    for dep_list in dep_lists:
        for d in dep_list:
            rt = d.get("raw_type", "")
            if rt == "PINBOARD_ANSWER_BOOK" and d.get("guid"):
                lb_guids.add(d["guid"])
            elif rt == "QUESTION_ANSWER_BOOK" and d.get("guid"):
                ans_guids.add(d["guid"])
    return lb_guids, ans_guids


def build_impact_summary(
    column_name: str,
    physical_col: str,
    pass1_deps: list[dict],
    formula_dep_results: list[tuple],
    pass4_deps: list[dict],
    sv_downstream: list[dict],
    broken_formulas: list[dict],
    col_security_rules: list[dict],
    broken_rls: list,
    broken_paths: list[dict],
    broken_vars: list[tuple],
    broken_terms: list[tuple],
    affected_actions: list[tuple],
    broken_views: list[dict],
    broken_cohorts: list[dict],
    broken_schedules: list[dict],
    broken_alerts: list[dict],
    any_inaccessible: bool,
) -> dict:
    """Build the structured JSON summary for stdout."""
    all_guids: set[str] = set()
    unique_objects: list[dict] = []

    def add_deps(label: str, dep_list: list[dict]) -> None:
        for d in dep_list:
            if d.get("guid") and d["guid"] not in all_guids:
                all_guids.add(d["guid"])
                unique_objects.append({**d, "via": label})

    add_deps(f"direct (model col '{column_name}')", pass1_deps)
    for fname, _fg, fdeps, _ in formula_dep_results:
        add_deps(f"via formula '{fname}'", fdeps)
    add_deps(f"table col '{physical_col}'", pass4_deps)
    add_deps("downstream of SQL view", sv_downstream)

    return {
        "column_name": column_name,
        "physical_col": physical_col,
        "unique_affected_objects": len(unique_objects),
        "objects": unique_objects,
        "broken_formulas": broken_formulas,
        "col_security_rules": len(col_security_rules),
        "broken_rls_rules": len(broken_rls),
        "broken_rls_paths": len(broken_paths),
        "broken_formula_variables": len(broken_vars),
        "broken_memory_terms": len(broken_terms),
        "affected_custom_actions": len(affected_actions),
        "broken_sql_views": len(broken_views),
        "broken_cohorts": len(broken_cohorts),
        "affected_schedules": len(broken_schedules),
        "affected_alerts": len(broken_alerts),
        "has_inaccessible_dependents": any_inaccessible,
        "not_checked": ["personalized_liveboard_views"],
    }
