"""DomoApp IR -> Table TML(s) + Model TML + mapping report.

Pure: returns dicts the command layer serializes with tml_common.dump_tml_yaml.
Delegates model assembly to ts_cli.model_builder.build_model_tml (shared emitter).
"""
from __future__ import annotations

import re
from typing import Optional

from ts_cli.databricks.mv_tml import validate_tml_invariants
from ts_cli.formula_common import expr_is_aggregated, resolve_name_collisions
from ts_cli.model_builder import build_model_tml

from .functions import translate
from .ir import Dataset, DomoApp, note_rows
from .naming import (
    Index,
    build_index,
    deduped_beast_modes,
    index_to_dict,
    ordered_datasets,
)

# Domo dataset type -> ThoughtSpot data_type
_TYPE_MAP = {
    "STRING": "VARCHAR", "DATETIME": "DATE_TIME", "DATE": "DATE",
    "DOUBLE": "DOUBLE", "LONG": "INT64", "BOOLEAN": "BOOL",
}
_NUMERIC_TS = {"DOUBLE", "INT64"}


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (s or "")).strip("_") or "obj"


def _ts_type(domo_type: str, overrides: Optional[dict] = None, col_name: str = "") -> str:
    if overrides and col_name in overrides:
        return overrides[col_name]
    return _TYPE_MAP.get((domo_type or "STRING").upper(), "VARCHAR")


def _col_type(ts_type: str) -> str:
    return "MEASURE" if ts_type in _NUMERIC_TS else "ATTRIBUTE"


def _build_table_doc(ds: Dataset, connection_name: str, db: str, schema: str,
                     overrides: Optional[dict]) -> dict:
    columns = []
    for c in ds.columns:
        ts_type = _ts_type(c.domo_type, overrides, c.name)
        column_type = _col_type(ts_type)
        props = {"column_type": column_type}
        if column_type == "MEASURE":
            props["aggregation"] = "SUM"
        columns.append({
            "name": c.name,
            "db_column_name": c.name,
            "properties": props,
            "db_column_properties": {"data_type": ts_type},
        })
    return {"table": {
        "name": ds.name, "db": db, "schema": schema, "db_table": ds.name,
        "connection": {"name": connection_name}, "columns": columns,
    }}


# Columns whose shared name is almost never a real relationship — joining on them
# silently fans out measures. A pair whose ONLY shared column is one of these is not
# joined at all; it is reported instead.
_INCIDENTAL_KEYS = {
    "date", "day", "month", "year", "quarter", "week", "region", "country", "state",
    "city", "status", "type", "category", "name", "description", "created_at",
    "updated_at", "currency", "segment",
}


# An id-like column name: a trailing `id`/`key`/`code`/`urn` TOKEN, not a trailing
# substring — `endswith("id")` also matched Paid, Void, Valid, Rapid and Overpaid, so
# two tables could end up joined on a boolean flag.
_KEY_TOKENS = {"id", "ids", "key", "keys", "code", "codes", "urn", "guid", "uuid", "pk", "fk"}
_KEY_TOKEN_RE = re.compile(r"[^a-z0-9]+")


# Words that END in an id-like token but are not keys. The token test alone cannot
# separate `orderid` (a key) from `Paid` (a boolean), because neither has a separator
# or a camelCase hump — so glued forms are matched by suffix and this list carves out
# the English words that would otherwise match.
_NOT_KEYS = {
    "paid", "void", "valid", "invalid", "rapid", "overpaid", "unpaid", "prepaid",
    "candid", "solid", "avid", "acid", "arid", "bid", "did", "grid", "hid", "kid",
    "lid", "mid", "rid", "aid", "said", "afraid", "repaid", "humid", "vivid",
    "liquid", "squid", "amid", "forbid", "outbid", "undid", "hybrid", "eyelid",
}


# Suffixes safe to match when GLUED to a stem. `urn` is deliberately absent: too many
# ordinary words end in it (Churn, Return, Turn, Saturn), and matching it there silently
# changed which column two tables joined on. `urn` still matches as a separated token.
_GLUED_SUFFIXES = ("ids", "id", "keys", "key", "codes", "code", "guid", "uuid")


