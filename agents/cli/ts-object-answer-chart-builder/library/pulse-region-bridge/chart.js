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

// Search: [sales] [region] [state] [date].quarterly
// YTD bridge: last year's YTD total, each region's change (same quarters, latest year vs the year before), this year's YTD total.
// Interactions: hover a row for the numbers. Click a region step (or press Enter) to open it: the step splits into its
// states and the bridge re-scales to that region (crumbs, Back or Escape return). Click a total, or a state, to isolate
// it (dims the rest); click again or use Show all to clear.
let sel = null, openReg = null;

AZ.boot({
  need: 'sales by region, state and quarter, e.g. [sales] [region] [state] [date].quarterly',
  render: async ({ el, rows, schema, w, h }) => {
    const rK = AZ.col(schema, /region/i), stK = AZ.col(schema, /state/i), dK = AZ.col(schema, /date|quarter/i), sK = AZ.col(schema, /sales/i);
    const M = rows.map((r) => ({ g: String(r[rK]), st: String(r[stK]), t: AZ.ms(r[dK]), v: AZ.num(r[sK]) })).filter((r) => isFinite(r.t));
    if (!M.length) throw new Error('No quarters in the result');
    const last = Math.max.apply(null, M.map((r) => r.t)), ly = AZ.year(last), lq = Math.floor(new Date(last).getUTCMonth() / 3);
    const ST = new Map();
    const nCur = new Set(), nPrev = new Set();
    M.forEach((r) => {
      const d = new Date(r.t), y = d.getUTCFullYear(), q = Math.floor(d.getUTCMonth() / 3);
      if (q > lq || (y !== ly && y !== ly - 1)) return;
      const k = r.g + '||' + r.st;
      if (!ST.has(k)) ST.set(k, { g: r.st, region: r.g, cur: 0, prev: 0 });
      const o = ST.get(k);
      if (y === ly) { o.cur += r.v; nCur.add(q); } else { o.prev += r.v; nPrev.add(q); }
    });
    const states = Array.from(ST.values()).map((o) => Object.assign(o, { d: o.cur - o.prev }));
    const RG = new Map();
    states.forEach((o) => { if (!RG.has(o.region)) RG.set(o.region, { g: o.region, cur: 0, prev: 0, kids: [] }); const r = RG.get(o.region); r.cur += o.cur; r.prev += o.prev; r.kids.push(o); });
    const regions = Array.from(RG.values()).map((o) => Object.assign(o, { d: o.cur - o.prev })).sort((a, b) => b.d - a.d);
    regions.forEach((r) => r.kids.sort((a, b) => b.d - a.d));
    const span = 'Jan to ' + AZ.MON[lq * 3 + 2];
    if (!nPrev.size || !nCur.size || !regions.length) {
      AZ.paint(el, '<div class="az-empty"><b>No year-on-year bridge</b><span>The current filter has no ' + span + ' in both ' + (ly - 1) + ' and ' + ly + '. Search: [sales] [region] [state] [date].quarterly</span></div>');
      return;
    }
    if (openReg && !RG.has(openReg)) openReg = null;
    const comparable = nCur.size === nPrev.size;
    const capNote = comparable ? '' : ' Prior year has ' + nPrev.size + ' of ' + nCur.size + ' quarters.';
    const signed = (n, d) => (n > 0 ? '+' : n < 0 ? '-' : '') + AZ.money(Math.abs(n), d == null ? 1 : d);
    const pctS = (x) => (x == null ? 'n/a' : AZ.pct(x, 1, true));
    const cls = (n) => (n >= 0 ? 'up' : 'dn');

    el.innerHTML = '<div class="br-head"><div class="br-title"></div><div class="br-line"></div></div><div class="br-crumbrow"></div><div class="br-plot" id="br-plot"></div>'
      + '<div class="br-key"><span><i style="background:' + AZ.T.slate[4] + '"></i>YTD total</span><span><i style="background:' + AZ.T.ink + '"></i>Increase</span><span><i style="border:1.5px solid ' + AZ.T.slate[6] + ';background:' + AZ.T.slate[1] + '"></i>Decrease</span>'
      + '<button type="button" class="br-clear" id="br-clear" style="visibility:hidden">Show all</button></div><div class="br-key br-cap"></div>';
    const titleEl = el.querySelector('.br-title'), lineEl = el.querySelector('.br-line'), crumbEl = el.querySelector('.br-crumbrow'), capEl = el.querySelector('.br-cap');
    const plot = document.getElementById('br-plot'), clear = document.getElementById('br-clear');
    const flash = (n) => { n.classList.remove('br-fade'); void n.offsetWidth; n.classList.add('br-fade'); };

    // Rows for one level: prior total, steps, current total.
    const layoutFor = (reg) => {
      const src = reg ? RG.get(reg).kids : regions;
      const totPrev = src.reduce((x, o) => x + o.prev, 0), totCur = src.reduce((x, o) => x + o.cur, 0);
      const R = [{ k: '__p', label: ly - 1 + ' YTD', total: true, from: null, to: totPrev }];
      let run = totPrev;
      src.forEach((o) => { R.push({ k: reg ? 'st:' + o.g : o.g, label: o.g, o, from: run, to: run + o.d }); run += o.d; });
      R.push({ k: '__c', label: ly + ' YTD', total: true, from: null, to: totCur });
      const vals = R.map((r) => r.to).concat([totPrev]);
      const hi0 = Math.max.apply(null, vals), lo0 = Math.min.apply(null, vals), rg = (hi0 - lo0) || Math.max(1, hi0 * 0.05);
      const lo = lo0 - rg * 0.55, hi = hi0 + rg * 0.1;
      return { reg, R, src, totPrev, totCur, net: totCur - totPrev, lo, hi };
    };
    const W = Math.max(120, plot.clientWidth), H = Math.max(80, plot.clientHeight);
    const labW = W < 300 ? 70 : 84, valW = W < 300 ? 58 : 66, gap = 8;
    const x0 = labW + gap, x1 = W - valW - gap;
    const geoOf = (L) => {
      const sx = (v) => x0 + (v - L.lo) / (L.hi - L.lo) * (x1 - x0);
      const rowH = H / L.R.length, bh = Math.min(22, Math.max(12, rowH * 0.5));
      const G = {};
      L.R.forEach((r, i) => {
        const a = r.total ? L.lo : Math.min(r.from, r.to), b = r.total ? r.to : Math.max(r.from, r.to);
        const xa = sx(a), xb = Math.max(sx(b), xa + 2);
        G[r.k] = { y: rowH * i + rowH / 2, h: bh, x: xa, w: xb - xa, ex: sx(r.to), rh: rowH, op: sel != null && r.k !== sel ? 0.25 : 1 };
      });
      L.G = G; L.rowH = rowH; L.bh = bh;
      return L;
    };

    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg'); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.setAttribute('width', W); svg.setAttribute('height', H);
    svg.innerHTML = '<defs><pattern id="br-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="' + AZ.T.slate[0] + '"/><line x1="0" y1="0" x2="0" y2="6" stroke="' + AZ.T.slate[3] + '" stroke-width="2"/></pattern></defs><g class="conns"></g><g class="rows"></g>';
    plot.appendChild(svg);
    const connG = svg.querySelector('.conns'), rowG = svg.querySelector('.rows');
    const tipRoot = document.createElement('div'); tipRoot.style.cssText = 'position:absolute;left:0;top:0;right:0;bottom:0;pointer-events:none'; el.style.position = 'relative'; el.appendChild(tipRoot);
    const tip = AZ.tip(tipRoot);

    // ---- row elements (one per key) -------------------------------------------------------------
    const els = {};
    const mkRow = (r) => {
      const g = document.createElementNS(NS, 'g');
      g.setAttribute('class', 'br-row'); g.setAttribute('data-k', r.k); g.setAttribute('tabindex', 0); g.setAttribute('role', 'button');
      const inc = !r.total && r.o.d >= 0;
      const valTxt = r.total ? AZ.money(r.to, 1) : signed(r.o.d), col = r.total ? AZ.T.ink : (r.o.d >= 0 ? AZ.T.good : AZ.T.bad);
      g.setAttribute('aria-label', r.label + ' ' + valTxt + (r.total || openReg ? '' : ', open its states'));
      g.innerHTML = '<rect class="br-hit" x="0" rx="6"/>'
        + '<text class="lab" x="' + labW + '" y="4" text-anchor="end" font-size="12" fill="' + AZ.T.ink + '" font-weight="' + (r.total ? 600 : 500) + '">' + AZ.esc(r.label) + '</text>'
        + '<rect class="bar" rx="2"/>' + (r.total ? '<path class="tk" stroke="#fff" stroke-width="2" fill="none"/>' : '')
        + '<text class="val" x="' + W + '" y="4" text-anchor="end" font-size="12" font-weight="600" fill="' + col + '">' + AZ.esc(valTxt) + '</text>';
      const bar = g.querySelector('.bar');
      if (r.total) bar.setAttribute('fill', AZ.T.slate[4]);
      else if (inc) bar.setAttribute('fill', AZ.T.ink);
      else { bar.setAttribute('fill', 'url(#br-hatch)'); bar.setAttribute('stroke', AZ.T.slate[6]); bar.setAttribute('stroke-width', 1.5); }
      g.addEventListener('mousemove', (e) => { const rr = curL.R.find((x) => x.k === r.k); if (!rr) return; const b = el.getBoundingClientRect(); tip.show(html(rr), e.clientX - b.left, e.clientY - b.top); });
      g.addEventListener('mouseleave', () => tip.hide());
      g.addEventListener('click', () => activate(r.k));
      g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(r.k); } });
      rowG.appendChild(g);
      els[r.k] = { g, bar, hit: g.querySelector('.br-hit'), tk: g.querySelector('.tk'), lab: g.querySelector('.lab'), val: g.querySelector('.val'), total: !!r.total, dec: !inc && !r.total };
      return els[r.k];
    };
    const applyRow = (k, rec) => {
      const e = els[k]; if (!e) return;
      e.g.setAttribute('transform', 'translate(0,' + rec.y.toFixed(2) + ')'); e.g.style.opacity = rec.op;
      e.hit.setAttribute('y', (-rec.rh / 2 + 1).toFixed(2)); e.hit.setAttribute('width', W); e.hit.setAttribute('height', Math.max(2, rec.rh - 2).toFixed(2));
      if (e.dec) { e.bar.setAttribute('x', (rec.x + 0.75).toFixed(2)); e.bar.setAttribute('y', (-rec.h / 2 + 0.75).toFixed(2)); e.bar.setAttribute('width', Math.max(1, rec.w - 1.5).toFixed(2)); e.bar.setAttribute('height', Math.max(1, rec.h - 1.5).toFixed(2)); }
      else { e.bar.setAttribute('x', rec.x.toFixed(2)); e.bar.setAttribute('y', (-rec.h / 2).toFixed(2)); e.bar.setAttribute('width', Math.max(1, rec.w).toFixed(2)); e.bar.setAttribute('height', rec.h.toFixed(2)); }
      if (e.tk) e.tk.setAttribute('d', 'M' + (rec.x + 5).toFixed(1) + ' ' + (-rec.h / 2 - 2).toFixed(1) + ' l-4 ' + (rec.h + 4).toFixed(1) + ' M' + (rec.x + 9).toFixed(1) + ' ' + (-rec.h / 2 - 2).toFixed(1) + ' l-4 ' + (rec.h + 4).toFixed(1));
    };
    const html = (r) => {
      const L = curL;
      if (r.total) return '<b>' + AZ.esc(openReg ? openReg + ', ' + r.label : r.label) + ', ' + span + '</b>' + AZ.row('Sales', AZ.money(r.to, 2), '#FFFFFF') + (r.k === '__c' ? AZ.row('vs ' + (ly - 1), signed(L.net, 2) + ' (' + pctS(L.totPrev ? L.net / L.totPrev : null) + ')') : '');
      const o = r.o;
      return '<b>' + AZ.esc(o.g) + (openReg ? ', ' + AZ.esc(openReg) : '') + '</b>' + AZ.row(ly - 1 + ' YTD', AZ.money(o.prev, 2), AZ.T.slate[3]) + AZ.row(ly + ' YTD', AZ.money(o.cur, 2), '#FFFFFF')
        + AZ.row('Change', signed(o.d, 2) + ' (' + pctS(o.prev ? o.d / o.prev : null) + ')') + (L.net ? AZ.row('Share of ' + (openReg ? openReg + ' ' : '') + 'net change', AZ.pct(o.d / L.net, 0)) : '')
        + (openReg ? '' : AZ.row('States', String(o.kids.length)));
    };

    // ---- headings ---------------------------------------------------------------------------------
    const head = (L, fade) => {
      titleEl.textContent = openReg ? 'YTD sales in ' + openReg + ' by state, ' + span + ', ' + ly + ' vs ' + (ly - 1) : 'YTD sales by region, ' + span + ', ' + ly + ' vs ' + (ly - 1);
      const steps = L.src, net = L.net, big = steps.reduce((b, o) => (Math.abs(o.d) > Math.abs(b.d) ? o : b), steps[0]);
      const who = openReg ? openReg : 'All regions';
      let line;
      if (steps.length === 1) line = '<b>' + AZ.esc(big.g) + '</b> <span class="' + cls(big.d) + '">' + signed(big.d) + '</span> (' + pctS(big.prev ? big.d / big.prev : null) + ') on the same quarters a year earlier';
      else line = '<b>' + AZ.esc(big.g) + '</b> moved most: <span class="' + cls(big.d) + '">' + signed(big.d) + '</span> (' + pctS(big.prev ? big.d / big.prev : null) + '). ' + AZ.esc(who) + ': <span class="' + cls(net) + '">' + signed(net) + '</span> (' + pctS(L.totPrev ? net / L.totPrev : null) + ')';
      lineEl.innerHTML = line;
      crumbEl.innerHTML = openReg ? AZ.crumbs(['All regions', openReg]) + '<button type="button" class="br-back">Back</button>' : '<span class="br-hint">Click a region to open its states</span>';
      if (openReg) { AZ.wireCrumbs(crumbEl, () => goTo(null)); crumbEl.querySelector('.br-back').addEventListener('click', () => goTo(null)); }
      capEl.textContent = 'Axis starts at ' + AZ.money(L.lo, 1) + '; total bars are cut.' + capNote;
      clear.style.visibility = sel == null ? 'hidden' : 'visible';
      if (fade) { flash(titleEl); flash(lineEl); flash(crumbEl); }
    };

    // ---- the morph ----------------------------------------------------------------------------------
    let curL = null, cur = null, cancelT = null, leaving = [], conns = [];
    const lerpRec = (a, b, k) => ({ y: AZ.lerp(a.y, b.y, k), h: AZ.lerp(a.h, b.h, k), x: AZ.lerp(a.x, b.x, k), w: AZ.lerp(a.w, b.w, k), ex: AZ.lerp(a.ex, b.ex, k), rh: AZ.lerp(a.rh, b.rh, k), op: AZ.lerp(a.op, b.op, k) });
    const update = (animate, ms) => {
      if (cancelT) { cancelT(); cancelT = null; }
      leaving.forEach((k) => { if (els[k]) { els[k].g.remove(); delete els[k]; } }); leaving = [];
      const L = geoOf(layoutFor(openReg)), prev = animate ? cur : null;
      const prevReg = curL ? curL.reg : undefined;
      curL = L;
      const start = {};
      L.R.forEach((r) => {
        const tg = L.G[r.k];
        let s = null;
        if (prev && prev[r.k]) s = Object.assign({}, prev[r.k]);
        else if (prev && prevReg === null && openReg && prev[openReg]) s = Object.assign({}, prev[openReg], { op: 1 });
        else if (prev && prevReg && openReg === null) {
          const kids = Object.keys(prev).filter((k) => k.indexOf('st:') === 0);
          const kr = RG.get(prevReg);
          if (r.k === prevReg && kids.length) {
            const yy = kids.map((k) => prev[k].y), xa = Math.min.apply(null, kids.map((k) => prev[k].x)), xb = Math.max.apply(null, kids.map((k) => prev[k].x + prev[k].w));
            s = { y: yy.reduce((a, b) => a + b, 0) / yy.length, h: prev[kids[0]].h, x: xa, w: xb - xa, ex: prev[kids[kids.length - 1]].ex, rh: prev[kids[0]].rh, op: 1 };
          }
        }
        if (!s) s = Object.assign({}, tg, { op: prev ? 0 : tg.op });
        if (!prev) s = Object.assign({}, tg);
        start[r.k] = s;
        if (!els[r.k]) mkRow(r);
        else if (!els[r.k].total) { /* reused non-total key keeps its element */ }
        if (els[r.k].total) { els[r.k].val.textContent = AZ.money(r.to, 1); }
      });
      // rows that go away
      const gone = prev ? Object.keys(prev).filter((k) => !L.G[k]) : [];
      const fadeKeys = [];
      gone.forEach((k) => {
        const swallowed = (openReg && k === openReg) || (prevReg && openReg === null && k.indexOf('st:') === 0);
        if (swallowed) { if (els[k]) { els[k].g.remove(); delete els[k]; } } else fadeKeys.push(k);
      });
      leaving = fadeKeys.slice();
      // connectors: one per gap between target rows
      connG.innerHTML = ''; conns = [];
      for (let i = 0; i < L.R.length - 1; i++) { const ln = document.createElementNS(NS, 'line'); ln.setAttribute('stroke', AZ.T.slate[3]); ln.setAttribute('stroke-width', 1); ln.setAttribute('stroke-dasharray', '2 2'); connG.appendChild(ln); conns.push(ln); }
      cur = {}; L.R.forEach((r) => { cur[r.k] = Object.assign({}, start[r.k]); });
      const fromFade = {}; fadeKeys.forEach((k) => { fromFade[k] = Object.assign({}, prev[k]); });
      const levelChange = prevReg !== undefined && prevReg !== openReg && animate;
      const frame = (k) => {
        L.R.forEach((r) => { const rec = lerpRec(start[r.k], L.G[r.k], k); cur[r.k] = rec; applyRow(r.k, rec); });
        fadeKeys.forEach((key) => { const f = fromFade[key]; applyRow(key, Object.assign({}, f, { op: f.op * (1 - k) })); });
        conns.forEach((ln, i) => {
          const a = cur[L.R[i].k], b = cur[L.R[i + 1].k], cx = a.ex;
          ln.setAttribute('x1', cx); ln.setAttribute('x2', cx); ln.setAttribute('y1', a.y + a.h / 2); ln.setAttribute('y2', b.y - b.h / 2);
          ln.setAttribute('opacity', levelChange ? k : 1);
        });
      };
      cancelT = AZ.tween(animate ? (ms || 500) : 0, frame, () => {
        cancelT = null;
        leaving.forEach((k) => { if (els[k]) { els[k].g.remove(); delete els[k]; } }); leaving = [];
      }, AZ.EASE.inOut);
      // rows keep tab order from top to bottom
      L.R.forEach((r) => rowG.appendChild(els[r.k].g));
    };

    const activate = (k) => {
      const L = curL, r = L.R.find((x) => x.k === k);
      if (!r) return;
      if (!r.total && !openReg) { goTo(r.k); return; }
      sel = sel === k ? null : k; head(curL, false); update(true, 260);
    };
    const goTo = (reg) => {
      if (reg === openReg) return;
      openReg = reg; sel = null; tip.hide();
      update(true, 520); head(curL, true);
    };
    clear.addEventListener('click', () => { sel = null; head(curL, false); update(true, 260); });
    const onKey = (e) => { if (e.key !== 'Escape') return; if (openReg) { e.preventDefault(); goTo(null); } else if (sel != null) { e.preventDefault(); sel = null; head(curL, false); update(true, 260); } };
    document.addEventListener('keydown', onKey);

    update(false); head(curL, false);
    return () => { if (cancelT) cancelT(); document.removeEventListener('keydown', onKey); };
  }
});
