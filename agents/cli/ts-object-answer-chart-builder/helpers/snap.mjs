#!/usr/bin/env node
// snap.mjs <slug> <attempt> [--data live|empty|absent|wrapped|noviz] [--tile WxH] [--standalone]
//   (--data=absent and --tile=620x400 also work: under zsh an unquoted "$args" is not split, so prefer the = form in loops)
//
// Captures one attempt to <runs>/<slug>/attempts/<NN>.png.
//
// Headed is preferred: when start-preview.mjs's window is up, snap attaches to it
// over CDP, so the user watches the capture happen. When it is not — no display,
// a headed launch that failed, or a daemon that died mid-loop — snap starts its
// own server and headless browser for this one capture and tears both down. The
// loop never stalls on a missing window; the `mode:` line says which ran.
//
// Also prints a diagnostic block — console errors, the preview status line,
// whether emitRenderCompletedEvent fired. The screenshot answers "does it look
// right"; this answers "did it actually work", and the two fail differently: a
// chart that throws still screenshots, just empty.
//
// --tile WxH resizes the tile container (not the window) before capturing and
// reports whether the chart followed it — the check a Liveboard tile resize needs.
//
// Exit codes: 0 ok · 1 fatal · 2 usage

import fs from "node:fs";
import path from "node:path";
import { captureTile, parseTile, printDiag, seedChartFiles } from "./capture.mjs";
import { launchOptions, loadPlaywright, resolveBrowser, resolveEnv, VIEWPORT } from "./env.mjs";
import { startServer } from "./serve.mjs";

const argv = process.argv.slice(2);
const positional = [];
let dataOverride = null, tileSpec = null, standalone = false;
for (let i = 0; i < argv.length; i++) {
  if (argv[i].startsWith("--data=")) dataOverride = argv[i].slice(7);
  else if (argv[i].startsWith("--tile=")) tileSpec = argv[i].slice(7);
  else if (argv[i] === "--data") dataOverride = argv[++i];
  else if (argv[i] === "--tile") tileSpec = argv[++i];
  else if (argv[i] === "--standalone") standalone = true;
  else positional.push(argv[i]);
}
const [slug, attemptArg] = positional;
if (!slug || !attemptArg) {
  console.error("usage: snap.mjs <slug> <attempt> [--data live|empty|absent|wrapped|noviz] [--tile WxH] [--standalone]");
  process.exit(2);
}

let tile = null;
try { tile = tileSpec ? parseTile(tileSpec) : null; } catch (e) { console.error(`[snap] ${e.message}`); process.exit(2); }

const env = resolveEnv({ slug });
const attempt = String(attemptArg).padStart(2, "0");
const cdpPath = path.join(env.previewDir, "cdp.json");

async function reachableDaemon() {
  if (standalone || !fs.existsSync(cdpPath)) return null;
  try {
    const cfg = JSON.parse(fs.readFileSync(cdpPath, "utf8"));
    const r = await fetch(`${cfg.cdpUrl}/json/version`, { signal: AbortSignal.timeout(2000) });
    return r.ok ? cfg : null;
  } catch { return null; }
}

function outName(defaultData) {
  const suffix = [];
  if (dataOverride && dataOverride !== defaultData) suffix.push(dataOverride);
  if (tile) suffix.push(`${tile.width}x${tile.height}`);
  return `${attempt}${suffix.length ? "." + suffix.join(".") : ""}.png`;
}

// In the Claude app the run dir is not somewhere the user can open, so each
// attempt is also copied under the outputs folder.
function copyForUser(png) {
  if (env.platform !== "claude-app" && process.env.TS_CHART_COPY_PNG !== "1") return null;
  const dst = path.join(env.outDir, "attempts", path.basename(png));
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.copyFileSync(png, dst);
  return dst;
}

const pw = await loadPlaywright(env);
if (!pw) { console.error("[snap] playwright not found - run: node env.mjs"); process.exit(1); }

const cfg = await reachableDaemon();
let browser, server;
try {
  if (cfg) {
    // Headed: attach to the window the user is watching.
    browser = await pw.chromium.connectOverCDP(cfg.cdpUrl);
    const pages = browser.contexts().flatMap((c) => c.pages());
    const page = pages.find((p) => p.url().includes(`localhost:${cfg.previewPort}`));
    if (!page) throw new Error("preview page not found in the headed browser");
    const dataMode = dataOverride ?? cfg.data;
    const outPath = path.join(env.attemptsDir, outName(cfg.data));
    const result = await captureTile(page, {
      url: `http://localhost:${cfg.previewPort}/?data=${dataMode}&watch=1`, outPath, tile,
    });
    printDiag(result, { mode: "headed", png: outPath, userPng: copyForUser(outPath), dataMode, tile });
  } else {
    // Headless fallback: a server and a browser for this capture only.
    const seeded = seedChartFiles(env.chartDir);
    if (seeded.length) console.log(`[snap] seeded missing chart files: ${seeded.join(", ")}`);
    const exe = resolveBrowser(pw);
    if (!exe) throw new Error("no Chromium found - run: node env.mjs");
    server = await startServer({ scaffoldDir: env.scaffoldDir, runDir: env.runDir, port: 0 });
    browser = await pw.chromium.launch(launchOptions(exe, { headless: true }));
    const page = await (await browser.newContext(VIEWPORT)).newPage();
    const dataMode = dataOverride ?? "live";
    const outPath = path.join(env.attemptsDir, outName("live"));
    const result = await captureTile(page, { url: `${server.url}/?data=${dataMode}`, outPath, tile });
    const why = env.headless
      ? (env.display ? "TS_CHART_HEADLESS=1" : "no display")
      : standalone ? "--standalone" : `no headed preview reachable - run start-preview.mjs ${slug} for the window`;
    printDiag(result, { mode: `headless (${why})`, png: outPath, userPng: copyForUser(outPath), dataMode, tile });
  }
} catch (e) {
  console.error("[snap] error:", e.message);
  process.exitCode = 1;
} finally {
  // Over CDP, close() disconnects this client only; the daemon's browser stays up.
  if (browser) try { await browser.close(); } catch {}
  if (server) try { await server.close(); } catch {}
}
