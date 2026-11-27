#!/usr/bin/env python3
"""Render a Sisense -> ThoughtSpot `--target-model` run as one self-contained HTML page.

migration-report.json is the source of truth and this page never claims more than it does:
each widget's outcome is its row's status, NEEDS REVIEW is counted on its own and never shown
as done, and every converter note is printed in full (labels only group them). Run it with the
Python that has ts-cli installed: the bundle is read through the converter's own parser.

    python3 render_report_html.py --bundle bundle.json --out-dir out/ \
        [--target-model target-model.json] [--overrides overrides.json] \
        [--readback readback.json] [--dropped dropped.json] [--reconcile reconcile.json] \
        [--notes notes.json] [--title "..."] [--board-url URL] --html report.html

--readback   tiles read back off the imported board: JSON list of [tile name, rows, ...]
             (metadata/liveboard/data). Each entry is matched to a tile by name; a tile counts as
             returning data only when its row count is a number above 0. Without --readback the
             page is a preview and says so everywhere.
--dropped    JSON list of tile names the user left out of the import; shown as not imported.
--reconcile  JSON list of {kpi, thoughtspot, sisense[, sisense_variant]}: a KPI read off the board
             next to the same widget run in Sisense. Labels and intro come from
             notes.reconcile {intro, sisense_label, variant_label}.
--notes      report-specific facts the converter cannot derive (source-dashboard findings,
             adaptations, what was not carried, how to check). Never hardcode them here.
"""
import argparse, collections, datetime, html, json, math, re, sys
from pathlib import Path

import yaml

E = html.escape
HERE = Path(__file__).resolve().parent
CONTAINERS = ("richtexteditor", "WidgetsTabber")
DONE = ("Migrated", "Approximated", "Merged")
FIELD_REFS = re.compile(r"\[[^\]]*\]|'[^']*'|\"[^\"]*\"|`[^`]*`")

# Labels group the converter's notes; they never replace them. Patterns match the converter's
# own phrasing after field names, quoted values and bracketed refs are stripped from the note.
REASONS = [
    ("board", "Same warehouse not declared", r"reads connection|reach the same warehouse"),
    ("board", "Join path not provable in Sisense", r"relate to each other in a loop|no single fact Sisense relates"),
    ("board", "Dashboard filter not carried exactly", r"\bdashboard filter\b"),
    ("board", "Outer vs inner joins", r"join not INNER|of the Model's \d+ joins are"),
    ("board", "Filter value matching to confirm", r"whose matching against Sisense's is not verified|matches filter values without regard to case"),
    ("tile", "Filter switched off in Sisense", r"disabled widget filter"),
    ("tile", "Date joins a different way", r"which the target model does not join|the target model joins .* through"),
    ("tile", "Week start or fiscal quarter to confirm", r"buckets weeks|buckets quarters"),
    ("tile", "Count with no matching measure", r"add a Model measure"),
    ("tile", "Quick function not carried", r"applies the Sisense quick function"),
    ("tile", "Field not on the model", r"is not exposed on the target model"),
    ("tile", "Ambiguous role", r"is ambiguous in the target model"),
    ("tile", "Filter cannot reach the tile", r"is not reachable from the widget's facts"),
    ("tile", "Formula matched by name", r"bound to Model formula .* by name only"),
    ("tile", "Tab set not carried", r"no tile to merge into"),
]


class ReportError(Exception):
    """An input the page cannot be built from; reported as one line, never a traceback."""


# ---------------------------------------------------------------- small HTML helpers

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
    out = "".join(f'<span class="chip">{E(str(n))}</span>' for n in shown)
    if limit is not None and len(names) > limit:
        out += f'<span class="chip">+{len(names) - limit} more</span>'
    return out


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def fmt(v):
    if not is_number(v):
        return "n/a"
    return f"{v:,.2f}" if v != int(v) else f"{int(v):,}"


# ---------------------------------------------------------------- inputs

def read_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReportError(f"cannot read {what} {path}: {exc}") from exc
    except ValueError as exc:
        raise ReportError(f"{what} {path} is not JSON: {exc}") from exc


def optional_json(path, what, default):
    return read_json(path, what) if path else default


def readback_list(path):
    data = optional_json(path, "--readback", None)
    if data is not None and not isinstance(data, list):
        raise ReportError(f"--readback {path} must be a JSON list of [tile name, rows, ...] entries")
    return data


