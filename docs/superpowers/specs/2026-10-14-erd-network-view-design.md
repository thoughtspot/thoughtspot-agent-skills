# ERD network view — design

**Date:** 2026-10-14 · **Skill:** `ts-object-model-erd` (shared renderer `agents/shared/erd/`)
**Status:** approved in chat 2026-10-14; this spec awaits review

## Why

The card ERD answers "what is in each table and how are they joined". At 30+ tables,
and especially with many aliases, the question people actually ask first is about the
model's *shape*: where the hubs are, how far the aliases fan out, and which areas hang
off which fact. A node-link diagram (labelled dots, plain lines, force layout) answers
that at a glance. A user brought one in as a reference image; it came from a real
tenant's model, so it is **not** committed or reproduced here. The synthetic
`examples/order-fulfilment` model (29 tables, 20 aliases) is the stand-in.

## What the user said vs. what is assumed

| Said / agreed | Assumed (correct me) |
|---|---|
| Add the node diagram "as an option" in the ERD | It lives in the existing viewer, not a separate output file |
| A View toggle, Cards / Network | Network has its own layout; the Layout buttons are disabled while it is on |
| Colour by kind, distinct alias colour | Aliases stay **purple** (`#7C3AED`), matching the legend and card badge, not the image's yellow |
| Collapse-aliases is out of scope | — |

## Success criteria

1. On `examples/order-fulfilment`, Network view shows all 29 tables as labelled dots.
   The 20 aliases are visibly distinct, and the four role-playing hubs (`DM_ORDER`,
   `DM_SHIPMENT`, `DM_INVOICE`, `DM_AUDIT_EVENT`) read as hubs without zooming.
2. Every existing interaction keeps working in Network view: click-to-inspect (table and
   join), focus (click, double-click tree, shift-click compare and path), search,
   filters, Group by, minimap, fit, drag with saved positions, notes, Share HTML.
3. Switching between views does not lose dragged positions in either one.
4. The Cards view is unchanged, pixel for pixel, when Network has never been selected.

## Design

### State and persistence

- New `let VIEW="cards"` (`"cards"|"network"`). The choice persists in localStorage
  under `ts-erd-view`, wrapped in try/catch like the other keys. It is per viewer, not
  per model, and not baked into Share HTML. A shared file opens in Cards, its default.
- Positions: the network layout is stored as `savedPos.network` and cached as
  `layoutCache.network`, using the existing per-layout mechanism. `captureLayout()`
  already keys by `layoutName`. In Network view `layoutName` is `"network"`, and the
  previous card layout name is remembered so that switching back restores it.

### Geometry — the one structural change

Card size is currently read from `NODE_W` and `nodeHeight(t)` in several places:
`renderEdges` and `renderNodes` reset `n.h`, while `center()`, `border()`, `fitNodes`,
the minimap and drag all read `n.w`/`n.h`. Introduce one function:

```js
function nodeSize(t){ return VIEW==="network" ? {w:2*dotR(t), h:2*dotR(t)} : {w:NODE_W, h:nodeHeight(t)}; }
```

and route every `n.h=nodeHeight(...)` / `n.w=NODE_W` assignment through it. With
`n.w = n.h = 2r` and `(n.x, n.y)` as the bounding-box corner, `center()`, fit, the
minimap and drag work unchanged. `border()` gets a circle branch (in network view, the
point at distance `r` from the centre toward the target) so lines meet the dot's edge.

`dotR(t) = 7 + 2.2·sqrt(degree)`, where degree is undirected join count from `undir`,
capped at 22. A leaf alias is ~9px; `DM_ORDER` (degree ~10) is ~14px.

### Layout — `computeNetwork()`

A separate force pass, not `computeOrganic()` reused. Organic spaces nodes by
`NODE_W+40` (card width), which leaves dots marooned. Same deterministic structure as
organic (fixed seed, 500 iterations, cooling), with these parameters:

- target edge length ~110px; repulsion sized for ~**label width** (the label sits to the
  right of the dot and is wider than it, so spacing has to clear text, not dots);
- a weak centring pull, as organic has;
- `resolveOverlaps` against a label-inclusive box.

