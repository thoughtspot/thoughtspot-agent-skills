// capture.mjs — what start-preview.mjs and snap.mjs share: the seed files, and
// the settle → screenshot → diagnose sequence for one attempt.

import fs from "node:fs";
import path from "node:path";
import { VIEWPORT } from "./env.mjs";

// A run must render something on the very first load, before any chart code is
// written — otherwise the user stares at a blank window while we think.
const SEED = {
  "chart.html": `<div id="chart"></div>\n`,
  "chart.css": `#chart { width: 100%; height: 100%; }\n`,
  "chart.js": `// Waiting for the first attempt.
const el = document.getElementById('chart');
el.textContent = 'ready';
el.style.cssText = 'display:grid;place-items:center;height:100%;color:#bbb;font:13px sans-serif';
viz.events.emitRenderCompletedEvent();
`,
};

export function seedChartFiles(chartDir) {
  fs.mkdirSync(chartDir, { recursive: true });
  const seeded = [];
  for (const [name, body] of Object.entries(SEED)) {
    const p = path.join(chartDir, name);
    if (!fs.existsSync(p)) { fs.writeFileSync(p, body); seeded.push(name); }
  }
  return seeded;
}

export function parseTile(spec) {
  const m = /^(\d+)x(\d+)$/.exec(spec ?? "");
  if (!m) throw new Error(`--tile expects WxH, e.g. 620x400 (got "${spec}")`);
  return { width: Number(m[1]), height: Number(m[2]) };
}

// Settle on the preview's own status line rather than a selector — the chart may
// be an SVG, a canvas, or a plain HTML table, and waiting for "#chart svg" would
// hang forever on the last two.
//
// Returns false when the status never reached ok/warn/error within SETTLE_MS: the
// chart hung (an unresolved await, a CDN that never answers) and render-complete
// never fired. The caller must say so loudly; a swallowed timeout reads as a
// chart that merely has not finished yet.
export const SETTLE_MS = 20000;
export async function settle(page, timeout = SETTLE_MS) {
  const settled = await page
    .waitForFunction(() => {
      const s = document.getElementById("status");
      return s && /^(ok|warn|error)$/.test(s.className);
    }, { timeout })
    .then(() => true, () => false);
  await page.waitForTimeout(700); // animations / late layout
  return settled;
}

// Resize the CONTAINER, never the window. A Liveboard tile resizes while the
// window does not, so a chart that only listens to window.resize (Plotly's and
// Chart.js's `responsive`) passes a window resize and overflows a real tile.
// Only a ResizeObserver on the container sees this change.
async function resizeTile(page, { width, height }) {
  await page.evaluate(({ width, height }) => {
    const t = document.getElementById("tile");
    Object.assign(t.style, { right: "auto", bottom: "auto", boxSizing: "border-box",
                             width: `${width}px`, height: `${height}px` });
  }, { width, height });
  await page.waitForTimeout(600);
}

// Compare the widest rendered <svg>/<canvas> with the tile it has to fit.
async function measureFit(page) {
  return page.evaluate(() => {
    const host = document.getElementById("chart-host");
    const hostW = host.getBoundingClientRect().width;
    let best = null;
    for (const el of host.querySelectorAll("svg, canvas")) {
      const r = el.getBoundingClientRect();
      if (!best || r.width > best.width) best = { width: r.width, height: r.height };
    }
    if (!best) return { verdict: "n/a (no svg or canvas)", hostW: Math.round(hostW) };
    const w = Math.round(best.width), h = Math.round(best.height);
    let verdict = "ok";
    if (w === 0 || h === 0) verdict = "blank";
    else if (w > hostW + 2) verdict = "overflow";
    return { verdict, hostW: Math.round(hostW), w, h };
  });
}

