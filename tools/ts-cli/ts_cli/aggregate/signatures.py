"""Parse Answer/Liveboard TML into normalized query signatures (pure, no I/O)."""
from __future__ import annotations

import re
from typing import Optional

BUCKET_TOKENS = {"hourly": "HOURLY", "daily": "DAILY", "weekly": "WEEKLY",
                 "monthly": "MONTHLY", "quarterly": "QUARTERLY", "yearly": "YEARLY"}
_TOKEN = re.compile(r"\[([^\]]+)\](?:\.(\w+))?")
_FILTER = re.compile(r"\[([^\]]+)\]\s*(=|!=|>=|<=|>|<)")
_DATE_KINDS = ("DATE", "DATE_TIME", "TIMESTAMP")


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


def _parse_answer(answer: dict, kinds: dict, source_guid: str, source_name: str,
                  source_type: str, viz_name: Optional[str]) -> dict:
    query = answer.get("search_query", "") or ""
    filter_cols = [m.group(1) for m in _FILTER.finditer(query)]
    dims, measures = [], []
    date_column, date_bucket = None, None
    partial = not query
    seen = set()
    for m in _TOKEN.finditer(query):
        name, suffix = m.group(1), (m.group(2) or "").lower()
        if name in seen:
            continue
        seen.add(name)
        kind = kinds.get(name)
        if kind is None:
            if not name.startswith("formula_"):
                partial = True
            continue
        if name in filter_cols and kind != "MEASURE":
            continue  # filter-only column
        if kind == "MEASURE":
            measures.append(name)
        elif kind == "DATE":
            date_column = name
            date_bucket = BUCKET_TOKENS.get(suffix)
        else:
            dims.append(name)
    return {
        "source_guid": source_guid, "source_name": source_name,
        "source_type": source_type, "viz_name": viz_name,
        "dimensions": dims, "date_column": date_column, "date_bucket": date_bucket,
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
