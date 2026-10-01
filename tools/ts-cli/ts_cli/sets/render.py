"""Inventory -> self-contained HTML + Markdown. No external assets; every name escaped.

Read-only rendering of a `ts-sets-inventory/1` document. Orgs, Models and Sets are
rendered in the order the document gives them (the inventory already sorts Sets); the
renderer never re-sorts. An INCOMPLETE Model is shown as "unknown", never as zero Sets.
"""
from __future__ import annotations

from html import escape as e
from typing import Iterator, List, Tuple

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
    return sum(1 for _, _, s in _sets(inv) for g in s["grants"] if g["provenance"] == "UNKNOWN")


def _notes(inv: dict) -> List[dict]:
    """Top-level notes (e.g. `org_skipped`) first, then every Org's notes."""
    return list(inv.get("notes") or []) + [n for o in inv["orgs"] for n in o.get("notes") or []]


def _count(m: dict) -> str:
    if m["discovery"] == "INCOMPLETE" or m.get("set_count") is None:
        return "unknown (discovery INCOMPLETE)"
    return str(m["set_count"])


def _summary_values(inv: dict) -> List[str]:
    s = inv["summary"]
    return [str(s["models"]), str(s["models_incomplete"]), str(s["sets"]),
            str(s["unexplained_grants"]), str(unknown_grant_count(inv))]


SUMMARY_HEADERS = ["Models", "Incomplete", "Sets", "Unexplained grants", UNKNOWN_LABEL]
SET_HEADERS = ["Set", "Type", ANCHOR_LABEL, "Author", "Dependents", "Class", "Next"]


def _set_cells(x: dict) -> List[str]:
    return [x["name"], x.get("cohort_type", ""), x.get("anchor_column", ""),
            x.get("author", ""), str(len(x["dependents"])), x["class"], NEXT[x["class"]]]


# ---------------------------------------------------------------- Markdown

def _md(text) -> str:
    """Make a value safe inside a Markdown table cell."""
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _md_row(cells: List[str]) -> str:
    return "| " + " | ".join(_md(c) for c in cells) + " |"


def _md_table(headers: List[str], rows: List[List[str]]) -> List[str]:
    return [_md_row(headers), "|" + "---|" * len(headers)] + [_md_row(r) for r in rows]


def _md_models(inv: dict) -> List[str]:
    out: List[str] = []
    for o, m in _models(inv):
        out += ["", f"## {_md(o['org'])} / {_md(m['name'])} — {_count(m)} Set(s)", ""]
        if m["sets"]:
            out += _md_table(SET_HEADERS, [_set_cells(x) for x in m["sets"]])
    return out


def _md_review(inv: dict) -> List[str]:
    rl = review_lists(inv)
    out = ["", "## Review — delete candidates", ""]
    out += [f"- {_md(d['org'])} / {_md(d['model'])} / {_md(d['set'])} (`{d['guid']}`)"
            for d in rl["delete"]] or ["- none"]
    out += ["", "## Review — unexplained grants", ""]
    out += [f"- {_md(g['org'])} / {_md(g['model'])} / {_md(g['set'])}: "
            f"{_md(g['principal_name'])} ({_md(g['principal_type'])})"
            for g in rl["grants"]] or ["- none"]
    return out


def render_markdown(inv: dict) -> str:
    by_class = inv["summary"]["by_class"]
    out: List[str] = ["# Reusable Set inventory", "",
                      f"Generated {inv.get('generated_at', '')} · profile "
                      f"`{inv.get('profile', '')}` · read-only report", ""]
    out += _md_table(SUMMARY_HEADERS, [_summary_values(inv)])
    out += [""] + _md_table(["Class", "Sets", "Next"],
                            [[c, str(by_class.get(c, 0)), NEXT[c]] for c in CLASS_ORDER])
    out += _md_models(inv)
    out += _md_review(inv)
    out += ["", "## Scan notes", ""]
    out += [f"- `{_md(n['kind'])}` {_md(n['object'])}: {_md(n['detail'])}"
            for n in _notes(inv)] or ["- none"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- HTML

def _h_table(headers: List[str], rows: List[List[str]], cls: str = "") -> str:
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows)
    attr = f' class="{cls}"' if cls else ""
    return f"<table{attr}><tr>{head}</tr>{body}</table>"


