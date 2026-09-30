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

// Search: [sales] [state]
// Hex-tile cartogram: one equal-sized hex per US state at a fixed, pseudo-geographic position (layout idea from
// examples/State-hex-cartogram, rebuilt on the board core). States with sales are filled on the slate ramp by
// sales rank (the totals are very skewed, so rank keeps the middle readable); states without sales are outlines.
// Interactions: Sales / Share of total toggle changes the figure shown; hover for the numbers; click a hex to pin it.
const GRID = {
  AK: [0, 0], ME: [10, 0], VT: [9, 1], NH: [10, 1],
  WA: [0, 2], ID: [1, 2], MT: [2, 2], ND: [3, 2], MN: [4, 2], WI: [5, 2], MI: [6, 2], NY: [8, 2], MA: [9, 2], RI: [10, 2],
  OR: [0, 3], NV: [1, 3], WY: [2, 3], SD: [3, 3], IA: [4, 3], IL: [5, 3], IN: [6, 3], OH: [7, 3], PA: [8, 3], NJ: [9, 3], CT: [10, 3],
  CA: [0, 4], UT: [1, 4], CO: [2, 4], NE: [3, 4], MO: [4, 4], KY: [5, 4], WV: [6, 4], VA: [7, 4], MD: [8, 4], DE: [9, 4],
  AZ: [1, 5], NM: [2, 5], KS: [3, 5], AR: [4, 5], TN: [5, 5], NC: [6, 5], SC: [7, 5], DC: [8, 5],
  OK: [3, 6], LA: [4, 6], MS: [5, 6], AL: [6, 6], GA: [7, 6],
  HI: [0, 7], TX: [3, 7], FL: [7, 7]
};
const NAMES = {
  AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', FL: 'Florida', GA: 'Georgia',
  HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland',
  MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri', MT: 'Montana', NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire',
  NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania',
  RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont', VA: 'Virginia', WA: 'Washington',
  WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming', DC: 'D.C.'
};
const CODE = {};
Object.keys(NAMES).forEach((k) => { CODE[NAMES[k].toLowerCase()] = k; CODE[k.toLowerCase()] = k; });
CODE['district of columbia'] = 'DC';
let mode = 'sales';
let pinned = null;

