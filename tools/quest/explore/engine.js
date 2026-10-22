// Quest.engine: the explore page's own small tile engine, in place of a game library (so the page
// ships no third-party code). It does only what the page needs: draw a Tiled map's tile layers and
// one-tile sprites from one atlas, move a 12x12 body against solid tiles and solid sprites, read
// the arrow keys, follow the player with the camera, and run timers, tweens and a fade.
// The geometry (Quest.engine.Layer, Quest.engine.move) has no DOM, so node tests can drive it.
var Quest = (typeof Quest === "object" && Quest) || {};
(function (Q) {
  "use strict";
  const TILE = 16, GID = 0x1FFFFFFF;

  // A tile layer, as Tiled saves it (CSV data, gid 0 is empty). Tiles are live objects: setting a
  // tile's index changes what is drawn. getTileAt returns null for an empty tile.
  class Layer {
    constructor(spec) {
      this.name = spec.name;
      this.width = spec.width; this.height = spec.height;
      const rows = [];
      for (let y = 0; y < spec.height; y++) {
        const row = [];
        for (let x = 0; x < spec.width; x++) {
          const g = (spec.data[y * spec.width + x] || 0) & GID;
          row.push({ x, y, index: g > 0 ? g : -1, collides: false });
        }
        rows.push(row);
      }
      this.layer = { data: rows, width: spec.width, height: spec.height };
    }
    getTileAt(x, y) {
      const t = this.layer.data[y] && this.layer.data[y][x];
      return t && t.index > 0 ? t : null;
    }
    getTileAtWorldXY(x, y) { return this.getTileAt(Math.floor(x / TILE), Math.floor(y / TILE)); }
    forEachTile(fn) { for (const row of this.layer.data) for (const t of row) fn(t); }
    setCollisionByExclusion() { this.forEachTile(t => { t.collides = t.index > 0; }); return this; }
  }

  // Move a box (centre x, y; size w, h) by dx then dy, stopping at anything solid(x0, y0, x1, y1,
  // from) reports. One axis at a time, so the box slides along walls; steps of at most half a tile,
  // so nothing is passed through. A solid the box already overlaps where it stands (`from`) never
  // stops it, so something that moved onto the player can be walked out of, and never shoves it.
  // Returns the new centre.
  function move(box, dx, dy, solid) {
    let { x, y } = box;
    const hw = box.w / 2, hh = box.h / 2;
    const steps = Math.max(1, Math.ceil(Math.max(Math.abs(dx), Math.abs(dy)) / (TILE / 2)));
    for (let i = 0; i < steps; i++) {
      const sx = dx / steps, sy = dy / steps;
      if (sx) {
        const nx = x + sx, hit = solid(nx - hw, y - hh, nx + hw, y + hh, [x - hw, y - hh, x + hw, y + hh]);
        if (!hit) x = nx;
        else x = sx > 0 ? hit.x0 - hw : hit.x1 + hw;          // flush against what it hit
      }
      if (sy) {
        const ny = y + sy, hit = solid(x - hw, ny - hh, x + hw, ny + hh, [x - hw, y - hh, x + hw, y + hh]);
        if (!hit) y = ny;
        else y = sy > 0 ? hit.y0 - hh : hit.y1 + hh;
      }
    }
    return { x, y };
  }

  // What blocks a box: solid tiles of a layer and enabled sprite bodies (each one tile, centred).
  // Returns the first rectangle it overlaps that `from` (a box, [x0, y0, x1, y1]) doesn't already
  // overlap, or null. Touching edges don't count.
  function blocker(layer, bodies) {
    const e = 1e-6;
    const over = (r, a0, b0, a1, b1) => a0 < r.x1 - e && a1 > r.x0 + e && b0 < r.y1 - e && b1 > r.y0 + e;
    return (x0, y0, x1, y1, from) => {
      const hit = r => over(r, x0, y0, x1, y1) && !(from && over(r, ...from));
      for (let ty = Math.floor(y0 / TILE); ty <= Math.floor((y1 - e) / TILE); ty++)
        for (let tx = Math.floor(x0 / TILE); tx <= Math.floor((x1 - e) / TILE); tx++) {
          const t = layer && layer.getTileAt(tx, ty), r = { x0: tx * TILE, y0: ty * TILE, x1: tx * TILE + TILE, y1: ty * TILE + TILE };
          if (t && t.collides && hit(r)) return r;
        }
      for (const b of bodies()) {
        const r = { x0: b.x - TILE / 2, y0: b.y - TILE / 2, x1: b.x + TILE / 2, y1: b.y + TILE / 2 };
        if (hit(r)) return r;
      }
      return null;
    };
  }

  // A one-tile picture from the atlas. A solid one has a body that blocks the player while enabled.
  class Sprite {
    constructor(x, y, frame, solid) {
      this.x = x; this.y = y; this.frame = { name: frame }; this.oy = 0;   // oy: drawn this far below its body
      this.visible = true; this.flipX = false; this.depth = 0; this.scale = 1; this.angle = 0;
      this.body = solid ? { enable: true } : null;
    }
    setFrame(f) { this.frame.name = f; return this; }
    setVisible(v) { this.visible = v; return this; }
    setPosition(x, y) { this.x = x; this.y = y; return this; }
    setY(y) { this.y = y; return this; }
    setOffsetY(oy) { this.oy = oy; return this; }    // moves the picture, never the body
    setFlipX(f) { this.flipX = f; return this; }
    setDepth(d) { this.depth = d; return this; }
    setScale(s) { this.scale = s; return this; }
    refreshBody() { return this; }
  }

  // The player: a 12x12 body moved by its velocity each frame; deltaX/deltaY say how far it got.
  class Body {
    constructor(x, y) { this.x = x; this.y = y; this.w = 12; this.h = 12; this.vx = 0; this.vy = 0; this.dx = 0; this.dy = 0; }
    setPosition(x, y) { this.x = x; this.y = y; return this; }
    setVelocity(vx, vy) { this.vx = vx; this.vy = vy; return this; }
    get body() { return { deltaX: () => this.dx, deltaY: () => this.dy }; }
  }

  // The game: a canvas, a loop, keys, a camera, timers and tweens, and one scene at a time.
  function create({ parent, width, height, background, atlas, columns, keyTarget, timeouts }) {
    const canvas = document.createElement("canvas");
    canvas.width = width; canvas.height = height;
    parent.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("no 2D canvas");
    ctx.imageSmoothingEnabled = false;

    const keys = { left: false, right: false, up: false, down: false };
    const KEYS = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down", 37: "left", 39: "right", 38: "up", 40: "down" };
    const input = { enabled: true, cursors: { left: {}, right: {}, up: {}, down: {} }, resetKeys() { for (const k in keys) keys[k] = false; } };
    for (const k of Object.keys(keys)) Object.defineProperty(input.cursors[k], "isDown", { get: () => keys[k] });
    const onKey = down => e => {
      const k = KEYS[e.key] || KEYS[e.keyCode];
      if (!k) return;
      e.preventDefault();                         // arrows walk the map, they don't scroll the page
      if (input.enabled || !down) keys[k] = down;
    };
    keyTarget.addEventListener("keydown", onKey(true));
    keyTarget.addEventListener("keyup", onKey(false));
    keyTarget.addEventListener("blur", () => input.resetKeys());

    const game = { loop: { frame: 0 }, canvas, input };
    let scene = null, now = 0;
    const timers = [], tweens = [];
    const time = {
      get now() { return now; },
      addEvent({ delay, loop, callback }) { const t = { at: now + delay, delay, loop, callback }; timers.push(t); return t; },
    };
    const tween = {
      add({ targets, duration, ...to }) {
        const from = {};
        for (const k of Object.keys(to)) from[k] = targets[k] || 0;
        tweens.push({ target: targets, from, to, start: now, duration });
      },
    };
    const camera = { x: 0, y: 0, lerp: 1, fade: 0, fadeFrom: 0, fadeMs: 0, follow: null, w: width, h: height, boundsW: width, boundsH: height,
      startFollow(target, _round, lx) { this.follow = target; this.lerp = lx; this.snap(); },
      setBounds(_x, _y, w, h) { this.boundsW = w; this.boundsH = h; },
      fadeIn(ms) { this.fade = 1; this.fadeFrom = now; this.fadeMs = ms; },
      snap() { if (this.follow) { this.x = this.goal("x"); this.y = this.goal("y"); } },
      goal(axis) {
        const size = axis === "x" ? this.w : this.h, bound = axis === "x" ? this.boundsW : this.boundsH;
        const c = this.follow[axis] - size / 2;
        return Math.max(0, Math.min(Math.max(0, bound - size), c));
      },
    };

    function step(ms) {
      now += ms; game.loop.frame++;
      for (const t of timers.slice()) {
        if (now < t.at) continue;
        t.callback();
        if (t.loop) t.at += t.delay; else timers.splice(timers.indexOf(t), 1);
      }
      for (const w of tweens.slice()) {
        const k = Math.min(1, (now - w.start) / w.duration);
        for (const p of Object.keys(w.to)) w.target[p] = w.from[p] + (w.to[p] - w.from[p]) * k;
        if (k >= 1) tweens.splice(tweens.indexOf(w), 1);
      }
      if (!scene) return;
      scene.update && scene.update();
      const p = scene.player;
      if (p) {
        const to = move(p, p.vx * ms / 1000, p.vy * ms / 1000, scene.blocks);
        p.dx = to.x - p.x; p.dy = to.y - p.y; p.x = to.x; p.y = to.y;
      }
      scene.postupdate && scene.postupdate();
      if (camera.follow) {
        camera.x += (camera.goal("x") - camera.x) * camera.lerp;
        camera.y += (camera.goal("y") - camera.y) * camera.lerp;
      }
      if (camera.fade) camera.fade = Math.max(0, 1 - (now - camera.fadeFrom) / camera.fadeMs);
    }
    function frame(ctx2, f, x, y, flip, scale, angle) {
      const sx = (f % columns) * TILE, sy = Math.floor(f / columns) * TILE, s = TILE * scale;
      ctx2.save();
      ctx2.translate(Math.round(x), Math.round(y));
      if (angle) ctx2.rotate(angle * Math.PI / 180);
      if (flip) ctx2.scale(-1, 1);
      ctx2.drawImage(atlas, sx, sy, TILE, TILE, -s / 2, -s / 2, s, s);
      ctx2.restore();
    }
    function draw() {
      ctx.fillStyle = background;
      ctx.fillRect(0, 0, width, height);
      if (!scene) return;
      const ox = Math.round(camera.x), oy = Math.round(camera.y);
      const tx0 = Math.floor(ox / TILE), ty0 = Math.floor(oy / TILE), tx1 = tx0 + Math.ceil(width / TILE), ty1 = ty0 + Math.ceil(height / TILE);
      for (const layer of scene.layers)                  // only the tiles in view
        for (let ty = Math.max(0, ty0); ty <= Math.min(layer.height - 1, ty1); ty++)
          for (let tx = Math.max(0, tx0); tx <= Math.min(layer.width - 1, tx1); tx++) {
            const t = layer.layer.data[ty][tx];
            if (t.index > 0) frame(ctx, t.index - 1, tx * TILE + TILE / 2 - ox, ty * TILE + TILE / 2 - oy, false, 1, 0);
          }
      const sprites = scene.sprites.filter(s => s.visible).sort((a, b) => a.depth - b.depth);
      for (const s of sprites) frame(ctx, s.frame.name, s.x - ox, s.y + s.oy - oy, s.flipX, s.scale, s.angle);
      if (camera.fade > 0) { ctx.globalAlpha = camera.fade; ctx.fillStyle = "#000"; ctx.fillRect(0, 0, width, height); ctx.globalAlpha = 1; }
    }
    // Fixed steps of 1/60 s, as many as real time has passed (so speed is the same at 30, 60 or
    // 144 Hz), catching up at most a quarter of a second after a stall. An error is reported and
    // the loop goes on.
    const STEP = 1000 / 60;
    let last = null, owed = 0;
    const tick = () => {
      const t = typeof performance === "object" ? performance.now() : Date.now();
      owed += last === null ? STEP : Math.min(250, t - last);
      last = t;
      try {
        let n = 0;
        while (owed >= STEP && n++ < 15) { step(STEP); owed -= STEP; }
        draw();
      } catch (e) { (game.onerror || (() => {}))(e); }
      schedule();
    };
    const schedule = () => (timeouts || typeof requestAnimationFrame !== "function" ? setTimeout(tick, STEP) : requestAnimationFrame(tick));

    // A scene: the layers it draws, its sprites, the player's body and what blocks it.
    game.start = build => {
      timers.length = 0; tweens.length = 0; camera.follow = null; camera.fade = 0;
      scene = { layers: [], sprites: [], player: null, blocks: () => null };
      const api = {
        time, tweens: tween, cameras: { main: camera }, input: { keyboard: input }, game,
        addLayer(spec) { const l = new Layer(spec); scene.layers.push(l); return l; },
        addSprite(x, y, f, solid) { const s = new Sprite(x, y, f, solid); scene.sprites.push(s); return s; },
        addPlayer(x, y) { scene.player = new Body(x, y); return scene.player; },
        collide(layer) { scene.blocks = blocker(layer, () => scene.sprites.filter(s => s.body && s.body.enable)); },
      };
      Object.assign(scene, build(api) || {});
      draw();
    };
    schedule();
    return game;
  }

  Q.engine = { TILE, Layer, Sprite, Body, move, blocker, create };
})(Quest);
