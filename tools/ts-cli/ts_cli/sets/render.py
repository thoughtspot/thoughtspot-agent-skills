"""Inventory -> self-contained HTML + Markdown. No external assets; every name escaped.

Read-only rendering of a `ts-sets-inventory/1` document. Orgs, Models and Sets are
rendered in the order the document gives them (the inventory already sorts Sets); the
renderer never re-sorts. An INCOMPLETE Model is shown as "unknown", never as zero Sets.
"""
from __future__ import annotations

import re
from html import escape
from typing import Iterator, List, Optional, Tuple

CLASS_ORDER = ["KEEP_FILTER", "REVIEW_MANUAL", "KEEP_SHARED", "CANDIDATE_ANSWER",
               "CANDIDATE_VIZ", "REVIEW_DELETE"]
NEXT = {"KEEP_FILTER": "Keep reusable (Liveboard filter)",
        "REVIEW_MANUAL": "Inspect by hand",
        "KEEP_SHARED": "Keep reusable",
        "CANDIDATE_ANSWER": "v2: move into the Answer",
        "CANDIDATE_VIZ": "v2: move into the visualization",
        "REVIEW_DELETE": "Review for deletion (check ad-hoc use)"}
UNKNOWN_LABEL = "Unknown grants (could not determine)"
ANCHOR_LABEL = "Anchor (column id)"


def _s(v) -> str:
    """A rendered value as text: JSON null becomes blank, never the string "None"."""
    return "" if v is None else str(v)


def e(v) -> str:
    """HTML-escape any value, null-safe."""
    return escape(_s(v))


# ---------------------------------------------------------------- links

# Only objects ThoughtSpot has a page for. A Set is a hidden column on its Model — no page.
_ROUTES = {"MODEL": "/#/data/tables/", "ANSWER": "/#/saved-answer/", "LIVEBOARD": "/#/pinboard/"}
_GUID = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def object_url(base_url, kind: str, guid) -> Optional[str]:
    """Deep link to a Model, Answer or Liveboard, or None when one cannot be built safely:
    no or non-http(s) base, a kind with no page, or a value that is not a GUID."""
    base = _s(base_url).rstrip("/")
    if not base.startswith(("https://", "http://")) or kind not in _ROUTES:
        return None
    if not _GUID.match(_s(guid)):
        return None
    return f"{base}{_ROUTES[kind]}{guid}"


def _h_link(base_url, kind: str, guid, label) -> str:
    url = object_url(base_url, kind, guid)
    if not url:
        return e(label)
    return f'<a href="{e(url)}" target="_blank" rel="noopener">{e(label)}</a>'


def _md_link(base_url, kind: str, guid, label) -> str:
    url = object_url(base_url, kind, guid)
    return f"[{_md(label)}]({url})" if url else _md(label)


def _dep_names(x: dict) -> dict:
    return {d["guid"]: d.get("name") or d["guid"] for d in x.get("dependents") or []}


def _models(inv: dict) -> Iterator[Tuple[dict, dict]]:
    for o in inv["orgs"]:
        for m in o["models"]:
            yield o, m


def _sets(inv: dict) -> Iterator[Tuple[dict, dict, dict]]:
    for o, m in _models(inv):
        for s in m["sets"]:
            yield o, m, s


def review_lists(inv: dict) -> dict:
    """REVIEW_DELETE Sets and UNEXPLAINED grants. Only UNEXPLAINED qualifies: a REQUIRED,
    EXPLAINED, DIRECT or UNKNOWN grant never lands on the grant review list."""
    delete, grants = [], []
    for o, m, s in _sets(inv):
        if s["class"] == "REVIEW_DELETE":
            delete.append({"org": o["org"], "model": m["name"], "set": s["name"],
                           "guid": s["guid"]})
        for g in s["grants"]:
            if g["provenance"] == "UNEXPLAINED":
                grants.append({"org": o["org"], "model": m["name"], "set": s["name"],
                               "principal_name": g["principal_name"],
                               "principal_type": g["principal_type"]})
    return {"delete": delete, "grants": grants}