AZ.boot({
  need: 'sales by state, e.g. [sales] [state]',
  render: async ({ el, rows, schema, w, redraw }) => {
    const tK = AZ.col(schema, /state/i), vK = AZ.col(schema, /sales/i);
    const D = new Map();
    let total = 0, unknown = 0;
    rows.forEach((r) => {
      const c = CODE[String(r[tK]).trim().toLowerCase()], v = AZ.num(r[vK]);
      if (!c) { unknown++; return; }
      D.set(c, (D.get(c) || 0) + v); total += v;
    });
    if (!D.size || total <= 0) {
      AZ.paint(el, '<div class="az-empty"><b>No US states to draw</b><span>The current filter returns no state rows. Search: [sales] [state]</span></div>');
      return;
    }
    const ranked = Array.from(D.keys()).sort((a, b) => D.get(b) - D.get(a));
    const rank = {}; ranked.forEach((k, i) => { rank[k] = i + 1; });
    const n = ranked.length, S = AZ.T.slate;
    const bin = (k) => (n === 1 ? S.length - 1 : Math.min(S.length - 1, Math.round((1 - (rank[k] - 1) / (n - 1)) * (S.length - 1))));
    if (pinned && !D.has(pinned)) pinned = null;
    const shareOf = (k) => D.get(k) / total;
    const fig = (k) => (mode === 'sales' ? AZ.money(D.get(k), 0) : AZ.pct(shareOf(k), 0));
    const top = ranked[0], top5 = ranked.slice(0, 5).reduce((t, k) => t + shareOf(k), 0);
    const t3 = ranked.slice(0, 3).map((k) => AZ.esc(NAMES[k]) + ' ' + AZ.pct(shareOf(k), 1)).join(', ');
    const line = n === 1
      ? '<b>' + AZ.esc(NAMES[top]) + '</b> is the only state in the current filter: ' + AZ.money(D.get(top), 1) + '.'
      : mode === 'sales'
        ? '<b>' + AZ.esc(NAMES[top]) + '</b> leads with ' + AZ.money(D.get(top), 1) + '. ' + n + ' of ' + Object.keys(GRID).length + ' states have sales; the top ' + Math.min(5, n) + ' hold ' + AZ.pct(top5, 0) + '.'
        : 'Largest shares of total sales: <b>' + t3 + '</b>. ' + n + ' of ' + Object.keys(GRID).length + ' states have sales.';

    el.innerHTML =
      '<div class="hx-top"><div class="hx-title">Sales by state, hex map</div><div class="hx-seg" role="group" aria-label="Measure"><button type="button" data-m="sales" class="' + (mode === 'sales' ? 'on' : '') + '">Sales</button><button type="button" data-m="share" class="' + (mode === 'share' ? 'on' : '') + '">Share of total</button></div></div>'
      + '<div class="hx-line">' + line + '</div>'
      + '<div class="hx-map" id="hx-map"></div>'
      + '<div class="hx-key"><span>Rank: low</span><span class="hx-ramp">' + S.map((c) => '<i style="background:' + c + '"></i>').join('') + '</span><span>high</span><span class="hx-none"></span><span>No sales</span></div>'
      + '<div class="hx-read" id="hx-read"></div>';
    el.querySelectorAll('.hx-seg button').forEach((b) => b.addEventListener('click', () => { mode = b.getAttribute('data-m'); redraw(); }));

    const map = document.getElementById('hx-map'), read = document.getElementById('hx-read');
    const W = Math.max(160, map.clientWidth), H = Math.max(120, map.clientHeight);
    const wd = Math.min(W / 11.5, H / 7.2), R = wd / Math.sqrt(3), ox = (W - wd * 11.5) / 2 + wd / 2, oy = (H - wd * 7.2) / 2 + R;
    const showVal = wd >= 46, fs = 11;
    const pts = (cx, cy, r) => [0, 1, 2, 3, 4, 5].map((i) => { const a = Math.PI / 180 * (60 * i - 30); return (cx + r * Math.cos(a)).toFixed(1) + ',' + (cy + r * Math.sin(a)).toFixed(1); }).join(' ');
    let s = '';
    Object.keys(GRID).forEach((k) => {
      const g = GRID[k], cx = ox + g[0] * wd + (g[1] % 2 ? wd / 2 : 0), cy = oy + g[1] * 1.5 * R, has = D.has(k);
      const fill = has ? S[bin(k)] : 'transparent', tc = has ? (bin(k) >= 4 ? '#fff' : AZ.T.ink) : AZ.T.muted;
      s += '<g class="hx-h' + (has ? ' has' : '') + '" data-k="' + k + '"' + (has ? ' tabindex="0" role="button" aria-label="' + AZ.esc(NAMES[k] + ' ' + fig(k)) + '"' : '') + '>'
        + '<polygon points="' + pts(cx, cy, R * 0.96) + '" fill="' + fill + '" stroke="' + (has ? '#fff' : AZ.T.grid) + '" stroke-width="' + (has ? 1.5 : 1) + '"' + (has ? '' : ' stroke-dasharray="3 2"') + '/>'
        + '<text class="hx-t" x="' + cx.toFixed(1) + '" y="' + (cy + (has && showVal ? -1 : 4)).toFixed(1) + '" font-size="' + fs + '" font-weight="' + (has ? 600 : 400) + '" fill="' + tc + '">' + k + '</text>'
        + (has && showVal ? '<text class="hx-t" x="' + cx.toFixed(1) + '" y="' + (cy + 12).toFixed(1) + '" font-size="11" fill="' + tc + '">' + AZ.esc(fig(k)) + '</text>' : '')
        + '</g>';
    });
    map.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '">' + s + '</svg>';

    const hs = Array.from(map.querySelectorAll('.hx-h.has'));
    const paintRead = () => {
      if (!pinned) { read.innerHTML = '<div>Click a state to pin it.' + (unknown ? ' ' + unknown + ' row(s) skipped: state not recognised.' : '') + '</div>'; return; }
      read.innerHTML = '<div><b>' + AZ.esc(NAMES[pinned]) + '</b>: ' + (mode === 'sales' ? AZ.money(D.get(pinned), 1) + ', ' + AZ.pct(shareOf(pinned), 1) + ' of sales' : AZ.pct(shareOf(pinned), 1) + ' of sales, ' + AZ.money(D.get(pinned), 1)) + ', rank ' + rank[pinned] + ' of ' + n + '</div><button type="button" class="hx-x" id="hx-x">Unpin</button>';
      document.getElementById('hx-x').addEventListener('click', () => { pinned = null; paint(); });
    };
    const paint = () => {
      hs.forEach((g) => { const k = g.getAttribute('data-k'); g.classList.toggle('pin', pinned === k); g.classList.toggle('dim', !!pinned && pinned !== k); if (pinned === k) g.parentNode.appendChild(g); });
      paintRead();
    };
    paint();
    const tip = AZ.tip(el), pick = (k) => { pinned = pinned === k ? null : k; paint(); };
    Array.from(map.querySelectorAll('.hx-h:not(.has)')).forEach((g) => {
      const k = g.getAttribute('data-k');
      g.addEventListener('mousemove', (e) => { const b = el.getBoundingClientRect(); tip.show('<b>' + AZ.esc(NAMES[k]) + '</b>' + AZ.row('Sales', 'none in this search'), e.clientX - b.left, e.clientY - b.top); });
      g.addEventListener('mouseleave', () => tip.hide());
    });
    hs.forEach((g) => {
      const k = g.getAttribute('data-k');
      g.addEventListener('mousemove', (e) => {
        const b = el.getBoundingClientRect();
        tip.show('<b>' + AZ.esc(NAMES[k]) + '</b>' + (mode === 'sales' ? AZ.row('Sales', AZ.money(D.get(k), 2), '#FFFFFF') + AZ.row('Share of total', AZ.pct(shareOf(k), 1)) : AZ.row('Share of total', AZ.pct(shareOf(k), 1), '#FFFFFF') + AZ.row('Sales', AZ.money(D.get(k), 2))) + AZ.row('Rank', rank[k] + ' of ' + n), e.clientX - b.left, e.clientY - b.top);
      });
      g.addEventListener('mouseleave', () => tip.hide());
      g.addEventListener('click', () => pick(k));
      g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(k); } });
    });
  }
});
