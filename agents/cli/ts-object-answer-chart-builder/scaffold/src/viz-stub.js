// Stands in for the `viz` global that ThoughtSpot injects into a BYOC chart.
// The point is fidelity: chart.js must be written in the exact shape it will be
// pasted in, so the preview has to lie convincingly rather than offer a nicer API.
//
// What this deliberately reproduces:
//
//   1. `getDataFromSearchQuery().getData()` returns ARRAY rows — not the object
//      rows a chart library takes. Charts that assume object rows
//      break only once pasted, which is the failure this whole preview exists to
//      catch early. (Schema `type` passes through as the dataset declares it —
//      see the note above `wrapped` mode below.)

//   2. The returned object is handed to chart.js as an ARGUMENT and is never put
//      on `globalThis`. The host's documented entry point is the bare identifier
//      `viz`, and a chart reaching for `globalThis.viz` breaks on a host that
//      scopes it to the wrapper — silently, by falling back to sample rows and
//      never signalling render-complete. See the header of preview.js.

const DATA_MODES = new Set(["live", "empty", "absent", "wrapped", "noviz"]);

export function buildViz({ dataset, mode }) {
  if (!DATA_MODES.has(mode)) mode = "live";

  // 'noviz' is the plain-browser case: no host at all. A mode-C chart must still
  // render its baked-in rows; a mode-A chart must be untouched by this.
  if (mode === "noviz") return undefined;

  // ── the search-query side ────────────────────────────────────────────────
  // The host's result object: charts pull rows out with `.getData()`, which returns
  // { schema, data } with ARRAY rows in schema order.
  const schema = (dataset?.schema ?? []).map((c) => ({ ...c }));
  const columns = schema.map((c) => c.name);
  const rows = mode === "empty" ? [] : (dataset?.rows ?? []);
  const searchResult = {
    getData: () => ({ schema, data: rows.map((r) => columns.map((c) => r[c])) }),
    getSchema: () => schema,
  };

  // Some clusters hand cells back as objects instead of primitives, and `.value`
  // is occasionally a method rather than a property. `wrapped` mode reproduces
  // that on the getData() path so a chart missing its cellVal() unwrapping fails
  // here rather than on a customer's tile.
  //
  // Column `type` is left exactly as the dataset declares it. Real clusters have
  // been seen reporting both 'measure' and 'MEASURE' — charts should accept
  // either, and
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
