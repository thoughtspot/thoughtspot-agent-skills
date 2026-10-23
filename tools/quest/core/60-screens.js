// Quest.screens(env): the HTML for every screen of a quest, shared by the classic page and the
// explore page's dialogs, so both ask questions the same way. Draws only: buttons go to
// env.choose(list of { label, action }) and screen-reader announcements to env.announce(text).
//   env: { quest, art, progress (Quest.progress), machine (Quest.machine), state: () => state,
//          choose(list), announce(text) }
// draw(screen) returns that screen's HTML for the current state.
// (The body below is not indented: its template literals carry the page's exact whitespace.)
var Quest = (typeof Quest === "object" && Quest) || {};
(function (Q) {
"use strict";
Q.screens = env => {
const QUEST = env.quest, REALMS = QUEST.realms, ART = env.art, MAP_ROWS = ART.map.split("\n");
const { S, H } = Q.wording(QUEST.pack.strings), esc = Q.esc;
const { GOLD_WIN, GOLD_LOSS, maxGold } = Q.rules;
const OPEN = Q.rules.open(REALMS), COURSE_MAX = Q.rules.courseMax(REALMS);
const progress = env.progress, loadProgress = progress.load, treasury = progress.treasury, courseDone = progress.courseDone;
const machine = env.machine;
let state = env.state();
const realm = () => REALMS[state.realm];
const hall = () => realm().halls[state.hall];
const encounter = () => realm().encounters[state.enc];
const firstDone = () => machine.firstDone(state, loadProgress());

// The throne room for a hall: pillars with torches, the hall's banner, the throne, and
// petitioners. During petitions one petitioner stands before the throne.
function hallScene(title, petitioning) {
  const W = 50, pad = s => s.padEnd(W);
  const banner = title.toUpperCase();
  const inner = 33, lp = Math.max(0, Math.floor((inner - banner.length) / 2));
  const row = (left, mid, right) => left + mid.padEnd(W - left.length - right.length) + right;
  const crowd = petitioning
    ? ["      o   o                o       o   o",
       "     /|\\ /|\\     o        /|\\     /|\\ /|\\",
       "     / \\ / \\    /|\\       / \\     / \\ / \\",
       "                / \\  " + S("hall_steps_forward")]
    : ["      o   o    o      o      o    o   o",
       "     /|\\ /|\\  /|\\    /|\\    /|\\  /|\\ /|\\",
       "     / \\ / \\  / \\    / \\    / \\  / \\ / \\"];
  const lines = [
    row(" )\uE000(", "   .---------------------------------.", " )\uE001( "),
    row(" |#|", "   |" + (" ".repeat(lp) + banner).padEnd(inner) + "|", " |#| "),
    row(" |#|", "   '---------------------------------'", " |#| "),
    row(" |#|", "        ||        _/^\\_        ||", " |#| "),
    row(" |#|", "        ||       |  \uE002  |       ||", " |#| "),
    row(" |#|", "        ||      _|_____|_      ||", " |#| "),
    row(" |#|", "        ||     |_________|     ||", " |#| "),
    "_|#|_" + "_".repeat(W - 10) + "_|#|_",
    ...crowd.map(pad)
  ];
  return `<pre class="art scene" style="--cols:${W}" aria-hidden="true">${lines.map(l => esc(l)
    // Private-use markers, so no letter in a hall's name can turn into a torch or a crown.
    .replace("\uE000", '<span class="flame">*</span>').replace("\uE001", '<span class="flame b">*</span>')
    .replace("\uE002", '<span class="hot crown">W</span>')).join("\n")}</pre>`;  // one cell wide, unlike ♛
}

// A realm's scene: its art with the realm's name on a banner. Markers apply to the art only,
// never to the banner, so no letter in a name can become a lantern.
function realmScene(r) {
  const scene = ART[`scene_${r.id}`];
  if (!scene) return art("banner", "hot");
  const lines = scene.split("\n");
  const art_ = lines.filter(l => l !== "@BANNER").map(l => l.replace(/^!/, ""));
  const name = r.name.toUpperCase(), inner = name.length + 6;
  const W = Math.max(inner + 2, ...art_.map(l => l.length));
  const off = " ".repeat(Math.floor((W - inner - 2) / 2));
  const banner = [off + "." + "-".repeat(inner) + ".", off + "|   " + name + "   |", off + "'" + "-".repeat(inner) + "'"];
  const out = lines.flatMap(l => l === "@BANNER" ? banner.map(b => esc(b))
    : [l.startsWith("!") ? `<span class="shimmer">${esc(l.slice(1))}</span>`
       : esc(l).replace(/\$/g, '<span class="flame">*</span>').replace(/%/g, '<span class="flame b">*</span>')]);
  return `<pre class="art scene" style="--cols:${W}" aria-hidden="true">${out.join("\n")}</pre>`;
}

const MAP = (() => {
  const w = Math.max(...MAP_ROWS.map(r => r.length));
  const edge = "+" + "-".repeat(w + 2) + "+";
  return [edge, ...MAP_ROWS.map(r => "| " + r.padEnd(w) + " |"), edge].join("\n");
})();


const LEGEND = () => `<div class="legend" aria-label="${esc(S("legend_label"))}">
  <span>${H("legend_guide")}</span><span>${H("legend_scroll")}</span>
  <span>${H("legend_compiler")}</span><span>${H("legend_foe")}</span></div>`;
const RULE = () => `<div class="rule-card"><span class="hot">${H("rule_title")}</span>
  <p>${H("rule_text")}</p></div>`;
const GOLD_RULES = () => S("gold_rules", { win: GOLD_WIN, loss: GOLD_LOSS });

const bar = (n, max, on, off) => `<span class="bar">${on.repeat(n)}<span class="gone">${off.repeat(max - n)}</span></span>`;
const cols = t => Math.max(...String(t).split("\n").map(l => l.length));
const art = (k, cls = "") => `<pre class="art ${cls}" style="--cols:${cols(ART[k])}" aria-hidden="true">${esc(ART[k])}</pre>`;
const isOn = (hl, i) => hl === "all" || hl.includes(i);


// Buttons: each is a label and the machine action it sends.
function choices(list) {
  env.choose(list);
  return `<ul class="choices">${list.map((c, i) =>
    `<li><button type="button" id="choice-${i}" data-i="${i}"><span class="key">[${i + 1}]</span> ${esc(c.label)}</button></li>`
  ).join("")}</ul>`;
}

function code(lines, hl, cls, label) {
  return `<div class="sr-only">${esc(label)}:</div><pre class="scroll">${lines.map((l, i) =>
    `<span class="ln ${cls}${isOn(hl, i) ? " on" : ""}">${isOn(hl, i) ? `<span class="sr-only">${H("sr_highlighted")} </span>` : ""}${esc(l)}</span>`).join("")}</pre>`;
}

function cell(c) {
  const at = c.indexOf(S("soon_marker")), mark = S("soon_marker");  // styled wherever a cell says it
  const m = mark && at >= 0 ? [c, c.slice(0, at), mark, c.slice(at + mark.length)] : null;
  return m ? `${esc(m[1])}<span class="soon">${esc(m[2])}</span>${esc(m[3])}` : esc(c);
}
function table(columns, rows) {
  return `<div class="law-wrap"><table class="law"><thead><tr><th></th>${columns.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(row => `<tr><td>${esc(row.label)}</td>${row.cells.map((c, i) =>
      `<td data-col="${esc(columns[i] || "")}">${cell(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

// Every pane, in the pack's order; the first is the guide's (the AI's scroll).
function panes(e, p) {
  return e.panes.map((pane, i) => `<div class="pane"><span class="lbl">${esc(pane.label)}</span>${code(pane.lines, p.highlights[pane.id], i === 0 ? "agent" : "", pane.name)}${
    pane.caption ? `\n    <span class="cap">${esc(pane.caption)}</span>` : ""}</div>`).join("\n    ");
}

const MAGIC_LABEL = () => S("magic_label");
const settled = machine.settled;
const announce = env.announce;


function feedback(f, why, hint, correctText, court = false) {
  announce(f.kind === "win" ? S("said_win", { amount: f.amount, why }) : f.kind === "magic" ? S("said_magic", { answer: correctText, why })
           : f.kind === "blocked" ? S("said_blocked", { hint }) : S("said_miss", { hint }));
  if (f.kind === "win") return `<div class="feedback"><span class="tag">${H("won_tag", { amount: f.amount })}</span><p>${esc(why)}</p></div>`;
  if (f.kind === "magic") return `<div class="feedback magic"><span class="tag">${H("magic_tag")}</span>
    <p>${H("magic_answer", { answer: correctText })}</p><p>${esc(why)}</p></div>`;
  if (f.kind === "blocked") return `<div class="feedback magic"><span class="tag">${H("blocked_tag")}</span><p>${esc(hint)}</p></div>`;
  const took = f.amount ? H(court ? "fine_court" : "fine_foe", { amount: f.amount }) : H(court ? "empty_court" : "empty_foe");
  return `<div class="feedback miss"><span class="tag">${took}</span><p>${esc(hint)}</p></div>`;
}

const meta = r => S("realm_meta", { depth: r.depth, minutes: r.minutes });
const MAP_ACTION = { type: "map" }, MAGIC = { type: "magic" }, NEXT = { type: "next" };
const answers = options => options.map((o, i) => ({ label: o, action: { type: "answer", option: i } }));
const goldTag = () => `<span><span class="lbl">${H("gold_tag")}</span> <span class="hot">${state.gold}</span></span>`;

const SCREENS = {
  title() {
    return `<h1 class="sr-only">${esc(QUEST.pack.title)}</h1>${art("title", "hot")}
      <p>${H("title_intro")}</p>
      <p class="dim">${H("title_start")}</p>
      ${choices([{ label: S("title_open"), action: MAP_ACTION }])}
      <p class="foot">${H("title_keys")} <span class="cursor">&nbsp;</span><br>
        ${H("title_links")}</p>`;
  },
  map() {
    const done = loadProgress();
    const names = Object.fromEntries(REALMS.map(r => [r.id, r.name.replace(/^The /, "")]));
    const routes = QUEST.routes.map(rt => `<span><b>${esc(rt.who)}:</b> ${rt.path.map(id => esc(names[id] || id)).join(" → ")}</span>`).join("");
    const purse = courseDone()
      ? `<p class="hot">${H("course_complete", { score: treasury(), max: COURSE_MAX })}</p>`
      : `<p><span class="lbl">${H("treasury_label")}</span> <span class="hot">${treasury()}</span> <span class="dim">${H("treasury_of", { max: COURSE_MAX })}</span></p>`;
    return `<h2>${H("map_title")}</h2>
      <pre class="art" style="--cols:${cols(MAP)}" aria-hidden="true">${esc(MAP)}</pre>
      ${purse}
      <div class="routes"><span>${H("routes_intro")}</span>${routes}</div>
      ${choices(REALMS.map((r, i) => {
        const d = done[r.id];
        const mark = d && d.done ? S("mark_best", { best: d.best, max: maxGold(r) }) : r.sealed ? S("mark_sealed")
          : i === 0 ? S("mark_start") : !firstDone() ? S("mark_after_first") : "";
        return { label: S("map_entry", { name: r.name, meta: meta(r), mark }), action: { type: "realm", realm: i } };
      }))}`;
  },
  realm() {
    const r = realm();
    const head = `${r.halls.length ? art("crown") : realmScene(r)}<h2>${esc(r.name)}</h2><p class="realm-meta">${esc(meta(r))}</p><p>${esc(r.covers)}</p>`;
    if (r.sealed) return `${head}<p class="dim">${H("realm_sealed")}</p>
      ${choices([{ label: S("back_to_map"), action: MAP_ACTION }])}`;
    if (machine.locked(state, loadProgress())) return `${head}<p class="dim">${H("realm_locked", { first: REALMS[0].name })}</p>
      ${choices([{ label: S("travel_to", { first: REALMS[0].name }), action: { type: "realm", realm: 0 } }, { label: S("back_to_map"), action: MAP_ACTION }])}`;
    return `${head}<p class="dim">${H("realm_max", { max: maxGold(r) })}</p>
      ${choices([{ label: S(r.halls.length ? "enter_halls" : "take_quest"), action: { type: "enter" } }, { label: S("back_to_map"), action: MAP_ACTION }])}`;
  },

  // ---- A realm of halls: one idea per hall, then its questions ---------------------------------
  hall() {
    const r = realm(), h = hall();
    return `<div class="status"><span class="lbl">${H("hall_of", { n: state.hall + 1, total: r.halls.length })}</span>${goldTag()}</div>
      ${hallScene(h.title, false)}
      <h2>${esc(h.title)}</h2>
      ${h.teach.map(t => `<p>${esc(t)}</p>`).join("")}
      ${h.rows.length ? table(h.columns, h.rows) : ""}
      ${choices([{ label: S("hear_petitions", { n: h.trials.length }), action: { type: "hear" } }, { label: S("back_to_map"), action: MAP_ACTION }])}`;
  },
  trials() {
    const r = realm(), h = hall(), t = h.trials[state.step];
    const head = `<div class="status"><span class="lbl">${esc(h.title.toUpperCase())}</span>${goldTag()}
      <span><span class="lbl">${H("petition_label")}</span> ${state.step + 1}/${h.trials.length}</span></div>`;
    const intro = t.kind === "claim" ? H("intro_claim") : H("intro_choice");
    if (state.flash) {
      const f = state.flash, lastInHall = state.step + 1 >= h.trials.length, lastHall = state.hall + 1 >= r.halls.length;
      const next = !settled(f) ? S("judge_again") : !lastInHall ? S("next_petitioner") : lastHall ? S("hear_decree") : S("on_to_hall", { n: state.hall + 2 });
      return `${head}${hallScene(h.title, true)}<p class="hot">${esc(t.text)}</p>
        ${feedback(f, t.why, S("court_hint"), t.options[t.correct], true)}
        ${choices([{ label: next, action: NEXT }])}`;
    }
    return `${head}${hallScene(h.title, true)}<p>${intro}</p><p class="hot">${esc(t.text)}</p>
      ${choices([...answers(t.options), { label: MAGIC_LABEL(), action: MAGIC }])}`;
  },
  decree() {
    const r = realm();
    const record = state.record;   // saved, with the fanfare, by the action that finished the realm
    return `${art("crown", "hot")}<h2>${H("decree_title")}</h2>
      <p>${H("decree_carry", { gold: state.gold, max: maxGold(r), realm: r.name, record: record ? S("record_best") : "" })}</p>
      ${r.decree.map((d, i) => `<p>${i + 1}. ${esc(d)}</p>`).join("")}
      <p class="dim">${H("scroll_recap")}</p>
      ${r.scroll ? table(r.scroll.columns, r.scroll.rows) : ""}
      <p class="dim">${H("roads_open")}</p>
      ${choices([{ label: S("back_to_map"), action: MAP_ACTION }])}`;
  },

  // ---- Every other realm: one quest -----------------------------------------------------------
  quest() {
    const r = realm(), e = encounter(), p = e.path;
    const head = `<div class="status"><span class="lbl">${esc(r.name.toUpperCase())}</span>${goldTag()}</div>`;
    const body = `${realmScene(r)}<p>${H("quest_intro")}</p><p class="hot">"${esc(e.quest)}"</p>
      <p>${H("read_intent")}</p>`;
    if (state.flash) {
      const f = state.flash, chosen = state.choice ?? p.correct;
      const text = f.kind === "magic" ? p.outcomes[p.correct].why : p.outcomes[chosen].why;
      return `${head}${body}${feedback(f, text, text, p.options[p.correct])}
        ${choices([{ label: S(settled(f) ? "watch_guide" : "choose_again"), action: NEXT }])}`;
    }
    return `${head}${body}
      ${choices([...answers(p.options), { label: MAGIC_LABEL(), action: MAGIC }])}`;
  },
  guide() {
    const e = encounter();
    return `<div class="status"><span class="lbl">${H("path_label")}</span>${goldTag()}</div>${art("guide")}
      <p>${H("guide_text")}</p>
      ${code(e.panes[0].lines, [], "agent", e.panes[0].name)}
      ${choices([{ label: S("carry_scroll"), action: { type: "carry" } }])}`;
  },
  compiler() {
    const e = encounter();
    return `${art("compiler")}
      <p>${H("compiler_text")}</p>
      ${LEGEND()}${RULE()}
      <p class="dim">${H("foe_points", { n: e.points.length, gold_rules: GOLD_RULES() })}</p>
      ${choices([{ label: S("draw_weapon"), action: { type: "fight" } }])}`;
  },
  battle() {
    const e = encounter(), q = e.points[state.step];
    const head = `<div class="status">${goldTag()}
      <span><span class="lbl">${H("foe_label")}</span> ${bar(e.points.length - state.step, e.points.length, "█", "░")}</span></div>${LEGEND()}`;
    if (state.flash) {
      const f = state.flash, last = state.step + 1 >= e.points.length;
      return `${head}${panes(e, q)}
        ${feedback(f, q.why, q.hint, q.options[q.correct])}
        ${choices([{ label: S(!settled(f) ? "try_again" : last ? "foe_falls" : "next_point"), action: NEXT }])}`;
    }
    return `${head}${state.step === 0 ? art("foe") : ""}${panes(e, q)}
      <p>${esc(q.ask)}</p>
      ${choices([...answers(q.options), { label: MAGIC_LABEL(), action: MAGIC }])}`;
  },
  victory() {
    const r = realm(), e = encounter();
    const record = state.record;   // saved, with the fanfare, by the action that finished the realm
    const TAGS = QUEST.pack.rule_tags, group = p => p.rule && TAGS[p.ruleTag] ? TAGS[p.ruleTag].group : "";
    const item = p => `<li><span class="who">${esc(TAGS[p.ruleTag].label)}</span><span>${esc(p.rule)}</span></li>`;
    const rules = e.points.filter(p => group(p) === "rules");
    const yours = e.points.filter(p => group(p) === "yours");
    return `${realmScene(r)}<h2>${H("victory_title")}</h2>
      <p>${H("carry_home", { gold: state.gold, max: maxGold(r), record: record ? S("record_best") : "" })}</p>
      <p class="lbl">${H("rules_heading")}</p>
      <p class="dim">${H("rules_note")}</p>
      <ul class="rules">${rules.map(item).join("")}</ul>
      ${yours.length ? `<p class="lbl">${H("yours_heading")}</p><ul class="rules">${yours.map(item).join("")}</ul>` : ""}
      <p class="verdict">${H("verdict")}</p>
      <p>${esc(e.takeaway)}</p>
      ${choices([{ label: S("back_to_map"), action: MAP_ACTION }, { label: S("quest_again"), action: { type: "again" } }])}`;
  }
};

const MUSIC_FOR = { hall: "court", trials: "court", decree: "court", quest: "battle", guide: "battle",
                    compiler: "battle", battle: "battle", victory: "battle" };

return {
  SCREENS, MUSIC_FOR,
  draw(screen) { state = env.state(); return SCREENS[screen](); }
};
};
})(Quest);
