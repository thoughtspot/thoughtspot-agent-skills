// Smoke-play any pack's built classic page headlessly, assuming nothing about its content: every
// open realm in map order, every question settled with magic (the last button, which always
// shows the answer), every other screen moved on with its first button. Every screen visited, the
// last included, must render something with no "undefined" and no unfilled {name}. Prints the
// screens visited and exits non-zero on any failure or error.
//   node smoke_page.js <built index.html>
"use strict";
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const block = id => html.split(`<script id="${id}" type="application/json">`)[1].split("</script>")[0];
const js = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].pop()[1];
const quest = JSON.parse(block("quest-data"));
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
vm.runInContext(js + "\n;globalThis.__state = () => state; globalThis.__actions = () => actions;", ctx);
const fail = msg => { console.error(`FAIL: ${msg}`); process.exit(1); };
const key = k => (listeners.keydown || []).forEach(fn => fn({ key: k, metaKey: false, ctrlKey: false, altKey: false,
                                                                repeat: false, preventDefault() {} }));
const check = s => {
  if (!screen.innerHTML.trim()) fail(`screen "${s}" rendered nothing`);
  if (/\bundefined\b/.test(screen.innerHTML)) fail(`screen "${s}" shows "undefined"`);
  const unfilled = screen.innerHTML.match(/\{[a-z_]+\}/);
  if (unfilled) fail(`screen "${s}" shows an unfilled ${unfilled[0]}`);
};
const QUESTIONS = new Set(["trials", "quest", "battle"]);
const open = quest.realms.map((r, i) => (r.sealed ? -1 : i)).filter(i => i >= 0);
const played = new Set(), seen = [];
for (let i = 0; i < 2000; i++) {
  const st = ctx.__state(), s = st.screen;
  check(s);
  if (seen[seen.length - 1] !== s) seen.push(s);
  if (s === "map") {
    const next = open.find(r => !played.has(r));
    if (next === undefined) break;                       // every open realm done
    played.add(next);
    key(String(next + 1));
  } else if (QUESTIONS.has(s) && !st.flash) {
    key(String(ctx.__actions().length));                 // magic: always the last button
  } else {
    key("1");
  }
}
console.log(seen.join(" > "));
if (open.some(r => !played.has(r))) fail("did not reach every open realm");
for (const want of ["decree", "victory"]) {
  if (quest.realms.some(r => !r.sealed && (want === "decree" ? r.halls.length : r.encounters.length)) && !seen.includes(want))
    fail(`never reached ${want}`);
}