def _looks_like_key(name: str) -> bool:
    """True when the name ends in an id-like token.

    Three shapes have to work, and earlier fixes traded one for another:

    - separated  — `Customer ID`, `order_guid`, `row urn`
    - camelCase  — `customerId`, `userIds`
    - glued      — `orderid`, `custid`, `CUSTOMERID`, `SSID`

    A token-only test (split, match the last token) handles the first two and fails
    every glued form. A suffix-only test handles glued forms and also matches
    `Paid`/`Void`/`Valid`. So: token test first, then a *restricted* glued-suffix test,
    guarded by `_NOT_KEYS` and by requiring at least two characters of stem — which is
    also what keeps singular and plural agreeing (`bid`/`bids` are both False).
    """
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name.strip())
    tokens = [t for t in _KEY_TOKEN_RE.split(spaced.lower()) if t]
    if not tokens:
        return False
    last = tokens[-1]
    if last in _KEY_TOKENS:
        return True
    base = last[:-1] if last.endswith("s") and len(last) > 1 else last
    if last in _NOT_KEYS or base in _NOT_KEYS:
        return False
    return any(last.endswith(sfx) and len(last) >= len(sfx) + 2
               for sfx in _GLUED_SUFFIXES)


def _pick_join_key(shared: set[str]) -> tuple[str | None, str]:
    """Choose ONE join key for a dataset pair. Returns (key, note_suffix)."""
    ranked = sorted(shared)
    keyish = [c for c in ranked if _looks_like_key(c)]
    if len(keyish) == 1:
        others = [c for c in ranked if c != keyish[0]]
        if others:
            return keyish[0], (f"joined on '{keyish[0]}'; {len(others)} other shared "
                               f"column(s) ({', '.join(others)}) were not used")
        return keyish[0], ""
    if len(keyish) > 1:
        return keyish[0], (f"{len(keyish)} id-like columns shared "
                           f"({', '.join(keyish)}) — picked the first")
    meaningful = [c for c in ranked if c.strip().lower() not in _INCIDENTAL_KEYS]
    if not meaningful:
        return None, (f"only incidental column(s) shared ({', '.join(ranked)}) — "
                      "no join inferred; supply --etl or join by hand")
    return meaningful[0], (f"no id-like column shared; picked '{meaningful[0]}' from "
                           f"{', '.join(ranked)}")


def _infer_joins(datasets: list[Dataset],
                 index: Index) -> tuple[list[dict], list[tuple], list[str], list[str]]:
    """Domo carries no join metadata — infer ONE join per dataset pair, and flag.

    Emitting one join per shared column (the previous behaviour) produced duplicate
    `with:` entries for the same table pair and joined on incidental names like
    `Region` or `Date`, which fans measures out across the star.
    """
    joins: list[dict] = []
    notes: list[tuple] = []
    drops: list[str] = []          # a join that could NOT be emitted
    advisories: list[str] = []     # a join that WAS emitted, with a caveat
    for i in range(len(datasets)):
        for j in range(i + 1, len(datasets)):
            a, b = datasets[i], datasets[j]
            # Resolved names: two datasets sharing a raw name previously produced
            # `[Sales::Order ID] = [Sales::Order ID]` — a self-join — plus a
            # disconnected second table, both reported Migrated.
            an = index.table(a.id) or a.name
            bn = index.table(b.id) or b.name
            shared = {c.name for c in a.columns} & {c.name for c in b.columns}
            if not shared or an == bn:
                continue
            key, note = _pick_join_key(shared)
            if key is None:
                drops.append(f"{an} ↔ {bn}: {note}")
                continue
            if note:
                advisories.append(f"{an} ↔ {bn}: {note}")
            joins.append({
                "left_table": an, "right_table": bn, "type": "LEFT_OUTER",
                "keys": [{"left": key, "right": key}],
            })
            notes.append((an, bn, key))
    return joins, notes, drops, advisories


def _flip(j: dict) -> None:
    """Swap a join's sides (and its keys), in place."""
    j["left_table"], j["right_table"] = j["right_table"], j["left_table"]
    j["keys"] = [{"left": k.get("right"), "right": k.get("left")}
                 for k in j.get("keys", [])]


