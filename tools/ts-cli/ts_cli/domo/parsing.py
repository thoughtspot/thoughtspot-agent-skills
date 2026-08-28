"""Offline parse: a directory of exported Domo JSON -> DomoApp IR + flat inventory.

Files are classified by shape (not filename), so any capture layout matching the
Domo API responses works.

There is no live mode and `mode` is not honoured here: a Domo card's analyzer query is
not reachable from any Domo API a token can reach, so a live extraction could not fill
the IR faithfully (see the skill's references/open-items.md #3, #4). `ts domo` refuses
any --mode other than `offline` rather than recording a mode it did not use.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Any

from .ir import (
    BeastMode, Card, CardQuery, Dataset, DomoApp, DomoColumn,
    Page, QueryColumn, QueryFilter, QueryOrder,
)


def parse_app(source: str, *, mode: str = "offline") -> DomoApp:
    app = DomoApp(app_name="Untitled", source=source, extraction_mode=mode)
    if not os.path.isdir(source):
        app.note("warning", "parse", f"source is not a directory: {source}")
        return app
    for fp in sorted(glob.glob(os.path.join(source, "*.json"))):
        try:
            with open(fp) as fh:
                data = json.load(fh)
        except Exception as e:  # noqa: BLE001 — never crash on a bad file
            app.note("warning", "parse", f"could not read {os.path.basename(fp)}: {e}")
            continue
        _classify(app, data, os.path.basename(fp))
    if app.pages and app.pages[0].name:
        app.app_name = app.pages[0].name
    return app


def _classify(app: DomoApp, data: Any, fname: str) -> None:
    if not isinstance(data, dict):
        app.note("warning", "parse", f"unrecognized object in {fname}")
        return
    results = data.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict) \
            and "formula" in results[0]:
        for r in results:
            app.beast_modes.append(BeastMode(
                id=r.get("id"), name=r.get("name", ""), formula=r.get("formula", ""),
                data_source_id=r.get("dataSourceId"),
                is_global=bool(r.get("global", True)), status=r.get("status")))
        return
    if isinstance(data.get("schema"), dict) and "columns" in data["schema"]:
        cols = [DomoColumn(name=c.get("name", ""), domo_type=c.get("type", "STRING"))
                for c in data["schema"]["columns"]]
        app.datasets.append(Dataset(
            id=data.get("id", ""), name=data.get("name", ""),
            description=data.get("description"), rows=data.get("rows"), columns=cols))
        return
    if "chartType" in data and ("urn" in data or "id" in data):
        app.cards.append(_parse_card(data))
        return
    if "cardIds" in data:
        app.pages.append(Page(
            id=data.get("id"), name=data.get("name", ""),
            card_ids=[str(c) for c in data.get("cardIds", [])],
            collection_ids=data.get("collectionIds", []),
            children=data.get("children", [])))
        return
    app.note("warning", "parse", f"unrecognized object in {fname}")


def _parse_card(data: dict) -> Card:
    body = data.get("chartBody") or data.get("summaryNumber") or {}

    def _gb(g: Any) -> str:
        return g.get("column", "") if isinstance(g, dict) else str(g)

    query = CardQuery(
        columns=[QueryColumn(column=c.get("column", ""), aggregation=c.get("aggregation"),
                             alias=c.get("alias"), fmt=c.get("format"))
                 for c in body.get("columns", [])],
        group_by=[_gb(g) for g in body.get("groupBy", [])],
        order_by=[QueryOrder(column=o.get("column", ""), order=o.get("order", "ASCENDING"))
                  for o in body.get("orderBy", [])],
        filters=[QueryFilter(column=f.get("column", ""), operand=f.get("operand", ""),
                             values=f.get("values", []))
                 for f in body.get("filters", [])],
        limit=body.get("limit"),
    )
    calc = [BeastMode(id=cf.get("id"), name=cf.get("name", ""), formula=cf.get("formula", ""),
                      data_source_id=data.get("dataSetId"), is_global=False)
            for cf in data.get("calculatedFields", [])]
    return Card(
        urn=str(data.get("urn") or data.get("id")), title=data.get("title", ""),
        chart_type=data.get("chartType", "table"), data_set_id=data.get("dataSetId"),
        calc_fields=calc, query=query,
        conditional_formats=data.get("conditionalFormats", []),
        quick_filters=data.get("quickFilters", []),
        pref_width=data.get("preferredFullWidth"), pref_height=data.get("preferredFullHeight"))


def build_inventory(app: DomoApp) -> dict:
    """Flatten a DomoApp into the JSON the `parse` command emits."""
    return {
        "app_name": app.app_name,
        "extraction_mode": app.extraction_mode,
        "counts": {
            "datasets": len(app.datasets), "beast_modes": len(app.beast_modes),
            "cards": len(app.cards), "pages": len(app.pages),
        },
        "datasets": [
            {"id": d.id, "name": d.name, "rows": d.rows,
             "columns": [{"name": c.name, "type": c.domo_type} for c in d.columns]}
            for d in app.datasets],
        "beast_modes": [
            {"id": b.id, "name": b.name, "formula": b.formula,
             "data_source_id": b.data_source_id, "global": b.is_global}
            for b in app.beast_modes],
        "cards": [
            {"urn": c.urn, "title": c.title, "chart_type": c.chart_type,
             "data_set_id": c.data_set_id} for c in app.cards],
        "pages": [
            {"id": p.id, "name": p.name, "card_ids": p.card_ids} for p in app.pages],
        "notes": [
            {"severity": n.severity, "area": n.area, "message": n.message}
            for n in app.notes],
    }
