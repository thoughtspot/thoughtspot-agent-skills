// The buttons a built classic page draws must be exactly the actions Quest.machine accepts, on every
// state the page can show: each screen x realm x hall x step x flash, under several saves, and for
// a realm's gate also when the save changes between drawing and pressing (another tab finishing or
// clearing a realm). Candidate actions include malformed ones. Exits non-zero on any mismatch.
//   node drawn_vs_accepted.js <built index.html> [plain|sealed|sealed_first|onehall]
"use strict";
const fs = require("fs"), vm = require("vm");
const [, , file, variant = "plain"] = process.argv;
const html = fs.readFileSync(file, "utf8");
const block = id => html.split(`<script id="${id}" type="application/json">`)[1].split("</script>")[0];
const js = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].pop()[1];
const Q = JSON.parse(block("quest-data"));
if (variant === "sealed") { Q.realms[2].sealed = true; Q.realms[4].sealed = true; }
if (variant === "sealed_first") Q.realms[0].sealed = true;
if (variant === "onehall") Q.realms[0].halls = Q.realms[0].halls.slice(0, 1);
const data = JSON.stringify(Q);
function boot(saved) {
  const P = { store: { ...saved } };
  P.screen = { innerHTML: "", querySelector: () => null };
  const el = () => ({ textContent: "", setAttribute() {} });
  const els = { "quest-data": { textContent: data }, "classic-art": { textContent: block("classic-art") },
                live: el(), "sound-sfx": el(), "sound-music": el() };
  P.ctx = vm.createContext({
    document: { getElementById: id => els[id] || P.screen, hidden: false, addEventListener() {} },
    localStorage: { getItem: k => P.store[k] ?? null, setItem: (k, v) => { P.store[k] = String(v); } },
    setInterval: () => 1, clearInterval: () => {}, JSON, String, Number, parseInt, Object, Array, Math });
  vm.runInContext(js + "\n;globalThis.__set = s => { state = s; }; globalThis.__render = () => render();"
                  + " globalThis.__actions = () => actions; globalThis.__m = machine; globalThis.__lp = () => loadProgress();", P.ctx);
  return P;
}
const KEY = Q.pack.storage_key, ids = Q.realms.map(r => r.id);
const prog = o => ({ [`${KEY}-progress`]: JSON.stringify(o) });
const SAVES = { fresh: {}, first_done: prog({ [ids[0]]: { done: true, best: 30 } }), first_true: prog({ [ids[0]]: true }),
                all_done: prog(Object.fromEntries(ids.map(id => [id, { done: true, best: 999 }]))),
                tampered: { [`${KEY}-progress`]: '{"x":1' } };
const FLASHES = [null, { kind: "win", amount: 10 }, { kind: "loss", amount: 5 }, { kind: "magic", amount: 0 }, { kind: "blocked", amount: 0 }];
const base = { screen: "title", realm: 0, hall: 0, enc: 0, step: 0, gold: 0, flash: null };
const shapes = [{ screen: "title" }, { screen: "map" }, { screen: "map", firstDone: true }];
Q.realms.forEach((r, ri) => {
  for (const extra of [{}, { firstDone: true }, { locked: true }, { locked: false }]) shapes.push({ screen: "realm", realm: ri, ...extra });
  r.halls.forEach((h, hi) => {
    shapes.push({ screen: "hall", realm: ri, hall: hi });
    h.trials.forEach((t, ti) => FLASHES.forEach(f => shapes.push({ screen: "trials", realm: ri, hall: hi, step: ti, flash: f })));
  });
  if (r.halls.length) shapes.push({ screen: "decree", realm: ri, hall: r.halls.length - 1, gold: 10, record: true });
  r.encounters.forEach((e, ei) => {
    FLASHES.forEach(f => shapes.push({ screen: "quest", realm: ri, enc: ei, flash: f, choice: 0 }));
    shapes.push({ screen: "guide", realm: ri, enc: ei }, { screen: "compiler", realm: ri, enc: ei });
    e.points.forEach((p, pi) => FLASHES.forEach(f => shapes.push({ screen: "battle", realm: ri, enc: ei, step: pi, flash: f })));
    shapes.push({ screen: "victory", realm: ri, enc: ei, step: e.points.length, gold: 10, record: false });
  });
});
const universe = [null, undefined, {}, { type: "map" }, { type: "enter" }, { type: "hear" }, { type: "magic" }, { type: "next" },
  { type: "carry" }, { type: "fight" }, { type: "again" }, { type: "teleport" }, { type: "answer" }, { type: "answer", option: "0" },
  { type: "answer", option: 0.5 }, { type: "realm" }, { type: "realm", realm: "0" }, { type: "realm", realm: 1.5 }];
for (let i = -1; i <= 8; i++) universe.push({ type: "answer", option: i });
for (let i = -1; i <= Q.realms.length; i++) universe.push({ type: "realm", realm: i });
let checked = 0, bad = 0;
const compare = (P, st, label) => {
  const drawn = P.ctx.__actions().map(a => JSON.stringify(a)), m = P.ctx.__m, now = P.ctx.__lp();
  const accepted = new Set(universe.filter(a => {
    try { return !m.act(st, a, now).refused; } catch (e) { bad++; console.error(`act threw on ${label} ${JSON.stringify(a)}: ${e}`); return false; }
  }).map(a => JSON.stringify(a)));
  for (const d of drawn) if (!accepted.has(d)) { if (bad++ < 20) console.error(`DRAWN BUT REFUSED ${label} ${d}`); }
  for (const a of accepted) if (!drawn.includes(a)) { if (bad++ < 20) console.error(`ACCEPTED BUT NOT DRAWN ${label} ${a}`); }
  checked++;
};
for (const [sn, saved] of Object.entries(SAVES)) for (const sh of shapes) {
  const P = boot(saved), st = { ...base, ...sh };
  P.ctx.__set(st); P.ctx.__render();
  compare(P, st, `${variant} ${sn} ${JSON.stringify(sh)}`);
}
// A gate opened under one save, pressed under another.
for (const [from, a] of Object.entries(SAVES)) for (const [to, b] of Object.entries(SAVES)) for (let ri = 0; ri < Q.realms.length; ri++) {
  const P = boot(a), m = P.ctx.__m;
  const st = m.act(m.act({ ...base }, { type: "map" }, P.ctx.__lp()).state, { type: "realm", realm: ri }, P.ctx.__lp()).state;
  P.ctx.__set(st); P.ctx.__render();
  P.store = { ...b };
  compare(P, st, `${variant} gate ${ri} drawn under ${from}, pressed under ${to}`);
}
if (bad) { console.error(`FAIL: ${bad} mismatches over ${checked} states`); process.exit(1); }
console.log(`${variant}: ${checked} states, 0 mismatches`);
