#!/usr/bin/env node
// probe.mjs <slug> [--tile WxH] [--data live|empty|absent|wrapped|noviz]
//                  [--eval "<js expression>"] [--eval-first "<js>"] [--hover fx,fy] [--click fx,fy] [--out NN]
//
// Looks inside a rendered tile. snap.mjs answers "does it look right"; probe answers
// "what is in there" and "does it respond".
//
//   --eval   run a JS expression in the page (after render, resize, and any hover/click) and print
//            the JSON result. Use it to read DOM attributes, series colours, path counts.
//   --hover  move the mouse to a point inside the tile, given as fractions of the tile
//            (0.5,0.5 is the centre), wait for the chart's own hover handlers, then screenshot
//            to attempts/<out>.hover.png so the tooltip can be read.
//   --click  same, but click, then screenshot to attempts/<out>.click.png.
//   --hover-sel / --click-sel "css"  target the centre of the first element matching the selector instead of a fraction.
//   --after "<js>"  run a JS expression AFTER the hover/click and its wait, and print the JSON result (read what a
//            drill or a hover changed without a second run). --wait <ms> lengthens that wait for animated drills.
//   --sweep  hover 5 evenly spaced points along the middle of the tile AND up to 8 of the chart's own
//            marks (svg circle/rect/path, buttons, [tabindex]), and report how many changed the DOM (a
//            tooltip, a highlight). Sparse charts (scatter, bubble) are judged on their marks, not on the
//            middle line. A tile where nothing changes anywhere is not interactive.
//   --eval-first  run a JS expression BEFORE the hover/click screenshot (set a slider, open an accordion),
//            so the screenshot captures the state it produces.
//
// Always headless, always its own server; never disturbs the headed preview.
// Exit codes: 0 ok, 1 fatal, 2 usage
import fs from "node:fs";
import path from "node:path";
import { parseTile } from "./capture.mjs";
import { launchOptions, loadPlaywright, resolveBrowser, resolveEnv, VIEWPORT } from "./env.mjs";
import { startServer } from "./serve.mjs";

const argv = process.argv.slice(2);
const pos = [];
const opt = {};
for (let i = 0; i < argv.length; i++) {
  if (argv[i].startsWith("--")) {
    const eq = argv[i].indexOf("=");
    if (eq > 0) { opt[argv[i].slice(2, eq)] = argv[i].slice(eq + 1); continue; }
    const k = argv[i].slice(2);
    opt[k] = k === "sweep" ? true : argv[++i];
  } else pos.push(argv[i]);
}
const [slug] = pos;
if (!slug) {
  console.error('usage: probe.mjs <slug> [--tile WxH] [--data mode] [--eval "js"] [--hover fx,fy] [--click fx,fy] [--sweep] [--out NN]');
  process.exit(2);
}
const tile = opt.tile ? parseTile(opt.tile) : null;
const env = resolveEnv({ slug });
const pw = await loadPlaywright(env);
if (!pw) { console.error("[probe] playwright not found - run: node env.mjs"); process.exit(1); }
const exe = resolveBrowser(pw);
if (!exe) { console.error("[probe] no Chromium found - run: node env.mjs"); process.exit(1); }

const point = (spec, box) => {
  const [fx, fy] = spec.split(",").map(Number);
  return { x: box.x + box.width * fx, y: box.y + box.height * fy };
};

