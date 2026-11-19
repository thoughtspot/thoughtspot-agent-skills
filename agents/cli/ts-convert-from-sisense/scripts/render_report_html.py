#!/usr/bin/env python3
"""Render a Sisense -> ThoughtSpot conversion as one self-contained HTML page.

migration-report.json stays the source of truth. This page is the version people read,
projected in a room or opened by a business owner: how much of the dashboard is live,
what shipped, what the source dashboard itself gets wrong, how the model was adapted,
every decision the converter refused to guess at, and how the numbers reconcile, with
the per-widget detail folded away. Same sections and look as the Power BI skill's report.

    python3 render_report_html.py --bundle bundle.json --out-dir out/ \
        [--target-model target-model.json] [--overrides overrides.json] \
        [--readback readback.json] [--dropped dropped.json] [--reconcile reconcile.json] \
        [--notes notes.json] [--title "..."] [--board-url URL] --html report.html

--readback   live read of the imported board: JSON list of [tile name, rows, column names, first rows]
             (from metadata/liveboard/data). Without it the page says it is a preview.
--dropped    JSON list of tile names held back before import (tiles lint would ship blank).
--reconcile  JSON list of {kpi, thoughtspot, sisense[, sisense_variant]}: the same KPI read off the board
             and run live in Sisense (JAQL); `sisense` is the comparable run, `sisense_variant` an optional
             second run (e.g. with a filter the board does not carry). Column labels and the intro come
             from notes.reconcile {intro, sisense_label, variant_label}.
--notes      report-specific facts the converter cannot derive (source-dashboard findings with their
             evidence, adaptations, what was not carried, how to check). Never hardcode them here.
Standard library + PyYAML only.
"""
import argparse, collections, datetime, html, json, re
from pathlib import Path

import yaml

E = html.escape
HERE = Path(__file__).resolve().parent
GRAIN = re.compile(r"\s*\((Daily|Weekly|Monthly|Quarterly|Yearly)\)\s*$", re.I)
CONTAINERS = ("richtexteditor", "WidgetsTabber")
MERGED = "Merged into a date control"

# Plain-language labels for the converter's NEEDS REVIEW reasons. First match wins.
REASONS = [
    ("board", "Same warehouse not declared", r"reads connection|reach the same warehouse",
     "The Sisense data model and the ThoughtSpot connection have different names. Declaring them the same warehouse is a one-line decision in the overrides file."),
    ("board", "Join path not provable in Sisense", r"loop|no single fact",
     "Sisense's data model can reach some tables by more than one route, so which joins a widget used cannot be proven. ThoughtSpot always takes one defined path."),
    ("board", "Dashboard filter not carried exactly", r"dashboard filter",
     "A filter-bar setting the converter does not read, or a filter whose path to a tile could not be proven."),
    ("board", "Outer vs inner joins", r"not INNER|join types",
     "The ThoughtSpot model uses outer joins; a Sisense relation is inner by default. Counts match where every row has a match on the other side."),
    ("board", "Filter value matching to confirm", r"matching against Sisense|filter value matching|text on a number",
     "ThoughtSpot matches filter values regardless of case and keeps empty values under 'not equal'. Sisense's behaviour is not yet verified to be the same."),
    ("tile", "Filter switched off in Sisense", r"disabled widget filter",
     "Sisense carries this filter but it is disabled, so it is left off here too."),
    ("tile", "Date joins a different way", r"which the target model does not|joins .* through",
     "The ThoughtSpot model reaches this date through a different table than Sisense does."),
    ("tile", "Week start or fiscal quarter to confirm", r"buckets weeks|buckets quarters",
     "Weekly and quarterly buckets follow the cluster's calendar settings."),
    ("tile", "Count with no matching measure", r"unique count of", "The widget counts a column the model has no measure for."),
    ("tile", "Contribution % not carried", r"Contribution", "Sisense quick function; rebuilt by hand as a ThoughtSpot formula."),
    ("tile", "Pie 'Others' slice not carried", r"convolution", "Sisense merges small slices into 'Others'; ThoughtSpot shows every slice."),
    ("tile", "Field not on the model", r"not exposed on the target model", "A plotted field has no column on the model."),
    ("tile", "Ambiguous role", r"ambiguous in the target model",
     "The model has more than one copy of this table (two role-playing copies of one dimension), so the converter will not pick one."),
    ("tile", "Filter cannot reach the tile", r"not reachable", "The filter's table is not reachable from the tile's data."),
    ("tile", "Formula matched by name", r"by name only", "A Sisense calculated column bound to a model formula with the same name; confirm it is the same calculation."),
    ("tile", "Tab set not carried", r"no tile to merge into", "The tab set's active chart could not be built, so its other date grains have nothing to attach to."),
    ("tile", MERGED, r"other grain of tab set", "A daily / weekly / monthly tab of the same chart becomes the chart's own date-bucket control."),
]


