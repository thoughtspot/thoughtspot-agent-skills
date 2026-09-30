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

// Search: [product] [item type] [sales] [quantity purchased]
// Beeswarm of every product along a price-per-unit axis, dot area = sales, hue = product family.
// A d3 force simulation settles the dots and they animate into place. Family chips filter (the rest dim).
// Hover a dot for the product; click one to open its card (price against its item type average, rank among
// its item type) and highlight its item type peers; Back or Escape closes.
let fam = null, selP = null, peerT = null, entered = false;
const D3URLS = ['https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js', 'https://unpkg.com/d3@7/dist/d3.min.js'];

AZ.boot({
  need: 'product, item type, sales and quantity purchased, e.g. [product] [item type] [sales] [quantity purchased]',
  render: async ({ el, rows, schema, w, h }) => {
    await AZ.loadScript(D3URLS, () => !!window.d3, 8000);
    const pK = AZ.col(schema, /product/i), iK = AZ.col(schema, /item/i), sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity/i);
    const agg = new Map();
    rows.forEach((r) => {
      const k = String(r[pK]) + '||' + String(r[iK]);
      const o = agg.get(k) || { name: String(r[pK]), type: String(r[iK]), s: 0, u: 0 };
      o.s += AZ.num(r[sK]); o.u += AZ.num(r[uK]); agg.set(k, o);
    });
    const P = Array.from(agg.values()).filter((o) => o.u > 0 && o.s > 0);
    if (!P.length) { AZ.paint(el, '<div class="az-empty"><b>No products in the result</b><span>The search needs [product] [item type] [sales] [quantity purchased]</span></div>'); return; }
    P.forEach((o) => { o.price = o.s / o.u; o.fam = AZ.familyOf(o.type); o.col = AZ.familyColor(o.type); });
    // rank within item type, and item type averages (weighted: sales / units)
    const T = new Map();
    P.forEach((o) => { const t = T.get(o.type) || { n: 0, s: 0, u: 0, list: [] }; t.n++; t.s += o.s; t.u += o.u; t.list.push(o); T.set(o.type, t); });
    T.forEach((t) => { t.avg = t.s / t.u; t.list.sort((a, b) => b.s - a.s).forEach((o, i) => { o.rank = i + 1; }); });
    if (selP && !P.some((o) => o.name === selP.name && o.type === selP.type)) selP = null;
    else if (selP) selP = P.find((o) => o.name === selP.name && o.type === selP.type);
    if (peerT && !T.has(peerT)) peerT = null;
    if (selP) peerT = selP.type;
    const famList = Object.keys(AZ.T.family).filter((f) => P.some((o) => o.fam === f)).concat(P.some((o) => o.fam === 'Other') ? ['Other'] : []);
    if (fam && famList.indexOf(fam) < 0) fam = null;
    if (selP && fam && selP.fam !== fam) { selP = null; }

    const dhFull = 108;
    const median = (a) => { const s = a.slice().sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
    el.innerHTML = '<div class="bs-head"><div class="bs-title">Every product by price per unit</div><div class="bs-sub" id="bs-sub"></div></div>'
      + '<div class="bs-chips" id="bs-chips"></div>'
      + '<div class="bs-plot" id="bs-plot"></div>'
      + '<div class="bs-card" id="bs-card" style="height:0"><div class="bs-cbar" id="bs-cbar"></div><div class="bs-cbody" id="bs-cbody"></div></div>';
    const plot = el.querySelector('#bs-plot'), card = el.querySelector('#bs-card'), cbar = el.querySelector('#bs-cbar'), cbody = el.querySelector('#bs-cbody'), chips = el.querySelector('#bs-chips'), subEl = el.querySelector('#bs-sub');
    const tip = AZ.tip(el);
    const NS = 'http://www.w3.org/2000/svg';
    const mk = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); Object.keys(attrs || {}).forEach((k) => e.setAttribute(k, attrs[k])); if (parent) parent.appendChild(e); return e; };

    chips.innerHTML = famList.map((f) => '<button type="button" class="bs-chip" data-f="' + AZ.esc(f) + '" aria-pressed="false"><i style="background:' + (AZ.T.family[f] || AZ.T.muted) + '"></i>' + AZ.esc(f) + '</button>').join('');
    chips.querySelectorAll('.bs-chip').forEach((b) => b.addEventListener('click', () => { const f = b.getAttribute('data-f'); fam = fam === f ? null : f; if (selP && fam && selP.fam !== fam) closeCard(); update(); }));

    // ---- layout with the card at its final height first, so the plot measures its final size
    let cardK = selP ? 1 : 0;
    card.style.height = Math.round(cardK * dhFull) + 'px';
    const W = Math.max(200, plot.clientWidth);
    // the swarm is settled for the height left when the card is open; closed, it is stretched vertically (never overlaps)
    const Hopen = Math.max(110, plot.clientHeight - (1 - cardK) * dhFull);
    let Hc = Math.max(110, plot.clientHeight), ent = entered ? 1 : 0;
    const narrow = W < 420, ML = 12, MR = 14, MT = 6, MB = 32;
    let pmin = Infinity, pmax = 0; P.forEach((o) => { pmin = Math.min(pmin, o.price); pmax = Math.max(pmax, o.price); });
    // log scale: prices bunch up between $15 and $60, and a linear axis would stack them into one column
    const L0 = Math.log(Math.max(1, pmin * 0.92)), L1 = Math.log(pmax * 1.05);
    const xs = (v) => ML + (Math.log(v) - L0) / (L1 - L0) * (W - ML - MR);
    const cy = MT + (Hopen - MT - MB) / 2, halfH = (Hopen - MT - MB) / 2 - 3;
    const smax = Math.max.apply(null, P.map((o) => o.s));
    // settle with a force simulation; shrink the dots until the swarm fits the height
    let rMax = narrow ? 12 : 16, nodes = [];
    for (let attempt = 0; attempt < 6; attempt++) {
      nodes = P.map((o) => ({ o: o, r: Math.max(2.2, rMax * Math.sqrt(o.s / smax)), x: xs(o.price), y: cy }));
      const sim = d3.forceSimulation(nodes).force('x', d3.forceX((d) => xs(d.o.price)).strength(1)).force('y', d3.forceY(cy).strength(0.06)).force('c', d3.forceCollide((d) => d.r + 0.7).iterations(2)).stop();
      for (let i = 0; i < 260; i++) sim.tick();
      let ext = 0; nodes.forEach((d) => { ext = Math.max(ext, Math.abs(d.y - cy) + d.r); });
      if (ext <= halfH) break;
      rMax *= Math.max(0.55, halfH / ext * 0.95);
    }
    { let ext = 0; nodes.forEach((d) => { ext = Math.max(ext, Math.abs(d.y - cy) + d.r); }); if (ext > halfH) nodes.forEach((d) => { d.y = cy + (d.y - cy) * halfH / ext; }); }
    nodes.forEach((d) => { d.o.node = d; d.dy = d.y - cy; });

    // static layer: axis
    const svg = mk('svg', { viewBox: '0 0 ' + W + ' ' + Hc, role: 'img', 'aria-label': 'Beeswarm of ' + P.length + ' products by price per unit' }, plot);
    const gAx = mk('g', {}, svg);
    const vLines = [], vTexts = [];
    [10, 15, 20, 30, 40, 50, 75, 100, 150, 200].filter((v) => v >= pmin * 0.92 && v <= pmax * 1.05 && (!narrow || [15, 30, 50, 100, 150].indexOf(v) >= 0 || v === 20 && false)).forEach((v) => {
      vLines.push(mk('line', { x1: xs(v), x2: xs(v), y1: MT, y2: Hc - MB, stroke: AZ.T.grid }, gAx));
      vTexts.push(mk('text', { class: 'bs-ax', x: xs(v), y: Hc - MB + 13, 'text-anchor': 'middle' }, gAx)); vTexts[vTexts.length - 1].textContent = AZ.money(v, 0);
    });
    const axT = mk('text', { class: 'bs-axt', x: W - MR, y: Hc - 2, 'text-anchor': 'end' }, gAx); axT.textContent = narrow ? 'Log scale. Area is sales' : 'Price per unit, log scale. Dot area is sales';
    const gAvg = mk('g', { 'pointer-events': 'none' }, svg), gD = mk('g', {}, svg), gSel = mk('g', { 'pointer-events': 'none' }, svg);
    nodes.forEach((d) => {
      const o = d.o;
      d.c = mk('circle', { class: 'bs-dot', r: d.r, cx: d.x, cy: cy, fill: o.col, 'fill-opacity': 0.78, stroke: '#fff', 'stroke-width': 0.8 }, gD);
    });
    // focusable: the 12 largest, so the keyboard reaches the swarm
    nodes.slice().sort((a, b) => b.o.s - a.o.s).slice(0, 12).forEach((d) => {
      d.c.setAttribute('tabindex', 0); d.c.setAttribute('role', 'button'); d.c.setAttribute('aria-label', d.o.name + ', ' + d.o.type);
      d.c.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openCard(d.o); } });
      d.c.addEventListener('focus', () => { const b = d.c.getBoundingClientRect(); showTip(d.o, { clientX: b.left + b.width / 2, clientY: b.top }); });
      d.c.addEventListener('blur', () => tip.hide());
    });

    // place(): dots at their settled offset from the centre line, scaled to the current plot height
    function place() {
      Hc = Math.max(110, plot.clientHeight);
      svg.setAttribute('viewBox', '0 0 ' + W + ' ' + Hc);
      const cyC = MT + (Hc - MT - MB) / 2, sy = Math.max(1, ((Hc - MT - MB) / 2 - 3) / Math.max(1, halfH));
      vLines.forEach((l) => l.setAttribute('y2', Hc - MB)); vTexts.forEach((t) => t.setAttribute('y', Hc - MB + 14)); axT.setAttribute('y', Hc - 2);
      nodes.forEach((d) => { d.py = cyC + d.dy * sy * ent; d.c.setAttribute('cy', d.py.toFixed(1)); });
    }
    let hovO = null, cancel = () => {};
    const inFam = (o) => !fam || o.fam === fam;
    const state = (o) => {
      if (!inFam(o)) return 0.08;
      if (peerT) return o.type === peerT ? 1 : 0.12;
      return 1;
    };
    function update() {
      chips.querySelectorAll('.bs-chip').forEach((b) => { const on = b.getAttribute('data-f') === fam; b.classList.toggle('on', on); b.classList.toggle('dim', !!fam && !on); b.setAttribute('aria-pressed', String(on)); });
      nodes.forEach((d) => {
        const o = d.o, a = state(o), isSel = selP === o, isH = hovO === o;
        d.c.setAttribute('opacity', a);
        d.c.setAttribute('stroke', isSel || isH ? AZ.T.ink : '#fff'); d.c.setAttribute('stroke-width', isSel ? 2.4 : isH ? 1.8 : 0.8);
        d.c.style.pointerEvents = inFam(o) ? '' : 'none';
      });
      const shown = P.filter(inFam), pr = shown.map((o) => o.price);
      subEl.innerHTML = shown.length ? '<b>' + shown.length + '</b> product' + (shown.length === 1 ? '' : 's') + (fam ? ' in ' + AZ.esc(fam) : '') + ', priced <b>' + AZ.money(Math.min.apply(null, pr), 2) + '</b> to <b>' + AZ.money(Math.max.apply(null, pr), 2) + '</b> a unit, median <b>' + AZ.money(median(pr), 2) + '</b>' : 'No products in this family under the current filter';
      // item type average marker
      gAvg.innerHTML = ''; gSel.innerHTML = '';
      if (peerT && T.has(peerT)) {
        const t = T.get(peerT), x = xs(t.avg);
        mk('line', { x1: x, x2: x, y1: MT, y2: Hc - MB, stroke: AZ.T.ink, 'stroke-width': 1.2, 'stroke-dasharray': '4 3' }, gAvg);
        const tx = mk('text', { class: 'bs-avg', x: Math.min(W - MR, Math.max(ML, x)), y: MT + 10, 'text-anchor': x > W - 110 ? 'end' : 'start' }, gAvg);
        tx.setAttribute('dx', x > W - 110 ? -5 : 5); tx.textContent = peerT + ' average ' + AZ.money(t.avg, 2);
      }
      if (selP) { const d = selP.node; mk('circle', { cx: d.x, cy: d.py, r: d.r + 3.5, fill: 'none', stroke: AZ.T.ink, 'stroke-width': 1.4 }, gSel); }
    }

    const showTip = (o, e) => {
      const b = el.getBoundingClientRect();
      tip.show('<b>' + AZ.esc(o.name) + '</b>' + AZ.row(o.type, o.fam, o.col) + AZ.row('Sales', AZ.money(o.s, 2)) + AZ.row('Units', AZ.int(o.u)) + AZ.row('Price per unit', AZ.money(o.price, 2)) + AZ.row('Click', 'open card'), e.clientX - b.left, e.clientY - b.top);
    };
    const pick = (e) => {
      const b = plot.getBoundingClientRect(), px = (e.clientX - b.left) / b.width * W, py = (e.clientY - b.top) / b.height * Hc;
      let best = null, bd = 1e9;
      for (const d of nodes) { if (!inFam(d.o)) continue; const dd = Math.hypot(d.x - px, d.py - py) - d.r; if (dd < bd) { bd = dd; best = d; } }
      if (bd > 6) best = null;
      return best && inFam(best.o) ? best.o : null;
    };
    plot.addEventListener('mousemove', (e) => {
      const o = pick(e);
      if (o !== hovO) { hovO = o; update(); }
      plot.style.cursor = o ? 'pointer' : '';
      if (o) showTip(o, e); else tip.hide();
    });
    plot.addEventListener('mouseleave', () => { hovO = null; tip.hide(); update(); });
    plot.addEventListener('click', (e) => { const o = pick(e); if (o) openCard(o); });

    // ---- drill: product card
    function fillCard() {
      if (!selP) { cbar.innerHTML = ''; cbody.innerHTML = ''; return; }
      const o = selP, t = T.get(o.type), diff = o.price / t.avg - 1;
      cbar.innerHTML = AZ.crumbs(['All products', o.type, o.name]) + '<button type="button" class="bs-back" id="bs-back">Back</button>';
      AZ.wireCrumbs(cbar, (i) => { if (i === 0) closeCard(); else { selP = null; cardTo(0); peerT = o.type; update(); } });
      cbar.querySelector('#bs-back').addEventListener('click', closeCard);
      cbody.innerHTML = '<div class="bs-stat"><span>Sales</span><b>' + AZ.money(o.s, 2) + '</b><i>' + AZ.pct(o.s / t.s, 1) + ' of ' + AZ.esc(o.type) + '</i></div>'
        + '<div class="bs-stat"><span>Units</span><b>' + AZ.int(o.u) + '</b><i>' + AZ.pct(o.u / t.u, 1) + ' of ' + AZ.esc(o.type) + '</i></div>'
        + '<div class="bs-stat"><span>Price per unit</span><b>' + AZ.money(o.price, 2) + '</b><i class="' + (diff > 0.005 ? 'up' : diff < -0.005 ? 'dn' : '') + '">' + AZ.pct(diff, 1, true) + ' vs avg ' + AZ.money(t.avg, 2) + '</i></div>'
        + '<div class="bs-stat"><span>Rank by sales</span><b>#' + o.rank + '</b><i>of ' + t.n + ' in ' + AZ.esc(o.type) + '</i></div>';
    }
    function cardTo(k) {
      cancel();
      const from = cardK;
      cancel = AZ.tween(420, (e) => { cardK = AZ.lerp(from, k, e); card.style.height = Math.round(cardK * dhFull) + 'px'; card.style.opacity = String(Math.min(1, cardK * 1.5)); place(); update(); }, () => { if (k === 0) { cbar.innerHTML = ''; cbody.innerHTML = ''; } }, AZ.EASE.inOut);
    }
    function openCard(o) { selP = o; peerT = o.type; tip.hide(); fillCard(); cardTo(1); update(); }
    function closeCard() { selP = null; peerT = null; cardTo(0); update(); }
    const onKey = (e) => { if (e.key === 'Escape' && (selP || peerT)) closeCard(); };
    window.addEventListener('keydown', onKey);

    card.style.opacity = selP ? '1' : '0';
    fillCard(); place(); update();
    if (!entered && !AZ.reduced()) {
      // dots start on the price line and settle into the swarm
      ent = 0; place(); update();
      cancel = AZ.tween(620, (k) => { ent = k; place(); if (selP) update(); }, () => { ent = 1; place(); update(); }, AZ.EASE.out);
    }
    entered = true;
    return () => { cancel(); window.removeEventListener('keydown', onKey); };
  }
});
