// Play a built AgentQL Quest page headlessly. A stub DOM runs the page's own script, and every
// input goes through the page's real listeners: keydown for number keys, S and M, click for
// buttons, visibilitychange for a hidden tab. Exits non-zero with a reason on any failure.
//   node play_quest.js <built index.html>
"use strict";
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const data = html.split('<script id="quest-data" type="application/json">')[1].split("</script>")[0];
const art = html.split('<script id="classic-art" type="application/json">')[1].split("</script>")[0];
const js = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].pop()[1];
const Q = JSON.parse(data);
const KEY = Q.pack.storage_key;  // saves are <key>-progress and <key>-sound
const TAGS = Q.pack.rule_tags;
const groupOf = pt => (pt.rule && TAGS[pt.ruleTag] ? TAGS[pt.ruleTag].group : "");
let current = "";
const fail = (msg, where) => { console.error(`FAIL${where ? ` on screen "${where}"` : ""}: ${msg}`); process.exit(1); };

// A page in a sandbox. `audio`: "fake" (counts notes), "throws" (its constructor throws), "none".
function boot({ audio = "fake", saved = {} } = {}) {
  const page = { notes: 0, store: { ...saved }, listeners: {}, intervals: new Map(), nextId: 1 };
  const param = { value: 1, setValueAtTime() {}, exponentialRampToValueAtTime() {} };
  class FakeAudioContext {
    constructor() { this.currentTime = 0; this.state = "running"; this.destination = {}; page.audio = this; }
    createGain() { return { gain: { ...param }, connect() {} }; }
    createOscillator() { return { type: "", frequency: { ...param }, connect() {}, start() { page.notes++; }, stop() {} }; }
    resume() {}
  }
  class ThrowingAudioContext { constructor() { throw new Error("audio is not allowed here"); } }
  page.screen = { innerHTML: "", querySelector: () => null };
  const el = () => ({ textContent: "", setAttribute() {} });
  const els = { "quest-data": { textContent: data }, "classic-art": { textContent: art }, live: el(), "sound-sfx": el(), "sound-music": el() };
  page.doc = {
    getElementById: id => els[id] || page.screen,
    addEventListener: (type, fn) => { (page.listeners[type] = page.listeners[type] || []).push(fn); },
    activeElement: null, body: {}, hidden: false
  };
  const globals = {
    document: page.doc,
    localStorage: { getItem: k => page.store[k] ?? null, setItem: (k, v) => { page.store[k] = v; } },
    setInterval: fn => { const id = page.nextId++; page.intervals.set(id, fn); return id; },
    clearInterval: id => page.intervals.delete(id),
    JSON, String, Number, parseInt, Object, Array, Math
  };
  if (audio === "fake") globals.AudioContext = FakeAudioContext;
  if (audio === "throws") globals.AudioContext = ThrowingAudioContext;
  page.ctx = vm.createContext(globals);
  vm.runInContext(js + "\n;globalThis.__state = () => state; globalThis.__actions = () => actions;" +
                  "globalThis.__sound = Sound; globalThis.__gold = { WIN: GOLD_WIN, LOSS: GOLD_LOSS };", page.ctx);
  page.fire = (type, ev) => (page.listeners[type] || []).forEach(fn => fn(ev));
  page.key = (k, extra = {}) => page.fire("keydown", { key: k, metaKey: false, ctrlKey: false, altKey: false,
                                                       repeat: false, preventDefault() {}, ...extra });
  // A click on choice n, or on a sound button, as the page's own `closest()` lookups see it.
  page.click = what => page.fire("click", { target: { closest: sel =>
    typeof what === "number" ? (sel === ".choices button" ? { dataset: { i: String(what) } } : null)
                             : (sel === `#${what}` ? {} : null) } });
  page.S = () => page.ctx.__state();
  return page;
}

