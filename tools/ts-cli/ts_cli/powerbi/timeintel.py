"""timeintel — deterministic SPLY / YoY measures via a Reference Date parameter.

Power BI's SAMEPERIODLASTYEAR / DATEADD time-intelligence has no 1:1 ThoughtSpot formula,
so `build-model` flags those measures NEEDS REVIEW rather than fake them. This module
rebuilds them from the ONE pattern verified live on the Employee Hiring migration
(agents/shared/worked-examples/powerbi/sply-parameter.md): a single `Reference Date`
model parameter that every comparison measure reads, with

    <base> for the reference year  = sum_if(year([date]) = year([Reference Date]),     <base_expr>)
    <base> same period last year   = sum_if(year([date]) = year([Reference Date]) - 1, <base_expr>)
    <base> YoY                      = [formula_<ref>] - [formula_<sply>]
    <base> YoY %                    = safe_divide([formula_<yoy>], [formula_<sply>])

It is measure-based (the measures live in the model and tiles reference them), which is
what renders — as opposed to a period-comparison search tile, whose resolved column
structure cannot be hand-authored without reproducing the "No data source found" trap.

Deterministic and generic for a measure whose row-level body (`base_expr`) is known — the
caller supplies it (from the base measure `build-model` already translated). It NEVER
invents numbers: the emitted measures are shown to a human to verify against the source
before adoption, exactly like the flagged originals.

Pure functions, no I/O.
"""
from __future__ import annotations

from typing import Any, Optional

# Default matches the worked example; a real migration overrides it to the source's as-of date.
DEFAULT_REF_DATE = "12/31/2024"

REFERENCE_DATE_PARAM = "Reference Date"


def _fid(name: str) -> str:
    """A formula's id-reference token, matching build-model's `formula_<name>` convention."""
    return f"[formula_{name}]"


def sply_expr(date_column: str, base_expr: str, *, offset: int) -> str:
    """The sum_if body for a year-offset comparison. offset 0 = reference year, 1 = SPLY.

    `date_column` is the model column display name (e.g. "Date"); `base_expr` is the
    row-level body being summed (e.g. "[formula_isNewHire]" for a count-of-flag measure,
    or "Sales" for a plain additive measure)."""
    year_of_ref = f"year([{REFERENCE_DATE_PARAM}])"
    rhs = year_of_ref if offset == 0 else f"{year_of_ref} - {offset}"
    return f"sum_if(year([{date_column}]) = {rhs}, {base_expr})"


def build_time_intelligence(
    specs: list,
    date_column: str,
    ref_date_default: str = DEFAULT_REF_DATE,
) -> dict:
    """Build the Reference Date parameter + SPLY/YoY measures for a set of base measures.

    ``specs`` is a list of dicts, each:
        {"base_name": "New Hires",           # display name of the migrated base measure
         "base_expr": "[formula_isNewHire]",  # its row-level body to sum_if over
         "sply_name": "New Hires SPLY",       # optional; default "<base_name> SPLY"
         "yoy_name": "New Hires YoY",         # optional; default "<base_name> YoY"
         "yoy_pct_name": "New Hires YoY %"}   # optional; default "<base_name> YoY %"

    Returns ``{"parameter": {...}, "formulas": [...], "columns": [...], "review": [...]}``
    ready to merge into a Model TML: one parameter, and per base measure a reference-year,
    SPLY, YoY and YoY% formula (each with its MEASURE column entry). ``review`` lists the
    human-verify notes (one per emitted comparison set) — never adopt without checking the
    numbers against the source. A spec missing ``base_expr`` is skipped into ``review`` with
    a reason rather than guessed."""
    parameter = {
        "name": REFERENCE_DATE_PARAM,
        "data_type": "DATE",
        "default_value": ref_date_default,
    }
    formulas: list = []
    columns: list = []
    review: list = []
    seen: set = set()

    def _emit(name: str, expr: str) -> None:
        if name in seen:
            review.append(f"'{name}' collides with an existing measure name — skipped, resolve by hand")
            return
        seen.add(name)
        formulas.append({"name": name, "expr": expr})
        columns.append({
            "name": name,
            "formula_id": f"formula_{name}",
            "properties": {"column_type": "MEASURE", "aggregation": "NONE"},
        })

    for spec in specs:
        base = spec.get("base_name")
        base_expr = spec.get("base_expr")
        if not base or not base_expr:
            review.append(f"time-intelligence spec {spec!r} missing base_name/base_expr — NEEDS REVIEW, not emitted")
            continue
        ref_name = f"{base} Ref Yr"
        sply_name = spec.get("sply_name") or f"{base} SPLY"
        yoy_name = spec.get("yoy_name") or f"{base} YoY"
        pct_name = spec.get("yoy_pct_name") or f"{base} YoY %"

        _emit(ref_name, sply_expr(date_column, base_expr, offset=0))
        _emit(sply_name, sply_expr(date_column, base_expr, offset=1))
        _emit(yoy_name, f"{_fid(ref_name)} - {_fid(sply_name)}")
        _emit(pct_name, f"safe_divide({_fid(yoy_name)}, {_fid(sply_name)})")
        review.append(
            f"'{base}': emitted {ref_name} / {sply_name} / {yoy_name} / {pct_name} "
            f"via Reference Date={ref_date_default}. VERIFY per-period numbers vs the Power BI source."
        )

    return {"parameter": parameter, "formulas": formulas, "columns": columns, "review": review}


def merge_into_model(model: dict, built: dict) -> dict:
    """Merge a build_time_intelligence() result into a Model TML dict in place.

    Adds the parameter (unless a same-named one already exists) and appends the formulas +
    MEASURE columns. Returns the mutated model for chaining."""
    params = model.setdefault("parameters", [])
    if not any(p.get("name") == built["parameter"]["name"] for p in params):
        params.append(built["parameter"])
    model.setdefault("formulas", []).extend(built["formulas"])
    model.setdefault("columns", []).extend(built["columns"])
    return model