// One capture: navigate, settle, optionally resize the tile, screenshot #tile,
// and collect everything the diagnostic block prints.
export async function captureTile(page, { url, outPath, tile }) {
  const consoleErrors = [];
  const onConsole = (m) => { if (m.type() === "error") consoleErrors.push(m.text()); };
  const onPageError = (e) => consoleErrors.push(String(e.message || e));
  page.on("console", onConsole);
  page.on("pageerror", onPageError);

  try {
    if (tile) {
      // Room for the tile plus the preview's 16px margins and status line, set
      // BEFORE loading so the window never resizes after the chart has drawn.
      const vp = VIEWPORT.viewport;
      await page.setViewportSize({ width: Math.max(vp.width, tile.width + 32),
                                   height: Math.max(vp.height, tile.height + 50) });
    }
    await page.goto(url, { waitUntil: "domcontentloaded" });
    const settled = await settle(page);
    if (tile) await resizeTile(page, tile);

    const status = await page.evaluate(() => {
      const s = document.getElementById("status");
      return { text: s?.textContent ?? "", kind: s?.className ?? "" };
    });
    const diag = await page.evaluate(() => globalThis.__previewDiagnostics ?? {});
    const fit = tile ? await measureFit(page) : null;

    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    const tileEl = await page.$("#tile");
    await (tileEl ?? page).screenshot({ path: outPath });

    // timedOut: the diagnostic block prints `status: TIMEOUT ...` and the caller exits 2.
    return { status, heightChain: diag.heightChain, muze: diag.muzeRequested && diag.muze === "unavailable" ? "unavailable" : null, fit, consoleErrors, timedOut: !settled, settleMs: SETTLE_MS };
  } finally {
    page.off("console", onConsole);
    page.off("pageerror", onPageError);
    if (tile) await page.setViewportSize(VIEWPORT.viewport).catch(() => {});
  }
}

export function printDiag(result, { mode, png, userPng, dataMode, tile }) {
  console.log(`mode: ${mode}`);
  console.log(`png: ${png}`);
  if (userPng) console.log(`user-png: ${userPng}`);
  console.log(`data-mode: ${dataMode}`);
  if (result.timedOut) {
    // Unmistakable on purpose: the PNG is still written, but the chart never settled.
    console.log(`status: TIMEOUT render-complete never fired after ${Math.round(result.settleMs / 1000)}s` +
                ` (preview status stayed [${result.status.kind || "pending"}] ${JSON.stringify(result.status.text)})`);
  } else {
    console.log(`status: [${result.status.kind || "pending"}] ${result.status.text}`);
  }

  // The tile's <body> has no explicit height; the preview's #chart-host does. A
  // chart sized with `height: 100%` therefore renders here and collapses to a
  // blank tile there, with nothing in the console either side. preview.js
  // measures both, so report it rather than leaving it to the screenshot.
  // No Muze build ships with the skill. A chart that asks for Muze without one cannot render; say so, so the
  // failure is read as "not previewable here" and not as a chart defect. Silent for charts that do not use Muze.
  if (result.muze === "unavailable") console.log("muze: unavailable in this preview (no Muze build installed; see the doctor's muze line). A Muze chart cannot be verified here: report it as not previewed and check it in ThoughtSpot");

  const hc = result.heightChain;
  if (hc) {
    console.log(
      hc.broken
        ? `height-chain: BROKEN - #chart is ${hc.sized}px here but collapses to ` +
          `${hc.collapsed}px against a parent with no explicit height, which is what a ` +
          `ThoughtSpot tile's <body> is. Add \`html, body { height: 100% }\` to chart.css.`
        : `height-chain: ok (${hc.sized}px sized / ${hc.collapsed}px unparented)`
    );
  }

  if (tile) {
    const f = result.fit;
    console.log(`tile: ${tile.width}x${tile.height}`);
    console.log(
      f.w === undefined
        ? `svg-fit: ${f.verdict}`
        : `svg-fit: ${f.verdict} (widest mark ${f.w}x${f.h}px in a ${f.hostW}px tile)` +
          (f.verdict === "overflow" ? " - no ResizeObserver on the container" : "") +
          (f.verdict === "blank" ? " - canvas shadowing or a zero-size stage" : "")
    );
  }

  if (result.consoleErrors.length) {
    console.log(`console-errors (${result.consoleErrors.length}):`);
    for (const e of result.consoleErrors.slice(0, 10)) console.log(`  - ${e}`);
  } else {
    console.log("console-errors: none");
  }
}
