"""Dependency-DAG and cross-reference resolution for Tableau calculated fields.

Pure functions, no I/O. Two independent fixpoint loops live here:

- ``build_dependency_dag`` / ``resolve_cross_references`` / ``build_calc_id_map``
  — used by the formula translator (tableau_translate.py). Only matches
  ``[Calculation_\\d+]`` references.
- ``build_formula_levels`` / ``resolve_all_internal_refs`` — used by the model
  builder (model_builder.py). Matches ALL bracketed refs, including copy-style
  ``[Field Name (copy)_NNN]`` references.

These loops are deliberately kept separate — see the NOTE on
``build_formula_levels`` below.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# 1. Dependency DAG — cross-reference resolution
# ---------------------------------------------------------------------------

def build_dependency_dag(
    formulas: list[dict],
) -> dict[str, dict]:
    """Build a map from formula caption → {formula, deps, level, resolved_expr}.

    Each formula dict must have 'caption' and 'formula' keys.
    A dependency is any [Calculation_NNNN] reference in the formula text.
    """
    _CALC_REF = re.compile(r"\[Calculation_\d+\]", re.IGNORECASE)

    by_name: dict[str, dict] = {}
    by_calc_id: dict[str, str] = {}

    for f in formulas:
        caption = f.get("caption", "")
        raw = f.get("formula", "")
        name = f.get("name", caption)
        # 'name' in classification.json is the Tableau internal name (e.g. Calculation_123)
        # 'caption' is the display name
        if name and name.startswith("Calculation_"):
            by_calc_id[f"[{name}]"] = caption

        by_name[caption] = {
            "formula": f,
            "raw": raw,
            "deps": set(),
            "level": -1,
            "resolved_expr": None,
        }

    # Find dependencies
    for caption, entry in by_name.items():
        refs = _CALC_REF.findall(entry["raw"])
        for ref in refs:
            dep_caption = by_calc_id.get(ref)
            if dep_caption and dep_caption != caption:
                entry["deps"].add(dep_caption)
            elif ref.strip("[]") != caption:
                # Unknown calc ref — record as unresolvable
                entry["deps"].add(ref)

    # Topological sort — assign levels
    changed = True
    while changed:
        changed = False
        for caption, entry in by_name.items():
            if entry["level"] >= 0:
                continue
            if not entry["deps"]:
                entry["level"] = 0
                changed = True
            elif all(
                by_name.get(d, {}).get("level", -1) >= 0
                for d in entry["deps"]
                if not d.startswith("[Calculation_")
            ):
                max_dep = max(
                    (by_name[d]["level"] for d in entry["deps"]
                     if d in by_name and by_name[d]["level"] >= 0),
                    default=0,
                )
                entry["level"] = max_dep + 1
                changed = True

    # Mark remaining as circular or unresolvable
    for entry in by_name.values():
        if entry["level"] < 0:
            entry["level"] = -1  # circular / unresolvable

    return by_name


def resolve_cross_references(
    expr: str,
    dag: dict[str, dict],
    by_calc_id: dict[str, str],
    max_depth: int = 10,
) -> str:
    """Replace [Calculation_NNN] references with the referenced formula's expression.

    Inlines recursively up to max_depth. Returns the resolved expression.
    """
    _CALC_REF = re.compile(r"\[Calculation_\d+\]", re.IGNORECASE)

    for _ in range(max_depth):
        refs = _CALC_REF.findall(expr)
        if not refs:
            break
        replaced_any = False
        for ref in refs:
            dep_caption = by_calc_id.get(ref)
            # Fallback: try normalized (case-insensitive) lookup
            if dep_caption is None:
                norm_ref = re.sub(r"\s+", " ", ref).lower()
                dep_caption = by_calc_id.get(norm_ref)
            if dep_caption and dep_caption in dag:
                dep_entry = dag[dep_caption]
                replacement = dep_entry.get("resolved_expr") or dep_entry["raw"]
                if replacement and "[Calculation_" not in replacement:
                    expr = expr.replace(ref, f"({replacement})")
                    replaced_any = True
                elif replacement:
                    # Try partial replacement
                    expr = expr.replace(ref, f"({replacement})")
                    replaced_any = True
            else:
                # Can't resolve — replace with display name if available
                caption = by_calc_id.get(ref)
                if caption:
                    expr = expr.replace(ref, f"[{caption}]")
                    replaced_any = True
        if not replaced_any:
            break

    return expr


def build_calc_id_map(formulas: list[dict]) -> dict[str, str]:
    """Build [Calculation_NNN] → caption map from formula list.

    Stores both the original-case key and a normalized (lowercase, whitespace-
    collapsed) key so that lookups are case-insensitive and whitespace-tolerant.
    """
    result: dict[str, str] = {}
    for f in formulas:
        name = f.get("name", "")
        caption = f.get("caption", "")
        if name and name.startswith("Calculation_") and caption:
            key = f"[{name}]"
            result[key] = caption
            # Also store normalized version for case-insensitive matching
            norm_key = re.sub(r"\s+", " ", key).lower()
            if norm_key != key.lower():
                result[norm_key] = caption
    return result


# ---------------------------------------------------------------------------
# Dependency level computation (must run BEFORE resolve_all_internal_refs)
# ---------------------------------------------------------------------------

# NOTE: near-duplicate of build_dependency_dag — evaluated 2026-07-03, kept
# separate deliberately (different ref universe, unresolvable handling, and
# return shape). See docs/backlog.md BL-069 follow-ups for the full rationale.
def build_formula_levels(
    calcs: list[dict],
    calc_map: dict[str, str],
) -> dict[str, int]:
    """Build dependency levels from raw (pre-resolved) calculated fields.

    Must be called BEFORE resolve_all_internal_refs — it relies on the
    original [Calculation_NNN] and copy-style [Field (copy)_NNN] refs
    still being present in the formula text.

    Matches ALL bracketed refs against the calc_map to detect dependencies,
    unlike build_dependency_dag which only matches [Calculation_\\d+].
    """
    all_captions = {c.get("caption", "") for c in calcs if c.get("caption")}

    bracket_to_caption: dict[str, str] = {}
    for key, caption in calc_map.items():
        bracketed = f"[{key}]" if not key.startswith("[") else key
        bracket_to_caption[bracketed] = caption

    caption_deps: dict[str, set[str]] = {}
    for c in calcs:
        caption = c.get("caption", "")
        formula = c.get("formula", "")
        deps: set[str] = set()
        for ref in re.findall(r"\[[^\]]+\]", formula):
            dep_caption = bracket_to_caption.get(ref)
            if dep_caption and dep_caption != caption and dep_caption in all_captions:
                deps.add(dep_caption)
        caption_deps[caption] = deps

    levels: dict[str, int] = {}
    changed = True
    while changed:
        changed = False
        for caption, deps in caption_deps.items():
            if caption in levels:
                continue
            if not deps:
                levels[caption] = 0
                changed = True
            elif all(d in levels for d in deps):
                max_dep = max(levels[d] for d in deps)
                levels[caption] = max_dep + 1
                changed = True

    for caption in caption_deps:
        if caption not in levels:
            levels[caption] = 0

    return levels


# ---------------------------------------------------------------------------
# Pre-translation: resolve ALL internal references to display names
# ---------------------------------------------------------------------------

def resolve_all_internal_refs(
    calcs: list[dict],
    calc_map: dict[str, str],
) -> list[dict]:
    """Replace ALL internal refs ([Calculation_NNN] and copy-style) with captions.

    Tableau TWBs use two reference styles:
      [Calculation_1234567890] — original calc field
      [Field Name (copy)_1234567890] — copied from another datasource

    The existing translate pipeline only resolves [Calculation_NNN].
    This function resolves BOTH by substituting any bracketed reference
    that matches a calc_map key with the corresponding caption.

    Returns a new list of calcs with resolved formulas (caption field).
    """
    bracket_map = {}
    for internal, caption in calc_map.items():
        bracket_map[f"[{internal}]"] = f"[{caption}]"

    resolved = []
    for c in calcs:
        formula = c.get("formula", "")
        for internal_ref, caption_ref in bracket_map.items():
            if internal_ref in formula:
                formula = formula.replace(internal_ref, caption_ref)
        entry = dict(c)
        entry["formula"] = formula
        resolved.append(entry)
    return resolved
