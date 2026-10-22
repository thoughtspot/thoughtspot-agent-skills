// The explore front end: walk a pack's Tiled maps (Quest.engine, engine.js), and answer each step in a dialog drawn
// by Quest.screens, the same screens as the classic page. The rules of play are Quest.machine's:
// talking to someone sends `interact {step}`, which it refuses unless that step is next.
// Design: docs/superpowers/specs/2026-10-21-agentql-quest-pack-design.md (§4).
"use strict";
(async function () {
  const $ = id => document.getElementById(id);
  const log = t => { $("log").textContent += t + "\n"; };
  window.addEventListener("error", e => log(`ERROR ${e.message}`));
  window.addEventListener("unhandledrejection", e => log(`ERROR ${e.reason}`));

  const [quest, art] = await Promise.all([fetch("../quest.json").then(r => r.json()), fetch("art.json").then(r => r.json())]);
  const pack = quest.pack, realms = quest.realms;
  const { S } = Quest.wording(pack.strings);
  const progress = Quest.progress(realms, pack.storage_key), machine = Quest.machine(quest);
  const Sound = Quest.sound(pack.storage_key, S);
  const explorable = new Set(pack.explore_realms);
  const TILE = 16;
  const ROLES = ["merchant", "guide", "compiler", "foe", "reward"];
  const FRAMES = await fetch("tiles.json").then(r => r.json());

  // ---- the page's words ----------------------------------------------------------------------
  $("help").textContent = S("explore_help");
  $("classic").textContent = S("explore_classic");
  $("world").setAttribute("aria-label", S("explore_world"));
  $("close").textContent = S("explore_close");
  $("leave").textContent = S("explore_leave");

  const PAD = { left: S("explore_pad_left"), up: S("explore_pad_up"), down: S("explore_pad_down"),
                right: S("explore_pad_right"), talk: S("explore_pad_talk"), weapon: S("explore_pad_weapon") };
  for (const b of document.querySelectorAll("#pad button")) { b.textContent = PAD[b.dataset.key]; b.setAttribute("aria-label", PAD[b.dataset.key]); }
  Sound.label();
  const toast = t => { $("toast").textContent = t; };
  // ---- the fun, which never touches the quest: loot found, chests opened, barrels rolled, the
  // weapon in hand. Saved apart from progress, under <storage key>-explore. ----------------------
  const ITEMS = FRAMES.items, FUN_KEY = `${pack.storage_key}-explore`, MIMIC = "mimic";
  const fun = (() => {
    let f = {};
    try { f = JSON.parse(localStorage.getItem(FUN_KEY) || "{}") || {}; } catch { f = {}; }
    const items = Array.isArray(f.items) ? f.items.filter(i => ITEMS[i]) : [];
    if (!items.includes(FRAMES.weapon)) items.unshift(FRAMES.weapon);    // you start with this one
    return { items, weapon: ITEMS[f.weapon] && items.includes(f.weapon) ? f.weapon : FRAMES.weapon,
             done: f.done && typeof f.done === "object" ? f.done : {} };
  })();
  const saveFun = () => { try { localStorage.setItem(FUN_KEY, JSON.stringify(fun)); } catch {} };
  const itemName = id => S(`item_${id}`);
  const weapons = () => fun.items.filter(i => ITEMS[i].kind === "weapon");
  function gain(ids) {
    for (const id of ids) fun.items.push(id);
    saveFun(); hud();
  }
  // The gold bar: where you are, and your gold (this quest's, in a realm; every realm's, on the map).
  const open = realms.filter(r => !r.sealed), maxGold = Quest.rules.maxGold;
  function hud() {
    const inRealm = world && world.mapId !== "overworld", r = inRealm ? realms[state.realm] : null;
    $("hud-place").textContent = r ? r.name : S("explore_hud_map");
    $("hud-gold").textContent = r ? S("explore_hud_gold", { gold: state.gold, max: maxGold(r) })
                                  : S("explore_hud_gold", { gold: progress.treasury(), max: open.reduce((n, x) => n + maxGold(x), 0) });
    $("hud-kit").textContent = S("explore_hud_kit", { weapon: itemName(fun.weapon).toUpperCase(),
                                                      n: fun.items.filter(i => ITEMS[i].kind === "treasure").length });
  }
  // X: the next weapon you carry.
  function switchWeapon() {
    const w = weapons();
    if (w.length < 2) return;
    fun.weapon = w[(w.indexOf(fun.weapon) + 1) % w.length];
    saveFun(); hud();
    if (world) world.held.setFrame(ITEMS[fun.weapon].frame);
    toast(S("explore_weapon", { weapon: itemName(fun.weapon) }));
    Sound.play("blip");
  }
  const announce = t => { $("live").textContent = t; };

  // ---- the machine, and the dialog that draws its screens ------------------------------------
  let state = machine.fresh(), actions = [], dialogStep = null, world = null;
  state = machine.act(state, { type: "map" }, progress.load()).state;            // the overworld is the map
  const screens = Quest.screens({ quest, art, progress, machine, state: () => state, announce,
                                  choose: list => { actions = list.map(c => c.action); } });
  const dialog = $("dialog");
  function show() {
    $("dialog-title").textContent = state.screen !== "map" && realms[state.realm] ? realms[state.realm].name : pack.title;
    $("screen").innerHTML = screens.draw(state.screen);
    portrait();
    if (state.screen === "battle" && state.step === 0 && !state.flash) {      // what you face it with
      const line = document.createElement("p");
      line.className = "dim"; line.textContent = S("explore_face_foe", { weapon: itemName(fun.weapon) });
      $("screen").prepend(line);
    }
    Sound.music(screens.MUSIC_FOR[state.screen] || "map");
    $("screen").querySelector(".choices button")?.focus({ preventScroll: true });
  }
  // Who you're talking to, drawn from the map's own art beside the question.
  let sheet = null;                      // the atlas and its columns, once loaded
  function portrait() {
    const who = world && world.objects.find(o => (dialogStep === "portal" ? o.type === "portal" && realms[state.realm] && o.to === realms[state.realm].id : o.step === dialogStep));
    const c = $("portrait");
    c.hidden = !(who && sheet);
    if (c.hidden) return;
    const f = who.sprite.frame.name, g = c.getContext("2d");
    g.imageSmoothingEnabled = false;
    g.clearRect(0, 0, TILE, TILE);
    g.drawImage(sheet.atlas, (f % sheet.columns) * TILE, Math.floor(f / sheet.columns) * TILE, TILE, TILE, 0, 0, TILE, TILE);
  }
  function openDialog(step) {
    dialogStep = step;
    const inRealm = !!world && world.mapId !== "overworld";
    $("close").textContent = S(inRealm ? "explore_close_realm" : "explore_close");
    $("leave").hidden = !inRealm;
    if (world && /:reward$/.test(step)) world.openChest(step);    // the hoard's chest opens as you claim it
    if (world) world.freeze(true);
    if (!dialog.open) dialog.showModal();
    show();
  }
  function closeDialog() {
    dialogStep = null;
    if (dialog.open) dialog.close();
    if (world) { world.freeze(false); world.near = undefined; }   // say again what is close, once back
    $("world").focus({ preventScroll: true });
  }
  // Esc: not now. The close event comes a task later, so one from a dialog already reopened is stale.
  dialog.addEventListener("close", () => { if (!dialog.open && dialogStep !== null) closeDialog(); });
  $("close").addEventListener("click", closeDialog);
  $("leave").addEventListener("click", () => { closeDialog(); leaveRealm(); });
  // Out of a realm to the world map, beside its door; a quest left unfinished is not saved.
  function leaveRealm() {
    const left = world.mapId;
    state = Object.assign(machine.fresh(), { screen: "map", firstDone: state.firstDone });
    Sound.play("blip");
    goTo("overworld", left);
  }

  // Do an action from a dialog button: the machine decides; then close the dialog once the game
  // waits on another step, and follow it to another map when it leaves this one.
  function dispatch(action) {
    if (action.type === "realm" && !explorable.has(realms[action.realm].id)) return toClassic(realms[action.realm].id);
    const out = machine.act(state, action, progress.load());
    if (out.refused) return;
    state = out.state;
    for (const fx of out.effects) {
      if (fx.type === "sound") Sound.play(fx.name);
      else if (fx.type === "save") progress.finish(fx.realm, fx.gold);
    }
    if (state.screen === "map") { closeDialog(); if (!world || world.mapId !== "overworld") goTo("overworld", world && world.mapId); return; }
    if (dialogStep === "portal") {
      if (state.screen === "realm") return show();                  // still at the gate: locked or sealed
      closeDialog(); return goTo(realms[state.realm].id);
    }
    hud();
    if (state.screen === "decree") { if (world) world.refresh(); return show(); }   // a realm of halls ends with its decree: read it first
    if (machine.expected(state) !== dialogStep) { closeDialog(); if (world) world.refresh(); return; }
    show();
  }
  $("screen").addEventListener("click", e => {
    const b = e.target.closest(".choices button");
    if (b && actions[+b.dataset.i]) dispatch(actions[+b.dataset.i]);
  });
  const toClassic = id => {
    if (SMOKE) return log(`ERROR the scripted play left for the classic page (${id})`);   // keep the log
    location.href = `../#realm=${encodeURIComponent(id)}&from=explore`;
  };

  // Talk to an object the player stands next to.
  function talk(obj) {
    if (!obj) return toast(world && world.shutGate() ? S("explore_gate_locked") : S("explore_nobody"));
    toast("");
    if (obj.type === "portal") {
      const i = realms.findIndex(r => r.id === obj.to);
      if (!explorable.has(obj.to)) return toClassic(obj.to);
      // A portal is the map's entry for its realm: back to the map first (from a gate left open with
      // Esc), so the gate is judged now, from the save as it is.
      let at = state;
      if (at.screen !== "map") at = machine.act(at, { type: "map" }, progress.load()).state;
      const out = machine.act(at, { type: "realm", realm: i }, progress.load());
      if (out.refused) { log(`ERROR portal ${obj.to}: ${out.refused}`); return toast(S("explore_not_yet")); }
      state = out.state;
      Sound.play("blip");
      return openDialog("portal");
    }
    if (obj.type === "chest" || obj.type === "barrel" || obj.type === "hoard" || obj.type === "npc") return world.play(obj);
    if (obj.type === "exit") return leaveRealm();
    if (state.screen === "decree" && obj.type === "throne") return openDialog(obj.step);   // closed with Esc: a throne reads it again
    const out = machine.act(state, { type: "interact", step: obj.step }, progress.load());
    if (out.refused) return toast(S("explore_not_yet"));
    openDialog(obj.step);
  }

  // ---- input: keys and the touch pad ---------------------------------------------------------
  const pad = { up: false, down: false, left: false, right: false };
  document.addEventListener("keydown", e => {
    Sound.unlock();
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = (e.key || "").toLowerCase();
    if (k === "s" && !e.repeat) { e.preventDefault(); return Sound.toggle("sfx"); }
    if (k === "m" && !e.repeat) { e.preventDefault(); return Sound.toggle("music"); }
    if (k === "x" && !e.repeat && !dialog.open) { e.preventDefault(); return switchWeapon(); }
    if (dialog.open) {
      const n = parseInt(e.key, 10);
      if (!e.repeat && n >= 1 && n <= actions.length) { e.preventDefault(); dispatch(actions[n - 1]); }
      if (e.repeat && (k === "enter" || k === " ")) e.preventDefault();   // holding a key must not skip explanations
      return;
    }
    // Enter and Space talk only on the map: on a link or a button they keep their own meaning.
    const onMap = e.target === $("world") || e.target === document.body || !!(e.target.closest && e.target.closest("#world"));
    if ((k === "enter" || k === " ") && !e.repeat && world && onMap) { e.preventDefault(); talk(world.nearby()); }
  });
  // Clicking the map, or anywhere that isn't a control, gives the map the keys again (the engine
  // listens for arrows only on the map). On click, after the browser has put focus where it puts it.
  document.addEventListener("click", e => {
    if (dialog.open || (e.target.closest && e.target.closest("a, button, input, select, textarea, dialog, label"))) return;
    if (window.getSelection && String(window.getSelection())) return;      // selecting text: leave focus be
    $("world").focus({ preventScroll: true });
  });
  document.addEventListener("click", e => {
    Sound.unlock();
    if (e.target.closest("#sound-sfx")) Sound.toggle("sfx");
    else if (e.target.closest("#sound-music")) Sound.toggle("music");
  });
  for (const b of document.querySelectorAll("#pad button")) {
    const k = b.dataset.key;
    // Talk and Weapon act on pointerdown, so a second finger works while another holds a direction
    // (a click needs the first finger off the screen); Enter or Space on the button still clicks.
    const act = k === "talk" ? () => { if (world && !dialog.open) talk(world.nearby()); }
              : k === "weapon" ? () => { if (!dialog.open) switchWeapon(); } : null;
    if (act) {
      b.addEventListener("pointerdown", e => { e.preventDefault(); Sound.unlock(); act(); });
      b.addEventListener("click", e => { if (e.detail === 0) { Sound.unlock(); act(); } });   // the keyboard
      continue;
    }
    b.addEventListener("pointerdown", e => { e.preventDefault(); Sound.unlock(); pad[k] = true; });
    for (const ev of ["pointerup", "pointerleave", "pointercancel"]) b.addEventListener(ev, () => { pad[k] = false; });
  }
  document.addEventListener("visibilitychange", () => (document.hidden ? Sound.pause() : Sound.resume()));
  // Back from classic mode: saves may have changed there. A gate left open (the page may come back
  // from the back/forward cache) is judged again next time, so close it.
  window.addEventListener("pageshow", () => {
    if (dialogStep === "portal") { closeDialog(); state = machine.act(state, { type: "map" }, progress.load()).state; }
    if (world) { world.refresh(); world.near = undefined; }   // and say again what is close, from the new save
    hud();                                  // gold won in the classic page shows at once
  });

  // ---- the world: one scene per map (engine.js) -----------------------------------------------
  const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // The steps a gate waits on are done once the game has moved past them.
  const done = step => {
    const r = realms.find(x => x.encounters.some(e => step.startsWith(e.id + ":")) || x.halls.some(h => step === `hall:${h.id}`));
    if (!r) return false;
    const order = r.halls.map(h => `hall:${h.id}`).concat(r.encounters.flatMap(e => ROLES.map(x => `${e.id}:${x}`)));
    const now = machine.expected(state);
    return (progress.load()[r.id] || {}).done || (now !== null && order.indexOf(now) > order.indexOf(step));
  };

  class World {
    constructor(api, mapId, doc, from) { Object.assign(this, api); this.mapId = mapId; this.doc = doc; this.from = from; }
    create() {
      const doc = this.doc, map = { height: doc.height };
      const layer = name => doc.layers.find(l => l.type === "tilelayer" && l.name === name);
      this.addLayer(layer("floor"));
      const walls = this.addLayer(layer("walls"));
      this.walls = walls;
      walls.setCollisionByExclusion();
      // A wall painted with the wall tile shows its brick face where floor is below it, and its dark
      // top elsewhere; any other tile on the walls layer (a crate, a barrel) is drawn as it is.
      const plain = t => !!t && (t.index - 1 === FRAMES.wall || t.index - 1 === FRAMES.wall_top);
      walls.forEachTile(t => {
        if (plain(t)) t.index = 1 + (t.y + 1 < map.height && !plain(walls.getTileAt(t.x, t.y + 1)) ? FRAMES.wall : FRAMES.wall_top);
      });
      this.decor = layer("decor") ? this.addLayer(layer("decor")) : null;   // torches, rails, rubble: drawn, never blocking
      this.objects = [];
      this.gates = [];
      for (const o of doc.layers.find(l => l.type === "objectgroup" && l.name === "objects").objects) {
        const prop = n => ((o.properties || []).find(p => p.name === n) || {}).value;
        const x = o.x + o.width / 2, y = o.y + o.height / 2;
        const obj = { type: o.type, x, y, to: prop("to"), key: `${this.mapId}:${o.id}`, loot: prop("loot"), roll: prop("roll"),
                      look: prop("look"), says: prop("says"), about: prop("about"), said: 0,
                      step: ROLES.includes(o.type) ? `${prop("encounter")}:${o.type}` : o.type === "throne" ? `hall:${prop("hall")}` : null };
        if (o.type === "spawn") { this.spawn = { x, y }; continue; }
        if (o.type === "gate") {
          const g = this.addSprite(x, y, FRAMES.gate, true);
          g.requires = String(prop("requires") || "").split(",").map(s => s.trim()).filter(Boolean);
          this.gates.push(g); continue;
        }
        const opened = !!fun.done[obj.key];
        const frame = o.type === "portal" ? FRAMES.portals[obj.to] ?? FRAMES.portal
          : o.type === "chest" && opened ? (obj.loot === MIMIC ? FRAMES.mimic : FRAMES.chest_open)
          : o.type === "hoard" && opened ? FRAMES.hoard_empty
          : o.type === "npc" || (o.type === "throne" && obj.look) ? FRAMES.npcs[obj.look] : FRAMES[o.type] ?? FRAMES.portal;
        obj.sprite = this.addSprite(x, y, frame, true);
        if (o.type === "barrel" && opened) this.place(obj, ...this.rolledTo(obj));
        if (o.type === "barrel") obj.sprite.setDepth(2);
        // The living breathe: a pixel up and down, out of step with each other.
        if (!reduced && (["merchant", "guide", "foe", "npc"].includes(o.type) || (o.type === "throne" && obj.look)))
          this.time.addEvent({ delay: 650 + 90 * this.objects.length, loop: true,       // a pixel up, a pixel down
                               callback: () => obj.sprite.setOffsetY(obj.sprite.oy ? 0 : -1) });   // the picture, not the body
        this.objects.push(obj);
      }
      // A hoard lies hidden under its barrel until the barrel has rolled off it.
      for (const h of this.objects.filter(o => o.type === "hoard")) {
        const b = this.objects.find(o => o.type === "barrel" && o.x === h.x && o.y === h.y);
        this.hide(h, !!b && !fun.done[b.key]);
      }
      // The player's body moves; what you see follows it, facing the way it walks, with a step bob.
      // Back from a realm, beside its door (the first open floor next to it); else at the spawn.
      let start = this.spawn;
      const door = this.from && this.objects.find(o => o.type === "portal" && o.to === this.from);
      if (door) {
        const open = ([dx, dy]) => { const tx = Math.floor(door.x / TILE) + dx, ty = Math.floor(door.y / TILE) + dy, t = walls.getTileAt(tx, ty);
          return tx >= 0 && ty >= 0 && tx < doc.width && ty < doc.height          // on the map: a door can be on its edge
            && !(t && t.collides) && !this.objects.some(o => Math.floor(o.x / TILE) === tx && Math.floor(o.y / TILE) === ty); };
        const side = [[0, 1], [0, -1], [-1, 0], [1, 0]].find(open);
        if (side) start = { x: door.x + side[0] * TILE, y: door.y + side[1] * TILE };
      }
      this.player = this.addPlayer(start.x, start.y);                   // a 12x12 body
      this.look = this.addSprite(start.x, start.y, FRAMES.player, false).setDepth(10);
      this.facing = [0, 1];
      this.held = this.addSprite(start.x, start.y, ITEMS[fun.weapon].frame, false).setDepth(11).setScale(0.75);
      this.collide(walls);                                                // walls, and every enabled solid sprite
      this.cursors = this.input.keyboard.cursors;
      this.cameras.main.setBounds(0, 0, doc.width * TILE, doc.height * TILE);
      this.cameras.main.startFollow(this.player, true, reduced ? 1 : 0.2);
      if (!reduced) this.cameras.main.fadeIn(220);
      this.refresh();
      world = this;
      hud();
      log(`MAP ${this.mapId}`);
    }
    refresh() {
      for (const g of this.gates) {
        const open = g.opened = g.opened || g.requires.every(done);   // once open, open for this visit
        g.setVisible(!open); g.body.enable = !open;
      }
      for (const o of this.objects)       // the quest's chest is open only while it is being claimed
        if (o.type === "reward") o.sprite.setFrame(dialogStep === o.step ? FRAMES.reward_open : FRAMES.reward);
    }
    openChest(step) {
      const o = this.objects.find(x => x.type === "reward" && x.step === step);
      if (o) o.sprite.setFrame(FRAMES.reward_open);
    }
    freeze(on) {
      this.input.keyboard.enabled = !on;
      if (!on) this.input.keyboard.resetKeys();
      this.player.setVelocity(0, 0);
      this.look.setPosition(Math.round(this.player.x), Math.round(this.player.y));
      this.hold();
      this.frozen = on;
    }
    // Whoever the player stands next to, up, down, left or right (not across a corner); the one the
    // game waits on first, so the right one answers when two are close.
    nearby() {
      const p = this.player, want = machine.expected(state);
      const close = this.objects.filter(o => !o.hidden).filter(o => {
        const dx = Math.abs(o.x - p.x), dy = Math.abs(o.y - p.y);
        // Beside it: within reach on one axis, overlapping it on the other (half the 12px body
        // plus half the 16px tile, so a player pressed against it anywhere along its side counts).
        return (dx <= TILE * 1.25 && dy < 14) || (dy <= TILE * 1.25 && dx < 14);
      }).sort((a, b) => Math.hypot(a.x - p.x, a.y - p.y) - Math.hypot(b.x - p.x, b.y - p.y)
                        || this.ahead(b) - this.ahead(a));         // a tie goes to the one you face
      // Something that isn't a step (the exit, a door, a chest, someone to talk to) answers when you
      // face it squarely, so you can always leave; otherwise the step the game waits on answers first.
      const faced = close.find(o => !o.step && this.ahead(o) > 0.8);     // squarely: not across a diagonal
      const next = close.find(o => o.step && o.step === want);
      if (faced && next && this.ahead(next) > this.ahead(faced)) return next;   // but not over the step you face more squarely
      return faced || next || close[0] || null;
    }
    // A shut gate the player stands beside, if any (gates aren't objects: nothing to talk to).
    shutGate() {
      const p = this.player;
      return this.gates.find(g => g.body.enable && ((Math.abs(g.x - p.x) <= TILE * 1.25 && Math.abs(g.y - p.y) < 14)
                                                    || (Math.abs(g.y - p.y) <= TILE * 1.25 && Math.abs(g.x - p.x) < 14))) || null;
    }
    // How squarely the player faces something: 1 straight ahead, -1 behind.
    ahead(o) {
      const dx = o.x - this.player.x, dy = o.y - this.player.y, d = Math.hypot(dx, dy) || 1;
      const f = Math.hypot(this.facing[0], this.facing[1]) || 1;      // walking diagonally faces between two
      return (dx * this.facing[0] + dy * this.facing[1]) / d / f;
    }
    update() {
      if (this.frozen) return;
      const near = this.nearby() || this.shutGate();
      if (near !== this.near) { this.near = near; describe(near); }
      const c = this.cursors, v = 90;
      const dx = (c.left.isDown || pad.left ? -1 : 0) + (c.right.isDown || pad.right ? 1 : 0);
      const dy = (c.up.isDown || pad.up ? -1 : 0) + (c.down.isDown || pad.down ? 1 : 0);
      this.player.setVelocity(dx * v, dy * v);
      if (dx) { this.look.setFlipX(dx < 0); this.held.setFlipX(dx < 0); }
      if (dx || dy) this.facing = [Math.sign(dx), Math.sign(dy)];
    }
    // After the physics step, so what you see is where the body is; bob only when it really moved.
    follow() {
      if (!this.player) return;
      const b = this.player.body, moving = !this.frozen && (Math.abs(b.deltaX()) > 0.01 || Math.abs(b.deltaY()) > 0.01);
      const step = !reduced && moving && Math.floor(this.time.now / 140) % 2;
      this.look.setPosition(Math.round(this.player.x), Math.round(this.player.y) - (step ? 1 : 0));
      this.hold();
    }
    // The weapon sits in the hand the player faces with.
    hold() {
      this.held.setPosition(this.look.x + (this.look.flipX ? -6 : 6), this.look.y + 3);
    }
    hide(obj, hidden) {
      obj.hidden = hidden;
      obj.sprite.setVisible(!hidden);
      obj.sprite.body.enable = !hidden;
    }
    rolledTo(b) {
      const [dx, dy] = { left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] }[b.roll] || [0, 0];
      return [b.x + dx * TILE, b.y + dy * TILE];
    }
    place(obj, x, y) {
      obj.x = x; obj.y = y;
      obj.sprite.setPosition(x, y);
      obj.sprite.refreshBody();
    }
    // A chest, a barrel or a hoard: none of them is a step, so the machine never hears of it.
    play(obj) {
      if (obj.hidden) return toast(S("explore_nobody"));
      if (obj.type === "npc") {              // the next of its lines, round and round
        const lines = obj.about ? [(r => S("explore_npc_about", { realm: r.name, covers: r.covers }))(realms.find(r => r.id === obj.about))]
                                : String(obj.says).split(",").map(k => S(k.trim()));
        const line = lines[obj.said++ % lines.length];
        Sound.play("blip");
        return toast(line);
      }
      const first = !fun.done[obj.key];
      if (obj.type === "chest") {
        if (!first) return toast(S(obj.loot === MIMIC ? "explore_mimic" : "explore_chest_empty"));
        fun.done[obj.key] = true;
        if (obj.loot === MIMIC) { obj.sprite.setFrame(FRAMES.mimic); Sound.play("steal"); saveFun(); return toast(S("explore_mimic")); }
        obj.sprite.setFrame(FRAMES.chest_open); Sound.play("coin");
        gain([obj.loot]);
        return toast(S("explore_found", { item: itemName(obj.loot) }));
      }
      if (obj.type === "barrel") {
        if (!first) return toast(S("explore_nobody"));
        const [x, y] = this.rolledTo(obj), from = { x: obj.x, y: obj.y };
        const p = this.player;              // never onto the player: step out of its way first
        if (Math.abs(p.x - x) < TILE / 2 + p.w / 2 && Math.abs(p.y - y) < TILE / 2 + p.h / 2) return toast(S("explore_barrel_blocked"));
        fun.done[obj.key] = true; saveFun();
        this.place(obj, x, y);
        // The body is where it lands at once (checked clear of the player above); the picture rolls there.
        if (!reduced) { obj.sprite.setOffsetX(from.x - x).setOffsetY(from.y - y); this.tweens.add({ targets: obj.sprite, ox: 0, oy: 0, angle: 360, duration: 320 }); }
        const hoard = this.objects.find(o => o.type === "hoard" && o.x === from.x && o.y === from.y);
        if (hoard) this.hide(hoard, false);
        Sound.play("blip");
        return toast(S("explore_barrel"));
      }
      if (!first) return toast(S("explore_hoard_empty"));                // the hoard
      fun.done[obj.key] = true;
      const loot = String(obj.loot || "").split(",").map(s => s.trim()).filter(id => ITEMS[id]);
      obj.sprite.setFrame(FRAMES.hoard_empty); Sound.play("fanfare");
      gain(loot);
      return toast(S("explore_hoard", { items: loot.map(itemName).join(", ") }));
    }
  }
  // Standing by a portal says where it goes, as the classic map's entry does (best gold, sealed,
  // locked until the first realm); by a shut gate, that it is locked and why; by the step the game
  // waits on, how to talk to it. The live region reads it too.
  let portalText = "";
  function describe(obj) {
    const say = t => { toast(t); portalText = t; };   // #toast is a status region: read once, not twice
    if (obj && obj.requires) return say(S("explore_gate_locked"));
    if (obj && obj.step && obj.step === machine.expected(state))
      return say(obj.type === "throne" && obj.look ? S("explore_near_petitioner") : S("explore_near_step"));
    if (!obj || obj.type !== "portal") {            // walked away: the words go with it
      if (portalText && $("toast").textContent === portalText) toast("");
      portalText = "";
      return;
    }
    const i = realms.findIndex(r => r.id === obj.to), r = realms[i], d = progress.load()[r.id];
    const mark = d && d.done ? S("mark_best", { best: d.best, max: Quest.rules.maxGold(r) }) : r.sealed ? S("mark_sealed")
      : i === 0 ? S("mark_start") : !machine.firstDone(state, progress.load()) ? S("mark_after_first") : "";
    const t = S(r.sealed ? "explore_near_sealed" : "explore_near_portal", { name: r.name, mark: mark.trim() ? ` ${mark.trim()}` : "" });
    say(t);
  }
  // `from`: the realm just left, so the overworld puts the player beside that realm's door.
  // The view: as much of the map as fits at 1.25 screen pixels a game pixel or more (the whole map
  // on a laptop), and as many rows as fit in 70% of the window at that size; the camera follows
  // the player over the rest. Never fewer than 20x8 tiles, the size the realms are drawn for (so a
  // narrow screen goes below 1.25, and a map smaller than that sits in a 20x8 view, as it always did).
  const MIN_SCALE = 1.25;
  function fitView(doc) {
    const box = $("world").clientWidth || 960;
    const cols = Math.max(20, Math.min(doc.width, Math.floor(box / (MIN_SCALE * TILE))));
    const scale = box / (cols * TILE);
    const rows = Math.max(8, Math.min(doc.height, Math.floor(window.innerHeight * 0.7 / (scale * TILE))));
    $("world").style.aspectRatio = `${cols} / ${rows}`;
    game.resize(cols * TILE, rows * TILE);
  }
  window.addEventListener("resize", () => { if (world) fitView(world.doc); });
  function goTo(mapId, from = null) {
    world = null;
    fitView(MAPS[mapId]);
    game.start(api => {
      const w = new World(api, mapId, MAPS[mapId], from);
      w.create();
      return { update: () => w.update(), postupdate: () => w.follow() };
    });
    Sound.music(mapId === "overworld" ? "map" : "battle");
  }

  // The scripted play (tests/smoke_explore.py) writes saves, so it runs only on a local server.
  const LOCAL = ["127.0.0.1", "localhost"].includes(location.hostname);
  const SMOKE = location.hash.startsWith("#smoke=") && LOCAL;
  // #look=<map>, locally: open that map straight away, for screenshots (tests/shoot_maps.py).
  const LOOK = LOCAL && /^#look=([a-z0-9_]+)$/.exec(location.hash);
  // A 2D canvas; if the page can't start one, offer the classic version.
  let game, MAPS;
  try {
    const image = src => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => no(new Error(`couldn't load ${src}`)); i.src = src; });
    const ids = ["overworld", ...explorable];
    const [atlas, ...docs] = await Promise.all([image("tiles/tiles.png"), ...ids.map(id => fetch(`maps/${id}.tmj`).then(r => r.json()))]);
    MAPS = Object.fromEntries(ids.map((id, i) => [id, docs[i]]));
    sheet = { atlas, columns: MAPS.overworld.tilesets[0].columns };
    game = Quest.engine.create({
      parent: $("world"), width: 320, height: 128, background: "#16131f", atlas, columns: MAPS.overworld.tilesets[0].columns,
      keyTarget: $("world"),
      timeouts: SMOKE || !!LOOK        // a headless run uses virtual time, which never fires animation frames
    });
    game.onerror = e => log(`ERROR ${e && e.message}`);
  } catch (e) {
    $("nogl").textContent = S("explore_no_canvas");
    $("nogl").style.display = "block";
    for (const id of ["help", "world", "pad"]) $(id).hidden = true;
    document.querySelector(".sound").hidden = true;
    log(`NOGL ${e.message}`);
    return;
  }
  const looking = LOOK && (LOOK[1] === "overworld" || explorable.has(LOOK[1])) ? LOOK[1] : null;   // a map that exists
  if (looking && looking !== "overworld") state = Object.assign(state, { realm: realms.findIndex(r => r.id === looking) });
  // Back from the classic page (explore/#from=<realm>): on the map, beside that realm's door.
  const back = /^#from=([a-z0-9_]+)$/.exec(location.hash);
  goTo(looking || "overworld", !looking && back && realms.some(r => r.id === back[1]) ? back[1] : null);
  $("world").focus({ preventScroll: true });

  // For tests: the state, the world, and a scripted play of one realm (see tests/smoke_explore.py).
  if (LOCAL) window.Quest.explore = {
    state: () => state, world: () => world, talk, dispatch, actions: () => actions, dialogOpen: () => dialog.open,
    async smoke(realmId) {
      const wait = (ms = 50) => new Promise(r => setTimeout(r, ms));
      const until = async test => { for (let i = 0; i < 200 && !test(); i++) await wait(); if (!test()) throw new Error(`timed out on map ${world ? world.mapId : "(none)"} at frame ${game.loop.frame}`); };
      await until(() => world && world.mapId === "overworld");
      {                                      // the view fits the map, and is drawn to its edges
        const doc = world.doc, box = $("world").clientWidth, cols = game.canvas.width / TILE, rows = game.canvas.height / TILE;
        const want = Math.max(20, Math.min(doc.width, Math.floor(box / (1.25 * TILE))));
        if (cols !== want || rows < 8 || rows > doc.height) throw new Error(`the view is ${cols}x${rows} tiles; ${want} columns fit a ${box}px box`);
        if (Math.abs(box / $("world").clientHeight - cols / rows) > 0.02) throw new Error("the map's box isn't the view's shape");
        if (game.loop.frame === 0) await wait(100);
        const px = game.canvas.getContext("2d").getImageData(game.canvas.width - 4, game.canvas.height - 4, 1, 1).data;
        if (px[0] === 0x16 && px[1] === 0x13 && px[2] === 0x1f) throw new Error("the view isn't drawn to its corner");
        log(`VIEW ${cols}x${rows} in ${box}px`);
      }
      // Enter on a link keeps its meaning: the map must not take it.
      $("classic").focus();
      const enter = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
      $("classic").dispatchEvent(enter);
      if (enter.defaultPrevented) throw new Error("Enter on the classic link was taken by the map");
      // Clicking something that isn't a control gives the map the keys; the arrows then walk.
      $("world").blur();
      $("help").dispatchEvent(new MouseEvent("click", { bubbles: true }));
      if (document.activeElement !== $("world")) throw new Error("a click off the controls left the map without focus");
      const key = (type, k, code, more = {}) => {
        const ev = new KeyboardEvent(type, Object.assign({ key: k, code: k, bubbles: true, cancelable: true }, more));
        Object.defineProperty(ev, "keyCode", { get: () => code }); Object.defineProperty(ev, "which", { get: () => code });
        (document.activeElement || document.body).dispatchEvent(ev);
        return ev;
      };
      // Walk, with the arrow keys and the engine's own collision, to a floor tile beside something:
      // a tile path found over walls and solid bodies (as maps.py's walk), then each tile's centre
      // reached by holding the arrow towards it. Throws if the engine won't let the player there.
      const ARROWS = { left: ["ArrowLeft", 37], right: ["ArrowRight", 39], up: ["ArrowUp", 38], down: ["ArrowDown", 40] };
      const blockedTile = (tx, ty) => {
        const t = world.walls.getTileAt(tx, ty);
        return !!(t && t.collides) || world.gates.concat(world.objects.map(o => o.sprite))
          .some(sp => sp.body && sp.body.enable && Math.floor(sp.x / TILE) === tx && Math.floor(sp.y / TILE) === ty);
      };
      const walk = async (obj, avoid = []) => {
        const p = world.player, goal = new Set([[0, 1], [0, -1], [1, 0], [-1, 0]]
          .map(([dx, dy]) => [Math.floor(obj.x / TILE) + dx, Math.floor(obj.y / TILE) + dy])
          .filter(([tx, ty]) => !blockedTile(tx, ty) && !avoid.some(a => a[0] === tx && a[1] === ty)).map(t => t.join()));
        const start = [Math.floor(p.x / TILE), Math.floor(p.y / TILE)], from = { [start.join()]: null }, todo = [start];
        let end = null;
        while (todo.length && !end) {
          const [tx, ty] = todo.shift();
          if (goal.has([tx, ty].join())) { end = [tx, ty]; break; }
          for (const [dx, dy] of [[0, 1], [0, -1], [1, 0], [-1, 0]]) {
            const n = [tx + dx, ty + dy];
            if (n[0] < 0 || n[1] < 0 || n[0] >= world.doc.width || n[1] >= world.doc.height) continue;   // the map, not beyond it
            if (n.join() in from || blockedTile(...n)) continue;
            from[n.join()] = [tx, ty]; todo.push(n);
          }
        }
        if (!end) throw new Error(`no path to ${obj.step || obj.type} at (${Math.floor(obj.x / TILE)}, ${Math.floor(obj.y / TILE)}) from (${start})`);
        const path = [];
        for (let t = end; t; t = from[t.join()]) path.unshift(t);
        for (const [tx, ty] of path) {
          for (const axis of ["x", "y"]) {
            const want = (axis === "x" ? tx : ty) * TILE + TILE / 2;
            for (let n = 0; Math.abs(p[axis] - want) > 0.75; n++) {
              if (n > 120) throw new Error(`stuck walking to ${obj.step || obj.type} at (${p.x.toFixed(1)}, ${p.y.toFixed(1)})`);
              const [k, code] = ARROWS[axis === "x" ? (p[axis] < want ? "right" : "left") : (p[axis] < want ? "down" : "up")];
              key("keydown", k, code); await wait(16); key("keyup", k, code);
            }
          }
        }
        const fx = obj.x - p.x, fy = obj.y - p.y;
        world.facing = Math.abs(fx) >= Math.abs(fy) ? [Math.sign(fx), 0] : [0, Math.sign(fy)];   // face it, as a player would
        await wait(30);
      };
      // The arrows walk at the page's speed, don't scroll the page, and let go when the map loses focus.
      {
        const x0 = world.player.x;
        const ev = key("keydown", "ArrowRight", 39); await wait(500); key("keyup", "ArrowRight", 39); await wait(50);
        const went = world.player.x - x0;
        if (!ev.defaultPrevented) throw new Error("an arrow on the map scrolled the page");
        if (!(went > 30 && went < 60)) throw new Error(`half a second of walking went ${went.toFixed(1)}px (90px/s expected)`);
        key("keydown", "ArrowLeft", 37); $("world").blur(); await wait(50);
        const x1 = world.player.x; await wait(300);
        if (world.player.x !== x1) throw new Error("the player kept walking after the map lost focus");
        $("world").focus();
        // and the canvas draws: the top-left wall face isn't the background colour
        const px = game.canvas.getContext("2d").getImageData(1 * TILE + 8 - Math.round(0), 8, 1, 1).data;
        if (px[0] === 0x16 && px[1] === 0x13 && px[2] === 0x1f) throw new Error("the canvas drew no walls");
      }
      // A wall over floor shows its brick face, over wall its dark top (strict: the map must have both).
      const wallsLook = strict => {
          const W = world.walls, at = (x, y) => W.getTileAt(x, y);
          let faces = 0, tops = 0;
          W.forEachTile(t => {
            if (t.index - 1 === FRAMES.wall) { faces++; if (at(t.x, t.y + 1) && at(t.x, t.y + 1).index - 1 === FRAMES.wall) throw new Error(`a brick face at (${t.x}, ${t.y}) has wall below`); }
            if (t.index - 1 === FRAMES.wall_top) { tops++; const b = at(t.x, t.y + 1); if (t.y + 1 < W.layer.height && !(b && (b.index - 1 === FRAMES.wall || b.index - 1 === FRAMES.wall_top))) throw new Error(`a wall top at (${t.x}, ${t.y}) has floor below`); }
          });
          // a map built of brick walls shows both (a town or a forest of other solid tiles has neither)
          const bricks = world.doc.layers.find(l => l.name === "walls").data.some(g => g - 1 === FRAMES.wall);
          if (strict && bricks && (!faces || !tops)) throw new Error(`walls drew ${faces} faces and ${tops} tops`);
      };
      const playFun = async () => {
          // The fun: a chest's loot, a mimic's teeth, a barrel rolled off a hoard, a weapon switched.
          const of = t => world.objects.filter(o => o.type === t);
          const has = () => fun.items.length;
          for (const c of of("chest")) {
            const n = has(); await walk(c); talk(world.nearby());
            if (c.loot === MIMIC ? has() !== n || c.sprite.frame.name !== FRAMES.mimic : has() !== n + 1 || !fun.items.includes(c.loot))
              throw new Error(`the chest of ${c.loot} gave the wrong thing`);
            talk(world.nearby());
            if (has() !== (c.loot === MIMIC ? n : n + 1)) throw new Error("a chest gave its loot twice");
          }
          for (const b of of("barrel")) {
            const hoard = of("hoard").find(h => h.x === b.x && h.y === b.y);
            if (hoard && !hoard.hidden) throw new Error("a hoard showed before its barrel rolled");
            // standing where it would roll, it won't
            const to = world.rolledTo(b).map(v => Math.floor(v / TILE));
            await walk({ type: "barrel's landing", x: b.x, y: b.y }, [[0, 1], [0, -1], [1, 0], [-1, 0]]
              .map(([dx, dy]) => [Math.floor(b.x / TILE) + dx, Math.floor(b.y / TILE) + dy]).filter(t => t.join() !== to.join()));
            const at = [b.x, b.y];
            talk(world.nearby()); await wait(400);
            if (b.x !== at[0] || b.y !== at[1]) throw new Error("the barrel rolled onto the player");
            await walk(b, [to]); talk(world.nearby()); await wait(400);
            if (!hoard) continue;
            if (hoard.hidden || b.x === hoard.x && b.y === hoard.y) throw new Error("the barrel didn't roll off its hoard");
            const n = has(); await walk(hoard); talk(world.nearby());
            if (has() !== n + String(hoard.loot).split(",").length) throw new Error("the hoard gave the wrong loot");
          }
          const w0 = fun.weapon;
          key("keydown", "x", 88); key("keyup", "x", 88);
          if (weapons().length > 1 && (fun.weapon === w0 || world.held.frame.name !== ITEMS[fun.weapon].frame))
            throw new Error("X didn't switch the weapon in hand");
          log(`FUN ${fun.items.join(",")} | ${fun.weapon}`);
          await npcs();
      };
      const portal = world.objects.find(o => o.type === "portal" && o.to === realmId);
      const ri = realms.findIndex(r => r.id === realmId);
      const npcs = async () => {                                         // everyone has something to say
        for (const n of world.objects.filter(x => x.type === "npc")) {
          await walk(n);
          const lines = n.about ? 1 : String(n.says).split(",").length;
          const heard = [];
          for (let i = 0; i <= lines; i++) { talk(world.nearby()); heard.push($("toast").textContent); }
          if (!heard[0] || heard[lines] !== heard[0] || new Set(heard).size !== lines)
            throw new Error(`the ${n.look} by (${n.x}, ${n.y}) said ${JSON.stringify(heard)}`);
        }
        log(`NPCS ${world.mapId} ${world.objects.filter(x => x.type === "npc").length}`);
      };
      await npcs();
      for (const o of world.objects.filter(x => x.type === "portal"))      // each realm's own door
        if (o.sprite.frame.name !== (FRAMES.portals[o.to] ?? FRAMES.portal)) throw new Error(`the ${o.to} door is the wrong one`);
      // Standing by the portal names its realm, with the classic map's mark.
      await walk(portal);
      await until(() => $("toast").textContent.includes(realms[ri].name));
      const locked0 = machine.locked(Object.assign({}, state, { realm: ri, gate: null }), progress.load());
      if (locked0 && !$("toast").textContent.includes(S("mark_after_first").trim())) throw new Error("the portal doesn't say it is locked");
      log(`NEAR ${$("toast").textContent}`);
      // The art: a wall over floor shows its face, a wall over wall its top; decoration is drawn and
      // never blocks; walls stop a real walk; what you see is where the body is.
      {
        wallsLook(false);
        if (world.decor && (!world.decor.layer.data.flat().some(t => t.index > 0) || world.decor.layer.data.flat().some(t => t.collides)))
          throw new Error("decoration isn't drawn, or blocks");
        // From the spawn, straight up into the first solid thing above it, held long enough to cross
        // the whole map: the player stops flush beneath it.
        world.player.setPosition(world.spawn.x, world.spawn.y);
        const sx = Math.floor(world.spawn.x / TILE);
        let wy = Math.floor(world.spawn.y / TILE) - 1;
        while (wy >= 0 && !blockedTile(sx, wy)) wy--;
        if (wy < 0) throw new Error("nothing solid above the spawn to walk into");
        key("keydown", "ArrowUp", 38); await wait(Math.ceil(world.doc.height * TILE / 90 * 1000) + 300); key("keyup", "ArrowUp", 38); await wait(80);
        if (world.player.y < (wy + 1) * TILE + 6 - 0.5) throw new Error(`walked into the wall above the spawn (y ${world.player.y.toFixed(1)})`);
        if (Math.abs(world.look.x - Math.round(world.player.x)) > 1 || Math.abs(world.look.y - Math.round(world.player.y)) > 1)
          throw new Error("the player you see isn't where its body is");
        // Back from the classic page with gold won there: the bar shows it at once.
        const before = $("hud-gold").textContent;
        const other = [...realms].reverse().find(r => r.id !== realmId && r.id !== realms[0].id);   // another realm, not this one
        if (other) {                         // (a pack of one or two realms has none to spare)
          progress.finish(other.id, 10);
          window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
          if ($("hud-gold").textContent === before) throw new Error("the gold bar didn't catch up after Back");
        }
      }
      // Back from the classic page with a gate left open: the page closes it and returns to the map.
      talk(portal);
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
      if (dialog.open || state.screen !== "map") throw new Error("pageshow left a portal dialog open");
      if (machine.locked(Object.assign({}, state, { realm: ri, gate: null }), progress.load())) {   // a fresh player plays the first realm first
        talk(portal); dispatch({ type: "enter" });
        if (world.mapId !== "overworld" || !dialog.open) throw new Error(`${realmId} let a fresh player in`);
        log(`LOCKED ${realmId}`);
        closeDialog();
        progress.finish(realms[0].id, 0);
      }
      talk(portal);
      if (state.screen !== "realm") throw new Error(`the portal did not open ${realmId}`);
      dispatch({ type: "enter" });
      await until(() => world && world.mapId === realmId);
      {
        // Beside someone along a whole side counts; across a corner doesn't.
        const first = world.objects.find(o => o.step === machine.expected(state));
        world.player.setPosition(first.x - 14, first.y + 11);
        if (world.nearby() !== first) throw new Error("pressed against the side of someone, nearby() found nobody");
        world.player.setPosition(first.x - 14, first.y + 15);
        if (world.nearby() === first) throw new Error("across a corner counted as next to someone");
        // A dialog freezes the world; held Enter doesn't click through it; Esc lets go and gives the map the keys.
        world.player.setPosition(first.x - 14, first.y);
        talk(world.nearby());
        if (!dialog.open || !world.frozen) throw new Error("talking didn't open a dialog over a frozen world");
        const before = JSON.stringify(state);
        if (!key("keydown", "Enter", 13, { repeat: true }).defaultPrevented) throw new Error("held Enter reached the dialog's button");
        if (JSON.stringify(state) !== before) throw new Error("held Enter changed the game");
        dialog.close();
        try { await until(() => !world.frozen); } catch {}   // the close event comes a task later
        if (dialog.open || world.frozen || document.activeElement !== $("world")) throw new Error(`closing the dialog didn't hand back the map (open ${dialog.open}, frozen ${world.frozen}, focus ${document.activeElement && document.activeElement.id})`);
        // Beside the step the game waits on, the page says how to talk to it.
        const hint = o => (o.type === "throne" && o.look ? S("explore_near_petitioner") : S("explore_near_step"));
        world.near = undefined; await wait(80);
        if ($("toast").textContent !== hint(first)) throw new Error(`beside the step, not its hint (${$("toast").textContent})`);
        for (const o of world.objects.filter(x => x.type === "throne" && x.look))      // a petitioner is drawn, not the throne
          if (o.sprite.frame.name !== FRAMES.npcs[o.look]) throw new Error(`the petitioner ${o.look} isn't drawn`);
        // Beside a step the game doesn't wait on yet, no hint (only where one can be stood beside alone).
        let checkedHint = 0;
        for (const o of world.objects.filter(x => x.step && x.step !== machine.expected(state))) {
          const tx = Math.floor(o.x / TILE), ty = Math.floor(o.y / TILE);
          const spot = [[0, 1], [0, -1], [1, 0], [-1, 0]].map(([dx, dy]) => [tx + dx, ty + dy]).find(([x, y]) => x > 0 && y > 0 && x < world.doc.width && y < world.doc.height && !blockedTile(x, y));
          if (!spot) continue;
          world.player.setPosition(spot[0] * TILE + TILE / 2, spot[1] * TILE + TILE / 2); world.facing = [tx - spot[0], ty - spot[1]];
          if (world.nearby() !== o) continue;
          world.near = undefined; await wait(80);
          if ([S("explore_near_step"), S("explore_near_petitioner")].includes($("toast").textContent)) throw new Error(`beside ${o.step}, which the game doesn't wait on, a hint to talk`);
          checkedHint++;
        }
        if (!checkedHint) throw new Error("no step the game doesn't wait on could be stood beside alone, to check it gives no hint");
        world.player.setPosition(first.x - 14, first.y); world.near = undefined; await wait(80);
        // A question in a realm offers the way back to the realm (Esc) and out to the world map.
        talk(world.nearby());
        if ($("leave").hidden || $("close").textContent !== S("explore_close_realm")) throw new Error("a realm's dialog doesn't offer the way back and out");
        const art = [...$("screen").querySelectorAll(".art")];
        if ($("portrait").hidden || art.some(a => getComputedStyle(a).display !== "none"))
          throw new Error("the dialog doesn't show who you talk to, or shows the classic page's art");
        $("leave").click();
        await until(() => world && world.mapId === "overworld");
        try { await until(() => !world.frozen); } catch {}
        if (dialog.open || state.screen !== "map" || world.frozen || !world.input.keyboard.enabled || document.activeElement !== $("world"))
          throw new Error(`leaving for the world map didn't hand back the map (open ${dialog.open}, screen ${state.screen}, frozen ${world.frozen}, keys ${world.input.keyboard.enabled})`);
        const door = world.objects.find(o => o.type === "portal" && o.to === realmId);
        if (Math.abs(world.player.x - door.x) + Math.abs(world.player.y - door.y) > TILE + 0.5) throw new Error("leaving didn't put the player beside the realm's door");
        talk(door);
        if (!$("leave").hidden || $("close").textContent !== S("explore_close")) throw new Error("the world map's dialog offers to leave for the world map");
        dispatch({ type: "enter" });
        await until(() => world && world.mapId === realmId);
      }
      const someone = world.objects.find(o => ["merchant", "guide", "foe", "npc"].includes(o.type) || (o.type === "throne" && o.look));
      if (!reduced && someone) {             // the living breathe (a petitioner too; an empty throne doesn't)
        const ys = new Set();
        for (let i = 0; i < 30; i++) { ys.add(someone.sprite.oy); await wait(100); }
        if (ys.size < 2) throw new Error("nobody breathes");
      }
      {                                      // facing the exit, it answers, whoever else is close
        const exit = world.objects.find(o => o.type === "exit"), want = machine.expected(state);
        const step = world.objects.find(o => o.step === want);
        // stand on a free tile beside it, facing it
        const face = obj => {
          const side = [[0, -1], [0, 1], [-1, 0], [1, 0]].find(([dx, dy]) => {
            const tx = Math.floor(obj.x / TILE) + dx, ty = Math.floor(obj.y / TILE) + dy;
            return tx >= 0 && ty >= 0 && tx < world.doc.width && ty < world.doc.height && !blockedTile(tx, ty);
          });
          world.player.setPosition(obj.x + side[0] * TILE, obj.y + side[1] * TILE); world.facing = [-side[0], -side[1]];
        };
        face(exit);
        if (world.nearby() !== exit) throw new Error("facing the exit, something else answered");
        face(step);
        if (world.nearby() !== step) throw new Error("facing the step the game waits on, it didn't answer");
      }
      // Solid things stop the player: every shut gate, as soon as it can be reached, and someone.
      const push = async (obj, axis, dir) => {
        const [k, code] = ARROWS[axis === "x" ? (dir > 0 ? "right" : "left") : (dir > 0 ? "down" : "up")];
        key("keydown", k, code); await wait(500); key("keyup", k, code); await wait(30);
        // still on the near side, a body's half-width short of it: not into it, and not through it
        const short = -((axis === "x" ? world.player.x : world.player.y) - (axis === "x" ? obj.x : obj.y)) * dir;
        if (short < TILE / 2 + 6 - 0.5) throw new Error(`walked into the ${obj.type || "gate"} (${short.toFixed(1)}px short of its centre)`);
      };
      const pushed = new Set();
      const pushGates = async () => {
        for (const gate of world.gates.filter(g => g.body.enable && !pushed.has(g))) {
          const gateTile = { type: "gate", x: gate.x, y: gate.y };
          try { await walk(gateTile); } catch (e) { if (/^no path/.test(e.message)) continue; throw e; }   // behind another gate: later
          pushed.add(gate);
          const dx = gate.x - world.player.x, dy = gate.y - world.player.y;
          await push(gateTile, Math.abs(dx) > Math.abs(dy) ? "x" : "y", Math.abs(dx) > Math.abs(dy) ? Math.sign(dx) : Math.sign(dy));
          // Beside it, the page says it is locked, and talking says so too.
          await wait(80);
          if ($("toast").textContent !== S("explore_gate_locked")) throw new Error(`beside the shut gate, no word that it is locked (${$("toast").textContent})`);
          if (!world.nearby()) { toast(""); talk(null); if ($("toast").textContent !== S("explore_gate_locked")) throw new Error("talking at the shut gate didn't say it is locked"); }
        }
      };
      {
        await pushGates();
        const someone = world.objects.find(o => o.step === machine.expected(state));
        await walk(someone);
        const dx = someone.x - world.player.x, dy = someone.y - world.player.y;
        await push(someone, Math.abs(dx) > Math.abs(dy) ? "x" : "y", Math.abs(dx) > Math.abs(dy) ? Math.sign(dx) : Math.sign(dy));
      }
      const chest = world.objects.find(o => o.type === "reward");
      const gateCount = world.gates.length;
      const steps = [];
      let decreeSeen = false;
      for (let n = 0; n < 50; n++) {
        const want = machine.expected(state);
        if (want === null) break;
        const obj = world.objects.find(o => o.step === want);
        await pushGates();
        if (want.endsWith(":reward") && chest.sprite.frame.name !== FRAMES.reward) throw new Error("the chest opened before you claimed it");
        await walk(world.objects.find(o => o.step === want));
        await wait(80);
        talk(world.nearby());
        if (!dialog.open) throw new Error(`talking at ${want} opened no dialog`);
        if (want.endsWith(":reward") && chest.sprite.frame.name !== FRAMES.reward_open) throw new Error("the chest didn't open as you claimed it");
        // each gate: 1 shut (drawn and solid), 0 open (neither), x drawn but not solid or the other way
        steps.push(want + (world.gates.length ? `[gates:${world.gates.map(g => (g.body.enable && g.visible ? 1 : !g.body.enable && !g.visible ? 0 : "x")).join("")}]` : ""));
        for (let d = 0; d < 60 && dialog.open; d++) {
          if (state.screen === "decree" && !decreeSeen) {   // the decree: shown, kept by Esc, read again at a throne
            decreeSeen = true;
            if (!$("screen").textContent.includes(S("decree_title"))) throw new Error("the decree wasn't shown");
            dialog.close();
            try { await until(() => !world.frozen); } catch {}
            if (state.screen !== "decree" || dialog.open) throw new Error("closing the decree lost it");
            talk(world.nearby());
            if (!dialog.open || !$("screen").textContent.includes(S("decree_title"))) throw new Error("the throne didn't show the decree again");
            log(`DECREE ${realmId}`);
            continue;
          }
          const last = actions[actions.length - 1];
          dispatch(state.flash ? actions[0] : (last && last.type === "magic" ? last : actions[0]));
          await wait(20);
        }
        if (state.screen === "map" || world.mapId === "overworld") break;
      }
      if (pushed.size !== gateCount) throw new Error(`only ${pushed.size} of ${gateCount} gates were ever pushed against while shut`);
      // Nothing came from anywhere but this site.
      for (const e of performance.getEntriesByType("resource"))
        if (!e.name.startsWith(location.origin + "/") && !/^(data|blob):/.test(e.name)) log(`ERROR outside request ${e.name}`);
      log(`SMOKE ${realmId} ${steps.join(" ")} | ${JSON.stringify(progress.load()[realmId] || null)}`);
      // Then the fun, which maps.py promises can all be reached once the quest is done: back in
      // through the door (its gates open now), then out by the exit.
      await until(() => world && world.mapId === "overworld");
      // Back from the realm, by victory now and by the exit later: one tile from its door, on floor.
      const besideDoor = how => {
        const d = world.objects.find(o => o.type === "portal" && o.to === realmId);
        if (Math.abs(Math.abs(world.player.x - d.x) + Math.abs(world.player.y - d.y) - TILE) > 0.5 || blockedTile(Math.floor(world.player.x / TILE), Math.floor(world.player.y / TILE)))
          throw new Error(`back from ${realmId} by ${how}, the player wasn't one tile from its door`);
      };
      besideDoor("victory");
      const door = world.objects.find(o => o.type === "portal" && o.to === realmId);
      await walk(door); talk(world.nearby());
      if (!dialog.open || state.screen !== "realm") throw new Error(`the ${realmId} door didn't open`);
      dispatch({ type: "enter" });
      await until(() => world && world.mapId === realmId);
      wallsLook(true);
      for (const g of world.gates) {         // open now: standing in the doorway, no word of a lock
        world.player.setPosition(g.x, g.y); world.near = undefined; await wait(80);
        if (g.body.enable || world.shutGate() || $("toast").textContent === S("explore_gate_locked")) throw new Error("an open gate still says it is locked");
      }
      await playFun();
      const exit = world.objects.find(o => o.type === "exit");
      await walk(exit); talk(world.nearby());
      await until(() => world && world.mapId === "overworld");
      besideDoor("the exit");
      log(`EXIT ${realmId}`);
      game.halt();                           // done: headless Chrome needn't run frames to the end of its budget
      return steps;
    }
  };
  if (SMOKE) Quest.explore.smoke(location.hash.slice(7)).catch(e => { log(`ERROR smoke: ${e.message} @ ${String(e.stack || "").split("\n").slice(1, 3).join(" | ")}`); game.halt(); });
})();
