"""Column context for single-formula translation: the three levels of spec §5.

Level 0 (no context)  — every reference becomes a placeholder ``[TABLE::<source name>]``.
Level 1 (names)       — a user-supplied column map (``--columns`` JSON).
Level 2 (Model)       — columns read from an exported Model TML (plus its Table TMLs,
                        for data types).

Every resolution goes through ``ColumnContext.resolve``, which records what it did in
``references`` — the "recording resolver" of spec §3.2. A level-1/2 miss is never a
guess: the reference is kept as a placeholder, flagged ``unresolved``, and carries the
close-match ``candidates`` the skill offers the user to confirm (spec §5: "never a
silent fuzzy match").

Pure: no I/O. The Model TML is fetched by the command layer and handed in parsed.
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

PLACEHOLDER_TABLE = "TABLE"
PRIMARY_KEY_PLACEHOLDER = "<primary key>"


@dataclass
class ColumnSpec:
    """One column a source reference can resolve to."""

    names: list[str]                  # source-side names that match this column
    target: str                       # the ThoughtSpot reference, brackets included
    table: Optional[str] = None
    column_type: Optional[str] = None  # ATTRIBUTE | MEASURE
    data_type: Optional[str] = None    # DATE, DATE_TIME, VARCHAR, INT64, DOUBLE, ...
    formula_expr: Optional[str] = None  # set when the column is a Model formula
    key: bool = False                  # a non-null key, used for COUNT(*)
    display_name: Optional[str] = None

    @property
    def is_date(self) -> bool:
        return (self.data_type or "").upper() in {"DATE", "DATE_TIME", "DATETIME", "TIMESTAMP"}

    @property
    def is_aggregate_formula(self) -> bool:
        from ts_cli.spotql_ops import is_aggregate_expr

        return bool(self.formula_expr) and is_aggregate_expr(self.formula_expr)


@dataclass
class Reference:
    source: str
    target: str
    placeholder: bool
    unresolved: bool = False
    candidates: list[str] = field(default_factory=list)
    kind: str = "column"  # column | parameter | primary_key

    def as_dict(self) -> dict:
        out: dict[str, Any] = {"source": self.source, "target": self.target,
                               "placeholder": self.placeholder}
        if self.kind != "column":
            out["kind"] = self.kind
        if self.unresolved:
            out["unresolved"] = True
            out["candidates"] = self.candidates
        return out


def _norm(name: str) -> str:
    """Case-, space- and underscore-insensitive key (spec §5 second match tier)."""
    return re.sub(r"[\s_]+", "", name or "").lower()


def _bracket(table: str, column: str) -> str:
    return f"[{table}::{column}]"


class ColumnContext:
    """Resolve source column names to ThoughtSpot references, recording each one."""

    def __init__(self, specs: Optional[list[ColumnSpec]] = None, level: int = 0,
                 model_name: Optional[str] = None):
        self.specs = specs or []
        self.level = level if self.specs or level == 2 else 0
        self.model_name = model_name
        self._refs: dict[tuple[str, str], Reference] = {}

    # -- recording ---------------------------------------------------------------
    @property
    def references(self) -> list[Reference]:
        return list(self._refs.values())

    def _record(self, ref: Reference) -> Reference:
        self._refs.setdefault((ref.kind, ref.source), ref)
        return self._refs[(ref.kind, ref.source)]

    def record_parameter(self, name: str) -> str:
        target = f"[{name}]"
        self._record(Reference(source=f"[{name}]", target=target,
                               placeholder=self.level < 2, kind="parameter"))
        return target

    # -- lookup ------------------------------------------------------------------
    def _match(self, name: str, table_hint: Optional[str]) -> Optional[ColumnSpec]:
        def pick(cands: list[ColumnSpec]) -> Optional[ColumnSpec]:
            if not cands:
                return None
            if table_hint:
                hinted = [s for s in cands if (s.table or "").lower() == table_hint.lower()]
                if len(hinted) == 1:
                    return hinted[0]
            return cands[0] if len(cands) == 1 else None

        exact = [s for s in self.specs if name in s.names]
        hit = pick(exact)
        if hit or exact:
            return hit
        key = _norm(name)
        loose = [s for s in self.specs if any(_norm(n) == key for n in s.names)]
        return pick(loose)

    def find(self, name: str) -> Optional[ColumnSpec]:
        """The spec ``name`` matches (exact, then case/space-insensitive), or None."""
        return self._match(name, None)

    def _ambiguous(self, name: str) -> list[ColumnSpec]:
        key = _norm(name)
        return [s for s in self.specs if any(_norm(n) == key for n in s.names)]

    def spec_for_target(self, target: str) -> Optional[ColumnSpec]:
        for s in self.specs:
            if s.target == target:
                return s
        return None

    def resolve(self, name: str, table_hint: Optional[str] = None) -> str:
        """Return the ThoughtSpot reference for a source column ``name``."""
        name = name.strip()
        source = f"{table_hint}.{name}" if table_hint and self.level == 0 else name
        if self.level == 0:
            target = _bracket(table_hint or PLACEHOLDER_TABLE, name)
            return self._record(Reference(source=source, target=target, placeholder=True)).target
        spec = self._match(name, table_hint)
        if spec is not None:
            return self._record(Reference(source=name, target=spec.target,
                                          placeholder=False)).target
        pool = sorted({n for s in self.specs for n in s.names})
        amb = self._ambiguous(name)
        cands = [s.display_name or s.names[0] for s in amb] or \
            difflib.get_close_matches(name, pool, n=3, cutoff=0.6)
        target = _bracket(table_hint or PLACEHOLDER_TABLE, name)
        return self._record(Reference(source=name, target=target, placeholder=True,
                                      unresolved=True, candidates=cands)).target

    def key_reference(self) -> str:
        """A non-null key to count rows by (COUNT(*) has no ThoughtSpot form)."""
        keys = [s for s in self.specs if s.key]
        if len(keys) == 1:
            ref = Reference(source="COUNT(*)", target=keys[0].target, placeholder=False,
                            kind="primary_key")
        else:
            ref = Reference(source="COUNT(*)",
                            target=_bracket(PLACEHOLDER_TABLE, PRIMARY_KEY_PLACEHOLDER),
                            placeholder=True, unresolved=self.level > 0,
                            candidates=[s.display_name or s.names[0] for s in keys],
                            kind="primary_key")
        return self._record(ref).target

    # -- derived sets the translators want ----------------------------------------
    def date_names(self) -> set[str]:
        return {n for s in self.specs if s.is_date for n in s.names}

    def date_targets(self) -> set[str]:
        """``TABLE::col`` (no brackets) for every date column — DAX's date_cols form."""
        return {s.target[1:-1] for s in self.specs if s.is_date}

    def aggregate_formula_targets(self) -> set[str]:
        return {s.target for s in self.specs if s.is_aggregate_formula}

    @property
    def unresolved(self) -> list[Reference]:
        return [r for r in self.references if r.unresolved]

    @property
    def has_placeholders(self) -> bool:
        return any(r.placeholder for r in self.references)


