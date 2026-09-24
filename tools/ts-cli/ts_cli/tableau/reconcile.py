# tools/ts-cli/ts_cli/tableau/reconcile.py
"""Reconcile Tableau-parsed columns/formulas against a real target schema.

Pure functions, no I/O. Tier 1 (clean_*) is always-safe and needs no schema;
Tier 2 (suggest_column_mappings / apply_reconciliation, Task 2) needs the target
table's real column names.
"""
from __future__ import annotations
import re

_SUFFIX = re.compile(r"\s*\(Custom SQL Query\d+\)")
_JUNK = "__tableau_internal_object_id__"

# Tableau's own internal pseudo-fields, which arrive as ordinary `<column>`
# elements but name no warehouse column. Emitting one produces a Model column
# whose `column_id` resolves to nothing — `:Measure Names` alone accounted for
# every I12 `ts tml lint` finding (a bare `column_id` ThoughtSpot rejects at
# import), plus the same column table-qualified (`TABLE:::Measure Names`) on
# multi-table models, where I12 is scoped out and nothing flagged it at all.
#
# The members are Tableau's pivot pair: `dashboards.py` reads them together off
# a shelf (`[Multiple Values]`/`[:Measure Names]`), which is the in-repo
# evidence for the second one.
#
# Matched by EQUALITY, not as a substring like _JUNK (which arrives decorated,
# `__tableau_internal_object_id__].[agg_booked_monthly (…)_HASH`) and not by
# leading-colon prefix: a colon is Tableau's marker, but a prefix rule would
# reach past the evidence and a real column is only ever one false positive
# away. Add a member to `_PSEUDO_FIELDS` when another is actually observed —
# see the constants note below before touching `_PIVOT_PSEUDO_FIELDS`.
#
# The two do NOT carry the same false-positive risk, and only one is self-
# marking. `:Measure Names` leads with Tableau's colon, so no user column
# collides with it by accident. `Multiple Values` does not — it is a name a
# user could legitimately choose. `dashboards.py` can afford that because it
# tests the token against SHELF TEXT and the context disambiguates; this layer
# sees a bare column list with no such context, so it matches on name alone.
# Taken deliberately: the string is Tableau's own, and left unfiltered it emits
# a phantom `TABLE::Multiple Values` no gate sees — I12 reads only a BARE
# column_id, and the cross-reference check resolves because the same phantom is
# written into the Table TML.
#
# `Number of Records` is deliberately NOT here, and the reason is not the one it
# looks like. Tableau's built-in one is a CALCULATED field, and `_extract_columns`
# skips any `<column>` carrying a `<calculation>` child before this runs — so it
# never reaches this predicate at all. A warehouse column genuinely named that is
# not a calculated field, does reach here, and must survive.
#
# Two DISTINCT meanings, deliberately separate constants:
#
#   _PIVOT_PSEUDO_FIELDS — one of these appearing in a worksheet's raw shelf text
#     means "this worksheet is a Measure Values pivot". `dashboards.py` reads it
#     as a TRIGGER.
#   _PSEUDO_FIELDS       — these must never be emitted as real columns.
#
# They coincide today because the pivot pair is also the whole exclusion set. A
# future filter-only member belongs in _PSEUDO_FIELDS alone: adding it to the
# pivot pair would make an unrelated token fire the measure-values branch and
# pull every column-instance into a worksheet's field list.
_PIVOT_PSEUDO_FIELDS = frozenset({":Measure Names", "Multiple Values"})

_PSEUDO_FIELDS = _PIVOT_PSEUDO_FIELDS   # | {"<filter-only member>"} — extend HERE, not above


def _is_internal_column(raw: str) -> bool:
    """True for a Tableau-internal column that must never reach emitted TML.

    Shared by ``clean_column_name`` (single-table path), ``drop_junk_columns``
    (multi-table path) and ``dashboards.py``'s field assembly, so they cannot
    drift — the parse records the marker in BOTH ``name`` and
    ``db_column_name``, so either key may be the one passed in.

    The ``_SUFFIX``-normalised form is tested as well, still by EQUALITY. Nothing
    in this repo shows Tableau decorating a pseudo-field, so this is defensive:
    ``clean_column_name`` strips that suffix AFTER this check, so a decorated one
    would be stripped back to the exact string the filter exists to remove, while
    ``drop_junk_columns`` (which never strips) kept a third spelling.
    """
    return (_JUNK in raw
            or raw in _PSEUDO_FIELDS
            or _SUFFIX.sub("", raw).strip() in _PSEUDO_FIELDS)


# The same members as a bracketed REFERENCE, for scanning formula expressions.
_PSEUDO_REFS = frozenset(f"[{tok}]" for tok in _PSEUDO_FIELDS)


