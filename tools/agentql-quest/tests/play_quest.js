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
// A fake AudioContext that counts the notes the page starts, and timers we tick by hand.
let notes = 0;
const param = { value: 1, setValueAtTime() {}, exponentialRampToValueAtTime() {} };
class FakeAudioContext {
  constructor() { this.currentTime = 0; this.state = "running"; this.destination = {}; FakeAudioContext.last = this; }
  createGain() { return { gain: { ...param }, connect() {} }; }
  createOscillator() { return { type: "", frequency: { ...param }, connect() {}, start() { notes++; }, stop() {} }; }
  resume() {}
}
const intervals = new Map(); let nextId = 1;
const ctx = vm.createContext({
  document: {
    getElementById: id => (id === "quest-data" ? { textContent: data } : screen),
    addEventListener() {}, activeElement: null, body: {}, hidden: false
  },
  localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } },
  AudioContext: FakeAudioContext,
  setInterval: fn => { const id = nextId++; intervals.set(id, fn); return id; },
  clearInterval: id => intervals.delete(id),
  JSON, String, parseInt, Object, Array, Math
});
vm.runInContext(js + "\n;globalThis.__state = () => state; globalThis.__actions = () => actions; globalThis.__sound = Sound;", ctx);

const Q = JSON.parse(data);
const S = () => ctx.__state();
const fail = msg => { console.error(`FAIL on screen "${S().screen}": ${msg}`); process.exit(1); };
const press = i => { const a = ctx.__actions(); if (!a[i]) fail(`no button ${i + 1}`); a[i](); };
const decode = s => s.replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const text = () => decode(screen.innerHTML.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ");
const has = s => text().includes(s.trim().split(/\s+/).join(" ").slice(0, 40));
const expect = (screenName, why) => { if (S().screen !== screenName) fail(`expected "${screenName}": ${why}`); };
const log = [];

// Sound: silent until the player's first input, effects on and music off by default.
if (notes !== 0) fail("no sound may play before the player clicks or presses a key");
const snd = ctx.__sound;
if (!snd.prefs.sfx || snd.prefs.music) fail("defaults should be effects on, music off");
snd.unlock();                                               // what the first click or key press does
press(0);                                                   // title -> map
expect("map", "the title opens the map");
if (notes === 0) fail("moving to the map should blip once audio is unlocked");
if (intervals.size !== 0) fail("music must stay off until the player turns it on");
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
  const heard = notes;
  press(t.correct);
  if (notes === heard) fail("a correct verdict should sound the coin");
  if (!S().flash.ok || !has(t.why)) fail("a correct verdict was marked wrong or unexplained");
  press(0);
});
if (!text().includes("Royal decree")) fail("Law should end in the decree");
// Effects off: an answer makes no sound. Music on: a loop starts and plays notes.
let before = notes;
snd.toggle("sfx"); before = notes;
snd.play("coin");
if (notes !== before) fail("with effects off, the coin sound must not play");
snd.toggle("sfx");
snd.toggle("music");
if (intervals.size !== 1) fail("turning music on should start one loop");
FakeAudioContext.last.currentTime += 2;                     // let two seconds of music pass
before = notes; [...intervals.values()][0]();
if (notes === before) fail("the music loop should schedule notes");
if (!JSON.parse(store["aqq-sound"]).music) fail("the music setting should be remembered");
snd.toggle("music");
if (intervals.size !== 0) fail("turning music off should stop the loop");
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
        const heard = notes;
        press((p.correct + 1) % p.options.length);
        if (notes === heard) fail("a miss should sound the damage");
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
log.push(`sound: silent before input, coin/damage/fanfare heard, toggles and music loop work (${notes} notes)`);
console.log(log.join("\n"));
