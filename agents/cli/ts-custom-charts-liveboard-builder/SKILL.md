---
name: ts-custom-charts-liveboard-builder
description: Build or rebuild a whole ThoughtSpot Liveboard made of custom charts (BYOC / Muze Studio tiles) that tells one story across numbered tabs, on a real model, through the ThoughtSpot MCP. Profiles the model, plans the tabs and the question each answers, has each tile built with the ts-custom-charts-builder skill against real search results, writes the narrative tiles (About, tab banners), adds Liveboard filters, imports the Liveboard (validate, then commit, then a round-trip proof), and screenshots every tab in a logged-in browser. Use when the user wants a storytelling or demo Liveboard of custom charts, wants tiles added to or rearranged on such a Liveboard, or wants the Amuzing chart samples Liveboard rebuilt. Needs the ts-custom-charts-builder skill installed alongside and the ThoughtSpot MCP (execute-thoughtspot-code). Not for a single chart (use ts-custom-charts-builder) or for Liveboards of native ThoughtSpot charts.
---

# ThoughtSpot custom charts Liveboard builder

You turn a model into a Liveboard that reads as one argument, every tile a custom chart that reads
live data. The charts themselves are made by the sibling skill **ts-custom-charts-builder** (its
`SKILL.md`, `references/library-contract.md` and `library/`); this skill owns everything above the tile:
the story, the tabs, the layout, the narrative tiles, the filters, the import and the in-cluster check.

`<L>` is this skill's folder, `<C>` the chart skill's folder (a sibling; the scripts find it, or set
`TS_CUSTOM_CHARTS_SKILL`). The worked example is `<L>/liveboards/amuzing-chart-samples/`: 50 tiles in
7 tabs on **(Sample) Retail - Apparel**, live as the Liveboard *Amuzing chart samples*.

Use ThoughtSpot's words: **Liveboard**, tile, tab, filter, model, search. Not "board" or "dashboard".

## Route first

| The user wants | Do |
|---|---|
| A new storytelling Liveboard on a model | Steps 1 to 8 |
| More tiles, or changed tiles, on an existing one | Step 4 for the new tiles, then Steps 6 to 8 |
| A rearranged Liveboard (tabs, sizes, filters) | Edit the spec (Step 5), then Steps 6 to 8 |
| One chart, no Liveboard | Stop: that is `ts-custom-charts-builder` |

## Before you start: what must be true

- The ThoughtSpot MCP tool `execute-thoughtspot-code` is connected. Its token is bound to one org; an
  org switch returns 403 (10088), so work in the org it gives you and tell the user which one.
- The chart skill is installed next to this one and its doctor has run once
  (`node <C>/helpers/env.mjs`): the screenshot step uses its Playwright and Chromium.
- Read `references/pipeline.md` once. It holds the sandbox limits that shape every step.

## Step 1 - profile the model (MCP)

Find the model by name, list its columns, and run a few `searchdata` queries: row counts per attribute,
the date range and grain, totals by year and month, the top and bottom of each attribute. Look for the
**story**: steps, trends, concentration, seasonality, what is flat. Write down what the data cannot
support (no cost column means no margin talk). Note data-quality traps (partial first and last periods,
wrong coordinates, renamed columns). Put the findings in `<L>/liveboards/<name>/README.md`; the
example's is the template.

## Step 2 - plan the story and tabs

Follow `references/story-and-layout.md`: numbered, plain tab names, one question per tab, an About tab
first and an action tab last, a banner on every tab, 4 to 10 tiles per tab, a hero per tab, KPI variety,
drill-downs where the data has a hierarchy. Choose each tile's chart shape from the chart skill's
"Start here" table (`<C>/references/examples.md`) and `library.md`. Show the user the plan (tabs,
tiles, searches) and get a yes before building; it is the expensive part.

## Step 3 - confirm the Liveboard exists

Ask for the Liveboard's name or URL, or create an empty one with the user's approval. Its guid goes
in the spec; every import updates it in place.

## Step 4 - build the tiles

