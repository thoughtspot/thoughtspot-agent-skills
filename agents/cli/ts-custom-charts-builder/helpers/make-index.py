#!/usr/bin/env python3
"""Regenerates references/library.md from every library/<slug>/README.md. Run after adding or changing a chart."""
import os, re, glob
HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.abspath(os.path.join(HERE, "..", "library"))
OUT = os.path.abspath(os.path.join(LIB, "..", "references", "library.md"))
rows = []
for d in sorted(glob.glob(os.path.join(LIB, "*"))):
    slug = os.path.basename(d)
    if slug.startswith("_") or not os.path.exists(os.path.join(d, "README.md")): continue
    t = open(os.path.join(d, "README.md")).read()
    title = re.search(r"^# (.+)$", t, re.M)
    def cell(k):
        m = re.search(r"\| " + k + r" \| (.+?) \|", t)
        return m.group(1).strip() if m else ""
    tile = cell("Tile")
    tab = re.search(r"\((\d\d \w+|[A-Za-z0-9 ]+) tab\)", tile)
    interactions = re.search(r"## Interactions\n(.+?)\n\n", t, re.S)
    rows.append(dict(slug=slug, title=title.group(1) if title else slug, search=cell("Search").strip("`"), lib=cell("Library"), tile=re.sub(r"\s*\(.*\)", "", tile), tab=(tab.group(1) if tab else ""), inter=(interactions.group(1).replace("\n", " ") if interactions else "")))
order = ["01 About", "About", "02 Pulse", "Pulse", "03 Where", "Where", "04 What", "What", "05 When", "When", "06 Who", "Who", "07 Next", "Next", ""]
def key(r):
    return (order.index(r["tab"]) if r["tab"] in order else 99, r["slug"])
rows.sort(key=key)
out = ["# Library: proven live-data charts\n",
"Every chart here runs on the model **(Sample) Retail - Apparel**, reads only what its search returns (data mode B, an empty state names the search), is interactive, and passed the loop, the edge checks, `probe.mjs` and a screenshot in a real cluster. Start from the nearest one: copy `library/<slug>/`, change the search and the copy, run the loop.\n",
"Shared pieces: `library/_shared/core.js` and `core.css` (theme, data access, tooltip, bounded CDN loader, boot), `library/_shared/us-states.js` (inline US map). The Liveboard that arranges them, and the tools that build it, are in the sibling skill `ts-custom-charts-liveboard-builder`.\n",
"| Chart | Tab | Tile | Built with | Search |", "|---|---|---|---|---|"]
for r in rows:
    out.append(f"| `{r['slug']}` {r['title']} | {r['tab']} | {r['tile']} | {r['lib']} | `{r['search']}` |")
out.append("\n## What each one does when you touch it\n")
for r in rows:
    out.append(f"- **{r['slug']}**: {r['inter']}")
open(OUT, "w").write("\n".join(out) + "\n")
print(len(rows), "charts indexed ->", os.path.relpath(OUT))
