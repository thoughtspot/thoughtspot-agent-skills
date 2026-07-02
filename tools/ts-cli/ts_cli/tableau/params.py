"""Tableau parameter handling — prefix stripping, name mapping, conflict
detection, and sanitisation.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# 2. Parameter handling
# ---------------------------------------------------------------------------

def strip_parameter_prefix(expr: str) -> str:
    """[Parameters].[X] → [X]"""
    return re.sub(
        r"\[Parameters\]\.\[([^\]]+)\]",
        r"[\1]",
        expr,
        flags=re.IGNORECASE,
    )


def map_parameter_names(
    expr: str,
    param_map: dict[str, str],
) -> str:
    """Replace internal parameter names with display captions.

    param_map: {"Parameter 3 1": "Metric"} — internal name → caption.
    """
    for internal, caption in param_map.items():
        expr = expr.replace(f"[{internal}]", f"[{caption}]")
    return expr


# ---------------------------------------------------------------------------
# 16. Parameter name conflict detection
# ---------------------------------------------------------------------------

def detect_param_conflicts(
    formulas: list[dict],
    parameters: list[dict],
) -> dict[str, str]:
    """Detect formula names that collide with parameter names.

    Returns: { formula_caption: "conflict_reason" }
    """
    param_names = set()
    for p in parameters:
        caption = p.get("caption", p.get("name", ""))
        if caption:
            param_names.add(caption)

    conflicts: dict[str, str] = {}
    for f in formulas:
        caption = f.get("caption", "")
        if caption in param_names:
            raw = f.get("formula", "").strip()
            # Check if it's a pass-through (just returns the parameter)
            stripped = strip_parameter_prefix(raw)
            if stripped.strip() == f"[{caption}]" or stripped.strip() == caption:
                conflicts[caption] = "pass-through — omit formula, use parameter directly"
            else:
                conflicts[caption] = "name collision — rename formula"

    return conflicts


# ---------------------------------------------------------------------------
# 19. Parameter name sanitisation (BL-050 #6)
# ---------------------------------------------------------------------------

_PARAM_UNSAFE = re.compile(r"[/\\:*?\"<>|]")

def sanitise_parameter_name(name: str) -> str:
    """Remove characters not allowed in ThoughtSpot parameter names."""
    return _PARAM_UNSAFE.sub(" ", name).strip()


def sanitise_parameter_refs(
    expr: str,
    param_renames: dict[str, str],
) -> str:
    """Rewrite formula references to use sanitised parameter names.

    param_renames: {"Platform/Placement": "Platform Placement", ...}
    """
    for old_name, new_name in param_renames.items():
        expr = expr.replace(f"[{old_name}]", f"[{new_name}]")
    return expr


def build_param_renames(parameters: list[dict]) -> dict[str, str]:
    """Detect parameters needing sanitisation and build a rename map.

    Returns: { original_name: sanitised_name } for names that changed.
    """
    renames: dict[str, str] = {}
    for p in parameters:
        caption = p.get("caption", p.get("name", ""))
        if caption and _PARAM_UNSAFE.search(caption):
            renames[caption] = sanitise_parameter_name(caption)
    return renames
