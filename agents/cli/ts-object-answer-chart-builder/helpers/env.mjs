#!/usr/bin/env node
// env.mjs — where things live and what can run, in Claude Code or the Claude app.
//
// Imported by the other helpers; run directly it is the Step 0 doctor:
//
//   node env.mjs [slug] [--no-probe]
//
// and prints one `key: value` per line — the paths SKILL.md substitutes into
// every later command, which browser will be used, and the one command that
// fixes a missing dependency. Exit 0 when `deps: ok`, 1 otherwise.
//
// Nothing here may name the skill: an install may still use an older folder name
// (`thoughtspot-amuzing-chart`), so the name is read off the directory.

import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// 1280x720 at DPR 2 is what the headed preview has always rendered at — every
// attempt PNG on record is 2496x1340. Pinning it keeps a headless capture
// pixel-comparable with a headed one, so critiques mean the same thing in both.
export const VIEWPORT = { viewport: { width: 1280, height: 720 }, deviceScaleFactor: 2 };

function realpath(p) {
  try { return fs.realpathSync(p); } catch { return path.resolve(p); }
}

function isWritable(dir) {
  try { fs.accessSync(dir, fs.constants.W_OK); return true; } catch { return false; }
}

function containsSkill(dir, skillName) {
  return (
    fs.existsSync(path.join(dir, ".claude", "skills", skillName)) ||
    (path.basename(dir) !== ".claude" &&
      fs.existsSync(path.join(dir, "skills", skillName, "SKILL.md")))
  );
}

// The skill is copied or symlinked into any repo, so nothing may be hardcoded.
function findProjectRoot(skillDir, skillName) {
  if (process.env.TS_CHART_PROJECT_ROOT) return path.resolve(process.env.TS_CHART_PROJECT_ROOT);
  const cwd = process.cwd();
  if (containsSkill(cwd, skillName)) return cwd;
  // Walk up from the skill itself. `runs/` is created on demand, so its absence
  // must not fail the search. The `.claude` guard in containsSkill is
  // load-bearing: walking up from <repo>/.claude/skills/<name>/helpers reaches
  // <repo>/.claude, where skills/<name>/SKILL.md also exists, and stopping there
  // puts runs/ in <repo>/.claude/runs/ while sample-data.json lands in
  // <repo>/runs/ — every live-data mode then renders empty with no error.
  //
  // $HOME is rejected: a skill installed under ~/.claude/skills (the library's
  // symlink install) would otherwise put runs/ and output/ in the home directory.
  const home = realpath(os.homedir());
  let cur = skillDir;
  while (cur !== path.dirname(cur)) {
    if (realpath(cur) !== home && containsSkill(cur, skillName)) return cur;
    cur = path.dirname(cur);
  }
  return cwd;
}

function detectPlatform(skillDir) {
  const forced = process.env.TS_CHART_PLATFORM;
  if (forced === "claude-app" || forced === "claude-code") return forced;
  if (skillDir.startsWith("/mnt/skills/") || fs.existsSync("/mnt/user-data")) return "claude-app";
  return "claude-code";
}

function hasDisplay() {
  if (process.platform !== "linux") return true; // macOS / Windows always have one
  return Boolean(process.env.DISPLAY || process.env.WAYLAND_DISPLAY);
}

// Headed is preferred everywhere it can work. `headless` is a fallback, chosen
// here only when there is no display; a headed launch that fails is caught by
// the doctor's probe and by start-preview.mjs.
function headlessDefault() {
  const forced = process.env.TS_CHART_HEADLESS;
  if (forced === "1") return true;
  if (forced === "0") return false;
  return !hasDisplay();
}

// ~/.cache/ts-charts (or $XDG_CACHE_HOME/ts-charts): run folders, deliverables, browser deps, sign-in profiles,
// backups, Liveboard working folders and the user's own library. A relative $XDG_CACHE_HOME is ignored (the
// XDG spec says so), since it would resolve against whatever folder the command runs in, a repo included.
export function cacheRoot() {
  const xdg = process.env.XDG_CACHE_HOME;
  return path.join(xdg && path.isAbsolute(xdg) ? xdg : path.join(os.homedir(), ".cache"), "ts-charts");
}