def load_bundle(path):
    """The bundle through the converter's own reader: a bare .dash export is the dashboard itself,
    and widgets come from the top level and the dashboard alike, in the order the converter reads them."""
    from ts_cli.sisense.parsing import _all_widgets, _unwrap
    raw = read_json(path, "--bundle")
    if not isinstance(raw, dict):
        raise ReportError(f"--bundle {path} is not a Sisense bundle object")
    bundle = _unwrap(raw)
    dash = bundle.get("dashboard") if isinstance(bundle.get("dashboard"), dict) else {}
    widgets = [w for w in _all_widgets(bundle, dash) if isinstance(w, dict)]
    return bundle, dash, widgets


def load_liveboard(out):
    files = sorted(out.glob("*.liveboard.tml"))
    if not files:
        return {}                    # nothing carried: the report still renders
    try:
        return yaml.safe_load(files[0].read_text(encoding="utf-8")).get("liveboard") or {}
    except (OSError, yaml.YAMLError, AttributeError) as exc:
        raise ReportError(f"cannot read {files[0]}: {exc}") from exc


def load_target_model(path):
    """(Model TML, Table TMLs) through the converter's own --target-model reader."""
    if not path:
        return None, []
    from ts_cli.commands.sisense import _load_tml
    try:
        return _load_tml(path)
    except SystemExit as exc:
        raise ReportError(f"--target-model {path} is not a Model TML export") from exc


def load_context(a):
    out = Path(a.out_dir)
    bundle, dash, widgets = load_bundle(a.bundle)
    report = read_json(out / "migration-report.json", "migration report")
    rows = report.get("visuals") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        raise ReportError(f"{out / 'migration-report.json'} has no 'visuals' list")
    lb = load_liveboard(out)
    return {"a": a, "bundle": bundle, "dash": dash, "widgets": widgets, "rows": rows, "lb": lb,
            "model": load_target_model(a.target_model),
            "readback": readback_list(a.readback),
            "dropped": [str(n) for n in optional_json(a.dropped, "--dropped", [])],
            "recon": optional_json(a.reconcile, "--reconcile", []),
            "notes": optional_json(a.notes, "--notes", {}),
            "ov": optional_json(a.overrides, "--overrides", {}),
            "title": a.title or dash.get("title") or "Sisense dashboard"}


# ---------------------------------------------------------------- tiles and readback

def board_tiles(ctx):
    """Answer tiles on the emitted board, by name; a name two tiles share is ambiguous."""
    vizzes = ctx["lb"].get("visualizations") or []
    tiles = [v for v in vizzes if isinstance(v, dict) and v.get("answer")]
    counts = collections.Counter(v["answer"].get("name") for v in tiles)
    ctx.update(tiles=tiles, note_tiles=[v for v in vizzes if isinstance(v, dict) and not v.get("answer")],
               tile_names=counts, chips_on_board=ctx["lb"].get("filters") or [])


def readback_rows(ctx):
    """Tile name -> rows returned, for entries that match exactly one tile on the board. Entries
    that match no tile, or a name two tiles share, are ignored; repeats of a tile count once."""
    got = {}
    for entry in ctx["readback"] or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        name, n = entry[0], entry[1]
        if ctx["tile_names"].get(name) == 1 and name not in got and name not in ctx["dropped"]:
            got[name] = n if is_number(n) else 0
    return got


def apply_readback(ctx):
    ctx["is_live"] = ctx["readback"] is not None
    rb = readback_rows(ctx) if ctx["is_live"] else {}
    ctx["rb"] = rb
    ctx["n_live"] = sum(1 for n in rb.values() if n > 0)
    ctx["n_board"] = sum(1 for name, c in ctx["tile_names"].items() if c == 1 and name not in ctx["dropped"])


# ---------------------------------------------------------------- widgets -> report rows

def classify_widgets(ctx):
    """Each data widget's row is the converter's own, in the order it reads them: one row per
    widget that is not a text or tab container, before any board-level row."""
    data_w = [w for w in ctx["widgets"] if w.get("type") not in CONTAINERS]
    rows = ctx["rows"]
    if len(rows) < len(data_w):
        raise ReportError("migration-report.json has fewer rows than the bundle has data widgets; "
                          "was it produced from this bundle?")
    pairs = list(zip(data_w, rows[:len(data_w)]))
    bad = [w.get("title") for w, r in pairs if not same_widget(w, r)]
    if bad:
        raise ReportError(f"migration-report.json rows do not line up with the bundle's widgets "
                          f"(first mismatch: {bad[0]!r}); was it produced from this bundle?")
    tally = collections.Counter(r.get("status") or "?" for _, r in pairs)
    ctx.update(data_w=data_w, pairs=pairs, other_rows=rows[len(data_w):], tally=tally,
               n_done=sum(tally[s] for s in DONE), n_review=tally["NEEDS REVIEW"])


