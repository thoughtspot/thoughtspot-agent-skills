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


// Search: [sales] [item type] [product]
// Radial bar chart: one bar per item type around a circle, longest first, family hues, growing out from the hub.
// Click a bar to swap the chart for that item type's top 12 products (old bars retract, new bars grow).
// Family is an editorial grouping (AZ.familyOf), not a model column. Bar length is proportional to sales.
const D3 = ['https://cdn.jsdelivr.net/npm/d3@7', 'https://unpkg.com/d3@7'];
const TOPP = 12, SVGNS = 'http://www.w3.org/2000/svg';
let focusItem = null; // item type opened into; survives redraw

const mk = (tag, attrs, parent) => { const n = document.createElementNS(SVGNS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; };
const trunc = (s, n) => (n < 3 ? '' : s.length <= n ? s : s.slice(0, Math.max(1, n - 2)) + '..');

AZ.boot({
  need: 'sales by item type and product, e.g. [sales] [item type] [product]',
  render: async ({ el, rows, schema }) => {
    const iK = AZ.col(schema, /item/i), pK = AZ.col(schema, /product/i), sK = AZ.col(schema, /sales/i);
    const R = rows.map((r) => ({ item: String(r[iK]), prod: String(r[pK]), v: AZ.num(r[sK]) })).filter((r) => r.v > 0);
    if (!R.length) { AZ.paint(el, '<div class="az-empty"><b>No sales to draw</b><span>The current filter leaves no products. Widen the filters, or the search needs: [sales] [item type] [product].</span></div>'); return; }
    await AZ.loadScript(D3, () => !!window.d3, 8000);

    const total = R.reduce((a, r) => a + r.v, 0);
    const itT = new Map(), byItem = new Map();
    R.forEach((r) => { itT.set(r.item, (itT.get(r.item) || 0) + r.v); if (!byItem.has(r.item)) byItem.set(r.item, []); byItem.get(r.item).push(r); });
    if (focusItem && !itT.has(focusItem)) focusItem = null;

    el.innerHTML = '<div class="rb-head"><p class="rb-lead"></p></div><div class="rb-bar"><button type="button" class="rb-back" aria-label="Back to all item types">Back</button><div class="rb-crumbs"></div></div><div class="rb-plot"></div>';
    const leadEl = el.querySelector('.rb-lead'), backEl = el.querySelector('.rb-back'), crumbsEl = el.querySelector('.rb-crumbs'), plot = el.querySelector('.rb-plot');
    leadEl.textContent = 'x';
    const W = Math.max(200, plot.clientWidth), H = Math.max(160, plot.clientHeight);
    const cx = W / 2, cy = H / 2, RS = Math.max(60, Math.min(W, H) / 2 - 3), r0 = Math.max(24, RS * 0.24);
    const GAPA = 0.3;
    const svg = mk('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, class: 'rb-svg' }, plot);
    const gridG = mk('g', {}, svg), barG = mk('g', {}, svg), labG = mk('g', {}, svg);
    const hub = mk('circle', { cx, cy, r: r0 - 3, fill: '#FFFFFF' }, svg);
    const cT = mk('text', { class: 'rb-c1', x: cx, y: cy + 1, 'text-anchor': 'middle' }, svg), cS = mk('text', { class: 'rb-c2', x: cx, y: cy + 15, 'text-anchor': 'middle' }, svg);
    const meas = mk('text', { class: 'rb-l', visibility: 'hidden' }, svg);
    const tw = (s, bold) => { meas.setAttribute('font-weight', bold ? 600 : 400); meas.textContent = s; try { return meas.getComputedTextLength(); } catch (e) { return s.length * 6.3; } };
    const tip = AZ.tip(plot), arc = d3.arc();

    // ---- state: bars for a focus ---------------------------------------------------
    function build(item) {
      let list;
      if (!item) list = Array.from(itT.entries()).map((e) => ({ id: 'i:' + e[0], name: e[0], v: e[1], fam: AZ.familyOf(e[0]), drill: true }));
      else list = byItem.get(item).slice().sort((a, b) => b.v - a.v).slice(0, TOPP).map((p, i) => ({ id: 'p:' + i + p.prod, name: p.prod, v: p.v, fam: AZ.familyOf(item), drill: false }));
      list.sort((a, b) => b.v - a.v);
      const max = list[0].v, n = list.length, band = (Math.PI * 2 - GAPA) / n;
      list.forEach((b, i) => {
        b.a0 = i * band + band * 0.06; b.a1 = (i + 1) * band - band * 0.06; b.r1 = r0 + (RS - r0) * b.v / max; b.i = i;
      });
      const focusTotal = item ? itT.get(item) : total, shownSum = list.reduce((a, b) => a + b.v, 0);
      return { item, list, max, n, focusTotal, shownSum };
    }
    const nice = (max) => { const t = d3.ticks(0, max, 3).filter((x) => x > 0); return t; };

    // ---- drawing ------------------------------------------------------------------------
    const cancels = [];
    let cur = null, hover = null, animating = false, els = [];
    function clearBars() { els.forEach((e) => { e.p.remove(); e.l.remove(); }); els = []; }
    function drawGrid(S) {
      gridG.innerHTML = '';
      nice(S.max).forEach((t) => {
        const r = r0 + (RS - r0) * t / S.max;
        mk('circle', { cx, cy, r, fill: 'none', stroke: AZ.T.grid, 'stroke-width': 1 }, gridG);
        const tx = mk('text', { x: cx - 3, y: cy - r + 11, 'text-anchor': 'end', class: 'rb-ax' }, gridG); tx.textContent = AZ.money(t, t >= 1e6 ? 0 : 0);
      });
    }
    function makeBars(S) {
      clearBars();
      S.list.forEach((b) => {
        const p = mk('path', { fill: AZ.T.family[b.fam] || AZ.T.muted, class: 'rb-bar-p', tabindex: b.drill ? 0 : -1, role: b.drill ? 'button' : 'img', 'aria-label': b.name + ', ' + AZ.money(b.v, 1) + (b.drill ? ', press Enter to open products' : '') }, barG);
        const l = mk('g', {}, labG);
        const e = { b, p, l }; els.push(e);
        p.addEventListener('mouseenter', (ev) => { if (!animating) { hover = b.id; dimAll(); showTip(ev, b); } });
        p.addEventListener('mousemove', (ev) => { if (!animating && hover === b.id) showTip(ev, b); });
        p.addEventListener('mouseleave', () => { hover = null; dimAll(); tip.hide(); });
        p.addEventListener('click', () => { if (!animating && b.drill) openItem(b.name); });
        p.addEventListener('keydown', (ev) => { if ((ev.key === 'Enter' || ev.key === ' ') && !animating && b.drill) { ev.preventDefault(); openItem(b.name); } });
        p.style.cursor = b.drill ? 'pointer' : 'default';
      });
    }
    function labelGeom(S, b) {
      const bold = true, val = AZ.money(b.v, 1), vw = tw(val, true), room = b.r1 - r0 - 8;
      const outside = RS - b.r1 - 6;
      const mid = (b.a0 + b.a1) / 2, arcPx = (b.a1 - b.a0) * (r0 + 4);
      if ((b.a1 - b.a0) * b.r1 < 11) return null;
      const out = { name: '', val: '', nameAt: null, valAt: null, mid };
      const nmMax = (avail) => { let s = b.name; while (s.length > 2 && tw(s) > avail) s = s.slice(0, -1); return s.length < b.name.length ? trunc(b.name, s.length) : s; };
      if (outside >= vw + 2) {
        out.val = val; out.valAt = { r: b.r1 + 4, dir: 1 };
        if (room >= 24) { out.name = nmMax(room); out.nameAt = { r: r0 + 6, dir: 1 }; }
      } else {
        const nw = tw(b.name);
        if (room >= nw + vw + 16) { out.val = val; out.valAt = { r: b.r1 - 5, dir: -1 }; out.name = b.name; out.nameAt = { r: r0 + 6, dir: 1 }; }
        else if (room >= 24) { out.name = nmMax(room); out.nameAt = { r: r0 + 6, dir: 1 }; }
        else if (room >= vw) { out.val = val; out.valAt = { r: b.r1 - 5, dir: -1 }; }
      }
      return (out.name || out.val) ? out : null;
    }
    function placeText(t, mid, at, text, bold) {
      const sn = Math.sin(mid), cs = Math.cos(mid), left = sn < -0.001;
      const px = cx + at.r * sn, py = cy - at.r * cs;
      const ang = mid * 180 / Math.PI - 90 + (left ? 180 : 0);
      const outward = at.dir > 0;
      t.setAttribute('transform', 'translate(' + px.toFixed(1) + ',' + py.toFixed(1) + ') rotate(' + ang.toFixed(1) + ')');
      t.setAttribute('text-anchor', outward !== left ? 'start' : 'end');
      t.setAttribute('dy', '0.35em');
      t.setAttribute('font-weight', bold ? 600 : 500);
      t.textContent = text;
    }
    function paintBars(S, kOf) {
      els.forEach((e) => {
        const b = e.b, k = kOf(b), r = r0 + (b.r1 - r0) * k;
        e.p.setAttribute('d', k <= 0.002 ? '' : arc.innerRadius(r0).outerRadius(r).startAngle(b.a0).endAngle(b.a1)({ }));
        e.p.setAttribute('transform', 'translate(' + cx + ',' + cy + ')');
        const lg = e.lg;
        e.l.style.opacity = 0;
      });
    }
    function paintLabels(S, op) {
      els.forEach((e) => {
        const lg = labelGeom(S, e.b);
        e.l.innerHTML = '';
        if (!lg) { e.l.style.display = 'none'; return; }
        e.l.style.display = '';
        const mkT = (at, text, bold, fill) => { const t = mk('text', { class: 'rb-l', fill }, e.l); placeText(t, lg.mid, at, text, bold); };
        const dark = ['#D99A00'].indexOf(AZ.T.family[e.b.fam]) < 0;
        if (lg.name) mkT(lg.nameAt, lg.name, false, dark ? '#FFFFFF' : AZ.T.ink);
        if (lg.val) mkT(lg.valAt, lg.val, true, lg.valAt.dir < 0 ? (dark ? '#FFFFFF' : AZ.T.ink) : AZ.T.ink);
        e.l.style.opacity = op * (hover && hover !== e.b.id ? 0.35 : 1);
      });
    }
    function dimAll() {
      els.forEach((e) => { e.p.style.opacity = hover && hover !== e.b.id ? 0.28 : 1; e.l.style.opacity = hover && hover !== e.b.id ? 0.3 : 1; });
    }
    function showTip(ev, b) {
      const pr = plot.getBoundingClientRect();
      let h = '<b>' + AZ.esc(b.name) + '</b>' + AZ.row('Sales', AZ.money(b.v, 1), AZ.T.family[b.fam]);
      if (cur.item) h += AZ.row('Share of ' + cur.item, AZ.pct(b.v / cur.focusTotal, 1)) + AZ.row('Rank', '#' + (b.i + 1) + ' of ' + cur.n);
      else h += AZ.row('Family', b.fam) + AZ.row('Share of all sales', AZ.pct(b.v / total, 1)) + AZ.row('Rank', '#' + (b.i + 1) + ' of ' + cur.n) + '<div class="rb-tipnote">Click to open its products</div>';
      tip.show(h, ev.clientX - pr.left, ev.clientY - pr.top);
    }

    // ---- header ---------------------------------------------------------------------------------
    let shown = 0;
    function header(S, animate) {
      const t = S.list[0];
      if (S.item) {
        const top = S.shownSum / S.focusTotal;
        leadEl.textContent = S.item + ': ' + t.name + ' leads at ' + AZ.pct(t.v / S.focusTotal, 0) + ' of sales' + (byItem.get(S.item).length > S.n ? '; the top ' + S.n + ' products make up ' + AZ.pct(top, 0) : '');
      } else {
        const top3 = S.list.slice(0, 3).reduce((a, b) => a + b.v, 0);
        leadEl.textContent = S.n >= 4 ? 'The top three item types, ' + S.list.slice(0, 3).map((b) => b.name).join(', ') + ', make up ' + AZ.pct(top3 / total, 0) + ' of sales' : t.name + ' leads with ' + AZ.pct(t.v / total, 0) + ' of sales';
      }
      crumbsEl.innerHTML = S.item ? AZ.crumbs(['All item types', S.item]) : '<span class="rb-hint">Click a bar to see its top products</span>';
      AZ.wireCrumbs(crumbsEl, () => closeItem());
      backEl.style.visibility = S.item ? 'visible' : 'hidden';
      cS.textContent = S.item ? trunc(S.item, Math.floor((r0 * 2 - 8) / 6.2)) : 'total sales';
      if (animate) cancels.push(AZ.countUp(cT, S.focusTotal, (n) => AZ.money(n, 1), 500, shown)); else cT.textContent = AZ.money(S.focusTotal, 1);
      shown = S.focusTotal;
    }
    const growth = (S, k, staggerSpan) => (b) => { const d = (b.i / Math.max(1, S.n)) * staggerSpan; return AZ.EASE.out(Math.max(0, Math.min(1, (k - d) / (1 - staggerSpan)))); };
    function show(S, animate, done) {
      cur = S; hover = null; tip.hide();
      drawGrid(S); makeBars(S); header(S, animate);
      if (!animate) { paintBars(S, () => 1); paintLabels(S, 1); dimAll(); if (done) done(); return; }
      animating = true; gridG.style.opacity = 0;
      cancels.push(AZ.tween(440, (k) => { paintBars(S, growth(S, k, 0.4)); gridG.style.opacity = Math.min(1, k * 3); }, () => { animating = false; paintLabels(S, 0); fadeLabels(S); if (done) done(); }, (t) => t));
    }
    function fadeLabels(S) { cancels.push(AZ.tween(140, (k) => paintLabels(S, k), () => { paintLabels(S, 1); }, AZ.EASE.out)); }
    function goTo(item) {
      if (animating || item === cur.item) return;
      focusItem = item; animating = true; hover = null; tip.hide();
      const old = cur, next = build(item);
      // old bars retract, then the new set grows
      els.forEach((e) => { e.l.style.opacity = 0; });
      cancels.push(AZ.tween(230, (k) => paintBars(old, () => 1 - k), () => {
        animating = false; show(next, true);
      }, AZ.EASE.inOut));
      cS.textContent = ''; cT.textContent = '';
    }
    const openItem = (n) => goTo(n), closeItem = () => goTo(null);
    backEl.addEventListener('click', closeItem);
    const onKey = (e) => { if (e.key === 'Escape' && cur && cur.item) closeItem(); };
    window.addEventListener('keydown', onKey);

    show(build(focusItem), true);
    return () => { cancels.forEach((c) => c()); window.removeEventListener('keydown', onKey); };
  }
});