// Charts published from a run (library-emit, build-narratives) go to the user's library under the cache, not
// into the skill folder: their previews and narratives come from live data, and the skill folder may be a
// repo checkout. A slug resolves to the user's copy first, then the shipped library/.
export const userLibrary = () => path.join(cacheRoot(), "library");
export function chartDirOf(slug, skillDir = path.resolve(here, "..")) {
  if (!/^[\w-]+$/.test(String(slug))) return null; // a slug is a folder name, never a path
  for (const d of [path.join(userLibrary(), slug), path.join(skillDir, "library", slug)]) if (fs.existsSync(path.join(d, "chart.js"))) return d;
  return null;
}

export function resolveEnv({ slug } = {}) {
  const skillDir = realpath(path.resolve(here, ".."));
  const skillName = path.basename(skillDir);
  const platform = detectPlatform(skillDir);
  const projectRoot = findProjectRoot(skillDir, skillName);

  let home = process.env.TS_CHART_HOME;
  if (!home) {
    if (platform === "claude-app") {
      home = fs.existsSync("/home/claude") ? "/home/claude/.ts-chart" : path.join(os.homedir(), ".ts-chart");
    } else {
      // Outside the working tree: runs hold live search rows and screenshots of real Liveboards, and must
      // never land in a repo checkout (this skill's own repo included).
      home = cacheRoot();
    }
  }
  home = path.resolve(home);

  let outputRoot = process.env.TS_CHART_OUTPUT_ROOT;
  if (!outputRoot) {
    if (platform === "claude-app") {
      outputRoot = fs.existsSync("/mnt/user-data/outputs") ? "/mnt/user-data/outputs" : path.join(home, "output");
    } else {
      outputRoot = path.join(home, "output");
    }
  }

  const env = {
    skillDir, skillName, platform, projectRoot, home,
    helpersDir: here,
    scaffoldDir: path.join(skillDir, "scaffold"),
    runsRoot: path.join(home, "runs"),
    outputRoot: path.resolve(outputRoot),
    depsDir: path.join(home, "deps"),
    headless: headlessDefault(),
    display: hasDisplay(),
    helpersWritable: isWritable(here),
  };
  if (slug) {
    // A slug names folders under runs/ and output/: letters, digits, - and _, never a path.
    if (!/^[\w-]+$/.test(String(slug))) throw new Error("the slug may hold only letters, digits, - and _ (got " + JSON.stringify(slug) + ")");
    env.slug = slug;
    env.runDir = path.join(env.runsRoot, slug);
    env.chartDir = path.join(env.runDir, "chart");
    env.attemptsDir = path.join(env.runDir, "attempts");
    env.previewDir = path.join(env.runDir, ".preview");
    env.outDir = path.join(env.outputRoot, slug);
  }
  return env;
}

