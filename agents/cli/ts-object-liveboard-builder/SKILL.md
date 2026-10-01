---
name: ts-object-liveboard-builder
description: Build or rebuild a whole ThoughtSpot Liveboard made of custom charts (BYOC / Muze Studio tiles) that tells one story across numbered tabs, on a real model, through the ThoughtSpot MCP. Starts with an intake that checks the prerequisites and asks the model, Liveboard, story, audience, size, filters and sign-in as pick-from-a-list questions. Profiles the model, plans the tabs and the question each answers, has each tile built with the ts-object-answer-chart-builder skill against real search results, writes the narrative tiles (About, tab banners), adds Liveboard filters, imports the Liveboard (validate, then commit, then a round-trip proof), and screenshots every tab in a logged-in browser. Use when the user wants a storytelling or demo Liveboard of custom charts, wants tiles added to or rearranged on such a Liveboard, or wants the Amuzing chart samples Liveboard rebuilt. Needs the ts-object-answer-chart-builder skill installed alongside and the ThoughtSpot MCP (execute-thoughtspot-code). Not for a single chart (use ts-object-answer-chart-builder) or for Liveboards of native ThoughtSpot charts.
---

# ThoughtSpot custom charts Liveboard builder

You turn a model into a Liveboard that reads as one argument, every tile a custom chart that reads
live data. You never start building from guesses: Step 0 checks the prerequisites and asks the user
what to build, with choices to pick from. The charts themselves are made by the sibling skill **ts-object-answer-chart-builder** (its
`SKILL.md`, `references/library-contract.md` and `library/`); this skill owns everything above the tile:
the story, the tabs, the layout, the narrative tiles, the filters, the import and the in-cluster check.

`<L>` is this skill's folder, `<C>` the chart skill's folder (a sibling; the scripts find it, or set
`TS_ANSWER_CHART_SKILL`). The worked example is `<L>/liveboards/amuzing-chart-samples/`: 50 tiles in
7 tabs on **(Sample) Retail - Apparel**, live as the Liveboard *Amuzing chart samples*.

`<W>` is the working folder of the Liveboard you build: `~/.cache/ts-charts/liveboards/<name>/` (or under
`$XDG_CACHE_HOME`). It holds the profile findings, the spec with real guids and the narrative configs, so it
lives outside any repo; never create Liveboard folders inside `<L>`. Charts you publish go to the user's
library, `~/.cache/ts-charts/library/<slug>/`, which the scripts read before `<C>/library/`.

Use ThoughtSpot's words: **Liveboard**, tile, tab, filter, model, search. Not "board" or "dashboard".

## Route first

Every route starts with Step 0. The intake answers pick the route.

| The user wants | Do |
|---|---|
| A new storytelling Liveboard on a model | Steps 0 to 8 |
| More tiles, or changed tiles, on an existing one | Step 0, Step 4 for the new tiles, then Steps 6 to 8 |
| A rearranged Liveboard (tabs, sizes, filters) | Step 0, edit the spec (Step 5), then Steps 6 to 8 |
| One chart, no Liveboard | Stop: that is `ts-object-answer-chart-builder` |

## Step 0 - intake: check the prerequisites, then ask

Do this before any profiling or planning. Nothing is built from guesses.

**0a. Check, do not ask.** Read `references/pipeline.md` once (the sandbox limits that shape every
step), then run these checks:

- The ThoughtSpot MCP tool `execute-thoughtspot-code` is connected. One read-only call returns the
  signed-in user, the org, the models (search the metadata for logical tables that are models or
  worksheets) and the Liveboards the user can edit. The token is bound to one org, and an org switch
  returns 403 (10088), so the org you get is the org you work in.
- The chart skill is installed next to this one. Run its doctor (`node <C>/helpers/env.mjs`) for the
  browser (headed, headless or none) and CDN reach. The screenshot step uses its Playwright and
  Chromium.

