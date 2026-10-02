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
//            "Changed the DOM" means a state signature changed: elements whose class carries a
//            hover/active/selected/tooltip/focus token, the visibility and text of tooltips,
//            aria-selected / data-active, and the inline style / paint attributes (opacity, fill, stroke,
//            stroke-width, font-weight) of marks, which is how D3 charts highlight without a class.
//            Geometry (d, transform, x, y, r, ...) is ignored since it animates. Unrelated classes do not count; the
//            baseline is sampled twice before the pointer moves and `sweep: UNSTABLE baseline` is
//            printed (nothing counted) when the two differ.
//   --eval-first  run a JS expression BEFORE the hover/click screenshot (set a slider, open an accordion),
//            so the screenshot captures the state it produces.
//
// Always headless, always its own server; never disturbs the headed preview.
// Exit codes: 0 ok, 1 fatal, 2 usage or the chart never settled (`status: TIMEOUT ...`)
import fs from "node:fs";
import path from "node:path";
import { parseTile, settle, SETTLE_MS } from "./capture.mjs";
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
  const settled = await settle(page);
  if (!settled) {
    // Loud, and exit 2: the probe still runs so the sweep/eval output is available, but a chart that never
    // settled is not a working chart.
    const st = await page.evaluate(() => { const s = document.getElementById("status"); return { text: s?.textContent ?? "", kind: s?.className ?? "" }; });
    console.log(`status: TIMEOUT render-complete never fired after ${Math.round(SETTLE_MS / 1000)}s (preview status stayed [${st.kind || "pending"}] ${JSON.stringify(st.text)})`);
    process.exitCode = 2;
  }
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
    // A state signature, not innerHTML.length: three parts, each of which only a hover/selection should move.
    //   a) elements whose class carries hover/active/selected/tooltip/focus as a whole token or a prefix
    //      (`hovered`, `is-active`, `bar--selected`, `az-tip` does not qualify here but is caught by b)
    //   b) the visibility and text of tooltips: [role=tooltip] and classes containing tooltip or tip
    //   c) the count and text of elements carrying aria-selected / data-active
    //   d) the inline `style` and the paint attributes (opacity, fill, stroke, stroke-width, font-weight) of every
    //      svg mark and HTML element: D3 charts highlight by setting these directly, with no class. Geometry
    //      attributes (d, transform, x, y, cx, cy, width, height, r) are left out because they animate.
    const sig = () => page.evaluate(() => {
      const h = document.getElementById("chart-host") || document.body;
      const STATE = /(^|[-_:])(hover|active|selected|tooltip|focus)/i;
      const text = (e, n) => (e.textContent || "").replace(/\s+/g, " ").trim().slice(0, n);
      const cls = (e) => e.getAttribute("class") || "";
      const stateEls = [...h.querySelectorAll("[class]")].filter((e) => cls(e).split(/\s+/).some((t) => STATE.test(t)));
      const a = stateEls.map((e) => e.tagName + "." + cls(e) + "=" + text(e, 60)).join(",");
      const tips = [...h.querySelectorAll("[role=tooltip],[class*=tooltip],[class*=tip]")].map((e) => {
        const cs = getComputedStyle(e), r = e.getBoundingClientRect();
        const vis = cs.display !== "none" && cs.visibility !== "hidden" && Number(cs.opacity) > 0.05 && r.width > 0 && r.height > 0;
        return (vis ? "v:" + text(e, 120) : "h");
      }).join(",");
      const sel = [...h.querySelectorAll("[aria-selected],[data-active]")];
      const c = sel.length + ":" + sel.map((e) => (e.getAttribute("aria-selected") ?? "") + "/" + (e.getAttribute("data-active") ?? "") + "=" + text(e, 40)).join(",");
      const PAINT = ["opacity", "fill", "stroke", "stroke-width", "font-weight"];
      const d = [...h.querySelectorAll("path, rect, circle, line, g, text, ellipse, polygon, polyline, *:not(svg *)")]
        .filter((e) => e.tagName !== "STYLE" && e.tagName !== "SCRIPT")
        .map((e) => (e.getAttribute("style") || "") + ";" + PAINT.map((k) => e.getAttribute(k) ?? "").join(";"))
        .join("/");
      return "a[" + stateEls.length + "]" + a + "|b[" + tips + "]|c[" + c + "]|d[" + d + "]";
    });
    // Baseline after settle, the tile resize and an extra pause for the entrance animation, sampled twice with
    // the pointer still outside the tile. A baseline that moves on its own would count animation as a reaction.
    await page.waitForTimeout(400);
    let base = await sig();
    await page.waitForTimeout(250);
    let again = await sig();
    if (base !== again) {
      // One more chance for a slow entrance animation before giving up on the sweep.
      await page.waitForTimeout(800);
      base = await sig();
      await page.waitForTimeout(250);
      again = await sig();
    }
    if (base !== again) {
      console.log("sweep: UNSTABLE baseline (animation still running)  <- not counted as interactive; re-run, or let the chart settle before emitRenderCompletedEvent");
    } else {
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
