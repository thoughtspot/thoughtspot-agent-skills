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


# ---------------------------------------------------------------------------
# 20. Substitute/flag Tableau parameters embedded in Custom SQL (BL-093)
# ---------------------------------------------------------------------------

_SQL_VIEW_PARAM_RE = re.compile(r"<\[Parameters\]\.\[([^\]]+)\]>")


def substitute_sql_view_parameters(
    sql_views: list[dict],
    parameters: list[dict],
) -> list[dict]:
    """Resolve ``<[Parameters].[Name]>`` tokens embedded in Custom SQL.

    Tableau lets a Custom SQL body reference a workbook parameter inline as
    ``<[Parameters].[Name]>``. That token is not valid warehouse SQL, so the
    emitted ``sql_view.sql_query`` fails at ThoughtSpot import until it's
    resolved. Each ``sv["sql_query"]`` in ``sql_views`` is mutated in place:

    - a token naming a parameter present in ``parameters`` (as returned by
      ``extract_parameters()``) has that parameter's default value
      substituted in — the SQL is now valid, but the value is static (no
      longer a live parameter), which is recorded as a warning.
    - a token naming a parameter not found in ``parameters`` gets a
      NEEDS-REVIEW warning instead and is left untouched (nothing safe to
      substitute) — never silently passed through to import.

    Returns the per-SQL-View warning list: ``[{"name": <sql_view_name>,
    "warnings": [...]}, ...]`` (same shape as ``validate_pre_import``'s
    return), empty when no SQL View embeds a ``<[Parameters]...>`` token.
    """
    param_defaults = {p["name"]: p.get("default_value", "") for p in parameters}
    issues: list[dict] = []

    for sv in sql_views:
        sql = sv.get("sql_query", "")
        if not sql or "<[Parameters]" not in sql:
            continue

        warnings: list[str] = []

        def _resolve(m: "re.Match[str]") -> str:
            pname = m.group(1)
            if pname in param_defaults:
                default = param_defaults[pname]
                warnings.append(
                    f"Parameter default inlined into Custom SQL: [{pname}] -> {default!r} "
                    "(value is now static, not a live parameter)"
                )
                return default
            warnings.append(
                f"NEEDS-REVIEW: unresolved Tableau parameter token "
                f"<[Parameters].[{pname}]> in Custom SQL — no matching parameter parsed; "
                "resolve manually before import"
            )
            return m.group(0)

        sv["sql_query"] = _SQL_VIEW_PARAM_RE.sub(_resolve, sql)
        if warnings:
            issues.append({"name": sv.get("name", ""), "warnings": warnings})

    return issues
