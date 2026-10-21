// Quest.progress(realms, storageKey): saved progress per realm, { done, best }, under
// <storageKey>-progress in the player's browser.
var Quest = (typeof Quest === "object" && Quest) || {};
(function (Q) {
  "use strict";
  Q.progress = (realms, storageKey) => {
    const KEY = `${storageKey}-progress`, maxGold = Q.rules.maxGold;
    // Saves come from the player's browser, so treat them as untrusted: only known realms, `best`
    // as a whole number between 0 and the realm's maximum. Older saves stored `true`: done with 0 gold.
    function load() {
      let raw = {};
      try { raw = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch { return {}; }
      const out = {};
      for (const r of realms) {
        const v = raw[r.id];
        if (v === true) out[r.id] = { done: true, best: 0 };
        else if (v && typeof v === "object") {
          const b = Math.floor(Number(v.best));
          out[r.id] = { done: !!v.done, best: Number.isFinite(b) ? Math.max(0, Math.min(b, maxGold(r))) : 0 };
        }
      }
      return out;
    }
    function finish(id, gold) {
      const p = load(), prev = p[id] || { done: false, best: 0 };
      const record = gold > prev.best;
      p[id] = { done: true, best: Math.max(prev.best, gold) };
      try { localStorage.setItem(KEY, JSON.stringify(p)); } catch {}
      return record;
    }
    const open = Q.rules.open(realms);
    const treasury = () => Object.entries(load()).reduce((n, [id, v]) => n + (open.some(r => r.id === id) ? v.best : 0), 0);
    const courseDone = () => { const p = load(); return open.every(r => p[r.id] && p[r.id].done); };
    return { load, finish, treasury, courseDone };
  };
})(Quest);
