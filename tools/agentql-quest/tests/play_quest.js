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

// One question, answered the given way: "right" | "wrong-then-right" | "magic".
// `wrongIndex` picks the wrong option (default: the one after the right answer).
function answerQuestion(correct, nOptions, how, explain, revealText, wrongIndex) {
  const before = S().gold;
  if (how === "magic") {
    const heard = notes;
    press(magicButton());
    if (S().flash.kind !== "magic" || S().gold !== before) fail("magic must win and lose no gold");
    if (notes === heard) fail("magic should make its sound");
    if (!has(revealText) || !has(explain)) fail("magic must show the answer and its explanation");
    press(0);
    return;
  }
  if (how === "wrong-then-right") {
    const heard = notes;
    press(wrongIndex ?? (correct + 1) % nOptions);
    const taken = Math.min(LOSS, before);
    if (S().flash.kind !== "loss" || S().gold !== before - taken) fail(`a miss with ${before} gold should take ${taken}`);
    if (notes === heard) fail("a miss should make its sound");
    press(0);                                                   // answer again, same question
  }
  const mid = S().gold, heard = notes;
  press(correct);
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

// Other roads wait for Law.
press(1);
if (!text().includes("The roads open once")) fail("a realm other than Law should wait for Law");
press(1);

const expected = {};

// ---- Law: each hall teaches, then asks. Empty-purse miss is free; magic is free. --------------
const law = Q.realms[0];
press(0); expect("realm", "Law opens"); press(0);
let missed = false;
law.halls.forEach((h, hi) => {
  expect("hall", `hall ${hi + 1}`);
  if (!has(h.title) || !h.teach.every(t => has(t))) fail(`hall ${hi + 1} must show its title and what it teaches`);
  h.rows.forEach(row => { if (!has(row.label)) fail(`hall ${hi + 1} is missing its "${row.label}" row`); });
  // The throne room: two torches, one crown, and the hall's own name on the banner (letters in a
  // name must never turn into torches or crowns).
  const flames = (screen.innerHTML.match(/class="flame/g) || []).length, crowns = (screen.innerHTML.match(/class="hot crown"/g) || []).length;
  if (flames !== 2 || crowns !== 1) fail(`hall ${hi + 1}: expected 2 torches and 1 crown, found ${flames} and ${crowns}`);
  if (!screen.innerHTML.includes(h.title.toUpperCase())) fail(`hall ${hi + 1}: the banner should carry "${h.title.toUpperCase()}"`);
  press(0); expect("trials", `hall ${hi + 1}'s petitions`);
  h.trials.forEach((t, ti) => {
    if (!has(t.text)) fail("petition not shown");
    const how = hi === 0 && ti === 0 ? "wrong-then-right" : hi === 0 && ti === 1 ? "magic" : hi === 1 && ti === 0 ? "wrong-then-right" : "right";
    if (how === "wrong-then-right" && hi === 1) missed = true;
    answerQuestion(t.correct, t.options.length, how, t.why, t.options[t.correct]);
  });
});
const lawQs = law.halls.reduce((n, h) => n + h.trials.length, 0);
expected.law = WIN * (lawQs - 1) - LOSS;                       // one magic (no gold); one paid miss
if (S().gold !== expected.law) fail(`Law should end with ${expected.law} gold, has ${S().gold}`);
expect("decree", "the last hall ends in the decree");
if (!text().includes(`${expected.law} of`)) fail("the decree should show the gold won");
law.scroll.rows.forEach(row => { if (!has(row.label)) fail(`the recap is missing "${row.label}"`); });
log.push(`law: ${law.halls.length} halls, ${lawQs} questions, ${expected.law} gold; recap table shown`);

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

// ---- Every quest: read the intent, then the AgentQL path and its dragon. ----------------------
Q.realms.forEach((r, ri) => {
  if (r.sealed || !r.encounters.length) return;
  const e = r.encounters[0], p = e.path;
  press(ri); expect("realm", r.name); press(0); expect("quest", `${r.name} opens on the question`);
  if (!has(e.quest)) fail("the business question is not shown");
  if (!screen.innerHTML.includes('class="art scene"') || !screen.innerHTML.includes(r.name.toUpperCase()))
    fail(`${r.name}'s question should show its own scene, with its name on the banner`);
  // Blocked paths cost nothing; then one paid wrong path; then the right one.
  p.outcomes.forEach((o, i) => {
    if (o.kind !== "blocked") return;
    const g = S().gold;
    press(i);
    if (S().flash.kind !== "blocked" || S().gold !== g || !has(o.why)) fail("a blocked path must explain itself and cost nothing");
    press(0);
  });
  const wrong = p.outcomes.findIndex(o => o.kind === "loss");
  if (wrong < 0) fail("every quest should have at least one wrong path");
  answerQuestion(p.correct, p.options.length, "right", p.outcomes[p.correct].why, p.options[p.correct]);
  expect("wizard", "the Wizard writes the AgentQL after the right path");
  if (!has(e.agentql[0])) fail("the scroll is not shown");
  press(0); expect("forge", "the scroll goes to the Forge"); press(0); expect("battle", "the fight starts");
  e.points.forEach((pt, k) => {
    if (!has(pt.ask)) fail("question not shown");
    const lit = (screen.innerHTML.match(/class="ln[^"]*\bon\b/g) || []).length;
    const want = (pt.sqlHl === "all" ? e.sql.length : pt.sqlHl.length) + (pt.scrollHl === "all" ? e.agentql.length : pt.scrollHl.length);
    if (lit !== want) fail(`expected ${want} highlighted lines, found ${lit}`);
    answerQuestion(pt.correct, pt.options.length, k === 1 ? "wrong-then-right" : "right", pt.lesson, pt.options[pt.correct]);
  });
  expect("victory", "the dragon falls");
  // The hoard: rules tagged by who adds them, the player's part apart, determinism as the conclusion.
  if (!text().includes("DETERMINISTIC RULES UNCOVERED")) fail("the hoard should be headed as deterministic rules");
  if (!text().includes("So the same AgentQL always compiles to the same SQL.")) fail("every hoard ends on determinism");
  const hoard = text(), yoursAt = hoard.indexOf("YOUR PART");
  e.points.filter(pt => pt.rule && pt.ruleBy !== "determinism").forEach(pt => {
    if (!has(pt.rule)) fail(`the hoard should list "${pt.rule}"`);
    const at = hoard.indexOf(pt.rule.slice(0, 30));
    const inYours = yoursAt >= 0 && at > yoursAt;
    if ((pt.ruleBy === "agentql") !== inYours) fail(`"${pt.rule}" is in the wrong part of the hoard`);
  });
  expected[r.id] = WIN * (1 + e.points.length) - LOSS;
  if (S().gold !== expected[r.id]) fail(`${r.id} should end with ${expected[r.id]} gold, has ${S().gold}`);
  press(0); expect("map", "the hoard returns to the map");
  log.push(`${r.id}: path (${p.outcomes.filter(o => o.kind === "blocked").length} blocked) + ${e.points.length} scales, ${expected[r.id]} gold`);
});

// Saved bests, the course high score, and a worse replay that can't lower a best.
const saved = JSON.parse(store["aqq-progress"]);
Object.entries(expected).forEach(([id, g]) => { if (!saved[id] || !saved[id].done || saved[id].best !== g) fail(`${id} should save best ${g}`); });
const total = Object.values(expected).reduce((a, b) => a + b, 0);
if (!text().includes("Course complete") || !text().includes(`${total} of`)) fail(`the map should show the course high score ${total}`);
const ri = Q.realms.findIndex(r => r.encounters.length);
press(ri); press(0);
const e0 = Q.realms[ri].encounters[0];
answerQuestion(e0.path.correct, e0.path.options.length, "magic", e0.path.outcomes[e0.path.correct].why, e0.path.options[e0.path.correct]);
press(0); press(0);
e0.points.forEach(pt => answerQuestion(pt.correct, pt.options.length, "magic", pt.lesson, pt.options[pt.correct]));
expect("victory", "an all-magic run still finishes the quest");
if (JSON.parse(store["aqq-progress"])[Q.realms[ri].id].best !== expected[Q.realms[ri].id]) fail("a 0-gold replay must not lower the best");
log.push(`course high score ${total}, kept after a 0-gold replay`);
log.push(`sound: silent before input; coin, theft, magic and fanfare heard; toggles and music work (${notes} notes)`);
console.log(log.join("\n"));
