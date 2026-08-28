"""Render a human-readable migration report (Markdown) from the mapping JSON(s).

Same rich shape as the rest of the family (qlik/looker): an executive summary and
a modernization scorecard framing a full per-object accounting, always leading the
manual-review section so a human sees the gaps first. Pure function: dicts in,
Markdown string out — every number is derived from the mappings, never invented.

`render_report` composes one `_section_*` helper per report section. Each takes the
`_Stats` bundle and returns its own lines, so a section can be read, changed or
tested on its own without walking the whole document.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

_REVIEW = {"NEEDS REVIEW", "Approximated", "Skipped"}


def _tally(items: list) -> tuple[int, int, int, int]:
    """(migrated, approximated, needs_review, skipped)."""
    m = a = r = s = 0
    for it in items:
        st = it.get("status", "Migrated")
        if st == "Migrated":
            m += 1
        elif st == "Approximated":
            a += 1
        elif st == "Skipped":
            s += 1
        else:
            r += 1
    return m, a, r, s


def _pct(n: int, d: int) -> int:
    """Percentage, or 0 when there is nothing to measure.

    Returning 100 on a zero denominator made an empty/unreadable bundle render as
    "Automation 100% — clean conversion", i.e. the most reassuring possible report for
    the case where nothing was converted at all.
    """
    return round(100 * n / d) if d else 0


def _chasm_keys(joins: list) -> list[str]:
    """Join keys used by >= 2 joins — a multi-fact fan-out (chasm-trap) risk."""
    counts: dict[str, int] = {}
    for j in joins:
        for k in str(j.get("on", "")).split(","):
            k = k.strip()
            if k:
                counts[k] = counts.get(k, 0) + 1
    return sorted([k for k, c in counts.items() if c >= 2])


def _complexity_effort(n_tables: int, n_joins: int) -> tuple[str, str]:
    if n_joins == 0 and n_tables <= 1:
        return "Low", "~0.5 engineer-day"
    if n_tables <= 3 and n_joins <= 3:
        return "Low–Medium", "~0.5–1 engineer-day"
    if n_tables <= 8:
        return "Medium", "~1 engineer-day"
    return "Medium–High", "~1–2 engineer-days"


def _risk_level(needs: int, approx: int, chasm: list, n_joins: int,
                dropped: int = 0, findings: int = 0, unread: int = 0,
                ambiguous: int = 0) -> str:
    """Risk must account for EVERY class the report can flag, not one of them.

    The first version keyed only off NEEDS REVIEW, so a conversion where every card
    lost its filters reported "Low — clean conversion". That was fixed for
    `Approximated` and not generalised, so a bundle that dropped 7 joins still reported
    "Automation 100% · Risk Low". `dropped` (joins not emitted) and `findings`
    (TML-invariant + aggregation changes) close the remaining inputs.
    """
    if not (needs or approx or dropped or findings or chasm or unread or ambiguous):
        return "Low"
    # An unread source file means data is MISSING, not approximated — that outranks
    # everything else, because the report cannot describe what it never parsed.
    if unread or chasm or needs or dropped or n_joins >= 5:
        return "Medium"
    return "Low–Medium"


# ---------------------------------------------------------------------------
# Derived numbers — computed once, read by every section
# ---------------------------------------------------------------------------

@dataclass
class _Stats:
    app_name: str
    mode: str
    datasets: list
    joins: list
    beast: list
    renamed: list
    invariants: list
    agg_changes: list
    cards: list
    pages: list
    n_tables: int
    n_cols: int
    n_joins: int
    n_beast: int
    n_cards: int
    n_pages: int
    n_pages_skipped: int
    cards_skipped: int
    bm_m: int
    bm_r: int
    bm_a: int
    jn_r: int
    cd_r: int
    cd_a: int
    ds_a: int
    needs: int
    approx: int
    automation: int
    complexity: str
    effort: str
    risk: str
    chasm: list = field(default_factory=list)
    from_etl: bool = False
    join_warnings: list = field(default_factory=list)
    join_drops: list = field(default_factory=list)
    table_renames: list = field(default_factory=list)
    formula_renames: list = field(default_factory=list)
    ambiguities: list = field(default_factory=list)
    parse_notes: list = field(default_factory=list)
    n_dropped: int = 0
    nothing_parsed: bool = False


def _page_stats(lb_mapping: Optional[dict], cards: list) -> tuple[int, int, int, list]:
    """(pages_converted, pages_skipped, cards_skipped, page_rows).

    A page's status has to be read back rather than assumed: the mapping records a
    later page as Skipped, and the report used to hardcode "N pages -> N Liveboards".
    """
    pages = (lb_mapping or {}).get("pages", [])
    converted = sum(1 for p in pages if p.get("status", "Migrated") != "Skipped")
    skipped = sum(1 for p in pages if p.get("status") == "Skipped")
    cards_skipped = sum(1 for c in cards if c.get("status") == "Skipped")
    return converted, skipped, cards_skipped, pages


def _tallies(datasets: list, joins: list, beast: list,
             cards: list) -> tuple[dict, int, int]:
    """Per-class status tallies plus the NEEDS-REVIEW and Approximated totals."""
    bm_m, bm_a, bm_r, _s1 = _tally(beast)
    jn_m, jn_a, jn_r, _s2 = _tally(joins)
    cd_m, cd_a, cd_r, _s3 = _tally(cards)
    ds_m, ds_a, ds_r, _s4 = _tally(datasets)
    t = {"bm_m": bm_m, "bm_a": bm_a, "bm_r": bm_r, "jn_r": jn_r,
         "cd_r": cd_r, "cd_a": cd_a, "ds_a": ds_a,
         "migrated": ds_m + jn_m + bm_m + cd_m}
    return t, ds_r + jn_r + bm_r + cd_r, ds_a + jn_a + bm_a + cd_a


def _merged(mapping: dict, lb_mapping: Optional[dict], key: str) -> list:
    """A list present in either mapping — both stages record notes and ambiguities."""
    return list(mapping.get(key) or []) + list((lb_mapping or {}).get(key) or [])


def _compute_stats(mapping: dict, lb_mapping: Optional[dict]) -> _Stats:
    src = mapping.get("source", {})
    datasets = mapping.get("datasets", [])
    joins = mapping.get("joins", [])
    beast = mapping.get("beast_modes", [])
    cards = (lb_mapping or {}).get("cards", [])

    t, needs_total, approx = _tallies(datasets, joins, beast, cards)
    bm_m, bm_a, bm_r = t["bm_m"], t["bm_a"], t["bm_r"]
    jn_r, cd_r, cd_a, ds_a = t["jn_r"], t["cd_r"], t["cd_a"], t["ds_a"]
    invariants = list(mapping.get("invariant_findings") or [])
    agg_changes = list(mapping.get("aggregation_changes") or [])
    drops = list(mapping.get("join_drops") or [])
    ambiguities = _merged(mapping, lb_mapping, "name_ambiguities")
    parse_notes = _merged(mapping, lb_mapping, "parse_notes")
    pages_converted, pages_skipped, cards_skipped, _rows = _page_stats(lb_mapping, cards)

    n_tables, n_joins, n_beast, n_cards = len(datasets), len(joins), len(beast), len(cards)
    # Dropped joins and aggregation changes are work the user still has to do, so they
    # belong in the denominator. Leaving them out reported "Automation 100%" for a
    # bundle where 7 relationships were never emitted.
    n_dropped = len(drops)
    total = n_tables + n_joins + n_beast + n_cards + n_dropped
    needs = needs_total
    chasm = _chasm_keys(joins)
    complexity, effort = _complexity_effort(n_tables, n_joins)

    return _Stats(
        app_name=src.get("app_name", "Untitled"),
        mode=src.get("mode", "offline"),
        datasets=datasets, joins=joins, beast=beast,
        renamed=mapping.get("renamed_columns", []),
        invariants=invariants,
        agg_changes=agg_changes,
        cards=cards, pages=(lb_mapping or {}).get("pages", []),
        n_tables=n_tables,
        n_cols=sum(d.get("columns", 0) for d in datasets),
        n_joins=n_joins, n_beast=n_beast, n_cards=n_cards,
        n_pages=pages_converted,
        n_pages_skipped=pages_skipped,
        cards_skipped=cards_skipped,
        bm_m=bm_m, bm_r=bm_r, bm_a=bm_a, jn_r=jn_r, cd_r=cd_r, cd_a=cd_a, ds_a=ds_a,
        needs=needs, approx=approx,
        automation=_pct(t["migrated"], total),
        n_dropped=n_dropped,
        complexity=complexity, effort=effort,
        risk=_risk_level(needs + pages_skipped, approx, chasm, n_joins,
                         dropped=n_dropped,
                         findings=len(invariants) + len(agg_changes),
                         unread=len(parse_notes), ambiguous=len(ambiguities)),
        chasm=chasm,
        from_etl=any(j.get("source") == "magic_etl" for j in joins),
        join_warnings=list(mapping.get("join_warnings") or []),
        join_drops=drops,
        table_renames=list(mapping.get("table_renames") or []),
        formula_renames=list(mapping.get("formula_renames") or []),
        ambiguities=ambiguities,
        parse_notes=parse_notes,
        nothing_parsed=not (datasets or joins or beast or cards),
    )


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _section_header(st: _Stats) -> list[str]:
    prov = "data model = **SOURCE** (Domo dataset schemas)"
    if st.from_etl:
        prov += " + joins from the **Magic ETL** export"
    if st.cards:
        prov += " · charts = **INFERRED** from the dashboard PDF (verify)"
    return [
        "# Domo → ThoughtSpot Migration Report",
        "",
        f"**App:** {st.app_name}  ",
        f"**Source mode:** {st.mode}  ",
        f"**Provenance:** {prov}",
        "",
    ]


def _section_exec_summary(st: _Stats) -> list[str]:
    if st.nothing_parsed:
        return [
            "## Executive summary",
            "",
            "⚠️ **Nothing was parsed from this source.** No datasets, joins, Beast Modes or "
            "cards were found, so there is nothing to migrate and no automation to report. "
            "Check that the bundle directory contains the expected Domo JSON files "
            "(see the skill's Prerequisites) and re-run `ts domo parse` to inspect `notes`.",
            "",
        ]
    risk_bits = []
    if st.needs:
        risk_bits.append(f"{st.needs} item(s) flagged NEEDS REVIEW")
    if st.approx:
        risk_bits.append(f"{st.approx} item(s) Approximated — mapped with a caveat, "
                         "each listed under Manual review")
    if st.n_pages_skipped:
        risk_bits.append(f"{st.n_pages_skipped} Domo page(s) and {st.cards_skipped} "
                         "card(s) were not converted at all")
    if st.join_drops:
        risk_bits.append(f"{len(st.join_drops)} relationship(s) could not be emitted "
                         "as a join")
    if st.agg_changes:
        risk_bits.append(f"{len(st.agg_changes)} measure(s) had their aggregation "
                         "changed from SUM, which changes every number")
    if st.parse_notes:
        risk_bits.insert(0, f"**{len(st.parse_notes)} source file(s) could not be read "
                            "in full — this conversion is incomplete**")
    if st.ambiguities:
        risk_bits.append(f"{len(st.ambiguities)} name(s) are ambiguous between a column "
                         "and a Beast Mode")
    if st.chasm:
        risk_bits.append(
            "multiple facts share the join key(s) "
            + ", ".join(f"`{k}`" for k in st.chasm)
            + " — confirm cardinality to avoid measure fan-out (chasm trap)")
    if not risk_bits:
        risk_bits.append("clean conversion — no structural gaps")
    return [
        "## Executive summary",
        "",
        f"- **Migration complexity:** {st.complexity}",
        f"- **Automation %:** {st.automation}%  |  **Manual %:** {100 - st.automation}%",
        f"- **Estimated effort:** {st.effort}",
        f"- **Risk score:** {st.risk} — " + "; ".join(risk_bits) + ".",
        "",
    ]


def _section_inventory(st: _Stats) -> list[str]:
    return [
        "## Inventory",
        "",
        f"- **Tables:** {st.n_tables}  |  **Columns:** {st.n_cols}",
        f"- **Relationships:** {st.n_joins}  |  **Measures (Beast Modes):** {st.n_beast}",
        (f"- **Pages:** {st.n_pages}  |  **Visuals:** {st.n_cards - st.cards_skipped}"
         + (f"  (+{st.n_pages_skipped} page(s) / {st.cards_skipped} card(s) NOT "
            "converted)" if st.n_pages_skipped else "")),
        "",
    ]


def _section_modernization(st: _Stats) -> list[str]:
    n_pages = st.n_pages
    if not n_pages:
        # `or 1` invented a page: running `report` after build-model only produced
        # "Pages → Liveboards | 0 |" in the table and "the 1 Domo page(s) map to 1
        # Liveboard(s)" in the prose of the same document.
        line = ("**Dashboards eliminated:** no Liveboard was built — run "
                "`ts domo build-liveboard` for the card/page half of the conversion.")
    else:
        line = (f"**Dashboards eliminated:** none — the {n_pages} Domo page(s) map to "
                f"{n_pages} Liveboard(s).")
    if st.n_pages_skipped:
        line = (f"**Pages:** {n_pages} of {n_pages + st.n_pages_skipped} Domo page(s) "
                f"became a Liveboard. **{st.n_pages_skipped} page(s) and "
                f"{st.cards_skipped} card(s) were NOT converted** — only the first Domo "
                "page is migrated; rebuild the rest by hand (each is listed under "
                "Manual review).")
    L = ["## Modernization", "", line, ""]
    kpi_cards = [c for c in st.cards if str(c.get("chart_type", "")).lower() == "kpi"]
    if kpi_cards:
        L += [f"**Search opportunities:** the {len(kpi_cards)} KPI card(s) "
              "are re-askable on demand via Search; kept as tiles for the overview band.",
              ""]
    L += ["**Spotter opportunities:** stand up Spotter on the model for conversational "
          "\"explain <measure> by <dimension>\" breakdowns that replace static charts.",
          "",
          "**Semantic improvements:**"]
    if st.bm_m:
        L.append(f"- Promoted {st.bm_m} Domo Beast Mode(s) to reusable model measures.")
    if st.bm_r:
        L.append(f"- Rewrite {st.bm_r} Beast Mode(s) flagged NEEDS REVIEW in ThoughtSpot syntax "
                 "(see Data model → formulas).")
    if st.renamed:
        L.append(f"- Disambiguated {len(st.renamed)} display-name collision(s); join keys stay "
                 "physically present on both tables so joins resolve.")
    if st.n_joins:
        L.append("- Confirm each join is MANY_TO_ONE from the fact so additive measures do not "
                 "fan out across the star.")
    L.append("")
    return L


def _section_summary_table(st: _Stats) -> list[str]:
    L = [
        "## Summary by object type",
        "",
        "| Object type | In Domo | Migrated | Approximated | Needs review | Skipped |",
        "|---|---|---|---|---|---|",
    ]
    for label, items in [("Datasets → Tables", st.datasets), ("Joins", st.joins),
                         ("Beast Modes → Formulas", st.beast), ("Cards → Answers", st.cards)]:
        m, a, r, s = _tally(items)
        L.append(f"| {label} | {len(items)} | {m} | {a} | {r} | {s} |")
    pm, pa, pr, ps = _tally(st.pages)
    L.append(f"| Pages → Liveboards | {len(st.pages)} | {pm} | {pa} | {pr} | {ps} |")
    L.append("")
    return L


def _section_data_model(st: _Stats) -> list[str]:
    L = ["## Data model", "", "### Tables", "",
         "| Domo dataset | ThoughtSpot table | Columns | Status |", "|---|---|---|---|"]
    for d in st.datasets:
        L.append(f"| {d.get('name')} | {d.get('ts_table')} | {d.get('columns')} | "
                 f"{d.get('status')} |")
    L.append("")

    if st.joins:
        L += ["### Relationships → joins", "",
              "| Relationship | On | Status | Note |", "|---|---|---|---|"]
        for j in st.joins:
            L.append(f"| {j.get('left')} ↔ {j.get('right')} | `{j.get('on')}` | "
                     f"{j.get('status')} | {j.get('note', '')} |")
        L.append("")

    if st.beast:
        L += ["### Beast Modes → Formulas", "",
              "| Name | Domo formula | ThoughtSpot formula | Status |", "|---|---|---|---|"]
        for f in st.beast:
            L.append(f"| {f.get('name')} | `{f.get('domo_formula')}` | "
                     f"`{f.get('ts_formula')}` | {f.get('status')} |")
        L.append("")
    return L


def _section_cards(st: _Stats) -> list[str]:
    L: list[str] = []
    if st.cards:
        L += ["## Cards → answers & liveboard", "",
              "| Card | ThoughtSpot chart | Status | Note |", "|---|---|---|---|"]
        for c in st.cards:
            ts_chart = c.get("ts_chart") or str(c.get("chart_type", "")).upper()
            L.append(f"| {c.get('title', c.get('urn'))} | {ts_chart} | {c.get('status')} "
                     f"| {c.get('note', '')} |")
        L.append("")
        if st.pages:
            L += [f"Assembled onto Liveboard **{st.pages[0].get('name')}** "
                  f"({st.pages[0].get('cards')} tiles).", ""]

    if st.renamed or st.table_renames or st.formula_renames:
        L += ["### Renamed to keep Model names unique", "",
              "A ThoughtSpot Model exposes one flat namespace, so a name used twice in "
              "Domo has to be disambiguated. The physical column is unchanged — only "
              "the display name.", ""]
        for rc in st.table_renames:
            L.append(f"- **Dataset** `{rc.get('from')}` → `{rc.get('to')}`")
        for rc in st.renamed:
            reason = rc.get("reason")
            L.append(f"- **Column** `{rc.get('from')}` → `{rc.get('to')}` "
                     f"(table {rc.get('table')})"
                     + (f" — {reason}" if reason else ""))
        for rc in st.formula_renames:
            L.append(f"- **Beast Mode** `{rc.get('from')}` → `{rc.get('to')}` "
                     f"(dataset {rc.get('dataset')}) — {rc.get('reason', '')}")
        L.append("")
    return L


def _source_review_rows(st: _Stats) -> list[str]:
    """Rows that mean data is MISSING or a name is ambiguous — read these first."""
    rows: list[str] = []
    for n in st.parse_notes:
        msg = n.get("message") if isinstance(n, dict) else str(n)
        rows.append(f"- **Source not fully read** — {msg}. Anything in that file is "
                    "missing from this conversion.")
    for a in st.ambiguities:
        rows.append(f"- **Ambiguous name** — {a}")
    return rows


def _object_review_rows(st: _Stats) -> list[str]:
    """Rows for individual objects the converter flagged."""
    rows: list[str] = []
    for j in st.joins:
        if j.get("status") in _REVIEW:
            rows.append(
                f"- **Join** {j.get('left')} ↔ {j.get('right')} on `{j.get('on')}` "
                f"({j.get('status')}) — {j.get('note', '')}. Confirm MANY_TO_ONE from "
                "the fact.")
    if st.chasm:
        rows.append(
            "- **Chasm-trap risk** — multiple facts share "
            + ", ".join(f"`{k}`" for k in st.chasm)
            + ". Keep each measure on its home fact (or split into separate Answers) so "
            "counts/sums do not fan out.")
    for f in st.beast:
        if f.get("status") in _REVIEW:
            rows.append(
                f"- **Formula** `{f.get('name')}` ({f.get('status')}) — "
                f"{f.get('note') or 'manual rewrite required'}  \n"
                f"  Domo: `{f.get('domo_formula')}`")
    for c in st.cards:
        if c.get("status") in _REVIEW:
            rows.append(
                f"- **Card** `{c.get('title', c.get('urn'))}` ({c.get('chart_type')}, "
                f"{c.get('status')}) — {c.get('note') or 'rebuild in ThoughtSpot'}")
    return rows


def _review_rows(st: _Stats) -> list[str]:
    """Manual-review rows, ordered by how much they cost the reader to miss."""
    rows = _source_review_rows(st) + _object_review_rows(st)
    for w in st.join_warnings:
        rows.append(f"- **Join not emitted / ambiguous** — {w}")
    for a in st.agg_changes:
        rows.append(f"- **Aggregation changed** — `{a['column']}` {a['note']}")
    for m in st.invariants:
        rows.append(f"- **TML invariant** — {m}")
    return rows


def _section_manual_review(st: _Stats) -> list[str]:
    rows = _review_rows(st)
    return ["## Manual review (do these in ThoughtSpot)", ""] + (
        rows if rows else ["_Nothing flagged — every object migrated cleanly._"]) + [""]


def _section_checklist(st: _Stats) -> list[str]:
    L = ["## Verification checklist", "",
         "- Pick one known total in Domo and confirm the identical number in ThoughtSpot "
         "(via Search / searchdata)."]
    if st.n_joins:
        L.append("- Slice a measure by a dimension across each join and confirm it does not "
                 "fan out (validates the join cardinality).")
    if st.bm_r:
        L.append("- Confirm every NEEDS REVIEW Beast Mode resolves correctly after its rewrite.")
    if st.bm_a:
        L.append("- Check each Approximated formula against the source Beast Mode "
                 "(grain, argument order, sample-vs-population).")
    if st.cd_r or st.cd_a:
        L.append("- Rebuild each flagged card and confirm it matches the source dashboard "
                 "tile — including its sort, filters and number formats, which are not "
                 "carried across.")
    if st.n_pages_skipped:
        L.append(f"- Rebuild the {st.n_pages_skipped} Domo page(s) that were not "
                 f"converted ({st.cards_skipped} card(s)) as additional Liveboards.")
    L += ["- Confirm any source filters became Liveboard filters and slice every tile.", ""]
    return L


def _section_scorecard(st: _Stats) -> list[str]:
    sem = max(60, 90 - (10 if st.jn_r else 0) - (10 if st.chasm else 0)
              - (5 if st.ds_a else 0))
    search = max(60, 90 - 5 * st.bm_r - 3 * st.bm_a)
    spotter = 85 if st.n_beast else 75
    lb = max(20, 90 - 5 * st.cd_r - 8 * st.cd_a
             - 15 * st.n_pages_skipped - 5 * st.cards_skipped)
    ai = 80 if st.n_beast else 70
    n_pages = st.n_pages
    return [
        "## ThoughtSpot Modernization Scorecard",
        "",
        "| Category | Score | Recommendation |",
        "|---|---|---|",
        f"| Semantic Model | {sem}/100 | "
        + ("Confirm MANY_TO_ONE cardinalities"
           + (" and resolve the chasm trap" if st.chasm else "")
           + " to lock the grain." if st.n_joins else
           "Flat, clean dataset; promote categoricals to model formulas.") + " |",
        f"| Search Readiness | {search}/100 | "
        + ("Friendly names + reusable measures in place; finish the flagged formula rewrites."
           if st.bm_r else "Friendly names + reusable measures in place.") + " |",
        f"| Spotter Readiness | {spotter}/100 | "
        "Stand up Spotter on the model to replace static breakdown charts. |",
        f"| Liveboards | {lb}/100 | "
        + (f"{n_pages} page(s) → {n_pages} Liveboard(s)"
           + (f"; {st.n_pages_skipped} page(s) not converted"
              if st.n_pages_skipped else "")
           + ("; rebuild the flagged tile(s) to reach 100."
              if (st.cd_r or st.cd_a) else ".")) + " |",
        f"| AI Readiness | {ai}/100 | "
        "Add a Monitor/Alert on a key measure and enable Spotter. |",
        "",
    ]


_SECTIONS = (
    _section_header,
    _section_exec_summary,
    _section_inventory,
    _section_modernization,
    _section_summary_table,
    _section_data_model,
    _section_cards,
    _section_manual_review,
    _section_checklist,
    _section_scorecard,
)


def render_report(mapping: dict, lb_mapping: Optional[dict] = None) -> str:
    """Render the full Markdown migration report from the build mapping(s)."""
    st = _compute_stats(mapping, lb_mapping)
    lines: list[str] = []
    for section in _SECTIONS:
        lines.extend(section(st))
    return "\n".join(lines)
