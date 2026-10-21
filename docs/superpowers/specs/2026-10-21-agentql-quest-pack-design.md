# Design: quest packs and an explorable AgentQL Quest

_Separate the game's content from its front ends, so that (1) AgentQL Quest can be played as an
explorable map, where you walk a realm and its characters ask the questions, and (2) a second game
on another topic can reuse the engine by adding a content folder._

Status: **accepted** (decisions in §8 made 2026-10-21) · Builds on: AgentQL Quest
([`tools/agentql-quest/`](../../../tools/agentql-quest/), #622) and its data contract
`quest.json` / `quest.schema.json` (#632)

---

## 1. Where we are

AgentQL Quest is one self-contained page. `build.py` compiles `encounters.yaml` with the lesson
capture (`lesson-sql.md`) and the course (`learning-path.md`), checks it, and writes:

- `quest.json`, the checked game data, described by `quest.schema.json` (version 1). The PR gate
  enforces it with a built-in checker (`lint_schema`), which accepts only a strict subset of
  JSON Schema: every property required, `additionalProperties: false`, no open maps. CI checks it
  again with a real JSON Schema validator.
- `index.html`, the text adventure (`game.html` with the data and fonts inlined). It runs from
  Pages, any static host, or a double-click.

The data is separate from the page, but it is **not** general. Everything below is specific to
AgentQL, and a second game must not need any of it.

**In the compiled data (`quest.json` v1):**

| Field | Why it's AgentQL's |
|---|---|
| top-level `captured`, `model` | the capture's date and Model (both required) |
| realm `module` (required integer) | the course module |
| encounter `case`, `lesson` | the `lesson-sql.md` case id and the `learning-path.md` lesson number ("2.3") |
| encounter `agentql`, `sql`; point `sqlHl`, `scrollHl` | exactly two code panes, named for AgentQL |
| point `ruleBy` ∈ `model / thoughtspot / agentql / determinism` | AgentQL's rule tags |
| trial kind `route` ("which engine") | AgentQL's three engines |
| option text written by `build.py`: "Send it to {engine}", "Heed them. It is true." / "Banish them. It is false." | wording in code, not content |
| the schema's title ("AgentQL Quest data") and `$id` under `/agentql-quest/` | one game's contract |

A point's `lesson` field is *not* in this table, because it isn't a lesson number. It's the
explanation shown after a right answer: `game.html` renders it as feedback, and `play_quest.js`
asserts it as the explanation. It's general content with a misleading name.

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
- the hoard's grouping:
  - `model` and `thoughtspot` rules under "rules uncovered";
  - `agentql` rules under "your part";
  - `determinism` rules hidden and replaced by the verdict;
- the rule that every realm waits until the first one is done;
- the save keys: `aqq-progress`, and `aqq-sound` (hard-coded in the Sound module).

How the page is built matters for the plan:
- It is one inline script with a global `state`.
- `render()` builds `innerHTML`, and the state changes live in click handlers created while
  rendering.
- Saves also happen during rendering: the decree and victory screens call `finishRealm`.
- `tests/play_quest.js` runs that script in a node `vm` with a fake DOM. It drives it with real
  clicks and key presses, and binds top-level names (`state`, `actions`, `Sound`, `GOLD_WIN`,
  `GOLD_LOSS`).

## 2. Goals and non-goals

**Goals**
- A **quest pack** format: one folder holds a game's content, words, art and (optionally) maps.
  The engine and its front ends contain no AgentQL wording or rules.
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

The engine moves to `tools/quest/` (decision 4), with the packs inside it, so the engine has one
path root. Path triggers also cover each pack's `sources` (§3.2).

```
tools/quest/
  build.py                     core compile and checks; loads the plugins a pack names
  checks/                      plugins: agentql_capture.py, course_refs.py, agentql_rules.py
  schema/core.json             the general part of the v2 schema (§3.4)
  core/                        shared front-end code, plain scripts (§3.6)
  classic/                     the text-adventure page (today's game.html, on core/)
  explore/                     the map front end (new)
  fonts/                       VT323 and IBM Plex Mono, with their OFL licences (moved)
  vendor/                      Phaser, pinned and verified (§9)
  tests/                       all engine and pack tests (one pytest root, as today)
  packs/
    agentql/                   AgentQL Quest's pack
      pack.yaml                the manifest
      content.yaml             today's encounters.yaml, with ids (§3.4)
      strings.yaml             every sentence a front end shows that isn't content
      art/classic/*.txt        the ASCII scenes
      maps/*.tmj               Tiled maps: the overworld, plus one per explorable realm
      tiles/                   a Kenney 1-Bit Pack subset (CC0 note)
      promo/                   the poster, the GIF and make_ad.py (moved)
```

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
rule_tags:                             # the reward screen's tags: label and where each is shown
  model:       {label: MODEL,       group: rules}
  thoughtspot: {label: THOUGHTSPOT, group: rules}
  agentql:     {label: YOUR PART,   group: yours}
  determinism: {label: "",          group: verdict}   # hidden; the verdict string stands in for them
lexicon:                               # the roles the engine knows, named the pack's way
  guide: The Wizard                    # writes the scroll (the AI)
  compiler: The Forge                  # turns it into what runs (ThoughtSpot + the Model)
  foe: dragon
  reward: hoard
  currency: gold
explore:
  realms: [mines]                      # realms with a map; others are played in classic mode
```

The build refuses two packs that share an `id`, a `publish_path` or a `storage_key`. Every pack is
served from the same origin (`thoughtspot.github.io`), and saving rewrites the whole progress
object, so a shared key would erase the other game's saves.

`strings.yaml` holds:
- the title blurb, the legend, the rule card and the determinism verdict;
- button and option wording ("Send it to {engine}", the claim buttons);
- pane labels and captions, with `{model}` and `{captured}` filled from the plugin's metadata;
- the course links.

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
- **declare** the content keys it owns, and their JSON Schema, for the pack's generated schema
  (§3.4). The core rejects any key no plugin claims.

| Today | Plugin |
|---|---|
| case ids, capture equality, SQL line highlights, `sql_count` / `sql_before` / `sql_last_line` / `rejected_case`, the Model header and `FROM` check | `agentql_capture` |
| lesson numbers and titles, Modules, realm `module` | `course_refs` |
| the dragon's path is `agentql`; the three engines (`choice` trials with engine options); the who-put-it-there options and their mapping; the first realm is open and has halls; the crediting rule (§3.5) | `agentql_rules` |

The core's `unlock: first_realm_first` only locks the other realms until the first is done. That
the first realm has *halls* is AgentQL's rule, so it lives in `agentql_rules`.

### 3.4 `quest.json` version 2

**What changes:**
- **IDs:** every hall and encounter gets an `id` in the content, matching `^[a-z][a-z0-9_]*$`.
  `hall` is reserved, because step ids use it (§4.2). Today encounters have only AgentQL's
  `case`, and halls only their position.
- **Panes:** an encounter's panes are a list `{id, label, lines, caption}`. `caption` is always
  present, `""` when there is none, because the gate's schema checker allows no optional fields.
  Point highlights refer to panes by id: `highlights: {dragon: [12], scroll: []}`.
- **Explanations:** a point's `lesson` (the explanation) is renamed `why`, as hall trials already
  have it.
- **Rule tags:** a point's `ruleTag` is checked against the pack's `rule_tags`. Today it is
  `ruleBy`.
- **Trials:** `route` becomes `choice`, with options from the content and its strings. `claim`
  stays.
- **The pack's settings** go into the data, so explore can read them from `quest.json`:
  `pack: {id, title, storage_key, unlock, explore_realms, lexicon, rule_tags, strings}`.
- **Plugin data** goes under named fields:
  - `meta: {agentql_capture: {model, captured}}` at the top;
  - `refs` on realms and encounters only (`case`, `lesson`, `module`);
  - front ends show `refs` only through strings.
- **Classic art** is inlined into the classic page from `art/classic/`. It's not in `quest.json`.

**One schema per pack, generated:**
- `build.py` assembles each pack's schema from `schema/core.json` plus what its plugins declare.
  The result is closed: every field is listed and required, with no open maps or
  `patternProperties`. So it passes the existing `lint_schema` unchanged, and CI's real validator
  checks it as today.
- It's published beside that pack's `quest.json`, so AgentQL's stays at
  `/agentql-quest/quest.schema.json`, with title "AgentQL Quest data" and the same `$id`.
- A second game gets its own schema, with only the core and its own plugins' fields. Nothing in
  it is AgentQL's.

**The switch from v1:**
- The only consumers of `quest.json` are our own front ends, so PR 2 switches it to
  `schema_version: 2` in place, with no period serving both.
- Every test that reads v1 fields is ported to v2 in that PR, not kept:
  - `play_quest.js`: `e.sql`, `e.agentql`, `sqlHl`, `scrollHl`, `ruleBy`, point `lesson`,
    `Q.model`, `Q.captured`;
  - `test_quest_build.py`: the data and schema assertions.

### 3.5 Content rules: what enforces them

| Rule | Enforced today | Added (PR 2) |
|---|---|---|
| Every lesson claim is true of the captured SQL | partly: highlighted lines, `sql_count`, `sql_before`, `sql_last_line`, `rejected_case` | — |
| Planned capabilities say *coming soon*, never shipped | one test on specific table cells and phrases | — |
| Null guards and the row cap are credited to ThoughtSpot, not the Model | **nothing**: changing those points to `answer: model` passes the gate | `agentql_rules` (see below) |
| Generic fantasy names only | **nothing**: a realm renamed after a published work's place passes | the core denylist (see below) |

**The crediting check** (`agentql_rules`) applies to a `who` point with explicit highlights,
where every highlighted SQL line is part of either:
- a `LIMIT <n>` line; or
- the full null-guard shape `CASE WHEN <aggregate> IS NOT NULL THEN <aggregate> ELSE 0 END`.

Such a point must answer `thoughtspot`. Points that highlight everything (`*`), such as the
determinism points in the Mines and the Isles, are out of scope. A `CASE` the AgentQL itself
wrote doesn't match the full shape.

**The denylist:**
- **Storage:** hashed and normalised (lowercased, accents stripped) single words and two-word
  phrases from published fantasy works. A helper adds entries, so the names themselves are never
  committed.
- **Scope:** content, strings, maps and `art/classic/`.
- **Report:** the offending word from our content, never the list.

The existing test fixture that uses a published place name (`test_quest_build.py`, an unknown
route realm) is replaced with a made-up name in PR 1.

### 3.6 Shared front-end code

- **`core/` is plain scripts, not ES modules.** Each one adds to one `Quest` global.
  - Classic mode: `build.py` concatenates them, in a fixed order, into the single inline script.
    So classic stays one self-contained file that runs from a double-click. The build refuses
    any core file containing `</script` or `<!--`, in any case.
  - Explore: loads the same files with `<script src>`.
- **The state machine moves out of rendering.** `Quest.act(state, action)` returns the new state
  plus effects (play a sound, save progress), and `render()` only draws.
  - Today's closures, created while rendering, become named actions.
  - The saves now inside the decree and victory screens become effects of the action that
    finishes a realm.
  - `Quest.act` enforces the order of steps (merchant, guide, compiler, foe, reward; halls in
    order). An out-of-order interaction is refused with a message and changes nothing. Gates on a
    map are for layout, not correctness.
- **Sound** moves to `core/`, keyed by the pack's `storage_key` instead of the hard-coded
  `aqq-sound`.
- **Classic is re-tested on core.** `play_quest.js` keeps driving the page with real clicks and
  keys. Its hooks move from top-level names (`state`, `actions`, `Sound`, `GOLD_WIN`, `GOLD_LOSS`)
  to the `Quest` global, and it reads v2. Explore's play-through calls `Quest.act` directly (§5).

## 4. The explorable front end

### 4.1 Libraries

| Need | Choice | Why |
|---|---|---|
| Engine | **Phaser 4.2.1** (MIT), the arcade-physics build (1,266,396 bytes minified) | The current stable major: 4.0 shipped April 2026, and 4.2.1 is npm `latest`. It includes walking, collision, cameras, input and Tiled map loading. It has the largest body of examples overall, though Phaser 4-specific ones still lag Phaser 3's. Vendored and pinned (§9). |
| Maps | **Tiled 1.10 or later**, saved as `.tmj` JSON with tilesets embedded (no external `.tsx`/`.tsj`) | Realms are drawn visually, and Phaser's Tiled loader reads the file directly. Tiled 1.9 wrote an object's `type` as `class`, which Phaser doesn't read; 1.10 went back to `type`. |
| Art | **Kenney 1-Bit Pack** (CC0, 1,078 files, 16×16 tiles), tinted amber (decision 2) | Monochrome, so tinting matches the video's CRT look. CC0 means no attribution or licence risk in a public repo. Only the tiles used are committed. |
| Dialogue | Not needed: questions come from `quest.json` | Ink or similar only if characters later need branching conversation. |

Rejected: KAPLAY (thinner for a game with several maps), RPG JS (smaller community), Godot (tens
of MB on the web, harder in CI), RPG Maker (commercial licence).

**Phaser settings this design relies on:**
- **Renderer: force WebGL (`type: Phaser.WEBGL`) and draw maps with `TilemapLayer`.**
  `TilemapLayer.setTint` works only under WebGL; the default `AUTO` mode can fall back to Canvas,
  which ignores tile tint. `TilemapGPULayer` has no tint API at all. If WebGL isn't available, the
  page offers classic mode.
- **Audio: boot with `audio: { noAudio: true }`.** Phaser otherwise creates its own
  AudioContext, and `core/`'s Web Audio module stays the only sound.
- **Keyboard: limit Phaser's input to the canvas** with `input.keyboard.target` set to the
  focusable canvas element.
  - Phaser's keyboard manager calls `preventDefault` on captured keys. Scoped to the canvas, it
    can't swallow Enter or Space on the dialog, the title links, the pause menu or the sound
    buttons.
  - When a dialog opens, the game also turns the manager off (`game.input.keyboard.enabled =
    false`). When the dialog closes, it turns it back on and calls `resetKeys()`, so a held arrow
    key doesn't stay stuck.

### 4.2 Binding maps to content

**Every interactive object on a map names what it starts.** The engine looks it up in
`quest.json`, and the build checks the link. Properties are strings, and lists are
comma-separated: Tiled's list properties need 1.12, and ids can't contain commas (§3.4).

| Object `type` | Properties | Does |
|---|---|---|
| `spawn` | — | where the player appears (exactly one per map) |
| `portal` | `to` (realm id) | overworld only: enters a realm. A realm not in `explore.realms` opens in classic mode (§4.3) |
| `exit` | — | realm maps only: back to the overworld |
| `merchant` | `encounter` | the business question and the "read the intent" path choice |
| `guide` | `encounter` | the guide writes the scroll (its first pane) |
| `compiler` | `encounter` | the compiler: the remaining panes appear and the foe wakes |
| `foe` | `encounter` | the points, one question each, in order |
| `reward` | `encounter` | the reward (rules uncovered) and the realm's end |
| `throne` | `hall` (hall id) | a hall's teaching, then its trials |
| `gate` | `requires` (step ids, comma-separated) | blocks the way until those steps are done |

**Step ids:**
- `<encounter id>:<merchant|guide|compiler|foe|reward>` for encounter steps;
- `hall:<hall id>` for halls.

They come from the content ids, and `hall` is reserved as an id, so the two forms can't collide.

**Collision, for both the game and the checks:**
- **One source:** a tile layer named `walls`, where any non-empty tile blocks. Phaser sets
  collision from that layer, and the build reads the same layer.
- **Objects:** each sits on the tile containing its centre (Tiled anchors tile objects at the
  bottom-left, so the build converts). Characters, chests and portals are solid.
- **Reaching an object** means standing on any walkable tile next to it (up, down, left or
  right).
- **Gates** block every tile their rectangle covers until their requirements are met.

**Build checks** (in the core, so every pack gets them):

- **Realm maps** (for the realms in `explore.realms`):
  - every object refers to content that exists;
  - one `spawn` and one `exit`;
  - every step of every encounter and hall in the realm has exactly one object;
  - `gate.requires` names real steps of that realm;
  - **reachability (a flood-fill):** start from the spawn, with every gate closed. Open each gate
    once the steps it requires are reachable, and repeat until nothing changes. Every object must
    end up reachable. So a redraw that walls off the Forge, puts the spawn inside a wall, or parks
    a solid character across a one-tile corridor fails the gate.
- **The overworld:**
  - one `spawn` and no `exit`;
  - exactly one `portal` per realm, each with a valid `to`;
  - every portal reachable, by the same flood-fill.
- **Every map:**
  - tilesets embedded, never external `.tsx`/`.tsj`;
  - each tileset's image exists in the pack and ships in the explore build;
  - no Tiled object templates (`template`), which Phaser doesn't resolve.

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
5. The **hoard** chest lists the rules uncovered (grouped by `rule_tags`), then the exit.

**The overworld and Law:**
- The overworld is a small map with the five realm portals. Sealed realms show a closed gate,
  and finished realms show your best gold.
- The Kingdom of Law, once mapped, is four rooms, one per hall. A throne asks each hall's trials,
  and the decree waits at the gate.

**Unlocking in the prototype:**
- **The same rule in both front ends.** The shared `unlock` rule applies to both, so a new player
  must finish Law first.
- **Law opens in classic mode.** Law has no map yet, so its portal opens
  `/agentql-quest/#realm=law`. Classic gains that deep link in PR 4 (today it always starts at
  the title), plus a "back to the map" link when it was opened from explore.
- **Saves are shared.** Classic (`/agentql-quest/`) and explore (`/agentql-quest/explore/`) share
  an origin and the `aqq` saves. Explore re-reads them on `pageshow` and before every portal
  check, so returning with Back shows Law as done and the Mines as open.

### 4.4 Questions as HTML over the game

When you interact, the scene pauses, Phaser's keyboard is turned off, and a modal `<dialog>`
opens over the canvas. It uses the same question rendering from `core/` as classic mode: panes
with highlights, options, **Invoke magic**, feedback and gold. This:
- keeps questions accessible: real buttons, focus management, a live region for results,
  screen-reader text;
- keeps one implementation of scoring and the answer rules;
- keeps the canvas purely for moving around.

Closing the dialog, whether through its buttons or **Esc**, resumes the scene, turns the
keyboard back on and resets keys. Esc counts as "not now": progress made inside the dialog is
kept, and the character can be asked again.

### 4.5 Controls, sound, saves

- **Keyboard:** the arrow keys move; Enter or Space interacts. WASD isn't bound, because S and M
  keep their meaning in both front ends (S toggles sound effects, M toggles music).
- **Touch:** an on-screen d-pad and an interact button; tap the dialog's options directly.
- **Reduced motion:** with `prefers-reduced-motion`, no screen shake and instant camera moves.
- **Sound:** `core/`'s Web Audio module, keyed by `storage_key`: no files, and nothing plays
  before the first input.
- **Saves:** under the pack's `storage_key` (`aqq-progress`, `aqq-sound`) with today's caps and
  tamper handling, shared with classic mode.
- **Classic mode:** always one link away, from the title screen and the pause menu.

### 4.6 Hosting, local running and budget

- **Side by side (decision 1):** classic stays the default at `/agentql-quest/`, one
  self-contained file that still runs from a double-click. Explore is published at
  `/agentql-quest/explore/` as several files (page, scripts, Phaser, maps, tiles) and fetches
  `../quest.json`. Explore becomes the default only when all five realms are explorable, with
  classic linked.
- **Explore needs HTTP.** Browsers block `fetch` and XHR from `file://`, and Phaser's loader uses
  XHR, so explore doesn't run from a double-click. To work locally, build into a folder and serve
  it with `python3 -m http.server`. To test on a phone, use the same server, reached by the
  computer's LAN address. Pages deploys only from `main` and there are no preview deploys, so this
  local loop is how the manual checklist (§6) is done.
- **No outside requests.**
- **Budget:** 3 MB for the explore folder. Phaser is about 1.27 MB, the fonts are 48 KB, and maps
  and tiles are small.

## 5. Testing

- **The map play-through (node, no canvas):**
  - Read each `.tmj` and build the object graph.
  - "Walk" it by calling `Quest.act` with an `interact` action per object, in any order the
    gates allow.
  - Answer every question right, wrong-then-right, and with magic, as `play_quest.js` does today.
  - Assert the scores and the saves, and that out-of-order interactions are refused.
- **Map checks (Python, the gate):** the §4.2 checks run in `build.py --check`, each with a test
  that breaks it on purpose. Together with the play-through, they prove every question can be
  reached and finished.
- **Content rules:** the two new checks in §3.5 each come with a test showing they fail.
- **Classic mode:** tested as in §3.6.
- **Where tests live:** all tests stay in `tools/quest/tests/` (pack-specific ones under
  `tests/packs/agentql/`), one pytest root, so `validate.yml` and pre-commit name one path.
- **Rendering (decision 3):** a manual checklist (§6) until explore becomes the default. Then a
  Playwright smoke test that uses the Chrome already on GitHub's Ubuntu runner
  (`channel: 'chrome'`), so no browser download.

## 6. Delivery

**PRs in order,** each gated and reviewed:

1. **Rename only** (decision 4): `tools/agentql-quest/` → `tools/quest/`, with no other change
   except the fixture fix in §3.5, so git keeps the history. Every reference to the folder
   changes with it:
   - **Silent if missed, so each gets a test:**
     - `pages.yml`'s `on.push.paths` (a test reads it);
     - the pre-commit trigger in `scripts/pre-commit.sh` (a test reads it);
     - the root README's tree (`check_consistency` only does a substring match, and "quest"
       already appears in the URL);
     - the folder's own docs: its README commands, `build.py`'s docstring and `--help`, and
       `promo/README.md` and `make_ad.py`.
   - **Loud if missed:**
     - the pytest paths in `validate.yml` (both jobs) and `pre-commit.sh`;
     - `pages.yml`'s build command and poster copy;
     - the path in `tools/validate/check_agentql_quest.py`.
   - **Also:** it edits `pre-commit.sh`, `validate.yml` and a validator, so
     `docs/quality-gates.md` is regenerated after committing, and the code owners review it.
