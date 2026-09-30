# Pipeline: from library charts to an imported Liveboard

Every fact here was verified on a ThoughtSpot cluster (release 26.8) while building *Amuzing chart samples*.

## The MCP sandbox shapes everything

`execute-thoughtspot-code` runs JavaScript in a worker with a `ts` client for the cluster.

| Fact | Consequence |
|---|---|
| Network reaches only the cluster | No CDN, no GitHub from inside; charts cannot be fetched from anywhere but ThoughtSpot |
| No state between calls | Nothing built in one call survives to the next except what is saved in ThoughtSpot |
| About 50 network calls per run | Batch: one export per block, `searchdata` cached by search string (`patch.js` does both) |
| The token is bound to one org | Org switch returns 403 (code 10088). Work in the org you have |
| A `VALIDATE_ONLY` import still counts as a write | Pass `confirm_write_operations: true` even to validate |
| TML import accepts JSON | `metadata_tmls: [JSON.stringify(tml)]`; no YAML needed |

## Patch the Liveboard in blocks

A 50-tile Liveboard is about 1.8 MB of TML, mostly base64 chart code. Sending that through your own
context is slow, and one wrong character corrupts a tile. So `<L>/scripts/liveboard-pack.mjs` splits the charts
into blocks, and each block patches the Liveboard itself (`<L>/scripts/patch.js`):

1. every chart and the core carry a sha256; the sandbox refuses the whole block on any mismatch;
2. it exports the Liveboard and indexes its tiles by the `/* amuzing-slug: <slug> */` marker at the top of
   each chart body (tiles imported before markers existed are matched by tab name and grid position);
3. it builds the whole TML from the spec: charts in the block replace their tile, every other tile keeps its
   current code, spec tiles with no code anywhere are left out and listed under `problems`;
4. it imports, and after a commit exports again and compares every tile's JS and CSS sha256 **in order**
   (ThoughtSpot renumbers viz ids).

Nothing else is created in ThoughtSpot. An earlier version stored every chart as its own
`zz-amuzing-store-<slug>` Liveboard and assembled from those: 56 objects in the user's library that they
never asked for. Do not bring that back.

A custom chart tile in TML is `answer.chart.type: MUZE_STUDIO`, with the three files base64 in
`custom_visual_props` (a JSON string) > `clientState` (another JSON string) > `playground.code`
`.{jsCodeBase64, cssCodeBase64, htmlCodeBase64}`.

Blocks must be pasted in order and one at a time: each exports, patches and imports the whole Liveboard,
so two running at once (for example from parallel subagents) would overwrite each other's tiles. Subagents
build and emit charts; the coordinator sends them.

## Import size

A commit of about 2.8 MB of TML failed with `ECONNRESET`; the same 50 tiles trimmed to 1.8 MB imported.
`liveboard-pack.mjs` strips `//` comment lines, CSS comments (except the core markers) and indentation; that is safe only
because chart files are ASCII and contain no template strings (the chart contract enforces both). Every block reports `tmlKB`, and
warns past 2000. Past about 2 MB: share code between tiles with
`.use`, or split the Liveboard.

## Inside a tile (the preview cannot show these)

| Fact | Consequence |
|---|---|
| `fetch()` to any external URL is blocked | Inline data files and maps (`<C>/library/_shared/us-states.js`) |
| `<script src>` from jsdelivr and unpkg loads | d3, echarts, plotly, topojson work; keep the bounded `AZ.loadScript` fallback |
| A runtime filter in the URL does not reach the tiles | Drive the filter chip through the UI (`cluster-shot.mjs --filter`) |
| Tiles load lazily as they scroll into view | `cluster-shot.mjs` scrolls and waits per screenful |

## Traps met on the way

- `String.prototype.replace(str, replacement)` treats `$'` and `$&` in the replacement as patterns; when
  composing code, use a function replacement (`.replace(a, () => b)`).
- **A chart changed in the library is not changed on the Liveboard until it is sent.** The tile renders
  fine with its old code, so nothing flags it. Run `liveboard-pack.mjs --check` before and after a round.
  To see what a live tile really runs, evaluate in its frame (for example `!!window.Plotly`).
- A stale core copy inside a chart only misleads the preview (every block sends the current core);
  `liveboard-pack.mjs` warns, and `<C>/helpers/sync-core.mjs` fixes it.
- Drag-and-drop layout edits made in the ThoughtSpot UI are overwritten by the next block, which lays the
  Liveboard out from the spec. Move tiles in `make-spec.py`, not in the UI.