# ---------------------------------------------------------------- small HTML helpers

def labels(note):
    return [(s, l) for s, l, p, _ in REASONS if re.search(p, note or "", re.I)]


def label_text(note):
    return "; ".join(sorted({l for _, l in labels(note)}))


def stat(label, value, sub="", tone=""):
    cls = f"tone-{tone}" if tone else ""
    return (f'<div class="stat {cls}"><div class="stat-label">{E(label)}</div>'
            f'<div class="stat-value">{value}</div><div class="stat-sub">{E(sub)}</div></div>')


def fold(title, body, count=None):
    c = "" if count is None else f' <span class="count">{count}</span>'
    return f'<details><summary>{E(title)}{c}</summary><div class="detail-body">{body}</div></details>'


def table(head, rows):
    th = "".join(f"<th>{E(h)}</th>" for h in head)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{th}</tr>{trs}</table>"


def pill(kind, text):
    icon = {"good": "✓", "warning": "◐", "serious": "!", "muted": "·"}[kind]
    return f'<span class="pill pill-{kind}"><span>{icon}</span>{E(text)}</span>'


def bar(parts):
    total = sum(n for _, _, n in parts) or 1
    segs = "".join(f'<div class="seg seg-{k}" style="flex:{n} 1 0" tabindex="0" data-tip="{E(l)}: {n} of {total}">'
                   f'<span class="seg-n">{n}</span></div>' for k, l, n in parts if n)
    leg = "".join(f'<li><span class="key key-{k}"></span>{E(l)}<b>{n}</b></li>' for k, l, n in parts)
    return f'<div class="bar">{segs}</div><ul class="legend">{leg}</ul>'


def chips(names, limit=None):
    shown = names if limit is None else names[:limit]
    out = "".join(f'<span class="chip">{E(n)}</span>' for n in shown)
    if limit is not None and len(names) > limit:
        out += f'<span class="chip">+{len(names) - limit} more</span>'
    return out


def fmt(v):
    if isinstance(v, float) and v != int(v):
        return f"{v:,.2f}"
    if isinstance(v, (int, float)):
        return f"{int(v):,}"
    return E(str(v))


# ---------------------------------------------------------------- inputs

def load_json(path, default):
    return json.load(open(path)) if path else default


def load_context(a):
    out = Path(a.out_dir)
    dash = json.load(open(a.bundle))["dashboard"]
    rows = json.loads((out / "migration-report.json").read_text())["visuals"]
    lb = yaml.safe_load(next(out.glob("*.liveboard.tml")).read_text())["liveboard"]
    vizzes = lb.get("visualizations", [])
    tiles = [v for v in vizzes if v.get("answer")]
    readback = load_json(a.readback, None)
    report = {}
    for r in rows:
        report.setdefault(r["visual"], r)
    return {
        "a": a, "dash": dash, "rows": rows, "report": report, "lb": lb, "tiles": tiles,
        "note_tiles": [v for v in vizzes if not v.get("answer")],
        "chips": lb.get("filters", []),
        "by_name": {v["answer"]["name"]: v for v in tiles},
        "readback": readback, "is_live": readback is not None,
        "rb": {x[0]: x for x in readback or []},
        "n_live": sum(1 for x in readback or [] if x[1]),
        "dropped": load_json(a.dropped, []), "recon": load_json(a.reconcile, []),
        "notes": load_json(a.notes, {}), "ov": load_json(a.overrides, {}),
        "title": a.title or dash.get("title", "Sisense dashboard"),
    }


# ---------------------------------------------------------------- widgets

def tile_for(ctx, title):
    return ctx["by_name"].get(title) or ctx["by_name"].get(GRAIN.sub("", title))


