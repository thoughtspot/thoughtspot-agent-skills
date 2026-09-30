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

// Search: [sales] [quantity purchased] [state]   (columns arrive as "state", "Total sales", "Total quantity purchased")
// Interactions: hover a dot for its tooltip; click a dot to pin it (the others dim); click the background to clear.
let pinned = null;

AZ.boot({
  need: 'sales and units by state, e.g. [sales] [quantity purchased] [state]',
  render: async ({ el, rows, schema }) => {
    const { muze } = AZ.host();
    const { DataModel } = muze;
    const kState = AZ.col(schema, /state/i), kSales = AZ.col(schema, /sales/i), kUnits = AZ.col(schema, /quantity|units/i);

    const pts = rows.map((r) => ({ s: String(r[kState]), v: AZ.num(r[kSales]), u: AZ.num(r[kUnits]) }))
      .filter((p) => p.u > 0);
    if (pts.length < 2) throw new Error('Need at least 2 states with units, got ' + pts.length);
    const totV = pts.reduce((a, p) => a + p.v, 0), totU = pts.reduce((a, p) => a + p.u, 0);
    const avg = totV / totU;
    pts.forEach((p) => { p.ppu = p.v / p.u; });
    const byU = pts.slice().sort((a, b) => b.u - a.u);
    const top2 = byU.slice(0, 2), top2Share = (top2[0].u + top2[1].u) / totU;
    const lo = pts.reduce((a, p) => (p.ppu < a.ppu ? p : a)), hi = pts.reduce((a, p) => (p.ppu > a.ppu ? p : a));
    if (pinned && !pts.some((p) => p.s === pinned)) pinned = null;

    const lead = top2[0].s + ' and ' + top2[1].s + ' sell ' + AZ.pct(top2Share, 0) + ' of all units across ' + pts.length + ' states.';
    const sub = 'Sales per unit only runs from ' + AZ.money(lo.ppu, 2) + ' (' + lo.s + ') to ' + AZ.money(hi.ppu, 2) + ' (' + hi.s + '), so volume decides sales. Dashed line: the ' + AZ.money(avg, 2) + ' average.';
    el.innerHTML = '<div class="sc-head"><p class="sc-lead">' + AZ.esc(lead) + '</p><p class="sc-sub">' + AZ.esc(sub) + '</p></div><div class="sc-plot" id="sc-plot"></div>';
    await AZ.settle();

    const dm = new DataModel(DataModel.loadDataSync(pts.map((p) => ({ State: p.s, Units: p.u, Sales: p.v })), [
      { name: 'State', type: 'dimension' },
      { name: 'Units', type: 'measure', defAggFn: 'sum' },
      { name: 'Sales', type: 'measure', defAggFn: 'sum' }
    ]));
    const plot = document.getElementById('sc-plot');
    const pr = plot.getBoundingClientRect();
    const fmtAxis = (f) => (d) => f(d && typeof d === 'object' ? d.rawValue : d);
    const canvas = muze.canvas()
      .data(dm)
      .width(Math.max(240, Math.round(pr.width))).height(Math.max(160, Math.round(pr.height)))
      .rows(['Sales']).columns(['Units'])
      .detail(['State'])
      .layers([{ mark: 'point', encoding: { color: { value: () => AZ.T.ink }, size: { value: () => 0.05 } } }])
      .config({
        legend: { show: false },
        gridLines: { x: { show: false }, y: { show: true }, color: AZ.T.grid },
        axes: {
          x: { showAxisName: false, numberOfTicks: 5, tickFormat: fmtAxis((n) => AZ.int(n)) },
          y: { showAxisName: false, numberOfTicks: 4, tickFormat: fmtAxis((n) => AZ.money(n, 0)) }
        }
      })
      .mount(plot);

    // Wait until Muze has drawn every dot, then read their centres.
    const dots = () => [...plot.querySelectorAll('[class*="muze-layer-point"] path, [class*="muze-layer-point"] circle')];
    await new Promise((res) => {
      let n = 0; const tick = () => { if (dots().length >= pts.length || n++ > 40) return res(); setTimeout(tick, 100); };
      canvas.once('afterRendered', tick); setTimeout(tick, 400);
    });

    // Match dots to states by rank on x: x is units, and units differ between states.
    const pb = () => plot.getBoundingClientRect();
    const centre = (d) => { const r = d.getBoundingClientRect(), b = pb(); return [r.x + r.width / 2 - b.x, r.y + r.height / 2 - b.y]; };
    const ds = dots().map((d) => ({ d, c: centre(d) })).sort((a, b) => a.c[0] - b.c[0]);
    const byUAsc = pts.slice().sort((a, b) => a.u - b.u);
    ds.forEach((o, i) => { if (byUAsc[i]) byUAsc[i].dot = o.d; });
    ds.forEach((o) => { o.d.style.fill = AZ.T.ink; o.d.style.fillOpacity = '0.85'; o.d.style.stroke = '#fff'; o.d.style.strokeWidth = '1'; });

    // Linear pixel scales from the two extreme dots, to draw the average line in data terms.
    const a0 = byUAsc[0], a1 = byUAsc[byUAsc.length - 1];
    const c0 = centre(a0.dot), c1 = centre(a1.dot);
    const sx = (u) => c0[0] + (u - a0.u) * (c1[0] - c0[0]) / (a1.u - a0.u);
    const sy = (v) => c0[1] + (v - a0.v) * (c1[1] - c0[1]) / (a1.v - a0.v);

    const NS = 'http://www.w3.org/2000/svg';
    const over = document.createElementNS(NS, 'svg'); over.setAttribute('class', 'sc-over');
    plot.appendChild(over);
    const mk = (tag, attrs, parent) => { const n = document.createElementNS(NS, tag); Object.keys(attrs).forEach((k) => n.setAttribute(k, attrs[k])); (parent || over).appendChild(n); return n; };
    const uA = a0.u * 0.92, uB = a1.u * 1.02;
    mk('line', { class: 'sc-avg', x1: sx(uA), y1: sy(avg * uA), x2: sx(uB), y2: sy(avg * uB) });
    const labels = mk('g', {}), ring = mk('circle', { class: 'sc-ring', r: 7, opacity: 0 });

    const draw = () => {
      labels.innerHTML = '';
      const show = pinned ? [pts.find((p) => p.s === pinned)] : byU.slice(0, 2);
      show.forEach((p, i) => {
        const [x, y] = centre(p.dot), right = x > plot.clientWidth * 0.6;
        const t = mk('text', { x: x + (right ? -10 : 10), y: y + (i === 1 && !pinned ? 14 : -8), 'text-anchor': right ? 'end' : 'start' }, labels);
        t.textContent = p.s;
      });
      pts.forEach((p) => { p.dot.style.fillOpacity = !pinned || p.s === pinned ? '0.85' : '0.25'; });
    };
    draw();

    const tip = AZ.tip(plot);
    const nearest = (e) => {
      const b = pb(), mx = e.clientX - b.x, my = e.clientY - b.y;
      let best = null, bd = 24 * 24;
      pts.forEach((p) => { const [x, y] = centre(p.dot), d = (x - mx) * (x - mx) + (y - my) * (y - my); if (d < bd) { bd = d; best = p; } });
      return best;
    };
    plot.addEventListener('mousemove', (e) => {
      const p = nearest(e);
      if (!p) { tip.hide(); ring.setAttribute('opacity', 0); plot.style.cursor = ''; return; }
      const [x, y] = centre(p.dot);
      ring.setAttribute('cx', x); ring.setAttribute('cy', y); ring.setAttribute('opacity', 1); plot.style.cursor = 'pointer';
      tip.show('<b>' + AZ.esc(p.s) + '</b>' + AZ.row('Sales', AZ.money(p.v, 1)) + AZ.row('Units', AZ.int(p.u)) + AZ.row('Sales per unit', AZ.money(p.ppu, 2)) + AZ.row('Against average', AZ.pct(p.ppu / avg - 1, 1, true)), x, y);
    });
    plot.addEventListener('mouseleave', () => { tip.hide(); ring.setAttribute('opacity', 0); });
    plot.addEventListener('click', (e) => { const p = nearest(e); pinned = p && p.s !== pinned ? p.s : null; draw(); });
    return () => { try { canvas.dispose && canvas.dispose(); } catch (e) {} };
  }
});
