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

// Search: [sales] [quantity purchased] [store] [date].quarterly
// Parallel coordinates: one line per store across five axes (total sales, total units, price per unit, year-to-date change,
// share of the largest store). Drag on an axis to brush and filter; hover a line for the store; click a line to pin it.
let pinned = null, entered = false;
const brush = {};

AZ.boot({
  need: 'sales, quantity purchased, store and date at quarterly grain, e.g. [sales] [quantity purchased] [store] [date].quarterly',
  render: async ({ el, rows, schema, w, h }) => {
    const sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity/i), stK = AZ.col(schema, /store/i), dK = AZ.col(schema, /date|quarter|month/i);
    const by = new Map(); let maxT = -1;
    rows.forEach((r) => {
      const t = AZ.ms(r[dK]); if (!isFinite(t)) return;
      if (t > maxT) maxT = t;
      const k = String(r[stK]);
      if (!by.has(k)) by.set(k, []);
      by.get(k).push({ t: t, s: AZ.num(r[sK]), u: AZ.num(r[uK]) });
    });
    if (!by.size) { AZ.paint(el, '<div class="az-empty"><b>No stores in the result</b><span>The search needs [sales] [quantity purchased] [store] [date].quarterly</span></div>'); return; }
    const qn = (t) => Math.floor(new Date(t).getUTCMonth() / 3) + 1, yr = (t) => new Date(t).getUTCFullYear();
    const ly = yr(maxT), lq = qn(maxT);
    const stores = Array.from(by.entries()).map(([name, a]) => {
      let s = 0, u = 0, c = 0, p = 0, nc = 0, np = 0;
      a.forEach((r) => {
        s += r.s; u += r.u;
        if (qn(r.t) <= lq) { if (yr(r.t) === ly) { c += r.s; nc++; } else if (yr(r.t) === ly - 1) { p += r.s; np++; } }
      });
      return { name: name, s: s, u: u, price: u ? s / u : 0, chg: nc > 0 && nc === np && p > 0 ? c / p - 1 : null };
    });
    const maxS = Math.max.apply(null, stores.map((x) => x.s)) || 1;
    stores.forEach((x) => { x.share = x.s / maxS; });
    const hasChg = stores.some((x) => x.chg != null);
    const lbl = 'Q1-Q' + lq;
    const AX = [
      { k: 's', t: 'Total sales', sub: 'all quarters', f: (v) => AZ.money(v, 1) },
      { k: 'u', t: 'Units', sub: 'all quarters', f: (v) => AZ.int(v) },
      { k: 'price', t: 'Price per unit', sub: 'sales / units', f: (v) => AZ.money(v, 2) },
      { k: 'chg', t: 'YTD change', sub: (lq === 1 ? 'Q1' : lbl) + ' vs ' + (ly - 1), f: (v) => AZ.pct(v, 1, true) },
      { k: 'share', t: 'Share of top', sub: 'largest = 100%', f: (v) => AZ.pct(v, 0) }
    ].filter((a) => a.k !== 'chg' || hasChg);
    AX.forEach((a) => {
      const vals = stores.map((x) => x[a.k]).filter((v) => v != null);
      let lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
      if (hi - lo < 1e-9) { lo -= Math.abs(lo) * 0.05 + 0.01; hi += Math.abs(hi) * 0.05 + 0.01; }
      const pad = (hi - lo) * 0.04; a.lo = lo - pad; a.hi = hi + pad; a.dlo = lo; a.dhi = hi;
      a.rank = new Map(); stores.filter((x) => x[a.k] != null).sort((p, q) => q[a.k] - p[a.k]).forEach((x, i) => a.rank.set(x.name, i + 1));
    });
    Object.keys(brush).forEach((k) => { if (!AX.some((a) => a.k === k)) delete brush[k]; });
    if (pinned && !by.has(pinned)) pinned = null;

    const N = stores.length, showPanel = w >= 600;
    const chgs = stores.map((x) => x.chg).filter((v) => v != null);
    const pa = AX.find((a) => a.k === 'price');
    const sub = hasChg
      ? 'Year-to-date change (' + lbl + ' ' + ly + ' on ' + (ly - 1) + ') runs from <b>' + AZ.pct(Math.min.apply(null, chgs), 1, true) + '</b> to <b>' + AZ.pct(Math.max.apply(null, chgs), 1, true) + '</b>; price per unit from <b>' + AZ.money(pa.dlo, 2) + '</b> to <b>' + AZ.money(pa.dhi, 2) + '</b>'
      : 'Price per unit runs from <b>' + AZ.money(pa.dlo, 2) + '</b> to <b>' + AZ.money(pa.dhi, 2) + '</b>. No same-quarter comparison with last year in this view, so YTD change is left out';
    el.innerHTML = '<div class="pc-head"><div><div class="pc-title" id="pc-title"></div><div class="pc-sub">' + sub + '</div></div><button type="button" class="pc-reset" id="pc-reset">Reset</button></div>'
      + '<div class="pc-body"><div class="pc-plot" id="pc-plot"></div>' + (showPanel ? '<div class="pc-panel" id="pc-panel"></div>' : '') + '</div>'
      + '<div class="pc-cap" id="pc-cap"></div>';
    const plot = el.querySelector('#pc-plot'), panel = el.querySelector('#pc-panel'), titleEl = el.querySelector('#pc-title'), resetB = el.querySelector('#pc-reset'), cap = el.querySelector('#pc-cap');
    const W = Math.max(200, plot.clientWidth), H = Math.max(120, plot.clientHeight);
    const narrow = W < 420, PT = narrow ? 34 : 42, PB = 12, PL = narrow ? 34 : 44, PR = narrow ? 34 : 50;
    const ph = H - PT - PB, n = AX.length, gap = (W - PL - PR) / Math.max(1, n - 1);
    const axX = (i) => n === 1 ? W / 2 : PL + i * gap;
    const yOf = (a, v) => PT + (1 - (v - a.lo) / (a.hi - a.lo)) * ph;
    const vOf = (a, y) => a.lo + (1 - (y - PT) / ph) * (a.hi - a.lo);
    const NS = 'http://www.w3.org/2000/svg';
    const mk = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); Object.keys(attrs || {}).forEach((k) => e.setAttribute(k, attrs[k])); if (parent) parent.appendChild(e); return e; };
    const svg = mk('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': 'Parallel coordinates of ' + N + ' stores' }, plot);
    const gAx = mk('g', {}, svg), gLines = mk('g', {}, svg), gStrip = mk('g', {}, svg), gHit = mk('g', {}, svg), gBr = mk('g', { 'pointer-events': 'none' }, svg), gTop = mk('g', { 'pointer-events': 'none' }, svg);

    AX.forEach((a, i) => {
      const x = axX(i), anchor = i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle';
      mk('line', { x1: x, x2: x, y1: PT, y2: PT + ph, stroke: AZ.T.slate[3], 'stroke-width': 1.5 }, gAx);
      mk('text', { class: 'pc-at', x: x, y: PT - (narrow ? 20 : 26), 'text-anchor': anchor }, gAx).textContent = narrow ? a.t.replace('Share of top', 'Share') : a.t;
      if (!narrow) mk('text', { class: 'pc-as', x: x, y: PT - 13, 'text-anchor': anchor }, gAx).textContent = a.sub;
      [a.dhi, a.dlo].forEach((v, j) => {
        mk('line', { x1: x - 4, x2: x + 4, y1: yOf(a, v), y2: yOf(a, v), stroke: AZ.T.slate[3] }, gAx);
        mk('text', { class: 'pc-tk', x: x + (i === n - 1 ? -8 : 8), y: yOf(a, v) + (j === 0 ? 11 : -3), 'text-anchor': i === n - 1 ? 'end' : 'start' }, gAx).textContent = a.f(v);
      });
    });

    // one path per store; a null value breaks the line
    const pathOf = (x) => { let d = '', open = false; AX.forEach((a, i) => { const v = x[a.k]; if (v == null) { open = false; return; } d += (open ? 'L' : 'M') + axX(i).toFixed(1) + ' ' + yOf(a, v).toFixed(1); open = true; }); return d; };
    stores.forEach((x) => {
      x.d = pathOf(x);
      x.p = mk('path', { d: x.d, class: 'pc-line', fill: 'none', 'stroke-linejoin': 'round', 'stroke-linecap': 'round', pathLength: 1 }, gLines);
      x.hit = mk('path', { d: x.d, class: 'pc-hit', fill: 'none', 'stroke-width': narrow ? 8 : 10, stroke: 'transparent', tabindex: 0, role: 'button', 'aria-label': x.name }, gHit);
    });
    const tip = AZ.tip(el); let hov = null, drag = null;
    const match = (x) => AX.every((a) => { const b = brush[a.k]; if (!b) return true; const v = x[a.k]; return v != null && v >= b[0] && v <= b[1]; });
    const brushed = () => Object.keys(brush).length > 0;

    function paint() {
      let m = 0; const front = [];
      stores.forEach((x) => {
        const ok = match(x); x.ok = ok; if (ok) m++;
        const isP = pinned === x.name, isH = hov === x;
        x.p.setAttribute('stroke', isP || isH || ok ? AZ.T.ink : AZ.T.slate[2]);
        x.p.setAttribute('stroke-opacity', isP ? 1 : isH ? 0.95 : ok ? (brushed() ? 0.7 : 0.32) : 0.12);
        x.p.setAttribute('stroke-width', isP ? 3 : isH ? 2.6 : ok && brushed() ? 1.7 : 1.4);
        if (isP || isH) front.push(x);
      });
      front.sort((p, q) => (pinned === p.name ? 1 : 0) - (pinned === q.name ? 1 : 0)).forEach((x) => gLines.appendChild(x.p));
      gBr.innerHTML = '';
      AX.forEach((a, i) => {
        const b = brush[a.k]; if (!b) return;
        const y1 = yOf(a, Math.min(a.hi, b[1])), y2 = yOf(a, Math.max(a.lo, b[0]));
        mk('rect', { class: 'pc-brush', x: axX(i) - 8, y: y1, width: 16, height: Math.max(2, y2 - y1), rx: 3 }, gBr);
      });
      gTop.innerHTML = '';
      const focus = pinned ? stores.find((x) => x.name === pinned) : hov;
      if (focus) AX.forEach((a, i) => { if (focus[a.k] != null) mk('circle', { cx: axX(i), cy: yOf(a, focus[a.k]), r: 3.5, fill: '#fff', stroke: AZ.T.ink, 'stroke-width': 2 }, gTop); });
      titleEl.textContent = brushed() ? m + ' of ' + N + ' stores match the brush' : N + ' stores across ' + n + ' measures';
      resetB.disabled = !(brushed() || pinned);
      cap.textContent = pinned ? 'Pinned: ' + pinned + '. Click its line again, or Reset, to release it.' : (brushed() ? 'Drag on an axis to replace its brush, click an axis to clear it.' : 'Drag along any axis to filter. Hover a line for the store, click to pin it.');
      if (panel) panelDraw(focus);
    }
    function panelDraw(x) {
      if (!x) { panel.innerHTML = '<div class="pc-pt">No store selected</div><div class="pc-pm">Hover a line to read a store, click to pin it.</div>'; return; }
      panel.innerHTML = '<div class="pc-pt">' + AZ.esc(x.name) + (pinned === x.name ? ' <span class="pc-pin">pinned</span>' : '') + '</div>'
        + AX.map((a) => '<div class="pc-pr"><span>' + AZ.esc(a.t) + '</span><b>' + (x[a.k] != null ? a.f(x[a.k]) : 'n/a') + '</b><i>' + (a.rank.get(x.name) ? '#' + a.rank.get(x.name) : '') + '</i></div>').join('');
    }
    const showTip = (x, e) => {
      const b = el.getBoundingClientRect();
      tip.show('<b>' + AZ.esc(x.name) + '</b>' + AX.map((a) => AZ.row(a.t, x[a.k] != null ? a.f(x[a.k]) : 'n/a')).join(''), e.clientX - b.left, e.clientY - b.top);
    };
    // hit-test by distance to the polyline, so the thin lines are easy to reach
    const segD = (px, py, x1, y1, x2, y2) => { const dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy, t = l2 ? Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / l2)) : 0; return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)); };
    const nearest = (e) => {
      const b = plot.getBoundingClientRect(), px = (e.clientX - b.left) / b.width * W, py = (e.clientY - b.top) / b.height * H;
      let best = null, bd = narrow ? 12 : 14;
      stores.forEach((x) => {
        if (brushed() && !x.ok) return;
        for (let i = 0; i < AX.length - 1; i++) {
          if (x[AX[i].k] == null || x[AX[i + 1].k] == null) continue;
          const d = segD(px, py, axX(i), yOf(AX[i], x[AX[i].k]), axX(i + 1), yOf(AX[i + 1], x[AX[i + 1].k]));
          if (d < bd) { bd = d; best = x; }
        }
      });
      return best;
    };
    plot.addEventListener('mousemove', (e) => {
      if (drag) return;
      const x = nearest(e);
      plot.style.cursor = x ? 'pointer' : '';
      if (x !== hov) { hov = x; paint(); }
      if (x) showTip(x, e); else tip.hide();
    });
    plot.addEventListener('mouseleave', () => { hov = null; tip.hide(); paint(); });
    plot.addEventListener('click', (e) => {
      if (e.target.classList && e.target.classList.contains('pc-strip')) return;
      const x = nearest(e); if (x) { pinned = pinned === x.name ? null : x.name; paint(); }
    });
    stores.forEach((x) => {
      x.hit.style.pointerEvents = 'none';
      x.hit.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pinned = pinned === x.name ? null : x.name; paint(); } });
      x.hit.addEventListener('focus', () => { const bb = x.hit.getBoundingClientRect(); hov = x; showTip(x, { clientX: bb.left + bb.width / 2, clientY: bb.top }); paint(); });
      x.hit.addEventListener('blur', () => { hov = null; tip.hide(); paint(); });
    });

    // brush: a transparent strip over each axis, below the hit lines so a line still wins where they cross
    AX.forEach((a, i) => {
      const r = mk('rect', { class: 'pc-strip', x: axX(i) - 12, y: PT - 4, width: 24, height: ph + 8, fill: 'transparent' }, gStrip);
      const yAt = (e) => { const b = plot.getBoundingClientRect(); return Math.max(PT, Math.min(PT + ph, (e.clientY - b.top) / b.height * H)); };
      r.addEventListener('pointerdown', (e) => { drag = { a: a, y0: yAt(e), moved: false }; try { r.setPointerCapture(e.pointerId); } catch (er) {} tip.hide(); hov = null; });
      r.addEventListener('pointermove', (e) => {
        if (!drag || drag.a !== a) return;
        const y = yAt(e); if (Math.abs(y - drag.y0) > 3) drag.moved = true;
        if (drag.moved) { const v0 = vOf(a, drag.y0), v1 = vOf(a, y); brush[a.k] = [Math.min(v0, v1), Math.max(v0, v1)]; paint(); }
      });
      const end = () => { if (!drag || drag.a !== a) return; if (!drag.moved) delete brush[a.k]; drag = null; paint(); };
      r.addEventListener('pointerup', end); r.addEventListener('pointercancel', end);
    });
    resetB.addEventListener('click', () => { Object.keys(brush).forEach((k) => delete brush[k]); pinned = null; paint(); });
    const onKey = (e) => { if (e.key === 'Escape') { Object.keys(brush).forEach((k) => delete brush[k]); pinned = null; paint(); } };
    window.addEventListener('keydown', onKey);

    paint();
    let cancel = () => {};
    if (!entered && !AZ.reduced()) {
      // lines draw in with a stagger; the final frame is the default state
      const total = 620, dur = 340, gp = N > 1 ? (total - dur) / (N - 1) : 0;
      stores.forEach((x) => { x.p.setAttribute('stroke-dasharray', '1 1'); x.p.setAttribute('stroke-dashoffset', 1); });
      cancel = AZ.tween(total, (k) => { const t = k * total; stores.forEach((x, i) => { const p = Math.max(0, Math.min(1, (t - i * gp) / dur)); x.p.setAttribute('stroke-dashoffset', (1 - AZ.EASE.out(p)).toFixed(3)); }); },
        () => stores.forEach((x) => { x.p.removeAttribute('stroke-dasharray'); x.p.removeAttribute('stroke-dashoffset'); }), (t) => t);
    }
    entered = true;
    return () => { cancel(); window.removeEventListener('keydown', onKey); };
  }
});