def _orient_joins(joins: list[dict], rows_by_table: dict[str, int]) -> list[str]:
    """Put each join on the MANY (FK) side, in place. Returns advisory notes.

    Orientation reads the DECLARED Domo direction first and only falls back to row
    counts when there isn't one. Doing it the other way round inverted a declared
    `OTM`: the row-count flip swapped the sides, then the cardinality was read off
    the un-flipped `relationshipType`, emitting `ONE_TO_MANY` on the fact — valid,
    importable, and backwards, with no warning. That made honouring the declaration
    worse than the guess it replaced.
    """
    notes: list[str] = []
    for j in joins:
        declared = _declared_direction(j)
        if declared == "ONE_TO_MANY":
            # Domo says left is the ONE side, so the join belongs on the right.
            _flip(j)
            continue
        if declared in ("MANY_TO_ONE", "ONE_TO_ONE"):
            continue                      # left is already the FK / either side is fine
        left, right = j.get("left_table"), j.get("right_table")
        lr, rr = rows_by_table.get(left, 0), rows_by_table.get(right, 0)
        if lr and rr and lr < rr:
            _flip(j)
        elif not (lr and rr):
            notes.append(
                f"{left} ↔ {right}: no declared relationship and row counts unknown, so "
                f"the many-side could not be determined — join placed on '{left}'. "
                "Confirm the direction.")
    return notes


def _build_tables_and_columns(app: DomoApp, connection_name: str, db: str, schema: str,
                             type_overrides: Optional[dict],
                             index: Index) -> tuple[dict, list, list, list]:
    """Return (table_docs, tables, model_columns, renamed_cols).

    Display names come from the shared `ColumnIndex`. The collision rule itself lives
    in ts_cli/domo/naming.py so that the formula bodies and the Answer columns resolve
    through exactly the same mapping — see that module for why.
    """
    table_docs: dict[str, dict] = {}
    tables: list[dict] = []
    columns: list[dict] = []

    for ds in ordered_datasets(app):
        table = index.table(ds.id) or ds.name
        doc = _build_table_doc(ds, connection_name, db, schema, type_overrides)
        # `name` is the Model-facing (possibly disambiguated) name; `db_table` stays
        # the physical Domo dataset name the warehouse table is actually called.
        doc["table"]["name"] = table
        # The filename comes from the index too: two datasets whose names slug to the
        # same string used to silently collapse into one .table.tml.
        table_docs[index.table_file(ds.id) or f"{_slug(table)}.table.tml"] = doc
        tables.append({"name": table, "db_table": ds.name})
        for c in ds.columns:
            ts_type = _ts_type(c.domo_type, type_overrides, c.name)
            columns.append({
                "name": index.display(ds.id, c.name) or c.name,
                "db_column_name": c.name, "table": table,
                "column_type": _col_type(ts_type),
            })
    return table_docs, tables, columns, list(index.renames)


def _resolve_joins(app: DomoApp, index: Index,
                   explicit_joins: Optional[list]) -> tuple[list, list, str, list[str], list[str]]:
    """Return (joins, join_notes, join_source, warnings).

    ETL-derived joins win over inference, but only those whose table names actually
    resolve to a dataset in this bundle. Magic ETL carries dataflow ACTION names, which
    often differ from dataset names — unmatched joins were previously counted and
    reported while being silently dropped from the TML.
    """
    if explicit_joins is not None:
        # ETL joins name Domo datasets; match against BOTH the raw and resolved names
        # so a renamed dataset still reconciles.
        raw_to_resolved = {d.name: (index.table(d.id) or d.name) for d in app.datasets}
        known = set(raw_to_resolved) | set(raw_to_resolved.values())
        matched, drops = [], []
        for j in explicit_joins:
            left, right = j.get("left_table"), j.get("right_table")
            missing = [t for t in (left, right) if t not in known]
            if missing:
                drops.append(
                    f"ETL join {left} ↔ {right}: {', '.join(missing)} does not match any "
                    "dataset in the bundle (Magic ETL uses dataflow action names) — "
                    "join dropped")
                continue
            j = dict(j)
            j["left_table"] = raw_to_resolved.get(left, left)
            j["right_table"] = raw_to_resolved.get(right, right)
            matched.append(j)
        notes = [(j["left_table"], j["right_table"],
                  ", ".join(k["left"] for k in j.get("keys", [])))
                 for j in matched]
        return matched, notes, "magic_etl", drops, []
    joins, notes, drops, advisories = _infer_joins(ordered_datasets(app), index)
    return joins, notes, "shared_column_name", drops, advisories


