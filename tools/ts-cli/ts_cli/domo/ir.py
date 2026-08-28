"""Domo App IR — the extract↔transform contract (see
agents/shared/schemas/domo-app-ir.md). Plain dataclasses; dump to JSON, hand-edit,
re-run. Every field is optional-friendly so a best-effort extract never hard-fails.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class DomoColumn:
    name: str
    domo_type: str = "STRING"  # STRING | DATETIME | DOUBLE | LONG


@dataclass
class Dataset:
    id: str
    name: str
    description: Optional[str] = None
    rows: Optional[int] = None
    columns: list[DomoColumn] = field(default_factory=list)


@dataclass
class BeastMode:
    id: Any = None
    name: str = ""
    formula: str = ""
    data_source_id: Optional[str] = None
    is_global: bool = True
    status: Optional[str] = None


@dataclass
class QueryColumn:
    column: str
    aggregation: Optional[str] = None
    alias: Optional[str] = None
    fmt: Optional[dict] = None


@dataclass
class QueryOrder:
    column: str
    order: str = "ASCENDING"  # ASCENDING | DESCENDING


@dataclass
class QueryFilter:
    column: str
    operand: str = ""
    values: list = field(default_factory=list)


@dataclass
class CardQuery:
    columns: list[QueryColumn] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    order_by: list[QueryOrder] = field(default_factory=list)
    filters: list[QueryFilter] = field(default_factory=list)
    limit: Optional[int] = None


@dataclass
class Card:
    urn: str
    title: str = ""
    chart_type: str = "table"  # kpi | bar | table | ...
    data_set_id: Optional[str] = None
    calc_fields: list[BeastMode] = field(default_factory=list)
    query: CardQuery = field(default_factory=CardQuery)
    conditional_formats: list = field(default_factory=list)
    quick_filters: list = field(default_factory=list)
    pref_width: Optional[int] = None
    pref_height: Optional[int] = None


@dataclass
class Page:
    id: Any = None
    name: str = ""
    card_ids: list[str] = field(default_factory=list)
    collection_ids: list = field(default_factory=list)
    children: list = field(default_factory=list)


@dataclass
class ExtractionNote:
    severity: str  # info | warning | needs_review
    area: str
    message: str


@dataclass
class DomoApp:
    app_name: str
    source: Optional[str] = None
    extraction_mode: str = "offline"  # offline | domo-cloud
    datasets: list[Dataset] = field(default_factory=list)
    beast_modes: list[BeastMode] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    notes: list[ExtractionNote] = field(default_factory=list)

    def note(self, severity: str, area: str, message: str) -> None:
        self.notes.append(ExtractionNote(severity, area, message))

    def to_dict(self) -> dict:
        return asdict(self)


def note_rows(app) -> list[dict]:
    """Parser notes as plain JSON-serialisable dicts.

    `ExtractionNote` is a dataclass, so putting the raw objects into `mapping.json`
    broke `json.dumps` for the whole command. One definition, used by both build
    stages — two inline copies is how the naming rule drifted in earlier rounds.
    """
    return [{
        "severity": str(getattr(n, "severity", "") or "note"),
        "area": str(getattr(n, "area", "") or ""),
        "message": str(getattr(n, "message", None) or n),
    } for n in list(getattr(app, "notes", []) or [])]

