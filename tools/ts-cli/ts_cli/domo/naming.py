"""The single naming authority for a Domo bundle.

Why this module exists
----------------------
A ThoughtSpot Model exposes ONE flat namespace on the search surface — table names,
column display names and formula display names all share it — plus a *generated* id
namespace (`formula_<display name>`, minted by `model_builder`). A Domo bundle can
collide in every one of those directions: the same column on two datasets, the same
Beast Mode on two datasets, a Beast Mode named after a column, two datasets with the
same name, two columns differing only by Unicode normalisation, and a column literally
named `formula_X` that aliases a generated id.

Four review rounds of one bug class taught the shape of this module. Each earlier fix
addressed the reported path and the class survived, because the rule lived in more than
one place, or owned only part of the namespace:

1. renames applied to `columns[]` but not to formula bodies;
2. nor to Answer columns;
3. then: a formula referencing a sibling formula, a Beast Mode colliding with a column
   (which the shared `resolve_name_collisions` silently *dropped*, poisoning every other
   formula that referenced that column), and the same clash on one dataset;
4. then: the `formula_*` id namespace was never reserved, the table pass was decorative,
   and the join graph keyed on raw dataset names.

So the rule lives here, once, and owns the whole namespace:

- `build_index(app)` resolves tables, columns and formulas into **one** reserved set, in
  that order, and records every rename it makes;
- the `formula_` prefix is reserved: a source column named `formula_X` is renamed, so no
  column can ever alias a generated formula id;
- names are compared NFC-normalised and casefolded, so two visually identical columns
  cannot both ship;
- `Index.resolve()` is dataset-scoped first and reports rather than guesses when a bare
  name is ambiguous;
- `Index.table_file()` owns emitted filenames, so two datasets cannot silently collapse
  into one `.table.tml`;
- nothing else applies a naming rule.

Determinism
-----------
`build-model` and `build-liveboard` are separate CLI invocations. The index is written
to `mapping.json` by the first and *loaded* by the second (see `index_to_dict` /
`index_from_dict`), so the two never independently re-derive it. When no index is
available, re-derivation is deterministic — datasets are ordered by `ds.id`, not by the
filename glob order `parse_app` happens to produce — but it is still announced, because
a bundle that changed between the two calls would otherwise bind silently.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from .ir import DomoApp

# `[Column Name]` references inside a translated formula or a search query.
_REF = re.compile(r"\[([^\[\]]+)\]")

# `model_builder` mints formula ids as `formula_<display name>`, so this prefix is a
# reserved namespace: a source column carrying it would alias a generated id.
FORMULA_ID_PREFIX = "formula_"


def _strip_reserved_prefix(name: str, kind: str) -> tuple[str, str]:
    """`(candidate, reason)` for a source name that intrudes on the id namespace.

    `model_builder` mints formula ids as `formula_<display name>`, so ANY Model object
    displayed as `formula_X` aliases the id of an object named `X`. The prefix is
    STRIPPED, never suffixed — a rename to `formula_Net (column)` leaves the alias in
    place, which was the first attempt at this in round 4.

    Both the column pass and the formula pass call this. Round 4 had the rule inline in
    the column pass only, and the formula pass therefore left a Beast Mode named
    `formula_Net` displayed with the prefix intact — one rule, two passes, applied in
    one. That asymmetry is the recurring shape of this converter's binding bugs, so the
    rule has exactly one home.
    """
    if not name.startswith(FORMULA_ID_PREFIX):
        return name, ""
    stem = name[len(FORMULA_ID_PREFIX):].strip() or kind
    return (f"{stem} ({kind})",
            f"'{FORMULA_ID_PREFIX}' is reserved for generated formula ids")


def _norm(s: str) -> str:
    """Normalised key for collision comparison.

    NFC first: `é` composed and `é` decomposed are visually identical and would both
    ship as distinct Model columns under a plain `.lower()` comparison.
    """
    return unicodedata.normalize("NFC", (s or "").strip()).casefold()


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (s or "")).strip("_") or "obj"


@dataclass
class Index:
    """Resolved Model names for every table, column and formula in a bundle."""

    # dataset id -> {raw column name -> model display name}
    columns_by_dataset: dict[str, dict[str, str]] = field(default_factory=dict)
    # (dataset id, Domo Beast Mode name) -> model formula display name
    formulas_by_dataset: dict[tuple[str, str], str] = field(default_factory=dict)
    # dataset id -> model table name / emitted filename
    table_by_dataset: dict[str, str] = field(default_factory=dict)
    file_by_dataset: dict[str, str] = field(default_factory=dict)

    column_names: set[str] = field(default_factory=set)
    formula_names: set[str] = field(default_factory=set)

    # report rows
    renames: list[dict] = field(default_factory=list)
    formula_renames: list[dict] = field(default_factory=list)
    table_renames: list[dict] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)

    # provenance
    bundle_digest: str = ""
    derived: bool = True          # False when loaded from a previous stage's mapping

    # ---- lookups ---------------------------------------------------------

    def table(self, dataset_id: Optional[str]) -> Optional[str]:
        return self.table_by_dataset.get(dataset_id or "")

    def table_file(self, dataset_id: Optional[str]) -> Optional[str]:
        return self.file_by_dataset.get(dataset_id or "")

    def display(self, dataset_id: Optional[str], column: str) -> Optional[str]:
        return (self.columns_by_dataset.get(dataset_id or "") or {}).get(column)

    def formula(self, dataset_id: Optional[str], name: str) -> Optional[str]:
        return self.formulas_by_dataset.get((dataset_id or "", name))

    def resolve(self, dataset_id: Optional[str], name: str) -> Optional[str]:
        """Resolve a Domo name to what the Model exposes, dataset-scoped first.

        Returns None when the name cannot be bound unambiguously; the caller flags it
        rather than emitting a reference that reads something else.
        """
        col = self.display(dataset_id, name)
        formula = self.formula(dataset_id, name)
        if col and formula:
            # Both exist on this dataset under the same source name. The column wins
            # (it is the search surface), but this is recorded — silently preferring
            # one re-points every pre-existing reference.
            note = (f"'{name}' is both a column and a Beast Mode on this dataset; "
                    f"references bind to the column, and the formula is exposed as "
                    f"'{formula}'")
            if note not in self.ambiguities:
                self.ambiguities.append(note)
            return col
        if col or formula:
            return col or formula

        # Not on this dataset. Binding a bare cross-dataset name is a guess: the two
        # datasets may not even be joined, in which case the result is a cross-product
        # artefact rather than a number. Only a formula that is globally unique AND
        # unambiguous against the column namespace resolves.
        if name in self.formula_names and name not in self.column_names:
            owners = [ds for (ds, n) in self.formulas_by_dataset if n == name]
            if len(owners) == 1:
                return name
        return None

    def rewrite(self, expr: str, dataset_id: Optional[str]) -> tuple[str, list[str]]:
        """Rewrite `[raw]` refs in `expr` to Model names for one dataset.

        EVERY ref is resolved, including one spelled `formula_X`. There used to be a
        pass-through for that prefix, justified as "an already-resolved generated id,
        safe because `build_index` reserves the prefix". Both halves were wrong, and
        the combination was the fifth wrong-binding path on this converter (PR #440
        review, round 5):

        * **Nothing reaching here is a generated id.** `rewrite` has one call site,
          `build_model._translate_one`, and it runs on the *output of
          `functions.translate`* — which converts Domo backticks to brackets and
          emits SOURCE names only. Generated ids are minted later, by
          `model_builder.add_formula_prefix` during assembly. So every `[formula_X]`
          arriving here is a Domo name that merely starts with those characters.
        * **The reservation is on the wrong side of the rename.** `build_index`
          reserves the prefix in the *Model display-name* namespace — a source column
          `formula_Net` is renamed to `Net (column)`. The pass-through fired on the
          *raw source* name, pre-rename. So it checked a source-side name against an
          output-side guarantee, which is this bug class's signature: two
          representations, the check applied to the wrong one.

        The observable failure: a Domo column `formula_Net` holding money, alongside
        a Beast Mode `Net`, made `SUM(`formula_Net`) * 0.9` emit
        `[formula_Net] * 0.9` — binding to the *formula* `Net` rather than the money
        column, reported `Migrated`, and `ts tml lint` clean. Wrong numbers, silently.
        The variant where the ref instead dangles was caught by lint, so the bug was
        loud when harmless and silent when harmful.
        """
        unresolved: list[str] = []

        def _sub(m: re.Match) -> str:
            raw = m.group(1)
            resolved = self.resolve(dataset_id, raw)
            if resolved is None:
                unresolved.append(raw)
                return m.group(0)
            return f"[{resolved}]"

        return _REF.sub(_sub, expr), unresolved


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class _Namespace:
    """One reserved flat namespace, NFC/casefold-compared."""

    def __init__(self) -> None:
        self._taken: set[str] = set()

    def taken(self, name: str) -> bool:
        return _norm(name) in self._taken

    def reserve(self, candidate: str, qualifier: str = "") -> str:
        """Return a free name, qualified then numbered, and reserve it."""
        name = candidate
        if self.taken(name) and qualifier:
            name = f"{candidate} ({qualifier})"
        n = 2
        while self.taken(name):
            name = f"{candidate} ({qualifier}) {n}" if qualifier else f"{candidate} {n}"
            n += 1
        self._taken.add(_norm(name))
        return name


def deduped_beast_modes(app: DomoApp) -> list:
    """Global Beast Modes then card-local calculated fields, deduped by (dataset, name).

    The ONE definition of "which Beast Modes exist", so the naming pass and the
    translation pass cannot disagree on the set or its order.
    """
    all_bm = list(app.beast_modes)
    for card in app.cards:
        all_bm.extend(card.calc_fields)
    seen: set = set()
    out = []
    for bm in all_bm:
        key = (bm.data_source_id or "", bm.name)
        if not bm.name or key in seen:
            continue
        seen.add(key)
        out.append(bm)
    return out


def ordered_datasets(app: DomoApp) -> list:
    """Datasets in a STABLE order.

    `parse_app` discovers files with `sorted(glob(...))`, so its order is filename sort
    order — nothing to do with the Domo data model. Renaming a fixture file therefore
    rewrote the whole namespace, and the two CLI stages could disagree. Ordering by
    dataset id (tie-broken by name) is a property of the data.
    """
    return sorted(app.datasets, key=lambda d: (str(d.id or ""), d.name or ""))


def bundle_digest(app: DomoApp) -> str:
    """A digest of everything the namespace depends on.

    Lets `build-liveboard` refuse a `mapping.json` produced from a different bundle
    rather than binding one layout's Answers against another's Model.
    """
    h = hashlib.sha256()
    for ds in ordered_datasets(app):
        h.update(f"D:{ds.id}:{ds.name}:".encode())
        for c in ds.columns:
            h.update(f"c:{c.name}:{c.domo_type}:".encode())
    for bm in deduped_beast_modes(app):
        h.update(f"B:{bm.data_source_id}:{bm.name}:".encode())
    for card in sorted(app.cards, key=lambda c: str(c.urn)):
        h.update(f"K:{card.urn}:{card.data_set_id}:".encode())
    return h.hexdigest()[:16]


def build_index(app: DomoApp) -> Index:
    """Resolve the whole namespace for a parsed bundle.

    Order is deliberate: tables, then columns, then formulas, all against ONE reserved
    set. Columns are the user's search surface and formulas are derived, so a formula
    yields to a column on a clash — never the reverse, because dropping a column removes
    a dimension and repoints every reference to it at a measure.
    """
    index = Index(bundle_digest=bundle_digest(app), derived=True)
    ns = _Namespace()
    files = _Namespace()
    datasets = ordered_datasets(app)

    # --- tables -----------------------------------------------------------
    for ds in datasets:
        name = ns.reserve(ds.name, "dataset")
        if name != ds.name:
            index.table_renames.append({"dataset_id": ds.id, "from": ds.name, "to": name})
        index.table_by_dataset[ds.id] = name
        # Filenames get their own namespace: `Sales-Data` and `Sales Data` both slug to
        # `Sales_Data`, which silently discarded one whole Table TML.
        base = files.reserve(_slug(name))
        index.file_by_dataset[ds.id] = f"{base}.table.tml"

    # --- columns ----------------------------------------------------------
    for ds in datasets:
        table = index.table_by_dataset[ds.id]
        per_id: dict[str, str] = {}
        for c in ds.columns:
            if c.name in per_id:
                # The same raw name twice on one dataset: the second used to overwrite
                # the first in the map, dropping a column with no report.
                index.renames.append({
                    "table": table, "from": c.name, "to": per_id[c.name],
                    "reason": "duplicate raw column name on this dataset — only the "
                              "first occurrence is mapped"})
                continue
            candidate, reason = _strip_reserved_prefix(c.name, "column")
            display = ns.reserve(candidate, table)
            if display != c.name:
                index.renames.append({
                    "table": table, "from": c.name, "to": display,
                    "reason": reason or "the name is already taken in the Model"})
            per_id[c.name] = display
            index.column_names.add(display)
        index.columns_by_dataset[ds.id] = per_id

    # --- formulas ---------------------------------------------------------
    for bm in deduped_beast_modes(app):
        table = index.table_by_dataset.get(bm.data_source_id) or ""
        clashes_with_column = ns.taken(bm.name)
        # The prefix is stripped from Beast Mode names too, not just columns. Round 4
        # applied this to the column pass only, which left a Beast Mode *named*
        # `formula_Net` displayed as `formula_Net` while its generated id became
        # `formula_formula_Net` — and `formula_common.add_formula_prefix` skips any ref
        # already starting with the prefix, so a sibling's `[formula_Net]` was never
        # prefixed and dangled. Two passes, one rule, applied in one of them: the same
        # shape as every other bug in this class, which is why the rule now lives in
        # `_strip_reserved_prefix` and both passes call it.
        candidate, prefix_reason = _strip_reserved_prefix(bm.name, "measure")
        name = ns.reserve(candidate, table)
        # Reserve the generated id too, so no later name can alias it.
        ns.reserve(f"{FORMULA_ID_PREFIX}{name}")
        if name != bm.name:
            index.formula_renames.append({
                "dataset": table, "from": bm.name, "to": name,
                "reason": (prefix_reason or
                           ("collides with a column or table name" if clashes_with_column
                            else "the same Beast Mode name exists on another dataset"))})
        index.formulas_by_dataset[(bm.data_source_id or "", bm.name)] = name
        index.formula_names.add(name)

    return index


# ---------------------------------------------------------------------------
# Cross-stage transport
# ---------------------------------------------------------------------------

def index_to_dict(index: Index) -> dict:
    """Serialise the resolved index into `mapping.json`."""
    return {
        "bundle_digest": index.bundle_digest,
        "tables": index.table_by_dataset,
        "files": index.file_by_dataset,
        "columns": {ds: dict(cols) for ds, cols in index.columns_by_dataset.items()},
        "formulas": [{"dataset_id": ds, "domo_name": n, "name": v}
                     for (ds, n), v in index.formulas_by_dataset.items()],
    }


def index_from_dict(payload: dict) -> Index:
    """Rebuild an Index written by a previous stage. Never re-derives."""
    index = Index(bundle_digest=payload.get("bundle_digest", ""), derived=False)
    index.table_by_dataset = dict(payload.get("tables") or {})
    index.file_by_dataset = dict(payload.get("files") or {})
    index.columns_by_dataset = {ds: dict(cols)
                               for ds, cols in (payload.get("columns") or {}).items()}
    for row in payload.get("formulas") or []:
        index.formulas_by_dataset[(row.get("dataset_id") or "",
                                   row.get("domo_name") or "")] = row.get("name") or ""
    for cols in index.columns_by_dataset.values():
        index.column_names.update(cols.values())
    index.formula_names.update(index.formulas_by_dataset.values())
    return index


# Backwards-compatible aliases (earlier review rounds).
ColumnIndex = Index
build_column_index = build_index