# ---------------------------------------------------------------------------
# Level 1 — --columns JSON
# ---------------------------------------------------------------------------

def _split_target(value: str) -> tuple[Optional[str], str]:
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    if "::" in v:
        t, c = v.split("::", 1)
        return t.strip(), c.strip()
    if "." in v:
        t, c = v.rsplit(".", 1)
        return t.strip(), c.strip()
    return None, v


def _spec_from_entry(source: Optional[str], target: str, meta: dict) -> ColumnSpec:
    table, column = _split_target(target)
    table = table or meta.get("table") or PLACEHOLDER_TABLE
    names = [n for n in dict.fromkeys([source or column, column]) if n]
    return ColumnSpec(
        names=names, target=_bracket(table, column), table=table,
        column_type=(meta.get("column_type") or meta.get("type") or None),
        data_type=(meta.get("data_type") or None),
        key=bool(meta.get("key")), display_name=source or column)


def _parse_shorthand(text: str) -> Optional[list[ColumnSpec]]:
    """``A=ORDERS.ORDER_DATE, B=ORDERS.AMOUNT`` → specs; None when ``text`` is JSON-shaped."""
    stripped = text.strip()
    if not stripped or stripped[0] in "[{\"" or "=" not in stripped:
        return None
    pairs = [p.strip() for p in re.split(r"[,\n]", stripped) if p.strip()]
    if not all("=" in p for p in pairs):
        raise ValueError("--columns shorthand must be source=TABLE.COLUMN pairs")
    return [_spec_from_entry(k.strip(), v.strip(), {})
            for k, v in (p.split("=", 1) for p in pairs)]


