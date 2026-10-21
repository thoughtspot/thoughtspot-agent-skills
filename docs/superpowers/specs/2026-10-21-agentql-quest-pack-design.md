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
- `index.html`, the text adventure (`game.html` with the data and fonts inlined). It runs from
  Pages, any static host, or a double-click.

The data is separate from the page, but it is **not** general. Everything below is specific to
AgentQL, and a second game must not need any of it.

**In the compiled data (`quest.json` v1):**

| Field | Why it's AgentQL's |
|---|---|
| top-level `captured`, `model` | the capture's date and Model (both required) |
| realm `module` (required integer) | the course module |
| encounter `case`, `lesson`; point `lesson` | `lesson-sql.md` case ids and `learning-path.md` lesson numbers |
| encounter `agentql`, `sql`; point `sqlHl`, `scrollHl` | exactly two code panes, named for AgentQL |
| point `ruleBy` ∈ `model / thoughtspot / agentql / determinism` | AgentQL's rule tags |
| trial kind `route` ("which engine") | AgentQL's three engines |
| option text written by `build.py`: "Send it to {engine}", "Heed them. It is true." / "Banish them. It is false." | wording in code, not content |
| the schema's title ("AgentQL Quest data") and `$id` under `/agentql-quest/` | one game's contract |

**In the build's rules (`build.py`):**
- every capture and course check: `case` ids; AgentQL equal to the capture; SQL highlights
  matched as whole lines; `sql_count`, `sql_before`, `sql_last_line`, `rejected_case`; lesson
  numbers and titles; the Model in the header and the `FROM` check;
- the game's rules:
  - the dragon's path must be `agentql`;
  - the who-put-it-there options and their mapping (`WHO_ORDER`, `WHO_ANSWERS`: model and
    thoughtspot both mean the Forge);
  - the rule tags (`RULE_BY`);
  - the first realm must be open and have halls.

**In the page (`game.html`):**
- the story and look:
  - the Wizard, the Forge, the dragon, the hoard;
  - the determinism verdict, the legend and the rule cards;
  - every ASCII scene and the realm map;
  - the pane labels and the capture caption;
- the rule that every realm waits until the first one is done;
- the save keys `aqq-progress` and `aqq-sound`.

How the page is built matters for the plan. It is one inline script with a global `state`.
`render()` builds `innerHTML`, and the state changes live in click handlers created while
rendering. Saves also happen during rendering: the decree and victory screens call
`finishRealm`. `tests/play_quest.js` runs that script in a node `vm` with a fake DOM, and drives
it with real clicks and key presses.

## 2. Goals and non-goals

**Goals**
- A **quest pack** format: one folder holds a game's content, words, art and (optionally) maps.
  The engine, its schema and its front ends contain no AgentQL wording or rules.
- An **explorable front end** for AgentQL Quest, built on existing libraries, that plays the same
  checked content as the text game.
- Designed so a **second game** needs only a new pack. That game is not built here.
- Keep what works:
  - content edited only in YAML;
  - the PR gate and the captured-SQL drift checks;
  - the headless play-through tests;
  - Pages hosting and no outside requests;
  - classic mode working from a double-click.

**Non-goals**
- A level editor in the browser, multiplayer, or a shared leaderboard (Pages serves files only).
- Replacing the text game. It stays, as **classic mode**, which is also the accessible way to
  play.
- Analytics. That's still an open question from the launch, and separate from this design.

## 3. The quest pack

### 3.1 Layout

Assuming decision 4 (§8): the engine moves to `tools/quest/`, with the packs inside it, so every
path trigger has one root.

