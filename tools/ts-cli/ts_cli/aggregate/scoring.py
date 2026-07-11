"""Cost-based greedy aggregate selection with marginal-gain curve (pure, no I/O).

Two modes, chosen automatically from the inputs:

- **Cost mode** (``base_rows`` given and at least one candidate has been
  profiled with ``agg_rows``): marginal benefit is rows saved vs. the best
  aggregate already selected for each covered signature. This is what lets a
  nested candidate (e.g. (Sales, Category) nested inside
  (Sales, Customer, Category, State)) win a later round purely on
  compression — it adds zero *new* coverage but scans far fewer rows than
  the wider aggregate that already covers the same signatures.
- **Coverage mode** (no profiling available): marginal benefit is newly
  covered signature weight only. Nested candidates that don't cover any new
  signature score zero and are never selected — a documented degradation
  relative to cost mode, since row cost can't be compared without profiling.
"""
from __future__ import annotations

from typing import Optional


def _is_cost_mode(candidates: list, base_rows: Optional[int]) -> bool:
    return base_rows is not None and any(
        c.get("agg_rows") is not None for c in candidates)


def _total_weight(signatures: list) -> float:
    return sum(s.get("weight", 1.0) for s in signatures) or 1.0


def _eligible_candidates(candidates: list, cost_mode: bool) -> list:
    """In cost mode, unprofiled candidates (agg_rows=None) can't be costed —
    exclude them rather than let them silently score zero."""
    if not cost_mode:
        return list(candidates)
    return [c for c in candidates if c.get("agg_rows") is not None]


def _marginal_benefit(candidate: dict, signatures: list, cost_mode: bool,
                      best_rows: dict, covered_set: set,
                      base_rows: Optional[int]) -> float:
    gain = 0.0
    for i in candidate["covered"]:
        weight = signatures[i].get("weight", 1.0)
        if cost_mode:
            current_best = best_rows.get(i, base_rows)
            gain += weight * max(0, current_best - candidate["agg_rows"])
        elif i not in covered_set:
            gain += weight
    return gain


def _pick_best(remaining: list, signatures: list, cost_mode: bool,
               best_rows: dict, covered_set: set,
               base_rows: Optional[int]) -> tuple:
    """Return (gain, candidate) for the highest-scoring remaining candidate,
    ties broken by candidate id for determinism."""
    scored = sorted(
        ((_marginal_benefit(c, signatures, cost_mode, best_rows, covered_set,
                            base_rows), c["id"], c) for c in remaining),
        key=lambda t: (-t[0], t[1]),
    )
    gain, _, candidate = scored[0]
    return gain, candidate


def _apply_selection(candidate: dict, covered_set: set, best_rows: dict,
                     cost_mode: bool) -> None:
    for i in candidate["covered"]:
        covered_set.add(i)
        if cost_mode:
            current_best = best_rows.get(i, candidate["agg_rows"])
            best_rows[i] = min(current_best, candidate["agg_rows"])


def _curve_entry(candidate: dict, gain: float, covered_set: set,
                 signatures: list, total_weight: float, cost_mode: bool,
                 base_rows: Optional[int]) -> dict:
    cum_weight = sum(signatures[i].get("weight", 1.0) for i in covered_set)
    compression = None
    if cost_mode and candidate.get("agg_rows"):
        compression = round(base_rows / float(candidate["agg_rows"]), 1)
    return {
        "id": candidate["id"],
        "marginal_benefit": gain,
        "cumulative_coverage_pct": round(100.0 * cum_weight / total_weight, 1),
        "compression": compression,
    }


def greedy_select(candidates: list, signatures: list,
                  base_rows: Optional[int] = None,
                  max_select: int = 10) -> dict:
    cost_mode = _is_cost_mode(candidates, base_rows)
    total_weight = _total_weight(signatures)
    best_rows: dict = {}
    covered_set: set = set()
    selected, curve = [], []
    remaining = _eligible_candidates(candidates, cost_mode)

    while remaining and len(selected) < max_select:
        gain, pick = _pick_best(remaining, signatures, cost_mode, best_rows,
                                covered_set, base_rows)
        if gain <= 0:
            break
        selected.append(pick["id"])
        remaining = [c for c in remaining if c["id"] != pick["id"]]
        _apply_selection(pick, covered_set, best_rows, cost_mode)
        curve.append(_curve_entry(pick, gain, covered_set, signatures,
                                  total_weight, cost_mode, base_rows))

    return {
        "selected": selected,
        "curve": curve,
        "mode": "cost" if cost_mode else "coverage",
    }