def unknown_grant_count(inv: dict) -> int:
    """`summary.unknown_grants` when present; older documents lack it, so count."""
    n = inv["summary"].get("unknown_grants")
    if n is not None:
        return n
    return sum(1 for _, _, s in _sets(inv) for g in s["grants"] if g["provenance"] == "UNKNOWN")


def _notes(inv: dict) -> List[dict]:
    """Top-level notes (e.g. `org_skipped`) first, then every Org's notes."""
    return list(inv.get("notes") or []) + [n for o in inv["orgs"] for n in o.get("notes") or []]


def _count(m: dict) -> str:
    if m["discovery"] == "INCOMPLETE" or m.get("set_count") is None:
        return "unknown (discovery INCOMPLETE)"
    return str(m["set_count"])


def _malformed_org_skips(inv: dict) -> int:
    """Top-level `org_skipped` notes for an Org row that was MALFORMED (missing `orgId` or
    `status`). Skipping a non-ACTIVE Org is a scope choice; skipping a row we could not read
    means an Org may hold Sets we never counted. A note without `reason` (written before it
    existed) cannot prove it was a scope choice, so it counts as malformed (spec §7)."""
    return sum(1 for n in inv.get("notes") or []
               if n.get("kind") == "org_skipped" and n.get("reason") != "inactive")


def _floor_note(inv: dict) -> str:
    """Non-empty when an INCOMPLETE Model or an unreadable Org row means the totals undercount."""
    n = inv["summary"].get("models_incomplete") or 0
    k = _malformed_org_skips(inv)
    parts = ([f"{n} Model(s) incomplete"] if n else []) + \
        ([f"{k} Org row(s) unreadable and not scanned"] if k else [])
    return f"({'; '.join(parts)} — totals are a floor)" if parts else ""


def _summary_values(inv: dict) -> List[str]:
    s = inv["summary"]
    sets = f"≥{s['sets']}" if _floor_note(inv) else str(s["sets"])
    return [_s(s["models"]), _s(s["models_incomplete"]), sets,
            _s(s["unexplained_grants"]), _s(unknown_grant_count(inv))]


def _dep_count(x: dict) -> str:
    """Never present a possibly-short dependents list as a total. A record without the
    flag (written before it existed) is read as INCOMPLETE — absence proves nothing (§7)."""
    n = len(x["dependents"])
    if x.get("dependents_complete", False):
        return str(n)
    return f"≥{n} (incomplete)" if n else "unknown (lookup incomplete)"


SUMMARY_HEADERS = ["Models", "Incomplete", "Sets", "Unexplained grants", UNKNOWN_LABEL]
SET_HEADERS = ["Set", "Type", ANCHOR_LABEL, "Author", "Dependents", "Class", "Reason", "Next"]


def _set_cells(x: dict) -> List[str]:
    return [_s(x.get("name")), _s(x.get("cohort_type")), _s(x.get("anchor_column")),
            _s(x.get("author")), _dep_count(x), _s(x["class"]), _s(x.get("reason")),
            NEXT.get(x["class"], "")]


# ---------------------------------------------------------------- Markdown

def _md(text) -> str:
    """Make a value safe inside Markdown text or a table cell: no raw HTML, no code spans,
    no column breaks."""
    return (_s(text).replace("<", "&lt;").replace(">", "&gt;").replace("`", "\\`")
            .replace("|", "\\|").replace("\n", " "))


def _md_code(text) -> str:
    """A value for inside a `code span` — a backtick there cannot be escaped, so drop it."""
    return _s(text).replace("`", "").replace("\n", " ")


def _md_row(cells: List[str]) -> str:
    return "| " + " | ".join(_md(c) for c in cells) + " |"