let server, browser;
try {
  server = await startServer({ scaffoldDir: env.scaffoldDir, runDir: env.runDir, port: 0 });
  browser = await pw.chromium.launch(launchOptions(exe, { headless: true }));
  const page = await (await browser.newContext(VIEWPORT)).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e.message || e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

  if (tile) {
    await page.setViewportSize({ width: Math.max(VIEWPORT.viewport.width, tile.width + 32), height: Math.max(VIEWPORT.viewport.height, tile.height + 50) });
  }
  await page.goto(`${server.url}/?data=${opt.data || "live"}`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => { const s = document.getElementById("status"); return s && /^(ok|warn|error)$/.test(s.className); }, { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(700);
  if (tile) {
    await page.evaluate(({ width, height }) => {
      const t = document.getElementById("tile");
      Object.assign(t.style, { right: "auto", bottom: "auto", boxSizing: "border-box", width: `${width}px`, height: `${height}px` });
    }, tile);
    await page.waitForTimeout(900);
  }
  const attempt = String(opt.out || "99").padStart(2, "0");
  fs.mkdirSync(env.attemptsDir, { recursive: true });
  const tileEl = await page.$("#tile");
  const box = await (tileEl ?? page.locator("body")).boundingBox();

  if (opt["eval-first"]) {
    const o = await page.evaluate(async (src) => { try { const v = await (0, eval)(src); return JSON.stringify(v, null, 2); } catch (e) { return "eval-first error: " + (e && e.message || e); } }, opt["eval-first"]);
    if (o && o !== "undefined") console.log(o);
    await page.waitForTimeout(400);
  }
  if (opt.hover || opt.click || opt["hover-sel"] || opt["click-sel"]) {
    const sel = opt["hover-sel"] || opt["click-sel"];
    let p;
    if (sel) {
      const c = await page.evaluate((s) => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }, sel);
      if (!c) { console.error("[probe] no element matches " + sel); process.exit(1); }
      p = { x: c[0], y: c[1] };
    } else p = point(opt.hover || opt.click, box);
    await page.mouse.move(p.x - 6, p.y - 6);
    await page.mouse.move(p.x, p.y, { steps: 6 });
    if (opt.click || opt["click-sel"]) await page.mouse.click(p.x, p.y);
    await page.waitForTimeout(Number(opt.wait || 500));
    if (opt.after) {
      const o = await page.evaluate(async (src) => { try { const v = await (0, eval)(src); return JSON.stringify(v, null, 2); } catch (e) { return "after error: " + (e && e.message || e); } }, opt.after);
      if (o && o !== "undefined") console.log(o);
    }
    const png = path.join(env.attemptsDir, `${attempt}.${(opt.click || opt["click-sel"]) ? "click" : "hover"}.png`);
    await (tileEl ?? page).screenshot({ path: png });
    console.log("png: " + png);
  }
  if (opt.sweep) {
    const sig = () => page.evaluate(() => {
      const h = document.getElementById("chart-host") || document.body;
      return h.innerHTML.length + "|" + h.querySelectorAll("[class*=tip],[class*=tooltip],[class*=hover],[class*=active],[class*=hl],[class*=dim],[class*=on]").length + "|" + [...h.querySelectorAll("*")].filter((e) => getComputedStyle(e).opacity !== "1" && e.tagName !== "STYLE").length;
    });
    const base = await sig();
    const seen = new Set([base]);
    let n = 0;
    for (const fx of [0.15, 0.32, 0.5, 0.68, 0.85]) {
      const p = point(`${fx},0.55`, box);
      await page.mouse.move(p.x - 8, p.y);
      await page.mouse.move(p.x, p.y, { steps: 5 });
      await page.waitForTimeout(250);
      const s = await sig();
      if (!seen.has(s)) n++;
      seen.add(s);
    }
    let total = 5, nm = 0;
    const marks = await page.evaluate(() => {
      const host = document.getElementById("chart-host") || document.body;
      const els = [...host.querySelectorAll("svg circle, svg rect, svg path[d], button, [tabindex], li, tr, [class*=row], [class*=cell], [class*=bubble], [class*=bar]")].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 4 && r.height > 4 && r.width < 600 && r.height < 600 && r.bottom > 0 && r.right > 0; });
      const step = Math.max(1, Math.floor(els.length / 8));
      return els.filter((_, i) => i % step === 0).slice(0, 8).map((e) => { const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; });
    });
    for (const [mx, my] of marks) {
      await page.mouse.move(mx - 3, my - 3);
      await page.mouse.move(mx, my, { steps: 3 });
      await page.waitForTimeout(220);
      const s = await sig();
      total++;
      if (!seen.has(s)) { nm++; }
      seen.add(s);
    }
    const hit = n + nm;
    console.log(`sweep: ${hit} of ${total} points changed the DOM (${n} of 5 on the middle line, ${nm} of ${marks.length} on marks)` + (hit === 0 ? "  <- NOT INTERACTIVE (no tooltip or highlight reacted)" : ""));
  }
  if (opt.eval) {
    const out = await page.evaluate(async (src) => {
      try { const v = await (0, eval)(src); return JSON.stringify(v, null, 2); } catch (e) { return "eval error: " + (e && e.message || e); }
    }, opt.eval);
    console.log(out);
  }
  if (errors.length) console.log("console-errors: " + errors.slice(0, 5).join(" | "));
} catch (e) {
  console.error("[probe] error:", e.message);
  process.exitCode = 1;
} finally {
  if (browser) try { await browser.close(); } catch {}
  if (server) try { await server.close(); } catch {}
}
