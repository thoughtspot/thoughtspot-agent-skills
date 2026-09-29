# Tile brief (for subagents building one tab)

When tiles are built in parallel, give each subagent this brief with the blanks filled. It keeps every
tile on the same contract and makes the reports mergeable.

---

You are building custom chart tiles for the ThoughtSpot Liveboard **<LIVEBOARD NAME>** (guid `<guid>`),
tab **<TAB>**, on the model **<MODEL NAME>** (guid `<model guid>`, org <ORG>). `$S` is the
ts-custom-charts-builder skill at `<path>`; `$L` is ts-custom-charts-liveboard-builder at `<path>`.

Read, in this order, before writing anything:
1. `$S/references/library-contract.md` (the whole file: the contract every tile follows).
2. `$L/liveboards/<name>/README.md` (what the data holds and its traps).
3. `$S/references/examples.md` "Start here" and the library charts named for your tiles.

Your tiles:

| Slug | Title | Search | Size (w x h) | Question it answers | Shape / starting chart |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... |

For each tile: real-data fixture from its exact search, the loop, the interaction and edge checks, the
filter-resilience check, then `library-emit`. Do **not** write to ThoughtSpot: the coordinator sends every
chart to the Liveboard, one block at a time, because two patches running at once overwrite each other.

Do not edit `$S/library/_shared/`, the spec, or any chart that is not yours. Propose changes to those in
your report instead.

Report, per tile: slug, title, one-sentence description (the search and how to read and interact),
search, size, libraries and CDN URLs, interactions, preview path,
caveats (data quality, filter behaviour). Then a **Friction** list: anything in either skill that
slowed you or caused a defect, with the fix you would make.
