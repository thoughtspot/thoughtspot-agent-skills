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
  JSON, String, parseInt, Object, Array, Math
});
vm.runInContext(js + "\n;globalThis.__state = () => state; globalThis.__actions = () => actions;", ctx);

const Q = JSON.parse(data);
const S = () => ctx.__state();
const fail = msg => { console.error(`FAIL on screen "${S().screen}": ${msg}`); process.exit(1); };
const press = i => { const a = ctx.__actions(); if (!a[i]) fail(`no button ${i + 1}`); a[i](); };
const decode = s => s.replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const text = () => decode(screen.innerHTML.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ");
const has = s => text().includes(s.trim().split(/\s+/).join(" ").slice(0, 40));
const expect = (screenName, why) => { if (S().screen !== screenName) fail(`expected "${screenName}": ${why}`); };
const log = [];

press(0);                                                   // title -> map
expect("map", "the title opens the map");
Q.realms.forEach(r => { if (!has(r.name)) fail(`map does not list ${r.name}`); });

// A road other than Law is closed until Law is done.
const firstOpenOther = Q.realms.findIndex((r, i) => i > 0 && !r.sealed);
press(firstOpenOther);
if (!text().includes("The roads open once")) fail("a realm other than Law should wait for Law");
press(1);                                                   // back to the map

// Sealed realms stay sealed.
Q.realms.forEach((r, i) => {
  if (!r.sealed) return;
  press(i);
  if (!text().includes("not yet open")) fail(`${r.name} should be sealed`);
  press(0);
});

// Law: the scroll, then every trial; one deliberate miss first.
const law = Q.realms[0];
press(0); expect("realm", "Law opens"); press(0); expect("scroll", "Law shows the Scroll of Law first");
law.scroll.rows.forEach(row => { if (!has(row.label)) fail(`scroll is missing "${row.label}"`); });
press(0); expect("trials", "the court follows the scroll");
law.trials.forEach((t, n) => {
  if (!has(t.text)) fail("petition not shown");
  if (n === 0) {
    press((t.correct + 1) % t.options.length);
    if (S().flash.ok || S().hp !== 2 || !has(t.why)) fail("a wrong verdict must cost trust and explain");
    press(0);                                               // next petitioner
    return;
  }
  press(t.correct);
  if (!S().flash.ok || !has(t.why)) fail("a correct verdict was marked wrong or unexplained");
  press(0);
});
if (!text().includes("Royal decree")) fail("Law should end in the decree");
log.push(`law: scroll + ${law.trials.length} trials, decree shown`);
press(0); expect("map", "the decree returns to the map");

// Every open dragon realm, every dragon, every scale; a miss on the first scale of each realm.
Q.realms.forEach((r, i) => {
  if (r.sealed || !r.encounters.length) return;
  press(i); expect("realm", r.name); press(0);
  r.encounters.forEach((e, n) => {
    expect("encIntro", `dragon ${n + 1} of ${r.name}`);
    if (!has(e.quest)) fail("quest not shown");
    press(0); expect("forge", "the scroll goes to the Forge"); press(0); expect("battle", "the fight starts");
    e.points.forEach((p, k) => {
      if (!has(p.ask)) fail("question not shown");
      const lit = (screen.innerHTML.match(/class="ln[^"]*\bon\b/g) || []).length;
      const want = (p.sqlHl === "all" ? e.sql.length : p.sqlHl.length) +
                   (p.scrollHl === "all" ? e.agentql.length : p.scrollHl.length);
      if (lit !== want) fail(`expected ${want} highlighted lines, found ${lit}`);
      if (n === 0 && k === 0) {
        press((p.correct + 1) % p.options.length);
        if (S().hp !== 2 || !has(p.hint)) fail("a miss must cost a heart and show the hint");
        press(0);                                           // try again
      }
      press(p.correct);
      if (!S().flash.ok || !has(p.lesson)) fail("the right answer was marked wrong or the lesson is missing");
      press(0);
    });
    expect("victory", "the dragon falls");
    if (!has(e.loot)) fail("loot not shown");
    press(0);                                               // next dragon, or back to the map
  });
  expect("map", `${r.name} returns to the map when cleared`);
  log.push(`${r.id}: ${r.encounters.length} dragon(s), ${r.encounters.reduce((a, e) => a + e.points.length, 0)} scales`);
});

// Defeat: three misses on a fresh fight.
const ri = Q.realms.findIndex(r => r.encounters.length);
press(ri); press(0); press(0); press(0);                    // realm -> intro -> forge -> battle
const p0 = Q.realms[ri].encounters[0].points[0];
for (let k = 0; k < 3; k++) { press((p0.correct + 1) % p0.options.length); press(0); }
expect("defeat", "three misses should end in defeat");
log.push("three misses ends in defeat");

const done = JSON.parse(store["aqq-progress"] || "{}");
Q.realms.forEach(r => { if (!r.sealed && !done[r.id]) fail(`${r.id} was cleared but not saved`); });
console.log(log.join("\n"));