def _h_dependents(x: dict) -> str:
    items = [f"<li>{e(d['type'])}: {e(d['name'])}</li>" for d in x["dependents"]]
    for lb_guid, u in (x.get("liveboards") or {}).items():
        items += [f"<li>Liveboard {e(lb_guid)} — viz {e(v['id'])}: {e(v['title'])}</li>"
                  for v in u.get("vizzes") or []]
        if u.get("filter"):
            items.append(f"<li>Liveboard {e(lb_guid)} — Liveboard filter</li>")
    return "<ul>" + ("".join(items) or "<li>none</li>") + "</ul>"


def _h_grants(x: dict) -> str:
    rows = "".join(
        f"<tr><td>{e(g.get('principal_name') or '(unknown)')}</td>"
        f"<td>{e(g.get('principal_type', ''))}</td><td>{e(g.get('permission', ''))}</td>"
        f"<td class='p-{e(g['provenance'])}'>{e(g['provenance'])}</td></tr>"
        for g in x["grants"])
    return ("<table><tr><th>Principal</th><th>Type</th><th>Permission</th>"
            f"<th>Provenance</th></tr>{rows}</table>")


def _h_set_detail(x: dict) -> str:
    return (f"<details><summary><b>{e(x['name'])}</b> · {e(x['class'])} · "
            f"{len(x['dependents'])} dependent(s) · {e(NEXT[x['class']])}</summary>"
            f"<p>{e(x.get('reason') or '')}</p><h4>Dependents</h4>{_h_dependents(x)}"
            f"<h4>Grants</h4>{_h_grants(x)}</details>")


def _h_models(inv: dict) -> str:
    parts = []
    for o, m in _models(inv):
        parts.append(f"<h2>{e(o['org'])} / {e(m['name'])} — {e(_count(m))} Set(s)</h2>")
        if m["sets"]:
            parts.append(_h_table(SET_HEADERS, [_set_cells(x) for x in m["sets"]]))
            parts += [_h_set_detail(x) for x in m["sets"]]
    return "\n".join(parts)


def _h_review(inv: dict) -> str:
    rl = review_lists(inv)
    dl = "\n".join(f"{d['org']} / {d['model']} / {d['set']} ({d['guid']})" for d in rl["delete"])
    gl = "\n".join(f"{g['org']} / {g['model']} / {g['set']}: {g['principal_name']} "
                   f"({g['principal_type']})" for g in rl["grants"])
    return (f"<h2>Review — delete candidates ({len(rl['delete'])})</h2>"
            f"<textarea readonly>{e(dl)}</textarea>"
            f"<h2>Review — unexplained grants ({len(rl['grants'])})</h2>"
            f"<textarea readonly>{e(gl)}</textarea>")


def _h_notes(inv: dict) -> str:
    items = "".join(f"<li><code>{e(n['kind'])}</code> {e(n['object'])}: {e(n['detail'])}</li>"
                    for n in _notes(inv))
    return f"<h2>Scan notes</h2><ul>{items or '<li>none</li>'}</ul>"


_CSS = """:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#ddd}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e8e8e8;--mut:#9a9a9a;--line:#333}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}
table{border-collapse:collapse;margin:8px 0;display:block;overflow-x:auto}
td,th{border:1px solid var(--line);padding:4px 8px;text-align:left}
details{border-bottom:1px solid var(--line);padding:6px 0}
.p-UNEXPLAINED{font-weight:600}.p-UNKNOWN{font-style:italic}
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
        f'<p style="color:var(--mut)">{e(inv.get("generated_at", ""))} · profile '
        f'{e(inv.get("profile", ""))} · read-only report</p>'
        f"{_h_table(SUMMARY_HEADERS, [_summary_values(inv)])}{classes}\n"
        f"{_h_models(inv)}\n{_h_review(inv)}\n{_h_notes(inv)}</body></html>")