```
tools/quest/
  build.py                     core compile and checks; loads the plugins a pack names
  checks/                      plugins: agentql_capture.py, course_refs.py, agentql_rules.py
  quest.schema.json            the compiled contract, version 2 (§3.4)
  core/                        shared front-end code, plain scripts (§3.6)
  classic/                     the text-adventure page (today's game.html, on core/)
  explore/                     the map front end (new)
  fonts/                       VT323 and IBM Plex Mono, with their OFL licences (moved)
  vendor/                      Phaser, pinned (§4.1, §9)
  tests/
  packs/
    agentql/                   AgentQL Quest's pack
      pack.yaml                the manifest
      content.yaml             today's encounters.yaml, with ids (§3.4)
      strings.yaml             every sentence a front end shows that isn't content
      art/classic/*.txt        the ASCII scenes
      maps/*.tmj               Tiled maps, one per explorable realm, plus the overworld
      tiles/                   a Kenney 1-Bit Pack subset (CC0 note)
      promo/                   the poster, the GIF and make_ad.py (moved)
```

If decision 4 is "later", the same layout sits under `tools/agentql-quest/`, and PR 1 (§6) is
skipped.

### 3.2 The manifest

```yaml
# tools/quest/packs/agentql/pack.yaml
id: agentql
title: AgentQL Quest
publish_path: agentql-quest            # the Pages folder: the live URL never changes
storage_key: aqq                       # saves are aqq-progress and aqq-sound, as today
unlock: first_realm_first              # every other realm waits for the first (today's rule)
checks: [agentql_capture, course_refs, agentql_rules]
sources:                               # read-only inputs the plugins check against
  lesson_sql: agents/cli/ts-object-model-agentql-query/references/lesson-sql.md
  learning_path: agents/cli/ts-object-model-agentql-query/references/learning-path.md
rule_tags: [model, thoughtspot, agentql, determinism]   # the hoard's tags; the core checks against this list
lexicon:                               # the roles the engine knows, named the pack's way
  guide: The Wizard                    # writes the scroll (the AI)
  compiler: The Forge                  # turns it into what runs (ThoughtSpot + the Model)
  foe: dragon
  reward: hoard
  currency: gold
explore:
  realms: [mines]                      # realms with a map; others are played in classic mode
```

- **Saves:** every pack is served from the same origin (`thoughtspot.github.io`), and saving
  rewrites the whole progress object. So each pack must have its own `storage_key`, or finishing
  one game would erase the other's saves. The build fails if two packs share a key.
