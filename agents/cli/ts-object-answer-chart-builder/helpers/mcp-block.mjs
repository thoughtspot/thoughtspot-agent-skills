#!/usr/bin/env node
// mcp-block.mjs <block> [--key value ...]
//
// Prints one MCP block, ready to paste as the `code` of execute-thoughtspot-code. A block is a versioned file:
// helpers/mcp/<block>.js, or a path to one (the Liveboard skill keeps its own under scripts/mcp/). Every REST call
// the skills make in the sandbox lives in such a file (or in answer-patch.js / patch.js), never in SKILL.md, so
// each one is reviewed, tested against a mock `ts` (tools/smoke-tests in thoughtspot-agent-skills) and changed in
// one place. Each --key fills the block's __KEY__ placeholder as a JSON literal; --tabs takes a comma-separated
// list, --rows a number. A placeholder left unfilled, or a key the block does not take, stops it.
//
//   node mcp-block.mjs intake --words "retail"
//   node mcp-block.mjs model-columns --model <guid>
//   node mcp-block.mjs fixture --model <guid> --search "[sales] [region]" --rows 1000
//   node mcp-block.mjs <L>/scripts/mcp/create-liveboard.js --name "..." --description "..." --tabs "01 About,02 Where"
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const [name, ...rest] = process.argv.slice(2);
if (!name) { console.error("usage: mcp-block.mjs <block> [--key value ...]"); process.exit(2); }
const file = name.endsWith(".js") ? path.resolve(name) : path.join(here, "mcp", name + ".js");
if ((!name.endsWith(".js") && !/^[\w-]+$/.test(name)) || !fs.existsSync(file)) { console.error("no MCP block " + name); process.exit(2); }
const vals = {};
for (let i = 0; i < rest.length; i += 2) {
  const k = rest[i], v = rest[i + 1];
  if (!/^--[a-z]+$/.test(k) || v === undefined) { console.error("expected --key value pairs, got " + JSON.stringify(rest.slice(i))); process.exit(2); }
  const key = k.slice(2);
  vals[key.toUpperCase()] = key === "tabs" ? v.split(",").map((t) => t.trim()).filter(Boolean) : key === "rows" ? Number(v) : v;
}
let code = fs.readFileSync(file, "utf8");
const wanted = [...new Set([...code.matchAll(/__([A-Z]+)__/g)].map((m) => m[1]))];
const extra = Object.keys(vals).filter((k) => !wanted.includes(k)), missing = wanted.filter((k) => !(k in vals));
if (extra.length || missing.length) { console.error((missing.length ? "missing --" + missing.map((k) => k.toLowerCase()).join(", --") + " " : "") + (extra.length ? "not taken by " + path.basename(file) + ": --" + extra.map((k) => k.toLowerCase()).join(", --") : "")); process.exit(2); }
for (const k of wanted) code = code.split("__" + k + "__").join(JSON.stringify(vals[k]));
console.log(code);