def _references_internal_column(expr: str) -> bool:
    """True when a formula expression references a column that never reaches TML.

    Reference matching, not the name matching ``_is_internal_column`` does: a
    pseudo-field is matched there by EQUALITY against a column name, so passing an
    expression to it returns False for every member. Matching the BRACKETED form
    keeps the false-positive discipline the name path has — ``[Multiple Values]``
    cannot occur inside ``[My Multiple Values]``.
    """
    return _JUNK in expr or any(ref in expr for ref in _PSEUDO_REFS)


def clean_column_name(name: str | None) -> str | None:
    if not name or _is_internal_column(name):
        return None
    cleaned = _SUFFIX.sub("", name).strip()
    return cleaned or None


def strip_suffix_in_expr(expr: str) -> str:
    return _SUFFIX.sub("", expr)


def clean_columns(columns: list[dict], table_name: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for c in columns:
        db = clean_column_name(c.get("db_column_name") or c.get("name"))
        if db is None:
            continue
        if db in seen:
            continue
        seen.add(db)
        nc = dict(c)
        nc["db_column_name"] = db
        nc["name"] = clean_column_name(c.get("name")) or db
        nc["table"] = table_name
        out.append(nc)
    return out


def drop_junk_columns(columns: list[dict]) -> list[dict]:
    """Drop Tableau-internal columns — ``__tableau_internal_object_id__`` junk
    and the pseudo-fields in ``_PSEUDO_FIELDS`` (see ``_is_internal_column``)
    — (Fix #A — multi-table companion to clean_columns).

    clean_columns() does this too, but it ALSO stamps every surviving column
    onto one ``table_name`` and dedupes by db_column_name within that single
    table — both wrong on a multi-table datasource, where columns legitimately
    belong to different tables (stamping them all onto one would mis-qualify
    every column not actually owned by it) and two different tables can
    legitimately share a bare column name (deduping globally would silently
    drop one of them). This is the narrow, table-blind half of that cleanup:
    it only removes the junk, leaving each column's own ``table``/ownership
    untouched. Order-preserving; matches on db_column_name (falling back to
    name) the same way clean_column_name does.
    """
    out: list[dict] = []
    for c in columns:
        raw = c.get("db_column_name") or c.get("name")
        if raw and _is_internal_column(raw):
            continue
        out.append(c)
    return out


def _tokens(s: str) -> set[str]:
    return {t for t in s.upper().replace("-", "_").split("_") if t}


def suggest_column_mappings(absent: list[str], target: set[str]) -> list[dict]:
    targets = sorted(target)
    out: list[dict] = []
    for a in absent:
        au = a.upper()
        best, best_score = None, 0.0
        for t in targets:
            tu = t.upper()
            if au == tu:
                score = 1.0
            elif tu == "DM_" + au or au == "DM_" + tu or tu.endswith("_" + au) or au.endswith("_" + tu):
                score = 0.9
            else:
                ta, tt = _tokens(a), _tokens(t)
                score = len(ta & tt) / len(ta | tt) if (ta | tt) else 0.0
            if score > best_score:
                best, best_score = t, score
        if best is not None and best_score > 0.5:
            out.append({"from": a, "to": best, "confidence": round(best_score, 2)})
    return out


def validate_name_map(name_map: dict[str, str]) -> str | None:
    """Validate a --column-name-map for a rename chain or convergent targets.
    Returns an error message if invalid, None if OK.

    apply_reconciliation rewrites renamed-column formula refs by applying
    name_map pairs sequentially on a mutating expression string:
    - A chain (A -> B, B -> C) would corrupt that rewrite (A ends up
      rewritten to C via B, or vice versa depending on dict order), since
      the first substitution's output becomes the second's input.
    - A convergent map (A -> X, B -> X) would collide two source columns
      into one column_id in the emitted model TML ("column_id values are
      incorrect" on import). apply_reconciliation's post-condition dedupe
      is defense-in-depth for this; failing fast here is a clearer error.

    suggest_column_mappings never produces either shape by construction, but
    this file is user-supplied, so validate it explicitly rather than trust it.
    """
    chained = set(name_map.keys()) & set(name_map.values())
    if chained:
        return (
            "reconcile: --column-name-map contains a rename chain — "
            f"{sorted(chained)} appear as both a source and a target. "
            "Chained renames would corrupt formula rewriting; split them "
            "into independent mappings."
        )
    targets = list(name_map.values())
    convergent = {t for t in targets if targets.count(t) > 1}
    if convergent:
        return (
            "reconcile: --column-name-map maps multiple columns to the same "
            f"target: {sorted(convergent)} — map at most one source column "
            "to each target."
        )
    return None


def drop_junk_formulas(formulas: list[dict]) -> tuple[list[dict], list[str]]:
    """Drop any formula whose expr references a __tableau_internal_object_id__
    junk column, or any member of ``_PSEUDO_FIELDS`` (Tier-1 companion to
    clean_columns, which drops those COLUMNS but leaves formulas referencing
    them dangling)."""
    kept: list[dict] = []
    dropped: list[str] = []
    for f in formulas:
        if _references_internal_column(f.get("expr", "")):
            dropped.append(f["name"])
        else:
            kept.append(f)
    return kept, dropped


def rewrite_expr_refs(expr: str, name_map: dict[str, str]) -> str:
    """Rewrite bracketed column refs in a formula expression by ``name_map``.

    Rewrites ``[old]`` -> ``[new]`` and ``[table::old]`` -> ``[table::new]``.
    Whole-token only: a mapping for ``DISCOUNT_RED_DOLLAR`` never touches
    ``DISCOUNT_RED_DOLLAR_PCT`` (the ``[...]`` match is on the full bracket
    content; the ``::`` match is word-bounded). Idempotent — applying an
    already-rewritten expression is a no-op because no ``old`` refs remain.
    Assumes ``name_map`` has no chained keys (validated by
    ``validate_name_map`` at load time).
    """
    for old, new in name_map.items():
        expr = re.sub(r"::" + re.escape(old) + r"\b", lambda _m, new=new: "::" + new, expr)
        expr = expr.replace("[" + old + "]", "[" + new + "]")
    return expr


def rewrite_formula_refs(formulas: list[dict], name_map: dict[str, str]) -> int:
    """Apply ``name_map`` to each formula's ``expr`` in place.

    Returns the number of formulas whose expression changed. Empty map is a
    no-op (returns 0).
    """
    if not name_map:
        return 0
    changed = 0
    for f in formulas:
        before = f.get("expr", "")
        after = rewrite_expr_refs(before, name_map)
        if after != before:
            f["expr"] = after
            changed += 1
    return changed


def apply_reconciliation(columns: list[dict], formulas: list[dict],
                         target_cols: set[str], name_map: dict[str, str]) -> tuple[list[dict], list[dict], dict]:
    kept_cols: list[dict] = []
    kept_origs: list[str] = []  # pre-mapping db_column_name, parallel to kept_cols
    dropped_cols: list[str] = []
    dropped_col_names: set[str] = set()
    renamed: dict[str, str] = {}
    for c in columns:
        orig = c.get("db_column_name")
        mapped = name_map.get(orig, orig)
        if mapped in target_cols:
            nc = dict(c)
            nc["db_column_name"] = mapped
            nc["name"] = mapped if c.get("name") == orig else c.get("name")
            kept_cols.append(nc)
            kept_origs.append(orig)
            if mapped != orig:
                renamed[orig] = mapped
        else:
            dropped_cols.append(orig)
            dropped_col_names.add(orig)

    # Post-condition dedupe: two different source columns can converge on the
    # same final db_column_name — either via name_map (two renames landing on
    # one target) or because a renamed column collides with an already-present
    # unmapped column. Either way, two kept columns sharing a db_column_name
    # would emit two columns with the same column_id, which ThoughtSpot's
    # import rejects. Keep the first occurrence; move later duplicates to the
    # dropped report (by their pre-mapping name, matching the convention used
    # for ordinary reconcile-drops above) and cascade-drop any formula that
    # referenced them via that pre-mapping name — formulas at this point still
    # reference original names; the `renamed` rewrite happens below.
    seen_final: set[str] = set()
    deduped_cols: list[dict] = []
    for nc, orig in zip(kept_cols, kept_origs):
        final = nc["db_column_name"]
        if final in seen_final:
            dropped_cols.append(orig)
            dropped_col_names.add(orig)
        else:
            seen_final.add(final)
            deduped_cols.append(nc)
    kept_cols = deduped_cols

    kept_formulas: list[dict] = []
    dropped_formulas: list[str] = []
    for f in formulas:
        expr = f.get("expr", "")
        if any(re.search(r"::" + re.escape(dc) + r"\b", expr) or ("[" + dc + "]") in expr
               for dc in dropped_col_names):
            dropped_formulas.append(f["name"])
        else:
            if renamed:
                nf = dict(f)
                nf["expr"] = rewrite_expr_refs(expr, renamed)
                kept_formulas.append(nf)
            else:
                kept_formulas.append(f)

    return kept_cols, kept_formulas, {"columns": dropped_cols, "formulas": dropped_formulas}