// ---- the main play-through, every input through the real listeners ---------------------------
const P = boot();
const S = P.S;
const where = () => S().screen;
const { WIN, LOSS } = P.ctx.__gold;
const press = i => {                                       // number key i+1, as a player types it
  const n = P.ctx.__actions().length;
  if (i >= n) fail(`no button ${i + 1}`, where());
  P.key(String(i + 1));
};
const decode = s => s.replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const text = () => decode(P.screen.innerHTML.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ");
const has = s => text().includes(s.trim().split(/\s+/).join(" ").slice(0, 40));
const expect = (screenName, why) => { if (S().screen !== screenName) fail(`expected "${screenName}": ${why}`, where()); };
const magicButton = () => P.ctx.__actions().length - 1;   // magic is always the last choice
const log = [];

function answerQuestion(correct, nOptions, how, explain, revealText) {
  const before = S().gold;
  if (how === "magic") {
    const heard = P.notes;
    press(magicButton());
    if (S().flash.kind !== "magic" || S().gold !== before) fail("magic must win and lose no gold", where());
    if (P.notes === heard) fail("magic should make its sound", where());
    if (!has(revealText) || !has(explain)) fail("magic must show the answer and its explanation", where());
    press(0);
    return;
  }
  if (how === "wrong-then-right") {
    const heard = P.notes;
    press((correct + 1) % nOptions);
    const taken = Math.min(LOSS, before);
    if (S().flash.kind !== "loss" || S().gold !== before - taken) fail(`a miss with ${before} gold should take ${taken}`, where());
    if (P.notes === heard) fail("a miss should make its sound", where());
    press(0);
  }
  const mid = S().gold, heard = P.notes;
  press(correct);
  if (S().flash.kind !== "win" || S().gold !== mid + WIN) fail(`a right answer should add ${WIN} gold`, where());
  if (P.notes === heard) fail("a right answer should sound the coin", where());
  if (!has(explain)) fail("the explanation must follow a right answer", where());
  press(0);
}

// Silence until the first input; that input both unlocks audio and acts.
if (P.notes !== 0) fail("no sound may play before the player clicks or presses a key");
const snd = P.ctx.__sound;
if (!snd.prefs.sfx || snd.prefs.music) fail("defaults should be effects on, music off");
P.click(0);                                               // a click on "Open the map"
expect("map", "a click on the first choice opens the map");
if (P.notes === 0) fail("the first click should unlock audio and blip");
if (P.intervals.size !== 0) fail("music must stay off until the player turns it on");
Q.realms.forEach(r => { if (!has(r.name)) fail(`map does not list ${r.name}`, where()); });

// Held-down keys repeat; a repeat must not act.
const before = S().screen;
P.key("1", { repeat: true });
if (S().screen !== before) fail("a repeated keydown must be ignored");

// S and M, by key and by button; a hidden tab silences the music.
P.key("s"); if (snd.prefs.sfx) fail("S should turn sound effects off");
P.click("sound-sfx"); if (!snd.prefs.sfx) fail("the sound effects button should turn them back on");
P.key("m"); if (!snd.prefs.music || P.intervals.size !== 1) fail("M should turn music on and start one loop");
P.audio.currentTime += 2; let n0 = P.notes; [...P.intervals.values()][0]();
if (P.notes === n0) fail("the music loop should schedule notes");
P.doc.hidden = true; P.fire("visibilitychange", {});
if (P.intervals.size !== 0) fail("hiding the tab should stop the music");
P.doc.hidden = false; P.fire("visibilitychange", {});
if (P.intervals.size !== 1) fail("showing the tab again should resume the music");
P.click("sound-music"); if (snd.prefs.music || P.intervals.size !== 0) fail("the music button should turn music off");
if (JSON.parse(P.store[`${KEY}-sound`]).music !== false) fail("the music setting should be remembered");
log.push("input: number keys, clicks, S/M keys and buttons, key repeat, hidden tab all go through the real listeners");

// Other roads wait for Law.
press(1);
if (!text().includes("The roads open once")) fail("a realm other than Law should wait for Law", where());
press(1);

const expected = {};

// ---- Law: each hall teaches, then asks -----------------------------------------------------------
const law = Q.realms[0];
press(0); expect("realm", "Law opens"); press(0);
law.halls.forEach((h, hi) => {
  expect("hall", `hall ${hi + 1}`);
  if (!has(h.title) || !h.teach.every(t => has(t))) fail(`hall ${hi + 1} must show its title and what it teaches`, where());
  h.rows.forEach(row => { if (!has(row.label)) fail(`hall ${hi + 1} is missing its "${row.label}" row`, where()); });
  const flames = (P.screen.innerHTML.match(/class="flame/g) || []).length, crowns = (P.screen.innerHTML.match(/class="hot crown"/g) || []).length;
  if (flames !== 2 || crowns !== 1) fail(`hall ${hi + 1}: expected 2 torches and 1 crown, found ${flames} and ${crowns}`, where());
  if (!P.screen.innerHTML.includes(h.title.toUpperCase())) fail(`hall ${hi + 1}: the banner should carry its name`, where());
  press(0); expect("trials", `hall ${hi + 1}'s petitions`);
  h.trials.forEach((t, ti) => {
    if (!has(t.text)) fail("petition not shown", where());
    const intro = t.kind === "claim" ? "makes a claim before the court" : "asks which engine should answer";
    if (!text().includes(intro)) fail(`a ${t.kind} trial should open with "${intro}"`, where());
    const how = hi === 0 && ti === 0 ? "wrong-then-right" : hi === 0 && ti === 1 ? "magic" : hi === 1 && ti === 0 ? "wrong-then-right" : "right";
    answerQuestion(t.correct, t.options.length, how, t.why, t.options[t.correct]);
  });
});
const lawQs = law.halls.reduce((n, h) => n + h.trials.length, 0);
expected.law = WIN * (lawQs - 1) - LOSS;                         // one magic (no gold); one paid miss
if (S().gold !== expected.law) fail(`Law should end with ${expected.law} gold, has ${S().gold}`, where());
expect("decree", "the last hall ends in the decree");
law.scroll.rows.forEach(row => { if (!has(row.label)) fail(`the recap is missing "${row.label}"`, where()); });
log.push(`law: ${law.halls.length} halls, ${lawQs} questions, ${expected.law} gold`);
press(0); expect("map", "the decree returns to the map");

// ---- every quest -----------------------------------------------------------------------------------
Q.realms.forEach((r, ri) => {
  if (r.sealed || !r.encounters.length) return;
  const e = r.encounters[0], p = e.path;
  press(ri); expect("realm", r.name); press(0); expect("quest", `${r.name} opens on the question`);
  if (!has(e.quest)) fail("the business question is not shown", where());
  if (!P.screen.innerHTML.includes('class="art scene"') || !P.screen.innerHTML.includes(r.name.toUpperCase()))
    fail(`${r.name}'s question should show its own scene`, where());
  p.outcomes.forEach((o, i) => {
    if (o.kind !== "blocked") return;
    const g = S().gold;
    press(i);
    if (S().flash.kind !== "blocked" || S().gold !== g || !has(o.why)) fail("a blocked path must explain itself and cost nothing", where());
    press(0);
  });
  if (p.outcomes.findIndex(o => o.kind === "loss") < 0) fail("every quest should have at least one wrong path");
  answerQuestion(p.correct, p.options.length, "right", p.outcomes[p.correct].why, p.options[p.correct]);
  expect("guide", "the Wizard writes the AgentQL after the right path");
  press(0); expect("compiler", "the scroll goes to the Forge"); press(0); expect("battle", "the fight starts");
  e.panes.forEach(pane => {
    if (!has(pane.label) || (pane.caption && !has(pane.caption))) fail(`the ${pane.id} pane should show its label and caption`, where());
  });
  const capture = Q.meta.agentql_capture;
  if (capture && (!capture.model || !text().includes(`Captured from generate-sql on ${capture.model}, ${capture.captured}.`)))
    fail("the dragon should name the Model and date it was captured on", where());
  e.points.forEach((pt, k) => {
    if (!has(pt.ask)) fail("question not shown", where());
    const lit = (P.screen.innerHTML.match(/class="ln[^"]*\bon\b/g) || []).length;
    const want = e.panes.reduce((n, pane) => n + (pt.highlights[pane.id] === "all" ? pane.lines.length : pt.highlights[pane.id].length), 0);
    if (lit !== want) fail(`expected ${want} highlighted lines, found ${lit}`, where());
    answerQuestion(pt.correct, pt.options.length, k === 1 ? "wrong-then-right" : "right", pt.why, pt.options[pt.correct]);
  });
  expect("victory", "the dragon falls");
  if (!text().includes("DETERMINISTIC RULES UNCOVERED")) fail("the hoard should be headed as deterministic rules", where());
  if (!text().includes("for the same user, always compiles to the same SQL.")) fail("every hoard ends on determinism", where());
  const hoard = text(), yoursAt = hoard.indexOf("YOUR PART");
  e.points.filter(pt => groupOf(pt) === "rules" || groupOf(pt) === "yours").forEach(pt => {
    if (!has(pt.rule)) fail(`the hoard should list "${pt.rule}"`, where());
    const inYours = yoursAt >= 0 && hoard.indexOf(pt.rule.slice(0, 30)) > yoursAt;
    if ((groupOf(pt) === "yours") !== inYours) fail(`"${pt.rule}" is in the wrong part of the hoard`, where());
  });
  expected[r.id] = WIN * (1 + e.points.length) - LOSS;
  if (S().gold !== expected[r.id]) fail(`${r.id} should end with ${expected[r.id]} gold, has ${S().gold}`, where());
  press(0); expect("map", "the hoard returns to the map");
  log.push(`${r.id}: path + ${e.points.length} scales, ${expected[r.id]} gold`);
});

const saved = JSON.parse(P.store[`${KEY}-progress`]);
Object.entries(expected).forEach(([id, g]) => { if (!saved[id] || !saved[id].done || saved[id].best !== g) fail(`${id} should save best ${g}`); });
const total = Object.values(expected).reduce((a, b) => a + b, 0);
if (!text().includes("Course complete") || !text().includes(`${total} of`)) fail(`the map should show the course high score ${total}`, where());
log.push(`course high score ${total}`);

// ---- audio that throws, and no audio at all: the game must still play -------------------------------
for (const audio of ["throws", "none"]) {
  const A = boot({ audio });
  A.click(0);
  if (A.S().screen !== "map") fail(`with audio "${audio}", the first click must still open the map`);
  A.key("m"); A.key("1");
  if (A.S().screen !== "realm") fail(`with audio "${audio}", keys must keep working`);
}
log.push("audio that throws, or no audio at all: the game still plays, silently");

// ---- a tampered save: markup, impossible scores, unknown realms ---------------------------------------
const evil = JSON.stringify({ law: null, mines: { done: true, best: "<img src=x onerror=alert(1)>" },
                              lake: { done: true, best: 999 }, forests: "x", atlantis: { done: true, best: 50 } });
const T = boot({ saved: { [`${KEY}-progress`]: evil } });
T.click(0);
if (T.S().screen !== "map") fail("a tampered save must not stop the map rendering");
if (/<img/i.test(T.screen.innerHTML)) fail("saved values must never reach the page as markup");
const lake = Q.realms.find(r => r.id === "lake");
const lakeMax = (lake.encounters[0].points.length + 1) * WIN;
if (!T.screen.innerHTML.includes(`best ${lakeMax}/${lakeMax} gold`)) fail("an impossible saved best must be capped at the realm's maximum");
log.push("tampered saves: no markup, scores capped, unknown realms ignored");

console.log(log.join("\n"));