def same_widget(w, row):
    """The converter titles a row by the widget's title, a kept tab without its grain suffix, or 'Visual'."""
    from ts_cli.sisense.target_tabs import _GRAIN_SUFFIX
    title = w.get("title") or ""
    visual = row.get("visual")
    return visual in (title, _GRAIN_SUFFIX.sub("", title)) or (not title and visual in ("Visual", None))


def outcome_pill(row):
    status = row.get("status") or "?"
    if status == "NEEDS REVIEW":
        return pill("warning", "Needs review")
    if status in ("Migrated", "Approximated"):
        return pill("good", status)
    if status == "Merged":
        return pill("good", "Merged into its chart's date control")
    return pill("serious", status)


def tile_state(ctx, row):
    name = row.get("visual")
    n = ctx["tile_names"].get(name, 0)
    if row.get("status") == "Merged":
        return "—"
    if n > 1:
        return pill("warning", "title shared by several tiles")
    if n == 0:
        return pill("serious", "no tile")
    if name in ctx["dropped"]:
        return pill("serious", "left out of the import")
    return data_cell(ctx, name)


def data_cell(ctx, name):
    if not ctx["is_live"]:
        return pill("muted", "preview")
    if name not in ctx["rb"]:
        return pill("serious", "not read back")
    n = ctx["rb"][name]
    return pill("good", f"{n:,} row(s)") if n > 0 else pill("serious", "no rows")


# ---------------------------------------------------------------- measures

def widget_values(w):
    out = []
    for p in (w.get("metadata") or {}).get("panels") or []:
        if p.get("name") not in ("values", "value"):
            continue
        for it in p.get("items") or []:
            j = it.get("jaql") or {}
            expr = j.get("formula") or (f"{j.get('agg', '')}({j.get('dim', '')})" if j.get("dim") else "")
            out.append((j.get("title") or "", expr, j.get("dim") or ""))
    return out


def tile_for_row(ctx, row):
    name = row.get("visual")
    if ctx["tile_names"].get(name) != 1:
        return None
    return next(v for v in ctx["tiles"] if v["answer"].get("name") == name)


def bound_column(tile, value_title):
    """The tile column carrying this value: by its display title only, never a guess."""
    for c in tile["answer"].get("answer_columns") or []:
        if value_title and value_title in (c.get("custom_name"), c.get("name")):
            return c.get("name") or ""
    return ""


def measure_outcome(ctx, row, tile, title, dim):
    if row.get("status") == "Merged":
        return "", "muted", "Merged with its chart"
    if tile is None:
        return "", "serious", "Not carried"
    col = bound_column(tile, title)
    if not col:
        return "", "serious", "Needs a person"
    if dim and dim in (ctx["ov"].get("field_map") or {}):
        return col, "warning", "Mapped by an override"
    return col, "good", "Bound to a model column"


def measure_table(ctx):
    rows, tally = [], collections.Counter()
    for w, row in ctx["pairs"]:
        tile = tile_for_row(ctx, row)
        for title, expr, dim in widget_values(w):
            col, kind, txt = measure_outcome(ctx, row, tile, title, dim)
            tally[kind] += 1
            rows.append([E(w.get("title") or "(untitled)"), E(title), f"<code>{E(expr)}</code>", E(col) or "—", pill(kind, txt)])
    ctx.update(meas_rows=rows, m_tally=tally)


# ---------------------------------------------------------------- converter notes

def labels(note):
    text = FIELD_REFS.sub("", note or "")
    return [(s, l) for s, l, p in REASONS if re.search(p, text)]


def group_findings(rows):
    groups = collections.OrderedDict((l, {"scope": s, "items": []}) for s, l, _ in REASONS)
    groups["Other reasons (see each row's note)"] = {"scope": "tile", "items": []}
    for r in rows:
        if r.get("status") != "NEEDS REVIEW":
            continue
        hits = labels(r.get("note")) or [("tile", "Other reasons (see each row's note)")]
        for _, l in hits:
            if r.get("visual") not in groups[l]["items"]:
                groups[l]["items"].append(r.get("visual"))
    return groups