def _md_table(headers: List[str], rows: List[List[str]]) -> List[str]:
    return [_md_row(headers), "|" + "---|" * len(headers)] + [_md_row(r) for r in rows]


def _md_models(inv: dict) -> List[str]:
    out: List[str] = []
    for o, m in _models(inv):
        base = inv.get("base_url")
        title = _md_link(base, "MODEL", m.get("guid"), m["name"])
        out += ["", f"## {_md(o['org'])} / {title} — {_count(m)} Set(s)", ""]
        if m["sets"]:
            out += _md_table(SET_HEADERS, [_set_cells(x) for x in m["sets"]])
            out += _md_dependents(base, m["sets"])
    return out


def _md_dependents(base, sets: List[dict]) -> List[str]:
    """Each used Set's dependents, linked. Sets with none are already in the table."""
    lines: List[str] = []
    for x in sets:
        deps = [_md_link(base, d.get("type"), d.get("guid"), d.get("name") or d.get("guid"))
                + f" ({_md(d.get('type'))})" for d in x.get("dependents") or []]
        if deps:
            lines.append(f"- **{_md(x.get('name'))}** → " + ", ".join(deps))
    return ["", "Dependents:", ""] + lines if lines else []


def _md_review(inv: dict) -> List[str]:
    rl = review_lists(inv)
    out = ["", "## Review — delete candidates", ""]
    out += [f"- {_md(d['org'])} / {_md(d['model'])} / {_md(d['set'])} (`{_md_code(d['guid'])}`)"
            for d in rl["delete"]] or ["- none"]
    out += ["", "## Review — unexplained grants", ""]
    out += [f"- {_md(g['org'])} / {_md(g['model'])} / {_md(g['set'])}: "
            f"{_md(g['principal_name'])} ({_md(g['principal_type'])})"
            for g in rl["grants"]] or ["- none"]
    return out


