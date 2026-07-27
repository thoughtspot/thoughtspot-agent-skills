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


def _sig_date_grains(sig: dict) -> list:
    """Signature's date grains (Task 14). Falls back to a single-entry list
    derived from the shim fields (date_column/date_bucket) when date_grains
    is absent — keeps hand-built single-date sig dicts (existing callers/
    tests) working unchanged."""
    grains = sig.get("date_grains")
    if grains is not None:
        return grains
    col = sig.get("date_column")
    return [{"column": col, "bucket": sig.get("date_bucket")}] if col else []


def _cand_date_grains(candidate: dict) -> list:
    """Candidate's date grains (Task 14); same shim fallback as _sig_date_grains."""
    grains = candidate.get("date_grains")
    if grains is not None:
        return grains
    col = candidate.get("date_column")
    return [{"column": col, "bucket": candidate.get("bucket")}] if col else []


def covers(candidate: dict, sig: dict, plans: dict) -> bool:
    dims = set(candidate["dimensions"])
    if not set(sig["dimensions"]) <= dims:
        return False
    sig_grains = _sig_date_grains(sig)
    sig_date_cols = {g["column"] for g in sig_grains}
    if not set(sig["filter_columns"]) <= dims | sig_date_cols:
        return False
    cand_buckets = {g["column"]: g["bucket"] for g in _cand_date_grains(candidate)}
    for g in sig_grains:
        if g["column"] not in cand_buckets:
            return False  # candidate lacks this date column entirely
        if not bucket_covers(cand_buckets[g["column"]], g["bucket"]):
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
    """Base dim-sets (dims + non-date filter columns), keyed by the sig's
    full set of date columns (Task 14: was keyed by a single date column)."""
    base = set()
    for _, s in usable:
        sig_date_cols = frozenset(g["column"] for g in _sig_date_grains(s))
        dset = frozenset(set(s["dimensions"]) |
                         (set(s["filter_columns"]) - sig_date_cols))
        base.add((dset, sig_date_cols))
    return base


def _merge_similar_dimsets(base: set, jaccard_threshold: float) -> set:
    """Pairwise unions of similar dim-sets sharing the same date-column set."""
    merged = set(base)
    items = sorted(base, key=lambda x: (sorted(x[0]), sorted(x[1])))
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (d1, dc1), (d2, dc2) = items[i], items[j]
            if dc1 == dc2 and _jaccard(d1, d2) >= jaccard_threshold:
                merged.add((d1 | d2, dc1))
    return merged


def _finest_bucket_for_column(dims: frozenset, date_cols: frozenset, column: str,
                              usable: list, plans: dict) -> Optional[str]:
    """Finest bucket required for `column` among sigs this dims+date_cols
    group could cover. Other candidate date columns are held permissive
    (raw/None) while testing so each column's requirement is derived
    independently of the others (generalizes the single-date _finest_bucket).

    A coverable detail-date sig (bucket=None) on `column` needs raw dates —
    it forces this column to bucket=None."""
    trial = {"dimensions": sorted(dims),
             "date_grains": [{"column": c, "bucket": None} for c in date_cols]}
    finest = None
    for _, s in usable:
        sig_bucket, has_col = None, False
        for g in _sig_date_grains(s):
            if g["column"] == column:
                sig_bucket, has_col = g["bucket"], True
                break
        for g in trial["date_grains"]:
            if g["column"] == column:
                g["bucket"] = sig_bucket
        if not covers(trial, s, plans):
            continue
        if not has_col:
            continue  # sig doesn't require this column: imposes no requirement
        if sig_bucket is None:
            return None  # detail-date query: raw dates are the finest requirement
        idx = BUCKETS.index(sig_bucket)
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


def _consolidated_dimsets(base: set, consolidatable: set, max_width: int) -> set:
    """One consolidated dim-set per date-column group: the union of all base
    dims that are **safe to consolidate** (F3).

    `_merge_similar_dimsets` only unions dim-sets that already OVERLAP (Jaccard
    >= threshold), so a model whose dependents each group by a *different*
    single dimension never yields the combined ("one wide table") grain — the
    highest-value aggregate. This adds it: per date-column set, union the base
    dims restricted to `consolidatable` (the caller passes the model's PHYSICAL
    attribute columns — column_id-backed — so formula dimensions like a
    concat(...) employee name, which can't be stored/joined in an aggregate,
    and date columns are excluded). Capped at `max_width`. Cross-fact
    infeasible grains are not special-cased here — the join walker / AgentQL
    generation fails closed on them downstream (never a silent wrong number).
    Only emits a set when it actually combines >1 dim."""
    from collections import defaultdict
    by_date: dict = defaultdict(set)
    for dset, date_cols in base:
        by_date[date_cols] |= (set(dset) & consolidatable)
    out = set()
    for date_cols, dims in by_date.items():
        if 1 < len(dims) <= max_width:
            out.add((frozenset(dims), date_cols))
    return out


def generate_candidates(signatures: list, plans: dict,
                        jaccard_threshold: float = 0.5,
                        max_width: int = 8,
                        consolidatable_dims: Optional[set] = None) -> list:
    usable = [(i, s) for i, s in enumerate(signatures)
              if s.get("parse_status") == "full"]
    base = _base_dimsets(usable)
    merged = _merge_similar_dimsets(base, jaccard_threshold)
    if consolidatable_dims:
        merged |= _consolidated_dimsets(base, consolidatable_dims, max_width)
    candidates = []
    for n, (dims, date_cols) in enumerate(sorted(
            merged, key=lambda x: (len(x[0]), sorted(x[0]), sorted(x[1])))):
        date_grains = [
            {"column": c, "bucket": _finest_bucket_for_column(dims, date_cols, c, usable, plans)}
            for c in sorted(date_cols)
        ]
        cand = {"id": f"cand_{n + 1}", "dimensions": sorted(dims),
                "date_column": date_grains[0]["column"] if date_grains else None,
                "bucket": date_grains[0]["bucket"] if date_grains else None,
                "date_grains": date_grains,
                "covered": [], "flags": [], "agg_rows": None,
                "measure_columns": []}
        _cover_candidate(cand, usable, plans)
        if len(cand["dimensions"]) > max_width:
            cand["flags"].append("wide_grain")
        if cand["covered"]:
            candidates.append(cand)
    return candidates
