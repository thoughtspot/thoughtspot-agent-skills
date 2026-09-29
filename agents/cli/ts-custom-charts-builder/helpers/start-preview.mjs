#!/usr/bin/env node
// start-preview.mjs <slug> [--port 5173] [--cdp-port 9222] [--data live|empty|absent|wrapped|noviz]
//                          [--window-pos 900,100] [--window-size 1100,800]
//
// Long-running daemon, spawned in the background. It:
//   1. seeds <runs>/<slug>/chart/{chart.html,chart.css,chart.js} if absent,
//   2. serves the scaffold and the run dir (serve.mjs — no install, no copy),
//   3. opens a headed Chromium the user can watch, reloading it when a chart
//      file changes,
//   4. writes <runs>/<slug>/.preview/{cdp.json,daemon.pid} for snap/close,
//   5. stays alive — the browser dies with this process.
//
// Headed is preferred. When it cannot work — no display (the Claude app), or a
// headed launch that fails — it prints a `headless fallback` line and exits 0.
// snap.mjs then captures with its own headless browser, so the loop continues.

import fs from "node:fs";
import path from "node:path";
import { seedChartFiles } from "./capture.mjs";
import { launchOptions, loadPlaywright, resolveBrowser, resolveEnv, VIEWPORT } from "./env.mjs";
import { startServer } from "./serve.mjs";

function parseArgs(argv) {
  const args = { slug: null, port: 5173, cdpPort: 9222, data: "live",
                 windowPos: "900,100", windowSize: "1100,800" };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--port") args.port = Number(argv[++i]);
    else if (a === "--cdp-port") args.cdpPort = Number(argv[++i]);
    else if (a === "--data") args.data = argv[++i];
    else if (a === "--window-pos") args.windowPos = argv[++i];
    else if (a === "--window-size") args.windowSize = argv[++i];
    else if (!args.slug) args.slug = a;
  }
  if (!args.slug) {
    console.error("usage: start-preview.mjs <slug> [--port N] [--cdp-port N] [--data live|empty|absent|wrapped|noviz]");
    process.exit(2);
  }
  return args;
}

function fallback(reason) {
  console.log(`[start-preview] ${reason} - headless fallback; snap.mjs launches its own browser per capture`);
  process.exit(0);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const env = resolveEnv({ slug: args.slug });
  fs.mkdirSync(env.attemptsDir, { recursive: true });
  fs.mkdirSync(env.previewDir, { recursive: true });
  seedChartFiles(env.chartDir);

  if (env.headless) fallback(env.display ? "TS_CHART_HEADLESS=1" : "no display");

  const pw = await loadPlaywright(env);
  if (!pw) { console.error("[start-preview] playwright not found - run: node env.mjs"); process.exit(1); }
  const browserExe = resolveBrowser(pw);
  if (!browserExe) { console.error("[start-preview] no Chromium found - run: node env.mjs"); process.exit(1); }

  // Fail fast if the port is taken, as Vite's --strictPort did: a second daemon
  // on another port would leave cdp.json pointing at the wrong one.
  const server = await startServer({ scaffoldDir: env.scaffoldDir, runDir: env.runDir, port: args.port })
    .catch((e) => { console.error(`[start-preview] port ${args.port}: ${e.message}`); process.exit(1); });
  const url = `${server.url}/?data=${args.data}`;
  console.log(`[start-preview] serving ${url}`);

  const [px, py] = args.windowPos.split(",").map(Number);
  const [pw_, ph] = args.windowSize.split(",").map(Number);

  // --remote-debugging-port so snap.mjs can attach over CDP and see these same
  // pages. chromium.connect()'s WS endpoint isolates contexts per client; CDP
  // shares them.
  let browser;
  try {
    browser = await pw.chromium.launch(launchOptions(browserExe, {
      headless: false,
      extraArgs: [`--window-position=${px},${py}`, `--window-size=${pw_},${ph}`,
                  `--remote-debugging-port=${args.cdpPort}`],
    }));
  } catch (e) {
    await server.close();
    fallback(`headed launch failed (${String(e.message || e).split("\n")[0]})`);
  }

  // Explicit viewport so a headed capture and a headless one are the same size.
  const ctx = await browser.newContext(VIEWPORT);
  const page = await ctx.newPage();
  for (const p of browser.contexts().flatMap((c) => c.pages())) if (p !== page) await p.close().catch(() => {});
  // ?watch=1 makes the page poll /__mtime and reload itself when a chart file
  // changes, so the user sees each attempt land.
  await page.goto(`${url}&watch=1`, { waitUntil: "domcontentloaded" });

  fs.writeFileSync(
    path.join(env.previewDir, "cdp.json"),
    JSON.stringify({ cdpUrl: `http://localhost:${args.cdpPort}`, url, previewPort: server.port,
                     cdpPort: args.cdpPort, data: args.data, mode: "headed" }, null, 2)
  );
  fs.writeFileSync(path.join(env.previewDir, "daemon.pid"), String(process.pid));

  console.log(`[start-preview] browser open, PID ${process.pid}`);
  console.log(`[start-preview] close with: node close-preview.mjs ${args.slug}`);

  const keepalive = setInterval(() => {}, 60000);
  const shutdown = async (why) => {
    console.log(`[start-preview] ${why}, shutting down`);
    clearInterval(keepalive);
    try { await browser.close(); } catch {}
    try { await server.close(); } catch {}
    process.exit(0);
  };
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));
  browser.on("disconnected", () => shutdown("browser closed"));
}

main().catch((e) => { console.error("[start-preview] fatal:", e); process.exit(1); });