function globalNodeModules() {
  const r = spawnSync("npm", ["root", "-g"], { encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : null;
}

// The sandbox has no write access to the skill folder, so the module may live in
// helpers/ (Claude Code), in <home>/deps (Claude app), or globally.
export async function loadPlaywright(env) {
  const bases = [env.helpersDir, env.depsDir, process.cwd(), os.homedir()];
  for (const p of (process.env.NODE_PATH || "").split(path.delimiter)) if (p) bases.push(path.dirname(p));
  let triedGlobal = false;
  for (let i = 0; i < bases.length + 1; i++) {
    let base = bases[i];
    if (i === bases.length) {
      if (triedGlobal) break;
      triedGlobal = true;
      const g = globalNodeModules();
      if (!g) break;
      base = path.dirname(g);
    }
    const req = createRequire(path.join(base, "noop.js"));
    for (const name of ["playwright", "playwright-core"]) {
      let resolved;
      try { resolved = req.resolve(name); } catch { continue; }
      const mod = await import(pathToFileURL(resolved).href);
      const chromium = mod.chromium ?? mod.default?.chromium;
      if (!chromium) continue;
      let version = "?";
      try { version = req(`${name}/package.json`).version; } catch {}
      return { chromium, name, version, from: path.dirname(resolved) };
    }
  }
  return null;
}

function newestChromiumUnder(dir) {
  let entries;
  try { entries = fs.readdirSync(dir); } catch { return null; }
  const revs = entries.filter((e) => /^chromium-\d+$/.test(e))
    .sort((a, b) => Number(b.split("-")[1]) - Number(a.split("-")[1]));
  for (const rev of revs) {
    for (const rel of ["chrome-linux/chrome", "chrome-linux64/chrome",
                       "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
                       "chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
                       "chrome-mac/Chromium.app/Contents/MacOS/Chromium"]) {
      const p = path.join(dir, rev, rel);
      if (fs.existsSync(p)) return p;
    }
  }
  return null;
}

function which(bin) {
  const r = spawnSync("sh", ["-c", `command -v ${bin}`], { encoding: "utf8" });
  const p = r.status === 0 ? r.stdout.trim() : "";
  return p && fs.existsSync(p) ? p : null;
}

// Find a browser without downloading one. In the Claude app `playwright install`
// is blocked and wastes minutes; the sandbox ships Chromium at a fixed path.
export function resolveBrowser(pw) {
  // An explicit override always wins over the bundled build.
  for (const v of ["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "CHROME_PATH", "CHROMIUM_PATH"]) {
    const p = process.env[v];
    if (p && fs.existsSync(p)) return { kind: `env ${v}`, path: p };
  }
  try {
    const p = pw?.chromium.executablePath();
    if (p && fs.existsSync(p)) return { kind: "bundled", path: p };
  } catch {}
  if (fs.existsSync("/opt/pw-browsers/chromium")) return { kind: "known", path: "/opt/pw-browsers/chromium" };
  for (const dir of [process.env.PLAYWRIGHT_BROWSERS_PATH, "/opt/pw-browsers",
                     path.join(os.homedir(), ".cache", "ms-playwright"),
                     path.join(os.homedir(), "Library", "Caches", "ms-playwright"), "/ms-playwright"]) {
    if (!dir) continue;
    const p = newestChromiumUnder(dir);
    if (p) return { kind: "known", path: p };
  }
  for (const bin of ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]) {
    const p = which(bin);
    if (p) return { kind: "system", path: p };
  }
  return null;
}

// Headless args that keep Chromium alive in a container: /dev/shm is tiny there
// and there is no GPU. Harmless on a desktop.
const CONTAINER_ARGS = ["--disable-dev-shm-usage", "--disable-gpu"];

export function launchOptions(browser, { headless, extraArgs = [] }) {
  const opts = { headless, args: [...(headless ? CONTAINER_ARGS : []), ...extraArgs] };
  if (browser && browser.kind !== "bundled") opts.executablePath = browser.path;
  // Full Chromium in new-headless mode, not chromium_headless_shell — the same
  // renderer the headed window uses, so the two capture identically.
  if (browser?.kind === "bundled" && headless) opts.channel = "chromium";
  return opts;
}

function fixCommand(env, pw, browser) {
  const helpers = env.helpersDir;
  if (!pw) {
    return env.platform === "claude-app" || !env.helpersWritable
      ? `npm install --prefix "${env.depsDir}" playwright-core`
      : `cd "${helpers}" && npm install && npx playwright install chromium`;
  }
  if (!browser) {
    return env.platform === "claude-app"
      ? "none known: no Chromium in this sandbox. Paste this block back to the skill author."
      : `cd "${helpers}" && npx playwright install chromium`;
  }
  return "none";
}

async function probe(pw, browser, headless) {
  const b = await pw.chromium.launch({ ...launchOptions(browser, { headless }), timeout: 30000 });
  const v = b.version();
  await b.close();
  return v;
}

async function cdnReachable() {
  try {
    const r = await fetch("https://cdn.jsdelivr.net/npm/chart.js", {
      method: "HEAD", signal: AbortSignal.timeout(4000),
    });
    return r.ok ? "reachable" : `blocked (HTTP ${r.status})`;
  } catch { return "blocked"; }
}

// The sha384 subresource-integrity value a <script> loading this pinned URL carries.
async function sri(url) {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(8000) });
    return r.ok ? "sha384-" + crypto.createHash("sha384").update(Buffer.from(await r.arrayBuffer())).digest("base64") : `unknown (HTTP ${r.status})`;
  } catch { return "unknown (unreachable)"; }
}

// MayaCharts is pinned by the skill, never "whatever is latest": a new release (or a bad or compromised publish)
// reaches a tile only after someone reviews it and writes its version and integrity here, in the same change as
// the library charts' pins (lean-lint checks every MayaCharts tile against this). The doctor fetches the pinned
// files and checks them against these values, and names a newer release without adopting it.
export const MAYA = {
  version: "0.18.1",
  sri: {
    "maya.core.global.js": "sha384-KZQbG8OHSEU86UWT5Pp3LATC64UAhHxwg1UMKN/lZtsu02CeDifcSVWCewQO2h/6",
    "maya.global.js": "sha384-Z7INdXfgP1H/WUINrm44nlLrtN58MLpFXLi52fr7HiGOGg/J4FAvjgXQM2Wnd9AK",
  },
};
const mayaUrl = (f) => `https://cdn.jsdelivr.net/npm/mayacharts@${MAYA.version}/dist/${f}`;

