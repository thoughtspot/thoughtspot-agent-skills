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
// Marimekko: column width is the region's sales, each column is split into the five family shares (100 percent).
// Click a column: it widens to the full tile and its families split into item types (animated, 450 ms).
// Family is an editorial grouping (AZ.familyOf), not a model column. Pure SVG, no library.
const FAMS = ['Outerwear', 'Tops and dresses', 'Bottoms', 'Swim and basics', 'Accessories'];
const SVGNS = 'http://www.w3.org/2000/svg';
let focusReg = null; // region the chart is opened into; survives redraw

const mk = (tag, attrs, parent) => { const n = document.createElementNS(SVGNS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; };
function tintHex(hex, k) {
  const n = parseInt(hex.slice(1), 16), c = [n >> 16 & 255, n >> 8 & 255, n & 255].map((v) => Math.round(v + (255 - v) * k));
  return { css: 'rgb(' + c.join(',') + ')', lum: (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255 };
}
const trunc = (s, n) => (n < 3 ? '' : s.length <= n ? s : s.slice(0, Math.max(1, n - 2)) + '..');

AZ.boot({
  need: 'sales by region and item type, e.g. [sales] [region] [item type]',
  render: async ({ el, rows, schema }) => {
    const rK = AZ.col(schema, /region/i), iK = AZ.col(schema, /item/i), sK = AZ.col(schema, /sales/i);
    const R = rows.map((r) => ({ reg: String(r[rK]), item: String(r[iK]), v: AZ.num(r[sK]) })).filter((r) => r.v > 0);
    if (!R.length) { AZ.paint(el, '<div class="az-empty"><b>No sales to draw</b><span>The current filter leaves no region and item type pairs. Widen the filters, or the search needs: [sales] [region] [item type].</span></div>'); return; }

    const total = R.reduce((a, r) => a + r.v, 0);
    const regT = new Map(), famAll = new Map(), cell = new Map(), itemCell = new Map();
    R.forEach((r) => {
      const f = AZ.familyOf(r.item);
      regT.set(r.reg, (regT.get(r.reg) || 0) + r.v); famAll.set(f, (famAll.get(f) || 0) + r.v);
      cell.set(r.reg + '|' + f, (cell.get(r.reg + '|' + f) || 0) + r.v);
      itemCell.set(r.reg + '|' + r.item, (itemCell.get(r.reg + '|' + r.item) || 0) + r.v);
    });
    const regs = Array.from(regT.keys()).sort((a, b) => regT.get(b) - regT.get(a));
    if (focusReg && !regT.has(focusReg)) focusReg = null;

    el.innerHTML = '<div class="mm-head"><p class="mm-lead"></p></div><div class="mm-bar"><button type="button" class="mm-back" aria-label="Back to all regions">Back</button><div class="mm-crumbs"></div><div class="mm-val"><b></b><span></span></div></div><div class="mm-plot"></div><p class="mm-foot"></p>';
    const leadEl = el.querySelector('.mm-lead'), backEl = el.querySelector('.mm-back'), crumbsEl = el.querySelector('.mm-crumbs');
    const valB = el.querySelector('.mm-val b'), valS = el.querySelector('.mm-val span'), plot = el.querySelector('.mm-plot'), foot = el.querySelector('.mm-foot');
    foot.textContent = 'Width is a region\'s share of sales; height is each family\'s share of that region.';
    leadEl.textContent = 'x';
    const W = Math.max(200, plot.clientWidth), H = Math.max(140, plot.clientHeight);
    const ML = 36, MT = 32, PW = W - ML, PH = H - MT - 2, GAP = 3;
    const svg = mk('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, class: 'mm-svg' }, plot);
    [0, 0.5, 1].forEach((p) => {
      const y = MT + PH * (1 - p);
      mk('line', { x1: ML, x2: W, y1: y, y2: y, stroke: AZ.T.grid, 'stroke-width': 1 }, svg);
      const t = mk('text', { x: ML - 5, y: y + (p === 1 ? 9 : p === 0 ? 0 : 4), 'text-anchor': 'end', class: 'mm-ax' }, svg); t.textContent = Math.round(p * 100) + '%';
    });
    const segG = mk('g', {}, svg), hdG = mk('g', {}, svg), tip = AZ.tip(plot);

    // ---- layout ----------------------------------------------------------------
    function build(reg) {
      const cols = reg ? [reg] : regs, sum = cols.reduce((a, r) => a + regT.get(r), 0);
      const avail = PW - GAP * (cols.length - 1);
      const segs = new Map(), heads = new Map();
      let x = ML;
      cols.forEach((r, ci) => {
        const w = avail * regT.get(r) / sum;
        heads.set('h:' + r, { id: 'h:' + r, reg: r, x, w, ci });
        let y = MT;
        const list = [];
        if (!reg) FAMS.forEach((f) => { const v = cell.get(r + '|' + f); if (v) list.push({ id: r + '|f:' + f, name: f, fam: f, v, tint: 0, item: false }); });
        else FAMS.forEach((f) => {
          const its = Array.from(itemCell.keys()).filter((k) => k.indexOf(r + '|') === 0).map((k) => k.slice(r.length + 1)).filter((it) => AZ.familyOf(it) === f).sort((a, b) => itemCell.get(r + '|' + b) - itemCell.get(r + '|' + a));
          its.forEach((it, i) => list.push({ id: r + '|i:' + it, name: it, fam: f, v: itemCell.get(r + '|' + it), tint: Math.min(0.55, i * 0.2), item: true }));
        });
        list.forEach((s) => {
          const h = PH * s.v / regT.get(r);
          segs.set(s.id, { id: s.id, reg: r, name: s.name, fam: s.fam, v: s.v, item: s.item, tint: s.tint, x, y, w, h, ci });
          y += h;
        });
        x += w + GAP;
      });
      return { reg, segs, heads, sum };
    }
    const parentId = (id) => { const p = id.split('|'); return p[1].slice(0, 2) === 'i:' ? p[0] + '|f:' + AZ.familyOf(p[1].slice(2)) : null; };
    function segLabel(s) {
      if (s.w < 30 || s.h < 15) return null;
      if (s.w >= 140 && s.h < 32) return { t1: trunc(s.name, Math.floor((s.w - 12) / 6.3)) + '  ' + AZ.pct(s.v / regT.get(s.reg), 0), t2: '' };
      const share = AZ.pct(s.v / regT.get(s.reg), 0);
      if (s.h >= 32 && s.w >= 62) return { t1: trunc(s.name, Math.floor((s.w - 10) / 6.3)), t2: share + (s.h >= 46 && s.w >= 90 ? '  ' + AZ.money(s.v, 1) : '') };
      return { t1: share, t2: '' };
    }
    function plan(from, to, delayed) {
      const segs = [], heads = [];
      const gs = (S, id) => {
        if (S.segs.has(id)) return { r: S.segs.get(id), on: 1 };
        const p = parentId(id); if (p && S.segs.has(p)) return { r: S.segs.get(p), on: 0 };
        let u = null; S.segs.forEach((g, k) => { if (parentId(k) === id) u = u ? { x: g.x, w: g.w, y: Math.min(u.y, g.y), y1: Math.max(u.y1, g.y + g.h), g } : { x: g.x, w: g.w, y: g.y, y1: g.y + g.h, g }; });
        return u ? { r: { x: u.x, w: u.w, y: u.y, h: u.y1 - u.y }, on: 0 } : null;
      };
      new Set([...from.segs.keys(), ...to.segs.keys()]).forEach((id) => {
        const A = gs(from, id), B = gs(to, id), src = to.segs.get(id) || from.segs.get(id);
        const ra = (A || B).r, rb = (B || A).r;
        segs.push({ id, a: { x: ra.x, y: ra.y, w: ra.w, h: ra.h }, b: { x: rb.x, y: rb.y, w: rb.w, h: rb.h }, oa: A ? A.on : 0, ob: B ? B.on : 0, src, la: from.segs.has(id) ? segLabel(from.segs.get(id)) : null, lb: to.segs.has(id) ? segLabel(to.segs.get(id)) : null });
      });
      new Set([...from.heads.keys(), ...to.heads.keys()]).forEach((id) => {
        const A = from.heads.get(id), B = to.heads.get(id);
        heads.push({ id, a: A || B, b: B || A, oa: A ? 1 : 0, ob: B ? 1 : 0, src: B || A });
      });
      return { segs, heads, delayed: !!delayed };
    }

    // ---- drawing ---------------------------------------------------------------
    const sEls = new Map(), hEls = new Map(), cancels = [];
    let cur = null, settled = null, hoverId = null, animating = false;
    function segEl(id, src) {
      let e = sEls.get(id); if (e) return e;
      const t = tintHex(AZ.T.family[src.fam] || AZ.T.muted, src.tint), dark = t.lum < 0.6;
      const g = mk('g', { class: 'mm-s' }, segG);
      const rect = mk('rect', { fill: t.css, stroke: '#FFFFFF', 'stroke-width': 1.5 }, g);
      const t1 = mk('text', { class: 'mm-t1', fill: dark ? '#FFFFFF' : AZ.T.ink }, g), t2 = mk('text', { class: 'mm-t2', fill: dark ? '#FFFFFF' : AZ.T.ink2 }, g);
      e = { g, rect, t1, t2, id }; sEls.set(id, e);
      g.addEventListener('mouseenter', (ev) => { if (!animating) { hoverId = id; repaint(); showTip(ev); } });
      g.addEventListener('mousemove', (ev) => { if (!animating && hoverId === id) showTip(ev); });
      g.addEventListener('mouseleave', () => { hoverId = null; repaint(); tip.hide(); });
      g.addEventListener('click', () => { if (!animating && !cur.reg) openReg(src.reg); });
      rect.addEventListener('keydown', (ev) => { if ((ev.key === 'Enter' || ev.key === ' ') && !animating && !cur.reg) { ev.preventDefault(); openReg(src.reg); } });
      return e;
    }
    function hdEl(id) {
      let e = hEls.get(id); if (e) return e;
      const t = mk('text', { class: 'mm-h1' }, hdG), t2 = mk('text', { class: 'mm-h2' }, hdG);
      e = { t, t2 }; hEls.set(id, e); return e;
    }
    function paintPlan(P, k) {
      const gk = (delay) => { const d = Math.max(0, Math.min(1, (k - delay) / (1 - delay))); return AZ.EASE.out(d); };
      P.segs.forEach((it) => {
        const e = segEl(it.id, it.src), kk = P.delayed ? gk(0.3 * (it.src.ci / Math.max(1, regs.length - 1))) : k, L = AZ.lerp;
        const x = L(it.a.x, it.b.x, kk), w = L(it.a.w, it.b.w, kk), h = L(it.a.h, it.b.h, kk), y = L(it.a.y, it.b.y, kk);
        const op = L(it.oa, it.ob, kk) * (settled && hoverId && hoverId !== it.id ? 0.3 : 1);
        e.g.style.display = op < 0.01 ? 'none' : ''; e.g.style.opacity = op;
        e.rect.setAttribute('x', x); e.rect.setAttribute('y', y); e.rect.setAttribute('width', Math.max(0, w)); e.rect.setAttribute('height', Math.max(0, h));
        const lab = it.lb || it.la, lo = L(it.la ? 1 : 0, it.lb ? 1 : 0, kk) * (P.delayed ? Math.max(0, (kk - 0.6) / 0.4) : 1);
        if (lab && lo > 0.01) {
          e.t1.style.display = ''; e.t1.style.opacity = lo; e.t1.textContent = lab.t1; e.t1.setAttribute('x', x + 6); e.t1.setAttribute('y', y + Math.min(14, h / 2 + 4));
          if (lab.t2) { e.t2.style.display = ''; e.t2.style.opacity = lo; e.t2.textContent = lab.t2; e.t2.setAttribute('x', x + 6); e.t2.setAttribute('y', y + 27); } else e.t2.style.display = 'none';
        } else { e.t1.style.display = 'none'; e.t2.style.display = 'none'; }
      });
      P.heads.forEach((it) => {
        const e = hdEl(it.id), L = AZ.lerp, kk = P.delayed ? gk(0.3 * (it.src.ci / Math.max(1, regs.length - 1))) : k;
        const x = L(it.a.x, it.b.x, kk), w = L(it.a.w, it.b.w, kk), op = L(it.oa, it.ob, kk) * (P.delayed ? Math.max(0, (kk - 0.4) / 0.6) : 1);
        const r = it.src.reg, one = it.b.w >= PW - 4;
        e.t.style.display = op < 0.01 ? 'none' : ''; e.t2.style.display = op < 0.01 || w < 64 ? 'none' : '';
        e.t.style.opacity = op; e.t2.style.opacity = op;
        const cx = one ? x + 2 : x + 2;
        e.t.setAttribute('x', cx); e.t.setAttribute('y', MT - 16); e.t.textContent = trunc(r, Math.floor((w - 4) / 6.9));
        e.t2.setAttribute('x', cx); e.t2.setAttribute('y', MT - 4); e.t2.textContent = AZ.pct(regT.get(r) / total, 0) + ' of sales';
      });
    }
    function repaint() { if (settled) paintPlan(settled, 1); }
    function settle(S) {
      cur = S; const P = plan(S, S); settled = P;
      sEls.forEach((e, id) => { if (!S.segs.has(id)) { e.g.remove(); sEls.delete(id); } });
      hEls.forEach((e, id) => { if (!S.heads.has(id)) { e.t.remove(); e.t2.remove(); hEls.delete(id); } });
      P.segs.forEach((it) => { const e = segEl(it.id, it.src); segG.appendChild(e.g); });
      paintPlan(P, 1);
      P.segs.forEach((it) => {
        const e = sEls.get(it.id), can = !S.reg;
        e.g.style.cursor = can ? 'pointer' : 'default';
        e.rect.setAttribute('tabindex', can ? '0' : '-1'); e.rect.setAttribute('role', can ? 'button' : 'img');
        e.rect.setAttribute('aria-label', it.src.reg + ', ' + it.src.name + ', ' + AZ.money(it.src.v, 1) + (can ? ', press Enter to open the region' : ''));
      });
    }
    function showTip(ev) {
      const s = cur.segs.get(hoverId); if (!s) return;
      const pr = plot.getBoundingClientRect(), col = regT.get(s.reg);
      let h = '<b>' + AZ.esc(s.reg + ', ' + s.name) + '</b>' + AZ.row('Sales', AZ.money(s.v, 1), AZ.T.family[s.fam]);
      if (s.item) h += AZ.row('Family', s.fam) + AZ.row('Share of ' + s.reg, AZ.pct(s.v / col, 1));
      else h += AZ.row('Share of ' + s.reg, AZ.pct(s.v / col, 1)) + AZ.row('Share of all ' + s.name, AZ.pct(s.v / famAll.get(s.fam), 1));
      h += AZ.row('Share of all sales', AZ.pct(s.v / total, 1));
      if (!cur.reg) h += '<div class="mm-tipnote">Click to open this region</div>';
      tip.show(h, ev.clientX - pr.left, ev.clientY - pr.top);
    }

    // ---- header and drill ------------------------------------------------------------
    let shown = 0;
    function header(S, animate) {
      const v = S.reg ? regT.get(S.reg) : total;
      if (S.reg) {
        const its = Array.from(S.segs.values()).sort((a, b) => b.v - a.v), t = its[0];
        const fam = new Map(); its.forEach((s) => fam.set(s.fam, (fam.get(s.fam) || 0) + s.v));
        const tf = Array.from(fam.entries()).sort((a, b) => b[1] - a[1])[0];
        leadEl.textContent = S.reg + ': ' + t.name + ' leads at ' + AZ.pct(t.v / v, 0) + ' of sales; ' + tf[0] + ' is ' + AZ.pct(tf[1] / v, 0) + ' of the region';
      } else {
        const top = regs[0], fam = FAMS.filter((f) => cell.has(top + '|' + f)).sort((a, b) => cell.get(top + '|' + b) - cell.get(top + '|' + a))[0];
        leadEl.textContent = top + ' is ' + AZ.pct(regT.get(top) / total, 0) + ' of sales, and ' + fam + ' is ' + AZ.pct(cell.get(top + '|' + fam) / regT.get(top), 0) + ' of it';
      }
      crumbsEl.innerHTML = S.reg ? AZ.crumbs(['All regions', S.reg]) : '<span class="mm-hint">Click a column to open it</span>';
      AZ.wireCrumbs(crumbsEl, () => closeReg());
      backEl.style.visibility = S.reg ? 'visible' : 'hidden';
      valS.textContent = S.reg ? AZ.pct(v / total, 1) + ' of sales' : '100% of sales';
      if (animate) cancels.push(AZ.countUp(valB, v, (n) => AZ.money(n, 1), 450, shown)); else valB.textContent = AZ.money(v, 1);
      shown = v;
    }
    function goTo(reg) {
      if (animating || reg === cur.reg) return;
      const to = build(reg), from = cur; focusReg = reg;
      hoverId = null; tip.hide(); settled = null; animating = true; header(to, true);
      const P = plan(from, to, false);
      P.segs.forEach((it) => segEl(it.id, it.src)); P.heads.forEach((it) => hdEl(it.id));
      // the widening column is drawn last so it covers the columns that fade out
      P.segs.slice().sort((a, b) => (to.segs.has(a.id) ? 1 : 0) - (to.segs.has(b.id) ? 1 : 0)).forEach((it) => segG.appendChild(sEls.get(it.id).g));
      cancels.push(AZ.tween(450, (k) => paintPlan(P, k), () => { animating = false; settle(to); }, AZ.EASE.inOut));
    }
    const openReg = (r) => goTo(r), closeReg = () => goTo(null);
    backEl.addEventListener('click', closeReg);
    const onKey = (e) => { if (e.key === 'Escape' && cur && cur.reg) closeReg(); };
    window.addEventListener('keydown', onKey);

    // ---- first paint: columns and stacks grow in ----------------------------------------
    const S0 = build(focusReg); cur = S0; header(S0, false);
    const P0 = plan(S0, S0, true);
    P0.segs.forEach((it) => { it.a = { x: it.b.x, w: it.b.w, y: it.b.y + it.b.h, h: 0 }; it.oa = 1; it.la = null; });
    P0.heads.forEach((it) => { it.oa = 0; });
    animating = true;
    cancels.push(AZ.tween(650, (k) => paintPlan(P0, k), () => { animating = false; settle(S0); }, (t) => t));
    return () => { cancels.forEach((c) => c()); window.removeEventListener('keydown', onKey); };
  }
});