# Translations that are mapped but need a human to confirm semantics: marker -> the
# caveat to report. `build_model_tml` derives each formula's id from its NAME, so a
# duplicate name means a duplicate id (see _translate_beast_modes).
_APPROXIMATE_MARKERS: tuple[tuple[str, str], ...] = (
    ("diff_days(", "DATEDIFF → diff_days assumes DAY grain and ThoughtSpot argument "
                   "order (a−b) — verify the sign and the unit"),
    ("stddev(", "verify sample vs population"),
    ("variance(", "verify sample vs population"),
)


def _formula_status(ts_expr: str, review: bool) -> tuple[str, str]:
    """Map a translation onto the report's three-value status vocabulary."""
    if review:
        return "NEEDS REVIEW", ""
    low = ts_expr.lower()
    for marker, caveat in _APPROXIMATE_MARKERS:
        if marker in low:
            return "Approximated", caveat
    return "Migrated", ""


def _translate_one(bm, index: Index) -> tuple[str, str, list[str]]:
    """Translate one Beast Mode. Returns (ts_expr, status, notes)."""
    ts_expr, review, reason = translate(bm.formula)

    # Bind the formula to the Model's names for ITS dataset. Without this a Beast Mode
    # defined on the second dataset reads the FIRST dataset's column of the same name —
    # a clean import with wrong numbers.
    ts_expr, unresolved = index.rewrite(ts_expr, bm.data_source_id)
    if unresolved:
        review = True
        reason = "; ".join(x for x in [
            reason,
            "references column(s) the Model does not expose: "
            + ", ".join(sorted(set(unresolved)))] if x)

    # Domo itself marks a broken Beast Mode (status != VALID). This must set `review`,
    # not just the reported status: otherwise the comment-wrap below never fires and a
    # formula the SOURCE already knows is broken ships bare, imports, and computes
    # something. The coverage matrix said "not translated as valid"; it was.
    declared = (getattr(bm, "status", None) or "").strip().upper()
    invalid_at_source = bool(declared) and declared != "VALID"
    if invalid_at_source:
        review = True
        reason = "; ".join(x for x in [
            reason, f"Domo reports this Beast Mode as {declared} (not VALID) — fix it in "
                    "Domo, or rewrite it here"] if x)

    status, extra = _formula_status(ts_expr, review)

    # A flagged formula is emitted VERBATIM — by definition not valid ThoughtSpot
    # syntax. Left bare it makes the whole model TML unimportable, so the user loses
    # every other measure too. Wrap it in a comment marker, as ts_cli/qlik does: the
    # rest of the model imports and the original survives for the human.
    if review:
        ts_expr = f"/* TODO review: {ts_expr} */"

    return ts_expr, status, [x for x in (reason, extra) if x]


def _translate_beast_modes(app: DomoApp, index: Index) -> tuple[list, list]:
    """Translate every Beast Mode into a Model formula + a mapping-report row.

    Names come from the shared ColumnIndex (see ts_cli/domo/naming.py): a Beast Mode
    name used by two datasets must be disambiguated because `build_model_tml` derives
    the formula id from the name, and a card referencing the renamed one has to resolve
    to the same string. Both facts live in one place so the stages cannot disagree.
    """
    ds_name = {d.id: d.name for d in app.datasets}
    translated: list[dict] = []
    mapping_formulas: list[dict] = []

    for bm in deduped_beast_modes(app):
        name = index.formula(bm.data_source_id, bm.name) or bm.name
        ts_expr, status, notes = _translate_one(bm, index)
        if name != bm.name:
            why = next((r["reason"] for r in index.formula_renames
                        if r["from"] == bm.name and r["to"] == name),
                       "the name is already taken in the Model")
            notes.append(f"renamed from '{bm.name}' — {why}; Model display names must "
                         "be unique")
        translated.append({"name": name, "expr": ts_expr, "column_type": "MEASURE"})
        mapping_formulas.append({
            "name": name, "domo_name": bm.name, "domo_formula": bm.formula,
            # The owning dataset — needed to verify the formula binds to the right
            # table, which is not derivable from the name once names collide.
            "dataset": ds_name.get(bm.data_source_id) or "",
            "dataset_id": bm.data_source_id or "",
            "ts_formula": ts_expr, "status": status, "note": "; ".join(notes),
        })
    return translated, mapping_formulas