async function mayaPinned() {
  const files = [];
  for (const [f, want] of Object.entries(MAYA.sri)) {
    const got = await sri(mayaUrl(f));
    if (got.startsWith("unknown")) return `${MAYA.version} pinned; could not fetch ${f} to check it (${got}): build only in preview, and say the pin is unchecked`;
    if (got !== want) return `${MAYA.version} pinned, but the CDN's ${f} does not match the recorded integrity: STOP, do not build MayaCharts tiles; tell the user`;
    files.push(`${f === "maya.global.js" ? "every type" : "core types"} ${mayaUrl(f)} integrity ${want}`);
  }
  let latest = null;
  try {
    const r = await fetch("https://registry.npmjs.org/mayacharts/latest", { signal: AbortSignal.timeout(4000) });
    latest = r.ok ? (await r.json()).version : null;
  } catch {}
  const newer = latest && latest !== MAYA.version ? ` (npm's latest is ${latest}: not used until it is reviewed and pinned in env.mjs)` : "";
  return `${MAYA.version} (pinned by the skill; files match: ${files.join("; ")})${newer}`;
}

function fontFamilies() {
  const r = spawnSync("fc-list", [":", "family"], { encoding: "utf8" });
  if (r.status !== 0) return "n/a";
  return String(new Set(r.stdout.split("\n").filter(Boolean)).size);
}

async function doctor(argv) {
  const slug = argv.find((a) => !a.startsWith("--"));
  const noProbe = argv.includes("--no-probe");
  const env = resolveEnv({ slug });
  const pw = await loadPlaywright(env);
  const browser = pw ? resolveBrowser(pw) : null;

  let mode = env.headless ? `headless (${env.display ? "TS_CHART_HEADLESS=1" : "no display"})` : "headed";
  let launch = "skipped";
  if (pw && browser && !noProbe) {
    try {
      launch = `ok (${await probe(pw, browser, env.headless)})`;
    } catch (e) {
      const first = String(e.message || e).split("\n")[0];
      if (env.headless) {
        launch = `FAILED: ${first}`;
      } else {
        // Headed is preferred; fall back only when it genuinely cannot start.
        try {
          launch = `ok (${await probe(pw, browser, true)})`;
          mode = `headless (headed launch failed: ${first})`;
        } catch (e2) {
          launch = `FAILED: ${String(e2.message || e2).split("\n")[0]}`;
        }
      }
    }
  }
  const depsOk = Boolean(pw && browser) && !launch.startsWith("FAILED");

  const lines = [
    ["platform", env.platform],
    ["mode", mode],
    ["skill", env.skillDir],
    ["home", env.home],
    ["runs-root", env.runsRoot],
    ["output-root", env.outputRoot],
    ["node", process.versions.node],
    ["playwright", pw ? `${pw.name} ${pw.version} (${pw.from})` : "missing"],
    ["browser", browser ? `${browser.kind} ${browser.path}` : "missing"],
    ["browser-launch", launch],
    ["cdn", noProbe ? "skipped" : await cdnReachable()],
    ["fonts", fontFamilies()],
    ["mayacharts", noProbe ? `${MAYA.version} (pinned, unchecked)` : await mayaPinned()],
  ];
  if (slug) {
    lines.push(["run-dir", env.runDir], ["chart-dir", env.chartDir],
               ["attempts-dir", env.attemptsDir], ["out-dir", env.outDir]);
  }
  lines.push(["deps", depsOk ? "ok" : "missing"], ["fix", depsOk ? "none" : fixCommand(env, pw, browser)]);
  for (const [k, v] of lines) console.log(`${k}: ${v}`);
  process.exit(depsOk ? 0 : 1);
}

if (process.argv[1] && realpath(process.argv[1]) === realpath(fileURLToPath(import.meta.url))) {
  doctor(process.argv.slice(2)).catch((e) => { console.error("[env] fatal:", e); process.exit(1); });
}