def cards(groups, scope):
    out = []
    for l, g in groups.items():
        if g["scope"] != scope or not g["items"]:
            continue
        out.append(f'<div class="finding"><div class="finding-label">{E(l)} <span class="count">{len(g["items"])}</span></div>'
                   f'<div class="chips">{chips(g["items"], 8)}</div></div>')
    return "".join(out) or '<p class="muted small">None.</p>'


# ---------------------------------------------------------------- sections

def section_hero(ctx):
    n, done, review = len(ctx["data_w"]), ctx["n_done"], ctx["n_review"]
    pct = round(100 * done / n) if n else 0
    badge = "Tiles read back off the cluster" if ctx["is_live"] else "Preview: nothing imported or read back"
    other = n - done - review
    return f"""<section class="panel hero"><div><div class="hero-figure">{done}<small>/{n}</small></div>
<div class="hero-label">data widgets the converter marked Migrated, Approximated or Merged</div>
<div class="badge"><span class="dot"></span>{E(badge)}</div></div>
<div><div class="meter"><div class="meter-fill" style="width:{pct}%"></div></div>
<div class="meter-scale"><span>{done} done</span><span>{review} need review</span><span>{other} other</span></div>
<p class="hero-note">A widget marked NEEDS REVIEW may still have a tile on the board; it is counted
as needing review, not as carried, until a person decides. Every row's full reason is in the detail below.</p></div></section>"""


def section_stats(ctx):
    if ctx["is_live"]:
        live = stat("Tiles returning rows", f"{ctx['n_live']}<span class='of'>/{ctx['n_board']}</span>",
                    "read back off the cluster", "good" if ctx["n_board"] and ctx["n_live"] == ctx["n_board"] else "")
    else:
        live = stat("Tiles on the board", str(len(ctx["tiles"])), "preview: not read back")
    t = ctx["m_tally"]
    return '<div class="stats">' + "".join([
        stat("Needs review", str(ctx["n_review"]), "data widgets the converter flagged", "serious" if ctx["n_review"] else ""),
        stat("Migrated", str(ctx["n_done"]), "Migrated, Approximated or Merged"),
        live,
        stat("Values bound", f"{t['good'] + t['warning']}<span class='of'>/{sum(t.values())}</span>",
             f"{t['serious']} need a person", "serious" if t["serious"] else ""),
    ]) + "</div>"


def section_shipped(ctx):
    a, lb = ctx["a"], ctx["lb"]
    name = E(lb.get("name") or "(no Liveboard: nothing was carried)")
    url = a.board_url or ""
    link = f'<a href="{E(url)}">{name}</a>' if url.startswith(("https://", "http://")) else name
    state = "read back" if ctx["is_live"] else "preview"
    chip_names = [(c.get("column") or ["?"])[0] for c in ctx["chips_on_board"]]
    return f"""<section class="panel"><h2>What the converter emitted</h2><div class="grid2">
<div class="card"><div class="card-head"><h3>Liveboard</h3><span class="ok">{E(state)}</span></div>
<p>{link}</p><p class="muted small">{len(ctx["tiles"])} tiles, {len(ctx["note_tiles"])} notes, {len(ctx["chips_on_board"])} filter chips</p></div>
<div class="card"><div class="card-head"><h3>Filter bar</h3><span class="ok">{len(chip_names)} chips</span></div>
<div class="chips">{chips(chip_names)}</div></div></div></section>"""


def section_notes_list(ctx, key, title, sub):
    items = ctx["notes"].get(key) or []
    if not items:
        return ""
    if key == "source_findings":
        body = "".join(f'<div class="finding"><div class="finding-label">{E(str(f.get("label", "")))}</div>'
                       f'<p>{E(str(f.get("body", "")))}</p><p class="evidence">{E(str(f.get("evidence", "")))}</p></div>'
                       for f in items if isinstance(f, dict))
        return f'<section class="panel"><h2>{E(title)} ({len(items)})</h2><p class="section-sub">{E(sub)}</p><div class="findings">{body}</div></section>'
    return f'<section class="panel"><h2>{E(title)}</h2><ul>{"".join(f"<li>{E(str(x))}</li>" for x in items)}</ul></section>'


