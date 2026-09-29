# Emit checklist — before handing the three files over

The preview runs the same three files, through a `viz` stub, inside an
`AsyncFunction` — the same shape the host uses. So unlike the older
image-to-Studio pipeline there is **no porting step**: what iterated is what ships.
`<RUNS>/<SLUG>/chart/*` are the deliverables, copied to `<OUT>/<SLUG>/` unchanged,
alongside `preview.png` (the passing attempt's screenshot) and the run README.

That makes this a verification pass, not a transformation. Work down it once.

## 1. The preview stub is not the host

Three differences the loop cannot catch. Check them by reading.

- **Muze version.** The preview runs the vendored bundle in `scaffold/vendor/muze/`;
  the host ships its own build, which may be older or newer. If the chart leans on a
  rarely-used option, say so in the run README rather than implying it is verified.
- **Theme.** `preview/index.html` supplies `.muze-*` CSS the host provides itself.
  Those rules are preview-only — if any of them leaked into `chart.css`, remove them.
- **Real data.** The stub serves `sample-data.json`. Column names, null density, row
  counts, and cardinality on a real search will differ.

## 2. Structural

- [ ] `chart.html` has no `<!DOCTYPE>`, `<html>`, `<head>`, or `<body>`. A CDN
      library's `<script src>` **does** belong here — that is the host's documented
      shape — with the bounded dynamic loader in `chart.js` as the fallback.
- [ ] `chart.css` completes the height chain: `html, body { height: 100% }` for any
      percentage-height layout, or `100vh` on `#chart`. The tile's `<body>` has no
      height of its own, so `#chart { height: 100% }` alone collapses to a blank
      tile. Confirmed by the `height-chain:` line in the snap output, not by eye —
      the preview's wrappers make a broken chart look correct.
- [ ] `chart.js` has no `<script>` tag and no literal `</script>` in any comment.
- [ ] `chart.js` is not wrapped in an async IIFE.
- [ ] Everything mounts into `#chart`.
- [ ] No static markup built via `innerHTML` / `createElement` that belongs in `chart.html`;
      no fixed styling set from JS that belongs in `chart.css`.
- [ ] All three files are pure ASCII — one sweep catches smart quotes, em dashes and
      the literal non-breaking space that browser textareas eat in transit:
      ```bash
      LC_ALL=C grep -n '[^ -~]' <OUT>/<SLUG>/chart.js <OUT>/<SLUG>/chart.css <OUT>/<SLUG>/chart.html
      ```
- [ ] `chart.js` resolves its mount points inside boot and creates any that are
      missing, so pasting the JS tab alone still renders. Verified by emptying
      `chart.html` and re-snapping, not by reading.

## 3. The BYOC contract

- [ ] `const { muze, getDataFromSearchQuery } = viz;` (or the guarded mode-C form) —
      reading the **bare identifier**. Grep for `globalThis.viz` as the sole route
      in: on a host that scopes `viz` to its wrapper it resolves to `undefined`, and
      the chart silently serves sample rows *and* never signals render-complete.
- [ ] `viz.events.emitRenderCompletedEvent()` on the success path **and** in `catch`,
      and the failure `console.warn`s rather than being swallowed by `catch {}`.
- [ ] Render wrapped in `try/catch` that paints `err.stack` into `#chart`.
- [ ] `DATA_MODE` present and set to the mode the user asked for.
- [ ] Live rows unwrapped through `cellVal()` before use.
- [ ] Epoch-millisecond dimensions formatted, not printed raw.
- [ ] Any CDN load is bounded by a timeout and lists a second host. An unbounded
      injection that hangs never settles, so render-complete never fires and the
      host shows a bare "Chart did not render".
- [ ] The `catch` paints through a fallback chain (`stage -> #chart -> body`), not
      through the one element whose absence caused the throw.

## 4. Verified in the loop, not assumed

- [ ] Snapped clean in `--data live`.
- [ ] Snapped in `--data absent` — mode C falls back and shows the sample badge;
      mode B degrades to a readable message, not a blank tile or a stack trace.
- [ ] Snapped in `--data wrapped` — object cells handled.
- [ ] Snapped in `--data noviz` — no host at all. Mode C renders its baked-in rows;
      nothing throws. (The render-complete warning is expected here — there is no
      host to signal.)
- [ ] Resized the **container**, not the window — no blank tile (canvas shadowing)
      and no overflow (missing `ResizeObserver`).
- [ ] `height-chain: ok` in the final snap output.
- [ ] `console-errors: none` in the final snap output.
- [ ] Status line reads `ok`, not the `emitRenderCompletedEvent() was never called`
      warning and not the `height chain incomplete` error.

## 5. Readability

- [ ] Column names live in UPPER_SNAKE_CASE constants, used everywhere.
- [ ] Non-default colors, labels, precision, thresholds are in one `// ─── Customize ───`
      block — and that block is absent entirely if there was nothing to put in it.
- [ ] Config that could be deleted without changing the render has been deleted.
- [ ] No `console.log`, debug overlays, or commented-out experiments.

## 6. The run README

`<OUT>/<SLUG>/README.md` must state:

- the search the user has to build — every column the field constants name, in TS's
  own naming;
- any prior-period selections needed for `vs. Last …` columns;
- which data mode the file is in, and how to change it;
- anything the chart could not reproduce, called out rather than quietly approximated;
- paste instructions: chart.html → HTML tab, chart.css → CSS tab, chart.js → JS tab.
