"""DomoApp IR -> Answers embedded in one Liveboard TML.

The Liveboard is a single page of tiles — Domo `collectionIds` / page `children` are
NOT translated into Liveboard tabs (see the skill's coverage matrix).

Resolves page.card_ids -> cards (page order), one Answer per card. No shared answer
emitter exists in this codebase, so the Answer/Liveboard TML is hand-built here
(same as the qlik converter did).
"""
from __future__ import annotations

import uuid
from typing import Optional

from .ir import Card, DomoApp, note_rows
from .naming import Index, build_index, bundle_digest

# Domo chartType -> ThoughtSpot chart.type (verified enum, thoughtspot-chart-types.md)
_CHART_MAP = {
    "kpi": "KPI", "bar": "BAR", "column": "COLUMN", "line": "LINE",
    "pie": "PIE", "area": "AREA", "scatter": "SCATTER",
    # "table" is handled specially -> TABLE_MODE (no chart block)
}


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (s or "")).strip("_") or "obj"


def _ordered_columns(card: Card,
                     index: Index) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return (attrs, measures, ordered, unresolved) — group-by first, then measures.

    Names are resolved through the shared ColumnIndex, scoped to the card's own
    dataset. Emitting the raw Domo name meant a card on the second dataset grouped by
    the FIRST dataset's column of the same name — a clean import with wrong numbers.
    """
    attrs: list[str] = []
    measures: list[str] = []
    unresolved: list[str] = []
    seen: set = set()

    def _resolve(raw: str) -> str:
        # A card column is either a dataset column or a Beast Mode (a Model formula).
        # Both may have been renamed, and both are resolved from the same index.
        resolved = index.resolve(card.data_set_id, raw)
        if resolved is None:
            unresolved.append(raw)
            return raw
        return resolved

    for g in card.query.group_by:
        if not g:
            continue
        name = _resolve(g)
        if name not in seen:
            seen.add(name)
            attrs.append(name)
    for c in card.query.columns:
        if not c.column:
            continue
        name = _resolve(c.column)
        if name in seen:
            continue
        seen.add(name)
        (attrs if c.column in card.query.group_by else measures).append(name)
    return attrs, measures, attrs + measures, unresolved


def _search_query(card: Card, ordered: list[str], ctype: str) -> str:
    parts = [f"[{c}]" for c in ordered]
    if card.query.limit and ctype != "kpi":
        parts.append(f"top {card.query.limit}")
    return " ".join(parts)


def _answer_shell(card: Card, model_name: str, model_fqn: Optional[str],
                  ordered: list[str], search_query: str) -> dict:
    table_ref = {"id": model_name, "name": model_name}
    if model_fqn:
        table_ref["fqn"] = model_fqn
    return {
        "name": card.title or "Untitled",
        "tables": [table_ref],
        "search_query": search_query,
        "answer_columns": [{"name": c} for c in ordered],
        # The `table` block is required on every viz, chart or not.
        "table": {
            "table_columns": [{"column_id": c, "show_headline": False} for c in ordered],
            "ordered_column_ids": ordered,
            "client_state": "",
            "client_state_v2": '{"tableVizPropVersion": "V1"}',
        },
    }


def _apply_display_mode(answer: dict, card: Card, ctype: str, attrs: list[str],
                        measures: list[str], ordered: list[str]) -> tuple[bool, str]:
    """Set display_mode (+ chart block). Return (review, reason)."""
    if ctype == "table":
        answer["display_mode"] = "TABLE_MODE"
        return False, ""
    if ctype in _CHART_MAP:
        # A chart needs chart_columns + axis_configs (x=attributes, y=measures);
        # an empty/absent axis is what triggers the importer's "Index: 0" error.
        answer["display_mode"] = "CHART_MODE"
        answer["chart"] = {
            "type": _CHART_MAP[ctype],
            "chart_columns": [{"column_id": c} for c in ordered],
            "axis_configs": [{"x": attrs, "y": measures}],
            "client_state": "",
        }
        return False, ""
    answer["display_mode"] = "TABLE_MODE"
    return True, f"unmapped Domo chartType '{card.chart_type}' — rendered as table"


def _answer(card: Card, model_name: str, model_fqn: Optional[str],
            index: Index) -> tuple[dict, bool, str]:
    attrs, measures, ordered, unresolved = _ordered_columns(card, index)
    ctype = card.chart_type.lower()
    answer = _answer_shell(card, model_name, model_fqn, ordered,
                           _search_query(card, ordered, ctype))
    review, reason = _apply_display_mode(answer, card, ctype, attrs, measures, ordered)
    if unresolved:
        review = True
        reason = "; ".join(x for x in [
            reason,
            "references column(s) the Model does not expose: "
            + ", ".join(sorted(set(unresolved)))] if x)
    return answer, review, reason


def _describe_sort(card: Card) -> Optional[str]:
    if not card.query.order_by:
        return None
    # Domo's orderBy names the card's column ALIAS ("Total Revenue"), not the underlying
    # column ("Net Revenue"). Say so, or the reader hunts for a column that doesn't exist.
    return "sort (%s — Domo alias)" % ", ".join(
        f"{o.column} {o.order}".strip() for o in card.query.order_by)


def _describe_filters(card: Card) -> Optional[str]:
    if not card.query.filters:
        return None
    return "card filter(s) (%s)" % ", ".join(
        f"{f.column} {f.operand}".strip() for f in card.query.filters)


def _describe_quick_filters(card: Card) -> Optional[str]:
    if not card.quick_filters:
        return None
    return "quick filter(s) (%s)" % ", ".join(
        str(f.get("column") or f.get("name") or "?") for f in card.quick_filters)


def _describe_conditional_formats(card: Card) -> Optional[str]:
    if not card.conditional_formats:
        return None
    return f"conditional formatting ({len(card.conditional_formats)} rule(s))"


def _describe_number_formats(card: Card) -> Optional[str]:
    formatted = [c.column for c in card.query.columns if c.fmt]
    if not formatted:
        return None
    return "number format on %s" % ", ".join(formatted)


def _describe_aggregation_overrides(card: Card) -> Optional[str]:
    """A card can override the aggregation per column (MIN/MAX/AVG/COUNT).

    The Answer carries no aggregation, so the Model default (SUM for numerics)
    applies — a `MIN(Price)` card would otherwise silently render as `SUM(Price)`.
    """
    overrides = [f"{c.column}={c.aggregation.upper()}" for c in card.query.columns
                 if c.aggregation and c.aggregation.upper() not in ("SUM", "")]
    if not overrides:
        return None
    return ("non-SUM aggregation (%s) — the Answer falls back to the Model default"
            % ", ".join(overrides))


# Each describer returns a human-readable string, or None when the card does not
# carry that construct. Adding a newly-dropped construct means adding one describer.
_DROPPED_DESCRIBERS = (
    _describe_sort,
    _describe_filters,
    _describe_quick_filters,
    _describe_conditional_formats,
    _describe_number_formats,
    _describe_aggregation_overrides,
)


def _dropped_constructs(card: Card) -> list[str]:
    """Constructs present on the Domo card that the emitted Answer does NOT carry.

    These are parsed into the IR but not translated (see references/open-items.md #11).
    Reporting them per card is the point: without this, a card whose sort, date filter
    and quick filters were all left behind still counted as fully "Migrated", which is
    exactly the silent downgrade this converter is supposed to refuse to do.
    """
    return [d for d in (describe(card) for describe in _DROPPED_DESCRIBERS) if d]


def _viz_guid() -> str:
    return str(uuid.uuid4())


def _card_mapping_row(card: Card, ans: dict, review: bool, reason: str,
                      dropped: list[str]) -> dict:
    """One card's row in the liveboard mapping — the report's source of truth."""
    notes = [reason] if reason else []
    if dropped:
        notes.append("not carried onto the Answer — rebuild by hand: "
                     + "; ".join(dropped))
    return {
        "urn": card.urn, "title": card.title, "chart_type": card.chart_type,
        "ts_chart": ans.get("chart", {}).get("type", "TABLE"),
        "status": ("NEEDS REVIEW" if review
                   else "Approximated" if dropped else "Migrated"),
        "note": " | ".join(notes),
        "dropped_constructs": dropped,
    }


def _report_skipped_pages(app: DomoApp, card_by_urn: dict,
                          mapping_cards: list[dict]) -> list[dict]:
    """Record every Domo page after the first, and its cards, as Skipped.

    Only the FIRST page becomes a Liveboard (declared in the coverage matrix). Cards on
    later pages used to disappear with no mapping row at all, so the report could not
    mention them and still asserted "the 1 Domo page(s) map to 1 Liveboard(s)".
    """
    # A card can appear on more than one Domo page. Only report it Skipped if it did
    # not already make it onto the Liveboard from page 1 — otherwise it got both a
    # Migrated and a Skipped row, told the reader to rebuild a card that is already
    # there, and inflated cards_skipped.
    already = {c["urn"] for c in mapping_cards}
    skipped_pages: list[dict] = []
    for extra in app.pages[1:]:
        pending = [u for u in extra.card_ids if str(u) not in already]
        skipped_pages.append({
            "name": extra.name, "cards": len(extra.card_ids),
            "cards_not_converted": len(pending),
            "status": "Skipped" if pending else "Migrated",
            "note": ("only the first Domo page is converted to a Liveboard — rebuild "
                     "this page separately" if pending else
                     "every card on this page is already on the Liveboard from page 1")})
        for urn in pending:
            already.add(str(urn))
            other = card_by_urn.get(str(urn))
            mapping_cards.append({
                "urn": str(urn),
                "title": other.title if other else str(urn),
                "chart_type": other.chart_type if other else "",
                "ts_chart": "",
                "status": "Skipped",
                "note": f"on Domo page '{extra.name}', which is not converted — only "
                        "the first page becomes a Liveboard",
                "dropped_constructs": [],
            })
    return skipped_pages


def _assemble_page(order: list, card_by_urn: dict, model_name: str,
                   model_fqn: Optional[str], index: Index) -> tuple[list, list, list]:
    """Build the Answers, tile layout and mapping rows for the first page."""
    vizzes: list[dict] = []
    tiles: list[dict] = []
    mapping_cards: list[dict] = []
    x = y = row_h = idx = 0
    for urn in order:
        card = card_by_urn.get(str(urn))
        if not card:
            mapping_cards.append({"urn": str(urn), "status": "Skipped",
                                  "note": "card id in page not found among cards"})
            continue
        idx += 1
        ans, review, reason = _answer(card, model_name, model_fqn, index)
        dropped = _dropped_constructs(card)
        vid = f"Viz_{idx}"
        vizzes.append({"id": vid, "answer": ans, "viz_guid": _viz_guid()})
        w = max(card.pref_width or 6, 3)
        h = max(card.pref_height or 4, 2)
        if x + w > 12:
            # Advance by the TALLEST tile in the row being closed, not by the height of
            # the tile that happens to wrap — otherwise a short tile wrapping under a
            # tall one lands inside it and the tiles overlap.
            x = 0
            y += row_h
            row_h = 0
        tiles.append({"visualization_id": vid, "x": x, "y": y, "width": w, "height": h})
        x += w
        row_h = max(row_h, h)
        mapping_cards.append(_card_mapping_row(card, ans, review, reason, dropped))
    return vizzes, tiles, mapping_cards


def build_liveboard_artifacts(app: DomoApp, *, model_name: str,
                              model_fqn: Optional[str] = None,
                              report_name: Optional[str] = None,
                              index: Optional[Index] = None) -> dict:
    """Build Answer + Liveboard TML.

    `index` should be the namespace `build-model` resolved and wrote to `mapping.json`.
    Passing it is what makes the two stages agree by construction rather than by both
    re-deriving the same rule and hoping. When it is omitted the index is re-derived
    (deterministically) and `mapping["index_rederived"]` is set so the caller can warn.
    """
    if index is None:
        index = build_index(app)
    # `Index.derived` is the single source of this fact: True when the namespace was
    # computed here, False when it was loaded from a previous stage's mapping. Keeping a
    # separate local alongside it would be two records of one thing.
    page = app.pages[0] if app.pages else None
    report_name = report_name or (page.name if page else app.app_name) or "Domo Liveboard"
    order = page.card_ids if page else [c.urn for c in app.cards]
    card_by_urn = {c.urn: c for c in app.cards}

    vizzes, tiles, mapping_cards = _assemble_page(
        order, card_by_urn, model_name, model_fqn, index)

    skipped_pages = _report_skipped_pages(app, card_by_urn, mapping_cards)

    lb_tml = {"liveboard": {
        "name": report_name,
        "visualizations": vizzes,
        "layout": {"tiles": tiles},
    }}
    mapping = {
        "pages": ([{"name": report_name, "cards": len(vizzes)}] + skipped_pages),
        "cards": mapping_cards,
        "index_rederived": index.derived,
        "bundle_digest": index.bundle_digest or bundle_digest(app),
        "name_ambiguities": list(index.ambiguities),
        "parse_notes": note_rows(app),
    }
    return {
        "liveboard": {"filename": f"{_slug(report_name)}.liveboard.tml", "tml": lb_tml},
        "mapping": mapping,
        "counts": {"cards": len(vizzes),
                   "cards_skipped": sum(1 for c in mapping_cards
                                        if c["status"] == "Skipped"),
                   "pages_skipped": len(skipped_pages)},
    }
