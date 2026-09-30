# Vendored Muze build

`muze.js`, `muze.css` and `assets/transform-data-worker-*.js` are a prebuilt Muze
bundle, vendored so the preview runs the same synchronous Muze API that a
ThoughtSpot BYOC tile exposes as `viz.muze` (`DataModel.loadDataSync`). The public
CDN build, `@chartshq/muze` 2.x, is the asynchronous API and would validate charts
that cannot run on a tile.

It is used only by the local preview. Nothing in it is copied into a chart's
deliverables — ThoughtSpot supplies Muze to the chart at run time.

**License: not yet confirmed.** `@chartshq/muze` declares no `license` field in its
npm metadata (checked 2026-09-29), and this bundle carries no license header.
Confirm the terms with the Muze owners before redistributing this folder outside
ThoughtSpot, and replace this section with the license text.
