// Smoke-play any pack's built classic page headlessly: always take the first option, and from the
// map go to the first realm, then the second once the first is done. Prints each screen visited and
// exits non-zero on any error. Unlike play_quest.js it assumes nothing about the game's content.
//   node smoke_page.js <built index.html>
"use strict";
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const block = id => html.split(`<script id="${id}" type="application/json">`)[1].split("</script>")[0];
const js = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].pop()[1];
const store = {}, listeners = {};
const el = () => ({ textContent: "", setAttribute() {} });
const screen = { innerHTML: "", querySelector: () => null };
const els = { "quest-data": { textContent: block("quest-data") }, "classic-art": { textContent: block("classic-art") },
              live: el(), "sound-sfx": el(), "sound-music": el() };
const ctx = vm.createContext({
  document: { getElementById: id => els[id] || screen, activeElement: null, body: {}, hidden: false,
              addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); } },
  localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } },
  setInterval: () => 0, clearInterval: () => {}, JSON, String, Number, parseInt, Object, Array, Math
});
vm.runInContext(js + "\n;globalThis.__state = () => state;", ctx);
const key = k => (listeners.keydown || []).forEach(fn => fn({ key: k, metaKey: false, ctrlKey: false, altKey: false,
                                                                repeat: false, preventDefault() {} }));
const seen = [];
let decreed = false;
for (let i = 0; i < 300; i++) {
  const s = ctx.__state().screen;
  if (seen[seen.length - 1] !== s) seen.push(s);
  if (s === "victory") break;
  if (s === "decree") decreed = true;
  if (!screen.innerHTML) { console.error(`FAIL: screen "${s}" rendered nothing`); process.exit(1); }
  key(s === "map" && decreed ? "2" : "1");
}
console.log(seen.join(" > "));
if (!seen.includes("victory")) { console.error("FAIL: never reached victory"); process.exit(1); }
