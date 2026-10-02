#!/usr/bin/env node
// cluster-shot.mjs --url <liveboard or answer url> [--tabs "01 About,02 Pulse"] [--name answer] [--out dir] [--wait 9]
//                  [--profile dir] [--login-timeout 300] [--scroll-wait 8] [--no-scroll] [--filter "Region=West"] [--debug-frames]
// cluster-shot.mjs --logout <cluster url or host | all>
//   Without --tabs it takes one shot of the page as <name>.png (default "liveboard"): use this for a saved answer.
//   --filter clicks the named filter chip, picks the value and applies it before capturing, to prove the tiles
//   survive a filtered view.
//   Each tab is captured screenful by screenful: the tallest scrolling container is found and scrolled, so a
//   long tab yields <tab>-1.png, <tab>-2.png ... (use --no-scroll for a single viewport shot).
//
// Opens a Liveboard or an answer in a real, logged-in ThoughtSpot session and screenshots it (each tab of a
// Liveboard), then
// inspects every custom-chart iframe for the failure texts that a local preview cannot show:
// "Chart did not render", "Something went wrong", the chart's own "No data yet" / stack paint.
//
// This is the check that closes the gap between the local preview and the cluster. It is headed
// on purpose: SSO (Okta, SAML) needs a human once. The session lives in a browser profile of its own per
// cluster (~/.cache/ts-charts/cluster-profiles/<host>, mode 0700, outside any repo), so later runs in the
// same skill run are silent. --logout deletes that profile, which signs the user out; the skills run it at
// the end unless the user chose to stay signed in (security.md: cached sessions are cleaned up at skill end).
//
// Prints a report and the PNG paths. Exit 0 when every tab screenshot was taken and no tile reported a failure
// text; exit 2 when a tab was not found, a tab has no chart frame or only blank ones, fewer custom-chart tiles rendered than the Liveboard holds on that tab, or a frame showed a failure text (the `problems:` line says how
// many); exit 1 on a fatal error (login timeout, browser).
import fs from "node:fs";
import path from "node:path";
// Playwright and Chromium are the ones the doctor (env.mjs) installed.
import { cacheRoot, launchOptions, loadPlaywright, resolveBrowser, resolveEnv } from "./env.mjs";

const argv = process.argv.slice(2);
const opt = {};
const BOOL = new Set(["no-scroll", "debug-frames"]); // flags that take no value
for (let i = 0; i < argv.length; i++) {
  if (!argv[i].startsWith("--")) continue;
  const k = argv[i].slice(2);
  opt[k] = BOOL.has(k) ? true : argv[++i];
}

