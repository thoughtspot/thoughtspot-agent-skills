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

// Search: [sales] [quantity purchased] [item type] [product]
// Diverging bar (Muze) per item type: share of sales minus share of units, in percentage points.
// Right of zero = premium (earns more than its share of units), left = sells on volume.
// Toggle: gap in pts, or price index (price per unit against the overall price per unit, minus 1).
// Click a bar (or Enter on the focused row) to see that item type's products, measured the same way inside
// the item type (top 12 by absolute gap). Crumb, Back or Escape goes up. Colour = family (editorial grouping).
const TOPN = 12, NS = 'http://www.w3.org/2000/svg', DUR = 450, AXIS_H = 18;
let mode = 'gap';   // 'gap' | 'idx'  (survives redraw)
let drill = null;   // item type name, or null for the top level (survives redraw)

const svgEl = (tag, attrs, parent) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; };
const trunc = (s, n) => (n < 3 ? '' : s.length <= n ? s : s.slice(0, Math.max(1, n - 2)) + '..');
const money2 = (v) => '$' + v.toFixed(2);

AZ.boot({
  need: 'sales, quantity purchased, item type and product, e.g. [sales] [quantity purchased] [item type] [product]',
  render: async ({ el, rows, schema, w }) => {
    const { muze } = AZ.host();
    const { DataModel } = muze;
    const iK = AZ.col(schema, /item/i), sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity|units/i);
    const pK = AZ.col(schema, /product/i, { optional: true });
    const R = rows.map((r) => ({ item: String(r[iK]), prod: pK ? String(r[pK]) : null, s: AZ.num(r[sK]), u: AZ.num(r[uK]) })).filter((r) => r.u > 0 && r.s >= 0);
    if (!R.length) { AZ.paint(el, '<div class="az-empty"><b>No units to compare</b><span>The current filter leaves no rows with units sold. Widen the filters, or the search needs: [sales] [quantity purchased] [item type] [product].</span></div>'); return; }

    // ---- data for one level ------------------------------------------------
    const roll = (list, keyOf) => {
      const m = new Map();
      list.forEach((r) => { const k = keyOf(r); const o = m.get(k) || { name: k, s: 0, u: 0 }; o.s += r.s; o.u += r.u; m.set(k, o); });
      const out = [...m.values()], S = out.reduce((a, o) => a + o.s, 0), U = out.reduce((a, o) => a + o.u, 0);
      out.forEach((o) => { o.ss = S ? o.s / S : 0; o.us = U ? o.u / U : 0; o.gap = o.ss - o.us; o.p = o.s / o.u; o.idx = S && U ? o.p / (S / U) - 1 : 0; });
      return { list: out, S, U, avgP: U ? S / U : 0 };
    };
    const top = roll(R, (r) => r.item);
    const itemNames = new Set(top.list.map((o) => o.name));
    if (drill && (!pK || !itemNames.has(drill))) drill = null;
    const levelData = () => {
      if (!drill) return Object.assign(top, { all: top.list.length, kind: 'item' });
      const L = roll(R.filter((r) => r.item === drill), (r) => r.prod);
      const all = L.list.length;
      L.list = L.list.slice().sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap)).slice(0, TOPN);
      return Object.assign(L, { all, kind: 'product' });
    };
    const val = (o) => (mode === 'gap' ? o.gap : o.idx) * 100;
    const fmtVal = (v) => (mode === 'gap' ? (v > 0.05 ? '+' : v < -0.05 ? '-' : '') + Math.abs(v).toFixed(1) : (v >= 0.5 ? '+' : v <= -0.5 ? '-' : '') + Math.abs(v).toFixed(0) + '%');
    const colorOf = (name) => AZ.familyColor(drill || name);

    // ---- shell -------------------------------------------------------------
    el.innerHTML = '<div class="pd-head"><p class="pd-lead"></p><p class="pd-sub"></p></div>'
      + '<div class="pd-bar"><div class="pd-crumbs"></div><div class="pd-tog" role="group" aria-label="Measure">'
      + '<button type="button" class="pd-t" data-m="gap">' + (w < 340 ? 'Gap' : 'Gap in pts') + '</button><button type="button" class="pd-t" data-m="idx">' + (w < 340 ? 'Price' : 'Price index') + '</button></div></div>'
      + '<div class="pd-plot" tabindex="0" aria-label="Diverging bars; arrow keys move, Enter opens products, Escape goes back"></div>';
    const leadEl = el.querySelector('.pd-lead'), subEl = el.querySelector('.pd-sub'), crumbsEl = el.querySelector('.pd-crumbs');
    const plot = el.querySelector('.pd-plot');
    const narrow = w < 400;
    el.classList.toggle('pd-narrow', narrow);

    function headFor(L) {
      const sorted = L.list.slice().sort((a, b) => val(b) - val(a));
      const hi = sorted[0], lo = sorted[sorted.length - 1];
      const where = drill ? 'Within ' + drill + ', ' : '';
      const one = !!drill;   // a product name is singular, an item type name plural
      const take = one ? ' takes ' : ' take ', sell = one ? ' sells at ' : ' sell at ';
      if (L.list.length < 2) return drill ? 'Only one product of ' + drill + ' is in the current filter' : 'Only ' + hi.name + ' is in the current filter';
      if (mode === 'gap') {
        return where + hi.name + take + AZ.pct(hi.ss, 1) + ' of sales from ' + AZ.pct(hi.us, 1) + ' of units; '
          + lo.name + take + AZ.pct(lo.ss, 1) + ' of sales from ' + AZ.pct(lo.us, 1) + ' of units';
      }
      const rel = (o) => Math.abs(o.idx * 100).toFixed(0) + '% ' + (o.idx >= 0 ? 'above' : 'below');
      return where + hi.name + sell + money2(hi.p) + ' a unit, ' + rel(hi) + ' the ' + money2(L.avgP) + ' average; '
        + lo.name + ' at ' + money2(lo.p) + ', ' + rel(lo);
    }
    function subFor(L, shown) {
      const what = mode === 'gap' ? 'Share of ' + (drill ? drill + ' ' : '') + 'sales minus share of units, in points.' : 'Price per unit against the ' + (drill ? drill : 'overall') + ' average.';
      const side = mode === 'gap' ? ' Right: premium, left: volume.' : ' Right: above it, left: below.';
      const n = shown == null ? L.list.length : shown;
      let more = '';
      if (drill) more = L.all > n ? ' The ' + n + ' of ' + L.all + ' products with the largest gaps.' : '';
      else more = n < L.list.length ? ' The ' + n + ' largest of ' + L.list.length + '.' : '';
      return what + side + more;
    }
    function paintControls(L) {
      leadEl.textContent = headFor(L);
      subEl.textContent = subFor(L);
      const hint = drill ? 'Esc to go back' : pK && L.list.length > 1 ? 'Click a bar for its products' : '';
      crumbsEl.innerHTML = AZ.crumbs(drill ? ['All item types', drill] : ['All item types']) + (hint && !narrow ? '<span class="pd-hint">' + hint + '</span>' : '');
      AZ.wireCrumbs(crumbsEl, () => go(null));
      el.querySelectorAll('.pd-t').forEach((b) => { const on = b.getAttribute('data-m') === mode; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false'); });
    }

    // ---- Muze --------------------------------------------------------------
    let shrink = 0;   // rows to drop when Muze still scrolls (its band floor is not a constant)
    let canvas = null, canvasLevel = null, geo = [], cur = null, ov = null, hover = -1, token = 0;
    const tip = AZ.tip(plot);
    const timers = [], anim = AZ.animator();
    const later = (fn, ms) => { const t = setTimeout(fn, ms); timers.push(t); return t; };
    const schemaM = [{ name: 'Label', type: 'dimension' }, { name: 'Value', type: 'measure', defAggFn: 'sum' }];
    const tick = (d) => {
      const v = Math.round(Number(d && typeof d === 'object' ? d.rawValue : d) * 10) / 10;
      if (!isFinite(v)) return String(d);
      const s = v > 0 ? '+' : v < 0 ? '-' : '';
      return mode === 'gap' ? s + Math.abs(v) + (narrow || v === 0 ? '' : ' pts') : s + Math.abs(v) + '%';
    };
    const cfg = (order) => ({
      legend: { show: false }, useExternalCSS: true,
      autoGroupBy: { disabled: true },
      gridLines: { show: false, x: { show: false }, y: { show: false } },
      axes: {
        x: { show: false, showAxisName: false, name: '', numberOfTicks: narrow ? 3 : 5, tickFormat: tick },
        y: { show: false, showAxisName: false, padding: 0.28, ordering: { type: 'custom', values: order } }
      },
      border: { style: 'none', showRowBorders: { top: false, bottom: false, left: false, right: false }, showColBorders: { top: false, bottom: false, left: false, right: false }, showValueBorders: { top: false, bottom: false, left: false, right: false } }
    });
    const layer = (still) => ({
      mark: 'bar',
      transition: still ? { disabled: true } : { effect: 'cubic', duration: DUR },
      encodingTransform: (points, lyr) => {
        const res = lyr.data().getData(), names = res.schema.map((s) => s.name), li = names.indexOf('Label'), vi = names.indexOf('Value');
        const g = [];
        points.forEach((p, i) => {
          const row = res.data[i] || [], name = String(row[li]);
          p.style = Object.assign(p.style || {}, { fill: colorOf(name) });
          const u = p.update || {};
          g.push({ name, v: Number(row[vi]), x: u.x, y: u.y, w: u.width, h: u.height });
        });
        geo = g;
        return points;
      }
    });

    function dropCanvas() {
      if (canvas) { try { canvas.dispose(); } catch (e) {} }
      canvas = null; geo = [];
      plot.querySelectorAll('.pd-muze, .pd-axis, .pd-ruler').forEach((n) => n.remove());
      if (ov) { ov.remove(); ov = null; }
    }
    function message(L) {
      dropCanvas();
      geo = []; cur = null;
      const one = L.list[0];
      plot.innerHTML = '';
      const box = document.createElement('div'); box.className = 'pd-msg';
      if (!drill) {
        box.innerHTML = '<p>With one item type in the filter, it holds 100% of sales and of units, so there is no gap to show at this level.</p>'
          + (pK ? '<button type="button" class="pd-go">Compare ' + AZ.esc(one.name) + ' products</button>' : '');
      } else {
        box.innerHTML = '<p>' + AZ.esc(one ? one.name : 'This item type') + ' is the only product of ' + AZ.esc(drill) + ' in the filter, so it holds all of its sales and units.</p><button type="button" class="pd-go">Back to all item types</button>';
      }
      plot.appendChild(box);
      const b = box.querySelector('.pd-go');
      if (b) b.addEventListener('click', () => go(drill ? null : one.name));
      plot.appendChild(tip.el);
    }

    function show() {
      const L = levelData();
      paintControls(L);
      tip.hide(); hover = -1;
      if (L.list.length < 2) { message(L); return; }
      // Muze needs about 18 px a row; in a short tile keep the rows with the largest gaps and say so
      const roomNow = () => Math.max(2, Math.floor((plot.clientHeight - AXIS_H - 2) / 17.8) - shrink);
      let room = roomNow();
      if (L.list.length > room) {
        subEl.textContent = subFor(L, room);   // the note can add a line, so measure again
        room = roomNow();
        subEl.textContent = subFor(L, room);
        room = Math.min(room, roomNow());
      }
      let pick = L.list;
      if (pick.length > room) pick = pick.slice().sort((a, b) => Math.abs(val(b)) - Math.abs(val(a))).slice(0, room);
      const list = pick.slice().sort((a, b) => val(b) - val(a));
      cur = { L, list, byName: new Map(list.map((o) => [o.name, o])) };
      const dm = new DataModel(DataModel.loadDataSync(list.map((o) => ({ Label: o.name, Value: val(o) })), schemaM));
      const order = list.map((o) => o.name);
      const my = ++token;
      if (ov) { const old = ov; AZ.tween(160, (k) => { old.style.opacity = String(1 - k); }, () => old.remove()); ov = null; }
      const level = drill || '';
      // Same level, new measure: remount without Muze's entrance and morph each bar from where it was (by name).
      // (Updating the data of a mounted canvas throws inside this Muze build, so every change remounts.)
      const prev = canvas && canvasLevel === level && geo.length ? new Map(geo.map((g) => [g.name, g])) : null;
      dropCanvas();
      canvasLevel = level;
      plot.querySelectorAll('.pd-msg').forEach((n) => n.remove());
      const W = Math.max(200, Math.round(plot.clientWidth)), H = Math.max(100, Math.round(plot.clientHeight) - AXIS_H);
      const mnt = document.createElement('div'); mnt.className = 'pd-muze'; mnt.style.width = W + 'px'; mnt.style.height = H + 'px';
      if (prev) mnt.style.opacity = '0';
      plot.insertBefore(mnt, tip.el);
      const ax = document.createElement('div'); ax.className = 'pd-axis'; plot.insertBefore(ax, tip.el);
      canvas = muze.canvas().data(dm).width(W).height(H).minUnitHeight(1).minUnitWidth(1)
        .rows(['Label']).columns(['Value']).layers([layer(!!prev)]).config(cfg(order)).mount(mnt);
      // Overlays (zero line, names, values, grid) use the final geometry captured in encodingTransform.
      let n = 0;
      const tryDraw = () => {
        if (my !== token) return;
        const layerG = plot.querySelector('.muze-layer-bar');
        const rects = barRects();
        if (layerG && geo.length === list.length && geo.every((g) => isFinite(g.x)) && rects.length === geo.length) {
          if (plot.querySelector('.muze-scroll-bar') && list.length > 2) { shrink++; return show(); }
          if (!prev) return overlay(layerG, my);
          return morph(rects, prev, () => overlay(layerG, my), mnt);
        }
        if (n++ < 40) later(tryDraw, 80); else mnt.style.opacity = '1';
      };
      later(tryDraw, prev ? 0 : 60);
    }
    // The bar rects Muze drew, indexed like the points in encodingTransform (group class muze-layer-bar-0-<i>).
    function barRects() {
      const out = [];
      plot.querySelectorAll('.muze-layer-bar rect').forEach((r) => {
        const m = /muze-layer-bar-\d+-(\d+)/.exec((r.parentNode && r.parentNode.getAttribute('class')) || '');
        if (m) out[Number(m[1])] = r;
      });
      return out.filter(Boolean);
    }
    let finishMorph = null;
    function morph(rects, prev, done, mnt) {
      const to = geo.map((g) => ({ x: g.x, y: g.y, w: g.w, h: g.h }));
      const from = geo.map((g, i) => { const p = prev.get(g.name); return p ? { x: p.x, y: p.y, w: p.w, h: p.h, o: 1 } : { x: to[i].x, y: to[i].y, w: to[i].w, h: to[i].h, o: 0 }; });
      const set = (k) => rects.forEach((r, i) => {
        const a = from[i], b = to[i];
        r.setAttribute('x', AZ.lerp(a.x, b.x, k)); r.setAttribute('y', AZ.lerp(a.y, b.y, k));
        r.setAttribute('width', Math.max(0, AZ.lerp(a.w, b.w, k))); r.setAttribute('height', Math.max(0, AZ.lerp(a.h, b.h, k)));
        if (!a.o) r.style.opacity = String(k);
      });
      set(0); mnt.style.opacity = '1';
      // A click or a paused frame never leaves the bars half way: the end state is known, and a timer finishes it.
      let fin = false, cancel = null;
      const finish = () => { if (fin) return; fin = true; clearTimeout(guard); if (cancel) cancel(); set(1); finishMorph = null; done(); };
      const guard = later(finish, DUR + 400);
      finishMorph = finish;
      cancel = anim(DUR, set, finish, AZ.EASE.inOut);
    }

    function overlay(layerG, my) {
      const host = layerG.parentNode;
      const g = svgEl('g', { class: 'pd-ov', 'pointer-events': 'none' }, host);
      g.style.opacity = '0';
      ov = g;
      const bars = geo.map((q) => Object.assign({}, q, { o: cur.byName.get(q.name) })).filter((q) => q.o);
      // zero pixel: the start of any positive bar or the end of any negative one
      const pos = bars.find((q) => q.v > 0), neg = bars.find((q) => q.v < 0);
      const x0 = pos ? pos.x : neg ? neg.x + neg.w : 0;
      const clip = layerG.closest('svg');
      const W = clip ? Number(clip.getAttribute('width')) || clip.getBoundingClientRect().width : plot.clientWidth;
      let yMin = Infinity, yMax = -Infinity;
      bars.forEach((q) => { yMin = Math.min(yMin, q.y); yMax = Math.max(yMax, q.y + q.h); });
      svgEl('line', { x1: x0, x2: x0, y1: yMin - 6, y2: yMax + 6, stroke: AZ.T.ink, 'stroke-width': 1.25 }, g);
      const CH = 6.2, fs = bars[0] && bars[0].h < 13 ? 11 : 12;
      bars.forEach((q) => {
        const right = q.v >= 0;
        const end = right ? q.x + q.w : q.x;
        const txt = fmtVal(q.v);
        const tw = txt.length * CH + 4;
        const inside = q.w > tw + 10;
        const vt = svgEl('text', { class: 'pd-v', y: q.y + q.h / 2, dy: '0.35em', 'font-size': 11, 'text-anchor': inside === right ? 'end' : 'start',
          x: inside ? (right ? end - 5 : end + 5) : (right ? end + 4 : end - 4), fill: inside ? '#FFFFFF' : AZ.T.ink2 }, g);
        vt.textContent = txt;
        // name on the other side of zero, where this row is empty
        const room = right ? x0 - 8 : W - x0 - 8;
        const nm = svgEl('text', { class: 'pd-n', y: q.y + q.h / 2, dy: '0.35em', 'font-size': fs, 'text-anchor': right ? 'end' : 'start', x: right ? x0 - 6 : x0 + 6, fill: AZ.T.ink }, g);
        nm.textContent = trunc(q.name, Math.floor(room / CH));
        q.vt = vt; q.nm = nm;
      });
      cur.bars = bars.sort((a, b) => a.y - b.y);
      // pixels per unit, from the longest bar; the axis labels are ours (Muze's x axis is hidden, see cfg)
      const big = bars.reduce((a, q) => (Math.abs(q.v) > Math.abs(a.v) ? q : a), bars[0]);
      cur.x0 = x0; cur.k = big && big.v ? big.w / Math.abs(big.v) : 0;
      drawGrid(host, layerG, x0, cur.k, W, yMin, yMax);
      AZ.tween(300, (k) => { if (my === token) g.style.opacity = String(k); }, null, AZ.EASE.out);
    }

    // Grid and axis labels are ours: Muze's x axis is hidden (its label row made the plot scroll) and its
    // grid lines are off, so both follow the same zero and scale as the bars.
    function drawGrid(host, layerG, x0, k, W, yMin, yMax) {
      const old = host.querySelector('.pd-grid'); if (old) old.remove();
      const ax = plot.querySelector('.pd-axis');
      if (ax) ax.innerHTML = '';
      if (!k) return;
      const lo = -x0 / k, hi = (W - x0) / k, want = w < 320 ? 3 : w < 460 ? 4 : 5;
      const raw = (hi - lo) / want, p10 = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p10;
      const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p10;
      const gg = svgEl('g', { class: 'pd-grid', 'pointer-events': 'none' });
      host.insertBefore(gg, layerG);
      const ctm = layerG.getScreenCTM(), pr = plot.getBoundingClientRect();
      for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
        const x = x0 + v * k;
        if (Math.abs(v) > 1e-9) svgEl('line', { x1: x, x2: x, y1: yMin - 6, y2: yMax + 6, stroke: AZ.T.grid, 'stroke-width': 1 }, gg);
        if (ax && ctm) {
          const t = document.createElement('span');
          t.textContent = tick(Math.round(v * 100) / 100);
          ax.appendChild(t);
          const sx = new DOMPoint(x, 0).matrixTransform(ctm).x - pr.left, hw = t.offsetWidth / 2;
          t.style.left = Math.round(Math.max(hw, Math.min(plot.clientWidth - hw, sx))) + 'px';
        }
      }
    }

    // ---- hover, click, keys -------------------------------------------------
    function rowAt(clientY) {
      if (!cur || !cur.bars || !cur.bars.length) return -1;
      const lg = plot.querySelector('.muze-layer-bar'); if (!lg) return -1;
      const ctm = lg.getScreenCTM(); if (!ctm) return -1;
      let best = -1, bd = Infinity;
      cur.bars.forEach((q, i) => { const cy = new DOMPoint(0, q.y + q.h / 2).matrixTransform(ctm).y; const d = Math.abs(cy - clientY); if (d < bd) { bd = d; best = i; } });
      const band = cur.bars.length > 1 ? Math.abs(new DOMPoint(0, cur.bars[1].y).matrixTransform(ctm).y - new DOMPoint(0, cur.bars[0].y).matrixTransform(ctm).y) : 40;
      return bd <= band * 0.6 + 2 ? best : -1;
    }
    function paintHover(i) {
      hover = i;
      const rects = [...plot.querySelectorAll('.muze-layer-bar rect')].filter((r) => r.parentNode && /muze-layer-bar-\d+-\d+/.test(r.parentNode.getAttribute('class') || ''));
      const hy = i >= 0 && cur && cur.bars ? cur.bars[i].y : null;
      rects.forEach((r) => { const y = Number(r.getAttribute('y')); r.style.opacity = hy == null || Math.abs(y - hy) < 0.5 ? '1' : '0.25'; });
      if (cur && cur.bars) cur.bars.forEach((q, j) => { const o = i < 0 || j === i ? '1' : '0.3'; q.vt.style.opacity = o; q.nm.style.opacity = o; q.nm.style.fontWeight = j === i ? '600' : ''; });
    }
    function tipFor(q) {
      const o = q.o, L = cur.L, of = drill ? drill + ' ' : '';
      let h = '<b>' + AZ.esc(o.name) + '</b>'
        + AZ.row('Share of ' + of + 'sales', AZ.pct(o.ss, 1), colorOf(o.name))
        + AZ.row('Share of ' + of + 'units', AZ.pct(o.us, 1))
        + AZ.row('Gap', AZ.pts(o.gap))
        + AZ.row('Price per unit', money2(o.p))
        + AZ.row(drill ? drill + ' average' : 'Overall average', money2(L.avgP))
        + AZ.row('Price index', AZ.pct(o.idx, 0, true));
      if (!drill && pK) h += '<div class="pd-tiphint">Click for its products</div>';
      return h;
    }
    function showTipAt(i, clientX, clientY) {
      const q = cur.bars[i], r = plot.getBoundingClientRect();
      tip.show(tipFor(q), clientX - r.left, clientY - r.top);
    }
    plot.addEventListener('mousemove', (e) => {
      const i = rowAt(e.clientY);
      if (i < 0) { if (hover >= 0) { paintHover(-1); tip.hide(); } return; }
      if (i !== hover) paintHover(i);
      ruler(e.clientX);
      showTipAt(i, e.clientX, e.clientY);
      plot.style.cursor = !drill && pK ? 'pointer' : 'default';
    });
    plot.addEventListener('mouseleave', () => { paintHover(-1); tip.hide(); ruler(null); });
    // A thin ruler under the pointer with its value on the axis, for reading any bar against the scale.
    function ruler(clientX) {
      let rl = plot.querySelector('.pd-ruler');
      const lg = plot.querySelector('.muze-layer-bar'), mnt = plot.querySelector('.pd-muze'), ax = plot.querySelector('.pd-axis');
      if (clientX == null || !lg || !mnt || !ax || !cur || !cur.k) { if (rl) rl.style.opacity = '0'; return; }
      const ctm = lg.getScreenCTM(); if (!ctm) return;
      if (!rl) { rl = document.createElement('div'); rl.className = 'pd-ruler az-tip-free'; rl.innerHTML = '<i></i><b></b>'; plot.insertBefore(rl, tip.el); }
      const pr = plot.getBoundingClientRect(), zx = new DOMPoint(cur.x0, 0).matrixTransform(ctm).x, k = cur.k * (ctm.a || 1);
      const x = clientX - pr.left, v = Math.round(((clientX - zx) / k) * 10) / 10;
      rl.style.left = Math.round(x) + 'px'; rl.style.height = (mnt.offsetHeight + AXIS_H) + 'px'; rl.style.opacity = '1';
      rl.querySelector('b').textContent = tick(v);
    }
    plot.addEventListener('click', (e) => {
      if (e.target.closest && e.target.closest('.pd-msg')) return;
      const i = rowAt(e.clientY);
      if (i >= 0 && !drill && pK) go(cur.bars[i].name);
    });
    plot.addEventListener('keydown', (e) => {
      if (!cur || !cur.bars) { if (e.key === 'Escape' && drill) go(null); return; }
      const n = cur.bars.length;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const i = hover < 0 ? 0 : Math.max(0, Math.min(n - 1, hover + (e.key === 'ArrowDown' ? 1 : -1)));
        paintHover(i);
        const lg = plot.querySelector('.muze-layer-bar'), ctm = lg && lg.getScreenCTM();
        if (ctm) { const q = cur.bars[i], p = new DOMPoint(q.x + q.w, q.y + q.h / 2).matrixTransform(ctm); showTipAt(i, p.x, p.y); }
      } else if ((e.key === 'Enter' || e.key === ' ') && hover >= 0 && !drill && pK) { e.preventDefault(); go(cur.bars[hover].name); }
      else if (e.key === 'Escape' && drill) { e.preventDefault(); go(null); }
    });
    const onKey = (e) => { if (e.key === 'Escape' && drill && el.contains(document.activeElement)) { go(null); } };
    el.addEventListener('keydown', (e) => { if (e.target !== plot) onKey(e); });

    function go(item) { if (finishMorph) finishMorph(); drill = item; show(); }
    el.querySelectorAll('.pd-t').forEach((b) => b.addEventListener('click', () => { const m = b.getAttribute('data-m'); if (m === mode) return; if (finishMorph) finishMorph(); mode = m; show(); }));

    await AZ.settle();
    show();
    // let the entrance finish before render-complete, so the first screenshot is the settled chart
    await new Promise((res) => later(res, DUR + 150));
    return () => { token++; anim.stop(); timers.forEach(clearTimeout); try { if (canvas) canvas.dispose(); } catch (e) {} };
  }
});
