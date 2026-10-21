// Smoke-play any pack's built classic page headlessly, assuming nothing about its content: every
// open realm in map order, every question settled with magic (the last button, which always
// shows the answer), every other screen moved on with its first button. A realm counts as played
// only when it opens from the map, reaches its decree (if it has halls) or victory (if it has an
// encounter), and returns to the map. Every screen visited, the last included, must render
// something, with no "undefined" (unless the game's own data says it) and no unfilled {name} the
// pack's strings use as a placeholder. Prints the screens visited and exits non-zero on any failure.
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
// Only names the strings use as placeholders can be left unfilled: content such as a formula's
// {date} is shown as written.
const placeholders = new Set(Object.values(quest.pack.strings).flatMap(t => t.match(/\{\w+\}/g) || []));
const dataSaysUndefined = /\bundefined\b/.test(block("quest-data"));
const check = s => {
  if (!screen.innerHTML.trim()) fail(`screen "${s}" rendered nothing`);
  if (!dataSaysUndefined && /\bundefined\b/.test(screen.innerHTML)) fail(`screen "${s}" shows "undefined"`);
  const unfilled = (screen.innerHTML.match(/\{\w+\}/g) || []).find(m => placeholders.has(m));
  if (unfilled) fail(`screen "${s}" shows an unfilled ${unfilled}`);
};
const QUESTIONS = new Set(["trials", "quest", "battle"]);
const open = quest.realms.map((r, i) => (r.sealed ? -1 : i)).filter(i => i >= 0);
const played = new Set(), finished = new Set(), seen = [];
let entered = null, done = false;
const needs = r => [quest.realms[r].halls.length && "decree", quest.realms[r].encounters.length && "victory"].filter(Boolean);
const reached = new Map();
for (let i = 0; i < 2000; i++) {
  const st = ctx.__state(), s = st.screen;
  check(s);
  if (seen[seen.length - 1] !== s) seen.push(s);
  if (entered !== null && st.realm === entered && (s === "decree" || s === "victory")) reached.get(entered).add(s);
  if (s === "map") {
    if (entered !== null) {
      const missing = needs(entered).filter(w => !reached.get(entered).has(w));
      if (missing.length) fail(`left realm "${quest.realms[entered].id}" without reaching ${missing.join(" and ")}`);
      finished.add(entered); entered = null;
    }
    const next = open.find(r => !played.has(r));
    if (next === undefined) { done = true; break; }
    played.add(next); entered = next; reached.set(next, new Set());
    key(String(next + 1));
    if (ctx.__state().screen !== "realm" || ctx.__state().realm !== next) fail(`realm "${quest.realms[next].id}" did not open from the map`);
  } else if (QUESTIONS.has(s) && !st.flash) {
    key(String(ctx.__actions().length));                 // magic: always the last button
  } else {
    key("1");
  }
}
console.log(seen.join(" > "));
if (!done) fail("ran out of steps before every open realm was finished and the map was back");