const profiles = path.join(cacheRoot(), "cluster-profiles");
// Before per-cluster profiles, one profile was shared by every cluster. It is never reused (it would belong to
// whichever cluster ran first); --logout all removes it.
// Same cache folder resolution as env.mjs ($XDG_CACHE_HOME or ~/.cache), one level up from ts-charts.
const legacy = path.join(path.dirname(cacheRoot()), "amuzing-chart", "cluster-profile");
// The profile folder of a cluster: its host name, checked to be one, so no input can name a folder outside
// cluster-profiles (".." included). Returns null for anything that is not a host.
const HOST = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*(?::\d{1,5})?$/i;
function profileOf(u) {
  let h = String(u || "").trim();
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(h)) { try { h = new URL(h).host; } catch { return null; } }
  h = h.toLowerCase();
  if (!HOST.test(h)) return null;
  const dir = path.join(profiles, h.replace(":", "_"));
  const rel = path.relative(profiles, dir);
  return rel && !rel.startsWith("..") && !path.isAbsolute(rel) && !rel.includes(path.sep) ? dir : null;
}
// The profiles folder itself must be a real folder inside the cache: a symlink there would point a removal
// somewhere else.
if (fs.existsSync(profiles) && (fs.lstatSync(profiles).isSymbolicLink() || path.relative(fs.realpathSync(cacheRoot()), fs.realpathSync(profiles)) !== "cluster-profiles")) {
  console.error(profiles + " is a link or lies outside " + cacheRoot() + "; refusing to touch it. Remove it by hand.");
  process.exit(2);
}
if (opt.logout) {
  const targets = opt.logout === "all" ? [profiles, legacy] : [profileOf(opt.logout)];
  if (!targets[0]) { console.error("--logout takes a cluster URL, a host name or all; not a host: " + JSON.stringify(opt.logout)); process.exit(2); }
  const gone = targets.filter((t) => fs.existsSync(t));
  for (const t of gone) fs.rmSync(t, { recursive: true, force: true });
  console.log(gone.length ? "signed out: removed " + gone.join(", ") : "no saved sign-in for " + opt.logout + " (nothing to remove)");
  process.exit(0);
}
// A bare host ("my.thoughtspot.cloud") is a URL too.
if (opt.url && !/^[a-z][a-z0-9+.-]*:\/\//i.test(opt.url)) opt.url = "https://" + opt.url;
if (!opt.url) { console.error('usage: cluster-shot.mjs --url <liveboard or answer url> [--tabs "a,b"] [--name answer] [--out dir] [--wait seconds]\n       cluster-shot.mjs --logout <cluster url or host | all>'); process.exit(2); }

const env = resolveEnv({});
const out = path.resolve(opt.out || path.join(env.home, "runs", "_cluster"));
const profile = opt.profile ? path.resolve(opt.profile) : profileOf(opt.url);
if (!profile) { console.error("--url is not a cluster URL: " + opt.url); process.exit(2); }
if (fs.existsSync(legacy)) console.log("note: an old shared sign-in profile is still at " + legacy + "; --logout all removes it");
const tabs = (opt.tabs || "").split(",").map((s) => s.trim()).filter(Boolean);
const waitMs = Number(opt.wait || 9) * 1000;
const loginTimeout = Number(opt["login-timeout"] || 300) * 1000;
const scrollWaitMs = Number(opt["scroll-wait"] || 8) * 1000; // tiles load lazily as they scroll into view
fs.mkdirSync(out, { recursive: true });
fs.mkdirSync(profile, { recursive: true, mode: 0o700 });
fs.chmodSync(profile, 0o700); // mkdir's mode is masked by umask and does not touch a folder that exists

const pw = await loadPlaywright(env);
if (!pw) { console.error("playwright not found - run the doctor: node <ts-object-answer-chart-builder>/helpers/env.mjs"); process.exit(1); }
const exe = resolveBrowser(pw);
if (!exe) { console.error("no Chromium found - run the doctor: node <ts-object-answer-chart-builder>/helpers/env.mjs"); process.exit(1); }

const host = new URL(opt.url).host;
const ctx = await pw.chromium.launchPersistentContext(profile, { ...launchOptions(exe, { headless: false }), viewport: { width: 1600, height: 1000 } });
const page = ctx.pages()[0] || (await ctx.newPage());
try {
  await page.goto(opt.url, { waitUntil: "domcontentloaded" });

  // Logged in when we are on the cluster host, not on an SSO page, and the app has rendered.
  const ready = () => page.evaluate((h) => location.host === h && !/login|okta|saml|sso/i.test(location.href) && !!document.querySelector("[data-testid], .ts-app, app-root, #app") && document.body.innerText.length > 200, host).catch(() => false);
  const t0 = Date.now();
  let said = false;
  while (!(await ready())) {
    if (!said && Date.now() - t0 > 8000) { console.log("waiting for you to sign in to " + host + " in the browser window ..."); said = true; }
    if (Date.now() - t0 > loginTimeout) { console.error("timed out waiting for login"); process.exitCode = 1; throw new Error("login timeout"); }
    await page.waitForTimeout(2000);
  }
  if (said) { console.log("signed in"); await page.goto(opt.url, { waitUntil: "domcontentloaded" }); }
  await page.waitForTimeout(waitMs);
  let filterDone = false;
  async function applyFilter() {
    if (!opt.filter || filterDone) return;
    filterDone = true;
    const [fcol, fval] = opt.filter.split("=");
    try {
      const esc = fcol.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); // the filter name is text, not a pattern
      await page.getByText(new RegExp("^" + esc + "\\b", "i")).first().click({ timeout: 8000 });
      await page.waitForTimeout(1500);
      await page.getByText(fval, { exact: true }).first().click({ timeout: 8000 });
      await page.waitForTimeout(600);
      const btn = page.getByRole("button", { name: /update|apply|done/i }).first();
      if (await btn.count()) await btn.click();
      await page.waitForTimeout(4000);
      console.log("filter applied: " + opt.filter);
    } catch (e) { console.log("filter NOT applied: " + String(e.message).split("\n")[0]); }
  }


  // Every frame on the page with what it holds. Chart tiles render into frames of their own; ThoughtSpot also adds
  // helper frames, so a frame counts as a rendered chart only when it holds marks (svg, canvas, table, img) or text.
  async function survey() {
    const rows = [];
    for (const f of page.frames()) {
      if (f === page.mainFrame()) continue;
      let r = null;
      try {
        r = await f.evaluate(() => {
          const b = document.body;
          if (!b) return { text: "", marks: 0, w: 0, h: 0 };
          const marks = [...b.querySelectorAll("svg,canvas,table,img")].filter((e) => { const q = e.getBoundingClientRect(); return q.width > 4 && q.height > 4; }).length;
          return { text: b.innerText.trim(), marks, w: innerWidth, h: innerHeight };
        });
      } catch { r = null; }
      rows.push({ f, url: f.url(), ...(r || { text: "", marks: 0, w: 0, h: 0, dead: true }) });
    }
    return rows;
  }
  const isChart = (r) => !r.dead && r.w > 40 && r.h > 40 && (r.marks > 0 || r.text.length > 0);
  // How many custom-chart tiles each tab should show, from the Liveboard's own export (same-origin, signed in).
  async function expectedTiles() {
    const m = /#\/(?:pinboard|liveboard)\/([0-9a-f-]{36})/i.exec(opt.url);
    if (!m) return null;
    return page.evaluate(async (guid) => {
      try {
        const r = await fetch("/api/rest/2.0/metadata/tml/export", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-By": "ThoughtSpot" }, body: JSON.stringify({ metadata: [{ identifier: guid, type: "LIVEBOARD" }], edoc_format: "JSON" }) });
        if (!r.ok) return { error: "http " + r.status };
        const lb = JSON.parse((await r.json())[0].edoc).liveboard;
        const custom = new Set((lb.visualizations || []).filter((v) => v.answer && v.answer.chart && /MUZE_STUDIO|CUSTOM/i.test(v.answer.chart.type || "")).map((v) => v.id));
        const byTab = {};
        for (const t of (lb.layout && lb.layout.tabs) || []) byTab[t.name] = (t.tiles || []).filter((x) => custom.has(x.visualization_id)).length;
        return { byTab };
      } catch (e) { return { error: String(e && e.message || e).slice(0, 120) }; }
    }, m[1]);
  }
  const expected = await expectedTiles();
  if (expected && expected.error) console.log("tile count: unavailable (" + expected.error + "); only failure text and empty tabs are checked");
  let seen = new Set(); // rendered chart frames seen at any scroll position of the current tab

  async function look() {
    for (const r of await survey()) if (isChart(r)) seen.add(r.f);
  }

  async function report(label) {
    const frames = page.frames().filter((f) => f !== page.mainFrame());
    const findings = [];
    let withContent = 0; // ThoughtSpot adds helper frames of its own, so judge the tab, not each frame
    if (!frames.length) findings.push({ frame: "page", hit: "no chart frame", text: "the page has no chart frames: still loading (raise --wait), or the tab is empty" });
    for (const f of frames) {
      let t = "", nodes = 0;
      try { [t, nodes] = await f.evaluate(() => [document.body ? document.body.innerText : "", document.body ? document.body.querySelectorAll("svg,canvas,img,table,div,span").length : 0]); } catch { continue; }
      t = t.trim();
      if (t || nodes) withContent++;
      if (!t) continue;
      const bad = /Chart did not render|Something went wrong|Error:|TypeError|ReferenceError|Column not found|No data yet|is not defined|Cannot read/i.exec(t);
      if (bad) findings.push({ frame: f.url().slice(0, 60), hit: bad[0], text: t.slice(0, 200).replace(/\s+/g, " ") });
    }
    if (frames.length && !withContent) findings.push({ frame: "page", hit: "blank frames", text: "no chart frame has any content: still loading (raise --wait), or every tile is blank" });
    await look();
    const want = expected && expected.byTab ? expected.byTab[label] : undefined;
    if (want != null && seen.size < want) findings.push({ frame: "page", hit: "blank tiles", text: seen.size + " of " + want + " custom-chart tiles rendered: the rest are blank or still loading (raise --wait or --scroll-wait)" });
    if (opt["debug-frames"]) for (const r of await survey()) console.log("   frame " + (isChart(r) ? "chart " : "other ") + r.w + "x" + r.h + " marks=" + r.marks + " text=" + r.text.length + " " + r.url.slice(0, 80));
    const main = (await page.evaluate(() => document.body.innerText).catch(() => "")).match(/Chart did not render|Something went wrong/g) || [];
    console.log(`[${label}] iframes=${frames.length} rendered=${seen.size}${want != null ? " of " + want + " custom-chart tiles" : ""} problems=${findings.length + main.length}`);
    findings.forEach((x) => console.log("   - " + x.hit + " | " + x.text));
    return findings.length + main.length;
  }

  let problems = 0;
  const shots = [];
  if (!tabs.length) {
    const name = (opt.name || "liveboard").replace(/[^\w-]+/g, "-");
    const p = path.join(out, name + ".png");
    await page.screenshot({ path: p, fullPage: false }); shots.push(p);
    problems += await report(name);
  }
  for (const name of tabs) {
    const tab = page.getByText(name, { exact: true }).first();
    try { await tab.click({ timeout: 8000 }); } catch { console.log(`[${name}] tab not found`); problems++; continue; }
    seen = new Set();
    await page.waitForTimeout(waitMs);
    await applyFilter();
    const base = name.replace(/[^\w]+/g, "-").toLowerCase();
    if (opt["no-scroll"]) {
      const p = path.join(out, base + ".png");
      await page.screenshot({ path: p, fullPage: false }); shots.push(p);
    } else {
      const info = await page.evaluate(() => {
        let best = null;
        for (const e of document.querySelectorAll("*")) {
          const cs = getComputedStyle(e);
          if ((cs.overflowY === "auto" || cs.overflowY === "scroll") && e.scrollHeight > e.clientHeight + 60 && (!best || e.scrollHeight > best.scrollHeight)) best = e;
        }
        if (!best) return null;
        best.setAttribute("data-shot-scroller", "1");
        return { h: best.scrollHeight, c: best.clientHeight };
      });
      const step = info ? Math.max(300, info.c - 120) : 0;
      const n = info ? Math.min(8, Math.ceil((info.h - info.c) / step) + 1) : 1;
      for (let i = 0; i < n; i++) {
        if (info) { await page.evaluate((y) => { document.querySelector("[data-shot-scroller]").scrollTop = y; }, i * step); await page.waitForTimeout(i ? scrollWaitMs : 300); }
        const p = path.join(out, base + "-" + (i + 1) + ".png");
        await page.screenshot({ path: p, fullPage: false }); shots.push(p);
        await look();
      }
      if (info) await page.evaluate(() => { document.querySelector("[data-shot-scroller]").scrollTop = 0; });
    }
    problems += await report(name);
  }
  shots.forEach((s) => console.log("png: " + s));
  console.log(problems ? `problems: ${problems}` : "no tile reported a failure text");
  if (problems) process.exitCode = 2;
} catch (e) {
  if (!process.exitCode) console.error("cluster-shot:", e.message);
  process.exitCode = process.exitCode || 1;
} finally {
  await ctx.close().catch(() => {});
}