2. **Data v2 and plugins:**
   - the pack layout (fonts and promo moved), the manifest, and the three plugins;
   - the generated per-pack schema, `quest.json` v2, and the two content-rule checks;
   - classic adapted to read v2.
   Nothing changes for players.
3. **Shared core:** `core/`, with the state machine taken out of rendering, and classic rebuilt on
   it. `play_quest.js` is ported. Nothing changes for players.
4. **Map binding:** the §4.2 object types, step ids and checks (the flood-fill included), and the
   node map play-through, on a tiny test map.
5. **Explore prototype:**
   - Phaser vendored with its §9 checks;
   - the Mines map and tiles, plus the overworld;
   - classic's `#realm=` deep link and return link;
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

**Then:** you play it, and the remaining realms get maps.

## 7. A second game

To add a game, create `tools/quest/packs/<id>/` with:
- `pack.yaml`, with its own `id`, `publish_path` and `storage_key`;
- `content.yaml` and `strings.yaml`;
- maps, if it should be explorable.

It uses none of the AgentQL plugins, or new ones of its own. Its sources of truth are its own to
check, the way `agentql_capture` pins this game to the captured SQL. Its schema is generated from
the core and its own plugins (§3.4). Each pack is built to its `publish_path` and listed on the
site's home page.

## 8. Decisions (made 2026-10-21)