def section_decisions(ctx):
    groups = group_findings(ctx["rows"])
    return (f'<section class="panel"><h2>What needs review, across the board</h2><p class="section-sub">Grouped from the '
            f'converter\'s notes; each row\'s full note is in the detail below.</p><div class="findings">{cards(groups, "board")}</div></section>'
            f'<section class="panel"><h2>What needs review, tile by tile</h2><div class="findings">{cards(groups, "tile")}</div></section>')


# ---------------------------------------------------------------- folds

def fold_widgets(ctx):
    rows = []
    for w, row in ctx["pairs"]:
        rows.append([E(w.get("title") or "(untitled)"), E(w.get("type") or ""), outcome_pill(row),
                     E(row.get("ts_chart") or ""), tile_state(ctx, row), E(row.get("note") or "")])
    return table(["Widget", "Sisense type", "Converter status", "ThoughtSpot chart", "Tile", "Converter note"], rows)


def fold_board_rows(ctx):
    rows = [[E(str(r.get("visual") or "")), E(r.get("status") or ""), E(r.get("note") or "")] for r in ctx["other_rows"]]
    return table(["Item", "Status", "Converter note"], rows), len(rows)


def sisense_model_text(ctx, n_used):
    dm = ctx["bundle"].get("datamodel")
    dm = dm if isinstance(dm, dict) else {}
    datasets = [ds for ds in dm.get("datasets") or [] if isinstance(ds, dict)]
    n_tables = sum(len((ds.get("schema") or {}).get("tables") or []) for ds in datasets)
    name = ctx["notes"].get("sisense_model") or dm.get("title") or ""
    return (f"<p>Sisense data model <b>{E(str(name))}</b>: {n_tables} tables, "
            f"{len(dm.get('relations') or [])} relations. This dashboard reads {n_used} of them.</p>")


def target_model_text(ctx):
    model, tables = ctx["model"]
    if not model:
        return ""
    m = model.get("model") or model.get("worksheet") or {}
    return (f"<p>ThoughtSpot model <b>{E(str(m.get('name') or ''))}</b>: {len(m.get('model_tables') or [])} table "
            f"instances over {len(tables)} Tables and views, {len(m.get('columns') or [])} columns, "
            f"{len(m.get('formulas') or [])} formulas.</p>")


def fold_model(ctx):
    used = sorted({m.group(1) for w in ctx["widgets"] for m in re.finditer(r'"dim":\s*"\[([^.\]]+)\.', json.dumps(w))})
    return sisense_model_text(ctx, len(used)) + target_model_text(ctx) + f"<div class='chips'>{chips(used)}</div>"


def fold_source(ctx):
    types = collections.Counter(w.get("type") or "?" for w in ctx["widgets"])
    return (table(["Widget type", "Count"], [[E(t), str(n)] for t, n in types.most_common()])
            + f"<p class='small muted'>{len(ctx['dash'].get('filters') or [])} dashboard filters (cascading groups count once).</p>")


def fold_not_carried(ctx):
    rows = [[E(str(x.get("item", ""))), E(str(x.get("why", "")))] for x in ctx["notes"].get("not_carried") or [] if isinstance(x, dict)]
    rows += [[E(n), "Left out of the import by the user (--dropped)."] for n in ctx["dropped"]]
    return table(["Item", "Why"], rows), len(rows)


def recon_status(ts, s):
    if not (is_number(ts) and is_number(s)):
        return pill("muted", "n/a")
    return pill("good", "matches") if ts == s else pill("warning", f"differs by {abs(ts - s):,.2f}")


def fold_reconcile(ctx):
    recon = [x for x in ctx["recon"] if isinstance(x, dict)]
    if not recon:
        return ""
    has_variant = any("sisense_variant" in x for x in recon)
    rc = ctx["notes"].get("reconcile") or {}
    head = ["KPI", "ThoughtSpot", rc.get("sisense_label", "Sisense")] + ([rc.get("variant_label", "Sisense (variant)")] if has_variant else [])
    rows = []
    for x in recon:
        row = [E(str(x.get("kpi", ""))), fmt(x.get("thoughtspot")), fmt(x.get("sisense"))]
        row += [fmt(x.get("sisense_variant"))] if has_variant else []
        rows.append(row + [recon_status(x.get("thoughtspot"), x.get("sisense"))])
    intro = rc.get("intro", "Each KPI tile read off the board, next to the same widget run in Sisense. Values must match exactly.")
    return f"<p>{E(str(intro))}</p>" + table(head + [""], rows)


