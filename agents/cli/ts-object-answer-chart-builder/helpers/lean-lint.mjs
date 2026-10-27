#!/usr/bin/env node
// lean-lint.mjs <dir> [<dir> ...]    checks MayaCharts tiles against library-contract.md section 1a.
//   Each <dir> holds chart.html, chart.css, chart.js (a library folder or <RUNS>/<slug>/chart).
//   Exit 1 when any tile fails. Warnings (line counts) do not fail.
// What it enforces: no shared core, no white background, no hard-coded fg, ink only through light-dark(),
// color-scheme light dark, a pinned MayaCharts version and its integrity (same in the html and the js), and the transport rules.
import fs from "node:fs";
import path from "node:path";

const INK = /#1e1e24/i;
let failed = 0;
for (const dir of process.argv.slice(2).filter((a) => !a.startsWith("--"))) {
  const slug = path.basename(path.resolve(dir)) === "chart" ? path.basename(path.dirname(path.resolve(dir))) : path.basename(path.resolve(dir));
  const read = (f) => { try { return fs.readFileSync(path.join(dir, f), "utf8"); } catch { return null; } };
  const html = read("chart.html"), css = read("chart.css"), js = read("chart.js");
  const bad = [], warn = [];
  if (html == null || css == null || js == null) { console.log(`FAIL ${slug}: missing a chart file`); failed++; continue; }
  const all = html + "\n" + css + "\n" + js;
  // core and helpers
  if (/amuzing core|\bAZ\./.test(all)) bad.push("uses the shared core (AZ / core markers)");
  if (fs.existsSync(path.join(dir, ".uses-core"))) bad.push(".uses-core file present");
  // transport
  if (all.includes("`")) bad.push("backtick");
  if (all.includes("${")) bad.push("${");
  if (/[^\x09\x0a\x0d\x20-\x7e]/.test(all)) bad.push("non-ASCII");
  // pinned version, same in html and js
  const vh = [...html.matchAll(/mayacharts@([\d.]+)\/dist\/(maya(?:\.core)?\.global\.js)/g)].map((m) => m[1] + "/" + m[2]);
  const vj = [...js.matchAll(/mayacharts@([\d.]+)\/dist\/(maya(?:\.core)?\.global\.js)/g)].map((m) => m[1] + "/" + m[2]);
  if (!vh.length) bad.push("chart.html has no pinned MayaCharts script tag");
  if (!vj.length) bad.push("chart.js has no pinned MayaCharts loader");
  if (vh.length && vj.length && vh[0] !== vj[0]) bad.push("html and js pin different MayaCharts builds (" + vh[0] + " vs " + vj[0] + ")");
  // subresource integrity on both loads, and the same value: a CDN file that changed must refuse to run
  const ih = (html.match(/<script[^>]*mayacharts@[^>]*integrity="(sha384-[A-Za-z0-9+/=]+)"[^>]*crossorigin="anonymous"/) || [])[1];
  const ij = (js.match(/integrity:\s*(?:SRI|'(sha384-[A-Za-z0-9+/=]+)')/) || [])[1] || (js.match(/const SRI = '(sha384-[A-Za-z0-9+/=]+)'/) || [])[1];
  if (vh.length && !ih) bad.push('chart.html script tag lacks integrity="sha384-..." crossorigin="anonymous"');
  if (vj.length && (!ij || !/crossOrigin:\s*'anonymous'/.test(js))) bad.push("chart.js loader lacks integrity and crossOrigin: 'anonymous'");
  if (ih && ij && ih !== ij) bad.push("html and js carry different integrity values");
  if (!/<maya-chart id="chart"/.test(html)) bad.push('chart.html lacks <maya-chart id="chart">');
  // dark mode
  const strip = (s) => s.replace(/light-dark\([^)]*\)/g, "LD");
  const cssNoLD = strip(css), jsNoLD = strip(js);
  if (/(^|[;{\s])(?:html|body)[^{}]*\{[^}]*background(?:-color)?\s*:\s*(?!transparent|none|inherit)/i.test(css)) bad.push("html/body paint a background (not dark-mode safe)");
  if (/--maya-bg\s*:(?!\s*transparent)/i.test(css)) bad.push("--maya-bg is not transparent");
  if (!/--maya-bg\s*:\s*transparent/i.test(css)) bad.push("--maya-bg: transparent missing");
  if (/--maya-fg(?:-muted)?\s*:/i.test(css)) bad.push("hard-coded --maya-fg / --maya-fg-muted");
  if (/color-scheme\s*:\s*light dark/i.test(css)) bad.push("color-scheme: light dark follows the OS, not ThoughtSpot: set the scheme from the host text colour in chart.js");
  if (!/style\.setProperty\('color-scheme'/.test(js)) bad.push("chart.js does not set color-scheme from the host text colour");
  if (/(^|[^A-Za-z])title\s*[:=]/.test(js.replace(/subtitle|titles/g, ""))) bad.push("a chart-internal title (the Liveboard tile already shows one)");
  if (!/--maya-tooltip-bg\s*:/i.test(css)) bad.push("--maya-tooltip-bg missing (tooltip is see-through on a transparent chart)");
  if (INK.test(cssNoLD)) bad.push("ink #1E1E24 in chart.css outside light-dark()");
  if (INK.test(jsNoLD)) bad.push("ink #1E1E24 in chart.js outside light-dark()");
  if (/(^|[^-\w])#fff(fff)?\b/i.test(strip(css + js)) ) warn.push("a white (#fff) colour is set; check it on a dark host");
  // size
  const lines = (s) => s.split("\n").filter((l) => l.trim()).length;
  const jl = lines(js);
  if (jl > 15) warn.push(`${jl} JS lines (target under 15)`);
  const tag = bad.length ? "FAIL" : "ok  ";
  if (bad.length) failed++;
  console.log(`${tag} ${slug.padEnd(28)} js=${jl} css=${lines(css)} html=${lines(html)}` + (bad.length ? "  | " + bad.join("; ") : "") + (warn.length ? "  | warn: " + warn.join("; ") : ""));
}
process.exit(failed ? 1 : 0);
