---
name: ts-custom-charts-builder
description: Build a ThoughtSpot custom chart (BYOC) as three paste-ready files — chart.html, chart.css, chart.js — by iterating in a real browser until the render is right. Starts with an intake that checks the prerequisites and asks the model, data mode, search, library and destination as pick-from-a-list questions; can save the finished chart as a ThoughtSpot answer and screenshot it in a logged-in browser. Opens a preview the user watches (a headed window in Claude Code; headless screenshots in the Claude app or wherever no window can open), screenshots each attempt, critiques it with vision, and fixes the top defect. Use when the user wants a ThoughtSpot custom chart, a BYOC tile, a Muze chart, or wants an existing chart tile rebuilt, debugged, or converted between sample and live data. Covers Muze, D3, ECharts, Plotly, Chart.js, gridjs, hand-built HTML tables, and raw SVG, and hands finished tiles to the ts-custom-charts-liveboard-builder skill to put on a Liveboard. Ships a library of proven live-data charts under library/. Not for native ThoughtSpot chart configuration or non-ThoughtSpot charting work.
---

# ThoughtSpot custom chart builder

You are the engine. You write the three files, run the helpers over Bash, read the
screenshots with vision, critique, fix, repeat. No orchestrator, no API calls.

The preview runs **the same three files the user will paste**, through a `viz` stub,
inside an `AsyncFunction` — the shape the real host uses. So there is no porting step
at the end: what you iterated is what ships. Everything below protects that property.

Two things the harness withholds on purpose, because supplying them is how a chart
passes here and ships as a blank tile:

- **`viz` arrives as an argument, never as `globalThis.viz`.** Read the bare
  identifier.
- **The preview page does not set `html, body { height: 100% }`.** `chart.css` has to
  complete its own height chain, exactly as on a tile.

`snap.mjs` reports both — a `height-chain:` line in the diagnostic block, and a
status warning when render-complete never fires. Read them; neither shows up in the
screenshot.

## Route first

| Trigger | Do |
|---|---|
| User attaches or points at a chart image | **Rebuild** — match the image |
| User describes a chart in prose | **Build** — match the description |
| User has an existing tile that misbehaves | **Debug** — start from their files, skip to the loop |
| User wants sample→live or live→sample | **Convert** — read `references/byoc-data-modes.md`, change the mode, verify both |
| User wants a chart that a library chart already covers | **Adapt** - open `references/library.md`, copy the nearest `library/<slug>/`, change the search and copy, then run the loop |
| User wants finished tiles on a Liveboard, or a whole Liveboard | **Hand over** - `## Step 10`; the Liveboard work is the `ts-custom-charts-liveboard-builder` skill |
| Ambiguous | The Step 0 intake settles it |

Every route starts with Step 0. A **Debug** run asks only the destination and check questions.

## Step 0 — doctor and intake

### 0a. Doctor (every run, one Bash call)

`<SKILL>` is the folder this SKILL.md lives in. Typical values: Claude Code,
`~/.claude/skills/<name>` or `<project>/.claude/skills/<name>`; the Claude app,
`/mnt/skills/user/<name>`.

```bash
node "<SKILL>/helpers/env.mjs" "<SLUG>"
```

It prints one `key: value` per line. Take these from it and substitute the literal
paths into **every** later command — shell state does not persist between Bash calls,
so `$VARS` set in one call are gone in the next:

| Placeholder | Doctor line | Meaning |
|---|---|---|
| `<RUNS>` | `runs-root:` | working files for every run |
| `<OUT>` | `output-root:` | where deliverables go (the user downloads this in the Claude app) |
| `<MODE>` | `mode:` | `headed` (a window the user watches) or `headless (…)` |
| `<SLUG>` | — | the run's kebab-case name, chosen in Step 3 |

If `deps: missing`, the `fix:` line is the command that fixes it:

- **Claude Code** — ask once ("First-time setup, ~2 min: install Playwright +
  Chromium. OK?"), run the `fix:` line, re-run the doctor.
- **Claude app** (`platform: claude-app`) — run the `fix:` line directly (~30 s; it
  installs `playwright-core` into a writable folder and uses the sandbox's own
  Chromium), re-run the doctor. **Never run `playwright install` there** — the browser
  download is blocked and burns minutes before failing. If the doctor still reports
  no browser, stop and show the user the doctor block.

`browser-launch:` actually starts Chromium, which is the only reliable check:
Chromium is pinned to the Playwright version, so a cached build can look present and
still fail to launch. Note `cdn:` for Library choice below.

Also check whether the ThoughtSpot MCP tool `execute-thoughtspot-code` is connected. If it is, one
read-only call returns the signed-in user, the org, the cluster name and the models. The token is bound
to one org, so that is the org you work in. Search models by name: an org can hold hundreds of logical
tables and an unfiltered listing is cut off before the one the user means.

```js
const me = (await ts.get('/api/rest/2.0/auth/session/user')).body;
const sys = (await ts.get('/api/rest/2.0/system')).body;            // sys.name is the cluster, e.g. ps-internal
const r = await ts.post('/api/rest/2.0/metadata/search', { metadata: [{ type: 'LOGICAL_TABLE', name_pattern: '%<words from the request>%' }], record_size: 50 });
const models = (Array.isArray(r.body) ? r.body : []).filter((m) => ['WORKSHEET', 'MODEL'].includes((m.metadata_header || {}).type));
return { user: me.name, org: me.current_org.name, cluster: sys.name, models: models.map((m) => ({ name: m.metadata_name, guid: m.metadata_id })) };
```

For the model's columns (round 2), the same search with `identifier: '<guid>'` and `include_details: true`
returns `metadata_detail.columns` (name, `ATTRIBUTE` or `MEASURE`, data type).

Show the user one short block before asking anything: browser mode, CDN reach, MCP connected or not
(and which org), and what each missing piece rules out (no MCP: no real data and no saved answer; no
browser window: no check in ThoughtSpot).

### 0b. Intake: ask with choices

Use the `AskUserQuestion` tool so the user picks instead of typing. It takes up to 4 questions per
call and 2 to 4 options each, and adds "Other" for free text by itself. Build the options from what 0a
found, never from placeholders; put the likely pick first and add "(Recommended)" to it. Skip any
question the user's message already answered.

Round 1:

| Header | Question | Options |
|---|---|---|
| Model | Which model should the chart read? | Up to 3 models from 0a, the most likely first, plus "No model: sample data only". Skip when the MCP is not connected |
| Data | How should the chart get its data? | "Live with sample fallback (Recommended)", "Live only", "Sample only" (modes C, B, A in Step 2) |
| Result | Where should the finished chart go? | "Files only", "Save as an answer in ThoughtSpot", "Add to a Liveboard". Offer the last two only when the MCP is connected |
| Check | Testing in ThoughtSpot opens a browser window where you sign in once (SSO). Include it? | "Yes, I will sign in when the window opens (Recommended)", "No, verify in the local preview only". Ask only when the result is an answer or a Liveboard and 0a found a browser that can open a window |

Round 2, after a quick column list of the chosen model:

| Header | Question | Options |
|---|---|---|
| Search | Which search should the chart run? | 2 or 3 searches you draft from the columns and the request, for example `[sales] [region] [date].monthly`. "Other" takes the user's own |
| Library | Which chart library? | "Pick for me (Recommended)", then the two or three that fit this shape from Library choice below |

If `AskUserQuestion` is not available, ask the same questions in one message as a numbered list with
lettered options, and wait for the answers. Write the answers into `<RUNS>/<SLUG>/intent.txt` in Step 3.

## Step 1 — load knowledge

Read before writing any chart code, in this order:

1. `references/byoc-data-modes.md` — sample vs. live vs. both. **Always.**
2. `references/hard-rules.md` — the silent failures, and how each one shows up.
3. `references/examples.md` — the working charts under `examples/`, indexed by shape.
   Find the nearest one and read it before writing; it settles the API questions
   faster than the reference does and carries the workarounds already found.
4. `references/system-prompt.md` — long-form recipes and patterns.
5. `references/muze-api-reference.md` — when the chart is Muze.
6. `references/taste-rules.md` — the design bans and copy rules every chart is critiqued against (no emojis, no em-dashes, one accent rule, specific copy).
7. `references/library.md` — the proven live-data charts in `library/`, indexed by question. Start from the nearest one.
8. `references/library-starters.md` — per-library starters and traps (CDN loading, drill-down, motion) learned in real tiles. Read it before using a library for the first time.

All eight ship with the skill; paths are relative to the skill folder, wherever it is
installed.

## Step 2 — settle the data mode

Use the intake answer (Step 0). Default to **C**.

- **A — sample only.** Rows baked in. Demos, layout, print work.
- **B — live only.** `getDataFromSearchQuery()`. A tile bound to a real search.
- **C — live with sample fallback.** Tries live, falls back to baked-in rows, shows a
  "sample data" badge. One file that works on a live tile, an unbound tile, and a
  plain browser.

Skeletons are in `references/byoc-data-modes.md`. Follow them; do not improvise a
fourth shape.

With a model and search from the intake, the column names come from `searchdata` (Step 3). Without
the MCP, ask the user to paste the `Available Columns` block from their chart editor and map the field
constants onto those exact names.

## Step 3 — run dir and dataset

Pick `<SLUG>` (kebab-case: `revenue-by-region`, `credit-tier-snapshot`).

```bash
mkdir -p "<RUNS>/<SLUG>/chart"
```

Write `<RUNS>/<SLUG>/intent.txt` — one paragraph. From the image (vision) or the user's
prose. This is what you critique against later, so be concrete: chart type, encodings,
what "correct" looks like.

Write `<RUNS>/<SLUG>/sample-data.json` **once**, at run start. Never regenerate it
mid-loop — a moving schema means the loop cannot converge.

```json
{
  "schema": [
    { "name": "REGION",  "type": "dimension" },
    { "name": "REVENUE", "type": "measure", "defAggFn": "sum" }
  ],
  "rows": [ { "REGION": "EMEA", "REVENUE": 1240 } ]
}
```

Max 30 rows. If the user supplied a CSV, parse it and cap it. **If the ThoughtSpot MCP is connected and the tile has a real search, do not invent rows: run the exact search with `searchdata` and write its output as the fixture** (`{schema, rows}`, dates multiplied by 1000 because tiles receive epoch milliseconds, column names exactly as the search returns them: `Total sales`, `Month(date)`). The 30-row cap is lifted for real data, but keep searches aggregated so the fixture stays under about 1,000 rows. Otherwise invent
something plausible for the chart type. The preview serves this file both as the
baked-in sample rows and, reshaped into TS's array-row form, as the live query
result. Schema `type` passes through as declared — real clusters have been seen
reporting both `measure` and `MEASURE`, so charts should accept either.

## Step 4 — start the preview

Headed is preferred — the user watches each attempt land. Start it even when you are
not sure a window can open; it falls back on its own.

```bash
node "<SKILL>/helpers/start-preview.mjs" "<SLUG>"
```

Background it (`run_in_background: true`). It seeds `<RUNS>/<SLUG>/chart/` with three
placeholder files, serves the preview, and opens a window. Then wait (up to ~20 s)
for **either**:

- `<RUNS>/<SLUG>/.preview/cdp.json` — the window is up. It shows a tile-shaped box and
  reloads itself within a second of any edit to the three chart files.
- a `headless fallback` line in its output — there is no display (the Claude app) or
  the headed launch failed. It exits; carry on. `snap.mjs` captures with its own
  headless browser, so the loop is unchanged.

## Step 5 — the loop

For `attempt = 01..8`:

1. **Edit** `<RUNS>/<SLUG>/chart/chart.{html,css,js}`. First attempt: derive from the
   image or intent plus the `references/` files. Use UPPER_SNAKE_CASE field constants
   matching `sample-data.json`.
2. **Archive this attempt's files** so each `NN.png` sits next to the exact code
   that produced it:
   ```bash
   mkdir -p "<RUNS>/<SLUG>/attempts/<NN>" && cp "<RUNS>/<SLUG>/chart/"* "<RUNS>/<SLUG>/attempts/<NN>/"
   ```
3. **Capture:**
   ```bash
   node "<SKILL>/helpers/snap.mjs" "<SLUG>" "<NN>"
   ```
   Writes `attempts/NN.png` and prints a diagnostic block — `mode:`, status line,
   console errors, whether `emitRenderCompletedEvent` fired.
4. **Critique.** Read the PNG with the Read tool. **Read the diagnostic block too** —
   a chart that throws still screenshots, just empty, and the two failures need
   different fixes. Write `attempts/NN.critique.md`:
   ```
   VERDICT: MATCH | CLOSE | OFF
   DEFECTS:
   - <one per line, worst first>
   ```
5. **Decide:**
   - `MATCH` → go to step 6.
   - Same defect list twice running → escalate: change the mark, the encoding, or the
     library. Repeating the same fix harder does not work.
   - Three `OFF` in a row → stop and ask the user; you are solving the wrong problem.
   - Otherwise → fix the top defect and loop.
6. **User interjection.** A new message mid-loop is the top defect for the next pass.

**When `mode:` is headless**, the user has no window. After each snap, give them the
`user-png:` path (the Claude app copies every attempt into `<OUT>/<SLUG>/attempts/`,
where they can open it) and a one-line verdict. Font and anti-aliasing differences
from ThoughtSpot are not defects. If `mode:` flips from `headed` to `headless` mid-run
in Claude Code, the window died: run Step 4 once more, then continue in whatever mode
results.

Past 8 attempts without MATCH: stop, write `lessons.md` with `STATUS: incomplete`,
tell the user what is unresolved. Do not quietly keep going.

## Step 6 — verify the modes the loop did not exercise

The loop runs one data mode. These are the failures that only appear in the others,
and skipping them is how a chart that "worked" breaks on someone else's tile.

```bash
node "<SKILL>/helpers/snap.mjs" "<SLUG>" 91 --data absent    # mode C must fall back + badge; B must degrade readably
node "<SKILL>/helpers/snap.mjs" "<SLUG>" 92 --data wrapped   # object-wrapped cells must survive
node "<SKILL>/helpers/snap.mjs" "<SLUG>" 93 --data empty     # zero rows must not throw
node "<SKILL>/helpers/snap.mjs" "<SLUG>" 94 --data noviz     # no host at all - mode C must still render
```

Read each PNG — `status: ok` is not the same as correct, and each of these fails
differently. Use distinct attempt numbers so the four frames survive as evidence. To run several in a loop,
use `bash -c '...'`: zsh (the macOS default) does not split `$args`, so the flags arrive as one argument,
are ignored, and the PNGs get names like `91 --data absent.png`.

Then two more, neither of which the loop exercises.

**Resize the container, not the window.** A Liveboard tile resizes while the window
does not, so only a `ResizeObserver` on the container sees it. `--tile` resizes the
tile box (never the window — `Browser.setWindowBounds` silently no-ops on some builds
and a mid-transition screenshot shows a clip that is not a bug) and compares the
chart's widest `<svg>`/`<canvas>` against it:

```bash
node "<SKILL>/helpers/snap.mjs" "<SLUG>" 95 --tile 620x400    # a narrow Liveboard tile
node "<SKILL>/helpers/snap.mjs" "<SLUG>" 96 --tile 1400x500   # a wide one
```

Read `svg-fit:`. `overflow` means a missing `ResizeObserver` — Plotly's and Chart.js's
`responsive` options listen to `window.resize` only. `blank` means canvas shadowing
or a zero-size stage. Both are in `references/hard-rules.md`. `n/a` is expected for a
chart with no svg or canvas (an HTML table); read its PNG instead.

**Prove it responds.** Every chart must react to the pointer: at minimum a hover tooltip, and where the shape allows a click to isolate, a toggle, a sort or a scrub. Check it, do not assume it:

```bash
node "<SKILL>/helpers/probe.mjs" "<SLUG>" --tile 620x400 --sweep                 # >= 3 of 5 points must change the DOM
node "<SKILL>/helpers/probe.mjs" "<SLUG>" --tile 620x400 --hover 0.6,0.5 --out 97   # then Read attempts/97.hover.png
node "<SKILL>/helpers/probe.mjs" "<SLUG>" --tile 620x400 --click 0.9,0.1 --out 98   # a toggle or a mark
node "<SKILL>/helpers/probe.mjs" "<SLUG>" --tile 620x400 --click-sel ".wedge" --wait 900 --after "document.querySelector(\".crumbs\").innerText" --out 99   # read what a drill changed
```

`--eval "js"` inspects the DOM after the interaction. A chart whose sweep reports `NOT INTERACTIVE` is not done. Click-only charts (toggles, expanders) report 0 on the sweep by design: verify those with `--click`.

**Empty the HTML tab and re-snap.** `chart.js` must build its own mount points. A
chart that only renders when `chart.html` is present fails on a host that evaluates
the JS first — which surfaces as the host's own "Chart did not render" over an empty
tile, with nothing useful in the console. Judge this one by the status line and
`console-errors`, not the PNG: the created `#chart` lands on `<body>` outside the preview's tile
box, so it lays out at window size and the screenshot shows only its top-left corner. On a real
tile the body is the tile. Restore `chart.html` afterwards.

## Step 7 — emit

Work `references/emit-checklist.md` top to bottom. Then copy the deliverables into
`<OUT>/<SLUG>/` — files, not chat scroll. In Claude Code that is `output/<slug>/` at
the project root; in the Claude app it is the outputs folder the user downloads from.

```bash
mkdir -p "<OUT>/<SLUG>" && cp "<RUNS>/<SLUG>/chart/"* "<OUT>/<SLUG>/"
cp "<RUNS>/<SLUG>/attempts/<NN>.png" "<OUT>/<SLUG>/preview.png"   # the MATCH attempt
```

The chart files are copied unchanged — that is the point of the preview running the
real shape. `preview.png` is the screenshot of the attempt that passed, so the folder
shows what the chart looks like without running anything. Write
`<OUT>/<SLUG>/README.md` per the checklist: the search to build, the data mode, what
could not be reproduced, and which file goes in which tab.

Do **not** paste the three files into the chat. Tell the user the folder path, list
its contents, and summarize the run README in a couple of sentences. Show code inline
only if the user asks for it.

## Step 8 — close

```bash
node "<SKILL>/helpers/close-preview.mjs" "<SLUG>"
```

Always, on success or when the user says stop. In headless mode there is no window
and it says so — harmless.

## Step 9 - save it as an answer and check it in ThoughtSpot (optional)

Only when the intake chose "Save as an answer in ThoughtSpot". It needs the MCP and a live chart (mode B
or C) built on the intake search. The answer is the one object this creates; make no scratch answers.

1. **Pack.** `answer-pack.mjs` turns the three files into one block of MCP code. The files go unchanged,
   so the answer runs exactly what the preview ran.
   ```bash
   node "<SKILL>/helpers/answer-pack.mjs" "<OUT>/<SLUG>" --model <model guid> --search "<search>" --name "<title>" --commit > "<RUNS>/<SLUG>/answer-commit.js"
   ```
   To update an answer made earlier, add `--answer <guid>`: it updates in place instead of making a copy.
2. **Validate and commit in one paste.** `--commit` runs a `VALIDATE_ONLY` import first and commits only
   if it passes, so there is one block to send; `--validate` alone is for checking without writing. Read the
   file and paste it, unchanged, as the `code` of `execute-thoughtspot-code` with
   `confirm_write_operations: true` (a validate counts as a write too). A commit succeeds when it returns
   `validate.status_code: OK`, `import.status_code: OK`, `chartType: MUZE_STUDIO`, `roundTripOk: true` and a
   `guid`. The block carries the whole core (about 30 KB); copy it exactly, the checksum catches any slip.
   `CHECKSUM MISMATCH` means the paste was altered: resend the block. Put the guid in
   `<OUT>/<SLUG>/README.md` so the next change updates the same answer.
3. **Open it.** The answer is at `https://<cluster host>/#/saved-answer/<guid>`. The MCP does not expose
   the host (its configuration points at a proxy). `sys.name` from Step 0a names the cluster, and the host
   is usually `<name>.thoughtspot.cloud`; after a first screenshot run, the profile's history
   (`~/.cache/amuzing-chart/cluster-profile/Default/History`) has it too. Confirm with the user if unsure.
4. **Screenshot it**, unless the intake chose "verify in the local preview only". A headed Chromium
   with a persistent profile opens, and the first time the user signs in (SSO) in it, so remind them
   right before:
   ```bash
   node "<SKILL>/helpers/cluster-shot.mjs" --url "<answer url>" --name "<SLUG>" --out "<OUT>/<SLUG>/cluster" --wait 10
   ```
   Read the PNG and the `problems` line (failure text found inside the chart frame). A fix goes back
   through the loop (Step 5) and Step 6, then is sent again with `--answer <guid> --commit`.

Where no window can open (the Claude app), skip step 4 and report the chart as verified in preview only.

## Step 10 - put it on a Liveboard (optional)

Publishing tiles to a Liveboard, and building a whole storytelling Liveboard of them, is the sibling
skill **ts-custom-charts-liveboard-builder** (patches the Liveboard through the ThoughtSpot MCP, narrative
tiles, filters, round-trip proof, in-cluster screenshots). To hand a chart over:

1. Build it to `references/library-contract.md` (shared core, ASCII, no template strings).
2. `node "<SKILL>/helpers/sync-core.mjs" "<RUNS>/<SLUG>/chart"`, then
   `node "<SKILL>/helpers/library-emit.mjs" <SLUG> --title ... --search ... --tile WxH ...` publishes it to
   `library/<slug>/` (refuses non-ASCII or a drifted core). `--png` is relative to the run folder (`attempts/03.520x400.png`), not the repo. `python3 "<SKILL>/helpers/make-index.py"`
   refreshes `references/library.md`.

Without that skill or the MCP, hand the user the three files and the search to bind.

## Library choice

Start from a library chart: the "Start here" table at the top of `references/examples.md`
maps shapes (animated drill, map zoom, flow, KPI variants, what-if, beeswarm ...) to a
proven chart under `library/`. Copy its technique; keep the shared core. Otherwise,
Muze by default, and pick by what the chart is — `references/examples.md` has a working
file for each of these rows:

- **Muze** — bar, line, area, scatter, bubble, box, waterfall, pie, heatmap,
  dual-axis, data-bound KPIs. Anything wanting axes, legends, color encodings, or
  tooltips wired to a DataModel.
- **Chart.js** (CDN) — radar, polar, doughnut, sankey, gauges, bespoke smoothing,
  conditional bar coloring, background bands.
- **D3** (CDN) — stream graphs, force layouts (beeswarm), parallel coordinates, chord; anything with a bespoke layout.
- **ECharts** (CDN) — sankey and dense flow diagrams.
- **Plotly** (CDN) — **sunburst**, treemap, icicle. Anything hierarchical where a
  parent's arc must equal the sum of its children (`branchvalues: 'total'`) and
  clicking a wedge should zoom. Do not hand-roll this on Chart.js doughnuts.
- **gridjs** (CDN) — sortable tables. Unwrap object cells first or its Preact renderer
  dies with an opaque error.
- **Hand-built HTML table** — pivots and crosstabs, print-oriented output.
- **Raw SVG / Canvas** — single-stat KPI tiles that are mostly typography.
- **Raw HTML/CSS** — quote cards, text slides, annotation blocks.

**When the doctor reports `cdn: blocked`** (usual in the Claude app), the CDN libraries
cannot load in the preview, so a Chart.js / Plotly / gridjs chart cannot be verified
there. Prefer Muze (vendored), a hand-built table, or raw SVG when they fit. When only
a CDN library fits, write it anyway and tell the user it is **not previewed** — never
report MATCH on a render that could not load its library.

CDN loading works in BYOC: a `<script src>` in `chart.html`, or `document.createElement('script')` + a bounded promise (the shared core's `AZ.loadScript` is that, with a timeout and a fallback host). **Verified in a real cluster: `<script src>` from cdn.jsdelivr.net and unpkg loads (d3, echarts, topojson-client), but `fetch()` to any external URL is blocked** ("Network requests are blocked for security"). Data files, GeoJSON and topologies must be inlined in `chart.js`; `library/_shared/us-states.js` is an inline US map for that reason.

If the request matches none of these and no close analogue exists, say so before
writing code and offer two or three concrete paths. A confident wrong chart costs more
than an honest question.

## What not to do

- Do not regenerate `sample-data.json` mid-loop.
- Do not skip step 6 because the chart looked right.
- Do not report MATCH off the screenshot alone when the diagnostic block shows console
  errors.
- Do not leave the preview daemon running.
- Do not run `playwright install` in the Claude app, and do not rely on a background
  process surviving there — `snap.mjs` needs neither.
- Do not claim a chart is verified against ThoughtSpot unless it has been screenshotted there (`helpers/cluster-shot.mjs`, Step 9). Otherwise it is verified against a faithful stub; the Muze build, theme and network rules differ. Say "verified in preview".
- Do not ship a chart nothing reacts to, or one that invents rows when the search returns none.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.1.0 | 2026-09-29 | Step 0 adds an intake after the doctor: it checks the ThoughtSpot MCP and shows what is missing, then asks the model, data mode, search, library and destination as pick-from-a-list questions built from the org. New Step 9 saves the chart as a ThoughtSpot answer (`helpers/answer-pack.mjs` and `answer-patch.js`: checksum, validate and commit in one paste, round-trip) and screenshots it in a logged-in browser with `helpers/cluster-shot.mjs`, which moved here from the Liveboard skill. Library grown to 58 charts (a Muze state scatter, and four rebuilt from the older examples, marked preview only). Muze point marks render at half opacity (hard-rules); notes on model lookup, the cluster host and zsh loops. Verified end to end on ps-internal |
| 1.0.0 | 2026-09-29 | Initial release in this library (ported from thoughtspot-amuzing-chart 1.4.1). Builds a ThoughtSpot custom chart (BYOC) as paste-ready chart.html / chart.css / chart.js by iterating in a real browser against a faithful `viz` stub, screenshotting and critiquing each attempt. Ships a library of 53 live-data charts with a shared core, and hands finished tiles to `ts-custom-charts-liveboard-builder`. |
