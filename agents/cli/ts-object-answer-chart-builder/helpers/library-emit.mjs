#!/usr/bin/env node
// library-emit.mjs <slug> --title "..." --search "[sales] [date].monthly" --question "..." \
//                  --lib "Muze" --tile "8x6" --interactions "hover tooltip; click key to hide series" \
//                  [--notes "..."] [--png attempts/NN.WxH.png] [--tab Pulse] [--into-skill]
//                  [--model "(Sample) Retail - Apparel"] [--mode A|B|C]
//   --tile is the Liveboard footprint in grid units, WxH (e.g. 8x6); it is written to the README as given.
//   --png is relative to the RUN directory (runs/<slug>/), not the repo root.
//   --model names the model the search runs on; --mode is the data mode (references/byoc-data-modes.md).
//   Both default to the shipped library's values, (Sample) Retail - Apparel and B.
//
// Publishes a finished run into the user's library, ~/.cache/ts-charts/library/<slug>/ (outside any repo: the
// preview is a screenshot of live data). liveboard-pack and answer-pack find it there by slug. --into-skill
// writes into this skill's own library/ instead; that is for maintainers adding a chart to the shipped
// library, and its preview must not show customer data.
//   chart.html chart.css chart.js   the three files, byte for byte
//   preview.png                     the screenshot you name with --png (default: newest full-size snap)
//   query.txt                       the search the tile is bound to
//   README.md                       question, search, library, tile size, interactions, notes
// and refuses to publish when the files contain non-ASCII characters (they are pasted through a
// browser textarea) or when the shared core block has drifted from library/_shared.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolveEnv, userLibrary } from "./env.mjs";

const all = process.argv.slice(2);
const intoSkill = all.includes("--into-skill");
const args = all.filter((a) => a !== "--into-skill");
const VALUED = new Set(["title", "search", "question", "lib", "tile", "interactions", "notes", "png", "tab", "model", "mode"]);
const opt = {};
const pos = [];
for (let i = 0; i < args.length; i++) {
  if (!args[i].startsWith("--")) { pos.push(args[i]); continue; }
  const k = args[i].slice(2);
  if (!VALUED.has(k)) { console.error("unknown option --" + k); process.exit(2); }
  // A valued flag must have a value: `--model --mode B` must not record "--mode" as the model.
  if (args[i + 1] === undefined || args[i + 1].startsWith("--")) { console.error("--" + k + " needs a value"); process.exit(2); }
  opt[k] = args[++i];
}
const [slug] = pos;
const need = ["title", "search", "question", "lib", "tile", "interactions"];
if (!slug || pos.length !== 1 || need.some((k) => !opt[k])) {
  console.error('usage: library-emit.mjs <slug> --title T --search S --question Q --lib L --tile WxH --interactions I [--notes N] [--png P] [--tab T] [--model M] [--mode A|B|C]');
  process.exit(2);
}
if (!/^\d+x\d+$/.test(opt.tile)) { console.error("--tile expects grid units WxH, e.g. 8x6 (got " + JSON.stringify(opt.tile) + ")"); process.exit(2); }
const model = opt.model ?? "(Sample) Retail - Apparel";
const mode = (opt.mode ?? "B").toUpperCase();
if (!/^[ABC]$/.test(mode)) { console.error("--mode expects A, B or C (got " + JSON.stringify(opt.mode) + ")"); process.exit(2); }
const MODE_TEXT = {
  A: "A, sample only. Renders its baked-in rows; the search is not read.",
  B: "B, live only. With no rows it shows an empty state that names the search.",
  C: "C, live, falling back to sample. With no rows it renders the baked-in sample and badges it.",
};
const here = path.dirname(fileURLToPath(import.meta.url));
const skill = path.resolve(here, "..");
const env = resolveEnv({ slug });
const dest = path.join(intoSkill ? path.join(skill, "library") : userLibrary(), slug);
const files = ["chart.html", "chart.css", "chart.js"];

for (const f of files) if (!fs.existsSync(path.join(env.chartDir, f))) { console.error("missing " + path.join(env.chartDir, f)); process.exit(1); }

// core drift
try { execFileSync("node", [path.join(here, "sync-core.mjs"), "--check", env.chartDir], { stdio: "pipe" }); }
catch (e) { console.error("shared core has drifted in this run: run helpers/sync-core.mjs " + env.chartDir + "\n" + (e.stdout || "")); process.exit(1); }

// ASCII only
const bad = [];
for (const f of files) {
  const txt = fs.readFileSync(path.join(env.chartDir, f), "utf8");
  txt.split("\n").forEach((line, i) => { const m = /[^\x09\x0a\x0d\x20-\x7e]/.exec(line); if (m) bad.push(`${f}:${i + 1} U+${m[0].codePointAt(0).toString(16).toUpperCase().padStart(4, "0")}`); });
}
if (bad.length) { console.error("non-ASCII characters (write them as escapes or plain ASCII):\n  " + bad.slice(0, 12).join("\n  ")); process.exit(1); }

// preview image
let png = opt.png ? path.resolve(env.runDir, opt.png) : null;
if (!png) {
  const cands = fs.existsSync(env.attemptsDir) ? fs.readdirSync(env.attemptsDir).filter((n) => /^\d+\.png$|^\d+\.\d+x\d+\.png$/.test(n)).map((n) => path.join(env.attemptsDir, n)) : [];
  cands.sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  png = cands[0];
}
if (!png || !fs.existsSync(png)) { console.error("no preview png found; pass --png"); process.exit(1); }

fs.mkdirSync(dest, { recursive: true });
for (const f of files) fs.copyFileSync(path.join(env.chartDir, f), path.join(dest, f));
fs.copyFileSync(png, path.join(dest, "preview.png"));
fs.writeFileSync(path.join(dest, "query.txt"), opt.search + "\n");

const js = fs.readFileSync(path.join(dest, "chart.js"), "utf8");
const cdn = [...new Set([...(js + fs.readFileSync(path.join(dest, "chart.html"), "utf8")).matchAll(/https:\/\/[^\s'"`)]+/g)].map((m) => m[0]))]
  .filter((u) => !/fonts\.googleapis/.test(u));
const readme = `# ${opt.title}

${opt.question}

| | |
|---|---|
| Model | ${model} |
| Search | \`${opt.search}\` |
| Library | ${opt.lib} |
| Tile | ${opt.tile} grid units${opt.tab ? " (" + opt.tab + " tab)" : ""} |
| Data mode | ${MODE_TEXT[mode]} |
| CDN | ${cdn.length ? cdn.join(", ") : "none"} |

## Interactions
${opt.interactions}

${opt.notes ? "## Notes\n" + opt.notes + "\n\n" : ""}## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the \`amuzing core\` markers is shared: change it in \`library/_shared/\` and run \`helpers/sync-core.mjs\`.
`;
fs.writeFileSync(path.join(dest, "README.md"), readme);
console.log("published " + dest + "  (" + files.length + " files + preview.png, query.txt, README.md)");
