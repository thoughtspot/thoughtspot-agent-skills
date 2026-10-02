/* ==== amuzing core v1 | source: library/_shared/core.js | run helpers/sync-core.mjs, do not edit inside a chart ==== */
const AZ = (function () {
  // -- theme: one palette for the whole Liveboard -------------------------------
  // Families are validated categorical hues (dataviz validator, light surface).
  // Region is never a hue: it is shown by position, label or a slate ramp, so a
  // colour keeps exactly one meaning across every tile.
  const T = {
    ink: '#1E1E24', ink2: '#52525B', muted: '#8A8A94', grid: '#E6E7EA', surface: '#FFFFFF',
    good: '#1F7A4D', bad: '#B3261E',
    slate: ['#EEF0F3', '#D5DAE1', '#B4BDC9', '#8E9AAB', '#6A7891', '#4A5872', '#2F3B54', '#1E293B'],
    family: {
      'Outerwear': '#D1543A', 'Tops and dresses': '#2A6FD0', 'Bottoms': '#0F9D8A',
      'Swim and basics': '#D99A00', 'Accessories': '#C2477A'
    },
    font: "Geist, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
  };
  // Editorial grouping of the model's 15 item types (not a model column).
  const FAMILY_OF = {
    Jackets: 'Outerwear', Vests: 'Outerwear', Sweatshirts: 'Outerwear', Sweaters: 'Outerwear',
    Shirts: 'Tops and dresses', Dresses: 'Tops and dresses',
    Pants: 'Bottoms', Jeans: 'Bottoms', Shorts: 'Bottoms', Skirts: 'Bottoms',
    Swimwear: 'Swim and basics', Underwear: 'Swim and basics', Socks: 'Swim and basics',
    Bags: 'Accessories', Headwear: 'Accessories'
  };
  const familyOf = (item) => FAMILY_OF[item] || FAMILY_OF[String(item || '').replace(/^./, (c) => c.toUpperCase())] || 'Other';
  const familyColor = (item) => T.family[familyOf(item)] || T.muted;

  // -- host access ------------------------------------------------------------
  // Bare viz identifier, never globalThis.viz (see hard-rules.md).
  function host() {
    try { if (typeof viz !== 'undefined' && viz) return viz; } catch (e) {}
    return null;
  }
  const cellVal = (v) => {
    if (v == null || typeof v !== 'object') return v;
    try {
      const raw = typeof v.value === 'function' ? v.value() : v.value;
      return raw ?? v._value ?? v.v ?? v.formatted ?? v.f ?? null;
    } catch (e) { return v._value ?? null; }
  };
  // Live rows as objects keyed by column name, or null when the tile has no data.
  function liveData() {
    try {
      const h = host();
      const dm = h && h.getDataFromSearchQuery && h.getDataFromSearchQuery();
      const raw = dm && dm.getData();
      if (!raw || !raw.data || !raw.data.length) return null;
      const schema = raw.schema || [];
      const rows = raw.data.map((arr) => {
        const o = {};
        schema.forEach((c, i) => { o[c.name] = cellVal(arr[i]); });
        return o;
      });
      return { schema, rows };
    } catch (e) { console.warn('[chart] live data unavailable:', e); return null; }
  }
  // Resolve a column by regex against the schema (the host renames: Total sales, Month(date)).
  function col(schema, re, opt) {
    const c = schema.find((s) => re.test(s.name));
    if (!c && !(opt && opt.optional)) throw new Error('Column not found in the search: ' + re + ' | have: ' + schema.map((s) => s.name).join(', '));
    return c ? c.name : null;
  }
  const num = (v) => { const n = Number(v); return isFinite(n) ? n : 0; };
  // Dates arrive as epoch ms (or seconds from other paths); normalise to ms.
  const ms = (v) => { const n = Number(v); return n < 1e11 ? n * 1000 : n; };

  // -- formatting -------------------------------------------------------------
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const money = (n, d) => {
    const a = Math.abs(n), s = n < 0 ? '-' : '';
    if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(d ?? 2) + 'B';
    if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(d ?? 1) + 'M';
    if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(d ?? 0) + 'K';
    return s + '$' + a.toFixed(d ?? 0);
  };
  const int = (n) => { const a = Math.abs(n); return a >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : a >= 1e3 ? (n / 1e3).toFixed(a >= 1e5 ? 0 : 1) + 'K' : String(Math.round(n)); };
  const pct = (x, d, signed) => (signed && x > 0 ? '+' : '') + (x * 100).toFixed(d ?? 1) + '%';
  // Signed gap in percentage points, e.g. pts(0.009) -> '+0.9 pts'
  const pts = (x, d) => (x > 0 ? '+' : '') + (x * 100).toFixed(d ?? 1) + ' pts';
  const monthLabel = (t) => { const d = new Date(t); return MON[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); };
  const monthShort = (t) => MON[new Date(t).getUTCMonth()];
  const year = (t) => new Date(t).getUTCFullYear();
  const isoDay = (t) => new Date(t).toISOString().slice(0, 10);

  // -- same-period comparison: latest month in the data drives "YTD" ---------
  // rows: [{t: ms(month start), v: number}] at monthly grain.
  function ytd(rows) {
    if (!rows.length) return null;
    const last = Math.max.apply(null, rows.map((r) => r.t));
    const ly = year(last), lm = new Date(last).getUTCMonth();
    let cur = 0, prev = 0, nCur = 0, nPrev = 0;
    rows.forEach((r) => {
      const d = new Date(r.t), y = d.getUTCFullYear(), m = d.getUTCMonth();
      if (m > lm) return;
      if (y === ly) { cur += r.v; nCur++; } else if (y === ly - 1) { prev += r.v; nPrev++; }
    });
    return { cur, prev, delta: cur - prev, pct: prev ? cur / prev - 1 : null, lastMs: last, year: ly, month: lm, through: monthLabel(last), comparable: nCur === nPrev && nPrev > 0 };
  }

  // -- CDN loader: bounded, with fallback hosts (a hung request fires neither onload nor onerror)
  function loadScript(urls, isReady, timeoutMs) {
    const list = [].concat(urls);
    const tryOne = (i) => new Promise((resolve, reject) => {
      if (isReady()) return resolve();
      if (i >= list.length) return reject(new Error('Library could not be loaded from: ' + list.join(' , ')));
      const s = document.createElement('script');
      let done = false;
      const next = () => { if (done) return; done = true; s.remove(); tryOne(i + 1).then(resolve, reject); };
      const t = setTimeout(next, timeoutMs || 8000);
      s.src = list[i];
      s.onload = () => { if (done) return; done = true; clearTimeout(t); isReady() ? resolve() : tryOne(i + 1).then(resolve, reject); };
      s.onerror = () => { clearTimeout(t); next(); };
      document.head.appendChild(s);
    });
    // The HTML tab may already carry a <script src> for this library: if so, give it a moment to finish before
    // injecting a second copy. If no such tag exists, inject at once (no wait).
    const tagged = list.some((u) => document.querySelector('script[src="' + u + '"]'));
    if (!tagged) return tryOne(0);
    return new Promise((resolve, reject) => {
      let waited = 0;
      const poll = () => { if (isReady()) return resolve(); if ((waited += 100) >= 3000) return tryOne(0).then(resolve, reject); setTimeout(poll, 100); };
      poll();
    });
  }

  // -- mount + boot ------------------------------------------------------------
  function mount() {
    let el = document.getElementById('chart');
    if (!el) { el = document.createElement('div'); el.id = 'chart'; document.body.appendChild(el); }
    return el;
  }
  function paint(el, html) { (el || document.getElementById('chart') || document.body).innerHTML = html; }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function done() {
    try { host().events.emitRenderCompletedEvent(); } catch (e) { console.warn('[chart] emitRenderCompletedEvent unavailable:', e); }
  }

  // -- motion: small, motivated, and off under prefers-reduced-motion ---------
  const reduced = () => { try { return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); } catch (e) { return false; } };
  const EASE = { out: (t) => 1 - Math.pow(1 - t, 3), inOut: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2), spring: (t) => 1 - Math.pow(1 - t, 4) * Math.cos(t * 9) * (1 - t) };
  // tween(ms, step, done, easing): calls step(0..1) each frame; returns a cancel function.
  // With reduced motion it jumps straight to step(1).
  function tween(ms, step, done, easing) {
    const ez = easing || EASE.out;
    if (reduced() || !ms) { step(1); if (done) done(); return () => {}; }
    let raf = 0, t0 = 0, dead = false;
    const f = (t) => { if (dead) return; if (!t0) t0 = t; const k = Math.min(1, (t - t0) / ms); step(ez(k)); if (k < 1) raf = requestAnimationFrame(f); else if (done) done(); };
    raf = requestAnimationFrame(f);
    return () => { dead = true; cancelAnimationFrame(raf); };
  }
  // animator(): a tween runner that cancels its previous run on re-entry, so rapid toggles never fight.
  //   const go = AZ.animator(); go(400, (k) => draw(k), done); go(400, ...) again cancels the first.
  function animator() { let cancel = null; const run = (ms, step, done, easing) => { if (cancel) cancel(); cancel = tween(ms, step, done, easing); return cancel; }; run.stop = () => { if (cancel) cancel(); cancel = null; }; return run; }
  // Count a number up into an element: countUp(node, 142100000, AZ.money, 700)
  function countUp(node, to, fmt, ms, from) {
    const a = from == null ? 0 : from;
    return tween(ms || 700, (k) => { node.textContent = fmt(a + (to - a) * k); });
  }
  // Linear interpolation helper for tweens.
  const lerp = (a, b, k) => a + (b - a) * k;
  // Wait for web fonts and one animation frame so layout is final before you measure an element.
  const settle = () => new Promise((res) => {
    const done = () => requestAnimationFrame(() => requestAnimationFrame(res));
    try { if (document.fonts && document.fonts.ready) { Promise.race([document.fonts.ready, new Promise((r) => setTimeout(r, 400))]).then(done, done); return; } } catch (e) {}
    done();
  });
  // Breadcrumb for drill-down: crumbs(['All sales', 'Outerwear'], (index) => jumpTo(index)) -> html.
  // Wire clicks with AZ.wireCrumbs(el, onJump). The last crumb is the current level and is not a button.
  const crumbs = (names) => '<nav class="az-crumbs" aria-label="Drill path">' + names.map((n, i) => (i < names.length - 1 ? '<button type="button" class="az-crumb" data-i="' + i + '">' + esc(n) + '</button><span class="az-sep">/</span>' : '<span class="az-crumb now">' + esc(n) + '</span>')).join('') + '</nav>';
  function wireCrumbs(root, onJump) { root.querySelectorAll('.az-crumb[data-i]').forEach((b) => b.addEventListener('click', () => onJump(Number(b.getAttribute('data-i'))))); }

  // boot({ need: 'plain-English list of what the search must return', render(ctx) })
  // ctx = { el, rows, schema, w, h, redraw }; render may be async and may return a cleanup fn.
  function boot(opts) {
    let el = null, cleanup = null, lastW = 0, lastH = 0, timer = null, running = false;
    const run = async (first) => {
      if (running) return; running = true;
      try {
        el = mount();
        const data = liveData();
        if (!data) {
          paint(el, '<div class="az-empty"><b>No data yet</b><span>Attach a search with: ' + esc(opts.need) + '</span></div>');
          return;
        }
        if (typeof cleanup === 'function') { try { cleanup(); } catch (e) {} cleanup = null; }
        const r = el.getBoundingClientRect();
        lastW = Math.round(r.width); lastH = Math.round(r.height);
        cleanup = await opts.render({ el, rows: data.rows, schema: data.schema, w: lastW, h: lastH, redraw: () => run(false) });
        // Smooth entrance on first paint, a soft cross-fade on every redraw (toggle, drill, resize).
        el.classList.remove('az-in', 'az-swap'); void el.offsetWidth; el.classList.add(first ? 'az-in' : 'az-swap');
      } catch (err) {
        console.error('[chart] render failed:', err);
        paint(el, '<pre class="az-err">' + esc(err && err.stack || err) + '</pre>');
      } finally {
        running = false;
        if (first) done();
      }
    };
    run(true);
    if (typeof ResizeObserver !== 'undefined') {
      // Observe the chart container itself: a Liveboard tile resizes while the window does not.
      new ResizeObserver(() => {
        const t = mount(), r = t.getBoundingClientRect();
        if (Math.abs(r.width - lastW) < 2 && Math.abs(r.height - lastH) < 2) return;
        clearTimeout(timer); timer = setTimeout(() => run(false), 120);
      }).observe(mount());
    }
  }

  // -- tooltip: one look for every tile ---------------------------------------
  // const tip = AZ.tip(el); tip.show(html, x, y) with x,y in px relative to el; tip.hide().
  function tip(root) {
    root.style.position = root.style.position || 'relative';
    const d = document.createElement('div');
    d.className = 'az-tip';
    root.appendChild(d);
    return {
      show(html, x, y) {
        d.innerHTML = html; d.style.opacity = '1';
        const rw = root.clientWidth, rh = root.clientHeight, w = d.offsetWidth, h = d.offsetHeight;
        let left = x + 14, top = y - h - 10;
        if (left + w > rw - 4) left = x - w - 14;
        if (left < 4) left = 4;
        if (top < 4) top = Math.min(rh - h - 4, y + 16);
        d.style.left = Math.round(left) + 'px'; d.style.top = Math.round(top) + 'px';
      },
      hide() { d.style.opacity = '0'; },
      el: d
    };
  }
  const row = (k, v, swatch) => '<div class="az-tr"><span class="az-tk">' + (swatch ? '<i style="background:' + swatch + '"></i>' : '') + esc(k) + '</span><span class="az-tv">' + esc(v) + '</span></div>';

  return { tip, row, settle, reduced, EASE, tween, animator, countUp, lerp, crumbs, wireCrumbs, T, FAMILY_OF, familyOf, familyColor, host, cellVal, liveData, col, num, ms, money, int, pct, pts, monthLabel, monthShort, year, isoDay, MON, ytd, loadScript, mount, paint, esc, boot };
})();
/* ==== end amuzing core ==== */