1. **Explore sits beside classic.** It becomes the default only when all five realms are
   explorable, with classic linked.
2. **The art is Kenney 1-Bit, tinted amber,** for the prototype. Revisit only if it feels generic.
3. **Testing uses a manual checklist** until explore becomes the default. Then a Playwright smoke
   test on the runner's own Chrome.
4. **The engine is renamed** `tools/quest/` now, as PR 1, while only one pack depends on it. The
   public URL doesn't change.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Walking adds time: the course is "about 15 minutes" | Small maps (one screen or two), every question within 2–3 minutes per realm |
| Phaser 4 is new (April 2026) | Use only basic features (tilemaps, arcade movement, cameras, input); pin one version |
| **Vendored Phaser gets no security alerts today.** Snyk Code skips files over 1 MB and minified files, pip-audit is Python only, and Dependabot watches only Actions and `tools/ts-cli` | See **Vendored Phaser checks** below |
| A canvas game is harder to make accessible | All questions are HTML dialogs; classic mode is always one link away |
| Map edits silently break the course | The §4.2 checks (links, coverage, reachability) and the node map play-through, in the PR gate |
| Two front ends drift apart | One `core/` for state, scoring, saves, sound and the question panel; both front ends' tests run on it |
| Two packs overwrite each other's saves | A `storage_key` per pack; the build refuses duplicates |

**Vendored Phaser checks** (all added in PR 5):
- `vendor/package.json` and `package-lock.json` pin `phaser@4.2.1`. The lock records the npm
  tarball's integrity.
- An npm entry in `.github/dependabot.yml` for `vendor/`.
- A test checks the vendored file's own SHA-256 against the value recorded beside it, which
  matches jsDelivr's published per-file hash.
- Another test checks that the version in `package.json` equals the version Phaser's file
  declares. So a Dependabot bump fails until the vendored file is replaced.
