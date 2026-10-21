// Walk a realm's Tiled map through the game's state machine, as the explore front end will, with
// no canvas: enter the realm as its overworld portal does, then repeatedly find the object for the
// step the machine waits on, interact with it, and answer its dialog. Every other step's object
// must be refused at that moment. Questions are answered right, wrong-then-right and with magic in
// turn. Prints a JSON summary; exits non-zero with a reason on any failure.
//   node play_map.js <quest.json> <map.tmj> <realm id>
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const [, , questFile, mapFile, realmId] = process.argv;
const fail = msg => { console.error(`FAIL: ${msg}`); process.exit(1); };
const quest = JSON.parse(fs.readFileSync(questFile, "utf8"));
const map = JSON.parse(fs.readFileSync(mapFile, "utf8"));
const store = {};
const ctx = vm.createContext({ localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } },
                               JSON, String, Number, Object, Array, Math });
const coreDir = path.join(__dirname, "..", "core");
for (const f of fs.readdirSync(coreDir).filter(f => f.endsWith(".js")).sort())
  vm.runInContext(fs.readFileSync(path.join(coreDir, f), "utf8"), ctx);
const Q = ctx.Quest;
const machine = Q.machine(quest), progress = Q.progress(quest.realms, quest.pack.storage_key);

const ROLES = ["merchant", "guide", "compiler", "foe", "reward"];
const prop = (o, name) => ((o.properties || []).find(p => p.name === name) || {}).value;
const stepOf = o => (ROLES.includes(o.type) ? `${prop(o, "encounter")}:${o.type}` : o.type === "throne" ? `hall:${prop(o, "hall")}` : null);
const steps = map.layers.filter(l => l.type === "objectgroup").flatMap(l => l.objects).map(stepOf).filter(Boolean);

const ri = quest.realms.findIndex(r => r.id === realmId);
if (ri < 0) fail(`no realm ${realmId}`);
let state = machine.fresh(), turn = 0;
const log = { interactions: [], refused: 0, gold: 0, saves: [] };
const act = (a, mustWork = true) => {
  const out = machine.act(state, a, progress.load());
  if (out.refused) { if (mustWork) fail(`${out.refused} (${JSON.stringify(a)})`); return false; }
  state = out.state;
  for (const fx of out.effects) if (fx.type === "save") { progress.finish(fx.realm, fx.gold); log.saves.push(fx.realm); }
  return true;
};
// The overworld portal: the first realm is played first where the pack's unlock rule asks it.
const firstId = quest.realms[0].id;
if (ri !== 0 && quest.pack.unlock === "first_realm_first") progress.finish(firstId, 0);
act({ type: "map" }); act({ type: "realm", realm: ri }); act({ type: "enter" });

const answer = () => {               // right, wrong-then-right, magic, in turn
  const q = machine.question(state), right = q.correct, kind = turn++ % 3;
  if (kind === 2) return act({ type: "magic" });
  if (kind === 1 && q.options.length > 1) {
    act({ type: "answer", option: (right + 1) % q.options.length });
    if (machine.settled(state.flash)) return true;    // a quest path's other option can be a win too
    act({ type: "next" });
  }
  return act({ type: "answer", option: right });
};
for (let guard = 0; guard < 500; guard++) {
  const want = machine.expected(state);
  if (want === null) break;
  if (!steps.includes(want)) fail(`the map has no object for step ${want}`);
  for (const other of new Set(steps)) {
    if (other !== want && act({ type: "interact", step: other }, false)) fail(`${other} was accepted while the game waits on ${want}`);
    if (other !== want) log.refused++;
  }
  act({ type: "interact", step: want });
  log.interactions.push(want);
  // The step's dialog, until the machine waits on something else.
  for (let d = 0; d < 100 && machine.expected(state) === want; d++) {
    const s = state.screen;
    if (s === "hall") act({ type: "hear" });
    else if (s === "guide") act({ type: "carry" });
    else if (s === "compiler") act({ type: "fight" });
    else if (s === "victory") { act({ type: "map" }); break; }
    else if (state.flash) act({ type: "next" });
    else answer();
  }
}
log.gold = state.gold;
log.ended = state.screen;
const r = quest.realms[ri];
const needed = r.halls.map(h => `hall:${h.id}`).concat(r.encounters.flatMap(e => ROLES.map(x => `${e.id}:${x}`)));
const missed = needed.filter(s => !log.interactions.includes(s));
if (missed.length) fail(`never reached ${missed.join(", ")}`);
if (!log.saves.includes(realmId)) fail(`realm ${realmId} was never saved as finished`);
console.log(JSON.stringify(log));