def widget_outcome(ctx, w):
    t = w.get("title", "")
    note = ctx["report"].get(t, {}).get("note", "")
    if t in ctx["dropped"]:
        return "serious", "Held back"
    if t in ctx["by_name"]:
        return "good", "Tile"
    if re.search(r"no tile to merge into", note):
        return "serious", "Not carried"
    if re.search(r"other grain of tab set", note):
        return "good", "Date control of its chart"
    if GRAIN.sub("", t) in ctx["by_name"]:
        return "good", "Tile"
    return "serious", "Not carried"


def classify_widgets(ctx):
    data_w = [w for w in ctx["dash"].get("widgets", []) if w.get("type") not in CONTAINERS]
    outcome = [(w, *widget_outcome(ctx, w)) for w in data_w]
    carried = sum(1 for _, k, _ in outcome if k == "good")
    ctx.update(data_w=data_w, outcome=outcome, carried=carried,
               pct=round(100 * carried / max(1, len(data_w))))


# ---------------------------------------------------------------- measures

def widget_values(w):
    out = []
    for p in w.get("metadata", {}).get("panels", []):
        if p.get("name") not in ("values", "value"):
            continue
        for it in p.get("items", []):
            j = it.get("jaql", {})
            expr = j.get("formula") or (f"{j.get('agg', '')}({j.get('dim', '')})" if j.get("dim") else "")
            out.append((j.get("title") or "", expr, bool(j.get("formula"))))
    return out


def ts_measure_names(v, value_title):
    cols = v["answer"].get("answer_columns", [])
    named = {c["name"] for c in cols if (c.get("custom_name") or "") == value_title}
    if named:
        return named
    first = next((c["name"] for c in cols if c.get("format", {}).get("category") == "NUMBER"), "")
    return {first} if first else set()


def collect_measures(ctx):
    meas = collections.OrderedDict()
    fmap = ctx["ov"].get("field_map", {})
    for w, _, _ in ctx["outcome"]:
        v = tile_for(ctx, w.get("title", ""))
        for vt, expr, is_formula in widget_values(w):
            m = meas.setdefault((vt, expr), {"widgets": 0, "formula": is_formula, "ts": set(), "via": False})
            m["widgets"] += 1
            if v:
                m["ts"] |= ts_measure_names(v, vt)
            dim = re.search(r"\((\[.*\])\)", expr)
            m["via"] = m["via"] or bool(dim and dim.group(1) in fmap)
    return meas


def measure_kind(m, ts):
    if m["formula"] and not ts:
        return "serious", "Needs a person"
    if m["via"]:
        return "warning", "Mapped by us (overrides)"
    if ts:
        return "good", "Bound to model measure"
    return "serious", "Not carried"


def measure_table(ctx):
    meas = collect_measures(ctx)
    rows, tally = [], collections.Counter()
    for (vt, expr), m in meas.items():
        ts = ", ".join(sorted(x for x in m["ts"] if x))
        kind, txt = measure_kind(m, ts)
        tally[kind] += 1
        rows.append([E(vt), f"<code>{E(expr)}</code>", E(ts) or "—", pill(kind, txt), str(m["widgets"])])
    ctx.update(meas_rows=rows, m_good=tally["good"], m_warn=tally["warning"],
               m_bad=tally["serious"], n_meas=len(meas))


# ---------------------------------------------------------------- converter findings

def group_findings(rows):
    by_label = collections.OrderedDict((l, {"scope": s, "expl": x, "tiles": []}) for s, l, _, x in REASONS)
    for r in rows:
        for _, l in labels(r.get("note", "")):
            if r["visual"] not in by_label[l]["tiles"]:
                by_label[l]["tiles"].append(r["visual"])
    return by_label


def cards(by_label, scope):
    out = []
    for l, f in by_label.items():
        if f["scope"] != scope or not f["tiles"] or l == MERGED:
            continue
        out.append(f'<div class="finding"><div class="finding-label">{E(l)} <span class="count">{len(f["tiles"])}</span></div>'
                   f'<p>{E(f["expl"])}</p><div class="chips">{chips(f["tiles"], 8)}</div></div>')
    return "".join(out)


# ---------------------------------------------------------------- sections

