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

// Search: [sales] [store] [date].quarterly
// Dumbbell per store: the same quarters last year (grey) against this year (ink). The latest quarter in the data sets
// the window: every quarter of that year up to it, against the same quarters a year earlier.
// Interactions: Sort toggle (rows glide to their new place); hover a row; click a row to expand it in place into its
// quarterly line (this year solid, last year dashed slate); click again, Unpin or Escape collapses; the list scrolls.
let sortBy = 'change';
let pinned = null;

AZ.boot({
  need: 'sales by store and quarter, e.g. [sales] [store] [date].quarterly',
  render: async ({ el, rows, schema, w }) => {
    const sK = AZ.col(schema, /store/i), dK = AZ.col(schema, /date|quarter/i), vK = AZ.col(schema, /sales/i);
    const M = rows.map((r) => ({ s: String(r[sK]), t: AZ.ms(r[dK]), v: AZ.num(r[vK]) })).filter((r) => isFinite(r.t));
    if (!M.length) throw new Error('No quarters in the result');
    const last = Math.max.apply(null, M.map((r) => r.t)), ly = AZ.year(last), lq = Math.floor(new Date(last).getUTCMonth() / 3);
    const G = new Map(), QV = new Map();
    const qCur = new Set(), qPrev = new Set();
    M.forEach((r) => {
      const d = new Date(r.t), y = d.getUTCFullYear(), q = Math.floor(d.getUTCMonth() / 3);
      if (y === ly || y === ly - 1) {
        if (!QV.has(r.s)) QV.set(r.s, {});
        const z = QV.get(r.s); z[y + ':' + q] = (z[y + ':' + q] || 0) + r.v;
      }
      if (q > lq || (y !== ly && y !== ly - 1)) return;
      if (!G.has(r.s)) G.set(r.s, { s: r.s, cur: 0, prev: 0, nc: 0, np: 0 });
      const o = G.get(r.s);
      if (y === ly) { o.cur += r.v; o.nc++; qCur.add(q); } else { o.prev += r.v; o.np++; qPrev.add(q); }
    });
    const all = Array.from(G.values()).filter((o) => o.prev > 0 && o.cur > 0);
    if (!all.length) {
      AZ.paint(el, '<div class="az-empty"><b>No year-on-year comparison</b><span>The current filter has no stores with sales in both ' + (ly - 1) + ' and ' + ly + '. Search: [sales] [store] [date].quarterly</span></div>');
      return;
    }
    all.forEach((o) => { o.pct = o.cur / o.prev - 1; });
    const span = lq === 0 ? 'Q1' : 'Q1 to Q' + (lq + 1);
    const sorters = {
      change: (a, b) => b.pct - a.pct,
      size: (a, b) => b.cur - a.cur,
      name: (a, b) => (a.s < b.s ? -1 : a.s > b.s ? 1 : 0)
    };
    if (pinned && !all.some((o) => o.s === pinned)) pinned = null;
    const up = all.filter((o) => o.pct >= 0).length;
    const best = all.reduce((b, o) => (o.pct > b.pct ? o : b), all[0]);
    const sp = (x) => (x > 0 ? '+' : x < 0 ? '-' : '') + (Math.abs(x) * 100).toFixed(1) + '%';
    const line = all.length === 1
      ? '<b>' + AZ.esc(best.s) + '</b> ' + sp(best.pct) + ' on the same quarters a year earlier.'
      : '<b>' + up + ' of ' + all.length + '</b> stores are up; best is <b>' + AZ.esc(best.s) + '</b> at ' + sp(best.pct) + '.';
    const comparable = qCur.size === qPrev.size;

    el.innerHTML =
      '<div class="db-top"><div class="db-title">Sales by store</div><div class="db-seg" role="group" aria-label="Sort">'
      + ['change', 'size', 'name'].map((k) => '<button type="button" data-s="' + k + '" class="' + (sortBy === k ? 'on' : '') + '">' + k.charAt(0).toUpperCase() + k.slice(1) + '</button>').join('') + '</div></div>'
      + '<div class="db-line">' + span + ' ' + ly + ' vs ' + (ly - 1) + ': ' + line + '</div>'
      + '<div class="db-axis" id="db-axis"></div>'
      + '<div class="db-scroll" id="db-scroll"></div>'
      + '<div class="db-key" id="db-key"></div>';

    const box = document.getElementById('db-scroll'), axis = document.getElementById('db-axis'), read = document.getElementById('db-key');
    const RH = 28, EH = 112, labW = w < 420 ? 146 : 160, pctW = 48, gap = 10;
    const W = Math.max(200, box.clientWidth - 2), x0 = labW + gap, x1 = W - pctW - gap;
    const vals = all.reduce((a, o) => a.concat([o.cur, o.prev]), []);
    let lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    const pad = (hi - lo || hi * 0.1) * 0.08; lo -= pad; hi += pad;
    const sx = (v) => x0 + (v - lo) / (hi - lo) * (x1 - x0);
    const step = (() => { const raw = (hi - lo) / 4, p = Math.pow(10, Math.floor(Math.log10(raw))); return [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw) || raw; })();
    const ticks = []; for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t);
    const tickTxt = (t) => AZ.money(t, step >= 1e6 ? (step % 1e6 ? 1 : 0) : (step % 1e5 ? 2 : 1));
    axis.innerHTML = '<svg viewBox="0 0 ' + W + ' 16" preserveAspectRatio="none" width="100%" height="16">' + ticks.map((t) => '<text x="' + sx(t).toFixed(1) + '" y="12" text-anchor="middle" font-size="11" fill="' + AZ.T.muted + '">' + AZ.esc(tickTxt(t)) + '</text>').join('') + '</svg>';

    const tipBox = document.createElement('div'); tipBox.className = 'db-tipbox'; tipBox.style.position = 'absolute'; el.style.position = 'relative'; el.appendChild(tipBox);
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg'); svg.setAttribute('width', W); box.appendChild(svg);
    const grid = document.createElementNS(NS, 'g'); svg.appendChild(grid);
    grid.innerHTML = ticks.map((t) => '<line x1="' + sx(t).toFixed(1) + '" x2="' + sx(t).toFixed(1) + '" y1="0" y2="1" stroke="' + AZ.T.grid + '" stroke-width="1"/>').join('');
    const gridLines = Array.from(grid.querySelectorAll('line'));
    const clip = (str, max) => (str.length > max ? str.slice(0, max - 1) + '...' : str);
    const maxCh = Math.floor(labW / 6.1);
    const initial = all.slice().sort(sorters[sortBy]);
    const R = {}; // store -> { o, g, head, rec: {y, ext}, panel }
    initial.forEach((o, i) => {
      const cy = RH / 2, a = sx(o.prev), b = sx(o.cur), col = o.pct >= 0 ? AZ.T.good : AZ.T.bad;
      const g = document.createElementNS(NS, 'g');
      g.setAttribute('class', 'db-row'); g.setAttribute('data-s', o.s); g.setAttribute('tabindex', 0); g.setAttribute('role', 'button');
      g.setAttribute('aria-label', o.s + ' ' + sp(o.pct) + ', open quarterly line');
      g.innerHTML = '<g class="db-head">'
        + '<rect class="bg" x="0" y="1" width="' + W + '" height="' + (RH - 2) + '" rx="6"/>'
        + '<text x="6" y="' + (cy + 4) + '" font-size="12" fill="' + AZ.T.ink + '">' + AZ.esc(clip(o.s, maxCh)) + '</text>'
        + '<line x1="' + a.toFixed(1) + '" x2="' + b.toFixed(1) + '" y1="' + cy + '" y2="' + cy + '" stroke="' + AZ.T.slate[3] + '" stroke-width="3" stroke-linecap="round"/>'
        + '<circle cx="' + a.toFixed(1) + '" cy="' + cy + '" r="4.5" fill="' + AZ.T.slate[3] + '"/>'
        + '<circle cx="' + b.toFixed(1) + '" cy="' + cy + '" r="5" fill="' + AZ.T.ink + '"/>'
        + '<text x="' + (W - 6) + '" y="' + (cy + 4) + '" text-anchor="end" font-size="12" font-weight="600" fill="' + col + '">' + sp(o.pct) + '</text></g>';
      svg.appendChild(g);
      R[o.s] = { o, g, head: g.querySelector('.db-head'), rec: { y: i * RH, ext: 0 }, panel: null, id: i };
    });

    // ---- the expanded panel: this year against last year, by quarter ------------------------
    const qv = (s, y, q) => { const z = QV.get(s); return z && z[y + ':' + q] != null ? z[y + ':' + q] : null; };
    const narrow = x1 - x0 < 150;
    const px0 = narrow ? 30 : x0 + 14, px1 = narrow ? W - 30 : x1 - 14, pw = px1 - px0;
    const qx = (q) => px0 + q * pw / 3;
    function panelFor(r) {
      const s = r.o.s, cur = [], prv = [];
      for (let q = 0; q < 4; q++) { cur.push(q <= lq ? qv(s, ly, q) : null); prv.push(qv(s, ly - 1, q)); }
      const vs = cur.concat(prv).filter((v) => v != null);
      let a = Math.min.apply(null, vs), b = Math.max.apply(null, vs); const pd = (b - a || b * 0.1) * 0.18; a -= pd; b += pd;
      const top = RH + (narrow ? 44 : 24), bot = RH + EH - 24, sy = (v) => bot - (v - a) / (b - a) * (bot - top);
      const path = (arr) => { let d = '', pen = false; arr.forEach((v, q) => { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + qx(q).toFixed(1) + ' ' + sy(v).toFixed(1); pen = true; }); return d; };
      const dots = (arr, fill, stroke, rad) => arr.map((v, q) => (v == null ? '' : '<circle cx="' + qx(q).toFixed(1) + '" cy="' + sy(v).toFixed(1) + '" r="' + rad + '" fill="' + fill + '" stroke="' + stroke + '" stroke-width="2"/>')).join('');
      const labels = cur.map((v, q) => (v == null ? '' : '<text x="' + qx(q).toFixed(1) + '" y="' + (sy(v) - 9).toFixed(1) + '" text-anchor="middle" font-size="11" fill="' + AZ.T.ink2 + '">' + AZ.esc(AZ.money(v, 1)) + '</text>')).join('');
      const xl = [0, 1, 2, 3].map((q) => '<text x="' + qx(q).toFixed(1) + '" y="' + (RH + EH - 8) + '" text-anchor="middle" font-size="11" fill="' + AZ.T.muted + '">Q' + (q + 1) + '</text>').join('');
      const cid = 'dbc' + r.id;
      const p = document.createElementNS(NS, 'g'); p.setAttribute('class', 'db-panel');
      p.innerHTML = '<clipPath id="' + cid + '"><rect x="' + (px0 - 14) + '" y="' + RH + '" width="0" height="' + EH + '"/></clipPath>'
        + '<rect class="pbg" x="0" y="' + (RH + 2) + '" width="' + W + '" height="' + (EH - 6) + '" rx="6"/>'
        + (narrow
          ? '<line x1="8" x2="24" y1="' + (RH + 16) + '" y2="' + (RH + 16) + '" stroke="' + AZ.T.ink + '" stroke-width="2.5"/><text x="29" y="' + (RH + 20) + '" font-size="11" fill="' + AZ.T.ink2 + '">' + ly + '</text>'
            + '<line x1="70" x2="86" y1="' + (RH + 16) + '" y2="' + (RH + 16) + '" stroke="' + AZ.T.slate[3] + '" stroke-width="2" stroke-dasharray="4 3"/><text x="91" y="' + (RH + 20) + '" font-size="11" fill="' + AZ.T.ink2 + '">' + (ly - 1) + '</text>'
          : '<text x="6" y="' + (RH + 20) + '" font-size="11" fill="' + AZ.T.ink2 + '">Quarterly sales</text>'
            + '<line x1="6" x2="24" y1="' + (RH + 38) + '" y2="' + (RH + 38) + '" stroke="' + AZ.T.ink + '" stroke-width="2.5"/><text x="30" y="' + (RH + 42) + '" font-size="11" fill="' + AZ.T.ink2 + '">' + ly + '</text>'
            + '<line x1="6" x2="24" y1="' + (RH + 54) + '" y2="' + (RH + 54) + '" stroke="' + AZ.T.slate[3] + '" stroke-width="2" stroke-dasharray="4 3"/><text x="30" y="' + (RH + 58) + '" font-size="11" fill="' + AZ.T.ink2 + '">' + (ly - 1) + '</text>'
            + '<text x="6" y="' + (RH + 78) + '" font-size="11" fill="' + AZ.T.muted + '">Axis does not</text><text x="6" y="' + (RH + 91) + '" font-size="11" fill="' + AZ.T.muted + '">start at zero</text>')
        + xl
        + '<g clip-path="url(#' + cid + ')">'
        + '<path d="' + path(prv) + '" fill="none" stroke="' + AZ.T.slate[3] + '" stroke-width="2" stroke-dasharray="5 4" stroke-linecap="round"/>' + dots(prv, '#fff', AZ.T.slate[3], 3.5)
        + '<path d="' + path(cur) + '" fill="none" stroke="' + AZ.T.ink + '" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>' + dots(cur, AZ.T.ink, '#fff', 4.5) + labels
        + '</g>';
      r.g.appendChild(p);
      r.panel = { g: p, clip: p.querySelector('clipPath rect'), sy, cur, prv };
      p.addEventListener('mousemove', (e) => {
        e.stopPropagation();
        const bx = el.getBoundingClientRect(), pr = svg.getBoundingClientRect(), x = e.clientX - pr.left;
        let q = Math.max(0, Math.min(3, Math.round((x - px0) / (pw / 3))));
        const c = cur[q], v = prv[q];
        let h = '<b>' + AZ.esc(s) + ' Q' + (q + 1) + '</b>' + (c != null ? AZ.row(ly, AZ.money(c, 2), '#FFFFFF') : AZ.row(ly, 'not yet')) + (v != null ? AZ.row(ly - 1, AZ.money(v, 2), AZ.T.slate[3]) : AZ.row(ly - 1, 'no data'));
        if (c != null && v) h += AZ.row('Change', sp(c / v - 1));
        tip.show(h, e.clientX - bx.left, e.clientY - bx.top);
      });
      p.addEventListener('mouseleave', () => tip.hide());
    }
    const dropPanel = (r) => { if (r.panel) { r.panel.g.remove(); r.panel = null; } };

    // ---- layout + motion ---------------------------------------------------------------------
    let total = initial.length * RH, cancelT = null;
    const targets = () => {
      const order = all.slice().sort(sorters[sortBy]).map((o) => o.s);
      let acc = 0; const T = {};
      order.forEach((s) => { const e = pinned === s ? 1 : 0; T[s] = { y: acc, ext: e }; acc += RH + EH * e; });
      return { T, total: acc };
    };
    const place = (r) => {
      r.g.setAttribute('transform', 'translate(0,' + r.rec.y.toFixed(2) + ')');
      if (r.panel) {
        const e = Math.max(0, Math.min(1, r.rec.ext));
        r.panel.g.style.opacity = Math.min(1, e * 1.6);
        r.panel.clip.setAttribute('width', ((px1 + 14) - (px0 - 14)) * e + 1);
      }
    };
    const setTotal = (t) => { total = t; svg.setAttribute('height', t); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + t); gridLines.forEach((l) => l.setAttribute('y2', t)); };
    const apply = (animate, ms, keepView) => {
      if (cancelT) { cancelT(); cancelT = null; }
      const { T, total: tt } = targets();
      const t0 = total, ks = Object.keys(R);
      const s0 = {}; ks.forEach((k) => { s0[k] = { y: R[k].rec.y, ext: R[k].rec.ext }; });
      ks.forEach((k) => { if (T[k].ext > 0 && !R[k].panel) panelFor(R[k]); });
      const sc0 = box.scrollTop;
      let sc1 = sc0;
      if (pinned && keepView !== false) {
        const yT = T[pinned].y, hgt = RH + EH, vh = box.clientHeight;
        if (yT < sc0) sc1 = yT; else if (yT + hgt > sc0 + vh) sc1 = Math.min(yT, yT + hgt - vh);
        sc1 = Math.max(0, sc1);
      }
      if (tt > t0) setTotal(tt);
      cancelT = AZ.tween(animate ? (ms || 480) : 0, (k) => {
        ks.forEach((key) => { const r = R[key]; r.rec.y = AZ.lerp(s0[key].y, T[key].y, k); r.rec.ext = AZ.lerp(s0[key].ext, T[key].ext, k); place(r); });
        if (sc1 !== sc0) box.scrollTop = AZ.lerp(sc0, sc1, k);
        if (tt <= t0) setTotal(AZ.lerp(t0, tt, k));
      }, () => { cancelT = null; setTotal(tt); ks.forEach((key) => { if (T[key].ext === 0) dropPanel(R[key]); }); }, AZ.EASE.inOut);
    };

    const paint = () => {
      Object.keys(R).forEach((k) => { const g = R[k].g; g.classList.toggle('pin', pinned === k); g.classList.toggle('dim', !!pinned && pinned !== k); g.setAttribute('aria-expanded', pinned === k ? 'true' : 'false'); });
      const o = pinned ? G.get(pinned) : null;
      const dots = '<span><i style="background:' + AZ.T.ink + '"></i>' + ly + '</span><span><i style="background:' + AZ.T.slate[3] + '"></i>' + (ly - 1) + '</span>';
      read.innerHTML = dots + (o
        ? '<span style="color:var(--az-ink2);font-size:12px"><b style="color:var(--az-ink)">' + AZ.esc(o.s) + '</b> ' + AZ.money(o.prev, 2) + ' to ' + AZ.money(o.cur, 2) + ', ' + sp(o.pct) + '</span><button type="button" class="db-x" id="db-x">Collapse</button>'
        : '<span>Sorted by ' + (sortBy === 'change' ? 'change' : sortBy === 'size' ? ly + ' sales' : 'name') + '. Axis starts at ' + AZ.money(lo, 1) + '. Click a store to open its quarters.' + (comparable ? '' : ' Prior year has ' + qPrev.size + ' of ' + qCur.size + ' quarters.') + '</span>');
      const x = document.getElementById('db-x'); if (x) x.addEventListener('click', () => { pinned = null; paint(); apply(true, 420); });
    };
    const tip = AZ.tip(tipBox), pick = (k) => { pinned = pinned === k ? null : k; paint(); apply(true, 480); };
    Object.keys(R).forEach((k) => {
      const r = R[k], o = r.o;
      r.head.addEventListener('mousemove', (e) => {
        const bx = el.getBoundingClientRect(), rank = all.slice().sort(sorters.change).indexOf(o) + 1;
        tip.show('<b>' + AZ.esc(o.s) + '</b>' + AZ.row(ly, AZ.money(o.cur, 2), '#FFFFFF') + AZ.row(ly - 1, AZ.money(o.prev, 2), AZ.T.slate[3]) + AZ.row('Change', (o.cur >= o.prev ? '+' : '-') + AZ.money(Math.abs(o.cur - o.prev), 2) + ' (' + sp(o.pct) + ')') + AZ.row('Rank by change', rank + ' of ' + all.length), e.clientX - bx.left, e.clientY - bx.top);
      });
      r.g.addEventListener('mouseleave', () => tip.hide());
      r.g.addEventListener('click', () => pick(o.s));
      r.g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(o.s); } });
    });
    el.querySelectorAll('.db-seg button').forEach((b) => b.addEventListener('click', () => {
      sortBy = b.getAttribute('data-s');
      el.querySelectorAll('.db-seg button').forEach((n) => n.classList.toggle('on', n === b));
      paint(); apply(true, 520);
    }));
    const onKey = (e) => { if (e.key === 'Escape' && pinned) { e.preventDefault(); pinned = null; paint(); apply(true, 420); } };
    document.addEventListener('keydown', onKey);
    setTotal(targets().total);
    if (pinned) { panelFor(R[pinned]); }
    paint();
    apply(false);
    if (pinned) { const yT = targets().T[pinned].y; box.scrollTop = Math.max(0, yT - Math.max(0, box.clientHeight - RH - EH) / 2); }
    return () => { if (cancelT) cancelT(); document.removeEventListener('keydown', onKey); };
  }
});