- **Strings:** `strings.yaml` holds the title blurb, the legend, the rule card, the determinism
  verdict, button and option wording ("Send it to {engine}", the claim buttons), pane labels and
  captions (with `{model}` / `{captured}` filled from the plugin's metadata), and the course links.

### 3.3 Plugins

The core compiler knows only general things:
- realms: order, sealing, minutes, the unlock rule;
- halls: teach, table slice, trials of kind `claim` or `choice`;
- encounters: a question, a path choice, panes, points, a takeaway;
- rule tags from the manifest, routes, scoring and storage keys.

A plugin may:
- **resolve** fields from an outside source. `agentql_capture` takes `case: l3_…`, fills the
  SQL pane from `lesson-sql.md`, checks the YAML's AgentQL pane against the capture, and adds
  `{model, captured}` metadata.
- **check** content and add errors.
- **declare** the content keys it owns, such as `case`, `lesson`, `sql_count` and `module`. The
  core rejects any key no plugin claims.

Where today's rules go:

| Today | Plugin |
|---|---|
| case ids, capture equality, SQL line highlights, `sql_count` / `sql_before` / `sql_last_line` / `rejected_case`, the Model header and `FROM` check | `agentql_capture` |
| lesson numbers and titles, Modules, realm `module` | `course_refs` |
| the dragon's path is `agentql`, the three engines (`route` trials), the who-put-it-there options and their mapping, crediting rules (§3.5) | `agentql_rules` |
| the first realm is open and has halls | core, from `unlock: first_realm_first` |

### 3.4 `quest.json` version 2

**What changes:**
- **IDs:** every hall and encounter gets an `id`, written in the content. Today encounters have
  only AgentQL's `case`, and halls only their position. Maps (§4.2) bind to these ids.
- **Panes:** an encounter's panes are a list `{id, label, lines, caption?}`, and point highlights
  refer to panes by id: `highlights: {dragon: [12], scroll: []}`. Today there are exactly two
  fixed panes, `sqlHl` and `scrollHl`. A second game might have one pane, or none.
- **Rule tags:** a point's `ruleTag` is checked against the pack's `rule_tags`, not a fixed
  list. Today it is `ruleBy`, an enum of AgentQL's tags.
- **Trials:** `route` becomes `choice`, with options from the content and its strings. `claim`
  stays.
- **The pack's words** go into the data: `pack: {id, title, lexicon, strings}`.
- **Plugin data** moves under namespaces: `meta: {agentql_capture: {model, captured}}`, plus a
  `refs` object on realms, encounters and points for things like `case`, `lesson` and `module`.
  Front ends display `refs` only through strings. No top-level field is any one game's.
- **Classic art** is inlined into the classic page from `art/classic/`. It is not in
  `quest.json`, because explore doesn't use it.

**Where it's published:**
- The schema becomes general: title "Quest data", `$id`
  `https://thoughtspot.github.io/thoughtspot-agent-skills/quest/schema/v2.json`. It's published
  once, at that site path, for every pack.
- Each pack's `quest.json` is published in its own folder, for example `/agentql-quest/quest.json`.

**The switch from v1:** the only consumers of `quest.json` are our own front ends. So PR 2 (§6)
switches `/agentql-quest/quest.json` to v2 and removes `/agentql-quest/quest.schema.json` in the
same change, with no period serving both. Every test that reads v1 fields is ported to v2 in that
PR, not kept:
- `play_quest.js`: `e.sql`, `e.agentql`, `sqlHl`, `scrollHl`, `Q.model`, `Q.captured`;
- `test_quest_build.py`: the data, schema and `$id` assertions.

### 3.5 Content rules: what enforces them

| Rule | Enforced today | Added |
|---|---|---|
| Every lesson claim is true of the captured SQL | partly: highlighted lines, `sql_count`, `sql_before`, `sql_last_line`, `rejected_case` | — |
| Planned capabilities say *coming soon*, never shipped | one test on specific table cells and phrases | — |
| Null guards and the row cap are credited to ThoughtSpot, not the Model | **nothing**: changing those points to `answer: model` passes the gate | `agentql_rules`: a point whose highlight is a `LIMIT n` line or a null guard (`… IS NOT NULL THEN …` / `ELSE 0`) must credit `thoughtspot` |
| Generic fantasy names only | **nothing**: a realm renamed after a published work's place passes | core: a denylist of names from published fantasy works, checked across content, strings and maps, kept as data in the repo |

### 3.6 Shared front-end code

- **`core/` is plain scripts, not ES modules.** Each one adds to one `Quest` global.
  - Classic mode: `build.py` concatenates them, in a fixed order, into the single inline script.
    So classic stays one self-contained file that runs from a double-click. The build refuses any
    core file containing `</script`.
  - Explore: loads the same files with `<script src>`.
- **The state machine moves out of rendering.** `Quest.act(state, action)` returns the new state
  plus effects (play a sound, save progress), and `render()` only draws. Today's closures,
  created while rendering, become named actions. The saves now inside the decree and victory
  screens become effects of the action that finishes a realm.
- **Classic is re-tested on core.** `play_quest.js` keeps driving the page with real clicks and
  keys. It changes only to run the concatenated script and to read v2. Explore's play-through
  calls `Quest.act` directly (§5).

## 4. The explorable front end

### 4.1 Libraries

| Need | Choice | Why |
|---|---|---|
| Engine | **Phaser 4.2.1** (MIT), the arcade-physics build (1,266,396 bytes minified) | The current stable major: 4.0 shipped April 2026 and 4.2.1 is npm `latest`. It includes walking, collision, cameras, input and Tiled map loading. It has the largest body of examples overall, though Phaser 4-specific ones still lag Phaser 3's. It's vendored at a pinned version. |
| Maps | **Tiled 1.10 or later**, saved as `.tmj` JSON with tilesets embedded (no external `.tsx`/`.tsj`) | Realms are drawn visually, and Phaser's Tiled loader reads the file directly. 1.10 is the first version that writes an object's `type` the way Phaser reads it. |
| Art | **Kenney 1-Bit Pack** (CC0, 1,078 files, 16×16 tiles) | Monochrome, so it can be tinted amber to match the video's CRT look. CC0 means no attribution or licence risk in a public repo. Only the tiles used are committed. |
| Dialogue | Not needed: questions come from `quest.json` | Ink or similar only if characters later need branching conversation. |

Rejected: KAPLAY (thinner for a game with several maps), RPG JS (smaller community), Godot (tens
of MB on the web, harder in CI), RPG Maker (commercial licence).

**Phaser settings this design relies on:**
- **Draw maps with `TilemapLayer`,** which has `setTint` in 4.2.1, not `TilemapGPULayer`, which
  doesn't.
- **Boot with `audio: { noAudio: true }`.** Phaser otherwise creates its own AudioContext, and
  the game's Web Audio module stays the only sound.
- **Turn Phaser's keyboard off while a dialog is open** (`input.keyboard.enabled = false`). Its
  window-level listener calls `preventDefault` on captured keys even while the scene is paused,
  which would stop Enter and Space from pressing the dialog's buttons.

### 4.2 Binding maps to content

**Every interactive object on a map names what it starts.** The engine looks it up in
`quest.json`, and the build checks the link. Properties are strings, and lists are
comma-separated, because Tiled's list properties need 1.12.

| Object `type` | Properties | Does |
|---|---|---|
| `spawn` | — | where the player appears (exactly one per map) |
| `portal` | `to` (realm id) | on the overworld: enters a realm. If that realm has no map, it opens the realm in classic mode |
| `exit` | — | back to the overworld |
| `merchant` | `encounter` | the business question and the "read the intent" path choice |
| `guide` | `encounter` | the guide writes the scroll (its first pane) |
| `compiler` | `encounter` | the compiler: the remaining panes appear and the foe wakes |
| `foe` | `encounter` | the points, one question each, in order |
| `reward` | `encounter` | the reward (rules uncovered) and the realm's end |
| `throne` | `hall` (hall id) | a hall's teaching, then its trials |
| `gate` | `requires` (step ids, comma-separated) | blocks the way until those steps are done |

**Step ids** are `<encounter id>:<merchant|guide|compiler|foe|reward>` and `hall:<hall id>`.
They're defined by the content ids, never by positions.

**Build checks** (in the core, so every pack gets them), only for realms listed in
`explore.realms`:
- **Links:** every object refers to content that exists, and each map has one `spawn` and one
  `exit`.
- **Coverage:** every step of every encounter and hall in that realm has an object.
- **Order:** `gate.requires` names real steps, and the order works. For example, the foe can't
  be reached before the compiler.
- **Reachability:** a flood-fill of the collision layer from the spawn, with each gate a wall
  until its requirements are met, reaches every object. So a redraw that walls off the Forge, or
  puts the spawn inside a wall, fails the gate.
- **Tilesets:** embedded, never external `.tsx`/`.tsj` files.

Positions are otherwise free, so a map can be redrawn without touching content.

### 4.3 How a realm plays

Dwarven Mines, about 2–3 minutes:

1. You enter at the mine mouth. A **merchant** asks the business question and offers the three
   engines. The keyword path is blocked in this realm, as today: choosing it explains why and
   costs nothing.
2. Deeper in, the **Wizard** writes the scroll (the AgentQL pane), and a gate opens.
3. You carry it to the **Forge** at the end of the tunnel. The SQL pane appears and the
   **dragon** wakes.
4. Each **scale** is a question from today's encounter, unchanged. Most highlight one or more SQL
   lines and ask who put them there; one is a choice. A right answer breaks a scale and plays the
   effect.
5. The **hoard** chest lists the rules uncovered (MODEL / THOUGHTSPOT tags, your part), then the
   exit.

**The overworld and Law:**
- The overworld is a small map with the five realm portals. Sealed realms show a closed gate,
  and finished realms show your best gold.
- The Kingdom of Law, once mapped, is four rooms, one per hall. A throne asks each hall's
  trials, and the decree waits at the gate.

**Unlocking in the prototype:** the shared `unlock` rule applies in both front ends, so a new
player must finish Law first. Law has no map yet, so its portal opens Law in classic mode.
Classic (`/agentql-quest/`) and explore (`/agentql-quest/explore/`) share an origin and the
`aqq` saves. So finishing Law in classic unlocks the Mines in explore, with no rule that differs
between the front ends.

### 4.4 Questions as HTML over the game

When you interact, the scene pauses, Phaser's keyboard is disabled, and an HTML `<dialog>` opens
over the canvas. It uses the same question rendering from `core/` as classic mode: panes with
highlights, options, **Invoke magic**, feedback and gold. This:
- keeps questions accessible: real buttons, focus management, a live region for results,
  screen-reader text;
- keeps one implementation of scoring and the answer rules;
- keeps the canvas purely for moving around.

### 4.5 Controls, sound, saves

- **Keyboard:** the arrow keys move; Enter or Space interacts. WASD isn't bound, because S and M
  keep their meaning in both front ends (S toggles sound effects, M toggles music).
- **Touch:** an on-screen d-pad and an interact button; tap the dialog's options directly.
- **Reduced motion:** with `prefers-reduced-motion`, no screen shake and instant camera moves.
- **Sound:** the existing Web Audio module moves to `core/`, unchanged: no files, and nothing
  plays before the first input.
- **Saves:** under the pack's `storage_key` (`aqq-progress`, `aqq-sound`) with today's caps and
  tamper handling, shared with classic mode.
- **Classic mode:** always one link away, from the title screen and the pause menu.

### 4.6 Hosting, local running and budget

- **Classic mode stays the default** at `/agentql-quest/`: one self-contained file, which still
  runs from a double-click.
- **Explore is published at `/agentql-quest/explore/`** as several files: page, scripts, Phaser,
  maps and tiles. It fetches `../quest.json`.
- **Explore needs HTTP.** Browsers block `fetch` and XHR from `file://`, and Phaser's loader uses
  XHR, so explore doesn't run from a double-click. To work locally, build into a folder and serve
  it with `python3 -m http.server`. To test on a phone, use the same server, reached by the
  computer's LAN address. Pages deploys only from `main` and there are no preview deploys, so this
  local loop is how the manual checklist (§6) is done.
- **No outside requests.**
- **Budget:** 3 MB for the explore folder. Phaser is about 1.27 MB, the fonts are 52 KB, and maps
  and tiles are small.

## 5. Testing

- **The map play-through (node, no canvas):**
  - Read each `.tmj` and build the object graph.
  - "Walk" it by calling `Quest.act` with an `interact` action per object, in any order the
    gates allow.
  - Answer every question right, wrong-then-right, and with magic, as `play_quest.js` does
    today.
  - Assert the scores and the saves.
  - Together with the §4.2 flood-fill, this proves every question can be reached and finished.
- **Map checks (Python, the gate):** the §4.2 checks run in `build.py --check`, with a test that
  breaks each one on purpose.
- **Content rules:** the two new checks in §3.5 each come with a test showing they fail.
- **Classic mode:** tested as in §3.6.
- **Rendering:** a manual checklist for the prototype (§6). A browser smoke test in CI is
  decision 3 (§8).

## 6. Delivery

**PRs in order,** each gated and reviewed:

1. **Rename only** (if decision 4 is "now"): `tools/agentql-quest/` → `tools/quest/`, with no
   other change, so git keeps the history. Every path that names the folder changes with it:
   - **Silent if missed:**
     - `pages.yml`'s `on.push.paths`, given a test so a filter change is caught;
     - the pre-commit trigger in `scripts/pre-commit.sh`.
   - **Loud if missed:**
     - the pytest paths in `validate.yml` (both jobs) and `pre-commit.sh`;
     - `pages.yml`'s build command and poster copy;
     - the path in `tools/validate/check_agentql_quest.py`;
     - links in the README tree and `CLAUDE.md`'s directory map.
   - It edits `pre-commit.sh`, `validate.yml` and a validator, so `docs/quality-gates.md` is
     regenerated after committing, and the code owners review it.
2. **Pack split:**
   - the layout of §3.1 (the pack folder, fonts and promo moved);
   - the manifest and the three plugins;
   - the two content-rule checks of §3.5;
   - `quest.json` v2 with the general schema;
   - `core/` with the state machine taken out of rendering, and classic rebuilt on it;
   - tests ported to v2.
   Nothing changes for players.
3. **Map binding:** the §4.2 object types, step ids and checks (the flood-fill included), and the
   node map play-through, on a tiny test map.
4. **Explore prototype:**
   - Phaser vendored, with its §9 coverage;
   - the Mines map and tiles, plus the overworld with portals;
   - the dialog, controls and the Pages build step;
   - published at `/agentql-quest/explore/`.

**The prototype is done when:**
- The Mines can be played start to finish with the keyboard alone, and with touch alone, in 2–4
  minutes.
- Law can be reached from the overworld (in classic), and finishing it there unlocks the Mines.
- Scores match classic mode for the same answers, and the best score shows in both.
- All tests pass, and the gate fails on each broken map check.
- There are no outside requests, and the explore folder is under 3 MB.
- A screen-reader pass with VoiceOver: each dialog announces, focus starts on the question, and
  results are read.
- The manual checklist, served locally: Chrome, Safari and Firefox on desktop; Safari on
  iPhone; and reduced motion.

**Then:** you play it and decide on decision 1 (§8).

## 7. A second game

To add a game, create `tools/quest/packs/<id>/` with:
- `pack.yaml`, with its own `publish_path` and `storage_key`;
- `content.yaml` and `strings.yaml`;
- maps, if it should be explorable.

It uses none of the AgentQL plugins, or new ones of its own. Its sources of truth are its own to
check, the way `agentql_capture` pins this game to the captured SQL. Each pack is built to its
`publish_path` and listed on the site's home page.

## 8. Decisions for you

1. **After the prototype, should explore replace classic** as the default at `/agentql-quest/`,
   or sit beside it? **Recommended:** beside it until all five realms are explorable, then make
   explore the default with classic linked.
2. **The art:** Kenney 1-Bit tinted amber (fast, CC0), or commission custom pixel art later?
   **Recommended:** Kenney for the prototype; revisit only if it feels generic.
3. **A browser smoke test in CI, or a manual checklist?** The cost of a smoke test is smaller
   than it sounds: GitHub's Ubuntu runner already has Chrome. Playwright using it
   (`channel: 'chrome'`) downloads no browser, though the repo would gain an npm toolchain in CI.
   **Recommended:** the manual checklist until explore becomes the default, then a smoke test.
4. **Rename the engine** (`tools/agentql-quest/` → `tools/quest/`) now, or only when a second
   game exists? §3.1, §6 and §7 assume "now". **Recommended:** now, as PR 1, while only one pack
   depends on it. The public URL doesn't change.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Walking adds time: the course is "about 15 minutes" | Small maps (one screen or two), every question within 2–3 minutes per realm |
| Phaser 4 is new (April 2026) | Use only basic features (tilemaps, arcade movement, cameras, input); pin one version |
| **Vendored Phaser gets no security alerts today.** Snyk Code skips files over 1 MB and minified files, pip-audit is Python only, and Dependabot watches only Actions and `tools/ts-cli` | PR 4 adds: a `package.json` in `vendor/` that pins `phaser@4.2.1`; an npm entry in `.github/dependabot.yml` for it; and a test that the vendored file's hash matches npm's published integrity |
| A canvas game is harder to make accessible | All questions are HTML dialogs; classic mode is always one link away |
| Map edits silently break the course | The §4.2 checks (links, coverage, order, flood-fill) and the node map play-through, in the PR gate |
| Two front ends drift apart | One `core/` for state, scoring, saves, sound and the question panel; both front ends' tests run on it |
| Two packs overwrite each other's saves | A `storage_key` per pack; the build refuses duplicates |
