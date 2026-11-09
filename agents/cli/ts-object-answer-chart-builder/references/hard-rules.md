# Hard rules — what breaks, and how it shows up in the preview

Every entry here is a silent failure: the code looks right. What makes them worth a
file is that most are invisible in a screenshot, so the iterate loop will happily
converge on a chart that is broken. Each rule below says how to *detect* it, not just
what to avoid.

The MayaCharts section of `references/library-starters.md` has the worked starter for the
MayaCharts ones. Read it when a rule bites and the fix is not obvious.

---

## Breaks only after paste — the preview cannot see these

The preview stubs `viz`, so anything about the real host's behaviour has to be caught
by reading the code, not the screenshot. Check these before emitting final files.

| Rule | Why |
|---|---|
| `viz?.getDataFromSearchQuery?.()` — **bare `viz`, never `globalThis.viz`** | See the entry below; this one has shipped a broken tile. |
| `viz.events.emitRenderCompletedEvent()` on **both** the success and `catch` paths | Liveboard PDF export blocks until every tile reports in. One silent tile means no PDF for the whole Liveboard. The preview's status line warns when it never fires. |
| Wrap the render in `try/catch` and paint `err.stack` into `#chart` | The BYOC sandbox replaces real errors with "Something went wrong". |
| Never a literal `</script>` — not even inside a comment | Breaks the host's HTML parser. |
| No `<!DOCTYPE>` / `<html>` / `<head>` / `<body>` in chart.html | The host wraps it. |
| Do not wrap chart.js in an async IIFE | The host already does. Top-level `await` and `return` work as-is. |
| Two same-named columns in one search collide (one overwrites the other in every row object) | Fix the search to give unique names — not the chart code. |
| `vs. Last Month` / `vs. Last Year` columns arrive empty unless the search selects the prior period | Nothing the chart can do about it; say so in the run README. |
| Table-mode column format (currency, percent) does **not** reach the chart | Format in the chart (MayaCharts: `format`, with Intl options for compact money). |
| Non-ASCII `·` or `—` in titles render as `Â·` | ASCII only. |
| No literal U+00A0 anywhere in the three files — write ` ` | The files are pasted through a browser textarea, which is exactly where a literal non-breaking space gets normalised to a plain space. Ironic failure mode: the character silently disappears from the guard written to handle it. Sweep with `LC_ALL=C grep -n '[^ -~]' chart.*`. |
| A CDN load must be **bounded** and must list a fallback host | `onerror` covers a blocked host. A request that *hangs* fires neither `onload` nor `onerror`, so the promise never settles, top-level `await` never returns, `emitRenderCompletedEvent()` never fires, and the host shows a bare "Chart did not render" over an empty tile. Wrap the injection in a `setTimeout` reject and try a second CDN. |
| Every CDN URL pins an **exact version** and carries its **sha384 integrity** | `d3@7` or an unversioned URL changes a saved tile under the user the day the package ships, and a URL with no `integrity` runs whatever the CDN serves. Pin `x.y.z`, put `integrity="sha384-..." crossorigin="anonymous"` on the `<script>` tag, and pass the same value to the loader (`AZ.maya` carries it for MayaCharts; `AZ.loadScript([{ src, integrity }])` otherwise). The doctor prints it for MayaCharts; for anything else: `curl -sL <url> \| openssl dgst -sha384 -binary \| openssl base64 -A`. Fonts from Google Fonts are CSS generated per browser and cannot carry one. |
| `chart.js` must build its own mount points if they are missing | The host assembles the three tabs and the order is not contractual. `document.getElementById('chart')` at module scope returns `null` when the JS evaluates before the HTML tab's markup lands, or when someone pastes only the JS. The library then throws on a null container, the `catch` guard `if (el)` skips painting, and the tile is blank with no error anywhere. Resolve elements inside boot and `createElement` whatever is absent. |
| Error painting must not depend on the element that failed | `catch { if (stageEl) stageEl.innerHTML = err.stack }` paints nothing when `stageEl` is the null that caused the throw. Fall back `stage -> #chart -> document.body`. |
| A CDN library's `<script src>` belongs in **chart.html**, with the dynamic loader as the fallback | The host's documented shape is the CDN URL in the HTML tab, and every chart that has actually run on a tile does it that way. The HTML tab executes script tags. Keep the bounded dynamic loader too — some clusters serve the tabs in an order that leaves the tag unfinished, and a chart with only one of the two paths has a single point of failure. If both are present, poll for `window.<Lib>` before injecting, or the tile downloads the library twice. |

## Verified in a real cluster (release 26.8) - the preview cannot tell you these

Found by screenshotting a Liveboard in a logged-in browser with `helpers/cluster-shot.mjs`.

