// Stands in for the `viz` global that ThoughtSpot injects into a BYOC chart.
// The point is fidelity: chart.js must be written in the exact shape it will be
// pasted in, so the preview has to lie convincingly rather than offer a nicer API.
//
// Two things this deliberately reproduces:
//
//   1. `viz.muze.canvas()` — BYOC hands you an object you call `.canvas()` on
//      directly. The CDN build is a factory you call first (`muze().canvas()`).
//      The shim below hides that difference so chart code never carries a
//      standalone-only line that has to be stripped on the way out.
//
//   2. `getDataFromSearchQuery().getData()` returns ARRAY rows — not the object
//      rows that `DataModel.loadDataSync` takes. Charts that assume object rows
//      break only once pasted, which is the failure this whole preview exists to
//      catch early. (Schema `type` passes through as the dataset declares it —
//      see the note above `wrapped` mode below.)

//   3. The returned object is handed to chart.js as an ARGUMENT and is never put
//      on `globalThis`. The host's documented entry point is the bare identifier
//      `viz`, and a chart reaching for `globalThis.viz` breaks on a host that
//      scopes it to the wrapper — silently, by falling back to sample rows and
//      never signalling render-complete. See the header of preview.js.

const DATA_MODES = new Set(["live", "empty", "absent", "wrapped", "noviz"]);

export function buildViz({ muze, dataset, mode }) {
  if (!DATA_MODES.has(mode)) mode = "live";

  // 'noviz' is the plain-browser case: no host at all. A mode-C chart must still
  // render its baked-in rows; a mode-A chart must be untouched by this.
  if (mode === "noviz") return undefined;

  // ── muze shim: viz.muze.canvas() over the CDN factory ────────────────────
  // Object.create keeps DataModel, Operators, Themes, and friends reachable
  // through the prototype chain, so only `canvas` needs overriding.
  let muzeShim = null;
  if (muze) {
    const env = typeof muze === "function" ? muze() : muze;
    muzeShim = Object.create(muze);
    muzeShim.canvas = () => env.canvas();
    if (!muzeShim.DataModel && muze.DataModel) muzeShim.DataModel = muze.DataModel;
  }

  // ── the search-query side ────────────────────────────────────────────────
  // The host returns a real DataModel: charts either hand it straight to
  // `.data(dm)` or pull rows out with `.getData()`. Both have to work, so build
  // an actual DataModel rather than a lookalike — a plain object would let a
  // chart pass the preview and then fail on `.data()` at paste time.
  const schema = (dataset?.schema ?? []).map((c) => ({ ...c }));
  const columns = schema.map((c) => c.name);
  const rows = mode === "empty" ? [] : (dataset?.rows ?? []);

  let searchResult;
  if (muzeShim?.DataModel) {
    const { DataModel } = muzeShim;
    searchResult = new DataModel(DataModel.loadDataSync(rows, schema));
  } else {
    searchResult = {
      getData: () => ({ schema, data: rows.map((r) => columns.map((c) => r[c])) }),
      getSchema: () => schema,
    };
  }

  // Some clusters hand cells back as objects instead of primitives, and `.value`
  // is occasionally a method rather than a property. `wrapped` mode reproduces
  // that on the getData() path so a chart missing its cellVal() unwrapping fails
  // here rather than on a customer's tile.
  //
  // Column `type` is left exactly as the dataset declares it. Real clusters have
  // been seen reporting both 'measure' and 'MEASURE' — charts should accept
  // either (see examples/table-pivot/pivot-table/pivot-table.js), and
  // the stub picking one would hide that.
  if (mode === "wrapped") {
    const inner = searchResult.getData.bind(searchResult);
    searchResult.getData = () => {
      const out = inner();
      return {
        ...out,
        data: out.data.map((r) =>
          r.map((v) =>
            v === null || v === undefined
              ? v
              : { value() { return v; }, formatted: String(v) }
          )
        ),
      };
    };
  }

  const viz = {
    // A getter, so the diagnostics know whether the chart asked for Muze at all: the "no Muze build" warning
    // is only meaningful for a chart that uses it.
    get muze() { globalThis.__previewDiagnostics && (globalThis.__previewDiagnostics.muzeRequested = true); return muzeShim; },
    events: {
      // The real host uses this to decide a tile is done; Liveboard PDF export
      // blocks until every tile reports in. Surfaced in the status bar so a
      // chart that forgets to call it is visible at a glance.
      emitRenderCompletedEvent() {
        globalThis.__renderCompleted = true;
        globalThis.dispatchEvent(new CustomEvent("preview:render-completed"));
      },
    },
  };

  // 'absent' drops the function entirely — a tile with no search bound to it.
  // A mode-C chart must still render from its baked-in sample rows.
  if (mode !== "absent") viz.getDataFromSearchQuery = () => searchResult;

  return viz;
}
