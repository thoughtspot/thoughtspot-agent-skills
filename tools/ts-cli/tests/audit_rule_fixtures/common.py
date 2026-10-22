"""Generic engine fixtures: one small input per aggregation mode and engine behaviour
(ratio, count, each, group, pairwise, composite; alias keying; data availability).
Not tied to any category's legacy checks."""
from __future__ import annotations

from ts_cli.audit.context import AuditContext, make_context

MODEL_GUID = "00000000-0000-4000-8000-000000000001"


def _column(name: str, column_type: str = "ATTRIBUTE", **props) -> dict:
    return {"name": name, "column_id": f"FACT::{name}",
            "properties": {"column_type": column_type, **props}}


def _model(name: str, guid: str, columns: list, model_tables: list | None = None,
           **extra) -> dict:
    return {"guid": guid, "model": {"name": name, "columns": columns,
                                    "model_tables": model_tables or [], **extra}}


def _measures(total: int, with_context: int) -> list:
    """`total` visible measures M0..M<total-1>; the first `with_context` carry ai_context."""
    return [_column(f"M{i}", "MEASURE",
                    **({"ai_context": "additivity: additive"} if i < with_context else {}))
            for i in range(total)]


def _noise_columns() -> list:
    """Columns a measure-coverage rule must ignore: a hidden measure, an attribute."""
    return [_column("HIDDEN_M", "MEASURE", is_hidden=True), _column("REGION")]


# ── measure AI context (ratio mode) ─────────────────────────────────────────

def model_measures_with_ai_context() -> AuditContext:
    """8 of 10 visible measures carry ai_context (80%)."""
    return make_context(models=[_model("Sales", MODEL_GUID,
                                       _measures(10, 8) + _noise_columns())])


def model_measures_no_ai_context() -> AuditContext:
    """3 of 10 visible measures carry ai_context (30%); M3..M9 are missing it."""
    return make_context(models=[_model("Sales", MODEL_GUID,
                                       _measures(10, 3) + _noise_columns())])


def model_without_measures() -> AuditContext:
    """A model whose only measure is hidden: the population is empty."""
    return make_context(models=[_model("Lookup", MODEL_GUID, _noise_columns())])


# ── column sprawl (count mode) ──────────────────────────────────────────────

def model_76_columns() -> AuditContext:
    return make_context(models=[_model("Wide", MODEL_GUID,
                                       [_column(f"C{i}") for i in range(76)])])


def model_75_columns() -> AuditContext:
    return make_context(models=[_model("Wide", MODEL_GUID,
                                       [_column(f"C{i}") for i in range(75)])])


# ── per-column (each mode) ──────────────────────────────────────────────────

def model_id_columns() -> AuditContext:
    """Two indexed ID-like attributes, one DONT_INDEX ID, one plain attribute."""
    cols = [_column("customer_id"), _column("order_id"),
            _column("row_id", index_type="DONT_INDEX"), _column("Region")]
    return make_context(models=[_model("Orders", MODEL_GUID, cols)])


# ── model tables keyed by alias ─────────────────────────────────────────────

def model_role_playing_dimension() -> AuditContext:
    """DIM_DATE joined twice, as ORDER_DATE and SHIP_DATE; FACT has no alias."""
    tables = [
        {"name": "FACT", "fqn": "t-fact",
         "joins": [{"with": "ORDER_DATE", "on": "[FACT::OD] = [ORDER_DATE::D]"}]},
        {"name": "DIM_DATE", "alias": "ORDER_DATE", "fqn": "t-date"},
        {"name": "DIM_DATE", "alias": "SHIP_DATE", "fqn": "t-date"},
    ]
    return make_context(models=[_model("Orders", MODEL_GUID, [], tables)])


# ── AI instructions (data availability) ─────────────────────────────────────

def models_with_and_without_ai_instructions() -> AuditContext:
    """Two models without coaching; only the first has an ai_instructions entry."""
    looked_up = _model("Looked Up", "guid-looked-up", [_column("A")])
    not_fetched = _model("Not Fetched", "guid-not-fetched", [_column("A")])
    return make_context(models=[looked_up, not_fetched],
                        ai_instructions={"guid-looked-up": {"nl_instructions_info": []}})


# ── duplicates and divergence (group mode) ──────────────────────────────────

def _header(guid: str, name: str, source: str = "SF", kind: str = "ONE_TO_ONE_LOGICAL") -> dict:
    return {"metadata_header": {"id": guid, "name": name, "type": kind,
                                "dataSourceName": source}}


def metadata_duplicate_tables() -> AuditContext:
    """ORDERS on SF registered three times; CUSTOMERS once; ORDERS on PG once."""
    return make_context(metadata=[
        _header("t1", "ORDERS"), _header("t2", "CUSTOMERS"), _header("t3", "ORDERS"),
        _header("t4", "ORDERS", source="PG"), _header("t5", "ORDERS"),
    ])


def models_divergent_column_types() -> AuditContext:
    """REGION is an ATTRIBUTE in one model and a MEASURE in another; AMOUNT agrees."""
    m1 = _model("North", "g-north", [_column("REGION"), _column("AMOUNT", "MEASURE")])
    m2 = _model("South", "g-south", [_column("REGION", "MEASURE"), _column("AMOUNT", "MEASURE")])
    return make_context(models=[m1, m2])


# ── overlap (pairwise mode) ─────────────────────────────────────────────────

def _tables(*fqns: str) -> list:
    return [{"name": f.upper(), "fqn": f} for f in fqns]


def models_overlapping_tables() -> AuditContext:
    """A/B share 3 of 4 tables (0.75); A/C share 1 of 5 (0.2); B/D share nothing."""
    return make_context(models=[
        _model("A", "g-a", [], _tables("t1", "t2", "t3")),
        _model("B", "g-b", [], _tables("t1", "t2", "t3", "t4")),
        _model("C", "g-c", [], _tables("t1", "t8", "t9")),
        _model("D", "g-d", [], _tables("t7")),
    ])


# ── weighted score (composite mode) ─────────────────────────────────────────

def models_for_readiness_score() -> AuditContext:
    """Component values live on the model's `properties` so the test needs no derived field."""
    def scored(name: str, guid: str, coverage: float, coached: bool) -> dict:
        return _model(name, guid, [], properties={"coverage": coverage, "coached": coached})
    return make_context(models=[scored("Ready", "g-ready", 90.0, True),
                                scored("Partial", "g-partial", 50.0, True),
                                scored("Bare", "g-bare", 20.0, False)])

