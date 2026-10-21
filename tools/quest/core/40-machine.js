// Quest.machine(quest): the game's state machine, with no drawing and no DOM.
//   act(state, action, progress) -> { state, effects, refused? }
// `progress` is Quest.progress(...).load(). `effects` are what the front end does next, in
// order: { type: "sound", name } and { type: "save", realm, gold }. An action the current screen
// doesn't offer is refused with a message and changes nothing, so a front end can't skip a step.
//
// Actions: map, realm {realm}, enter, hear, answer {option}, magic, next, carry, fight, again.
var Quest = (typeof Quest === "object" && Quest) || {};
(function (Q) {
  "use strict";
  Q.machine = quest => {
    const realms = quest.realms, R = Q.rules;
    const fresh = () => ({ screen: "title", realm: 0, hall: 0, enc: 0, step: 0, gold: 0, flash: null });
    const settled = f => !!f && (f.kind === "win" || f.kind === "magic");
    const firstDone = (s, progress) => !!(progress[realms[0].id] || {}).done || !!s.firstDone;
    // Whether a realm's gate is locked is decided once, when the gate opens (the "realm" action),
    // and kept in the state as `gate`: the screen drawn and the actions accepted then agree even if
    // the save changes meanwhile (another tab). It counts only for the realm it was decided for; any
    // other state (made or moved by hand) is judged from `progress`.
    const locked = (s, progress) => (s.gate && s.gate.realm === s.realm ? s.gate.locked
                                                                          : s.realm !== 0 && !firstDone(s, progress));
    // The question a screen asks: a hall's petition, a quest's path, or the foe's point.
    function question(s) {
      const r = realms[s.realm];
      if (s.screen === "trials") return r.halls[s.hall].trials[s.step];
      if (s.screen === "quest") return r.encounters[s.enc].path;
      if (s.screen === "battle") return r.encounters[s.enc].points[s.step];
      return null;
    }
    // What the current screen offers.
    function permitted(s, a, progress) {
      const r = realms[s.realm];
      switch (s.screen) {
        case "title": return a.type === "map";
        case "map": return a.type === "realm" && Number.isInteger(a.realm) && a.realm >= 0 && a.realm < realms.length;
        case "realm":
          if (r.sealed) return a.type === "map";
          if (locked(s, progress)) return a.type === "map" || (a.type === "realm" && a.realm === 0);
          return a.type === "enter" || a.type === "map";
        case "hall": return a.type === "hear" || a.type === "map";
        case "decree": return a.type === "map";
        case "guide": return a.type === "carry";
        case "compiler": return a.type === "fight";
        case "victory": return a.type === "map" || a.type === "again";
        case "trials": case "quest": case "battle":
          if (s.flash) return a.type === "next";
          return a.type === "magic" || (a.type === "answer" && Number.isInteger(a.option) && a.option >= 0
                                        && a.option < question(s).options.length);
        default: return false;
      }
    }
    function act(state, action, progress) {
      if (!action || !permitted(state, action, progress)) {
        return { state, effects: [], refused: `${action && action.type} is not offered on the ${state.screen} screen` };
      }
      const s = Object.assign({}, state), fx = [], sound = name => fx.push({ type: "sound", name });
      const r = realms[s.realm];
      // Finishing a realm saves its gold and plays the fanfare; the reward screen reads the record.
      const finish = screen => {
        s.screen = screen;
        s.record = s.gold > (progress[r.id] || { best: 0 }).best;  // what saving will report
        fx.push({ type: "save", realm: r.id, gold: s.gold });
        if (screen === "decree") s.firstDone = s.firstDone || s.realm === 0;
        sound("fanfare");
      };
      switch (action.type) {
        case "map": sound("blip"); Object.assign(s, { screen: "map", flash: null, gate: null }); break;
        case "realm": sound("blip");
          Object.assign(s, { screen: "realm", realm: action.realm, flash: null, gate: null });
          s.gate = { realm: s.realm, locked: locked(s, progress) };
          break;
        case "enter": sound("blip");
          Object.assign(s, r.halls.length ? { screen: "hall", hall: 0, step: 0, gold: 0, flash: null }
                                          : { screen: "quest", enc: 0, step: 0, gold: 0, flash: null });
          break;
        case "hear": sound("blip"); Object.assign(s, { screen: "trials", step: 0, flash: null }); break;
        case "carry": sound("blip"); s.screen = "compiler"; break;
        case "fight": sound("blip"); Object.assign(s, { screen: "battle", step: 0, flash: null }); break;
        case "again": sound("blip"); Object.assign(s, { screen: "quest", enc: 0, step: 0, gold: 0, flash: null }); break;
        case "magic": sound("magic"); s.flash = { kind: "magic", amount: 0 }; break;
        case "answer": {
          // Right: +gold, move on. Wrong: lose gold (never below 0), answer again. Blocked (a path
          // closed in this realm): nothing changes, choose again.
          const q = question(s);
          let kind;
          if (s.screen === "quest") { s.choice = action.option; kind = q.outcomes[action.option].kind; }
          else kind = action.option === q.correct ? "win" : "loss";
          if (kind === "win") { s.gold += R.GOLD_WIN; sound("coin"); s.flash = { kind, amount: R.GOLD_WIN }; }
          else if (kind === "loss") {
            const taken = Math.min(R.GOLD_LOSS, s.gold);
            s.gold -= taken; sound("steal"); s.flash = { kind, amount: taken };
          } else { sound("blip"); s.flash = { kind, amount: 0 }; }
          break;
        }
        case "next": {
          const ok = settled(s.flash);
          if (s.screen === "trials") {
            const lastInHall = s.step + 1 >= r.halls[s.hall].trials.length, lastHall = s.hall + 1 >= r.halls.length;
            if (ok) {
              if (!lastInHall) s.step++;
              else if (lastHall) finish("decree");
              else { s.hall++; s.step = 0; s.screen = "hall"; }
            }
          } else if (s.screen === "quest") {
            if (ok) s.screen = "guide";
          } else if (ok) {
            s.step++;
            if (s.step >= r.encounters[s.enc].points.length) finish("victory");
          }
          s.flash = null;
          break;
        }
      }
      return { state: s, effects: fx };
    }
    return { fresh, act, permitted, question, settled, firstDone, locked };
  };
})(Quest);