def section_hero(ctx):
    badge = "Read back off the cluster" if ctx["is_live"] else "Preview, not imported"
    n_data, carried = len(ctx["data_w"]), ctx["carried"]
    n_containers = len(ctx["dash"].get("widgets", [])) - n_data
    return f"""<section class="panel hero"><div><div class="hero-figure">{ctx["pct"]}<small>%</small></div>
<div class="hero-label">of the dashboard's data widgets are live in ThoughtSpot, as a tile or as the date control of one</div>
<div class="badge"><span class="dot"></span>{badge}</div></div>
<div><div class="meter"><div class="meter-fill" style="width:{ctx["pct"]}%"></div></div>
<div class="meter-scale"><span>{carried} carried</span><span>{n_data} data widgets</span></div>
<p class="hero-note">{n_data - carried} were not carried: listed below with the reason. The dashboard's
{n_containers} text and tab containers became {len(ctx["note_tiles"])} section-header notes.</p></div></section>"""


def section_stats(ctx):
    n_t = len(ctx["tiles"])
    if ctx["is_live"]:
        live = stat("Tiles returning data", f"{ctx['n_live']}<span class='of'>/{n_t}</span>",
                    "read back off the cluster", "good" if ctx["n_live"] == n_t else "")
    else:
        live = stat("Tiles", str(n_t), "not imported")
    bound = ctx["m_good"] + ctx["m_warn"]
    return '<div class="stats">' + "".join([
        live,
        stat("Widgets carried", f"{ctx['carried']}<span class='of'>/{len(ctx['data_w'])}</span>", "tiles and date controls"),
        stat("Measures bound", f"{bound}<span class='of'>/{ctx['n_meas']}</span>", f"{ctx['m_bad']} need a person",
             "serious" if ctx["m_bad"] else ""),
        stat("Filters", str(len(ctx["chips"])), "on the liveboard filter bar"),
    ]) + "</div>"


def section_measures(ctx):
    parts = [("good", "Bound to model measure", ctx["m_good"]), ("warning", "Mapped by us (overrides)", ctx["m_warn"]),
             ("serious", "Needs a person", ctx["m_bad"])]
    return f"""<section class="panel"><h2>Measures</h2><p class="section-sub">{ctx["m_good"] + ctx["m_warn"]} of {ctx["n_meas"]}
distinct Sisense values bound to a measure on the governed model. Anything the converter could not translate is named
with the reason, never guessed.</p>{bar(parts)}
<div class="prose"><p>Widget and value titles are reproduced <strong>verbatim from the Sisense dashboard</strong>, including
duplicates, so they can be matched one to one.</p></div></section>"""


def section_shipped(ctx):
    a, lb = ctx["a"], ctx["lb"]
    name = E(lb.get("name", ""))
    link = f'<a href="{E(a.board_url)}">{name}</a>' if a.board_url else name
    state = "live" if ctx["is_live"] else "preview"
    chip_names = [(c.get("column") or ["?"])[0] for c in ctx["chips"]]
    return f"""<section class="panel"><h2>What shipped</h2><div class="grid2">
<div class="card"><div class="card-head"><h3>Liveboard</h3><span class="ok"><span>✓</span> {state}</span></div>
<p>{link}</p><p class="muted small">{len(ctx["tiles"])} tiles, {len(ctx["note_tiles"])} notes, {len(ctx["chips"])} filter chips,
on the model {E(ctx["notes"].get("model_name", ""))}</p></div>
<div class="card"><div class="card-head"><h3>Filter bar</h3><span class="ok"><span>✓</span> {len(ctx["chips"])} chips</span></div>
<div class="chips">{chips(chip_names)}</div></div></div></section>"""


def section_source(ctx):
    sf = ctx["notes"].get("source_findings", [])
    if not sf:
        return ""
    items = "".join(f'<div class="finding"><div class="finding-label">{E(f["label"])}</div><p>{E(f["body"])}</p>'
                    f'<p class="evidence">{E(f.get("evidence", ""))}</p></div>' for f in sf)
    return (f'<section class="panel"><h2>Found in the source dashboard ({len(sf)})</h2><p class="section-sub">Behaviour of the '
            f'Sisense dashboard itself, kept apart from conversion decisions. These are about the source, not ThoughtSpot.</p>'
            f'<div class="findings">{items}</div></section>')


def section_adapted(ctx):
    ad = ctx["notes"].get("adaptations", [])
    if not ad:
        return ""
    return f'<section class="panel"><h2>How the model was adapted</h2><ul>{"".join(f"<li>{E(x)}</li>" for x in ad)}</ul></section>'