Show the user one short block: the org and user, whether the chart skill was found, the browser mode,
and anything missing with its fix. If the MCP is missing or the chart skill is not found, stop there:
say what to connect or install, and do not ask the questions below.

**0b. Ask with choices.** Use the `AskUserQuestion` tool so the user picks from options instead of
typing. It takes up to 4 questions per call and 2 to 4 options per question, and it adds "Other" for
free text on its own. Build the options from what 0a found, never from placeholders. Put the likely
pick first and add "(Recommended)" to its label.

Round 1:

| Header | Question | Options |
|---|---|---|
| Model | Which model should the Liveboard read? | Up to 4 models from 0a, the most likely first (for example the one the user named) |
| Liveboard | Create a new Liveboard or update one? | "Create a new one" plus up to 3 of the user's Liveboards that already hold custom-chart tiles |
| Story | What should the Liveboard answer? | "Let the data decide (Recommended)", "Performance and targets", "Trends and seasonality", "Where and who: regions, segments, products" |
| Audience | Who will read it? | "Executives", "Analysts", "Customer demo", "Internal team" |

Round 2, after a quick column list of the chosen model (Step 1 has not run yet). The metadata search
with `identifier: '<model guid>'` and `include_details: true` returns `metadata_detail.columns`; search
models by `name_pattern`, because an unfiltered listing of an org's logical tables is cut off:

| Header | Question | Options |
|---|---|---|
| Size | How big should it be? | "Pilot: About plus one tab, about 6 tiles", "Compact: 3 to 4 tabs, about 20 tiles", "Standard: 5 to 7 tabs, about 40 tiles (Recommended)", "Full: 8 or more tabs". A pilot is the cheap way to prove the pipeline on a new model or cluster before the full build |
| Filters | Which columns should the Liveboard filter on? (`multiSelect: true`) | Up to 4 attribute columns that fit filtering: a date, a region, a category, a segment |
| Charts | Anything the charts must include or avoid? | "No preference (Recommended)", "Maps where the data has places", "KPIs and tables first", "Only reuse library charts" |
| Check | The last step screenshots every tab in ThoughtSpot, which needs one SSO sign-in in a browser window. How should it go? | "Sign in for this run, sign out at the end (Recommended)", "Sign in and stay signed in on this cluster for later runs", "Skip the screenshots, report the tabs as unverified" |

If 0a found no browser (usual in the Claude app), drop the sign-in option from **Check** and say the
screenshots cannot run here. For an existing Liveboard, skip **Size** and ask what should change:
"Add tiles", "Change tiles", "Rearrange tabs or filters".

If `AskUserQuestion` is not available, ask the same questions in one message as a numbered list with
lettered options, and wait for the answers.

Write the answers at the top of `<W>/README.md`. Steps 1, 2, 3 and 7 follow them.

## Step 1 - profile the model (MCP)

Profile the model chosen in Step 0. List its columns and run a few `searchdata` queries: row counts per attribute,
the date range and grain, totals by year and month, the top and bottom of each attribute. Look for the
**story**: steps, trends, concentration, seasonality, what is flat. Write down what the data cannot
support (no cost column means no margin talk). Note data-quality traps (partial first and last periods,
wrong coordinates, renamed columns). Put the findings in `<W>/README.md`; the
example's (`<L>/liveboards/amuzing-chart-samples/README.md`) is the template.

## Step 2 - plan the story and tabs

Follow `references/story-and-layout.md`: numbered, plain tab names, one question per tab, an About tab
first and an action tab last, a banner on every tab, 4 to 10 tiles per tab, a hero per tab, KPI variety,
drill-downs where the data has a hierarchy. Choose each tile's chart shape from the chart skill's
"Start here" table (`<C>/references/examples.md`) and `library.md`. Shape it to the Step 0 answers:
the story and audience set the tab questions, the size sets the tab count, and the chosen filter
columns become the Liveboard filters. If the profile shows the data cannot support a choice (for
example no date column for "Trends and seasonality"), say so in the plan. Show the user the plan
(tabs, tiles, searches), then ask with `AskUserQuestion`: "Build this plan (Recommended)", "Change the
tabs", "Change the tiles". Do not build until it is approved, because building is the expensive part.