| Rule | Why |
|---|---|
| **`fetch()` to any external URL is blocked** ("Network requests are blocked for security. Charts cannot make ...") | Tiles run in a sandboxed iframe. Inline every data file, GeoJSON and topology in `chart.js` (see `library/_shared/us-states.js`). The preview happily fetches, so a chart that fetches passes locally and paints an error on the tile. |
| `<script src>` from cdn.jsdelivr.net and unpkg **does** load (d3@7, echarts@5, topojson-client@3 verified; mayacharts uses the same host) | Use it for libraries; keep the bounded `AZ.loadScript` fallback. |
| Tile size is decided by the Liveboard, not the window | Observe `#chart` with a `ResizeObserver` (the shared core does), never `document.body`. |
| A validate-only TML import is still a "write" to the MCP tool | Pass `confirm_write_operations: true`; `VALIDATE_ONLY` changes nothing. |
| The MCP sandbox has no network except the cluster and no memory between calls | Do not send a whole Liveboard's base64 in one call. Patch the Liveboard in sha256-checked blocks that export, replace and re-import it server side: `ts-object-liveboard-chart-builder` (`liveboard-pack.mjs`, `patch.js`). Create no helper objects. |
| CSS `@media` width queries never fire in the preview | `snap --tile` and `probe --tile` resize the tile container, not the window, exactly as a Liveboard does. Toggle a class from the measured width in JS (`w` from the boot context) instead of relying on `@media`. |
| `String.raw` transport: no backtick and no `${` anywhere in a chart | The chart source is pasted verbatim into a template literal; `liveboard-pack.mjs` lints for it. Build strings with `+`. |
| `String.prototype.replace(str, replacement)` treats `$'` and `$&` in the replacement as patterns | Generating chart code that contains `'$' + x` corrupted a file silently. Use a function replacement: `.replace(a, () => b)`. |
| **Import size ceiling.** A commit of about 2.8 MB of TML reset the connection (`ECONNRESET`); 1.8 MB imported | Strip full-line comments and indentation from shipped code (`liveboard-pack.mjs` does), share code between tiles with `.use`, and keep a Liveboard under about 2 MB of TML. Chart files stay ASCII with no template strings so the trim is safe. |
| A validate-only or dry run does not prove a commit fits | Size is the first suspect for a network reset on import; run `MODE = 'dry'` and read `tmlKB` before committing. |
| Text you fill in decides the size of what you measure | Populate header, legend and axis text first, then `await AZ.settle()`, then read `clientWidth` and `clientHeight`. Measuring before that lays the plot out against the wrong box. |
| Entrance animation may only change opacity, and never on `.az-tip` | A fill-mode animation on the tooltip pins it visible. The core's `#chart.az-in > *:not(.az-tip)` rule is the fix; do not undo it. |
| ECharts with `animation: false` and a redraw per drill has no zoom | For an animated drill, use Plotly's sunburst or treemap (`Plotly.restyle(gd, { level: [id] })` plus `layout.transition`), or tween your own marks with `AZ.tween`. |

## The two that shipped a blank tile — read these twice

Both were invisible in the preview *by construction*: the harness supplied the very
thing the host does not. Both are now instrumented (`snap.mjs` prints a
`height-chain:` line, and `viz` is passed as a parameter with no global), but the
rules stand on their own.

### `html, body { height: 100% }` in chart.css is load-bearing

A percentage height resolves only against an ancestor chain that is definite the
whole way up. On a tile, `#chart` is a child of `<body>`, and **that body has no
explicit height**. So `#chart { height: 100% }` on its own computes to the *content*
height — the chart runs perfectly, `emitRenderCompletedEvent()` fires, the console is
clean, and the tile is blank because the stage inside it is 0px tall.

```css
/* Option A — explicit chain (what every chart that works on a tile uses) */
html, body { height: 100%; margin: 0; }
#chart      { height: 100%; }

/* Option B — viewport unit; robust to whatever the host wraps #chart in */
#chart      { height: 100vh; }
```

Content-sized charts (KPI cards, quote cards) want the opposite — `height: auto` and
a content-driven `min-height`. The rule only bites percentage-height layouts.

The sibling trap in a chart-plus-KPI-strip layout is the missing `min-height: 0`:
without it a flex child never shrinks below its content size and the chart area does
not re-fit on resize.

```css
#chart            { display: flex; flex-direction: column; height: 100%; }
.chart-wrap       { flex: 1 1 0; min-height: 0; position: relative; }
.metrics          { flex: 0 0 auto; }
```

**Detect it:** the `height-chain:` line in the snap diagnostic block. It reports
`BROKEN` with both measurements. Do not rely on the screenshot — the preview's own
wrappers make the chart look right.