Each tile is a chart in `<C>/library/<slug>/`, built by the chart skill's procedure with a **real-data
fixture** (the tile's exact search through `searchdata`) and the library contract. Reuse a library chart
when one fits (change its search and copy; keep the slug if it is the same chart). For many tiles,
brief parallel subagents, one tab each, with `references/tile-brief.md`.

Narrative tiles (About hero, guide, tab banners) are not hand-built: write one
`<L>/liveboards/<name>/narratives/<slug>.cfg.js` per tile (copy the example's), then
`node <L>/scripts/build-narratives.mjs --liveboard <L>/liveboards/<name>`. Their copy is computed from
the rows, so it follows the filters.

## Step 5 - the spec

Copy `liveboards/amuzing-chart-samples/make-spec.py` to your Liveboard's folder, edit the tile table
(slug, title, search, x, y, w, h, description, whether filters apply), the filters and the Liveboard guid,
and run it. It writes `liveboard.spec.json`. Rows of each tab must fill 12 columns without overlap.

## Step 6 - write the tiles into the Liveboard (MCP)

The Liveboard is its own store. Nothing else is created in ThoughtSpot: no helper Liveboards, no answers.

```bash
node <L>/scripts/liveboard-pack.mjs --liveboard <dir> --validate <slug> ... > <scratch>/p.js   # or --all
node <L>/scripts/liveboard-pack.mjs --liveboard <dir> --commit   <slug> ... > <scratch>/p.js
```

Each block carries some charts (up to `--max`, default 60,000 characters), the spec and the shared core.
In the sandbox (`<L>/scripts/patch.js`) it checks every sha256, exports the Liveboard, replaces those charts'
tiles, keeps every other tile exactly as it is, imports, and after a commit proves by export that every
tile carries the code that was composed. Read the file and paste **each block between the `=====` lines
unchanged** as the `code` of `execute-thoughtspot-code` with `confirm_write_operations: true`, in order.
Every block leaves a complete, working Liveboard, so a build can stop between blocks.

1. `--validate` first when the spec changed (tabs, sizes, searches, filters): a `VALIDATE_ONLY` import.
2. `--commit`. Success is `import.status_code: OK`, `roundTripAllOk: true`, `problems: []`, and the
   slugs you meant in `replaced`. `CHECKSUM MISMATCH` means the paste was altered: resend the block.
3. Send only what changed. A new Liveboard needs every tile once (`--all`, several blocks).

**Before and after, check for drift:** `node <L>/scripts/liveboard-pack.mjs --liveboard <dir> --check`
prints one read-only block that compares every tile on the Liveboard with the library. Expect
`stale: []` and `missing: []`. A chart edited in the library but never sent keeps its **old** code on the
Liveboard with no error anywhere (this is how the Plotly sunburst stayed an ECharts one for a whole round).

## Step 7 - look at it in the cluster

```bash
node <L>/scripts/cluster-shot.mjs --url "<liveboard url>" --tabs "01 About,02 Pulse,..." --wait 10
node <L>/scripts/cluster-shot.mjs --url "<liveboard url>" --tabs "03 Where" --filter "Region=West" --out <dir>
```

A headed Chromium with a persistent profile opens; the first time the user signs in (SSO) in that
window, so tell them before you run it. It scrolls each tab, saves `<tab>-N.png`, and lists tiles
showing failure text. **Read every PNG**: blank or clipped tiles, overlapping text, a tooltip stuck on,
colours that break the rules, copy that reads wrong. The filtered run proves tiles survive filters. Fix
in the chart skill, then send just that chart (`--commit <slug>`).

## Step 8 - report

Tabs and tile counts, the round-trip result, the drift check, which screenshots you read and what you
fixed, and anything not verified (interactions and motion are only seen as still frames).
Update the example's README when the story changes.

## What not to do

- Do not send a whole Liveboard's TML from your context; it is megabytes of base64. Patch it in blocks.
- Do not create helper objects (stores, scratch Liveboards, answers) in the user's ThoughtSpot. If a task
  ever needs one, name it in the plan, get a yes, and delete it before you finish.
- Do not commit without a dry run and a validate run first.
- Do not claim a tile works in ThoughtSpot until its tab has been screenshotted and the PNG read.
- Do not put a native ThoughtSpot chart on these Liveboards, or sample rows in a chart.
- No emojis, em-dashes or stock phrasing anywhere, including tab names and banners
  (`<C>/references/taste-rules.md`).

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-09-29 | Initial release in this library (ported from thoughtspot-amuzing-liveboard 2.0.0). Builds a storytelling Liveboard of custom-chart tiles across numbered tabs on a real model through the ThoughtSpot MCP: plans tabs, has tiles built by `ts-custom-charts-builder`, writes narrative tiles, adds filters, patches the Liveboard in checked blocks, and screenshots every tab in a logged-in browser. |