## Step 3 - set up the Liveboard

Use the Liveboard chosen in Step 0. For "Create a new one", create an empty Liveboard now, named with
the user's approval. Its guid goes in the spec, and every import updates it in place. One import makes it,
with the tabs already named:

```js
const tml = { liveboard: { name: '<name>', description: '<one line>', visualizations: [],
  layout: { tabs: [{ name: '01 About', tiles: [] }, { name: '02 Where', tiles: [] }] } } };
const r = await ts.post('/api/rest/2.0/metadata/tml/import', { metadata_tmls: [JSON.stringify(tml)], import_policy: 'ALL_OR_NONE', create_new: true });
return r.body[0].response.header.id_guid;   // confirm_write_operations: true
```

## Step 4 - build the tiles

Each tile is a library chart (the user's library, or `<C>/library/<slug>/`), built by the chart skill's procedure with a **real-data
fixture** (the tile's exact search through `searchdata`) and the library contract. Reuse a library chart
when one fits (change its search and copy; keep the slug if it is the same chart). For many tiles,
brief parallel subagents, one tab each, with `references/tile-brief.md`.

Narrative tiles (About hero, guide, tab banners) are not hand-built: write one
`<W>/narratives/<slug>.cfg.js` per tile (copy the example's), then
`node <L>/scripts/build-narratives.mjs --liveboard <W>`. Their copy is computed from
the rows, so it follows the filters. Narratives land in the user's library by slug, so give each
Liveboard its own (`<liveboard>-banner-where`, not `banner-where`): the builder records the owner in
`<slug>/.narrative` and refuses a slug another Liveboard owns, in either library.

## Step 5 - the spec

Copy `<L>/liveboards/amuzing-chart-samples/make-spec.py` to `<W>`, edit the tile table
(slug, title, search, x, y, w, h, description, whether filters apply) and the filters, and run it with the
guids in the environment: `LIVEBOARD_GUID=<guid> MODEL_GUID=<guid> SPEC_OUT=<W> python3 <W>/make-spec.py`.
It writes `<W>/liveboard.spec.json`. Rows of each tab must fill 12 columns without overlap. (Run in
the example folder without `SPEC_OUT`, it writes the real-guid spec to
`~/.cache/ts-charts/liveboards/amuzing-chart-samples/`, never over the tracked example.)

## Step 6 - write the tiles into the Liveboard (MCP)

The Liveboard is its own store. Nothing else is created in ThoughtSpot: no helper Liveboards, no answers.

```bash
node <L>/scripts/liveboard-pack.mjs --liveboard <dir> --commit <slug> ... > <scratch>/p.js      # or --all
node <L>/scripts/liveboard-pack.mjs --liveboard <dir> --commit --reuse <other liveboard guid> <slug> ... > <scratch>/r.js
node <L>/scripts/liveboard-pack.mjs --liveboard <dir> --list --all                              # sizes, before anything
```

**Reuse before you paste.** A library chart already on another Liveboard in the same cluster (the
worked example holds 50) need not travel through your context: `--reuse <guid>` sends only its
checksums, and the sandbox copies it from that Liveboard, found by slug marker or, for older tiles, by
title, only when its body matches the library. Anything it cannot copy comes back under `needCode`; send
those without `--reuse`. A block with nothing to write is skipped, not committed. In the pilot this cut a
77 KB block (the state map inlines US outlines) to 27 KB. `--reuse <this Liveboard's guid> --all` stamps slug
markers on tiles imported before markers existed (matched by grid position), without sending any chart code.

**The core and the spec.** `--core-ref` sends the shared core as a checksum; the sandbox takes it from a tile
already on the Liveboard (blocks after the first in a run do this by themselves). Every block also carries a
checksum of the spec, because the spec sets every title, search and position: a slip in it is refused like a
slip in chart code.

Each block carries some charts (up to `--max`, default 60,000 characters), the spec and the shared core.
In the sandbox (`<L>/scripts/patch.js`) it checks every sha256, exports the Liveboard and **merges** into
that export.

**What the skill owns.** A tile is the skill's only when its code carries the owner marker
`/* ts-lb-owner: <this Liveboard's guid> */`, which the skill writes into every tile it composes. Those
tiles are replaced when their chart is in the block, keep their code otherwise, and are removed when the
spec no longer places them. Nothing else is touched: native charts, notes, custom charts it did not build
(a chart pinned from an answer carries the shared core but no marker), tiles copied from another
Liveboard (their marker names that one), a user's copy of a skill tile (two tiles marked with one slug:
the one at the spec position is the skill's), tabs the spec does not name, parameters, style, and the
Liveboard's own name and description. A filter the Liveboard already has on a spec column stays the
user's (values, label, mandatory, its exclusions); the spec only decides which of the skill's tiles it
skips. If the skill's tiles would overlap the user's own on a shared tab, the user's move below them.

**Tiles from before owner markers** (the shared core and a spec slug, or at a spec position, with no
marker) stop the commit and are listed under `problems`. If they are the skill's, build the block again
with `--adopt`, which takes them over and marks them (listed under `marked`); otherwise move them off
the spec positions.

**A commit writes only a clean state.** Any problem refuses it and leaves the Liveboard unchanged: a failed
search (the tile it would have rebuilt stays as it is), a spec tile with no code (`MISSING`), an ownership
conflict, tiles to adopt, a Liveboard laid out without tabs (refused before anything is composed: add a
tab in ThoughtSpot first, or build on a new Liveboard). Tiles that later blocks of the same run will
send are `pending`, not problems.

**Backup.** When the Liveboard holds anything the skill does not own, the sandbox refuses the commit unless
the block was built with `--backup <file>`: a TML export of this Liveboard taken before the commit, from
`ts tml export <guid> --profile <name> > ~/.cache/ts-charts/backups/<guid>-<date>.json` when a `ts`
profile is set up, or the Liveboard's **Export TML** menu item otherwise. `liveboard-pack.mjs` checks the
file names the Liveboard's guid, is under a day old and sits outside any git working tree. Tell the user
where it is; restore by importing it (`ts tml import`, or **Import TML** in ThoughtSpot). A Liveboard the
skill created and fills with its own tiles needs none.

After a commit the block exports the Liveboard again and proves: every composed tile carries the code
that was composed, every visualization the skill did not own before the patch is still there (matched by
title, chart type and search, so a loss shows even when the count is right), and every tab holds the tiles
it was given. `--commit` requires `--liveboard <dir>` and a spec with real guids, so it never falls back
to the worked example.

Read the file and paste **each block between the `=====` lines
unchanged** as the `code` of `execute-thoughtspot-code` with `confirm_write_operations: true`, in order.
Every block leaves a complete, working Liveboard, so a build can stop between blocks.

1. `--commit` runs a `VALIDATE_ONLY` import first and commits only if it passes, so each block is pasted
   once. `--validate` alone checks without writing.
2. Success is `validate.status_code: OK`, `import.status_code: OK`, `roundTripAllOk: true`, `problems: []`,
   and the slugs you meant in `replaced`. `refused: NOT COMMITTED ...` means nothing was written: fix what it
   names and send the block again. `kept` counts the visualizations the skill does not own; `removed`,
   `marked`, `droppedTabs` and `shiftedBelowCharts` list anything else it changed: tell the user.
   `roundTripLost`, `roundTripLayout` or `roundTripFailed` after a commit mean the import changed more than
   was composed: restore from the backup and tell the user. On a first build, tiles still to come in later blocks are listed
   under `pending`, not `problems`. `CHECKSUM MISMATCH` means the paste was altered: resend the block.
3. Send only what changed. A new Liveboard needs every tile once (`--all`, several blocks).

**Before and after, check for drift:** `node <L>/scripts/liveboard-pack.mjs --liveboard <dir> --check`
prints one read-only block that compares every tile on the Liveboard with the library. Expect
`stale: []` and `missing: []`. A chart edited in the library but never sent keeps its **old** code on the
Liveboard with no error anywhere (this is how the Plotly sunburst stayed an ECharts one for a whole round).

## Step 7 - look at it in the cluster

The Liveboard URL is `https://<cluster host>/#/pinboard/<guid>`; the host comes from Step 0 (see the chart
skill's Step 9 for where to find it).

```bash
node <L>/scripts/cluster-shot.mjs --url "<liveboard url>" --tabs "01 About,02 Pulse,..." --wait 10
node <L>/scripts/cluster-shot.mjs --url "<liveboard url>" --tabs "03 Where" --filter "Region=West" --out <dir>
```

If the user chose to skip the screenshots in Step 0, do not run this step. Mark every tab as
unverified in the report. Otherwise a headed Chromium opens with a sign-in profile of its own for this
cluster (`~/.cache/ts-charts/cluster-profiles/<host>`, readable only by the user). The first time, the user
signs in (SSO) in that window, so remind them right before you run it. It scrolls each tab, saves `<tab>-N.png`, and lists tiles
showing failure text. **Read every PNG**: blank or clipped tiles, overlapping text, a tooltip stuck on,
colours that break the rules, copy that reads wrong. The filtered run proves tiles survive filters. Fix
in the chart skill, then send just that chart (`--commit <slug>`).

## Step 8 - sign out and report

Unless the user chose to stay signed in, remove the saved session, which is a credential and does not
outlive the run: `node <L>/scripts/cluster-shot.mjs --logout "<liveboard url>"` (or `--logout all`).


Tabs and tile counts, the round-trip result, the drift check, which screenshots you read and what you
fixed, and anything not verified (interactions and motion are only seen as still frames).
Update the example's README when the story changes.

## What not to do

- Do not send a whole Liveboard's TML from your context; it is megabytes of base64. Patch it in blocks.
- Do not create helper objects (stores, scratch Liveboards, answers) in the user's ThoughtSpot. If a task
  ever needs one, name it in the plan, get a yes, and delete it before you finish.
- Do not commit without a validate: `--commit` does it in the same call; never import with `ALL_OR_NONE` by hand.
- Do not claim a tile works in ThoughtSpot until its tab has been screenshotted and the PNG read.
- Do not put a native ThoughtSpot chart on these Liveboards, or sample rows in a chart.
- No emojis, em-dashes or stock phrasing anywhere, including tab names and banners
  (`<C>/references/taste-rules.md`).

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-09-30 | Initial release (ported from thoughtspot-amuzing-liveboard 2.0.0). Builds a storytelling Liveboard of custom-chart tiles across numbered tabs on a real model through the ThoughtSpot MCP. Step 0 checks the prerequisites and asks the model, Liveboard, story, audience, size (including a pilot), filters and sign-in as pick-from-a-list questions. Plans tabs, has tiles built by `ts-object-answer-chart-builder`, writes narrative tiles, adds filters, and patches the Liveboard in checksummed blocks (validate then commit in one paste, `--reuse` and `--core-ref` to avoid re-pasting charts). A patch merges into the exported Liveboard and changes only the tiles carrying its owner marker for that Liveboard (`--adopt` takes over older tiles); any problem refuses the commit, content the skill does not own is written only with a checked `--backup`, and the round trip proves nothing it does not own was lost. Working folders, specs with real guids and published charts live under `~/.cache/ts-charts`; `--commit` requires `--liveboard` and real guids. Screenshots every tab with a per-cluster sign-in profile that is removed at the end unless the user keeps it |
