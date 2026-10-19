// Play a built AgentQL Quest page headlessly: stub the DOM, run the page's own script, and
// press buttons by index the way a player would. Exits non-zero with a reason on any failure.
//   node play_quest.js <built index.html>
"use strict";
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const data = html.split('<script id="quest-data" type="application/json">')[1].split("</script>")[0];
const js = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].pop()[1];
const screen = { innerHTML: "", querySelector: () => null };
const store = {};
const ctx = vm.createContext({
  document: {
    getElementById: id => (id === "quest-data" ? { textContent: data } : screen),
    addEventListener() {}, activeElement: null, body: {}
  },
  localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } },
  JSON, String, parseInt, Object, Array
});
vm.runInContext(js + "\n;globalThis.__state = () => state; globalThis.__actions = () => actions; globalThis.__render = render;", ctx);

const Q = JSON.parse(data);
const S = () => ctx.__state();
const fail = msg => { console.error(`FAIL on screen "${S().screen}": ${msg}`); process.exit(1); };
const press = i => { const a = ctx.__actions(); if (!a[i]) fail(`no button ${i + 1}`); a[i](); };
const decode = s => s.replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const text = () => decode(screen.innerHTML.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ");
const has = s => text().includes(s.trim().split(/\s+/).join(" ").slice(0, 40));
const toChoose = () => { S().screen = "choose"; ctx.__render(); };
const log = [];

// Royal Court as the Queen: judge every claim correctly.
press(0); press(0);
for (const c of Q.court) {
  if (!has(c.claim)) fail("claim not shown");
  press(c.truth ? 0 : 1);
  if (!S().flash.ok) fail("a correct verdict was marked wrong");
  if (!has(c.why)) fail("verdict explanation not shown");
  press(0);
}
if (!text().includes("Royal decree")) fail("court did not end in the decree");
log.push(`court: ${Q.court.length} claims judged, decree shown`);
press(0);

// Every path with no encounters is sealed; every path with encounters opens.
const heroes = { dwarf: 2, elf: 3, human: 4 };
for (const [path, idx] of Object.entries(heroes)) {
  press(idx);
  const open = (Q.paths[path] || []).length > 0;
  if (open !== (S().screen === "intro")) fail(`${path} should be ${open ? "open" : "sealed"}`);
  toChoose();
}

// Each open path: one miss (costs a heart, shows the hint), then every point answered right.
for (const [path, idx] of Object.entries(heroes)) {
  const encs = (Q.paths[path] || []).map(i => Q.encounters[i]);
  if (!encs.length) continue;
  toChoose(); press(idx);
  encs.forEach((e, n) => {
    if (S().screen !== "intro") fail(`expected the intro of dragon ${n + 1}`);
    press(0); press(0);                                  // intro -> forge -> battle
    if (n === 0) {
      press((e.points[0].correct + 1) % e.points[0].options.length);
      if (S().hp !== 2 || !has(e.points[0].hint)) fail("a miss must cost a heart and show the hint");
      press(0);
    }
    for (const p of e.points) {
      if (!has(p.ask)) fail("question not shown");
      const lit = (screen.innerHTML.match(/class="ln[^"]*\bon\b/g) || []).length;
      const want = (p.sqlHl === "all" ? e.sql.length : p.sqlHl.length) +
                   (p.scrollHl === "all" ? e.agentql.length : p.scrollHl.length);
      if (lit !== want) fail(`expected ${want} highlighted lines, found ${lit}`);
      press(p.correct);
      if (!S().flash.ok) fail("the correct answer was marked wrong");
      if (!has(p.lesson)) fail("lesson not shown after a hit");
      press(0);
    }
    if (S().screen !== "victory" || !has(e.loot)) fail("no victory screen with the loot");
    if (n + 1 < encs.length) press(0);
  });
  log.push(`${path}: ${encs.length} dragon(s), ${encs.reduce((a, e) => a + e.points.length, 0)} scales broken`);

  // Defeat: three misses on a fresh fight.
  press(1); press(0);
  const p0 = encs[encs.length - 1].points[0];
  for (let i = 0; i < 3; i++) { press((p0.correct + 1) % p0.options.length); press(0); }
  if (S().screen !== "defeat") fail("three misses should end in defeat");
  log.push(`${path}: three misses ends in defeat`);
  toChoose();
}

if (!store["aqq-best"]) fail("best scores were not saved");
console.log(log.join("\n"));