def section_decisions(ctx):
    by_label = group_findings(ctx["rows"])
    return (f'<section class="panel"><h2>Decisions that apply across the board</h2><p class="section-sub">From the Sisense '
            f'data model or the target model as a whole, so they touch many tiles at once.</p>'
            f'<div class="findings">{cards(by_label, "board")}</div></section>'
            f'<section class="panel"><h2>Tile-specific decisions</h2><p class="section-sub">Each is a judgement call for a person, '
            f'not a translation error.</p><div class="findings">{cards(by_label, "tile")}</div></section>')


# ---------------------------------------------------------------- folds

def data_cell(ctx, title, outcome):
    if outcome != "Tile":
        return "—"
    got = ctx["rb"].get(title) or ctx["rb"].get(GRAIN.sub("", title))
    return pill("good", f"{got[1]} row(s)") if got else "—"


def fold_widgets(ctx):
    rows = []
    for w, k, o in ctx["outcome"]:
        t = w.get("title", "")
        v = tile_for(ctx, t) if o == "Tile" else None
        chart = v["answer"].get("chart", {}).get("type", "") if v else ""
        rows.append([E(t), E(w.get("type", "")), pill(k, o), E(chart), data_cell(ctx, t, o)])
    return table(["Widget", "Sisense type", "Became", "ThoughtSpot chart", "Data"], rows)


def fold_flagged(ctx):
    flagged = [r for r in ctx["rows"] if r.get("status") == "NEEDS REVIEW"]
    rows = [[E(r["visual"]), E(label_text(r.get("note", "")) or r.get("note", "")[:160]), E(r.get("ts_chart", ""))]
            for r in flagged]
    return table(["Widget / item", "Why", "Chart"], rows), len(flagged)


def target_model_text(path):
    if not path:
        return ""
    tm = json.load(open(path))
    doc = yaml.safe_load(tm[0]["edoc"]) if isinstance(tm[0].get("edoc"), str) else tm[0]
    m = doc.get("model", {})
    return (f"<p>ThoughtSpot model <b>{E(m.get('name', ''))}</b>: {len(m.get('model_tables', []))} table instances "
            f"over {len(tm) - 1} warehouse tables and views, {len(m.get('columns', []))} columns, "
            f"{len(m.get('formulas', []))} formulas.</p>")


def fold_model(ctx):
    widgets = ctx["dash"].get("widgets", [])
    used = sorted({m.group(1) for w in widgets for m in re.finditer(r'"dim":\s*"\[([^.\]]+)\.', json.dumps(w))})
    dm = json.load(open(ctx["a"].bundle)).get("datamodel", {})
    n_tables = sum(len(ds.get("schema", {}).get("tables", [])) for ds in dm.get("datasets", []))
    name = ctx["notes"].get("sisense_model", dm.get("title", ""))
    return (f"<p>Sisense data model <b>{E(name)}</b>: {n_tables} tables, {len(dm.get('relations', []))} relations. "
            f"This dashboard reads {len(used)} of them.</p>{target_model_text(ctx['a'].target_model)}"
            f"<div class='chips'>{chips(used)}</div>")


def fold_source(ctx):
    types = collections.Counter(w.get("type") for w in ctx["dash"].get("widgets", []))
    return (table(["Widget type", "Count"], [[E(t), str(n)] for t, n in types.most_common()])
            + f"<p class='small muted'>{len(ctx['dash'].get('filters', []))} dashboard filters (cascading groups count once).</p>")


def fold_not_carried(ctx):
    nc = ctx["notes"].get("not_carried", [])
    rows = [[E(x["item"]), E(x["why"])] for x in nc]
    rows += [[E(n), "Held back before import: it lost its only measure and would have rendered blank."] for n in ctx["dropped"]]
    return table(["Item", "Why"], rows), len(rows)


def recon_status(ts, s):
    try:
        d = abs(float(ts) - float(s))
        rel = d / max(1e-9, abs(float(s)))
    except (TypeError, ValueError):
        return pill("muted", "n/a")
    return pill("good", "matches") if rel <= 0.01 else pill("warning", f"differs by {d:,.0f}")


