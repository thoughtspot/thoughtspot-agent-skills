#!/usr/bin/env node
// cluster-shot.mjs --url <liveboard or answer url> [--tabs "01 About,02 Pulse"] [--name answer] [--out dir] [--wait 9]
//                  [--profile dir] [--login-timeout 300] [--scroll-wait 8] [--no-scroll] [--filter "Region=West"]
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
// Prints a report and the PNG paths. Exit 0 when every tab screenshot was taken.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
// Playwright and Chromium are the ones the doctor (env.mjs) installed.
import { cacheRoot, launchOptions, loadPlaywright, resolveBrowser, resolveEnv } from "./env.mjs";

const argv = process.argv.slice(2);
const opt = {};
for (let i = 0; i < argv.length; i++) if (argv[i].startsWith("--")) opt[argv[i].slice(2)] = argv[++i];

const profiles = path.join(cacheRoot(), "cluster-profiles");
// Before per-cluster profiles, one profile was shared by every cluster. It is never reused (it would belong to
// whichever cluster ran first); --logout all removes it.
const legacy = path.join(os.homedir(), ".cache", "amuzing-chart", "cluster-profile");
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
if (opt.logout) {
  const targets = opt.logout === "all" ? [profiles, legacy] : [profileOf(opt.logout)];
  if (!targets[0]) { console.error("--logout takes a cluster URL, a host name or all; not a host: " + JSON.stringify(opt.logout)); process.exit(2); }
  const gone = targets.filter((t) => fs.existsSync(t));
  for (const t of gone) fs.rmSync(t, { recursive: true, force: true });
  console.log(gone.length ? "signed out: removed " + gone.join(", ") : "no saved sign-in for " + opt.logout + " (nothing to remove)");
  process.exit(0);
}
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
      await page.getByText(new RegExp("^" + fcol + "\\b", "i")).first().click({ timeout: 8000 });
      await page.waitForTimeout(1500);
      await page.getByText(fval, { exact: true }).first().click({ timeout: 8000 });
      await page.waitForTimeout(600);
      const btn = page.getByRole("button", { name: /update|apply|done/i }).first();
      if (await btn.count()) await btn.click();
      await page.waitForTimeout(4000);
      console.log("filter applied: " + opt.filter);
    } catch (e) { console.log("filter NOT applied: " + String(e.message).split("\n")[0]); }
  }


  async function report(label) {
    const frames = page.frames().filter((f) => f !== page.mainFrame());
    const findings = [];
    for (const f of frames) {
      let t = "";
      try { t = (await f.evaluate(() => document.body ? document.body.innerText : "")).trim(); } catch { continue; }
      if (!t) continue;
      const bad = /Chart did not render|Something went wrong|Error:|TypeError|ReferenceError|Column not found|No data yet|is not defined|Cannot read/i.exec(t);
      if (bad) findings.push({ frame: f.url().slice(0, 60), hit: bad[0], text: t.slice(0, 200).replace(/\s+/g, " ") });
    }
    const main = (await page.evaluate(() => document.body.innerText).catch(() => "")).match(/Chart did not render|Something went wrong/g) || [];
    console.log(`[${label}] iframes=${frames.length} problems=${findings.length + main.length}`);
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
    await page.waitForTimeout(waitMs);
    await applyFilter();
    const base = name.replace(/[^\w]+/g, "-").toLowerCase();
    if (opt["no-scroll"] !== undefined) {
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
        if (i) problems += 0;
      }
      if (info) await page.evaluate(() => { document.querySelector("[data-shot-scroller]").scrollTop = 0; });
    }
    problems += await report(name);
  }
  shots.forEach((s) => console.log("png: " + s));
  console.log(problems ? `problems: ${problems}` : "no tile reported a failure text");
} catch (e) {
  if (!process.exitCode) console.error("cluster-shot:", e.message);
  process.exitCode = process.exitCode || 1;
} finally {
  await ctx.close().catch(() => {});
}