def section_folds(ctx):
    board, n_board = fold_board_rows(ctx)
    nc, n_nc = fold_not_carried(ctx)
    rec = fold_reconcile(ctx)
    steps = ctx["notes"].get("check_steps") or []
    parts = ['<h2 class="fold-head">The detail</h2>',
             fold("Every data widget, its status and the converter's full note", fold_widgets(ctx), len(ctx["data_w"])),
             fold("Board-level rows (filter chips, settings, warnings)", board, n_board),
             fold("Every value, and the model column it is bound to", table(
                 ["Widget", "Sisense value", "Sisense expression", "ThoughtSpot column", "Outcome"], ctx["meas_rows"]), len(ctx["meas_rows"])),
             fold("The data model", fold_model(ctx)),
             fold("The source dashboard, by the numbers", fold_source(ctx)),
             fold("What was not carried over, and why", nc, n_nc)]
    if rec:
        parts.append(fold("How the numbers reconcile", rec))
    if steps:
        parts.append(fold("How to check it yourself", "<ol>" + "".join(f"<li>{E(str(s))}</li>" for s in steps) + "</ol>"))
    return "".join(parts)


# ---------------------------------------------------------------- page

def render(ctx):
    lede = ("Statuses come from the converter's migration-report.json; tile data was read back off the cluster after import."
            if ctx["is_live"] else "Preview: statuses come from the converter's migration-report.json; nothing has been imported or read back.")
    t = ctx["m_tally"]
    measures = (f'<section class="panel"><h2>Values</h2><p class="section-sub">A value counts as bound only when the tile '
                f'carries a column with its title; anything else needs a person.</p>'
                f'{bar([("good", "Bound", t["good"]), ("warning", "Mapped by an override", t["warning"]), ("serious", "Needs a person or not carried", t["serious"])])}</section>')
    body = (f'<header><div><p class="eyebrow">Sisense to ThoughtSpot migration report</p><h1>{E(str(ctx["title"]))}</h1>'
            f'<p class="lede">Generated {datetime.date.today():%d %B %Y}. {lede}</p></div>'
            f'<button class="theme-btn" id="theme" type="button">Light / dark</button></header>'
            + section_hero(ctx) + section_stats(ctx) + measures + section_shipped(ctx)
            + section_notes_list(ctx, "source_findings", "Found in the source dashboard",
                                 "Behaviour of the Sisense dashboard itself, kept apart from conversion decisions.")
            + section_notes_list(ctx, "adaptations", "How the model was adapted", "")
            + section_decisions(ctx) + section_folds(ctx)
            + f"<footer>Source of truth: migration-report.json ({len(ctx['rows'])} rows, {ctx['n_review']} data widgets "
              f"need review). Generated by the ts-convert-from-sisense skill's render_report_html.py.</footer>")
    css = (HERE / "report_assets" / "style.css").read_text(encoding="utf-8")
    js = (HERE / "report_assets" / "theme.js").read_text(encoding="utf-8")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{E(str(ctx["title"]))}: migration report</title>'
            f'<style>{css}</style></head><body><div class="wrap">{body}</div><script>{js}</script></body></html>')


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    for k in ("bundle", "out-dir", "html"):
        ap.add_argument(f"--{k}", required=True)
    for k in ("target-model", "overrides", "readback", "dropped", "reconcile", "notes", "title", "board-url"):
        ap.add_argument(f"--{k}")
    return ap.parse_args(argv)


def build(argv=None):
    ctx = load_context(parse_args(argv))
    board_tiles(ctx)
    apply_readback(ctx)
    classify_widgets(ctx)
    measure_table(ctx)
    Path(ctx["a"].html).write_text(render(ctx), encoding="utf-8")
    return {"html": ctx["a"].html, "data_widgets": len(ctx["data_w"]), "migrated": ctx["n_done"],
            "needs_review": ctx["n_review"], "tiles": len(ctx["tiles"]), "preview": not ctx["is_live"],
            "tiles_returning_rows": ctx["n_live"] if ctx["is_live"] else None}


def main(argv=None):
    try:
        print(json.dumps(build(argv)))
    except ImportError as exc:
        print(f"render_report_html: run with the Python that has ts-cli installed ({exc})", file=sys.stderr)
        return 2
    except ReportError as exc:
        print(f"render_report_html: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
