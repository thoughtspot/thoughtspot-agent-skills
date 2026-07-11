"""Grain lattice: coverage rule + candidate generation (pure, no I/O)."""
from __future__ import annotations

from typing import Optional

BUCKETS = ["HOURLY", "DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY"]


def bucket_covers(grain_bucket: Optional[str], sig_bucket: Optional[str]) -> bool:
    """Finer-or-equal grain serves coarser query. None grain = raw dates (serves all);
    None sig bucket = detail-date query (needs raw dates). Re-aggregation assumption
    is Open Item #1 — fallback is equality-only matching."""
    if grain_bucket is None:
        return True
    if sig_bucket is None:
        return False
    return BUCKETS.index(grain_bucket) <= BUCKETS.index(sig_bucket)


def covers(candidate: dict, sig: dict, plans: dict) -> bool:
    dims = set(candidate["dimensions"])
    if not set(sig["dimensions"]) <= dims:
        return False
    if not set(sig["filter_columns"]) <= dims | {sig.get("date_column")}:
        return False
    if sig.get("date_column"):
        if candidate.get("date_column") != sig["date_column"]:
            return False
        if not bucket_covers(candidate.get("bucket"), sig.get("date_bucket")):
            return False
    for m in sig["measures"]:
        plan = plans.get(m)
        if plan is None:
            return False
        if not plan["decomposable"]:
            req = plan.get("requires_grain_column")
            if not req or req not in dims:
                return False
    return True


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / float(len(a | b))


def _base_dimsets(usable: list) -> set:
    """Base dim-sets (dims + non-date filter columns), keyed by date column."""
    base = set()
    for _, s in usable:
        dset = frozenset(set(s["dimensions"]) |
                         (set(s["filter_columns"]) - {s.get("date_column")}))
        base.add((dset, s.get("date_column")))
    return base


def _merge_similar_dimsets(base: set, jaccard_threshold: float) -> set:
    """Pairwise unions of similar dim-sets sharing the same date column."""
    merged = set(base)
    items = sorted(base, key=lambda x: (sorted(x[0]), x[1] or ""))
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (d1, dc1), (d2, dc2) = items[i], items[j]
            if dc1 == dc2 and _jaccard(d1, d2) >= jaccard_threshold:
                merged.add((d1 | d2, dc1))
    return merged


def _finest_bucket(cand: dict, usable: list, plans: dict) -> Optional[str]:
    """Finest bucket required among sigs this dimset+datecol could cover."""
    trial = dict(cand)
    finest = None
    for _, s in usable:
        trial["bucket"] = s.get("date_bucket")
        if covers(trial, s, plans) and s.get("date_bucket"):
            idx = BUCKETS.index(s["date_bucket"])
            finest = idx if finest is None else min(finest, idx)
    return BUCKETS[finest] if finest is not None else None


def _cover_candidate(cand: dict, usable: list, plans: dict) -> None:
    """Populate cand['covered'] and cand['measure_columns'] in place."""
    measures = set()
    for i, s in usable:
        if covers(cand, s, plans):
            cand["covered"].append(i)
            measures.update(s["measures"])
    cand["measure_columns"] = sorted(measures)


def generate_candidates(signatures: list, plans: dict,
                        jaccard_threshold: float = 0.5,
                        max_width: int = 8) -> list:
    usable = [(i, s) for i, s in enumerate(signatures)
              if s.get("parse_status") == "full"]
    base = _base_dimsets(usable)
    merged = _merge_similar_dimsets(base, jaccard_threshold)
    candidates = []
    for n, (dims, date_col) in enumerate(sorted(
            merged, key=lambda x: (len(x[0]), sorted(x[0]), x[1] or ""))):
        cand = {"id": f"cand_{n + 1}", "dimensions": sorted(dims),
                "date_column": date_col, "bucket": None,
                "covered": [], "flags": [], "agg_rows": None,
                "measure_columns": []}
        if date_col:
            cand["bucket"] = _finest_bucket(cand, usable, plans)
        _cover_candidate(cand, usable, plans)
        if len(cand["dimensions"]) > max_width:
            cand["flags"].append("wide_grain")
        if cand["covered"]:
            candidates.append(cand)
    return candidates
