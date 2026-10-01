#!/usr/bin/env node
// answer-pack.mjs <chart dir | library slug> --model <guid or name> --search "<search>" --name "<answer name>"
//                 [--description "..."] [--answer <guid> --backup <file>] [--validate | --commit]
//
// Turns one chart (chart.html, chart.css, chart.js) into ready-to-paste MCP code that saves it as an answer
// in ThoughtSpot: a search on the model, shown as a custom chart (MUZE_STUDIO) running these three files.
// Without --answer it creates a new answer; with --answer <guid> it updates that one in place, and a commit then
// needs --backup <file>: a TML export of that answer (ts tml export, or Export TML in ThoughtSpot) that names its
// guid, is under a day old and sits outside any git working tree. The sandbox refuses the update without it.
//
//   --validate  (default) VALIDATE_ONLY import; changes nothing
//   --commit    VALIDATE_ONLY first, and only if that passes an ALL_OR_NONE import, in the same call; then exports
//               the answer and proves it carries exactly these files. One paste does both.
//
// The files are sent unchanged, so what ran in the preview is what the answer runs. Paste the printed block,
// unchanged, as the `code` of execute-thoughtspot-code with confirm_write_operations: true (a validate is a
// write to the MCP too). The sandbox side is helpers/answer-patch.js.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { chartDirOf } from "./env.mjs";
import { checkBackup, GUID } from "./backup-check.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const VALUED = new Set(["--model", "--search", "--name", "--description", "--answer", "--backup"]);
// A valued flag must have a value: a trailing `--answer` must not quietly build a commit for a NEW answer, and
// `--search --name n` must not search for "--name".
for (const [i, a] of argv.entries()) if (VALUED.has(a) && (argv[i + 1] === undefined || argv[i + 1].startsWith("--"))) { console.error(a + " needs a value"); process.exit(2); }
const unknown = argv.filter((a, i) => a.startsWith("--") && !VALUED.has(a) && !["--commit", "--validate"].includes(a) && !VALUED.has(argv[i - 1]));
if (unknown.length) { console.error("unknown option " + unknown.join(", ")); process.exit(2); }
const val = (k) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : undefined; };
const pos = argv.filter((a, i) => !a.startsWith("--") && !VALUED.has(argv[i - 1]));
const MODE = argv.includes("--commit") ? "commit" : "validate";
const P = { model: val("--model"), search: val("--search"), name: val("--name"), description: val("--description"), guid: val("--answer") };
if (pos.length !== 1 || !P.model || !P.search || !P.name) {
  console.error('usage: answer-pack.mjs <chart dir | library slug> --model <guid or name> --search "<search>" --name "<answer name>" [--answer <guid>] [--commit]');
  process.exit(2);
}

if (P.guid && (!GUID.test(P.guid) || /^[0-]+$/.test(P.guid))) { console.error("--answer takes the answer's guid, not " + JSON.stringify(P.guid)); process.exit(2); }
if (P.guid) P.guid = P.guid.toLowerCase();
if (P.guid && MODE === "commit") {
  P.backup = checkBackup(val("--backup"), P.guid, "answer");
  P.backupSha = crypto.createHash("sha256").update(JSON.stringify(P.backup), "utf8").digest("hex");
}
// A path to a folder with the three files, or a library slug (the user's library first, then the shipped one).
let dir = path.resolve(pos[0]);
if (!fs.existsSync(path.join(dir, "chart.js"))) dir = chartDirOf(pos[0]);
if (!dir) { console.error("no chart.js in " + pos[0] + " (or a library chart of that slug)"); process.exit(2); }
const read = (f) => (fs.existsSync(path.join(dir, f)) ? fs.readFileSync(path.join(dir, f), "utf8") : "");
P.f = { html: read("chart.html"), css: read("chart.css"), js: read("chart.js") };
const sha = (s) => crypto.createHash("sha256").update(s, "utf8").digest("hex");
P.sha = { html: sha(P.f.html), css: sha(P.f.css), js: sha(P.f.js) };

// Code goes in as String.raw with real line breaks when it can (easier to paste faithfully), JSON otherwise.
// The sandbox re-checks every sha256 either way.
const lit = (x) => (x.includes("`") || x.includes("${") || /\\u|\r/.test(x) ? JSON.stringify(x) : "String.raw`" + x + "`");
const { f, ...rest } = P;
const payload = "{ ...(" + JSON.stringify(rest) + "),\nf: { html: " + lit(f.html) + ",\ncss: " + lit(f.css) + ",\njs: " + lit(f.js) + " } }";
const tpl = fs.readFileSync(path.join(here, "answer-patch.js"), "utf8");
const block = tpl.replace("'__MODE__'", () => JSON.stringify(MODE)).replace("__PAYLOAD__", () => payload);
console.log(block);
const kb = Math.round(block.length / 1024);
console.error(`\n[answer-pack] ${path.basename(dir)} -> ${P.guid ? "answer " + P.guid : "a new answer"} "${P.name}", mode ${MODE}, ${kb} KB` + (kb > 1500 ? " (large: imports near 2.8 MB have reset the connection)" : ""));
