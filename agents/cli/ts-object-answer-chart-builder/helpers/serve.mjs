#!/usr/bin/env node
// serve.mjs — the preview's static server. Replaces the Vite dev server.
//
// Serves the scaffold straight out of the (possibly read-only) skill folder and
// the chart files out of the run dir, so a run needs no copy and no npm install.
// Nothing here needs bundling: a Muze build is a plain ES module and the chart files
// are fetched as text, exactly as the ThoughtSpot host treats them.
//
//   node serve.mjs <slug> [--port N]      manual debugging
//
// Routes:
//   /, /index.html            scaffold/index.html
//   /src/*                    scaffold
//   /vendor/muze/*            the user's own Muze build (TS_MUZE_DIR, or <home>/muze); none ships
//   /assets/*                 <muze dir>/assets — Muze builds its worker
//                             URL as the origin-absolute /assets/transform-data-worker-*.js
//   /chart/*, /sample-data.json   the run dir, never cached
//   /__mtime                  newest mtime of the chart files, polled by the headed
//                             window to reload itself when a file changes

import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolveEnv } from "./env.mjs";

const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
  ".woff": "font/woff", ".woff2": "font/woff2",
};

// Resolve under `root` and refuse anything that escapes it.
function safeJoin(root, rel) {
  const p = path.resolve(root, "." + path.sep + rel);
  return p === root || p.startsWith(root + path.sep) ? p : null;
}

function newestMtime(runDir) {
  let max = 0;
  const chartDir = path.join(runDir, "chart");
  let names = [];
  try { names = fs.readdirSync(chartDir).map((n) => path.join(chartDir, n)); } catch {}
  for (const p of [...names, path.join(runDir, "sample-data.json")]) {
    try { max = Math.max(max, fs.statSync(p).mtimeMs); } catch {}
  }
  return max;
}

export function startServer({ scaffoldDir, runDir, port = 0, host = "127.0.0.1", muzeDir = resolveEnv({}).muzeDir }) {
  const scaffold = path.resolve(scaffoldDir);
  const run = path.resolve(runDir);
  // The user's own Muze build, if any (none ships with the skill). Missing files answer 404 and the preview
  // reports Muze as unavailable.
  const muze = path.resolve(muzeDir);
  const muzeAssets = path.join(muze, "assets");

  const server = http.createServer((req, res) => {
    const headers = { "Content-Security-Policy": "frame-ancestors *" };
    // A malformed path (a lone "%") would throw here and take the daemon down with it.
    let p;
    try { p = decodeURIComponent(new URL(req.url, "http://x").pathname); }
    catch { res.writeHead(400, headers); res.end("bad request"); return; }

    // Chromium asks for a favicon on every load; a 404 there lands in the
    // diagnostic block's console errors and reads like a chart defect.
    if (p === "/favicon.ico") { res.writeHead(204, headers); res.end(); return; }

    // Whether the user has a Muze build, so the preview imports it only when it exists (a 404 would land in
    // the diagnostic block's console errors and read like a chart defect).
    if (p === "/__muze") {
      res.writeHead(200, { ...headers, "Content-Type": MIME[".json"], "Cache-Control": "no-store" });
      res.end(JSON.stringify({ available: fs.existsSync(path.join(muze, "muze.js")) }));
      return;
    }

    if (p === "/__mtime") {
      res.writeHead(200, { ...headers, "Content-Type": MIME[".json"], "Cache-Control": "no-store" });
      res.end(JSON.stringify({ mtime: newestMtime(run) }));
      return;
    }

    let file = null;
    if (p === "/" || p === "/index.html") file = path.join(scaffold, "index.html");
    else if (p.startsWith("/vendor/muze/")) file = safeJoin(muze, p.slice("/vendor/muze/".length));
    else if (p.startsWith("/src/")) file = safeJoin(scaffold, p);
    else if (p.startsWith("/assets/")) file = safeJoin(muzeAssets, p.slice("/assets/".length));
    else if (p.startsWith("/chart/") || p === "/sample-data.json") {
      file = safeJoin(run, p);
      headers["Cache-Control"] = "no-store";
    }

    if (!file) { res.writeHead(404, headers); res.end("not found"); return; }
    fs.readFile(file, (err, body) => {
      // The dataset is optional (a sample-only chart has none). preview.js warns
      // when it is missing; a 404 would also land in the console errors and read
      // like a chart defect, so answer with an empty body instead.
      if (err && p === "/sample-data.json") { res.writeHead(204, headers); res.end(); return; }
      if (err) { res.writeHead(404, headers); res.end("not found"); return; }
      res.writeHead(200, { ...headers, "Content-Type": MIME[path.extname(file)] ?? "application/octet-stream" });
      res.end(body);
    });
  });

  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      const actual = server.address().port;
      resolve({
        port: actual,
        url: `http://localhost:${actual}`,
        close: () => new Promise((r) => server.close(() => r())),
      });
    });
  });
}

if (process.argv[1] && fs.realpathSync(process.argv[1]) === fs.realpathSync(fileURLToPath(import.meta.url))) {
  const argv = process.argv.slice(2);
  const slug = argv.find((a) => !a.startsWith("--"));
  const pi = argv.indexOf("--port");
  if (!slug) { console.error("usage: serve.mjs <slug> [--port N]"); process.exit(2); }
  const env = resolveEnv({ slug });
  const s = await startServer({ scaffoldDir: env.scaffoldDir, runDir: env.runDir,
                                port: pi >= 0 ? Number(argv[pi + 1]) : 5173 });
  console.log(`[serve] ${s.url}/?data=live  (run dir ${env.runDir})`);
}