### `globalThis.viz` is not the same as `viz`

The documented entry point is the **bare identifier**. A host that hands the JS tab
its `viz` as a wrapper argument rather than a global leaves `globalThis.viz`
undefined, and the failure is silent in two directions at once:

- `loadRows()` sees no `getDataFromSearchQuery`, falls back to the baked-in rows, and
  the tile shows plausible **sample numbers** instead of the search's;
- `try { globalThis.viz.events.emitRenderCompletedEvent(); } catch {}` throws into the
  empty catch, so the tile **never reports in** — which is precisely the state the
  host renders as "Chart did not render", and which hangs Liveboard PDF export.

Resolve it so both host shapes work. `typeof` is not enough on its own: on a `let` or
`const` still in its temporal dead zone, `typeof` *throws*.

```js
function getViz() {
  try { if (typeof viz !== 'undefined' && viz) return viz; } catch (e) {}
  try { if (globalThis.viz) return globalThis.viz; } catch (e) {}
  return null;
}
```

And never swallow the emit failure — `console.warn` in the catch, so the one thing
that explains a hung tile is not deleted on the way out.

**Detect it:** the preview passes `viz` as a parameter and deliberately does not set
the global. A chart reading `globalThis.viz` shows the sample-data badge in
`--data live` and trips the `emitRenderCompletedEvent() was never called` status.

## Visible in the preview if you look for it

| Rule | How it shows |
|---|---|
| MayaCharts: render-complete from `maya-render` or `customElements.whenDefined` | Both fire before the chart has finished drawing: `whenDefined` before the first draw when the JS runs before the library has loaded (measured: 0 marks), `maya-render` while the entrance animation still has up to 1.5 s to run. A PDF export or screenshot taken then catches a half-drawn tile. Use `maya.host.thoughtspot` (it waits), or signal on `maya-settled`. |
| MayaCharts: a field the search renamed (`Total Sales`, not `Sales`) | The element paints its own error naming the fields it found (`unknown-field`). Use the names the search returns. |
| MayaCharts: marks live in the element's shadow root | `document.querySelector` from a probe `--eval` finds nothing; go through `.shadowRoot`. `probe.mjs` and `svg-fit` already look inside. |
| A temporal field typed `type: 'measure'` | Dates are summed or plotted as numbers. Keep dates dimensions. |

## Crashes — the preview shows the stack, so these are cheap

- Passing an object-wrapped cell into gridjs, MayaCharts or a formatter — an opaque error or `non-numeric-y`. Unwrap cells (`AZ.cellVal`) and run `--data wrapped` to catch it.
- Invented methods. `canvas.onready()`, `waitForLib()` and friends do not exist; read the library's own reference.

## The CDN-library sibling: `responsive: true` is not enough

A chart that does not follow its container does not blank the tile, it clips it, so it
is easy to miss.

Plotly's `responsive: true` and the Chart.js equivalent listen to **`window.resize`
only**. A Liveboard tile changes size while the window does not: drag-resize,
layout edits, a PDF export at a different geometry. The library keeps its old
dimensions and overflows a container that shrank around it.

Measured, resizing the container rather than the window:

```
with a ResizeObserver:  stage=596x648  svg=596x648   fits
without:                stage=596x648  svg=1222x616  overflows
```

Any CDN chart library mounted in a tile needs a `ResizeObserver` on its own
container, debounced through `requestAnimationFrame`:

```js
resizeObs = new ResizeObserver(() => {        // module-scope binding, not `const`
  if (pending) cancelAnimationFrame(pending);
  pending = requestAnimationFrame(() => { Plotly.Plots.resize(stageEl); });
});
resizeObs.observe(stageEl);
```

**Detect it:** set `el.style.width = '620px'` and compare the library's rendered
`svg` width against the container's. Do not resize the OS window for this — see
step 6 in `SKILL.md` for why that test lies.

## Defaults first

MayaCharts renders a complete chart from `type`, `x`, `y` and `data`: axis names from field names (or `titles`),
gridlines, a tooltip, keyboard focus. Before adding any spec key, ask whether deleting it changes the render. If
not, delete it.

- `format` only when the default reads badly (`$1,000,000` on an axis wants compact money).
- `colors` / `theme` only to match the house style (ink, slate, the family hues), not to decorate.
- `grid: false`, `legend: false`, `xAxis: false` only when the default is wrong.
- **No `title` on a Liveboard tile**: the tile draws its own, so a chart-internal one is a duplicate header (seen on a live Liveboard as two
  titles stacked in every tile). A `subtitle` is fine when it adds something the tile title does not. Plain ASCII strings.