It is deterministic, so the committed example HTML stays byte-stable. The layout runs
only when Network is first selected, so it adds no cost to Cards.

### Rendering — `drawNodeDot(g,n,t,stroke,sw,groupInfo)`

A third node-drawing branch in `renderNodes`, beside the card and `drawNodeBlock`. In
Network view it always wins: semantic zoom does not apply to dots.

- **Fill** by role: fact `#1E6FA8`, dim `#5B6472`, SQL view `#0D9488`, alias
  `#7C3AED` (alias wins over kind). When Group by is active, the group colour replaces
  the fill, as it does for cards.
- **Ring** (the state border): the existing `stroke`/`sw` (secured red, in-RLS-path
  amber, finding severity, focus blue), drawn with `vector-effect:non-scaling-stroke`.
  A plain node gets a white 1.5px ring so dots read on edges.
- **Label**: the table id to the right of the dot, 12px, with a white halo
  (`paint-order:stroke`) for legibility over lines. Labels are hidden below zoom
  `k<0.35` (via a class on `#viewport`, not a re-render per zoom step), the same
  threshold-crossing pattern as the existing LOD switch.
- **Note badge**: a small amber dot at the circle's upper right when the table has a
  note.
- Click, double-click and drag listeners are attached exactly as for cards (shared
  code after the branch).

### Edges in network view

- Straight lines between dot borders, stroke `#B8C0CB` at 1.2px, with no arrowhead and
  no crow's foot. The **Notation** segment is disabled in Network view. The origin badge
  (T/M) is not drawn.
- Selection, path, focus ghosting, hot-edge dashing and noted-edge amber are unchanged.
  They set `stroke`/`sw`, and network view only changes the defaults and markers.
- The transparent 16px hit path stays, so edges are still clickable.

### Toolbar

- A new **View** segment (Cards | Network) to the left of Layout.
- Disabled in Network view, at the same 0.4 opacity the Orthogonal toggle uses: the
  Layout segment, Orthogonal, Notation and the Column-mode select. Reset positions
  stays enabled and resets the network layout.
- The legend gains a network block (four fill swatches and the ring meanings), shown
  only in Network view.

## Out of scope

- Collapsing aliases into their physical table (a later toggle, on request).
- Edge bundling, label collision avoidance beyond spacing, and 3D.
- Changes to the parser, the data bundle, or `build_erd.py` flags. A `--view network`
  default for the opening view is a possible follow-up.

## Risks

| Risk | Mitigation |
|---|---|
| A missed `nodeHeight`/`NODE_W` read leaves card geometry in network view (wrong fit, wrong minimap, offset lines) | Route all of them through `nodeSize`; grep for `nodeHeight(` and `NODE_W` reads in review; screenshot-test both views |
| Labels overlap on dense hubs | Label-aware repulsion; a dense model can still overlap, and dragging fixes it (positions persist) |
| `renderer.js` keeps growing | The new code sits in three helpers (`nodeSize`, `computeNetwork`, `drawNodeDot`) plus small branches; no restructuring |
| ts-audit embeds the same renderer | It gets the view for free. Verify an audit ERD still renders in Cards by default |

## Testing

- **Python (`tests/test_render.py`)**: the rendered HTML contains the View segment and
  the `network` code path; the default view is cards.
- **Examples**: re-render both committed examples. `tests/test_examples.py` enforces
  this, and the HTML changes because the renderer does.
- **Visual**: headless-Chrome screenshots of both examples in both views. Network view
  is reached via a `#view=network` URL hash, read once on load and only when no
  localStorage choice exists, so screenshots and links can open it directly. Check
  criteria 1–4 by eye, including Cards before vs. after for criterion 4.
- **Interaction**: in a real browser on order-fulfilment, exercise select, focus tree,
  compare/path, search, Filter → Alias / RLS, Group by, drag, switching views back and
  forth with positions kept, and Share HTML.
- **Docs**: SKILL.md "ERD features" gains a Network-view bullet. Changelog 1.9.0
  (minor: a new capability). The examples README mentions the view and gets a
  network-view screenshot of order-fulfilment.