def parse_columns_json(text: str) -> list[ColumnSpec]:
    """Parse ``--columns``. Accepted shapes (all JSON):

    - ``{"Sales": "ORDERS.SALES_AMT", "Customer": "ORDERS::CUSTOMER_ID"}``
    - ``["ORDERS.SALES_AMT", "ORDERS.CUSTOMER_ID"]`` (source name = column name)
    - ``[{"source": "Sales", "table": "ORDERS", "column": "SALES_AMT",
          "data_type": "DOUBLE", "column_type": "MEASURE", "key": false}]``

    A mapping value may also be an object with the same keys as the list-of-objects form.
    A non-JSON ``A=ORDERS.ORDER_DATE, B=ORDERS.AMOUNT`` (``source=target`` pairs, comma- or
    newline-separated) is read as the mapping form — the shorthand for spreadsheet column
    letters. Raises ValueError on any other shape.
    """
    shorthand = _parse_shorthand(text)
    if shorthand is not None:
        return shorthand
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"--columns is not valid JSON: {exc}") from exc
    specs: list[ColumnSpec] = []
    if isinstance(data, dict):
        for src, val in data.items():
            if isinstance(val, str):
                specs.append(_spec_from_entry(src, val, {}))
            elif isinstance(val, dict):
                col = val.get("column") or src
                tgt = f"{val['table']}::{col}" if val.get("table") else col
                specs.append(_spec_from_entry(src, tgt, val))
            else:
                raise ValueError(f"--columns: value for {src!r} must be a string or object")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                specs.append(_spec_from_entry(None, item, {}))
            elif isinstance(item, dict) and item.get("column"):
                tgt = f"{item['table']}::{item['column']}" if item.get("table") else item["column"]
                specs.append(_spec_from_entry(item.get("source"), tgt, item))
            else:
                raise ValueError(f"--columns: list entries need a 'column' key: {item!r}")
    else:
        raise ValueError("--columns must be a JSON object or list")
    return specs


# ---------------------------------------------------------------------------
# Level 2 — exported Model TML
# ---------------------------------------------------------------------------

def _table_types(table_docs: list[dict]) -> dict[tuple[str, str], str]:
    """(table name, column name) -> data_type, from Table TMLs (best effort)."""
    out: dict[tuple[str, str], str] = {}
    for doc in table_docs or []:
        tbl = doc.get("table") if isinstance(doc, dict) else None
        if not isinstance(tbl, dict):
            continue
        tname = tbl.get("name", "")
        for col in tbl.get("columns") or []:
            dt = (col.get("db_column_properties") or {}).get("data_type")
            if dt:
                out[(tname.lower(), (col.get("name") or "").lower())] = dt
    return out


def _alias_map(model_tables: list[dict]) -> dict[str, str]:
    """model_tables alias (or name) -> the table's name."""
    out = {}
    for mt in model_tables:
        key = mt.get("alias") or mt.get("name")
        if key:
            out[key] = mt.get("name") or key
    return out


def _physical_spec(col: dict, alias_to_table: dict, types: dict) -> ColumnSpec:
    name = col.get("name")
    table, _, cname = col["column_id"].partition("::")
    real = alias_to_table.get(table, table)
    return ColumnSpec(
        names=[n for n in dict.fromkeys([name, cname]) if n],
        target=f"[{col['column_id']}]", table=table,
        column_type=(col.get("properties") or {}).get("column_type"),
        data_type=types.get((real.lower(), cname.lower())), display_name=name)


def _formula_spec(col: dict, formulas: dict) -> ColumnSpec:
    fid = col["formula_id"]
    f = formulas.get(fid) or {}
    return ColumnSpec(
        names=[n for n in dict.fromkeys([col.get("name"), f.get("name")]) if n],
        target=f"[{fid}]", column_type=(col.get("properties") or {}).get("column_type"),
        formula_expr=f.get("expr") or "", display_name=col.get("name"))


def specs_from_model_tml(model_doc: dict, table_docs: Optional[list[dict]] = None) -> list[ColumnSpec]:
    """Build ColumnSpecs from a parsed Model TML (``{"model": {...}}``).

    A physical column resolves to ``[column_id]`` (``TABLE::col``, which is what Model
    formulas reference) and matches on both its display name and its ``col`` part. A
    formula column resolves to ``[<formula id>]`` — formulas reference each other by id
    (CLAUDE.md invariant I9).
    """
    model = model_doc.get("model", model_doc) if isinstance(model_doc, dict) else {}
    formulas = {f.get("id"): f for f in model.get("formulas") or [] if f.get("id")}
    alias_to_table = _alias_map(model.get("model_tables") or [])
    types = _table_types(table_docs or [])
    specs: list[ColumnSpec] = []
    for col in model.get("columns") or []:
        if col.get("column_id"):
            specs.append(_physical_spec(col, alias_to_table, types))
        elif col.get("formula_id"):
            specs.append(_formula_spec(col, formulas))
    return specs
