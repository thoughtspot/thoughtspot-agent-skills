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


// Search: [sales] [region] [item type]
// Chord diagram: 5 regions (slate arcs, right) against the 5 product families (family hues, left).
// Click a family arc to open its item types in place of the family (arcs and ribbons morph, 450 ms).
// Family is an editorial grouping (AZ.familyOf), not a model column.
const D3 = ['https://cdn.jsdelivr.net/npm/d3@7', 'https://unpkg.com/d3@7'];
const FAMS = ['Outerwear', 'Tops and dresses', 'Bottoms', 'Swim and basics', 'Accessories'];
const SVGNS = 'http://www.w3.org/2000/svg';
let focusFam = null; // family name the chart is opened into; survives redraw

const mk = (tag, attrs, parent) => { const n = document.createElementNS(SVGNS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; };
function tint(hex, k) {
  const n = parseInt(hex.slice(1), 16);
  return 'rgb(' + [n >> 16 & 255, n >> 8 & 255, n & 255].map((v) => Math.round(v + (255 - v) * k)).join(',') + ')';
}
function wrapName(s, maxc) {
  if (s.length <= maxc) return [s];
  const i = s.lastIndexOf(' ', maxc), j = s.indexOf(' ');
  const cut = i > 2 ? i : j > 0 ? j : -1;
  if (cut < 0) return [s.slice(0, Math.max(3, maxc - 2)) + '..'];
  const a = s.slice(0, cut), b = s.slice(cut + 1);
  return [a, b.length > maxc ? b.slice(0, Math.max(3, maxc - 2)) + '..' : b];
}

AZ.boot({
  need: 'sales by region and item type, e.g. [sales] [region] [item type]',
  render: async ({ el, rows, schema }) => {
    const rK = AZ.col(schema, /region/i), iK = AZ.col(schema, /item/i), sK = AZ.col(schema, /sales/i);
    const R = rows.map((r) => ({ reg: String(r[rK]), item: String(r[iK]), v: AZ.num(r[sK]) })).filter((r) => r.v > 0);
    if (!R.length) { AZ.paint(el, '<div class="az-empty"><b>No sales to draw</b><span>The current filter leaves no region and item type pairs. Widen the filters, or the search needs: [sales] [region] [item type].</span></div>'); return; }
    await AZ.loadScript(D3, () => !!window.d3, 8000);

    const total = R.reduce((a, r) => a + r.v, 0);
    const famTot = new Map(); R.forEach((r) => famTot.set(AZ.familyOf(r.item), (famTot.get(AZ.familyOf(r.item)) || 0) + r.v));
    if (focusFam && !famTot.has(focusFam)) focusFam = null;

    el.innerHTML = '<div class="ch-head"><p class="ch-lead"></p></div><div class="ch-bar"><button type="button" class="ch-back" aria-label="Back to all families">Back</button><div class="ch-crumbs"></div></div><div class="ch-plot"></div>';
    const leadEl = el.querySelector('.ch-lead'), backEl = el.querySelector('.ch-back'), crumbsEl = el.querySelector('.ch-crumbs'), plot = el.querySelector('.ch-plot');

    // ---- state: groups (arcs) and ribbons for a focus ------------------------
    function build(fam) {
      const sub = fam ? R.filter((r) => AZ.familyOf(r.item) === fam) : R;
      const regT = new Map(), colT = new Map(), cell = new Map();
      sub.forEach((r) => {
        const c = fam ? r.item : AZ.familyOf(r.item);
        regT.set(r.reg, (regT.get(r.reg) || 0) + r.v); colT.set(c, (colT.get(c) || 0) + r.v);
        cell.set(r.reg + '>' + c, (cell.get(r.reg + '>' + c) || 0) + r.v);
      });
      const regs = Array.from(regT.keys()).sort((a, b) => regT.get(b) - regT.get(a));
      const cols = fam ? Array.from(colT.keys()).sort((a, b) => colT.get(b) - colT.get(a)) : FAMS.filter((f) => colT.has(f));
      const n = regs.length + cols.length, M = [];
      for (let i = 0; i < n; i++) M.push(new Array(n).fill(0));
      regs.forEach((r, i) => cols.forEach((c, j) => { const v = cell.get(r + '>' + c) || 0; M[i][regs.length + j] = v; M[regs.length + j][i] = v; }));
      const ch = d3.chord().padAngle(n > 2 ? 0.05 : 0.2).sortSubgroups(d3.descending)(M);
      const groups = new Map(), rib = new Map();
      regs.forEach((r, i) => groups.set('r:' + r, { id: 'r:' + r, name: r, val: regT.get(r), a0: ch.groups[i].startAngle, a1: ch.groups[i].endAngle, color: AZ.T.slate[Math.min(6, 4 + Math.floor(i / 2))], kind: 'r' }));
      cols.forEach((c, j) => {
        const g = ch.groups[regs.length + j];
        const color = fam ? tint(AZ.T.family[fam], Math.min(0.6, j * 0.18)) : AZ.T.family[c];
        groups.set((fam ? 'i:' : 'f:') + c, { id: (fam ? 'i:' : 'f:') + c, name: c, val: colT.get(c), a0: g.startAngle, a1: g.endAngle, color, kind: 'c' });
      });
      ch.forEach((c) => {
        let s = c.source, t = c.target;
        if (s.index >= regs.length) { const x = s; s = t; t = x; }
        if (s.index >= regs.length || t.index < regs.length) return;
        const rn = regs[s.index], cn = cols[t.index - regs.length], cid = (fam ? 'i:' : 'f:') + cn;
        const v = cell.get(rn + '>' + cn) || 0; if (v <= 0) return;
        rib.set('r:' + rn + '>' + cid, { key: 'r:' + rn + '>' + cid, rid: 'r:' + rn, cid, rn, cn, v, s0: s.startAngle, s1: s.endAngle, t0: t.startAngle, t1: t.endAngle, color: groups.get(cid).color });
      });
      return { fam, groups, rib, total: sub.reduce((a, r) => a + r.v, 0), regT, colT };
    }
    const parentKey = (id) => (id.slice(0, 2) === 'i:' ? 'f:' + AZ.familyOf(id.slice(2)) : null);
    const collapse = (S) => {
      const groups = new Map(), rib = new Map();
      S.groups.forEach((g, k) => groups.set(k, Object.assign({}, g, { a1: g.a0 })));
      S.rib.forEach((r, k) => rib.set(k, Object.assign({}, r, { s1: r.s0, t1: r.t0 })));
      return Object.assign({}, S, { groups, rib });
    };
    function plan(from, to) {
      const gi = [], ri = [];
      const gids = new Set([...from.groups.keys(), ...to.groups.keys()]);
      const geo = (S, id) => {
        if (S.groups.has(id)) return { g: S.groups.get(id), on: 1 };
        const p = parentKey(id); if (p && S.groups.has(p)) return { g: S.groups.get(p), on: 0 };
        // a family that becomes item types: span of its children in S
        let a0 = Infinity, a1 = -Infinity, base = null;
        S.groups.forEach((g, k) => { if (parentKey(k) === id) { a0 = Math.min(a0, g.a0); a1 = Math.max(a1, g.a1); base = g; } });
        return a0 < Infinity ? { g: Object.assign({}, base, { a0, a1 }), on: 0 } : null;
      };
      gids.forEach((id) => {
        const A = geo(from, id), B = geo(to, id);
        gi.push({ id, a: (A || B).g, b: (B || A).g, oa: A ? A.on : 0, ob: B ? B.on : 0, src: (B || A).g });
      });
      const rk = new Set([...from.rib.keys(), ...to.rib.keys()]);
      rk.forEach((key) => {
        let A = from.rib.get(key), B = to.rib.get(key), oa = A ? 1 : 0, ob = B ? 1 : 0;
        if (!A) { const p = key.replace(/>i:.*$/, function () { return '>f:' + AZ.familyOf(key.split('>i:')[1]); }); if (key.indexOf('>i:') > 0 && from.rib.has(p)) { A = from.rib.get(p); } else A = B; }
        if (!B) { const p = key.replace(/>i:.*$/, function () { return '>f:' + AZ.familyOf(key.split('>i:')[1]); }); if (key.indexOf('>i:') > 0 && to.rib.has(p)) { B = to.rib.get(p); } else B = A; }
        ri.push({ key, a: A, b: B, oa, ob, src: B === to.rib.get(key) ? to.rib.get(key) : from.rib.get(key) });
      });
      return { gi, ri };
    }

    // ---- geometry ----------------------------------------------------------------
    const pw = Math.max(200, plot.clientWidth), ph = Math.max(160, plot.clientHeight);
    const Lm = Math.min(96, Math.round(pw * 0.27)), Rm = Math.min(64, Math.round(pw * 0.17));
    const ro = Math.max(40, Math.min((pw - Lm - Rm) / 2, ph / 2 - 26)), ri0 = ro - Math.max(9, Math.round(ro * 0.11));
    const cx = Lm + (pw - Lm - Rm) / 2, cy = ph / 2;
    const svg = mk('svg', { width: pw, height: ph, viewBox: '0 0 ' + pw + ' ' + ph, class: 'ch-svg' }, plot);
    const bg = mk('rect', { x: 0, y: 0, width: pw, height: ph, fill: 'transparent' }, svg);
    const root = mk('g', { transform: 'translate(' + cx + ',' + cy + ')' }, svg);
    const ribG = mk('g', {}, root), arcG = mk('g', {}, root), labG = mk('g', {}, svg);
    const hub = mk('circle', { cx: cx, cy: cy, r: Math.max(26, Math.min(40, ri0 * 0.4)), fill: '#FFFFFF', 'fill-opacity': 0.92, 'pointer-events': 'none' }, svg);
    const cT = mk('text', { class: 'ch-c1', x: cx, y: cy + 2, 'text-anchor': 'middle' }, svg), cS = mk('text', { class: 'ch-c2', x: cx, y: cy + 17, 'text-anchor': 'middle' }, svg);
    const arcGen = d3.arc().innerRadius(ri0).outerRadius(ro), ribGen = d3.ribbon().radius(ri0 - 2);
    const tip = AZ.tip(plot);
    const gEls = new Map(), rEls = new Map(), cancels = [];
    let cur = null, animating = false, hover = null, settled = null;
    const maxc = Math.floor((Lm - 8) / 6.3);

    const arcEl = (id, src) => {
      let e = gEls.get(id); if (e) return e;
      const p = mk('path', { fill: src.color, tabindex: -1 }, arcG);
      const t = mk('text', { class: 'ch-lab' }, labG);
      e = { p, t, id }; gEls.set(id, e);
      p.addEventListener('mouseenter', (ev) => { if (!animating) { hover = { k: 'g', id }; repaint(); showTip(ev); } });
      p.addEventListener('mousemove', (ev) => { if (!animating && hover && hover.id === id) showTip(ev); });
      p.addEventListener('mouseleave', () => { hover = null; repaint(); tip.hide(); });
      p.addEventListener('click', () => { if (!animating && id.slice(0, 2) === 'f:') openFam(id.slice(2)); });
      p.addEventListener('keydown', (ev) => { if ((ev.key === 'Enter' || ev.key === ' ') && !animating && id.slice(0, 2) === 'f:') { ev.preventDefault(); openFam(id.slice(2)); } });
      return e;
    };
    const ribEl = (key) => {
      let e = rEls.get(key); if (e) return e;
      const p = mk('path', { 'fill-opacity': 0.5 }, ribG); e = { p, key }; rEls.set(key, e);
      p.addEventListener('mouseenter', (ev) => { if (!animating) { hover = { k: 'r', id: key }; repaint(); showTip(ev); } });
      p.addEventListener('mousemove', (ev) => { if (!animating && hover && hover.id === key) showTip(ev); });
      p.addEventListener('mouseleave', () => { hover = null; repaint(); tip.hide(); });
      return e;
    };
    const dimOf = (kind, id, obj) => {
      if (!hover) return 1;
      if (hover.k === 'r') { const r = cur.rib.get(hover.id); if (!r) return 1; return kind === 'r' ? (id === hover.id ? 1 : 0.12) : (id === r.rid || id === r.cid ? 1 : 0.3); }
      if (kind === 'r') return obj.rid === hover.id || obj.cid === hover.id ? 1 : 0.1;
      if (id === hover.id) return 1;
      let linked = false; cur.rib.forEach((r) => { if ((r.rid === hover.id && r.cid === id) || (r.cid === hover.id && r.rid === id)) linked = true; });
      return linked ? 1 : 0.3;
    };
    function paintPlan(P, k, labelFade) {
      P.ri.forEach((it) => {
        const e = ribEl(it.key), lerp = AZ.lerp, a = it.a, b = it.b;
        const s = { startAngle: lerp(a.s0, b.s0, k), endAngle: lerp(a.s1, b.s1, k) }, t = { startAngle: lerp(a.t0, b.t0, k), endAngle: lerp(a.t1, b.t1, k) };
        const op = lerp(it.oa, it.ob, k);
        e.p.setAttribute('d', ribGen({ source: s, target: t }));
        e.p.setAttribute('fill', it.src.color);
        e.p.style.opacity = op * (settled ? dimOf('r', it.key, it.src) : 1);
        e.p.style.display = op < 0.01 ? 'none' : '';
        e.p.style.pointerEvents = op < 0.6 ? 'none' : '';
      });
      P.gi.forEach((it) => {
        const e = arcEl(it.id, it.src), lerp = AZ.lerp;
        const a0 = lerp(it.a.a0, it.b.a0, k), a1 = lerp(it.a.a1, it.b.a1, k), op = lerp(it.oa, it.ob, k);
        e.p.setAttribute('d', arcGen({ startAngle: a0, endAngle: a1 }));
        e.p.setAttribute('fill', it.src.color);
        const dm = settled ? dimOf('g', it.id) : 1;
        e.p.style.opacity = op * dm; e.p.style.display = op < 0.01 ? 'none' : '';
        e.p.style.pointerEvents = op < 0.6 ? 'none' : '';
        // label at the mid angle
        const mid = (a0 + a1) / 2, sn = Math.sin(mid), cs = Math.cos(mid), g = it.src;
        const rr = ro + 8, px = cx + rr * sn, py = cy - rr * cs;
        const nm = wrapName(g.name, maxc), lines = nm.length + 1;
        const anchor = Math.abs(sn) < 0.28 ? 'middle' : sn > 0 ? 'start' : 'end';
        const y0 = py + 4 - (lines - 1) * 6.5 - cs * lines * 6.5 * (Math.abs(sn) < 0.28 ? 1 : 0.3);
        e.t.setAttribute('text-anchor', anchor);
        e.t.setAttribute('x', px); e.t.setAttribute('y', y0);
        let html = '';
        nm.forEach((ln, i) => { html += '<tspan x="' + px.toFixed(1) + '"' + (i ? ' dy="12.5"' : '') + ' class="ch-ln">' + AZ.esc(ln) + '</tspan>'; });
        html += '<tspan x="' + px.toFixed(1) + '" dy="12.5" class="ch-lv">' + AZ.money(g.val, 1) + '</tspan>';
        e.t.innerHTML = html;
        e.t.style.opacity = op * (labelFade == null ? 1 : labelFade(k)) * (settled ? Math.min(1, dm + 0.15) : 1);
        e.t.style.display = op < 0.01 ? 'none' : '';
      });
    }
    function repaint() { if (settled) paintPlan(settled, 1); }
    function settle(S) {
      cur = S;
      const P = plan(S, S);
      gEls.forEach((e, id) => { if (!S.groups.has(id)) { e.p.remove(); e.t.remove(); gEls.delete(id); } });
      rEls.forEach((e, key) => { if (!S.rib.has(key)) { e.p.remove(); rEls.delete(key); } });
      settled = P; paintPlan(P, 1);
      gEls.forEach((e, id) => {
        const can = id.slice(0, 2) === 'f:';
        e.p.style.cursor = can ? 'pointer' : 'default';
        e.p.setAttribute('tabindex', can ? '0' : '-1'); e.p.setAttribute('role', can ? 'button' : 'img');
        e.p.setAttribute('aria-label', S.groups.get(id).name + ', ' + AZ.money(S.groups.get(id).val, 1) + (can ? ', press Enter to open its item types' : ''));
      });
    }
    function showTip(ev) {
      const pr = plot.getBoundingClientRect(); let h = '';
      if (hover.k === 'r') {
        const r = cur.rib.get(hover.id); if (!r) return;
        h = '<b>' + AZ.esc(r.rn + ' to ' + r.cn) + '</b>' + AZ.row('Sales', AZ.money(r.v, 1), r.color) + AZ.row('Share of ' + r.rn, AZ.pct(r.v / cur.regT.get(r.rn), 1)) + AZ.row('Share of ' + r.cn, AZ.pct(r.v / cur.colT.get(r.cn), 1)) + AZ.row('Share of ' + (cur.fam || 'all') + ' sales', AZ.pct(r.v / cur.total, 1));
      } else {
        const g = cur.groups.get(hover.id); if (!g) return;
        let best = null; cur.rib.forEach((r) => { if ((r.rid === g.id || r.cid === g.id) && (!best || r.v > best.v)) best = r; });
        h = '<b>' + AZ.esc(g.name) + '</b>' + AZ.row('Sales', AZ.money(g.val, 1), g.kind === 'c' ? g.color : null) + AZ.row('Share of ' + (cur.fam || 'all') + ' sales', AZ.pct(g.val / cur.total, 1));
        if (best) h += AZ.row('Largest flow', (g.kind === 'r' ? best.cn : best.rn) + ' ' + AZ.pct(best.v / g.val, 0));
        if (g.id.slice(0, 2) === 'f:') h += '<div class="ch-tipnote">Click to open item types</div>';
      }
      tip.show(h, ev.clientX - pr.left, ev.clientY - pr.top);
    }

    // ---- header and drill --------------------------------------------------------
    let shown = 0;
    function header(S, animate) {
      const rs = Array.from(S.regT.entries()).sort((a, b) => b[1] - a[1]), cs = Array.from(S.colT.entries()).sort((a, b) => b[1] - a[1]);
      let top = null; S.rib.forEach((r) => { if (!top || r.v > top.v) top = r; });
      leadEl.textContent = S.fam
        ? S.fam + ': ' + cs[0][0] + ' is ' + AZ.pct(cs[0][1] / S.total, 0) + ' of it, strongest in ' + (function () { let b = null; S.rib.forEach((r) => { if (r.cn === cs[0][0] && (!b || r.v > b.v)) b = r; }); return b ? b.rn : rs[0][0]; })()
        : 'Biggest flow: ' + top.rn + ' to ' + top.cn + ', ' + AZ.pct(top.v / S.total, 1) + ' of sales';
      crumbsEl.innerHTML = S.fam ? AZ.crumbs(['All sales', S.fam]) : '<span class="ch-hint">Click a family arc to open its item types</span>';
      AZ.wireCrumbs(crumbsEl, () => closeFam());
      backEl.style.visibility = S.fam ? 'visible' : 'hidden';
      cS.textContent = S.fam ? S.fam : 'total sales';
      if (animate) cancels.push(AZ.countUp(cT, S.total, (n) => AZ.money(n, 1), 450, shown)); else cT.textContent = AZ.money(S.total, 1);
      shown = S.total;
    }
    function goTo(fam) {
      if (animating || fam === cur.fam) return;
      const to = build(fam), from = cur; focusFam = fam;
      hover = null; tip.hide(); settled = null; animating = true;
      header(to, true);
      const P = plan(from, to);
      P.gi.forEach((it) => arcEl(it.id, it.src)); P.ri.forEach((it) => ribEl(it.key));
      cancels.push(AZ.tween(450, (k) => paintPlan(P, k), () => { animating = false; settle(to); }, AZ.EASE.inOut));
    }
    const openFam = (f) => goTo(f), closeFam = () => goTo(null);
    backEl.addEventListener('click', closeFam);
    bg.addEventListener('click', () => { if (cur.fam) closeFam(); });
    const onKey = (e) => { if (e.key === 'Escape' && cur && cur.fam) closeFam(); };
    window.addEventListener('keydown', onKey);

    // ---- first paint: arcs and ribbons sweep in --------------------------------------
    const S0 = build(focusFam);
    cur = S0; header(S0, false);
    const P0 = plan(collapse(S0), S0);
    animating = true; settled = null;
    P0.gi.forEach((it) => arcEl(it.id, it.src)); P0.ri.forEach((it) => ribEl(it.key));
    cancels.push(AZ.tween(650, (k) => paintPlan(P0, k, (x) => Math.max(0, (x - 0.55) / 0.45)), () => { animating = false; settle(S0); }, AZ.EASE.out));
    return () => { cancels.forEach((c) => c()); window.removeEventListener('keydown', onKey); };
  }
});