def render_markdown(inv: dict) -> str:
    by_class = inv["summary"]["by_class"]
    out: List[str] = ["# Reusable Set inventory", "",
                      f"Generated {_md(inv.get('generated_at'))} · profile "
                      f"`{_md_code(inv.get('profile'))}` · read-only report", ""]
    out += _md_table(SUMMARY_HEADERS, [_summary_values(inv)])
    if _floor_note(inv):
        out += ["", _floor_note(inv)]
    out += [""] + _md_table(["Class", "Sets", "Next"],
                            [[c, str(by_class.get(c, 0)), NEXT[c]] for c in CLASS_ORDER])
    out += _md_models(inv)
    out += _md_review(inv)
    out += ["", "## Scan notes", ""]
    out += [f"- `{_md_code(n['kind'])}` {_md(n['object'])}: {_md(n['detail'])}"
            for n in _notes(inv)] or ["- none"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- HTML

def _h_table(headers: List[str], rows: List[List[str]]) -> str:
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def _h_dependents(x: dict, base=None) -> str:
    items = [f"<li>{e(d['type'])}: {_h_link(base, d['type'], d.get('guid'), d['name'])}</li>"
             for d in x["dependents"]]
    names = _dep_names(x)
    for lb_guid, u in (x.get("liveboards") or {}).items():
        lb = _h_link(base, "LIVEBOARD", lb_guid, names.get(lb_guid, lb_guid))
        items += [f"<li>Liveboard {lb} — viz {e(v['id'])}: {e(v['title'])}</li>"
                  for v in u.get("vizzes") or []]
        if u.get("filter"):
            items.append(f"<li>Liveboard {lb} — Liveboard filter</li>")
    return "<ul>" + ("".join(items) or "<li>none</li>") + "</ul>"


def _h_grants(x: dict) -> str:
    rows = "".join(
        f"<tr><td>{e(g.get('principal_name') or '(unknown)')}</td>"
        f"<td>{e(g.get('principal_type'))}</td><td>{e(g.get('permission'))}</td>"
        f"<td class='p-{e(g['provenance'])}'>{e(g['provenance'])}</td></tr>"
        for g in x["grants"])
    return ("<table><tr><th>Principal</th><th>Type</th><th>Permission</th>"
            f"<th>Provenance</th></tr>{rows}</table>")


def _h_set_detail(x: dict, base=None) -> str:
    return (f"<details><summary><b>{e(x['name'])}</b> · {e(x['class'])} · "
            f"{e(_dep_count(x))} dependent(s) · {e(NEXT.get(x['class'], ''))}</summary>"
            f"<p>{e(x.get('reason'))}</p><h4>Dependents</h4>{_h_dependents(x, base)}"
            f"<h4>Grants</h4>{_h_grants(x)}</details>")


def _h_models(inv: dict) -> str:
    parts = []
    for o, m in _models(inv):
        base = inv.get("base_url")
        title = _h_link(base, "MODEL", m.get("guid"), m["name"])
        parts.append(f"<h2>{e(o['org'])} / {title} — {e(_count(m))} Set(s)</h2>")
        if m["sets"]:
            parts.append(_h_table(SET_HEADERS, [_set_cells(x) for x in m["sets"]]))
            parts += [_h_set_detail(x, base) for x in m["sets"]]
    return "\n".join(parts)


def _h_review(inv: dict) -> str:
    rl = review_lists(inv)
    dl = "\n".join(f"{_s(d['org'])} / {_s(d['model'])} / {_s(d['set'])} ({_s(d['guid'])})"
                   for d in rl["delete"])
    gl = "\n".join(f"{_s(g['org'])} / {_s(g['model'])} / {_s(g['set'])}: "
                   f"{_s(g['principal_name'])} ({_s(g['principal_type'])})" for g in rl["grants"])
    return (f"<h2>Review — delete candidates ({len(rl['delete'])})</h2>"
            f"<textarea readonly>{e(dl)}</textarea>"
            f"<h2>Review — unexplained grants ({len(rl['grants'])})</h2>"
            f"<textarea readonly>{e(gl)}</textarea>")


def _h_notes(inv: dict) -> str:
    items = "".join(f"<li><code>{e(n['kind'])}</code> {e(n['object'])}: {e(n['detail'])}</li>"
                    for n in _notes(inv))
    return f"<h2>Scan notes</h2><ul>{items or '<li>none</li>'}</ul>"


def _h_floor(inv: dict) -> str:
    note = _floor_note(inv)
    return f'<p class="floor">{e(note)}</p>' if note else ""


_CSS = """:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#ddd}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e8e8e8;--mut:#9a9a9a;--line:#333}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}
table{border-collapse:collapse;margin:8px 0;display:block;overflow-x:auto}
td,th{border:1px solid var(--line);padding:4px 8px;text-align:left}
details{border-bottom:1px solid var(--line);padding:6px 0}
.p-UNEXPLAINED,.floor{font-weight:600}.p-UNKNOWN{font-style:italic}
textarea{width:100%;height:8em;background:var(--bg);color:var(--fg);box-sizing:border-box}"""


def render_html(inv: dict) -> str:
    by_class = inv["summary"]["by_class"]
    classes = _h_table(["Class", "Sets", "Next"],
                       [[c, str(by_class.get(c, 0)), NEXT[c]] for c in CLASS_ORDER])
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Set inventory</title><style>{_CSS}</style></head><body>"
        "<h1>Reusable Set inventory</h1>"
        f'<p style="color:var(--mut)">{e(inv.get("generated_at"))} · profile '
        f'{e(inv.get("profile"))} · read-only report</p>'
        f"{_h_table(SUMMARY_HEADERS, [_summary_values(inv)])}"
        f"{_h_floor(inv)}{classes}\n"
        f"{_h_models(inv)}\n{_h_review(inv)}\n{_h_notes(inv)}</body></html>")