// Search: [sales] [quantity purchased] [item type] [date].quarterly
// Gapminder-style bubbles: one bubble per item type, x units in the quarter, y price per unit, area sales.
// Play / Pause and a scrub slider move through the quarters; bubbles glide between them and leave a short trail.
// Hover a bubble for its numbers; click one to follow it (the rest dim and its path across all quarters is drawn).
let fpos = null, playing = false, followed = null;

AZ.boot({
  need: 'sales, quantity purchased, item type and date at quarterly grain, e.g. [sales] [quantity purchased] [item type] [date].quarterly',
  render: async ({ el, rows, schema, w, h }) => {
    const sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity/i), iK = AZ.col(schema, /item/i), dK = AZ.col(schema, /date|quarter|month/i);
    const qset = new Set(), by = new Map();
    rows.forEach((r) => {
      const t = AZ.ms(r[dK]); if (!isFinite(t)) return;
      qset.add(t);
      const k = String(r[iK]);
      if (!by.has(k)) by.set(k, new Map());
      const m = by.get(k), o = m.get(t) || { s: 0, u: 0 };
      o.s += AZ.num(r[sK]); o.u += AZ.num(r[uK]); m.set(t, o);
    });
    const qs = Array.from(qset).sort((a, b) => a - b);
    if (!qs.length || !by.size) { AZ.paint(el, '<div class="az-empty"><b>No quarters in the result</b><span>The search needs [sales] [quantity purchased] [item type] [date].quarterly</span></div>'); return; }
    const last = qs.length - 1;
    const qLabel = (t) => { const d = new Date(t); return 'Q' + (Math.floor(d.getUTCMonth() / 3) + 1) + ' ' + d.getUTCFullYear(); };
    const items = Array.from(by.keys()).map((name) => {
      const m = by.get(name);
      const pts = qs.map((t) => { const o = m.get(t); return o && o.u > 0 && o.s > 0 ? { s: o.s, u: o.u, p: o.s / o.u } : null; });
      return { name, pts, col: AZ.familyColor(name), fam: AZ.familyOf(name) };
    }).filter((it) => it.pts.some((p) => p));
    if (!items.length) { AZ.paint(el, '<div class="az-empty"><b>No units in the result</b><span>The search needs [quantity purchased] alongside [sales]</span></div>'); return; }
    if (fpos == null || fpos > last) fpos = last;
    if (followed && !by.has(followed)) followed = null;
    const firstJune = new Date(qs[0]).getUTCFullYear() === 2021 && new Date(qs[0]).getUTCMonth() === 3;
    const qtotal = qs.map((t, i) => items.reduce((a, it) => a + (it.pts[i] ? it.pts[i].s : 0), 0));

    let xmax = 0, pmin = 1e12, pmax = 0, smax = 0;
    items.forEach((it) => it.pts.forEach((p) => { if (!p) return; xmax = Math.max(xmax, p.u); pmin = Math.min(pmin, p.p); pmax = Math.max(pmax, p.p); smax = Math.max(smax, p.s); }));
    const niceMax = (v) => { const pw = Math.pow(10, Math.floor(Math.log10(v))); return ([1, 2, 2.5, 5, 10].find((n) => n * pw >= v) || 10) * pw; };
    const xTop = niceMax(xmax * 1.04);
    const span0 = Math.max(4, pmax - pmin), ystep = [1, 2, 5, 10, 20, 25, 50].find((n) => n * 4 >= span0 * 1.15) || 50;
    let yLo = Math.max(0, Math.floor(pmin / ystep) * ystep - (pmin - Math.floor(pmin / ystep) * ystep < ystep * 0.25 ? ystep : 0)), yHi = yLo + ystep * 4;
    while (yHi < pmax + ystep * 0.2) yHi += ystep;
    const yTicks = Math.round((yHi - yLo) / ystep);

    el.classList.toggle('bm-sm', w < 340); el.classList.toggle('bm-md', w < 480);
    el.innerHTML =
      '<div class="bm-head" id="bm-head"></div>'
      + '<div class="bm-ctl"><button type="button" class="bm-btn" id="bm-play"></button>'
      + '<input type="range" class="bm-slider" id="bm-sl" min="0" max="' + last + '" step="1" value="' + Math.round(fpos) + '" aria-label="Quarter"' + (last ? '' : ' disabled') + '>'
      + '<div class="bm-q" id="bm-q"></div></div>'
      + '<div class="bm-plot" id="bm-plot"></div>'
      + '<div class="bm-key" id="bm-key"></div>';
    const head = el.querySelector('#bm-head'), btn = el.querySelector('#bm-play'), sl = el.querySelector('#bm-sl'), qEl = el.querySelector('#bm-q'), plot = el.querySelector('#bm-plot'), key = el.querySelector('#bm-key');
    const fams = []; items.forEach((it) => { if (fams.indexOf(it.fam) < 0) fams.push(it.fam); });
    key.innerHTML = fams.map((f) => '<span class="bm-k"><i style="background:' + AZ.T.family[f] + '"></i>' + AZ.esc(f) + '</span>').join('')
      + '<span class="bm-note">Area is sales in the quarter.' + (firstJune && w > 420 ? ' ' + AZ.esc(qLabel(qs[0])) + ' holds June only.' : '') + '</span>';

    const W = Math.max(200, plot.clientWidth), H = Math.max(100, plot.clientHeight);
    const narrow = W < 420, ML = narrow ? 40 : 52, MR = 14, MT = 10, MB = 30;
    const pw = W - ML - MR, ph = H - MT - MB;
    const xs = (v) => ML + v / xTop * pw, ys = (v) => MT + (1 - (v - yLo) / (yHi - yLo)) * ph;
    const rMax = Math.max(14, Math.min(38, Math.min(pw, ph) * 0.14));
    const rs = (s) => Math.max(2.5, rMax * Math.sqrt(s / smax));
    const NS = 'http://www.w3.org/2000/svg';
    const mk = (tag, attrs, parent) => { const n = document.createElementNS(NS, tag); Object.keys(attrs || {}).forEach((k) => n.setAttribute(k, attrs[k])); if (parent) parent.appendChild(n); return n; };

    const svg = mk('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': 'Bubble chart of item types by quarter' }, plot);
    // grid + axes
    const gA = mk('g', {}, svg);
    for (let i = 0; i <= yTicks; i++) {
      const v = yLo + ystep * i, y = ys(v);
      mk('line', { x1: ML, x2: W - MR, y1: y, y2: y, stroke: AZ.T.grid }, gA);
      mk('text', { class: 'bm-ax', x: ML - 6, y: y + 4, 'text-anchor': 'end' }, gA).textContent = AZ.money(v, 0);
    }
    const nx = narrow ? 2 : 5;
    for (let i = 0; i <= nx; i++) {
      const v = xTop * i / nx, x = xs(v);
      mk('line', { x1: x, x2: x, y1: MT, y2: H - MB, stroke: AZ.T.grid, opacity: 0.6 }, gA);
      mk('text', { class: 'bm-ax', x: x, y: H - MB + 14, 'text-anchor': i === 0 ? 'start' : i === nx ? 'end' : 'middle' }, gA).textContent = AZ.int(v);
    }
    mk('text', { class: 'bm-axt', x: W - MR, y: H - 3, 'text-anchor': 'end' }, gA).textContent = narrow ? 'Units in the quarter' : 'Units sold in the quarter';
    mk('text', { class: 'bm-axt', x: ML - 6, y: MT - 1, 'text-anchor': 'start', transform: 'translate(0,0)' }, gA).textContent = '';
    const big = mk('text', { class: 'bm-big', x: ML + 10, y: MT + (narrow ? 34 : 50) }, svg);
    const big2 = mk('text', { class: 'bm-big2', x: ML + 12, y: MT + (narrow ? 48 : 68) }, svg);
    const gF = mk('g', {}, svg), gT = mk('g', {}, svg), gB = mk('g', {}, svg), gL = mk('g', { 'pointer-events': 'none' }, svg);

    // per item elements
    items.forEach((it) => {
      it.trail = mk('path', { fill: 'none', stroke: it.col, 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0.3, 'pointer-events': 'none' }, gT);
      it.tdots = [0, 1, 2, 3].map(() => mk('circle', { r: 2, fill: it.col, opacity: 0, 'pointer-events': 'none' }, gT));
      it.c = mk('circle', { class: 'bm-bub', r: 5, fill: it.col, 'fill-opacity': 0.72, stroke: '#fff', 'stroke-width': 1.5, tabindex: 0, role: 'button', 'aria-label': it.name }, gB);
      it.lb = mk('text', { class: 'bm-lb', 'text-anchor': 'start' }, gL);
    });
    // follow path (all quarters) and the part travelled so far
    const fAll = mk('path', { fill: 'none', 'stroke-width': 1.6, 'stroke-dasharray': '3 3', opacity: 0, 'pointer-events': 'none' }, gF);
    const fNow = mk('path', { fill: 'none', 'stroke-width': 2.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0, 'pointer-events': 'none' }, gF);
    const fDots = mk('g', { 'pointer-events': 'none' }, gF);
    const tip = AZ.tip(el); let hov = null, lastRound = -1, cancelTw = () => {}, timer = 0, cancelFollow = () => {};

    const P = (it, q) => it.pts[q];
    // position of an item at fractional quarter f: {x, y, r, a}
    function at(it, f) {
      const a = Math.floor(f), b = Math.min(last, a + 1), k = f - a, pa = P(it, a), pb = P(it, b);
      if (!pa && !pb) return null;
      if (pa && pb) return { u: AZ.lerp(pa.u, pb.u, k), p: AZ.lerp(pa.p, pb.p, k), s: AZ.lerp(pa.s, pb.s, k), al: 1 };
      return pa ? { u: pa.u, p: pa.p, s: pa.s, al: 1 - k } : { u: pb.u, p: pb.p, s: pb.s, al: k };
    }
    const pathOf = (it, from, to, f) => {
      let d = '';
      for (let q = from; q <= to; q++) { const p = P(it, q); if (!p) continue; d += (d ? 'L' : 'M') + xs(p.u).toFixed(1) + ' ' + ys(p.p).toFixed(1); }
      if (f != null) { const c = at(it, f); if (c) d += (d ? 'L' : 'M') + xs(c.u).toFixed(1) + ' ' + ys(c.p).toFixed(1); }
      return d;
    };

    function draw() {
      const f = fpos, qr = Math.round(f), fl = Math.floor(f);
      const cur = items.map((it) => ({ it, c: at(it, f) }));
      cur.forEach(({ it, c }) => {
        const isF = followed === it.name, dimmed = followed && !isF;
        if (!c) { it.c.setAttribute('opacity', 0); it.c.style.pointerEvents = 'none'; it.trail.setAttribute('opacity', 0); it.tdots.forEach((d) => d.setAttribute('opacity', 0)); return; }
        const cx = xs(c.u), cy = ys(c.p), r = rs(c.s);
        it.c.setAttribute('cx', cx.toFixed(1)); it.c.setAttribute('cy', cy.toFixed(1)); it.c.setAttribute('r', r.toFixed(1));
        it.c.setAttribute('opacity', (c.al * (dimmed ? 0.16 : 1)).toFixed(2)); it.c.style.pointerEvents = c.al < 0.3 ? 'none' : '';
        it.c.setAttribute('stroke-width', isF || hov === it ? 2.4 : 1.5); it.c.setAttribute('stroke', isF || hov === it ? AZ.T.ink : '#fff');
        // trail: the last 4 quarters before the current position
        const from = Math.max(0, fl - 3);
        it.trail.setAttribute('d', dimmed ? '' : pathOf(it, from, fl, f));
        it.trail.setAttribute('opacity', dimmed ? 0 : 0.3 * c.al);
        it.tdots.forEach((d, i) => {
          const q = fl - 3 + i, p = q >= 0 && q <= fl ? P(it, q) : null;
          if (!p || dimmed || q === fl && f - fl < 0.02) { d.setAttribute('opacity', 0); return; }
          d.setAttribute('cx', xs(p.u).toFixed(1)); d.setAttribute('cy', ys(p.p).toFixed(1)); d.setAttribute('opacity', (0.12 + 0.1 * i).toFixed(2) * c.al);
        });
        // label on the largest of the current quarter, the followed and the hovered one
        it.rank = 0;
      });
      const ord = cur.filter((o) => o.c).sort((a, b) => b.c.s - a.c.s);
      ord.forEach((o, i) => { o.it.rank = i; });
      if (qr !== lastRound) { ord.slice().reverse().forEach((o) => gB.appendChild(o.it.c)); }
      const nl = narrow ? 3 : 5;
      cur.forEach(({ it, c }) => {
        const show = c && ((it.rank < nl && !followed) || followed === it.name || hov === it);
        if (!show) { it.lb.setAttribute('opacity', 0); return; }
        const r = rs(c.s), cx = xs(c.u), left = cx + r + 4 + 60 > W - MR;
        it.lb.setAttribute('x', (left ? cx - r - 4 : cx + r + 4).toFixed(1)); it.lb.setAttribute('y', (ys(c.p) + 4).toFixed(1));
        it.lb.setAttribute('text-anchor', left ? 'end' : 'start'); it.lb.textContent = it.name; it.lb.setAttribute('opacity', c.al.toFixed(2));
      });
      // follow layer
      const fi = followed ? items.find((x) => x.name === followed) : null;
      if (fi) {
        fAll.setAttribute('d', pathOf(fi, 0, last)); fAll.setAttribute('stroke', fi.col); fAll.setAttribute('opacity', 0.55);
        fNow.setAttribute('d', pathOf(fi, 0, Math.floor(f), f)); fNow.setAttribute('stroke', fi.col); fNow.setAttribute('opacity', 0.95);
      } else { fAll.setAttribute('opacity', 0); fNow.setAttribute('opacity', 0); }
      if (qr !== lastRound || fi) {
        fDots.innerHTML = '';
        if (fi) fi.pts.forEach((p, q) => {
          if (!p) return;
          const d = new Date(qs[q]), yr = d.getUTCMonth() === 0 || q === 0;
          mk('circle', { cx: xs(p.u).toFixed(1), cy: ys(p.p).toFixed(1), r: 2.6, fill: '#fff', stroke: fi.col, 'stroke-width': 1.5, opacity: q <= f + 0.01 ? 1 : 0.5 }, fDots);
          if (yr && !narrow || q === 0) mk('text', { class: 'bm-yr', x: (xs(p.u) + (q === 0 ? 0 : 5)).toFixed(1), y: (ys(p.p) + (q === 0 ? 14 : -6)).toFixed(1), 'text-anchor': q === 0 ? 'middle' : 'start' }, fDots).textContent = q === 0 ? qLabel(qs[q]) : String(d.getUTCFullYear());
        });
      }
      if (qr !== lastRound) {
        lastRound = qr;
        big.textContent = qLabel(qs[qr]);
        big2.textContent = qr === 0 && firstJune ? 'June only' : '';
        const top = ord[0], tot = qtotal[qr];
        const c0 = top ? P(top.it, qr) : null;
        head.innerHTML = top && c0 ? '<b>' + AZ.esc(top.it.name) + '</b> leads ' + AZ.esc(qLabel(qs[qr])) + ' with ' + AZ.money(c0.s, 1) + ', ' + AZ.pct(tot ? c0.s / tot : 0, 0) + ' of sales, at ' + AZ.money(c0.p, 2) + ' a unit' + (items.length > 1 && w >= 480 ? ' <span>| ' + items.length + ' item types</span>' : '') : 'No sales in ' + AZ.esc(qLabel(qs[qr]));
        qEl.textContent = qLabel(qs[qr]);
      }
      sl.value = String(qr);
      btn.textContent = playing ? 'Pause' : 'Play';
      btn.setAttribute('aria-label', playing ? 'Pause' : (Math.round(fpos) >= last ? 'Play again from the first quarter' : 'Play'));
    }

    // motion: one tween per step between quarters
    function goTo(target, ms, then) {
      cancelTw();
      const from = fpos;
      cancelTw = AZ.tween(ms, (e) => { fpos = AZ.lerp(from, target, e); draw(); }, () => { fpos = target; draw(); if (then) then(); }, AZ.EASE.inOut);
    }
    function stepPlay() {
      if (!playing) return;
      if (Math.round(fpos) >= last) { playing = false; draw(); return; }
      goTo(Math.round(fpos) + 1, 620, () => { timer = setTimeout(stepPlay, AZ.reduced() ? 600 : 0); });
    }
    btn.addEventListener('click', () => {
      if (playing) { playing = false; cancelTw(); clearTimeout(timer); fpos = Math.round(fpos); draw(); return; }
      if (Math.round(fpos) >= last) { fpos = 0; }
      playing = true; draw(); stepPlay();
    });
    sl.addEventListener('input', () => { playing = false; clearTimeout(timer); goTo(Number(sl.value), 380); });

    // hover + follow
    const info = (it, e) => {
      const q = Math.round(fpos), p = P(it, q), b = el.getBoundingClientRect();
      if (!p) return tip.hide();
      tip.show('<b>' + AZ.esc(it.name) + '</b>' + AZ.row(qLabel(qs[q]) + ' sales', AZ.money(p.s, 2)) + AZ.row('Units', AZ.int(p.u)) + AZ.row('Price per unit', AZ.money(p.p, 2))
        + AZ.row('Share of sales', AZ.pct(qtotal[q] ? p.s / qtotal[q] : 0, 1)) + (followed === it.name ? AZ.row('Following', 'click to release') : AZ.row('Follow', 'click')), e.clientX - b.left, e.clientY - b.top);
    };
    const follow = (it) => {
      followed = followed === it.name ? null : it.name; lastRound = -1;
      cancelFollow();
      draw();
      if (followed) { cancelFollow = AZ.tween(600, (e) => { const len = fAll.getTotalLength ? fNow.getTotalLength() : 0; fNow.setAttribute('stroke-dasharray', (len * e) + ' ' + (len + 1)); }, () => fNow.removeAttribute('stroke-dasharray'), AZ.EASE.out); }
    };
    items.forEach((it) => {
      it.c.addEventListener('mousemove', (e) => { hov = it; info(it, e); draw(); });
      it.c.addEventListener('mouseleave', () => { hov = null; tip.hide(); draw(); });
      it.c.addEventListener('click', () => follow(it));
      it.c.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); follow(it); } });
      it.c.addEventListener('focus', () => { const b = it.c.getBoundingClientRect(), a = el.getBoundingClientRect(); hov = it; info(it, { clientX: b.left + b.width / 2, clientY: b.top }); });
      it.c.addEventListener('blur', () => { hov = null; tip.hide(); });
    });
    const onKey = (e) => { if (e.key === 'Escape' && followed) { followed = null; lastRound = -1; draw(); } };
    window.addEventListener('keydown', onKey);
    svg.addEventListener('click', (e) => { if (e.target === svg && followed) { followed = null; lastRound = -1; draw(); } });

    draw();
    if (playing) stepPlay();
    return () => { cancelTw(); cancelFollow(); clearTimeout(timer); window.removeEventListener('keydown', onKey); };
  }
});
