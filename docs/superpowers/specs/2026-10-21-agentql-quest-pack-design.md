# Design: quest packs and an explorable AgentQL Quest

_Separate the game's content from its front ends, so that (1) AgentQL Quest can be played as an
explorable map, where you walk a realm and its characters ask the questions, and (2) a second game
on another topic can reuse the engine by adding a content folder._

Status: **proposal / for review** · Date: 2026-10-21 · Builds on: AgentQL Quest
([`tools/agentql-quest/`](../../../tools/agentql-quest/), #622) and its data contract
`quest.json` / `quest.schema.json` (#632)

---

## 1. Where we are

AgentQL Quest is one self-contained page. `build.py` compiles `encounters.yaml` with the lesson
capture (`lesson-sql.md`) and the course (`learning-path.md`), checks it, and writes:

- `quest.json`, the checked game data, described by `quest.schema.json` (version 1). The PR gate
  enforces it, and CI checks it again with a real JSON Schema validator.
- `index.html`, the text adventure (`game.html` with the data and fonts inlined).

The **data** is already separate. Three other things are not:

| Tied to AgentQL today | Where |
|---|---|
| Checks against the capture and the course: `case` ids, AgentQL equal to the capture, SQL highlights matched as whole lines, `sql_count` / `sql_before` / `rejected_case`, lesson numbers and titles, the Model in the header | `build.py` (`_encounter`, `_point`, `check_course_refs`, `parse_*`) |
| The game's vocabulary and rules: three engines, "the dragon is the AgentQL path", the who-put-it-there options (Forge / scroll / Wizard), rule tags (MODEL / THOUGHTSPOT / …) | `build.py` (`WHO_*`, `RULE_BY`, `_path`) and `encounters.yaml` (`who_options`, `engines`) |
| The story and look: the Wizard, the Forge, the dragon, the hoard, the determinism verdict, the legend and rule cards, every ASCII scene | `game.html` (`ART`, `SCENES`, `DETERMINISM`, `LEGEND`, `RULE`, the screen functions) |

The compiled data is mostly general already. A point is `ask / hint / options / correct`, a
hall question is `text / why / options / correct`. Two exceptions: the point highlights are named
for AgentQL (`sqlHl`, `scrollHl`), and each encounter carries exactly two code panes (`agentql`,
`sql`).

## 2. Goals and non-goals

**Goals**
- A **quest pack** format: one folder holds a game's content, words, art and (optionally) maps.
  The engine and its front ends contain no AgentQL wording.
- An **explorable front end** for AgentQL Quest, built on existing libraries, that plays the same
  checked content as the text game.
- Designed so a **second game** needs only a new pack. That game is not built here.
- Keep what works: content edited only in YAML, the PR gate, the captured-SQL drift checks, the
  headless play-through tests, Pages hosting, no outside requests.

**Non-goals**
- A level editor in the browser, multiplayer, or a shared leaderboard (Pages serves files only).
- Replacing the text game. It stays, as **classic mode**, which is also the accessible way to
  play.
- Analytics. That's still an open question from the launch, and separate from this design.

## 3. The quest pack

### 3.1 Layout

```
tools/quest/                          the engine (renamed from tools/agentql-quest/, see §7)
  build.py                            core compile + checks, plugin loader
  checks/agentql_capture.py           plugin: case ids, capture drift, Model header
  checks/course_refs.py               plugin: lesson numbers and titles in learning-path.md
  quest.schema.json                   the compiled contract (version 2)
  classic/                            the text-adventure front end (today's game.html)
  explore/                            the map front end (new)
  core/                               shared front-end code: state, scoring, saves, sound, question panel
  vendor/phaser-4.2.1/                pinned, with its MIT licence
packs/
  agentql/                            AgentQL Quest's pack
    pack.yaml                         manifest
    content.yaml                      today's encounters.yaml
    strings.yaml                      every sentence the front ends show that isn't content
    art/classic/*.txt                 the ASCII scenes
    maps/*.tmj                        Tiled maps, one per realm, plus the overworld (explore only)
    tiles/                            the tileset (a Kenney 1-Bit Pack subset, CC0 note)
```

### 3.2 The manifest

```yaml
# packs/agentql/pack.yaml
id: agentql
title: AgentQL Quest
publish_path: agentql-quest            # the Pages folder, so the live URL never changes
checks: [agentql_capture, course_refs] # plugins this pack turns on; a new game may use none
sources:                               # read-only inputs the plugins check against
  lesson_sql: agents/cli/ts-object-model-agentql-query/references/lesson-sql.md
  learning_path: agents/cli/ts-object-model-agentql-query/references/learning-path.md
lexicon:                               # the roles the engine knows, named the pack's way
  guide: The Wizard                    # writes the scroll (the AI)
  compiler: The Forge                  # turns it into what runs (ThoughtSpot + the Model)
  foe: dragon
  reward: hoard
  currency: gold
front_ends: [classic, explore]         # explore needs maps/; a pack without maps is classic only
```

`strings.yaml` holds what `game.html` hard-codes today: the title blurb, the legend, the rule
card, the determinism verdict, button labels and the course links. The engine looks strings up
by key, so a second game changes its words without touching code.

### 3.3 Core content model and plugins

The core compiler knows only general things: realms (order, sealing, minutes), halls (teach,
table slice, trials), encounters (a question, a path choice, **panes**, points, a takeaway),
routes and scoring. A plugin may:

- **resolve** fields from an outside source. `agentql_capture` turns `case: l3_…` into the two
  panes from `lesson-sql.md`.
- **check** content and add errors. Every check that exists today moves into a plugin without
  changing its behaviour.
- **declare** what it adds to the content YAML, so the core rejects keys no plugin claims.

Panes become a list, and highlights refer to panes by id. That is the one schema change, and it
moves `quest.json` to **version 2**:

```jsonc
// an encounter in quest.json v2
"panes": [
  {"id": "scroll", "label": "YOUR SCROLL: the AgentQL the AI wrote", "lines": ["SELECT …"]},
  {"id": "dragon", "label": "THE DRAGON: SQL ThoughtSpot generated", "lines": ["SELECT …"],
   "caption": "Captured from generate-sql on (Sample) Retail - Apparel, 2026-10-20."}
],
"points": [{"ask": "…", "options": ["…"], "correct": 0, "highlights": {"dragon": [12], "scroll": []}, …}]
```

A second game might have one pane (a formula), or none (a pure quiz). Version 1 stays published
until classic mode reads version 2, then it is removed in the same PR.

### 3.4 What carries over unchanged

The content rules this game already follows go into the pack's `README`, and the checks keep
enforcing them:
- generic fantasy names only;
- planned capabilities described as *coming soon*, never as shipped;
- null guards and the row cap credited to ThoughtSpot, not the Model;
- every lesson claim true of the captured SQL.

## 4. The explorable front end

### 4.1 Libraries

| Need | Choice | Why |
|---|---|---|
| Engine | **Phaser 4.2.1** (MIT), the arcade-physics build (~1.27 MB minified) | The current stable major (4.0 shipped April 2026). It has walking, collision, cameras, input, sound and **Tiled map loading** built in, plus the most examples. It's vendored and pinned, so the page makes no outside requests. |
| Maps | **Tiled** (desktop editor), saved as `.tmj` JSON with embedded tilesets | Realms are drawn visually. Characters, doors and chests are objects on an object layer. Phaser reads the file directly. |
| Art | **Kenney 1-Bit Pack** (CC0, 1,000+ tiles, characters and items) | Monochrome, so tinting it amber matches the CRT look of the video. CC0 means no attribution or licence risk in a public repo. Only the tiles used are committed. |
| Dialogue | Not needed: questions come from `quest.json` | Ink or similar only if characters later need branching conversation. |

Rejected: KAPLAY (thinner for a game with several maps), RPG JS (smaller community), Godot (tens
of MB on the web, harder in CI), RPG Maker (commercial licence).

### 4.2 Binding maps to content

Every interactive object on a map names **what it starts**. The engine looks it up in
`quest.json` and the build checks the link:

| Object `type` | Properties | Starts |
|---|---|---|
| `merchant` | `encounter` | the business question and the "read the intent" path choice |
| `guide` | `encounter` | the Wizard writing the AgentQL (scroll pane) |
| `compiler` | `encounter` | the Forge: the SQL pane appears and the foe wakes |
| `foe` | `encounter` | the scales, one question each, in order |
| `reward` | `encounter` | the hoard (rules uncovered) and the realm's end |
| `throne` | `hall` (index) | a hall's teaching, then its trials |
| `gate` | `requires` (step ids) | blocks the way until those steps are done |
| `exit` | `to` (map id) | back to the overworld |

**Build checks** (new, in the core, so every pack gets them):
- every object refers to content that exists;
- every encounter step and hall is reachable from some object;
- `gate.requires` names real steps, and the order works: you can't meet the foe before the
  compiler;
- every map has an `exit` and a player spawn;
- tilesets are embedded, no external file references.

Positions are never checked, only ids, so a map can be redrawn freely.

### 4.3 How a realm plays

Dwarven Mines, about 2–3 minutes:

1. You enter at the mine mouth. A **merchant** asks the business question and offers the three
   engines. The keyword path is blocked in this realm, as today: choosing it explains why and
   costs nothing.
2. Deeper in, the **Wizard** writes the scroll (the AgentQL pane), and a gate opens.
3. You carry it to the **Forge** at the end of the tunnel. The SQL pane appears and the
   **dragon** wakes.
4. Each **scale** is a question: one line of SQL is highlighted, and you choose who put it there.
   A right answer breaks a scale and plays the effect.
5. The **hoard** chest lists the rules uncovered (MODEL / THOUGHTSPOT tags, your part), then the
   exit.

The Kingdom of Law is four rooms, one per hall. A throne asks each hall's trials, and the decree
waits at the gate. The overworld is a small map with the five realm entrances. Sealed realms
show a closed gate, and finished realms show your best gold.

### 4.4 Questions as HTML over the game

When you interact, the scene pauses and an HTML `<dialog>` opens over the canvas. It reuses the
question rendering from `core/`, the same code classic mode uses: panes with highlights, options,
**Invoke magic**, feedback, gold. This:
- keeps questions accessible: real buttons, focus management, a live region for results,
  screen-reader text;
- keeps one implementation of scoring and the answer rules for both front ends;
- keeps the canvas purely for moving around.

### 4.5 Controls, sound, saves

- **Keyboard:** arrows or WASD to move; Enter or Space to interact; S and M toggle sound, as
  today.
- **Touch:** an on-screen d-pad and an interact button; tap the dialog's options directly.
- **Reduced motion:** with `prefers-reduced-motion`, no screen shake and instant camera moves.
- **Sound:** the existing Web Audio module moves to `core/`, unchanged: no files, nothing before
  the first input.
- **Saves:** the same `aqq-progress` store and caps, so best scores carry between classic and
  explore.
- **Classic mode:** always one link away, from the title screen and the pause menu.

### 4.6 Hosting and budget

- **Classic mode stays the default** at `/agentql-quest/` (one self-contained file).
- **The explorable game is published at `/agentql-quest/explore/`** as several files: page, JS,
  Phaser, maps, tiles and `quest.json` (fetched from `../quest.json`).
- **No outside requests.**
- **Budget:** 3 MB for the explore folder; Phaser takes about 1.3 MB of that.
- **Workflow:** `pages.yml` gains one build step and the explore folder's path trigger. It stays
  main-only.

## 5. Testing

The model so far: Python gate checks, plus a headless play-through that drives the real page in
node. To keep that working without a browser:

- **Logic out of the scenes.** A pure `core/` state machine handles realm progress, step order,
  scoring and saves. Phaser scenes only move sprites and call `core.interact(objectId)`.
- **Map play-through (node).** Read each `.tmj`, build the object graph, and "walk" it by
  calling `core.interact` in an order the gates allow. Answer every question right, wrong-then-right
  and with magic, as `play_quest.js` does today. This proves every encounter is reachable and
  finishable from the maps, with no canvas.
- **Map checks (Python, the gate).** Run the §4.2 checks in `build.py --check`, with tests that
  break each one deliberately.
- **Classic mode** keeps its existing tests. It moves onto `core/` too, so both front ends share
  the scoring tests.
- **Rendering.** For the prototype, a short manual checklist (below). A headless-browser smoke
  test (Playwright) would add a large CI dependency, so it's decided after the prototype: §8,
  decision 3.

## 6. Prototype: the Dwarven Mines only

**Scope:**
- the pack layout with the AgentQL pack;
- `quest.json` v2;
- the core, with classic mode moved onto it;
- one explore map (the Mines) plus a stub overworld with one open entrance;
- published at `/agentql-quest/explore/`.

**Done when:**
- The Mines can be played start to finish with the keyboard alone, and with touch alone, in
  2–4 minutes.
- Scores match classic mode for the same answers, and the best score shows in both.
- The node map play-through and all existing tests pass; the gate fails on each broken map
  check.
- There are no outside requests, the folder is under 3 MB, and the questions pass a screen-reader
  pass (VoiceOver: each dialog announces, focus starts on the question, results are read).
- Manual checklist: Chrome, Safari and Firefox on desktop; Safari on iPhone; and reduced motion.

**Then:** you play it and decide whether to finish the remaining realms (§8, decision 1).

**Order of PRs** (each small, gated and reviewed):
1. Engine and pack split: move files, add plugins, `quest.json` v2, classic on `core/`. Nothing
   changes for players. Old paths are removed in the same PR, nothing kept "just in case".
2. Map binding: the §4.2 build checks and the node map play-through, with a tiny test map.
3. Explore front end: Phaser vendored, the Mines map and tiles, the dialog, controls, the Pages
   step.

## 7. A second game

To add a game: create `packs/<id>/` with `pack.yaml`, `content.yaml` and `strings.yaml`, plus
maps if it should be explorable. It uses no plugins, or new ones of its own. Each pack is built
to its own `publish_path` and listed on the site's home page.

The engine is renamed `tools/quest/` in PR 1 because the name `agentql-quest` would mislead once
it serves other games. The public URL stays `/agentql-quest/`, set by the pack's
`publish_path`.

What a second game must still check for itself: its own sources of truth. A plugin is the place
for that, the way `agentql_capture` pins this game to the captured SQL.

## 8. Decisions for you

1. **After the prototype, should explore replace classic as the default** at `/agentql-quest/`,
   or sit beside it? **Recommended:** beside it until all five realms are explorable, then make
   explore the default with classic linked.
2. **The art:** Kenney 1-Bit tinted amber (fast, CC0), or commission custom pixel art later?
   **Recommended:** Kenney for the prototype; revisit only if it feels generic.
3. **A browser smoke test in CI** (Playwright, roughly 150 MB of browsers) or a manual checklist
   per release? **Recommended:** a manual checklist until explore becomes the default.
4. **The engine rename** (`tools/agentql-quest/` → `tools/quest/`) now, or only when a second
   game exists? **Recommended:** now, in PR 1, while only one pack depends on it.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Walking adds time: the course is "about 15 minutes" | Small maps (one screen or two), and every question is reachable within 2–3 minutes per realm |
| Phaser 4 is new (April 2026) and its examples lag Phaser 3's | Use only basic features (tilemaps, arcade movement, cameras, input), and pin and vendor one version |
| A canvas game is harder to make accessible | All questions are HTML dialogs; classic mode is always one link away |
| Map edits silently break the course order | §4.2 build checks plus the node map play-through, in the PR gate |
| Vendored third-party code in a public repo | Pinned version, licence files kept, Snyk and the dependency review as today |
| Two front ends drift apart | One `core/` for state, scoring, saves, sound and the question panel; both front ends' tests run on it |
