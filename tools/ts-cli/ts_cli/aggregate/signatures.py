"""Parse Answer/Liveboard TML into normalized query signatures (pure, no I/O)."""
from __future__ import annotations

import re
from typing import Optional

BUCKET_TOKENS = {"hourly": "HOURLY", "daily": "DAILY", "weekly": "WEEKLY",
                 "monthly": "MONTHLY", "quarterly": "QUARTERLY", "yearly": "YEARLY"}
_TOKEN = re.compile(r"\[([^\]]+)\](?:\.(\w+))?")
_FILTER = re.compile(
    r"\[([^\]]+)\]\s*"
    r"(!=|>=|<=|=|>|<"
    r"|in\s*\(|between\b|contains\b|begins\s+with\b|ends\s+with\b"
    r"|after\b|before\b)",
    re.IGNORECASE,
)
_DATE_KINDS = ("DATE", "DATE_TIME", "TIMESTAMP")
_FORMULA_PREFIX = "formula_"


def column_kinds_from_model(model_tml: dict) -> dict:
    model = model_tml.get("model", {})
    kinds: dict = {}
    for c in model.get("columns", []) or []:
        props = c.get("properties", {}) or {}
        if props.get("column_type") == "MEASURE":
            kinds[c["name"]] = "MEASURE"
        elif (c.get("data_type") or "").upper() in _DATE_KINDS:
            kinds[c["name"]] = "DATE"
        else:
            kinds[c["name"]] = "ATTRIBUTE"
    for f in model.get("formulas", []) or []:
        # formula columns[] entries carry the type; default formulas to MEASURE
        kinds.setdefault(f["name"], "MEASURE")
    return kinds


def _first_grain(date_grains: list) -> tuple:
    """Compat shim (Task 14, removed in Task 15): date_column/date_bucket derive
    from date_grains[0] so sqlgen/generate/history/commands keep reading the
    single-date fields unchanged."""
    if not date_grains:
        return None, None
    first = date_grains[0]
    return first["column"], first["bucket"]


def _parse_answer(answer: dict, kinds: dict, source_guid: str, source_name: str,
                  source_type: str, viz_name: Optional[str]) -> dict:
    query = answer.get("search_query", "") or ""
    # Filter role is decided per OCCURRENCE, not per name: a column can be
    # grouped in one token and filtered in another (e.g. "[Order Date].monthly
    # [Order Date] > '01/01/2024'"). Match filter spans by start position.
    filter_spans = {m.start() for m in _FILTER.finditer(query)}
    filter_cols: list = []
    dims, measures = [], []
    date_grains: list = []
    partial = not query
    seen = set()
    for m in _TOKEN.finditer(query):
        name, suffix = m.group(1), (m.group(2) or "").lower()
        if m.start() in filter_spans:
            if name not in filter_cols:  # dedupe, order-preserving
                filter_cols.append(name)
            continue  # filter occurrence — never grouped
        if name not in kinds and name.startswith(_FORMULA_PREFIX):
            # ad-hoc formula token: try resolving the underlying column name
            name = name[len(_FORMULA_PREFIX):]
        if name in seen:
            continue
        seen.add(name)
        kind = kinds.get(name)
        if kind is None:
            partial = True
            continue
        if kind == "MEASURE":
            measures.append(name)
        elif kind == "DATE":
            # capture EVERY grouped date column, in query order (Task 14);
            # bucket is None for a raw/unbucketed date token
            date_grains.append({"column": name, "bucket": BUCKET_TOKENS.get(suffix)})
        else:
            dims.append(name)
    date_column, date_bucket = _first_grain(date_grains)
    return {
        "source_guid": source_guid, "source_name": source_name,
        "source_type": source_type, "viz_name": viz_name,
        "dimensions": dims, "date_column": date_column, "date_bucket": date_bucket,
        "date_grains": date_grains,
        "measures": measures, "filter_columns": filter_cols,
        "parse_status": "partial" if partial else "full", "weight": 1.0,
    }


def extract_signatures(tml_doc: dict, column_kinds: dict,
                       source_guid: str, source_name: str) -> list:
    if "answer" in tml_doc:
        return [_parse_answer(tml_doc["answer"], column_kinds, source_guid,
                              source_name, "ANSWER", None)]
    if "liveboard" in tml_doc:
        sigs = []
        for viz in tml_doc["liveboard"].get("visualizations", []) or []:
            answer = viz.get("answer") or {}
            sigs.append(_parse_answer(answer, column_kinds, source_guid,
                                      source_name, "LIVEBOARD_VIZ",
                                      answer.get("name")))
        return sigs
    return []
