// Composes the three files the way the ThoughtSpot host does, so what renders
// here is what renders on a tile:
//
//   chart.html → injected into #chart-host
//   chart.css  → a <style> in <head>
//   chart.js   → run as an async function body (NOT an ES module), with `viz`
//                passed in as a PARAMETER
//
// Two things there are deliberate and load-bearing.
//
// 1. The host wraps the JS tab in an async IIFE, which is why top-level `await`
//    and top-level `return` both work in a BYOC chart and would be syntax errors
//    in a module. Handing the text to AsyncFunction reproduces that exactly.
//
// 2. `viz` arrives as an argument, and is deliberately NOT set on `globalThis`.
//    ThoughtSpot's documented entry point is the bare identifier
//    (`const { muze, getDataFromSearchQuery } = viz;`). A chart that reads
//    `globalThis.viz` instead passes a preview that publishes the global and
//    then, on a host that scopes `viz` to the wrapper, silently falls back to
//    sample rows and never fires emitRenderCompletedEvent. Withholding the
//    global is what makes that failure visible here instead of on a tile.

import muze from "../vendor/muze/muze.js";
import { buildViz } from "./viz-stub.js";

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

const params = new URLSearchParams(location.search);
const dataMode = params.get("data") ?? "live";

const statusEl = document.getElementById("status");
const hostEl = document.getElementById("chart-host");

// Read by snap.mjs and printed in the diagnostic block.
globalThis.__previewDiagnostics = { heightChain: null };

function setStatus(text, kind = "") {
  statusEl.textContent = text;
  statusEl.className = kind;
}

function showError(label, err) {
  console.error(`[preview] ${label}:`, err);
  setStatus(`${label}: ${err?.message ?? err}`, "error");
  const pre = document.createElement("pre");
  pre.className = "preview-error";
  pre.textContent = (err?.stack || String(err));
  hostEl.appendChild(pre);
}

async function text(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} for ${url}`);
  return r.text();
}

// On a tile, `#chart` is a child of `<body>`, and that body has no explicit
// height. A percentage height resolves only against an ancestor chain that is
// definite all the way up, so `#chart { height: 100% }` alone computes to the
// content height there — the chart runs perfectly, draws into a ~0px stage, and
// the tile is blank with nothing in the console. `html, body { height: 100% }`
// in chart.css is what completes the chain.
//
// The preview cannot see that passively: #chart sits inside #chart-host inside a
// pixel-sized #tile, so the chain is already complete here and the bug is
// structurally invisible.
//
// Reproducing it means matching the tile's ANCESTRY, not just zeroing a height.
// Setting the two wrappers to `display: contents` removes their boxes from the
// layout tree entirely, which makes `<body>` the containing block for #chart —
// exactly the host's shape. Whether the chart then keeps its height is decided
// by chart.css's own html/body rule, which is the thing under test.
//
// (An earlier version just set #chart-host to `height: auto`. That flags every
// chart, correct or not: an unsized wrapper the host does not have breaks the
// percentage chain no matter what chart.css declares.)
//
// Both reads force synchronous layout and the restore lands in the same task, so
// no ResizeObserver ever sees the intermediate geometry.
function probeHeightChain() {
  const el = document.getElementById("chart") ?? hostEl.firstElementChild;
  if (!el) return null;

  const sized = el.getBoundingClientRect().height;

  const saved = [];
  for (const anc of [document.getElementById("tile"), hostEl]) {
    if (!anc) continue;
    saved.push([anc, anc.style.cssText]);
    anc.style.position = "static";
    anc.style.display = "contents";
  }
  const collapsed = el.getBoundingClientRect().height;
  for (const [anc, css] of saved) anc.style.cssText = css;

  // Compare proportionally, not against a floor. A chart with a breadcrumb or a
  // header does not collapse to zero — it collapses to its header, with the
  // `flex: 1` chart stage inside it at 0px. That is just as blank on a tile and
  // an absolute threshold misses it entirely.
  //
  // Charts that size themselves by content (KPI cards, quote cards) measure the
  // SAME both ways, so the ratio is 1 and nothing is reported.
  const broken = sized > 40 && collapsed < sized * 0.75;
  return { sized: Math.round(sized), collapsed: Math.round(collapsed), broken };
}

async function main() {
  setStatus("loading…");

  // Dataset is optional — a chart in sample-only mode does not need one.
  let dataset = null;
  try {
    dataset = JSON.parse(await text("/sample-data.json"));
  } catch {
    console.warn("[preview] no sample-data.json — live-data modes will be empty");
  }

  const viz = buildViz({ muze, dataset, mode: dataMode });

  let html = "", css = "", js = "";
  try {
    [html, css, js] = await Promise.all([
      text("/chart/chart.html"),
      text("/chart/chart.css"),
      text("/chart/chart.js"),
    ]);
  } catch (err) {
    showError("could not load chart files", err);
    return;
  }

  hostEl.innerHTML = html;

  // innerHTML does not execute <script> tags. The host's HTML tab does run them,
  // and that is the documented way to pull in a CDN library — so re-inject any
  // the chart declared, or the preview would exercise only the JS fallback path.
  for (const old of hostEl.querySelectorAll("script")) {
    const s = document.createElement("script");
    for (const { name, value } of old.attributes) s.setAttribute(name, value);
    s.textContent = old.textContent;
    old.replaceWith(s);
  }

  const style = document.createElement("style");
  style.id = "chart-css";
  style.textContent = css;
  document.head.appendChild(style);

  let completed = false;
  globalThis.addEventListener("preview:render-completed", () => {
    completed = true;
  });

  try {
    // `viz` as a parameter, never as a global — see the header note.
    await new AsyncFunction("viz", js)(viz);
  } catch (err) {
    // The real BYOC sandbox swallows this into "Something went wrong". Showing the
    // stack is the whole reason to iterate here instead of on a tile.
    showError("chart.js threw", err);
    return;
  }

  const heightChain = probeHeightChain();
  globalThis.__previewDiagnostics.heightChain = heightChain;

  // A chart that renders but never signals completion hangs Liveboard PDF export.
  // Silent in the host; loud here.
  setTimeout(() => {
    if (heightChain?.broken) {
      setStatus(
        `height chain incomplete — #chart is ${heightChain.sized}px here but ` +
        `collapses to ${heightChain.collapsed}px on a tile · data=${dataMode}`,
        "error"
      );
      return;
    }
    if (!completed) {
      setStatus(
        `rendered, but emitRenderCompletedEvent() was never called · data=${dataMode}`,
        "warn"
      );
      return;
    }
    setStatus(`rendered · data=${dataMode}`, "ok");
  }, 1200);
}

// The headed window reloads itself when a chart file changes, so the user sees
// each attempt land. The chart files are fetched as text, not imported, so there
// is no module graph to watch — poll the server's newest mtime instead. Only the
// daemon's window asks for this; a one-shot capture never polls.
function watchForEdits() {
  let last = null;
  setInterval(async () => {
    try {
      const { mtime } = await (await fetch("/__mtime", { cache: "no-store" })).json();
      if (last !== null && mtime !== last) location.reload();
      last = mtime;
    } catch {}
  }, 1000);
}

if (params.get("watch") === "1") watchForEdits();
main().catch((err) => showError("preview failed", err));