def fold_reconcile(ctx):
    recon = ctx["recon"]
    if not recon:
        return ""
    has_variant = any("sisense_variant" in x for x in recon)
    rc = ctx["notes"].get("reconcile", {})
    head = ["KPI", "ThoughtSpot", rc.get("sisense_label", "Sisense")]
    head += [rc.get("variant_label", "Sisense (variant)")] if has_variant else []
    rows = []
    for x in recon:
        row = [E(x["kpi"]), fmt(x.get("thoughtspot")), fmt(x.get("sisense"))]
        row += [fmt(x.get("sisense_variant"))] if has_variant else []
        rows.append(row + [recon_status(x.get("thoughtspot"), x.get("sisense"))])
    intro = rc.get("intro", "Each KPI tile read off the board, next to the same widget run live in Sisense "
                            "with the dashboard filters the board carries.")
    return f"<p>{E(intro)}</p>" + table(head + [""], rows)


def section_folds(ctx):
    flagged, n_flag = fold_flagged(ctx)
    nc, n_nc = fold_not_carried(ctx)
    rec = fold_reconcile(ctx)
    steps = ctx["notes"].get("check_steps", [])
    head = ["Sisense value", "Sisense expression", "ThoughtSpot measure", "Outcome", "Widgets"]
    parts = [
        '<h2 class="fold-head">The detail</h2>',
        fold("Every measure, with its Sisense expression and its ThoughtSpot measure", table(head, ctx["meas_rows"]), ctx["n_meas"]),
        fold("Every widget, and what it became", fold_widgets(ctx), len(ctx["data_w"])),
        fold("Widgets and items the converter flagged", flagged, n_flag),
        fold("The data model", fold_model(ctx)),
        fold("The source dashboard, by the numbers", fold_source(ctx)),
        fold("What was not carried over, and why", nc, n_nc),
    ]
    if rec:
        parts.append(fold("How the numbers reconcile", rec))
    if steps:
        parts.append(fold("How to check it yourself", "<ol>" + "".join(f"<li>{E(s)}</li>" for s in steps) + "</ol>"))
    return "".join(parts)


# ---------------------------------------------------------------- page

def render(ctx):
    lede = ("Coverage is read back off the ThoughtSpot cluster after import, so these figures describe what is deployed, "
            "not what the converter believes it built." if ctx["is_live"] else "Preview: nothing has been imported yet.")
    n_review = sum(1 for r in ctx["rows"] if r.get("status") == "NEEDS REVIEW")
    body = (f'<header><div><p class="eyebrow">Sisense to ThoughtSpot migration report</p><h1>{E(ctx["title"])}</h1>'
            f'<p class="lede">Generated {datetime.date.today():%d %B %Y}. {lede}</p></div>'
            f'<button class="theme-btn" id="theme" type="button">Light / dark</button></header>'
            + section_hero(ctx) + section_stats(ctx) + section_measures(ctx) + section_shipped(ctx)
            + section_source(ctx) + section_adapted(ctx) + section_decisions(ctx) + section_folds(ctx)
            + f"<footer>Source of truth: migration-report.json ({n_review} rows). Generated by the "
              f"ts-convert-from-sisense skill's render_report_html.py.</footer>")
    css = (HERE / "report_assets" / "style.css").read_text()
    js = (HERE / "report_assets" / "theme.js").read_text()
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{E(ctx["title"])}: migration report</title>'
            f'<style>{css}</style></head><body><div class="wrap">{body}</div><script>{js}</script></body></html>')


def parse_args():
    ap = argparse.ArgumentParser()
    for k in ("bundle", "out-dir", "html"):
        ap.add_argument(f"--{k}", required=True)
    for k in ("target-model", "overrides", "readback", "dropped", "reconcile", "notes", "title", "board-url"):
        ap.add_argument(f"--{k}")
    return ap.parse_args()


def main():
    ctx = load_context(parse_args())
    classify_widgets(ctx)
    measure_table(ctx)
    Path(ctx["a"].html).write_text(render(ctx), encoding="utf-8")
    print(json.dumps({"html": ctx["a"].html, "coverage_pct": ctx["pct"], "carried": ctx["carried"],
                      "data_widgets": len(ctx["data_w"]), "tiles": len(ctx["tiles"]),
                      "live": ctx["n_live"] if ctx["is_live"] else None, "measures": ctx["n_meas"],
                      "measures_need_person": ctx["m_bad"],
                      "source_findings": len(ctx["notes"].get("source_findings", []))}))


if __name__ == "__main__":
    main()