# Domo `relationshipType` -> what we can honestly assert about cardinality.
# ThoughtSpot has no many-to-many join, so MTM cannot be expressed at all: emitting
# MANY_TO_ONE over it silently changes the grain. Only the directional forms are
# trusted; anything else falls back to the row-count heuristic and says so.
_DOMO_CARDINALITY = {
    "MTO": "MANY_TO_ONE",
    "MANY_TO_ONE": "MANY_TO_ONE",
    "OTM": "ONE_TO_MANY",
    "ONE_TO_MANY": "ONE_TO_MANY",
    "OTO": "ONE_TO_ONE",
    "ONE_TO_ONE": "ONE_TO_ONE",
}
_DOMO_UNSUPPORTED_CARDINALITY = {"MTM", "MANY_TO_MANY"}


def _declared_direction(join: dict) -> Optional[str]:
    """The Domo-declared direction, or None when there isn't a usable one."""
    declared = str(join.get("domo_relationship") or "").strip().upper()
    return _DOMO_CARDINALITY.get(declared)


def _declared_cardinality(join: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (cardinality, warning) for an ALREADY-ORIENTED join.

    Orientation has put the FK on the left, so a declared direction always emits
    MANY_TO_ONE (or ONE_TO_ONE) from here — never ONE_TO_MANY, which would mean the
    join is sitting on the wrong table.
    """
    declared = str(join.get("domo_relationship") or "").strip().upper()
    if not declared:
        return None, None
    if declared in _DOMO_UNSUPPORTED_CARDINALITY:
        return "MANY_TO_ONE", (
            f"{join.get('left_table')} ↔ {join.get('right_table')}: Domo declares this "
            "relationship MANY-TO-MANY, which ThoughtSpot cannot express as a join. It "
            "is emitted MANY_TO_ONE so the Model still builds — a many-to-many needs a "
            "bridge table, and measures WILL fan out until it has one")
    mapped = _DOMO_CARDINALITY.get(declared)
    if mapped == "ONE_TO_MANY":
        return "MANY_TO_ONE", None   # oriented above; the FK is now on the left
    if mapped:
        return mapped, None
    return None, (f"{join.get('left_table')} ↔ {join.get('right_table')}: unrecognized "
                  f"Domo relationshipType {declared!r} — cardinality inferred instead")


def _apply_join_fixes(model_tml: dict, joins: list, app: DomoApp,
                      index: Index) -> None:
    """Fix two things the shared model emitter does not, in place.

    1. A join must declare a cardinality (the emitter sets only type).
    2. A join must live on the source (FK/MANY) side ONLY — the emitter emits it on
       both tables (bidirectional), which fails model schema validation.

    The source side is the declared left_table of each join (the fact for ETL chains,
    the first dataset for inferred joins); cardinality is refined by row count when
    known, else MANY_TO_ONE.
    """
    directed = {(j["left_table"], j["right_table"]): j for j in joins}
    rows_by_table = {(index.table(ds.id) or ds.name): (ds.rows or 0)
                     for ds in app.datasets}
    for mt in model_tml.get("model", {}).get("model_tables", []):
        name = mt.get("name")
        kept = []
        for j in mt.get("joins", []):
            other = j.get("with")
            source = directed.get((name, other))
            if source is None:  # keep only on the source side
                continue
            declared, _warning = _declared_cardinality(source)
            if declared:
                j["cardinality"] = declared
            else:
                here, there = rows_by_table.get(name, 0), rows_by_table.get(other, 0)
                j["cardinality"] = ("ONE_TO_MANY" if (here and there and here < there)
                                    else "MANY_TO_ONE")
            kept.append(j)
        if kept:
            mt["joins"] = kept
        else:
            mt.pop("joins", None)


def _aggregation_findings(model_tml: dict, index: Index,
                          formula_exprs: Optional[dict] = None) -> list[dict]:
    """Report every measure the shared emitter did NOT give SUM.

    `model_builder._aggregation_for_name` switches rate/ratio/percent/score-shaped
    names to AVERAGE. Domo's own default is SUM, so a Domo `SUM(Conversion Rate)`
    ships as `aggregation: AVERAGE` — every number changes. The emitter's own comment
    calls this out; naming it is exactly this converter's job.
    """
    findings: list[dict] = []
    exprs = formula_exprs or {}
    for c in model_tml.get("model", {}).get("columns", []):
        props = c.get("properties", {})
        agg = props.get("aggregation")
        if props.get("column_type") != "MEASURE" or not agg or agg == "SUM":
            continue
        # A formula that already aggregates (`sum(x) / count(y)`) carries the properties
        # aggregation as metadata — it is not applied on top, so switching it changes
        # nothing. Only report where the aggregation actually governs the number:
        # a plain dataset measure (Domo defaults to SUM) or a non-aggregating formula.
        expr = exprs.get(c.get("name"))
        if expr is not None and expr_is_aggregated(expr):
            continue
        findings.append({
            "column": c.get("name"),
            "aggregation": agg,
            "note": (f"emitted with aggregation {agg} rather than SUM — the name looked "
                     "rate/ratio/average-shaped to the shared model emitter. Domo's "
                     "default is SUM, so every number for this measure changes; "
                     "confirm which one is intended"),
        })
    return findings


def _build_mapping(app: DomoApp, join_notes: list, join_source: str,
                   mapping_formulas: list, renamed_cols: list,
                   table_docs: dict, joins: Optional[list] = None) -> dict:
    invariant_findings: list[str] = []
    for fn, doc in table_docs.items():
        invariant_findings += [f"{fn}: {m}" for m in validate_tml_invariants(doc)]
    note = ("from Magic ETL join graph" if join_source == "magic_etl"
            else "inferred by shared column name")
    # Per-join cardinality warnings (e.g. a Domo many-to-many, which ThoughtSpot cannot
    # express) must land on the join's OWN row. Previously they only reached the
    # aggregate warning list, so the Relationships table showed just the provenance and
    # the report claimed the warning appeared here when it did not.
    per_join = {(j.get("left_table"), j.get("right_table")): j.get("cardinality_warning")
                for j in (joins or []) if j.get("cardinality_warning")}
    return {
        "source": {"mode": app.extraction_mode, "app_name": app.app_name},
        "datasets": [
            {"domo_id": d.id, "name": d.name, "ts_table": d.name,
             "columns": len(d.columns), "status": "Migrated"} for d in app.datasets],
        "joins": [
            {"left": a, "right": b, "on": k, "inferred": True, "source": join_source,
             "status": "NEEDS REVIEW",
             "note": "; ".join(x for x in (note, per_join.get((a, b))) if x)}
            for (a, b, k) in join_notes],
        "beast_modes": mapping_formulas,
        "renamed_columns": renamed_cols,
        "invariant_findings": invariant_findings,
    }


def _assert_namespace_is_collision_free(columns: list, translated: list) -> None:
    """Prove, every run, that `naming.Index` kept the Model namespace clean.

    Uses the shared collision helper as an ASSERTION rather than a mutation. That
    distinction matters: the helper resolves a clash by DROPPING the column, which
    removes a dimension users search by and silently repoints every formula that
    referenced it at a measure (PR #440 review, round 3). `Index` resolves formulas
    into the same reserved namespace as columns, so nothing here can collide — and if
    it ever does, that is an index bug we want to hear about loudly rather than ship a
    quietly-different model.
    """
    checked_cols, _checked_formulas, renamed = resolve_name_collisions(
        [dict(c) for c in columns], [dict(f) for f in translated], [])
    if len(checked_cols) != len(columns) or renamed:
        dropped = {c["name"] for c in columns} - {c["name"] for c in checked_cols}
        raise AssertionError(
            "naming.Index failed to keep the Model namespace collision-free: "
            f"resolve_name_collisions would drop {sorted(dropped)} and rename "
            f"{renamed}. This is an index bug — fix build_index rather than letting "
            "the column be dropped.")


def _annotate_aggregation_changes(mapping: dict, model_tml: dict, index: Index,
                                  translated: list) -> None:
    """Attach aggregation switches to the measure they affect, in place.

    A switch is a SEMANTICS change, not a TML invariant, and the measure's own row must
    stop claiming Migrated while the number silently changed.
    """
    agg = _aggregation_findings(
        model_tml, index, {f["name"]: f["expr"] for f in translated})
    mapping["aggregation_changes"] = agg
    changed = {a["column"] for a in agg}
    for row in mapping.get("beast_modes", []):
        if row["name"] in changed:
            note = next(a["note"] for a in agg if a["column"] == row["name"])
            row["status"] = "Approximated"
            row["note"] = "; ".join(x for x in (row.get("note"), note) if x)


def build_model_artifacts(app: DomoApp, *, connection_name: str, db: str, schema: str,
                          model_name: Optional[str] = None,
                          type_overrides: Optional[dict] = None,
                          explicit_joins: Optional[list] = None) -> dict:
    """Build Table + Model TML + mapping.

    ``explicit_joins`` (e.g. from a Magic ETL export, see magic_etl.parse_etl) — a
    list of ``{left_table, right_table, type, keys:[{left,right}]}`` — overrides the
    shared-column-name inference. Each is still flagged NEEDS REVIEW because the
    join side/cardinality is inferred without full column lineage.
    """
    model_name = model_name or f"{app.app_name} Model"

    index = build_index(app)
    table_docs, tables, columns, renamed_cols = _build_tables_and_columns(
        app, connection_name, db, schema, type_overrides, index)
    joins, join_notes, join_source, join_drops, join_advisories = _resolve_joins(
        app, index, explicit_joins)
    translated, mapping_formulas = _translate_beast_modes(app, index)

    rows_by_table = {(index.table(ds.id) or ds.name): (ds.rows or 0)
                     for ds in app.datasets}
    join_advisories += _orient_joins(joins, rows_by_table)
    for j in joins:
        _c, warning = _declared_cardinality(j)
        if warning:
            join_advisories.append(warning)
            j["cardinality_warning"] = warning
    join_warnings = join_drops + join_advisories
    # Re-derive the notes AFTER orientation so the report names the same sides the TML does.
    join_notes = [(j["left_table"], j["right_table"],
                   ", ".join(k["left"] for k in j.get("keys", [])))
                  for j in joins]

    _assert_namespace_is_collision_free(columns, translated)

    model_tml = build_model_tml(
        model_name=model_name, connection_name=connection_name, tables=tables,
        columns=columns, joins=joins, parameters=[], translated_formulas=translated)
    _apply_join_fixes(model_tml, joins, app, index)

    mapping = _build_mapping(app, join_notes, join_source, mapping_formulas,
                             renamed_cols, table_docs, joins)
    mapping["join_warnings"] = join_warnings
    mapping["join_drops"] = join_drops
    mapping["join_advisories"] = join_advisories
    mapping["formula_renames"] = list(index.formula_renames)
    mapping["table_renames"] = list(index.table_renames)
    mapping["name_ambiguities"] = list(index.ambiguities)
    mapping["parse_notes"] = note_rows(app)
    # The resolved namespace, so `build-liveboard` binds against exactly these names
    # rather than re-deriving and hoping the two agree.
    mapping["bundle_digest"] = index.bundle_digest
    mapping["name_index"] = index_to_dict(index)
    _annotate_aggregation_changes(mapping, model_tml, index, translated)
    return {
        "tables": table_docs,
        "model": {"filename": f"{_slug(model_name)}.model.tml", "tml": model_tml},
        "mapping": mapping,
        # counts describe what was EMITTED, not what was seen — the join count used to
        # report parsed-but-dropped ETL joins. `joins_dropped` counts DROPS only; the
        # advisory orientation/cardinality notes live in mapping["join_warnings"].
        "counts": {"tables": len(tables), "formulas": len(translated),
                   "joins": len(joins), "joins_dropped": len(join_drops)},
    }
