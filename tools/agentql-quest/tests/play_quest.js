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
vm.runInContext(js + "\n;globalThis.__state = () => state; globalThis.__actions = () => actions;" +
                "globalThis.__sound = Sound; globalThis.__gold = { WIN: GOLD_WIN, LOSS: GOLD_LOSS };", ctx);

const Q = JSON.parse(data);
const { WIN, LOSS } = ctx.__gold;
const S = () => ctx.__state();
const fail = msg => { console.error(`FAIL on screen "${S().screen}": ${msg}`); process.exit(1); };
const press = i => { const a = ctx.__actions(); if (!a[i]) fail(`no button ${i + 1}`); a[i](); };
const decode = s => s.replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const text = () => decode(screen.innerHTML.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ");
const has = s => text().includes(s.trim().split(/\s+/).join(" ").slice(0, 40));
const expect = (screenName, why) => { if (S().screen !== screenName) fail(`expected "${screenName}": ${why}`); };
const magicButton = () => ctx.__actions().length - 1;          // magic is always the last choice
const log = [];

// One question, answered the given way. "right" | "wrong-then-right" | "magic".
function answerQuestion(q, how, explain) {
  const before = S().gold;
  if (how === "magic") {
    const heard = notes;
    press(magicButton());
    if (S().flash.kind !== "magic" || S().gold !== before) fail("magic must win and lose no gold");
    if (notes === heard) fail("magic should make its sound");
    if (!has(q.options[q.correct]) || !has(explain)) fail("magic must show the answer and its explanation");
    press(0);
    return;
  }
  if (how === "wrong-then-right") {
    const heard = notes;
    press((q.correct + 1) % q.options.length);
    const taken = Math.min(LOSS, before);
    if (S().flash.kind !== "loss" || S().gold !== before - taken) fail(`a miss with ${before} gold should take ${taken}`);
    if (notes === heard) fail("a miss should make the dragon's sound");
    press(0);                                                   // try again, same question
  }
  const mid = S().gold, heard = notes;
  press(q.correct);
  if (S().flash.kind !== "win" || S().gold !== mid + WIN) fail(`a right answer should add ${WIN} gold`);
  if (notes === heard) fail("a right answer should sound the coin");
  if (!has(explain)) fail("the explanation must follow a right answer");
  press(0);
}

// Sound: silent until the player's first input, effects on and music off by default.
if (notes !== 0) fail("no sound may play before the player clicks or presses a key");
const snd = ctx.__sound;
if (!snd.prefs.sfx || snd.prefs.music) fail("defaults should be effects on, music off");
snd.unlock();                                                   // what the first click or key press does
press(0);                                                       // title -> map
expect("map", "the title opens the map");
if (intervals.size !== 0) fail("music must stay off until the player turns it on");
Q.realms.forEach(r => { if (!has(r.name)) fail(`map does not list ${r.name}`); });

// A road other than Law is closed until Law is done; sealed realms stay sealed.
press(Q.realms.findIndex((r, i) => i > 0 && !r.sealed));
if (!text().includes("The roads open once")) fail("a realm other than Law should wait for Law");
press(1);
Q.realms.forEach((r, i) => { if (r.sealed) { press(i); if (!text().includes("not yet open")) fail(`${r.name} should be sealed`); press(0); } });

const expected = {};

// Law: the scroll, then every trial. A miss on an empty purse costs nothing; magic on the second.
const law = Q.realms[0];
press(0); expect("realm", "Law opens"); press(0); expect("scroll", "the Scroll of Law comes first");
law.scroll.rows.forEach(row => { if (!has(row.label)) fail(`scroll is missing "${row.label}"`); });
press(0); expect("trials", "the court follows the scroll");
law.trials.forEach((t, n) => {
  if (!has(t.text)) fail("petition not shown");
  answerQuestion(t, n === 0 ? "wrong-then-right" : n === 1 ? "magic" : n === 2 ? "wrong-then-right" : "right", t.why);
});
expected.law = WIN * (law.trials.length - 1) - LOSS;           // trial 1 missed at 0 gold (free); trial 2 magic; trial 3 missed
if (S().gold !== expected.law) fail(`Law should end with ${expected.law} gold, has ${S().gold}`);
if (!text().includes("Royal decree") || !text().includes(`${expected.law} of`)) fail("the decree should show the gold won");
log.push(`law: scroll + ${law.trials.length} trials, ${expected.law} gold (empty-purse miss free, magic free, one miss -${LOSS})`);

// Effects off: silent. Music on: a loop plays notes, and the setting is remembered.
snd.toggle("sfx"); let before = notes; snd.play("coin");
if (notes !== before) fail("with effects off, the coin sound must not play");
snd.toggle("sfx"); snd.toggle("music");
if (intervals.size !== 1) fail("turning music on should start one loop");
FakeAudioContext.last.currentTime += 2; before = notes; [...intervals.values()][0]();
if (notes === before) fail("the music loop should schedule notes");
if (!JSON.parse(store["aqq-sound"]).music) fail("the music setting should be remembered");
snd.toggle("music");
if (intervals.size !== 0) fail("turning music off should stop the loop");
press(0); expect("map", "the decree returns to the map");

// Every dragon realm: scale 2 of the first dragon is missed once, everything else right first time.
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
      answerQuestion(p, n === 0 && k === 1 ? "wrong-then-right" : "right", p.lesson);
    });
    expect("victory", "the dragon falls");
    if (!has(e.loot)) fail("loot not shown");
    press(0);                                                   // next dragon, or back to the map
  });
  expect("map", `${r.name} returns to the map when cleared`);
  const scales = r.encounters.reduce((a, e) => a + e.points.length, 0);
  expected[r.id] = WIN * scales - LOSS;
  log.push(`${r.id}: ${r.encounters.length} dragon(s), ${scales} scales, ${expected[r.id]} gold`);
});

// Saved bests and the treasury; replaying a realm worse never lowers the best.
const saved = JSON.parse(store["aqq-progress"]);
Object.entries(expected).forEach(([id, g]) => { if (!saved[id] || !saved[id].done || saved[id].best !== g) fail(`${id} should save best ${g}`); });
const total = Object.values(expected).reduce((a, b) => a + b, 0);
if (!text().includes(`${total} of`)) fail(`the map should show the high score ${total}`);
if (!text().includes("Course complete")) fail("with every open realm cleared, the map should say the course is complete");
const lake = Q.realms.findIndex(r => r.id === "lake");
press(lake); press(0); press(0); press(0);                      // realm -> intro -> forge -> battle
Q.realms[lake].encounters[0].points.forEach(p => answerQuestion(p, "magic", p.lesson));
expect("victory", "an all-magic run still finishes the dragon");
if (JSON.parse(store["aqq-progress"]).lake.best !== expected.lake) fail("a 0-gold replay must not lower the best");
log.push(`high score ${total}, kept after a 0-gold replay`);
log.push(`sound: silent before input; coin, theft, magic and fanfare heard; toggles and music work (${notes} notes)`);
console.log(log.join("\n"));
